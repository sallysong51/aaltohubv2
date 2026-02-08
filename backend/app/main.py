"""
Main FastAPI application
"""
import asyncio
import concurrent.futures
import contextvars
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest
from starlette.responses import Response as StarletteResponse
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import sentry_sdk
from sentry_sdk.integrations.asyncio import AsyncioIntegration
from app.config import settings
from app.routes import auth, groups, admin, events, email_linking, telegram_connect
from app.telegram_client import telegram_manager
from app import crawler_client
from app.database import db
from app.sse import sse_manager

# Request correlation ID — set per-request, available via contextvars in any async code
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
from app.metrics import metrics

class _RequestIdFilter(logging.Filter):
    """Inject the current request_id into every log record."""
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get("-")  # type: ignore[attr-defined]
        return True

_rid_filter = _RequestIdFilter()

if settings.ENVIRONMENT != "development":
    # Structured JSON logging for production (parseable by ELK, Datadog, etc.)
    try:
        from pythonjsonlogger import json as jsonlogger
        handler = logging.StreamHandler()
        handler.setFormatter(jsonlogger.JsonFormatter(
            fmt="%(asctime)s %(levelname)s %(name)s %(request_id)s %(message)s",
            rename_fields={"asctime": "timestamp", "levelname": "level", "name": "logger"},
        ))
        handler.addFilter(_rid_filter)
        logging.basicConfig(level=logging.INFO, handlers=[handler])
    except ImportError:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
        logging.getLogger().handlers[0].addFilter(_rid_filter)
else:
    # Human-readable format for development
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s [%(request_id)s]: %(message)s")
    logging.getLogger().handlers[0].addFilter(_rid_filter)

logger = logging.getLogger(__name__)

# Initialize Sentry if DSN is provided
if settings.SENTRY_DSN:
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.ENVIRONMENT,
        traces_sample_rate=1.0 if settings.ENVIRONMENT == "development" else 0.1,
        integrations=[AsyncioIntegration()],
    )


AUTO_RECONNECT_INTERVAL = 30  # seconds between DB reconnection attempts

MESSAGE_RETENTION_DAYS = 15  # 1-day buffer over 14-day historical crawl to prevent edge race
CLEANUP_INTERVAL_SECONDS = 3600  # 1 hour
CLEANUP_BATCH_SIZE = 1000
HEARTBEAT_INTERVAL_SECONDS = 300  # 5 minutes


async def heartbeat_log() -> None:
    """Background task: log system heartbeat every 5 minutes."""
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
        try:
            db_status = "ok" if db.is_connected else "down"
            sse_status = "ok" if sse_manager.is_connected else "down"
            tg_status = "ok" if (telegram_manager._warm_client and telegram_manager._warm_client.is_connected()) else "cold"

            # Crawler health (with timeout to avoid blocking heartbeat)
            crawler_status = "N/A"
            try:
                crawler_health = await asyncio.wait_for(
                    crawler_client.get_crawler_health(), timeout=3.0
                )
                # CrawlerHealth is now a dataclass with status field
                crawler_status = crawler_health.status
            except (asyncio.TimeoutError, Exception):
                crawler_status = "timeout"

            logger.info(
                "[HEARTBEAT] db=%s sse=%s telegram=%s crawler=%s",
                db_status, sse_status, tg_status, crawler_status,
            )

            # Dead letter file check
            try:
                from pathlib import Path
                dl_path = Path(__file__).resolve().parent.parent / "dead-letters.jsonl"
                if dl_path.exists():
                    dl_size_mb = dl_path.stat().st_size / (1024 * 1024)
                    if dl_size_mb > 1:
                        logger.warning("[HEARTBEAT] Dead letter file: %.1f MB", dl_size_mb)
            except Exception:
                pass

        except Exception as e:
            logger.warning("[HEARTBEAT] Error collecting status: %s", e)


