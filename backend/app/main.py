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
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest
from starlette.responses import Response as StarletteResponse
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import sentry_sdk
from sentry_sdk.integrations.asyncio import AsyncioIntegration
from app.config import settings
from app.routes import auth, groups, admin, events
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


MESSAGE_RETENTION_DAYS = 14
CLEANUP_INTERVAL_SECONDS = 3600  # 1 hour
CLEANUP_BATCH_SIZE = 1000


async def cleanup_old_messages() -> None:
    """Background task: delete messages older than 14 days (runs every hour).
    Runs cleanup immediately on startup, then every CLEANUP_INTERVAL_SECONDS.
    Deletes in batches of CLEANUP_BATCH_SIZE to avoid long-running transactions.
    """
    while True:
        try:
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

    # Connect asyncpg pool
    await db.connect()

    # Seed admin_credentials table from env vars on first startup (if table is empty)
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
            logger.info("✓ Seeded admin credentials: phone=%s, username=%s",
                       settings.ADMIN_PHONE, settings.ADMIN_USERNAME)
    except Exception as e:
        # admin_credentials table may not exist yet if migration hasn't run
        # This is expected and will be fixed once the migration is applied
        logger.warning("Could not seed admin_credentials (table may not exist yet): %s", e)

    # Start SSE manager (dedicated LISTEN connection for realtime fan-out)
    await sse_manager.start()

    # Startup: pre-warm a TelegramClient so first send_code is instant
    await telegram_manager.warm_up()
    # Start background message cleanup task
    cleanup_task = asyncio.create_task(cleanup_old_messages())
    yield
    # Shutdown: cancel background tasks first
    cleanup_task.cancel()
    try:
        await cleanup_task
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


# Request correlation ID middleware — generates X-Request-ID for tracing
class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: StarletteRequest, call_next) -> StarletteResponse:
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        request_id_var.set(rid)
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response

app.add_middleware(RequestIdMiddleware)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


# Include routers
app.include_router(auth.router, prefix="/api")
app.include_router(groups.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(events.router, prefix="/api")


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
    from fastapi.responses import JSONResponse
    db_ok = False
    try:
        await db.fetchval("SELECT 1")
        db_ok = True
    except Exception:
        pass

    crawler_health = await crawler_client.get_crawler_health()
    crawler_running = crawler_health.get("running", False) if crawler_health else False
    queue_size = crawler_health.get("queue_size", 0) if crawler_health else 0
    queue_healthy = queue_size < 8000  # 80% of 10K capacity

    all_ok = db_ok and crawler_running and queue_healthy
    status_code = 200 if all_ok else 503
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "healthy" if all_ok else "degraded",
            "database": "connected" if db_ok else "unreachable",
            "crawler": "running" if crawler_running else ("unreachable" if crawler_health is None else "stopped"),
            "queue_healthy": queue_healthy,
        },
    )


@app.get("/metrics")
async def prometheus_metrics():
    """Prometheus-compatible metrics endpoint."""
    from fastapi.responses import PlainTextResponse

    # Sync live values from the crawler before rendering
    crawler_status = await crawler_client.get_crawler_status()
    if crawler_status:
        metrics.messages_total._value = crawler_status.get("messages_received", 0)
        metrics.crawler_groups_active.set(crawler_status.get("groups_count", 0))
        metrics.queue_size.set(crawler_status.get("queue_size", 0))

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
