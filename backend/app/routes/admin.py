"""
Admin-only routes
"""
import asyncio
import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List
from datetime import datetime, timedelta, timezone
from app.models import (
    TelegramGroupResponse, MessagesListResponse,
    MessageResponse, UserResponse, UserRole
)
from app.auth import get_current_admin_user
from app.database import get_db
from app.routes.groups import _db_group_to_api

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get("/groups", response_model=List[TelegramGroupResponse])
async def get_all_groups(
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    current_user: UserResponse = Depends(get_current_admin_user),
    db = Depends(get_db)
):
    """Get all registered groups (admin only)"""
    try:
        offset = (page - 1) * page_size
        groups = await asyncio.to_thread(
            lambda: db.table("groups").select("*").order("created_at", desc=True).range(offset, offset + page_size - 1).execute()
        )
        return [TelegramGroupResponse(**_db_group_to_api(g)) for g in groups.data] if groups.data else []
    except Exception as e:
        logger.error("get_all_groups error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to fetch groups")


@router.get("/groups/{group_id}/messages", response_model=MessagesListResponse)
async def get_group_messages_admin(
    group_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    days: int = Query(30, ge=1, le=365, description="Number of days to look back"),
    current_user: UserResponse = Depends(get_current_admin_user),
    db = Depends(get_db)
):
    """Get messages from a group for the last N days (admin only)"""
    try:
        # Calculate date threshold
        date_threshold = datetime.now(timezone.utc) - timedelta(days=days)

        # Calculate offset
        offset = (page - 1) * page_size

        # Get total count
        count_response = await asyncio.to_thread(
            lambda: db.table("messages").select("id", count="exact").eq("group_id", group_id).eq("is_deleted", False).gte("sent_at", date_threshold.isoformat()).execute()
        )
        total = count_response.count if hasattr(count_response, 'count') else 0

        # Get messages
        messages_response = await asyncio.to_thread(
            lambda: db.table("messages").select("*").eq("group_id", group_id).eq("is_deleted", False).gte("sent_at", date_threshold.isoformat()).order("sent_at", desc=True).range(offset, offset + page_size - 1).execute()
        )

        messages = [MessageResponse(**m) for m in messages_response.data] if messages_response.data else []

        return MessagesListResponse(
            messages=messages,
            total=total,
            page=page,
            page_size=page_size,
            has_more=offset + page_size < total
        )
    except Exception as e:
        logger.error("get_group_messages_admin error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to fetch messages")


@router.get("/stats")
async def get_stats(
    current_user: UserResponse = Depends(get_current_admin_user),
    db = Depends(get_db)
):
    """Get platform statistics (admin only)"""
    try:
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)

        users_r, groups_r, public_r, msgs_r, recent_r = await asyncio.gather(
            asyncio.to_thread(lambda: db.table("users").select("id", count="exact").execute()),
            asyncio.to_thread(lambda: db.table("groups").select("id", count="exact").execute()),
            asyncio.to_thread(lambda: db.table("groups").select("id", count="exact").eq("visibility", "public").execute()),
            asyncio.to_thread(lambda: db.table("messages").select("id", count="exact").execute()),
            asyncio.to_thread(lambda: db.table("messages").select("id", count="exact").gte("sent_at", yesterday.isoformat()).execute()),
        )

        return {
            "total_users": users_r.count if hasattr(users_r, 'count') and users_r.count else 0,
            "total_groups": groups_r.count if hasattr(groups_r, 'count') and groups_r.count else 0,
            "total_public_groups": public_r.count if hasattr(public_r, 'count') and public_r.count else 0,
            "total_messages": msgs_r.count if hasattr(msgs_r, 'count') and msgs_r.count else 0,
            "messages_last_24h": recent_r.count if hasattr(recent_r, 'count') and recent_r.count else 0,
        }
    except Exception as e:
        logger.error("get_stats error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to fetch statistics")


