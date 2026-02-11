"""
System Diagnostics - Comprehensive monitoring of all crawler components.

Tracks 12 crawler subsystems:
1. LiveTelegramCrawler - Main crawler process
2. Telegram Listeners - Event listener tasks
3. Database Connection - asyncpg pool
4. SSE Manager - LISTEN/NOTIFY connection
5. Circuit Breaker - DB write failure tracker
6. Dead Letter Queue - Failed message backup
7. FloodWait Tracker - Telegram API rate limits
8. Error Recovery - get_me() retry logic
9. Metrics Tracker - Message processing stats
10. Manual Crawl Tasks - User-initiated crawls
11. Batch Crawl Worker - Queue-based batch processing
12. Telegram Connections - Session health
"""
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Dict, Any
from app.models import UserResponse
from app.auth import get_current_admin_user
from app.database import db
from app import crawler_client

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/system-diagnostics")
async def get_system_diagnostics(
    current_user: UserResponse = Depends(get_current_admin_user),
):
    """
    Get comprehensive system diagnostics for all crawler components.

    Returns health status, metrics, and recent issues for 12 subsystems.
    """
    try:
        # 1. Get live crawler detailed status
        crawler_status = await crawler_client.get_crawler_status()
        crawler_health = await crawler_client.get_crawler_health()

        if crawler_status is None:
            return {
                "overall_health": "critical",
                "components": [],
                "message": "Crawler process unreachable",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        # 2. Get DB connection status
        db_status = await _get_database_status()

        # 3. Get SSE manager status
        from app.main import sse_manager
        sse_status = _get_sse_status(sse_manager)

        # 4. Build component statuses
        components = []

        # Main Crawler Process
        components.append({
            "name": "Main Crawler Process",
            "category": "core",
            "health": _map_crawler_health(crawler_health.status if crawler_health else "unreachable"),
            "status": crawler_status.get("status", "unknown") if crawler_status else "stopped",
            "metrics": {
                "uptime_seconds": crawler_status.get("uptime_seconds", 0) if crawler_status else 0,
                "groups_monitored": crawler_status.get("groups_monitored", 0) if crawler_status else 0,
                "messages_handled": crawler_status.get("messages_handled", {}).get("total", 0) if crawler_status else 0,
                "messages_skipped": crawler_status.get("messages_skipped", {}).get("total", 0) if crawler_status else 0,
            },
            "issues": [],
            "last_activity": crawler_status.get("last_activity") if crawler_status else None,
        })

        # Telegram Listeners
        listener_health = "healthy"
        listener_issues = []
        if crawler_status:
            listeners = crawler_status.get("active_listeners", {})
            total_listeners = len(listeners)
            seconds_since_last = crawler_status.get("seconds_since_last_event")

            if total_listeners == 0:
                listener_health = "critical"
                listener_issues.append("No active listeners - no events will be received")
            elif seconds_since_last and seconds_since_last > 600:  # 10 minutes
                listener_health = "warning"
                listener_issues.append(f"No events received in {seconds_since_last}s")
        else:
            listener_health = "critical"
            listener_issues.append("Crawler unreachable - cannot check listeners")

        components.append({
            "name": "Telegram Listeners",
            "category": "connection",
            "health": listener_health,
            "status": "active" if listener_health != "critical" else "stopped",
            "metrics": {
                "active_count": len(crawler_status.get("active_listeners", {})) if crawler_status else 0,
                "seconds_since_last_event": crawler_status.get("seconds_since_last_event") if crawler_status else None,
            },
            "issues": listener_issues,
            "last_activity": None,
        })

        # Database Connection
        components.append({
            "name": "Database Connection",
            "category": "database",
            "health": db_status["health"],
            "status": "connected" if db_status["connected"] else "disconnected",
            "metrics": {
                "pool_size": db_status.get("pool_size", 0),
                "idle_connections": db_status.get("idle_connections", 0),
            },
            "issues": db_status.get("issues", []),
            "last_activity": None,
        })

        # SSE Manager
        components.append({
            "name": "SSE Manager",
            "category": "realtime",
            "health": sse_status["health"],
            "status": "connected" if sse_status["connected"] else "disconnected",
            "metrics": {
                "active_connections": sse_status.get("active_connections", 0),
            },
            "issues": sse_status.get("issues", []),
            "last_activity": None,
        })

        # Circuit Breaker
        circuit_breaker_health = "healthy"
        circuit_breaker_issues = []
        if crawler_status:
            cb_state = crawler_status.get("circuit_breaker", {})
            if cb_state.get("state") == "open":
                circuit_breaker_health = "critical"
                circuit_breaker_issues.append("Circuit breaker OPEN - no DB writes possible")
            elif cb_state.get("failure_count", 0) > 0:
                circuit_breaker_health = "warning"
                circuit_breaker_issues.append(f"{cb_state['failure_count']} failures in current window")

        components.append({
            "name": "Circuit Breaker",
            "category": "resilience",
            "health": circuit_breaker_health,
            "status": crawler_status.get("circuit_breaker", {}).get("state", "unknown") if crawler_status else "unknown",
            "metrics": {
                "failure_count": crawler_status.get("circuit_breaker", {}).get("failure_count", 0) if crawler_status else 0,
                "consecutive_opens": crawler_status.get("circuit_breaker", {}).get("consecutive_opens", 0) if crawler_status else 0,
            },
            "issues": circuit_breaker_issues,
            "last_activity": None,
        })

        # Dead Letter Queue
        dlq_health = "healthy"
        dlq_issues = []
        if crawler_status:
            dlq_size = crawler_status.get("dead_letter_queue_size", 0)
            if dlq_size > 100:
                dlq_health = "critical"
                dlq_issues.append(f"{dlq_size} messages in dead letter queue - manual intervention needed")
            elif dlq_size > 10:
                dlq_health = "warning"
                dlq_issues.append(f"{dlq_size} messages in dead letter queue")

        components.append({
            "name": "Dead Letter Queue",
            "category": "resilience",
            "health": dlq_health,
            "status": "active",
            "metrics": {
                "queued_messages": crawler_status.get("dead_letter_queue_size", 0) if crawler_status else 0,
            },
            "issues": dlq_issues,
            "last_activity": None,
        })

        # FloodWait Tracker
        floodwait_health = "healthy"
        floodwait_issues = []
        if crawler_status:
            penalties = crawler_status.get("floodwait_penalties", {})
            active_count = sum(1 for exp in penalties.values() if exp > datetime.now(timezone.utc).timestamp())
            if active_count > 5:
                floodwait_health = "warning"
                floodwait_issues.append(f"{active_count} groups under FloodWait penalty")

        components.append({
            "name": "FloodWait Tracker",
            "category": "rate_limit",
            "health": floodwait_health,
            "status": "active",
            "metrics": {
                "active_penalties": len(crawler_status.get("floodwait_penalties", {})) if crawler_status else 0,
            },
            "issues": floodwait_issues,
            "last_activity": None,
        })

        # Error Recovery
        error_recovery_health = "healthy"
        error_recovery_issues = []
        if crawler_status:
            circuit_open = crawler_status.get("get_me_circuit_open_count", 0)
            if circuit_open > 0:
                error_recovery_health = "warning"
                error_recovery_issues.append(f"{circuit_open} connections with open circuit breaker")

        components.append({
            "name": "Error Recovery",
            "category": "resilience",
            "health": error_recovery_health,
            "status": "active",
            "metrics": {
                "cache_size": crawler_status.get("get_me_cache_size", 0) if crawler_status else 0,
                "circuit_open_count": crawler_status.get("get_me_circuit_open_count", 0) if crawler_status else 0,
            },
            "issues": error_recovery_issues,
            "last_activity": None,
        })

        # Metrics Tracker
        components.append({
            "name": "Metrics Tracker",
            "category": "monitoring",
            "health": "healthy",
            "status": "active",
            "metrics": {
                "handled_total": crawler_status.get("messages_handled", {}).get("total", 0) if crawler_status else 0,
                "skipped_total": crawler_status.get("messages_skipped", {}).get("total", 0) if crawler_status else 0,
            },
            "issues": [],
            "last_activity": None,
        })

        # Manual Crawl Tasks
        manual_tasks_health = "healthy"
        manual_tasks_issues = []
        if crawler_status:
            active_tasks = crawler_status.get("manual_crawl_tasks_count", 0)
            if active_tasks > 10:
                manual_tasks_health = "warning"
                manual_tasks_issues.append(f"{active_tasks} manual crawl tasks running - high load")

        components.append({
            "name": "Manual Crawl Tasks",
            "category": "crawl",
            "health": manual_tasks_health,
            "status": "active",
            "metrics": {
                "active_tasks": crawler_status.get("manual_crawl_tasks_count", 0) if crawler_status else 0,
            },
            "issues": manual_tasks_issues,
            "last_activity": None,
        })

        # Batch Crawl Worker
        batch_health = "healthy"
        batch_issues = []
        if crawler_status:
            batch_active = crawler_status.get("batch_crawl_active", False)
            currently_crawling = crawler_status.get("currently_crawling_group_id")
            if batch_active and not currently_crawling:
                batch_health = "warning"
                batch_issues.append("Batch crawl active but no group currently crawling")

        components.append({
            "name": "Batch Crawl Worker",
            "category": "crawl",
            "health": batch_health,
            "status": "active" if crawler_status.get("batch_crawl_active", False) else "idle",
            "metrics": {
                "queue_size": crawler_status.get("batch_crawl_queue_size", 0) if crawler_status else 0,
            },
            "issues": batch_issues,
            "last_activity": None,
        })

        # Telegram Connections
        connection_health = "healthy"
        connection_issues = []
        if crawler_status:
            connections = crawler_status.get("active_listeners", {})
            if len(connections) == 0:
                connection_health = "critical"
                connection_issues.append("No active Telegram connections")

        components.append({
            "name": "Telegram Connections",
            "category": "connection",
            "health": connection_health,
            "status": "connected" if len(crawler_status.get("active_listeners", {})) > 0 else "disconnected",
            "metrics": {
                "connection_count": len(crawler_status.get("active_listeners", {})) if crawler_status else 0,
            },
            "issues": connection_issues,
            "last_activity": None,
        })

        # Calculate overall health
        health_scores = {"healthy": 3, "warning": 2, "degraded": 1, "critical": 0}
        avg_health_score = sum(health_scores.get(c["health"], 0) for c in components) / len(components)

        if avg_health_score >= 2.5:
            overall_health = "healthy"
        elif avg_health_score >= 1.5:
            overall_health = "warning"
        elif avg_health_score >= 0.5:
            overall_health = "degraded"
        else:
            overall_health = "critical"

        return {
            "overall_health": overall_health,
            "components": components,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "crawler_reachable": crawler_status is not None,
        }

    except Exception as e:
        logger.error("get_system_diagnostics error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch system diagnostics: {str(e)}")


async def _get_database_status() -> Dict[str, Any]:
    """Get database connection status and metrics."""
    try:
        connected = db.is_connected()

        issues = []
        if not connected:
            issues.append("Database disconnected - auto-reconnect in progress")

        pool_size = 0
        idle_connections = 0
        if connected and db._pool:
            pool_size = db._pool.get_size()
            idle_connections = db._pool.get_idle_size()

            if idle_connections == 0 and pool_size > 0:
                issues.append("No idle connections - pool may be exhausted")

        health = "healthy" if connected and not issues else ("warning" if connected else "critical")

        return {
            "connected": connected,
            "health": health,
            "pool_size": pool_size,
            "idle_connections": idle_connections,
            "issues": issues,
        }
    except Exception as e:
        logger.error("_get_database_status error: %s", e)
        return {
            "connected": False,
            "health": "critical",
            "issues": [f"Error checking database: {str(e)}"],
        }


def _get_sse_status(sse_manager) -> Dict[str, Any]:
    """Get SSE manager status."""
    try:
        connected = sse_manager.is_connected() if sse_manager else False
        active_connections = len(sse_manager._subscribers) if sse_manager and hasattr(sse_manager, '_subscribers') else 0

        issues = []
        if not connected:
            issues.append("LISTEN connection down - realtime events unavailable")

        health = "healthy" if connected else "critical"

        return {
            "connected": connected,
            "health": health,
            "active_connections": active_connections,
            "issues": issues,
        }
    except Exception as e:
        logger.error("_get_sse_status error: %s", e)
        return {
            "connected": False,
            "health": "critical",
            "issues": [f"Error checking SSE: {str(e)}"],
        }


def _map_crawler_health(status: str) -> str:
    """Map CrawlerHealthStatus to component health."""
    mapping = {
        "healthy": "healthy",
        "degraded": "degraded",
        "restarting": "warning",
        "unreachable": "critical",
        "stopped": "critical",
    }
    return mapping.get(status, "unknown")


@router.get("/system-logs")
async def get_system_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    component: str = Query(None),
    health: str = Query(None),
    current_user: UserResponse = Depends(get_current_admin_user),
):
    """Get system logs with filtering and pagination."""
    offset = (page - 1) * page_size

    # Map component to event_category
    component_category_map = {
        "Main Crawler Process": "system",
        "Telegram Listeners": "connection",
        "Database Connection": "database",
        "SSE Manager": "system",
        "Circuit Breaker": "circuit_breaker",
        "Dead Letter Queue": "system",
        "FloodWait Tracker": "rate_limit",
        "Error Recovery": "auth",
        "Metrics Tracker": "system",
        "Manual Crawl Tasks": "crawl",
        "Batch Crawl Worker": "crawl",
        "Telegram Connections": "connection",
    }

    where_clauses = []
    params = []
    param_count = 1

    if component and component in component_category_map:
        where_clauses.append(f"event_category = ${param_count}")
        params.append(component_category_map[component])
        param_count += 1

    if health:
        if health == "critical":
            where_clauses.append(f"event_type = ${param_count}")
            params.append("error")
            param_count += 1
        elif health == "warning":
            where_clauses.append(f"event_type = ${param_count}")
            params.append("warning")
            param_count += 1

    where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""
    params.extend([page_size, offset])

    try:
        table_exists = await db.fetchval(
            "SELECT EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'crawler_events')"
        )

        if not table_exists:
            return {"logs": [], "page": page, "page_size": page_size, "total": 0}

        rows = await db.fetch(
            f"""SELECT ce.*, g.name AS group_title
                FROM crawler_events ce
                LEFT JOIN groups g ON g.id = ce.group_id
                {where_sql}
                ORDER BY ce.created_at DESC
                LIMIT ${param_count} OFFSET ${param_count + 1}""",
            *params,
        )

        total = await db.fetchval(
            f"SELECT COUNT(*) FROM crawler_events ce {where_sql}",
            *params[:-2],
        ) or 0

        return {
            "logs": [dict(r) for r in rows],
            "page": page,
            "page_size": page_size,
            "total": total,
        }
    except Exception as e:
        logger.error("get_system_logs error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch system logs: {str(e)}")