async def auto_reconnect_db() -> None:
    """Background task: retry DB connection every 30s while in degraded mode."""
    while True:
        await asyncio.sleep(AUTO_RECONNECT_INTERVAL)
        if db.is_connected:
            continue
        try:
            ok = await db.try_reconnect()
            if ok:
                logger.warning("[AUTO-RECONNECT] Database connection recovered!")
                # Start SSE manager if it wasn't running
                if not sse_manager.is_connected:
                    try:
                        await sse_manager.start()
                        logger.info("[AUTO-RECONNECT] SSE manager started")
                    except Exception as e:
                        logger.warning("[AUTO-RECONNECT] SSE start failed: %s", e)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.debug("[AUTO-RECONNECT] Attempt failed: %s", e)


async def cleanup_old_messages() -> None:
    """Background task: delete messages older than 14 days (runs every hour).
    Runs cleanup immediately on startup, then every CLEANUP_INTERVAL_SECONDS.
    Deletes in batches of CLEANUP_BATCH_SIZE to avoid long-running transactions.
    """
    while True:
        try:
            if not db.is_connected:
                logger.debug("[CLEANUP] Skipping — database pool not available")
                await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
                continue
            threshold = datetime.now(timezone.utc) - timedelta(days=MESSAGE_RETENTION_DAYS)
            total_deleted = 0
            while True:
                result = await db.fetch(
                    """WITH to_delete AS (
                           SELECT id FROM messages WHERE sent_at < $1 LIMIT $2
                       )
                       DELETE FROM messages WHERE id IN (SELECT id FROM to_delete)
                       RETURNING id""",
                    threshold, CLEANUP_BATCH_SIZE,
                )
                batch_count = len(result)
                total_deleted += batch_count
                if batch_count < CLEANUP_BATCH_SIZE:
                    break
                await asyncio.sleep(0.1)  # yield between batches
            if total_deleted > 0:
                logger.info("[CLEANUP] Deleted %d messages older than %d days", total_deleted, MESSAGE_RETENTION_DAYS)

            # Also clean up expired revoked tokens
            try:
                revoked_status = await db.execute(
                    "DELETE FROM revoked_tokens WHERE expires_at < $1",
                    datetime.now(timezone.utc),
                )
                # status string like "DELETE 5"
                revoked_count = int(revoked_status.split()[-1]) if revoked_status else 0
                if revoked_count > 0:
                    logger.info("[CLEANUP] Deleted %d expired revoked tokens", revoked_count)
            except Exception as e:
                logger.warning("[CLEANUP] Revoked token cleanup error: %s", e)

            # Alert on dead letter queue growth
            try:
                dl_count = await db.fetchval(
                    "SELECT COUNT(*) FROM failed_messages WHERE resolved = FALSE"
                ) or 0
                if dl_count > 100:
                    logger.warning(
                        "[DEAD LETTER] %d unresolved failed messages — review /api/admin/failed-messages",
                        dl_count,
                    )
                    if sentry_sdk.is_initialized():
                        sentry_sdk.capture_message(
                            f"Dead letter queue has {dl_count} unresolved entries",
                            level="warning",
                        )
            except Exception as e:
                logger.debug("[CLEANUP] Dead letter check error: %s", e)

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("[CLEANUP] Error: %s", e)
        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Configure a thread pool for remaining sync calls (Storage uploads, Telethon).
    # Reduced from 64 to 16 — asyncpg eliminated the need for DB thread offloading.
    loop = asyncio.get_running_loop()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=16, thread_name_prefix="aaltohub-io")
    loop.set_default_executor(executor)

    # Connect asyncpg pool with retry (handles Supabase wake-up, transient failures)
    db_ok = await db.connect_with_retry()
    if not db_ok:
        try:
            db_host = urlparse(settings.DATABASE_URL).hostname or "???"
        except Exception:
            db_host = "???"
        logger.critical(
            "[STARTUP] Database unreachable (host=%s) — starting in degraded mode. "
            "Health check at /health will report 503. "
            "Check: is your Supabase project paused? Is DATABASE_URL correct?",
            db_host,
        )

    # Seed admin_credentials table from env vars on first startup (if table is empty)
    if db_ok:
        try:
            count = await db.fetchval("SELECT COUNT(*) FROM admin_credentials")
            if count == 0 and (settings.ADMIN_PHONE or settings.ADMIN_USERNAME):
                logger.info("Seeding admin_credentials from environment variables")
                await db.execute(
                    """INSERT INTO admin_credentials (phone_number, username)
                       VALUES ($1, $2)""",
                    settings.ADMIN_PHONE or None,
                    settings.ADMIN_USERNAME or None,
                )
                logger.info("Seeded admin credentials: phone=%s, username=%s",
                           settings.ADMIN_PHONE, settings.ADMIN_USERNAME)
        except Exception as e:
            logger.warning("Could not seed admin_credentials (table may not exist yet): %s", e)

    # Run session migration task (migrate telethon_sessions → telegram_connections)
    if db_ok:
        try:
            from app.session_migration import migrate_linked_user_sessions
            asyncio.create_task(migrate_linked_user_sessions())
        except Exception as e:
            logger.warning("Could not start session migration task: %s", e)

    # Start SSE manager only if DB is available (SSE needs its own pg connection)
    if db_ok:
        await sse_manager.start()
    else:
        logger.warning("[STARTUP] Skipping SSE manager — database unavailable")

    # Startup: pre-warm a TelegramClient so first send_code is instant
    await telegram_manager.warm_up()
    # Start background tasks (cleanup needs DB — skip if unavailable)
    cleanup_task = asyncio.create_task(cleanup_old_messages()) if db_ok else None
    heartbeat_task = asyncio.create_task(heartbeat_log())
    telegram_ping_task = asyncio.create_task(telegram_manager.ping_loop())
    # Auto-reconnect task: always runs, retries DB every 30s if disconnected
    reconnect_task = asyncio.create_task(auto_reconnect_db())

    # Startup diagnostic banner
    def _redact_url(url: str) -> str:
        try:
            p = urlparse(url)
            return f"{p.hostname}:{p.port or 5432}"
        except Exception:
            return "???"

    logger.info("=" * 50)
    logger.info("  AALTOHUB v2 API — STARTUP COMPLETE")
    logger.info("  API: http://%s:%d", settings.API_HOST, settings.API_PORT)
    if db_ok:
        logger.info("  Database: connected (%s)", _redact_url(settings.DATABASE_URL))
    else:
        logger.critical("  Database: DEGRADED — host=%s", _redact_url(settings.DATABASE_URL))
        logger.critical("  ACTION: Fix DATABASE_URL in backend/.env and restart")
    logger.info("  SSE: %s", "listening" if sse_manager.is_connected else "disconnected")
    logger.info("  Telegram: %s", "warm" if telegram_manager._warm_client and telegram_manager._warm_client.is_connected() else "cold")
    logger.info("  Auto-reconnect: enabled (every %ds)", AUTO_RECONNECT_INTERVAL)
    logger.info("  CORS: %s", settings.CORS_ORIGINS)
    logger.info("  Environment: %s", settings.ENVIRONMENT)
    logger.info("=" * 50)

    yield
    # Shutdown: cancel background tasks first
    bg_tasks = [t for t in (cleanup_task, heartbeat_task, telegram_ping_task, reconnect_task) if t is not None]
    for task in bg_tasks:
        task.cancel()
    for task in bg_tasks:
        try:
            await task
        except asyncio.CancelledError:
            pass
    # Close crawler client HTTP connection
    await crawler_client.close()

    # Stop SSE manager (close LISTEN connection)
    await sse_manager.stop()

    # Close asyncpg pool
    await db.close()

    # Shut down thread pool executor — wait briefly for in-flight calls to complete
    executor.shutdown(wait=True, cancel_futures=True)


