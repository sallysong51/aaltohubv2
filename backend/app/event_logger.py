"""
Crawler Event Logger
전체 상황 파악을 위한 이벤트 로깅 시스템

Features:
- Async event recording to crawler_events table
- Automatic resolution tracking (errors → recovery events)
- Metrics recording for trend analysis
- Non-blocking (failures don't crash crawler)
"""
import asyncio
import logging
import traceback
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from app.database import db

logger = logging.getLogger(__name__)


class EventLogger:
    """
    Centralized event logger for crawler operations.

    Usage:
        event_logger = EventLogger()
        await event_logger.log_error("database", "DB write failed", details={"error": str(e)})
        await event_logger.log_success("crawl", "Historical crawl completed", group_id=123)
    """

    def __init__(self):
        self._pending_events = asyncio.Queue(maxsize=1000)
        self._worker_task: Optional[asyncio.Task] = None
        self._running = False

        # Track unresolved errors for auto-resolution
        self._unresolved_errors: Dict[str, int] = {}  # key -> event_id

    async def start(self):
        """Start background worker for async event recording."""
        if self._running:
            return

        self._running = True
        self._worker_task = asyncio.create_task(self._worker())
        logger.info("EventLogger worker started")

    async def stop(self):
        """Stop background worker and flush pending events."""
        if not self._running:
            return

        self._running = False

        # Wait for pending events to be processed (with timeout)
        try:
            await asyncio.wait_for(self._pending_events.join(), timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning("EventLogger: %d events lost during shutdown", self._pending_events.qsize())

        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass

        logger.info("EventLogger worker stopped")

    async def _worker(self):
        """Background worker that writes events to database."""
        while self._running:
            try:
                event = await asyncio.wait_for(self._pending_events.get(), timeout=1.0)
                await self._write_event(event)
                self._pending_events.task_done()
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error("EventLogger worker error: %s", e, exc_info=True)
                await asyncio.sleep(1.0)

    async def _write_event(self, event: Dict[str, Any]):
        """Write single event to database."""
        try:
            if not db.is_connected:
                logger.warning("EventLogger: DB not connected, dropping event: %s", event.get("title"))
                return

            await db.execute(
                """
                INSERT INTO crawler_events (event_type, event_category, title, message, group_id, connection_id, details)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                event["event_type"],
                event["event_category"],
                event["title"],
                event["message"],
                event.get("group_id"),
                event.get("connection_id"),
                event.get("details"),
            )
        except Exception as e:
            logger.error("Failed to write event to DB: %s - %s", event.get("title"), e)

    def _enqueue(
        self,
        event_type: str,
        event_category: str,
        title: str,
        message: str,
        group_id: Optional[int] = None,
        connection_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        """Enqueue event for background writing (non-blocking)."""
        if not self._running:
            logger.warning("EventLogger not running, dropping event: %s", title)
            return

        event = {
            "event_type": event_type,
            "event_category": event_category,
            "title": title,
            "message": message,
            "group_id": group_id,
            "connection_id": connection_id,
            "details": details,
        }

        try:
            self._pending_events.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning("EventLogger queue full, dropping event: %s", title)

    # ========================================================================
    # Public API: Convenience methods for different event types
    # ========================================================================

    async def log_error(
        self,
        category: str,
        title: str,
        message: Optional[str] = None,
        group_id: Optional[int] = None,
        connection_id: Optional[str] = None,
        exception: Optional[Exception] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        """Log error event with automatic stack trace capture."""
        if details is None:
            details = {}

        if exception:
            details["exception_type"] = type(exception).__name__
            details["exception_message"] = str(exception)
            details["traceback"] = traceback.format_exc()

        error_key = f"{category}:{group_id or 'system'}"
        self._unresolved_errors[error_key] = 1  # Mark as unresolved for auto-recovery tracking

        self._enqueue(
            event_type="error",
            event_category=category,
            title=title,
            message=message or str(exception) if exception else title,
            group_id=group_id,
            connection_id=connection_id,
            details=details,
        )

    async def log_warning(
        self,
        category: str,
        title: str,
        message: str,
        group_id: Optional[int] = None,
        connection_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        """Log warning event."""
        self._enqueue(
            event_type="warning",
            event_category=category,
            title=title,
            message=message,
            group_id=group_id,
            connection_id=connection_id,
            details=details,
        )

    async def log_info(
        self,
        category: str,
        title: str,
        message: str,
        group_id: Optional[int] = None,
        connection_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        """Log informational event."""
        self._enqueue(
            event_type="info",
            event_category=category,
            title=title,
            message=message,
            group_id=group_id,
            connection_id=connection_id,
            details=details,
        )

    async def log_success(
        self,
        category: str,
        title: str,
        message: str,
        group_id: Optional[int] = None,
        connection_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        """Log success event."""
        self._enqueue(
            event_type="success",
            event_category=category,
            title=title,
            message=message,
            group_id=group_id,
            connection_id=connection_id,
            details=details,
        )

    async def log_recovery(
        self,
        category: str,
        title: str,
        message: str,
        group_id: Optional[int] = None,
        connection_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        """
        Log recovery event (error was automatically resolved).

        This also clears the unresolved error flag.
        """
        error_key = f"{category}:{group_id or 'system'}"
        if error_key in self._unresolved_errors:
            del self._unresolved_errors[error_key]

        self._enqueue(
            event_type="recovery",
            event_category=category,
            title=title,
            message=message,
            group_id=group_id,
            connection_id=connection_id,
            details=details,
        )

    async def record_metric(
        self,
        metric_name: str,
        metric_value: float,
        group_id: Optional[int] = None,
        connection_id: Optional[str] = None,
        labels: Optional[Dict[str, Any]] = None,
    ):
        """Record time-series metric for trend analysis."""
        try:
            if not db.is_connected:
                return

            await db.execute(
                """
                INSERT INTO crawler_metrics (metric_name, metric_value, group_id, connection_id, labels)
                VALUES ($1, $2, $3, $4, $5)
                """,
                metric_name,
                metric_value,
                group_id,
                connection_id,
                labels or {},
            )
        except Exception as e:
            logger.error("Failed to record metric %s: %s", metric_name, e)


# Global singleton instance
event_logger = EventLogger()
