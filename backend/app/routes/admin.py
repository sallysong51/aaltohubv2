"""
Admin-only routes
"""
import asyncio
import json
import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List
from datetime import datetime, timedelta, timezone
from app.models import (
    TelegramGroupResponse, MessagesListResponse,
    MessageResponse, UserResponse, UserRole
)
from app.auth import get_current_admin_user
from app.database import db
from app.routes.groups import _db_group_to_api

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get("/groups", response_model=List[TelegramGroupResponse])
async def get_all_groups(
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    current_user: UserResponse = Depends(get_current_admin_user),
):
    """Get all registered groups (admin only)"""
    try:
        offset = (page - 1) * page_size
        rows = await db.fetch(
            "SELECT * FROM groups ORDER BY created_at DESC LIMIT $1 OFFSET $2",
            page_size, offset,
        )
        return [TelegramGroupResponse(**_db_group_to_api(dict(g))) for g in rows]
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
):
    """Get messages from a group for the last N days (admin only)"""
    try:
        gid = int(group_id)
        date_threshold = datetime.now(timezone.utc) - timedelta(days=days)
        offset = (page - 1) * page_size

        total = await db.fetchval(
            "SELECT COUNT(*) FROM messages WHERE group_id = $1 AND is_deleted = FALSE AND sent_at >= $2",
            gid, date_threshold,
        )

        messages_rows = await db.fetch(
            """SELECT * FROM messages
               WHERE group_id = $1 AND is_deleted = FALSE AND sent_at >= $2
               ORDER BY sent_at DESC LIMIT $3 OFFSET $4""",
            gid, date_threshold, page_size, offset,
        )

        messages = [MessageResponse(**dict(m)) for m in messages_rows]

        return MessagesListResponse(
            messages=messages, total=total, page=page, page_size=page_size,
            has_more=offset + page_size < total,
        )
    except Exception as e:
        logger.error("get_group_messages_admin error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to fetch messages")


@router.get("/stats")
async def get_stats(
    current_user: UserResponse = Depends(get_current_admin_user),
):
    """Get platform statistics (admin only)"""
    try:
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)

        total_users, total_groups, total_public, total_msgs, recent_msgs = await asyncio.gather(
            db.fetchval("SELECT COUNT(*) FROM users"),
            db.fetchval("SELECT COUNT(*) FROM groups"),
            db.fetchval("SELECT COUNT(*) FROM groups WHERE visibility = 'public'"),
            db.fetchval("SELECT COUNT(*) FROM messages"),
            db.fetchval("SELECT COUNT(*) FROM messages WHERE sent_at >= $1", yesterday),
        )

        return {
            "total_users": total_users or 0,
            "total_groups": total_groups or 0,
            "total_public_groups": total_public or 0,
            "total_messages": total_msgs or 0,
            "messages_last_24h": recent_msgs or 0,
        }
    except Exception as e:
        logger.error("get_stats error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to fetch statistics")


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
            "SELECT * FROM crawler_status ORDER BY updated_at DESC LIMIT $1 OFFSET $2",
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


@router.get("/error-logs", response_model=List[dict])
async def get_error_logs(
    group_id: str = Query(None),
    limit: int = Query(100, ge=1, le=500),
    current_user: UserResponse = Depends(get_current_admin_user),
):
    """Get crawler error logs (admin only)"""
    try:
        if group_id:
            gid = int(group_id)
            rows = await db.fetch(
                "SELECT * FROM crawler_error_logs WHERE group_id = $1 ORDER BY created_at DESC LIMIT $2",
                gid, limit,
            )
        else:
            rows = await db.fetch(
                "SELECT * FROM crawler_error_logs ORDER BY created_at DESC LIMIT $1",
                limit,
            )
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error("get_error_logs error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to fetch error logs")


@router.get("/user-activity", response_model=List[dict])
async def get_user_activity(
    current_user: UserResponse = Depends(get_current_admin_user),
):
    """Get user activity statistics (admin only)"""
    try:
        rows = await db.fetch("SELECT * FROM user_statistics")
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error("get_user_activity error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to fetch user activity")


@router.get("/group-statistics", response_model=List[dict])
async def get_group_statistics(
    current_user: UserResponse = Depends(get_current_admin_user),
):
    """Get group statistics (admin only)"""
    try:
        rows = await db.fetch("SELECT * FROM group_statistics")
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error("get_group_statistics error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to fetch group statistics")


@router.get("/live-crawler/status")
async def get_live_crawler_status(
    current_user: UserResponse = Depends(get_current_admin_user),
):
    """Get live crawler status (admin only) — proxied to crawler process."""
    from app import crawler_client
    status = await crawler_client.get_crawler_status()
    if status is None:
        raise HTTPException(status_code=503, detail="Crawler process is unreachable")
    return status


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


@router.get("/failed-messages")
async def get_failed_messages(
    resolved: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    current_user: UserResponse = Depends(get_current_admin_user),
):
    """Get dead letter queue entries (failed message inserts)."""
    try:
        rows = await db.fetch(
            "SELECT * FROM failed_messages WHERE resolved = $1 ORDER BY created_at DESC LIMIT $2",
            resolved, limit,
        )
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error("get_failed_messages error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to fetch dead letter queue")


