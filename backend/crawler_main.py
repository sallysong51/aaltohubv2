"""
Standalone crawler process entry point.

Runs the LiveCrawlerService as an independent FastAPI app on port 8001
(configurable via CRAWLER_API_PORT). Bound to 127.0.0.1 by default —
not exposed to the internet.

Internal control API:
  GET  /health               — crawler health (deep check: clients, circuit breaker, queue)
  GET  /status               — full crawler status dict
  POST /restart              — restart the crawler
  POST /groups/{id}/crawl    — trigger historical crawl for a group
  POST /groups/batch-crawl   — sequential historical crawl for multiple groups

All endpoints require Authorization: Bearer {CRAWLER_API_SECRET}.
"""
import asyncio
import concurrent.futures
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
import sentry_sdk
from sentry_sdk.integrations.asyncio import AsyncioIntegration

from app.config import settings
from app.database import db
from app.live_crawler import live_crawler, CB_RECOVERY_TIMEOUT

# Logging setup (matches main.py pattern)
if settings.ENVIRONMENT != "development":
    try:
        from pythonjsonlogger import json as jsonlogger
        handler = logging.StreamHandler()
        handler.setFormatter(jsonlogger.JsonFormatter(
            fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
            rename_fields={"asctime": "timestamp", "levelname": "level", "name": "logger"},
        ))
        logging.basicConfig(level=logging.INFO, handlers=[handler])
    except ImportError:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
else:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

logger = logging.getLogger(__name__)

# Initialize Sentry if DSN is provided
if settings.SENTRY_DSN:
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.ENVIRONMENT,
        traces_sample_rate=1.0 if settings.ENVIRONMENT == "development" else 0.1,
        integrations=[AsyncioIntegration()],
    )

# Internal auth
_security = HTTPBearer()


def _verify_internal_token(credentials: HTTPAuthorizationCredentials = Depends(_security)):
    """Verify the internal crawler API secret."""
    import hmac
    if not hmac.compare_digest(credentials.credentials, settings.crawler_api_secret):
        raise HTTPException(status_code=401, detail="Invalid crawler API token")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Thread pool for Storage uploads + Telethon sync calls
    loop = asyncio.get_running_loop()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=16, thread_name_prefix="crawler-io")
    loop.set_default_executor(executor)

    await db.connect()
    asyncio.create_task(live_crawler.start())
    yield
    await live_crawler.stop()
    await db.close()
    executor.shutdown(wait=True, cancel_futures=True)