@router.get("/crawler-status", response_model=List[dict])
async def get_crawler_status(
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=500),
    current_user: UserResponse = Depends(get_current_admin_user),
    db = Depends(get_db)
):
    """Get crawler status for all groups (admin only)"""
    offset = (page - 1) * page_size
    try:
        result = await asyncio.to_thread(
            lambda: db.table("crawler_status")
                .select("*")
                .order("updated_at", desc=True)
                .range(offset, offset + page_size - 1)
                .execute()
        )
        return result.data or []
    except Exception as e:
        logger.error("get_crawler_status error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to fetch crawler status")


@router.post("/crawler-status/{group_id}/toggle")
async def toggle_crawler(
    group_id: str,
    is_enabled: bool,
    current_user: UserResponse = Depends(get_current_admin_user),
    db = Depends(get_db)
):
    """Toggle crawler on/off for a group (admin only)"""
    try:
        result = await asyncio.to_thread(
            lambda: db.table("crawler_status").update({
                "is_enabled": is_enabled,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }).eq("group_id", group_id).execute()
        )

        if not result.data:
            raise HTTPException(status_code=404, detail="Crawler status not found")

        return {"success": True, "is_enabled": is_enabled}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("toggle_crawler error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to toggle crawler")


@router.get("/error-logs", response_model=List[dict])
async def get_error_logs(
    group_id: str = Query(None),
    limit: int = Query(100, ge=1, le=500),
    current_user: UserResponse = Depends(get_current_admin_user),
    db = Depends(get_db)
):
    """Get crawler error logs (admin only)"""
    try:
        query = db.table("crawler_error_logs").select("*").order("created_at", desc=True).limit(limit)

        if group_id:
            query = query.eq("group_id", group_id)

        result = await asyncio.to_thread(lambda: query.execute())
        return result.data if result.data else []
    except Exception as e:
        logger.error("get_error_logs error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to fetch error logs")


@router.get("/user-activity", response_model=List[dict])
async def get_user_activity(
    current_user: UserResponse = Depends(get_current_admin_user),
    db = Depends(get_db)
):
    """Get user activity statistics (admin only)"""
    try:
        result = await asyncio.to_thread(
            lambda: db.table("user_statistics").select("*").execute()
        )
        return result.data if result.data else []
    except Exception as e:
        logger.error("get_user_activity error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to fetch user activity")


@router.get("/group-statistics", response_model=List[dict])
async def get_group_statistics(
    current_user: UserResponse = Depends(get_current_admin_user),
    db = Depends(get_db)
):
    """Get group statistics (admin only)"""
    try:
        result = await asyncio.to_thread(
            lambda: db.table("group_statistics").select("*").execute()
        )
        return result.data if result.data else []
    except Exception as e:
        logger.error("get_group_statistics error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to fetch group statistics")


@router.get("/live-crawler/status")
async def get_live_crawler_status(
    current_user: UserResponse = Depends(get_current_admin_user),
):
    """Get live crawler status (admin only)"""
    from app.live_crawler import live_crawler
    return live_crawler.get_status()


@router.post("/live-crawler/restart")
async def restart_live_crawler(
    current_user: UserResponse = Depends(get_current_admin_user),
):
    """Restart the live crawler (admin only)"""
    from app.live_crawler import live_crawler
    await live_crawler.restart()
    return {"success": True, "status": live_crawler.get_status()}


@router.post("/groups/{group_id}/crawl")
async def trigger_historical_crawl(
    group_id: str,
    current_user: UserResponse = Depends(get_current_admin_user),
):
    """Trigger historical crawl for a specific group (admin only)"""
    from app.live_crawler import live_crawler

    if not live_crawler.running:
        raise HTTPException(status_code=400, detail="Live crawler is not running")

    gid = int(group_id)
    if gid not in live_crawler.group_id_map:
        await live_crawler.refresh_groups()
        await live_crawler._ensure_crawler_status_rows()
        if gid not in live_crawler.group_id_map:
            raise HTTPException(status_code=404, detail="Group not found in crawler")

    live_crawler._crawled_groups.discard(gid)
    task = asyncio.create_task(live_crawler._crawl_historical_for_group(gid))
    # Store task reference to prevent GC
    if not hasattr(live_crawler, '_manual_crawl_tasks'):
        live_crawler._manual_crawl_tasks = {}
    live_crawler._manual_crawl_tasks[group_id] = task
    # Cleanup completed tasks
    live_crawler._manual_crawl_tasks = {
        k: v for k, v in live_crawler._manual_crawl_tasks.items() if not v.done()
    }
    return {"success": True, "message": f"Historical crawl started for group {group_id}"}


