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
from uuid import UUID

from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
import sentry_sdk
from sentry_sdk.integrations.asyncio import AsyncioIntegration

from app.config import settings
from app.database import db
from app.live_crawler import live_crawler, CB_RECOVERY_TIMEOUT
from app.event_logger import event_logger
from app.utils.connection_health_tracker import ConnectionHealthTracker
from app.watchdog import CrawlerWatchdog
from app.logging_config import setup_logging

# Track crawler process startup time (for restart detection)
STARTUP_TIMESTAMP = time.time()

# Global ConnectionHealthTracker instance for auto-join feature
_health_tracker: ConnectionHealthTracker | None = None

# Global queue for delayed join requests (when all connections are unhealthy)
# Format: (identifier, user_id, delay_seconds, retry_count)
_join_queue: asyncio.Queue = None  # Initialized in lifespan


def get_health_tracker() -> ConnectionHealthTracker:
    """Get the global ConnectionHealthTracker instance.

    Returns:
        ConnectionHealthTracker instance

    Raises:
        RuntimeError: If tracker not initialized
    """
    if _health_tracker is None:
        raise RuntimeError("ConnectionHealthTracker not initialized")
    return _health_tracker


async def queue_join_request(identifier: str, user_id: int, delay_seconds: int):
    """Add a join request to the queue for later processing.

    Args:
        identifier: Telegram link/username/ID
        user_id: Admin user ID
        delay_seconds: How long to wait before retrying
    """
    global _join_queue
    if _join_queue is None:
        logger.warning("Join queue not initialized, cannot queue request")
        return

    retry_count = 0
    await _join_queue.put((identifier, user_id, delay_seconds, retry_count))
    logger.info(
        f"Queued join request for {identifier} (user {user_id}) "
        f"with {delay_seconds}s delay"
    )

# Initialize centralized logging
setup_logging(settings, service_name="crawler")

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

# Global set to track background tasks (prevents GC of fire-and-forget tasks)
_background_tasks: set[asyncio.Task] = set()


def _safe_create_task(coro, *, name: str | None = None) -> asyncio.Task:
    """Create an asyncio task with automatic exception logging and Sentry reporting.

    Same pattern as live_crawler.py but duplicated here to avoid circular imports.
    """
    task = asyncio.create_task(coro, name=name)
    _background_tasks.add(task)

    def _done_callback(t: asyncio.Task) -> None:
        _background_tasks.discard(t)
        if t.cancelled():
            return
        exc = t.exception()
        if exc:
            task_name = name or t.get_name()
            logger.error(
                "[BACKGROUND-TASK] Task '%s' failed: %s",
                task_name,
                exc,
                exc_info=exc,
            )
            if settings.SENTRY_DSN:
                try:
                    sentry_sdk.capture_exception(
                        exc,
                        extras={
                            "task_name": task_name,
                            "task_id": id(t),
                            "coro_name": coro.__name__ if hasattr(coro, "__name__") else str(coro),
                        },
                    )
                except Exception as sentry_err:
                    logger.warning("[BACKGROUND-TASK] Failed to send to Sentry: %s", sentry_err)

    task.add_done_callback(_done_callback)
    return task


def _verify_internal_token(credentials: HTTPAuthorizationCredentials = Depends(_security)):
    """Verify the internal crawler API secret."""
    import hmac
    if not hmac.compare_digest(credentials.credentials, settings.crawler_api_secret):
        raise HTTPException(status_code=401, detail="Invalid crawler API token")


_AUTO_RECONNECT_INTERVAL = 30  # seconds


async def _auto_reconnect_and_start_crawler() -> None:
    """Background task: retry DB connection and start crawler every 30s while not running."""
    while True:
        await asyncio.sleep(_AUTO_RECONNECT_INTERVAL)
        if live_crawler.running:
            continue
        if not db.is_connected:
            try:
                ok = await db.try_reconnect()
                if not ok:
                    logger.debug("[AUTO-RECONNECT] DB reconnect attempt failed")
                    continue
                logger.warning("[AUTO-RECONNECT] Database connection recovered!")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug("[AUTO-RECONNECT] Attempt failed: %s", e)
                continue
        # DB is connected but crawler is not running — start it
        try:
            logger.info("[AUTO-RECONNECT] Starting crawler...")
            _safe_create_task(live_crawler.start(), name="crawler-restart")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("[AUTO-RECONNECT] Crawler start failed: %s", e)


