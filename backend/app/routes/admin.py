"""
Admin-only routes
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List
from datetime import datetime, timedelta
from app.models import (
    TelegramGroupResponse, MessagesListResponse,
    MessageResponse, UserResponse
)
from app.auth import get_current_admin_user
from app.database import get_db


router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get("/groups", response_model=List[TelegramGroupResponse])
async def get_all_groups(
    current_user: UserResponse = Depends(get_current_admin_user),
    db = Depends(get_db)
):
    """Get all registered groups (admin only)"""
    try:
        groups = db.table("groups").select("*").order("created_at", desc=True).execute()
        return [TelegramGroupResponse(**g) for g in groups.data] if groups.data else []
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
        date_threshold = datetime.utcnow() - timedelta(days=days)
        
        # Calculate offset
        offset = (page - 1) * page_size
        
        # Get total count
        count_response = db.table("messages").select("id", count="exact").eq("group_id", group_id).gte("sent_at", date_threshold.isoformat()).execute()
        total = count_response.count if hasattr(count_response, 'count') else 0
        
        # Get messages
        messages_response = db.table("messages").select("*").eq("group_id", group_id).gte("sent_at", date_threshold.isoformat()).order("sent_at", desc=False).range(offset, offset + page_size - 1).execute()
        
        messages = [MessageResponse(**m) for m in messages_response.data] if messages_response.data else []
        
        return MessagesListResponse(
            messages=messages,
            total=total,
            page=page,
            page_size=page_size,
            has_more=offset + page_size < total
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/failed-invites")
async def get_failed_invites(
    current_user: UserResponse = Depends(get_current_admin_user),
    db = Depends(get_db)
):
    """Get groups where admin invite failed (admin only)"""
    try:
        failed = db.table("groups").select("*").eq("admin_invited", False).is_("admin_invite_error", "not.null").execute()
        
        result = []
        for group in failed.data if failed.data else []:
            result.append({
                "id": group["id"],
                "telegram_id": group["telegram_id"],
                "title": group["title"],
                "error": group["admin_invite_error"],
                "created_at": group["created_at"]
            })
        
        return {"failed_invites": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_stats(
    current_user: UserResponse = Depends(get_current_admin_user),
    db = Depends(get_db)
):
    """Get platform statistics (admin only)"""
    try:
        # Count users
        users_response = db.table("users").select("id", count="exact").execute()
        total_users = users_response.count if hasattr(users_response, 'count') else 0
        
        # Count groups
        groups_response = db.table("groups").select("id", count="exact").execute()
        total_groups = groups_response.count if hasattr(groups_response, 'count') else 0
        
        # Count public groups
        public_groups_response = db.table("groups").select("id", count="exact").eq("visibility", "public").execute()
        total_public_groups = public_groups_response.count if hasattr(public_groups_response, 'count') else 0
        
        # Count messages
        messages_response = db.table("messages").select("id", count="exact").execute()
        total_messages = messages_response.count if hasattr(messages_response, 'count') else 0
        
        # Count messages in last 24 hours
        yesterday = datetime.utcnow() - timedelta(days=1)
        recent_messages_response = db.table("messages").select("id", count="exact").gte("sent_at", yesterday.isoformat()).execute()
        recent_messages = recent_messages_response.count if hasattr(recent_messages_response, 'count') else 0
        
        return {
            "total_users": total_users,
            "total_groups": total_groups,
            "total_public_groups": total_public_groups,
            "total_messages": total_messages,
            "messages_last_24h": recent_messages
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/crawler-status", response_model=List[dict])
async def get_crawler_status(
    current_user: UserResponse = Depends(get_current_admin_user),
    db = Depends(get_db)
):
    """Get crawler status for all groups (admin only)"""
    try:
        # Join crawler_status with groups
        result = db.rpc("get_crawler_status_with_groups").execute()
        return result.data if result.data else []
    except Exception as e:
        # Fallback: get crawler_status only
        try:
            status = db.table("crawler_status").select("*").execute()
            return status.data if status.data else []
        except:
            raise HTTPException(status_code=500, detail=str(e))


@router.post("/crawler-status/{group_id}/toggle")
async def toggle_crawler(
    group_id: str,
    is_enabled: bool,
    current_user: UserResponse = Depends(get_current_admin_user),
    db = Depends(get_db)
):
    """Toggle crawler on/off for a group (admin only)"""
    try:
        result = db.table("crawler_status").update({
            "is_enabled": is_enabled,
            "updated_at": datetime.utcnow().isoformat()
        }).eq("group_id", group_id).execute()
        
        if not result.data:
            raise HTTPException(status_code=404, detail="Crawler status not found")
        
        return {"success": True, "is_enabled": is_enabled}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
        
        result = query.execute()
        return result.data if result.data else []
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/user-activity", response_model=List[dict])
async def get_user_activity(
    current_user: UserResponse = Depends(get_current_admin_user),
    db = Depends(get_db)
):
    """Get user activity statistics (admin only)"""
    try:
        result = db.table("user_statistics").select("*").execute()
        return result.data if result.data else []
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/group-statistics", response_model=List[dict])
async def get_group_statistics(
    current_user: UserResponse = Depends(get_current_admin_user),
    db = Depends(get_db)
):
    """Get group statistics (admin only)"""
    try:
        result = db.table("group_statistics").select("*").execute()
        return result.data if result.data else []
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