@router.post("/failed-messages/{message_id}/retry")
async def retry_failed_message(
    message_id: str,
    current_user: UserResponse = Depends(get_current_admin_user),
):
    """Retry a failed message from the dead letter queue."""
    try:
        record = await db.fetchrow(
            "SELECT * FROM failed_messages WHERE id = $1", message_id
        )
        if not record:
            raise HTTPException(status_code=404, detail="Failed message not found")
        payload = record["payload"]
        if not payload:
            raise HTTPException(status_code=400, detail="No payload to retry")

        # payload is JSONB — already a dict from asyncpg
        if isinstance(payload, str):
            payload = json.loads(payload)

        # Upsert into messages
        await db.execute(
            """INSERT INTO messages (telegram_message_id, group_id, sender_id, sender_name, content,
                   media_type, media_url, reply_to_message_id, topic_id, sent_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
               ON CONFLICT (telegram_message_id, group_id) DO NOTHING""",
            payload.get("telegram_message_id"),
            payload.get("group_id"),
            payload.get("sender_id"),
            payload.get("sender_name"),
            payload.get("content"),
            payload.get("media_type", "text"),
            payload.get("media_url"),
            payload.get("reply_to_message_id"),
            payload.get("topic_id"),
            payload.get("sent_at"),
        )

        await db.execute(
            "UPDATE failed_messages SET resolved = TRUE, resolved_at = $1 WHERE id = $2",
            datetime.now(timezone.utc), message_id,
        )
        return {"success": True, "message": "Message retried and resolved"}
    except HTTPException:
        raise
    except Exception as e:
        # Increment retry count
        try:
            await db.execute(
                "UPDATE failed_messages SET retry_count = retry_count + 1 WHERE id = $1",
                message_id,
            )
        except Exception:
            pass
        logger.error("retry_failed_message error: %s", e)
        raise HTTPException(status_code=500, detail="Retry failed")


@router.get("/users", response_model=List[UserResponse])
async def get_all_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    current_user: UserResponse = Depends(get_current_admin_user),
):
    """Get all users (admin only)"""
    try:
        offset = (page - 1) * page_size
        rows = await db.fetch(
            "SELECT * FROM users ORDER BY created_at DESC LIMIT $1 OFFSET $2",
            page_size, offset,
        )
        return [UserResponse(**dict(u)) for u in rows]
    except Exception as e:
        logger.error("get_all_users error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to fetch users")


@router.patch("/users/{user_id}/role")
async def update_user_role(
    user_id: str,
    role: UserRole = Query(...),
    current_user: UserResponse = Depends(get_current_admin_user),
):
    """Update user role (admin only)"""
    # Prevent self-role-change
    if str(current_user.id) == user_id:
        raise HTTPException(status_code=400, detail="Cannot change your own role")

    try:
        uid = int(user_id)
        check = await db.fetchrow("SELECT id FROM users WHERE id = $1", uid)
        if not check:
            raise HTTPException(status_code=404, detail="User not found")

        result = await db.fetchrow(
            "UPDATE users SET role = $1 WHERE id = $2 RETURNING id",
            role.value, uid,
        )

        if not result:
            raise HTTPException(status_code=500, detail="Failed to update user role")

        return {"success": True, "user_id": user_id, "new_role": role.value}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("update_user_role error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to update user role")


@router.get("/admin-credentials")
async def get_admin_credentials(
    current_user: UserResponse = Depends(get_current_admin_user),
):
    """List all admin credentials (phone/username pairs) - admin only"""
    try:
        rows = await db.fetch(
            "SELECT id, phone_number, username, added_by_user_id, created_at FROM admin_credentials ORDER BY created_at DESC"
        )
        credentials = []
        for row in rows:
            cred_dict = dict(row)
            # If added_by_user_id exists, fetch the user's username for display
            if cred_dict.get("added_by_user_id"):
                added_by = await db.fetchrow(
                    "SELECT username FROM users WHERE id = $1",
                    cred_dict["added_by_user_id"]
                )
                cred_dict["added_by_username"] = added_by.get("username") if added_by else None
            credentials.append(cred_dict)
        return {"data": credentials}
    except Exception as e:
        logger.error("get_admin_credentials error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to fetch admin credentials")


@router.post("/admin-credentials")
async def add_admin_credential(
    phone_number: str | None = Query(None),
    username: str | None = Query(None),
    current_user: UserResponse = Depends(get_current_admin_user),
):
    """Add a new admin credential (phone or username) - admin only"""
    if not phone_number and not username:
        raise HTTPException(status_code=400, detail="Must provide phone_number or username")

    try:
        result = await db.fetchrow(
            """INSERT INTO admin_credentials (phone_number, username, added_by_user_id)
               VALUES ($1, $2, $3)
               RETURNING id, phone_number, username, created_at""",
            phone_number or None,
            username or None,
            current_user.id,
        )

        if not result:
            raise HTTPException(status_code=500, detail="Failed to add admin credential")

        logger.info("Admin credential added by %s: phone=%s, username=%s",
                   current_user.username, phone_number, username)

        return {"success": True, "credential": dict(result)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("add_admin_credential error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to add admin credential")


@router.delete("/admin-credentials/{credential_id}")
async def remove_admin_credential(
    credential_id: int,
    current_user: UserResponse = Depends(get_current_admin_user),
):
    """Remove an admin credential - admin only. Prevents removing the last credential."""
    try:
        # Safety check: prevent removing the last admin credential
        count = await db.fetchval("SELECT COUNT(*) FROM admin_credentials")
        if count <= 1:
            raise HTTPException(status_code=400, detail="Cannot remove the last admin credential")

        # Get credential info before deletion (for logging)
        cred = await db.fetchrow(
            "SELECT phone_number, username FROM admin_credentials WHERE id = $1",
            credential_id
        )

        if not cred:
            raise HTTPException(status_code=404, detail="Admin credential not found")

        # Delete the credential
        result = await db.execute(
            "DELETE FROM admin_credentials WHERE id = $1",
            credential_id
        )

        logger.info("Admin credential removed by %s: phone=%s, username=%s",
                   current_user.username, cred.get("phone_number"), cred.get("username"))

        return {"success": True, "message": "Admin credential removed"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("remove_admin_credential error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to remove admin credential")