async def _process_join_queue():
    """Background task: process queued join requests when connections become healthy."""
    global _join_queue, _health_tracker

    while True:
        try:
            # Get next request from queue (blocking)
            identifier, user_id, delay_seconds, retry_count = await _join_queue.get()

            # Wait the specified delay
            await asyncio.sleep(delay_seconds)

            logger.info(
                f"Processing queued join request: {identifier} "
                f"(retry #{retry_count + 1})"
            )

            # Import here to avoid circular dependency
            from app.routes.admin.auto_join import (
                parse_telegram_identifier,
                fetch_active_connections,
                select_best_connection_for_join,
                attempt_join_with_fallback,
            )

            # Re-check if connections are healthy
            try:
                connections = await fetch_active_connections(user_id)

                # Register connections with tracker
                for conn in connections:
                    _health_tracker.register_connection(
                        telegram_user_id=conn["telegram_user_id"],
                        connection_id=UUID(conn["id"]),
                    )

                # Select best connection
                best_conn, wait_time = await select_best_connection_for_join(
                    _health_tracker, connections
                )

                if best_conn is None:
                    # Still all unhealthy - re-queue with exponential backoff
                    new_delay = min(wait_time * 1.5, 1800)  # Max 30 minutes
                    new_retry = retry_count + 1

                    if new_retry < 10:  # Max 10 retries
                        await _join_queue.put((identifier, user_id, new_delay, new_retry))
                        logger.info(
                            f"Re-queued {identifier} with {new_delay}s delay "
                            f"(retry #{new_retry})"
                        )
                    else:
                        logger.warning(
                            f"Dropped {identifier} after {new_retry} retries"
                        )
                        sentry_sdk.capture_message(
                            f"Join request dropped after 10 queue retries",
                            level="warning",
                            extras={
                                "identifier": identifier,
                                "user_id": user_id,
                            },
                        )
                else:
                    # Connection available - attempt join
                    group_info = parse_telegram_identifier(identifier)
                    result = await attempt_join_with_fallback(
                        tracker=_health_tracker,
                        connections=connections,
                        group_info=group_info,
                        user_id=user_id,
                        max_attempts=3,
                    )

                    if result.success:
                        logger.info(
                            f"Queued join succeeded: {identifier} → "
                            f"group {result.group_id}"
                        )
                    else:
                        logger.warning(
                            f"Queued join failed: {identifier} - {result.message}"
                        )

            except Exception as e:
                logger.error(
                    f"Error processing queued join for {identifier}: {e}",
                    exc_info=True,
                )

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Join queue processor error: {e}", exc_info=True)
            await asyncio.sleep(5)  # Brief pause before continuing


async def _sync_flood_wait_to_tracker():
    """Background task: sync FloodWait status from crawler to health tracker every 60s."""
    global _health_tracker
    while True:
        await asyncio.sleep(60)  # Sync every 1 minute
        try:
            if _health_tracker and live_crawler.running:
                flood_status = live_crawler.get_flood_wait_status_for_auto_join()
                _health_tracker.sync_flood_wait_penalties(flood_status)
                logger.debug(f"Synced FloodWait status: {len(flood_status)} entries")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"Failed to sync FloodWait status: {e}")


async def _cleanup_tracker_history():
    """Background task: cleanup old tracker history every 1 hour."""
    global _health_tracker
    while True:
        await asyncio.sleep(3600)  # Cleanup every 1 hour
        try:
            if _health_tracker:
                _health_tracker.cleanup_old_history()
                logger.debug("Cleaned up tracker history")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"Failed to cleanup tracker history: {e}")