# Create FastAPI app
app = FastAPI(
    title="AaltoHub v2 API",
    description="Backend API for AaltoHub v2 - Telegram Group Message Crawler",
    version="1.0.0",
    docs_url="/docs" if settings.ENVIRONMENT == "development" else None,
    redoc_url="/redoc" if settings.ENVIRONMENT == "development" else None,
    lifespan=lifespan,
)


# Security headers middleware
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: StarletteRequest, call_next) -> StarletteResponse:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if settings.ENVIRONMENT != "development":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

app.add_middleware(SecurityHeadersMiddleware)


# Degraded mode middleware — blocks /api/* requests when DB is down (Point 3)
# Returns 503 with Korean user-facing message instead of cryptic 500
_DEGRADED_EXEMPT = {"/health", "/metrics", "/"}


class DegradedModeMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: StarletteRequest, call_next) -> StarletteResponse:
        path = request.url.path
        if (
            not db.is_connected
            and path.startswith("/api")
            and not path.startswith("/api/events/stream")
        ):
            return JSONResponse(
                status_code=503,
                content={"detail": "서비스가 일시적으로 사용할 수 없습니다. 잠시 후 다시 시도해주세요."},
            )
        return await call_next(request)


# DegradedModeMiddleware added BEFORE CORSMiddleware so that CORS headers
# are applied to 503 responses (Starlette runs middlewares in reverse add order)
app.add_middleware(DegradedModeMiddleware)


