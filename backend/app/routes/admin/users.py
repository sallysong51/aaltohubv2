"""Admin user management and statistics routes."""
import asyncio
import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List
from datetime import datetime, timedelta, timezone
from app.models import UserResponse, UserRole
from app.auth import get_current_admin_user
from app.database import db

logger = logging.getLogger(__name__)

router = APIRouter()


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