@router.get("/failed-messages")
async def get_failed_messages(
    resolved: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    current_user: UserResponse = Depends(get_current_admin_user),
    db=Depends(get_db),
):
    """Get dead letter queue entries (failed message inserts)."""
    try:
        query = db.table("failed_messages").select("*").eq("resolved", resolved).order("created_at", desc=True).limit(limit)
        result = await asyncio.to_thread(lambda: query.execute())
        return result.data or []
    except Exception as e:
        logger.error("get_failed_messages error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to fetch dead letter queue")


@router.post("/failed-messages/{message_id}/retry")
async def retry_failed_message(
    message_id: str,
    current_user: UserResponse = Depends(get_current_admin_user),
    db=Depends(get_db),
):
    """Retry a failed message from the dead letter queue."""
    try:
        record = await asyncio.to_thread(
            lambda: db.table("failed_messages").select("*").eq("id", message_id).execute()
        )
        if not record.data:
            raise HTTPException(status_code=404, detail="Failed message not found")
        payload = record.data[0].get("payload", {})
        if not payload:
            raise HTTPException(status_code=400, detail="No payload to retry")
        await asyncio.to_thread(
            lambda: db.table("messages").upsert(
                payload,
                on_conflict="telegram_message_id,group_id",
                ignore_duplicates=True,
            ).execute()
        )
        await asyncio.to_thread(
            lambda: db.table("failed_messages").update({
                "resolved": True,
                "resolved_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", message_id).execute()
        )
        return {"success": True, "message": "Message retried and resolved"}
    except HTTPException:
        raise
    except Exception as e:
        await asyncio.to_thread(
            lambda: db.table("failed_messages").update({
                "retry_count": record.data[0].get("retry_count", 0) + 1,
            }).eq("id", message_id).execute()
        )
        logger.error("retry_failed_message error: %s", e)
        raise HTTPException(status_code=500, detail="Retry failed")


@router.get("/users", response_model=List[UserResponse])
async def get_all_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    current_user: UserResponse = Depends(get_current_admin_user),
    db = Depends(get_db)
):
    """Get all users (admin only)"""
    try:
        offset = (page - 1) * page_size
        users = await asyncio.to_thread(
            lambda: db.table("users").select("*").order("created_at", desc=True).range(offset, offset + page_size - 1).execute()
        )
        return [UserResponse(**u) for u in users.data] if users.data else []
    except Exception as e:
        logger.error("get_all_users error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to fetch users")


@router.patch("/users/{user_id}/role")
async def update_user_role(
    user_id: str,
    role: UserRole = Query(...),
    current_user: UserResponse = Depends(get_current_admin_user),
    db = Depends(get_db)
):
    """Update user role (admin only)"""
    # Prevent self-role-change
    if str(current_user.id) == user_id:
        raise HTTPException(status_code=400, detail="Cannot change your own role")

    try:
        # Check user exists
        check = await asyncio.to_thread(
            lambda: db.table("users").select("id").eq("id", user_id).execute()
        )
        if not check.data:
            raise HTTPException(status_code=404, detail="User not found")

        # Update role
        result = await asyncio.to_thread(
            lambda: db.table("users").update({
                "role": role.value,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }).eq("id", user_id).execute()
        )

        if not result.data:
            raise HTTPException(status_code=500, detail="Failed to update user role")

        return {"success": True, "user_id": user_id, "new_role": role.value}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("update_user_role error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to update user role")