# Request correlation ID middleware — generates X-Request-ID for tracing + HTTP metrics
class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: StarletteRequest, call_next) -> StarletteResponse:
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        request_id_var.set(rid)
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        # Track HTTP request metrics (normalize path to avoid high cardinality)
        path = request.url.path
        if path.startswith("/api/"):
            # Strip IDs from paths: /api/groups/123/messages → /api/groups/:id/messages
            parts = path.split("/")
            normalized = "/".join(":id" if p.isdigit() else p for p in parts)
            metrics.http_requests_total.inc((request.method, normalized, str(response.status_code)))
        return response

app.add_middleware(RequestIdMiddleware)

# CORS middleware — outermost layer, ensures CORS headers on all responses including 503
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


# Include routers
app.include_router(auth.router, prefix="/api")
app.include_router(email_linking.router, prefix="/api")
app.include_router(groups.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(events.router, prefix="/api")
app.include_router(telegram_connect.router, prefix="/api")


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "name": "AaltoHub v2 API",
        "version": "1.0.0",
        "status": "running"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint — returns basic status for load balancers.
    Detailed diagnostics require admin authentication (via /api/admin endpoints)."""
    db_ok = False
    if db.is_connected:
        try:
            await asyncio.wait_for(db.fetchval("SELECT 1"), timeout=5.0)
            db_ok = True
        except Exception:
            pass

    # Timeout prevents health check from hanging if crawler process is unresponsive
    try:
        crawler_health = await asyncio.wait_for(
            crawler_client.get_crawler_health(), timeout=3.0
        )
    except (asyncio.TimeoutError, Exception) as e:
        logger.debug("Health check: crawler health timed out: %s", e)
        crawler_health = crawler_client.CrawlerHealth(
            status="unreachable",
            message="Health check timeout",
        )

    # Extract queue info from crawler details if available
    crawler_running = crawler_health.status in ("healthy", "degraded", "restarting")
    queue_size = crawler_health.details.get("queue_size", 0) if crawler_health.details else 0
    queue_healthy = queue_size < 8000  # 80% of 10K capacity

    sse_ok = sse_manager.is_connected

    all_ok = db_ok and crawler_health.status == "healthy" and queue_healthy and sse_ok
    status_code = 200 if all_ok else 503
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "healthy" if all_ok else "degraded",
            "database_connected": db_ok,
            "environment": settings.ENVIRONMENT,
            "crawler": {
                "status": crawler_health.status,
                "message": crawler_health.message,
                "last_checked": crawler_health.timestamp,
            },
            "queue_healthy": queue_healthy,
            "sse_listener": "connected" if sse_ok else "disconnected",
        },
    )


@app.get("/metrics")
async def prometheus_metrics(request: StarletteRequest):
    """Prometheus-compatible metrics endpoint.
    Protected by bearer token in production (reuses CRAWLER_API_SECRET)."""
    import hmac
    if settings.ENVIRONMENT != "development":
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer ") or not hmac.compare_digest(
            auth[7:], settings.crawler_api_secret
        ):
            return JSONResponse(status_code=401, content={"detail": "Unauthorized"})

    from fastapi.responses import PlainTextResponse

    # Sync live values from the crawler before rendering
    crawler_status = await crawler_client.get_crawler_status()
    if crawler_status:
        metrics.messages_total.set(crawler_status.get("messages_received", 0))
        metrics.crawler_groups_active.set(crawler_status.get("groups_count", 0))
        metrics.queue_size.set(crawler_status.get("queue_size", 0))
    metrics.sse_connections.set(sse_manager.active_connections)

    return PlainTextResponse(
        content=metrics.render(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=settings.ENVIRONMENT == "development"
    )
