"""Admin crawler management routes."""
import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List
from app.models import UserResponse
from app.auth import get_current_admin_user
from app.config import settings
from app.database import db

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/crawler-status", response_model=List[dict])
async def get_crawler_status(
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=500),
    current_user: UserResponse = Depends(get_current_admin_user),
):
    """Get crawler status for all groups (admin only)"""
    offset = (page - 1) * page_size
    try:
        rows = await db.fetch(
            """SELECT cs.*, g.name AS group_title
               FROM crawler_status cs
               LEFT JOIN groups g ON g.id = cs.group_id
               ORDER BY cs.updated_at DESC
               LIMIT $1 OFFSET $2""",
            page_size, offset,
        )
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error("get_crawler_status error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to fetch crawler status")


@router.post("/crawler-status/{group_id}/toggle")
async def toggle_crawler(
    group_id: str,
    is_enabled: bool,
    current_user: UserResponse = Depends(get_current_admin_user),
):
    """Toggle crawler on/off for a group (admin only)"""
    try:
        gid = int(group_id)
        result = await db.fetchrow(
            "UPDATE crawler_status SET is_enabled = $1 WHERE group_id = $2 RETURNING id",
            is_enabled, gid,
        )

        if not result:
            raise HTTPException(status_code=404, detail="Crawler status not found")

        return {"success": True, "is_enabled": is_enabled}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("toggle_crawler error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to toggle crawler")


@router.get("/live-crawler/status")
async def get_live_crawler_status(
    current_user: UserResponse = Depends(get_current_admin_user),
):
    """Get live crawler status (admin only) — proxied to crawler process.

    Returns enhanced status with health_status field:
    - healthy: All systems operational
    - degraded: Running but has issues (DB down, circuit breaker open)
    - restarting: Recently restarted (< 30s uptime)
    - unreachable: Connection failed after retries
    - stopped: Process responded but running=False
    """
    from app import crawler_client

    # Get health check (with retry logic)
    health = await crawler_client.get_crawler_health()

    if health.status == "unreachable":
        raise HTTPException(
            status_code=503,
            detail={
                "message": health.message,
                "status": "unreachable",
                "environment": settings.ENVIRONMENT,
            }
        )

    # Get detailed status if reachable
    status = await crawler_client.get_crawler_status()

    if status is None:
        # Edge case: health check passed but status call failed
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Crawler status unavailable",
                "status": "unreachable",
                "environment": settings.ENVIRONMENT,
            }
        )

    # Merge health info into status response
    return {
        **status,
        "health_status": health.status,
        "health_message": health.message,
        "environment": settings.ENVIRONMENT,
    }


@router.post("/live-crawler/restart")
async def restart_live_crawler(
    current_user: UserResponse = Depends(get_current_admin_user),
):
    """Restart the live crawler (admin only) — proxied to crawler process."""
    from app import crawler_client
    result = await crawler_client.restart_crawler()
    if result is None:
        raise HTTPException(status_code=503, detail="Crawler process is unreachable")
    return result


@router.post("/groups/{group_id}/crawl")
async def trigger_historical_crawl(
    group_id: str,
    current_user: UserResponse = Depends(get_current_admin_user),
):
    """Trigger historical crawl for a specific group (admin only) — proxied to crawler process."""
    from app import crawler_client
    result = await crawler_client.trigger_historical_crawl(group_id)
    if result is None:
        raise HTTPException(status_code=503, detail="Crawler process is unreachable")
    if result.get("error") == "not_found":
        raise HTTPException(status_code=404, detail=result.get("detail", "Group not found"))
    if result.get("error") == "not_running":
        raise HTTPException(status_code=400, detail=result.get("detail", "Crawler is not running"))
    return result


@router.post("/trigger-batch-crawl")
async def trigger_batch_crawl_admin(
    current_user: UserResponse = Depends(get_current_admin_user),
):
    """Trigger batch historical crawl for all groups (admin only) — proxied to crawler process."""
    from app import crawler_client

    # Get all group IDs
    rows = await db.fetch("SELECT id FROM groups WHERE crawl_enabled = true")
    group_ids = [str(row["id"]) for row in rows]

    if not group_ids:
        raise HTTPException(status_code=400, detail="No groups with crawl enabled")

    result = await crawler_client.trigger_batch_historical_crawl(group_ids)
    if result is None:
        raise HTTPException(status_code=503, detail="Crawler process is unreachable")
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result.get("detail", "Batch crawl failed"))

    return {
        "success": True,
        "message": f"Batch crawl started for {len(group_ids)} groups",
        "group_count": len(group_ids)
    }