def _handle_event_loop_exception(loop, context):
    """Global exception handler for asyncio event loop.

    Prevents unhandled exceptions in background tasks from crashing the loop.
    Logs to both logger and Sentry for visibility.
    """
    exception = context.get("exception")
    message = context.get("message", "Unknown asyncio error")

    # Log with full context
    logger.error(
        "[EVENT-LOOP] Unhandled exception in asyncio: %s",
        message,
        exc_info=exception,
        extra={"asyncio_context": context},
    )

    # Send to Sentry for alerting
    if settings.SENTRY_DSN:
        sentry_sdk.capture_exception(
            exception or Exception(message),
            extras={"asyncio_context": context},
        )

    # Only stop loop for fatal errors (not transient failures)
    if isinstance(exception, (SystemExit, KeyboardInterrupt)):
        logger.critical("[EVENT-LOOP] Fatal error, stopping loop")
        loop.stop()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _health_tracker, _join_queue

    # Thread pool for Storage uploads + Telethon sync calls
    loop = asyncio.get_running_loop()

    # Set global exception handler for the event loop
    loop.set_exception_handler(_handle_event_loop_exception)
    logger.info("[EVENT-LOOP] Global exception handler installed")

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=16, thread_name_prefix="crawler-io")
    loop.set_default_executor(executor)

    # Connect with retry (matches main.py behavior) — keeps process alive if DB is temporarily down
    db_ok = await db.connect_with_retry()

    # Initialize ConnectionHealthTracker for auto-join feature
    _health_tracker = ConnectionHealthTracker()
    logger.info("ConnectionHealthTracker initialized")

    # Initialize join queue
    _join_queue = asyncio.Queue()
    logger.info("Auto-join queue initialized")

    # Start event logger (async background worker for event recording)
    await event_logger.start()
    logger.info("EventLogger started")

    # Phase 34: Initialize systemd watchdog (before crawler starts)
    watchdog = CrawlerWatchdog(live_crawler)
    watchdog_task = _safe_create_task(watchdog.start(), name="systemd-watchdog")
    logger.info("[WATCHDOG] Systemd watchdog initialized")

    if db_ok:
        _safe_create_task(live_crawler.start(), name="crawler-start")
        # Wait briefly for crawler to initialize before notifying systemd
        await asyncio.sleep(1)
        watchdog.notify_ready()
        await event_logger.log_info(
            category="system",
            title="Crawler started",
            message="Live crawler process initialized successfully",
        )
    else:
        logger.critical(
            "[CRAWLER] Database unreachable after retries — crawler will not start. "
            "Auto-reconnect will retry every %ds.", _AUTO_RECONNECT_INTERVAL
        )
        await event_logger.log_error(
            category="database",
            title="Database unreachable at startup",
            message=f"Crawler will not start. Auto-reconnect will retry every {_AUTO_RECONNECT_INTERVAL}s.",
        )

    # Always start auto-reconnect (handles DB-down-at-startup and mid-run crashes)
    reconnect_task = _safe_create_task(_auto_reconnect_and_start_crawler(), name="auto-reconnect")

    # Start background tasks for ConnectionHealthTracker
    flood_sync_task = _safe_create_task(_sync_flood_wait_to_tracker(), name="flood-sync")
    cleanup_task = _safe_create_task(_cleanup_tracker_history(), name="tracker-cleanup")

    # Start queue processor for auto-join
    queue_processor_task = _safe_create_task(_process_join_queue(), name="join-queue-processor")

    yield

    # Cancel all background tasks
    reconnect_task.cancel()
    flood_sync_task.cancel()
    cleanup_task.cancel()
    queue_processor_task.cancel()
    watchdog_task.cancel()

    try:
        await asyncio.gather(
            reconnect_task,
            flood_sync_task,
            cleanup_task,
            queue_processor_task,
            watchdog_task,
            return_exceptions=True,
        )
    except asyncio.CancelledError:
        pass
    if live_crawler.running:
        await live_crawler.stop()

    # Stop event logger and flush pending events
    await event_logger.stop()
    logger.info("EventLogger stopped")

    await db.close()
    executor.shutdown(wait=True, cancel_futures=True)


app = FastAPI(
    title="AaltoHub Crawler Internal API",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)


@app.get("/health")
async def health(request: Request):
    """Deep health check — reports degraded if the crawler is logically broken
    even when the process is still alive (no clients, CB stuck open, queue saturated).
    In production, requires Bearer token to prevent internal state leakage."""
    if settings.is_production:
        import hmac as _hmac
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer ") or not _hmac.compare_digest(auth[7:], settings.crawler_api_secret):
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
    status = live_crawler.get_status()
    from fastapi.responses import JSONResponse

    reasons: list[str] = []
    if not live_crawler.running:
        reasons.append("not_running")
    if not live_crawler.connected:
        reasons.append("not_connected")
    if not live_crawler.clients:
        reasons.append("no_telegram_clients")
    if status.get("waiting_for_admin"):
        reasons.append("no_admin_session")

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

    # Periodic cleanup of completed manual crawl tasks (prevent memory accumulation)
    live_crawler._manual_crawl_tasks = {
        k: v for k, v in live_crawler._manual_crawl_tasks.items() if not v.done()
    }

    ok = len(reasons) == 0
    return JSONResponse(
        status_code=200 if ok else 503,
        content={
            "status": "healthy" if ok else "degraded",
            "reasons": reasons if reasons else None,
            "environment": settings.ENVIRONMENT,
            "startup_timestamp": STARTUP_TIMESTAMP,
            "uptime_seconds": time.time() - STARTUP_TIMESTAMP,
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
    task = _safe_create_task(live_crawler._crawl_historical_for_group(gid), name=f"manual-crawl-{group_id}")
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
    """Drain the batch crawl queue, processing groups one at a time.

    Worker runs until queue is genuinely empty (with grace period).
    """
    live_crawler._batch_crawl_active = True
    consecutive_timeouts = 0
    try:
        while True:
            try:
                gid = await asyncio.wait_for(_batch_crawl_queue.get(), timeout=30.0)
                consecutive_timeouts = 0  # Reset on successful get
            except asyncio.TimeoutError:
                # Only exit if queue is truly empty and we've waited enough
                queue_size = _batch_crawl_queue.qsize()
                consecutive_timeouts += 1

                if queue_size == 0 and consecutive_timeouts >= 2:
                    # Queue empty for 60s (2 × 30s), safe to exit
                    logger.info("[BATCH-CRAWL] Queue empty for 60s, worker exiting")
                    break
                else:
                    logger.warning(
                        "[BATCH-CRAWL] Timeout waiting for next group "
                        f"(queue size: {queue_size}, timeouts: {consecutive_timeouts}/2)"
                    )
                    continue

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
        _batch_crawl_task = _safe_create_task(_batch_crawl_worker(), name="batch-crawl-worker")

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
