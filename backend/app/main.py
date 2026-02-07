"""
Main FastAPI application
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import sentry_sdk
from sentry_sdk.integrations.asyncio import AsyncioIntegration
from app.config import settings
from app.routes import auth, groups, admin
from app.telegram_client import telegram_manager
from app.live_crawler import live_crawler

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


MESSAGE_RETENTION_DAYS = 14
CLEANUP_INTERVAL_SECONDS = 3600  # 1 hour


CLEANUP_BATCH_SIZE = 1000


async def cleanup_old_messages() -> None:
    """Background task: delete messages older than 14 days (runs every hour).
    Runs cleanup immediately on startup, then every CLEANUP_INTERVAL_SECONDS.
    Deletes in batches of CLEANUP_BATCH_SIZE to avoid long-running transactions.
    """
    from app.database import db as database

    while True:
        try:
            threshold = (datetime.now(timezone.utc) - timedelta(days=MESSAGE_RETENTION_DAYS)).isoformat()
            total_deleted = 0
            while True:
                result = await asyncio.to_thread(
                    lambda: database.get_client().table("messages")
                    .delete()
                    .lt("sent_at", threshold)
                    .limit(CLEANUP_BATCH_SIZE)
                    .execute()
                )
                batch_count = len(result.data) if result.data else 0
                total_deleted += batch_count
                if batch_count < CLEANUP_BATCH_SIZE:
                    break
                await asyncio.sleep(0.1)  # yield between batches
            if total_deleted > 0:
                logger.info("[CLEANUP] Deleted %d messages older than %d days", total_deleted, MESSAGE_RETENTION_DAYS)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("[CLEANUP] Error: %s", e)
        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: pre-warm a TelegramClient so first send_code is instant
    await telegram_manager.warm_up()
    # Start background message cleanup task
    cleanup_task = asyncio.create_task(cleanup_old_messages())
    # Start live real-time crawler
    crawler_task = asyncio.create_task(live_crawler.start())
    yield
    # Shutdown: cancel background tasks first, then stop crawler gracefully
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    await live_crawler.stop()
    crawler_task.cancel()
    try:
        await crawler_task
    except asyncio.CancelledError:
        pass


# Create FastAPI app
app = FastAPI(
    title="AaltoHub v2 API",
    description="Backend API for AaltoHub v2 - Telegram Group Message Crawler",
    version="1.0.0",
    docs_url="/docs" if settings.ENVIRONMENT == "development" else None,
    redoc_url="/redoc" if settings.ENVIRONMENT == "development" else None,
    lifespan=lifespan,
)


# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Include routers
app.include_router(auth.router, prefix="/api")
app.include_router(groups.router, prefix="/api")
app.include_router(admin.router, prefix="/api")


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
    """Health check endpoint with DB connectivity and crawler status"""
    from app.database import db as database
    db_ok = False
    try:
        await asyncio.to_thread(
            lambda: database.get_client().table("users").select("id", count="exact").limit(1).execute()
        )
        db_ok = True
    except Exception:
        pass

    crawler_status = {
        "running": live_crawler.running,
        "connected": live_crawler.connected,
        "queue_size": live_crawler._msg_queue.qsize() if live_crawler._msg_queue else 0,
    }
    all_ok = db_ok and live_crawler.running
    return {
        "status": "healthy" if all_ok else "degraded",
        "database": "connected" if db_ok else "unreachable",
        "crawler": crawler_status,
        "environment": settings.ENVIRONMENT
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=settings.ENVIRONMENT == "development"
    )