@router.get("/crawler-events")
async def get_crawler_events(
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    event_type: str = Query(None, description="Filter by event type: error, warning, info, success, recovery"),
    event_category: str = Query(None, description="Filter by category: connection, crawl, database, media, gap_fill, circuit_breaker, system, auth, rate_limit"),
    group_id: int = Query(None, description="Filter by group ID"),
    resolved: bool = Query(None, description="Filter by resolved status"),
    current_user: UserResponse = Depends(get_current_admin_user),
):
    """
    Get crawler events with optional filters (admin only).
    Returns comprehensive event log with resolution tracking.
    """
    offset = (page - 1) * page_size

    # Build dynamic WHERE clause
    where_clauses = []
    params = []
    param_count = 1

    if event_type:
        where_clauses.append(f"event_type = ${param_count}")
        params.append(event_type)
        param_count += 1

    if event_category:
        where_clauses.append(f"event_category = ${param_count}")
        params.append(event_category)
        param_count += 1

    if group_id is not None:
        where_clauses.append(f"group_id = ${param_count}")
        params.append(group_id)
        param_count += 1

    if resolved is not None:
        where_clauses.append(f"resolved = ${param_count}")
        params.append(resolved)
        param_count += 1

    where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

    # Add pagination params
    params.extend([page_size, offset])

    try:
        # Check if table exists first
        table_exists = await db.fetchval(
            "SELECT EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'crawler_events')"
        )

        if not table_exists:
            logger.warning("crawler_events table does not exist - returning empty result")
            return {
                "events": [],
                "unresolved_count": 0,
                "page": page,
                "page_size": page_size,
            }

        rows = await db.fetch(
            f"""
            SELECT
                ce.*,
                g.name AS group_title
            FROM crawler_events ce
            LEFT JOIN groups g ON g.id = ce.group_id
            {where_sql}
            ORDER BY ce.created_at DESC
            LIMIT ${param_count} OFFSET ${param_count + 1}
            """,
            *params,
        )

        # Also get count of unresolved errors for summary
        unresolved_count = await db.fetchval(
            "SELECT COUNT(*) FROM crawler_events WHERE resolved = false AND event_type IN ('error', 'warning')"
        ) or 0

        return {
            "events": [dict(r) for r in rows],
            "unresolved_count": unresolved_count,
            "page": page,
            "page_size": page_size,
        }
    except Exception as e:
        logger.error("get_crawler_events error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch crawler events: {str(e)}")


@router.get("/crawler-summary")
async def get_crawler_summary(
    current_user: UserResponse = Depends(get_current_admin_user),
):
    """
    Get summary statistics of crawler events for dashboard.
    전체 상황 파악용 요약 통계
    """
    try:
        # Check if table exists first
        table_exists = await db.fetchval(
            "SELECT EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'crawler_events')"
        )

        if not table_exists:
            logger.warning("crawler_events table does not exist - returning empty summary")
            return {
                "event_counts": [],
                "unresolved_errors": [],
                "recent_successes": [],
                "recovery_events": [],
            }

        # Get event counts by type (last 24 hours)
        event_counts = await db.fetch(
            """
            SELECT
                event_type,
                event_category,
                COUNT(*) as count
            FROM crawler_events
            WHERE created_at > NOW() - INTERVAL '24 hours'
            GROUP BY event_type, event_category
            ORDER BY count DESC
            """
        )

        # Get unresolved errors
        unresolved_errors = await db.fetch(
            """
            SELECT
                ce.*,
                g.name AS group_title
            FROM crawler_events ce
            LEFT JOIN groups g ON g.id = ce.group_id
            WHERE ce.resolved = false
              AND ce.event_type IN ('error', 'warning')
            ORDER BY ce.created_at DESC
            LIMIT 10
            """
        )

        # Get recent successes (last 10)
        recent_successes = await db.fetch(
            """
            SELECT
                ce.*,
                g.name AS group_title
            FROM crawler_events ce
            LEFT JOIN groups g ON g.id = ce.group_id
            WHERE ce.event_type = 'success'
            ORDER BY ce.created_at DESC
            LIMIT 10
            """
        )

        # Get recovery events (auto-resolved issues)
        recovery_events = await db.fetch(
            """
            SELECT
                ce.*,
                g.name AS group_title
            FROM crawler_events ce
            LEFT JOIN groups g ON g.id = ce.group_id
            WHERE ce.event_type = 'recovery'
            ORDER BY ce.created_at DESC
            LIMIT 10
            """
        )

        return {
            "event_counts": [dict(r) for r in event_counts],
            "unresolved_errors": [dict(r) for r in unresolved_errors],
            "recent_successes": [dict(r) for r in recent_successes],
            "recovery_events": [dict(r) for r in recovery_events],
        }
    except Exception as e:
        logger.error("get_crawler_summary error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch crawler summary: {str(e)}")