app = FastAPI(
    title="AaltoHub Crawler Internal API",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    """Deep health check — reports degraded if the crawler is logically broken
    even when the process is still alive (no clients, CB stuck open, queue saturated)."""
    status = live_crawler.get_status()
    from fastapi.responses import JSONResponse

    reasons: list[str] = []
    if not live_crawler.running:
        reasons.append("not_running")
    if not live_crawler.connected:
        reasons.append("not_connected")
    if not live_crawler.clients:
        reasons.append("no_telegram_clients")

    # Circuit breaker stuck open for > 5 minutes
    cb = live_crawler._circuit_breaker
    if cb._state == "open" and cb._opened_at > 0:
        open_duration = time.monotonic() - cb._opened_at
        if open_duration > 5 * 60:
            reasons.append(f"circuit_breaker_open_{int(open_duration)}s")

    # Queue saturation (> 80% for any check)
    queue_pct = (live_crawler._msg_queue.qsize() / live_crawler._msg_queue.maxsize * 100) if live_crawler._msg_queue.maxsize else 0
    if queue_pct > 80:
        reasons.append(f"queue_{int(queue_pct)}pct")

    ok = len(reasons) == 0
    return JSONResponse(
        status_code=200 if ok else 503,
        content={
            "status": "healthy" if ok else "degraded",
            "reasons": reasons if reasons else None,
            **status,
        },
    )


@app.get("/status", dependencies=[Depends(_verify_internal_token)])
async def get_status():
    return live_crawler.get_status()


@app.post("/restart", dependencies=[Depends(_verify_internal_token)])
async def restart():
    global _batch_crawl_task
    # Cancel running batch crawl and drain stale queue before restart
    if _batch_crawl_task and not _batch_crawl_task.done():
        _batch_crawl_task.cancel()
        try:
            await _batch_crawl_task
        except asyncio.CancelledError:
            pass
        _batch_crawl_task = None
    _drain_batch_queue()
    _batch_queued_gids.clear()

    await live_crawler.restart()
    return {"success": True, "status": live_crawler.get_status()}


@app.post("/groups/{group_id}/crawl", dependencies=[Depends(_verify_internal_token)])
async def trigger_crawl(group_id: str):
    if not live_crawler.running:
        raise HTTPException(status_code=400, detail="Crawler is not running")

    gid = int(group_id)
    if gid not in live_crawler.group_id_map:
        await live_crawler.refresh_groups()
        await live_crawler._ensure_crawler_status_rows()
        if gid not in live_crawler.group_id_map:
            raise HTTPException(status_code=404, detail="Group not found in crawler")

    # Prevent concurrent crawls of the same group
    existing_task = live_crawler._manual_crawl_tasks.get(group_id)
    if existing_task and not existing_task.done():
        return {"success": True, "message": f"Historical crawl already running for group {group_id}"}

    live_crawler._crawled_groups.discard(gid)
    task = asyncio.create_task(live_crawler._crawl_historical_for_group(gid))
    live_crawler._manual_crawl_tasks[group_id] = task
    # Clean up completed tasks to prevent memory accumulation
    live_crawler._manual_crawl_tasks = {
        k: v for k, v in live_crawler._manual_crawl_tasks.items() if not v.done()
    }
    return {"success": True, "message": f"Historical crawl started for group {group_id}"}


class BatchCrawlRequest(BaseModel):
    group_ids: list[str]


# Batch crawl queue — ensures only ONE sequential crawl task runs at a time.
# New requests append to the queue; the running task drains it.
_batch_crawl_queue: asyncio.Queue[int] = asyncio.Queue(maxsize=500)
_batch_crawl_task: asyncio.Task | None = None


async def _batch_crawl_worker():
    """Drain the batch crawl queue, processing groups one at a time."""
    live_crawler._batch_crawl_active = True
    try:
        while True:
            try:
                gid = await asyncio.wait_for(_batch_crawl_queue.get(), timeout=5.0)
            except asyncio.TimeoutError:
                # No new items for 5 seconds — worker exits cleanly
                break
            if not live_crawler.running:
                _batch_crawl_queue.task_done()
                break
            try:
                live_crawler._crawled_groups.discard(gid)
                title = live_crawler._get_group_title(gid)
                remaining = _batch_crawl_queue.qsize()
                logger.info("[BATCH-CRAWL] Crawling %s (queue: %d remaining)", title, remaining)
                await live_crawler._crawl_historical_for_group(gid)
            except Exception as e:
                logger.error("[BATCH-CRAWL] Error crawling group %s: %s", gid, e)
            finally:
                _batch_crawl_queue.task_done()
    finally:
        live_crawler._batch_crawl_active = False
        _batch_queued_gids.clear()

    logger.info("[BATCH-CRAWL] Worker finished — queue drained")


def _drain_batch_queue() -> None:
    """Clear all pending items from the batch crawl queue (used on restart)."""
    drained = 0
    while not _batch_crawl_queue.empty():
        try:
            _batch_crawl_queue.get_nowait()
            _batch_crawl_queue.task_done()
            drained += 1
        except asyncio.QueueEmpty:
            break
    if drained:
        logger.info("[BATCH-CRAWL] Drained %d stale items from queue on restart", drained)


# Track which group IDs are already in the batch queue (dedup)
_batch_queued_gids: set[int] = set()


@app.post("/groups/batch-crawl", dependencies=[Depends(_verify_internal_token)])
async def trigger_batch_crawl(request: BatchCrawlRequest):
    """Trigger sequential historical crawl for multiple groups.

    Groups are crawled ONE AT A TIME via a shared queue to avoid
    Telegram FloodWaitError. Concurrent requests safely append to queue.
    Returns immediately.
    """
    global _batch_crawl_task

    if not live_crawler.running:
        raise HTTPException(status_code=400, detail="Crawler is not running")

    if not request.group_ids:
        raise HTTPException(status_code=400, detail="No group IDs provided")

    # Always refresh groups when batch-crawl is called — this is typically triggered
    # right after group registration, so we need to pick up new groups immediately
    # for both historical crawl AND live event listening.
    await live_crawler.refresh_groups()
    await live_crawler._ensure_crawler_status_rows()

    int_ids: list[int] = []

    skipped: list[str] = []
    for gid_str in request.group_ids:
        gid = int(gid_str)
        if gid in live_crawler.group_id_map:
            int_ids.append(gid)
        else:
            skipped.append(gid_str)

    if not int_ids:
        raise HTTPException(status_code=404, detail="No valid groups found in crawler")

    # Enqueue all validated IDs (with deduplication)
    for gid in int_ids:
        if gid in _batch_queued_gids:
            skipped.append(str(gid))
            logger.debug("[BATCH-CRAWL] Skipping duplicate group %s (already queued)", gid)
            continue
        try:
            _batch_crawl_queue.put_nowait(gid)
            _batch_queued_gids.add(gid)
        except asyncio.QueueFull:
            skipped.append(str(gid))
            logger.warning("[BATCH-CRAWL] Queue full (maxsize=500), skipping group %s", gid)

    # Start worker if not already running
    if _batch_crawl_task is None or _batch_crawl_task.done():
        _batch_crawl_task = asyncio.create_task(_batch_crawl_worker())

    accepted_ids = [str(g) for g in int_ids if g not in set(int(s) for s in skipped)]
    result: dict = {
        "success": True,
        "message": f"Sequential historical crawl queued for {len(int_ids)} groups",
        "group_ids": accepted_ids,
    }
    if skipped:
        result["skipped_ids"] = skipped
    return result


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "crawler_main:app",
        host="127.0.0.1",
        port=settings.CRAWLER_API_PORT,
        reload=False,
    )
