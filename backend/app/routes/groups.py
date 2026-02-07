"""
Telegram groups routes

DB `groups` table columns:
  id (bigint PK = telegram group ID), name, type, photo_url, member_count,
  has_topics, visibility, crawl_status, crawl_enabled, last_crawled_at,
  last_error, registered_by (FK users.id), created_at
"""
import asyncio
import logging
import secrets
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Dict

logger = logging.getLogger(__name__)
from app.models import (
    TelegramGroupInfo, TelegramGroupResponse,
    RegisterGroupsRequest, RegisterGroupsResponse,
    MessagesListResponse, MessageResponse,
    UserResponse, GroupVisibility
)
from app.auth import get_current_user, get_current_admin_user
from app.database import get_db
from app.telegram_client import telegram_manager


router = APIRouter(prefix="/groups", tags=["Groups"])


def _db_group_to_api(g: Dict) -> Dict:
    """Map DB groups row → API response fields expected by the frontend.

    DB has: id, name, type, photo_url, member_count, visibility, registered_by, created_at
    API returns: id, telegram_id, title, group_type, visibility, etc.
    """
    return {
        "id": str(g["id"]),
        "telegram_id": g["id"],
        "title": g.get("name") or "Unknown",
        "username": g.get("username"),
        "member_count": g.get("member_count"),
        "group_type": g.get("type"),
        "visibility": g.get("visibility", "public"),
        "invite_link": g.get("invite_link"),
        "description": g.get("description"),
        "registered_by": g.get("registered_by"),
        "created_at": g.get("created_at"),
    }


@router.get("/my-telegram-groups", response_model=List[TelegramGroupInfo])
async def get_my_groups(
    current_user: UserResponse = Depends(get_current_user),
    db = Depends(get_db)
):
    """Get all Telegram groups user is member of"""
    try:
        # Get groups from Telegram
        groups = await telegram_manager.get_user_groups(current_user.id)

        # Get registered group IDs from database (groups.id = telegram group ID)
        registered_response = await asyncio.to_thread(lambda: db.table("groups").select("id").execute())
        registered_ids = {g["id"] for g in registered_response.data} if registered_response.data else set()

        # Mark registered groups
        result = []
        for group in groups:
            group_info = TelegramGroupInfo(
                **group,
                is_registered=group["telegram_id"] in registered_ids
            )
            result.append(group_info)

        return result
    except Exception as e:
        logger.error("Groups API error: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/register", response_model=RegisterGroupsResponse)
async def register_groups(
    request: RegisterGroupsRequest,
    current_user: UserResponse = Depends(get_current_user),
    db = Depends(get_db)
):
    """Register selected groups"""
    try:
        registered_groups = []

        for group_data in request.groups:
            telegram_id = group_data.telegram_id

            # Check if group already exists (groups.id = telegram group ID)
            existing = await asyncio.to_thread(lambda tid=telegram_id: db.table("groups").select("id").eq("id", tid).execute())

            if existing.data and len(existing.data) > 0:
                continue

            # Insert group (map API fields → DB columns)
            # DB uses: name, type (not title, group_type)
            group_insert = {
                "id": telegram_id,
                "name": group_data.title,
                "type": group_data.group_type or "group",
                "member_count": group_data.member_count,
                "visibility": group_data.visibility or GroupVisibility.PUBLIC.value,
                "registered_by": current_user.id,
                "crawl_enabled": True,
            }

            new_group = await asyncio.to_thread(lambda gi=group_insert: db.table("groups").insert(gi).execute())
            group_id = new_group.data[0]["id"]

            # Add to user's group membership
            await asyncio.to_thread(lambda uid=current_user.id, gid=group_id: db.table("user_groups").insert({
                "user_id": uid,
                "group_id": gid,
            }).execute())

            # Create crawler_status row for this group
            try:
                await asyncio.to_thread(lambda gid=group_id: db.table("crawler_status").insert({
                    "group_id": gid,
                    "status": "inactive",
                    "is_enabled": True,
                    "error_count": 0,
                    "initial_crawl_progress": 0,
                    "initial_crawl_total": 0,
                }).execute())
            except Exception:
                pass  # crawler_status table may not exist yet

            # Build API response from the inserted row
            updated = await asyncio.to_thread(lambda gid=group_id: db.table("groups").select("*").eq("id", gid).execute())
            registered_groups.append(TelegramGroupResponse(**_db_group_to_api(updated.data[0])))

        return RegisterGroupsResponse(
            success=True,
            registered_groups=registered_groups,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Groups API error: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/registered", response_model=List[TelegramGroupResponse])
async def get_registered_groups(
    current_user: UserResponse = Depends(get_current_user),
    db = Depends(get_db)
):
    """Get user's registered groups"""
    try:
        follows = await asyncio.to_thread(lambda: db.table("user_groups").select("group_id").eq("user_id", current_user.id).execute())

        if not follows.data or len(follows.data) == 0:
            return []

        group_ids = [f["group_id"] for f in follows.data]
        groups = await asyncio.to_thread(lambda: db.table("groups").select("*").in_("id", group_ids).execute())

        return [TelegramGroupResponse(**_db_group_to_api(g)) for g in groups.data] if groups.data else []
    except Exception as e:
        logger.error("Groups API error: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/messages/aggregated", response_model=MessagesListResponse)
async def get_aggregated_messages(
    group_ids: str = Query(..., description="Comma-separated group IDs"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    topic_id: int = Query(None),
    current_user: UserResponse = Depends(get_current_user),
    db = Depends(get_db)
):
    """Get messages from multiple groups in a single request."""
    try:
        ids = [gid.strip() for gid in group_ids.split(",") if gid.strip()]
        if not ids:
            return MessagesListResponse(messages=[], total=0, page=page, page_size=page_size, has_more=False)

        offset = (page - 1) * page_size

        count_q = db.table("messages").select("id", count="exact").in_("group_id", ids).eq("is_deleted", False)
        msg_q = db.table("messages").select("*").in_("group_id", ids).eq("is_deleted", False)

        if topic_id is not None:
            count_q = count_q.eq("topic_id", topic_id)
            msg_q = msg_q.eq("topic_id", topic_id)

        count_response, messages_response = await asyncio.gather(
            asyncio.to_thread(lambda: count_q.execute()),
            asyncio.to_thread(lambda: msg_q.order("sent_at", desc=True).range(offset, offset + page_size - 1).execute()),
        )

        total = count_response.count if hasattr(count_response, 'count') and count_response.count else 0
        messages = [MessageResponse(**m) for m in messages_response.data] if messages_response.data else []

        return MessagesListResponse(
            messages=messages, total=total, page=page, page_size=page_size,
            has_more=offset + page_size < total,
        )
    except Exception as e:
        logger.error("get_aggregated_messages error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to fetch aggregated messages")


@router.get("/{group_id}/topics")
async def get_group_topics(
    group_id: str,
    current_user: UserResponse = Depends(get_current_user),
    db = Depends(get_db)
):
    """Get topics/threads for a group (Telegram forum groups)"""
    try:
        group_response = await asyncio.to_thread(lambda: db.table("groups").select("id").eq("id", group_id).execute())
        if not group_response.data:
            raise HTTPException(status_code=404, detail="Group not found")

        # Query topics from recent messages (limit to 5000 to avoid memory issues on large groups)
        topics_response = await asyncio.to_thread(lambda: db.table("messages").select(
            "topic_id"
        ).eq("group_id", group_id).eq("is_deleted", False).not_.is_("topic_id", "null").order("sent_at", desc=True).limit(5000).execute())

        if not topics_response.data:
            return []

        # Deduplicate and count messages per topic
        topic_map: Dict[int, dict] = {}
        for row in topics_response.data:
            tid = row["topic_id"]
            if tid not in topic_map:
                topic_map[tid] = {
                    "topic_id": tid,
                    "topic_title": f"Topic {tid}",
                    "message_count": 0,
                }
            topic_map[tid]["message_count"] += 1

        return sorted(topic_map.values(), key=lambda t: t["message_count"], reverse=True)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Groups API error: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/{group_id}/messages", response_model=MessagesListResponse)
async def get_group_messages(
    group_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    topic_id: int = Query(None, description="Filter by topic ID"),
    current_user: UserResponse = Depends(get_current_user),
    db = Depends(get_db)
):
    """Get messages from a specific group"""
    try:
        group_response = await asyncio.to_thread(lambda: db.table("groups").select("visibility").eq("id", group_id).execute())
        if not group_response.data:
            raise HTTPException(status_code=404, detail="Group not found")

        group = group_response.data[0]

        if group["visibility"] == GroupVisibility.PRIVATE.value:
            access_response = await asyncio.to_thread(lambda: db.table("user_groups").select("id").eq("user_id", current_user.id).eq("group_id", group_id).execute())
            if not access_response.data:
                raise HTTPException(status_code=403, detail="Access denied: Private group")

        offset = (page - 1) * page_size

        count_q = db.table("messages").select("id", count="exact").eq("group_id", group_id).eq("is_deleted", False)
        msg_q = db.table("messages").select("*").eq("group_id", group_id).eq("is_deleted", False)

        if topic_id is not None:
            count_q = count_q.eq("topic_id", topic_id)
            msg_q = msg_q.eq("topic_id", topic_id)

        count_response = await asyncio.to_thread(lambda: count_q.execute())
        total = count_response.count if hasattr(count_response, 'count') else 0

        messages_response = await asyncio.to_thread(lambda: msg_q.order("sent_at", desc=True).range(offset, offset + page_size - 1).execute())

        messages = [MessageResponse(**m) for m in messages_response.data] if messages_response.data else []

        return MessagesListResponse(
            messages=messages,
            total=total,
            page=page,
            page_size=page_size,
            has_more=offset + page_size < total,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Groups API error: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/{group_id}")
async def get_group(
    group_id: str,
    current_user: UserResponse = Depends(get_current_user),
    db = Depends(get_db)
):
    """Get a single group by ID"""
    try:
        group_response = await asyncio.to_thread(lambda: db.table("groups").select("*").eq("id", group_id).execute())

        if not group_response.data or len(group_response.data) == 0:
            raise HTTPException(status_code=404, detail="Group not found")

        group = group_response.data[0]

        if group["visibility"] == GroupVisibility.PRIVATE.value:
            if group["registered_by"] != current_user.id:
                follow = await asyncio.to_thread(lambda: db.table("user_groups").select("id").eq("user_id", current_user.id).eq("group_id", group_id).execute())
                if not follow.data:
                    raise HTTPException(status_code=403, detail="Access denied")

        return TelegramGroupResponse(**_db_group_to_api(group))
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Groups API error: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/{group_id}/invite-links")
async def get_invite_links(
    group_id: str,
    current_user: UserResponse = Depends(get_current_user),
    db = Depends(get_db)
):
    """Get all invite links for a group"""
    try:
        group = await asyncio.to_thread(lambda: db.table("groups").select("*").eq("id", group_id).eq("registered_by", current_user.id).execute())

        if not group.data:
            raise HTTPException(status_code=404, detail="Group not found or you don't have permission")

        invites = await asyncio.to_thread(lambda: db.table("private_group_invites").select("*").eq("group_id", group_id).order("created_at", desc=True).execute())

        return invites.data if invites.data else []
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Groups API error: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/{group_id}/invite-link")
async def create_invite_link(
    group_id: str,
    expires_at: str = None,
    max_uses: int = None,
    current_user: UserResponse = Depends(get_current_user),
    db = Depends(get_db)
):
    """Create an invite link for a private group"""
    try:
        group = await asyncio.to_thread(lambda: db.table("groups").select("*").eq("id", group_id).eq("registered_by", current_user.id).execute())

        if not group.data:
            raise HTTPException(status_code=404, detail="Group not found or you don't have permission")

        group_data_row = group.data[0]

        if group_data_row["visibility"] != GroupVisibility.PRIVATE.value:
            raise HTTPException(status_code=400, detail="Can only create invite links for private groups")

        token = secrets.token_urlsafe(32)

        invite_data = {
            "group_id": group_id,
            "token": token,
            "created_by": current_user.id,
            "expires_at": expires_at,
            "max_uses": max_uses,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        await asyncio.to_thread(lambda: db.table("private_group_invites").insert(invite_data).execute())

        return {
            "success": True,
            "invite_link": f"/invite/{token}",
            "token": token,
            "expires_at": expires_at,
            "max_uses": max_uses,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Groups API error: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/invite/{token}/accept")
async def accept_invite(
    token: str,
    current_user: UserResponse = Depends(get_current_user),
    db = Depends(get_db)
):
    """Accept an invite link and gain access to private group"""
    try:
        invite = await asyncio.to_thread(lambda: db.table("private_group_invites").select("*").eq("token", token).single().execute())

        if not invite.data:
            raise HTTPException(status_code=404, detail="Invite not found")

        invite_data = invite.data

        if invite_data.get("is_revoked"):
            raise HTTPException(status_code=400, detail="Invite link has been revoked")

        if invite_data.get("expires_at"):
            expires_at = datetime.fromisoformat(invite_data["expires_at"])
            if datetime.now(timezone.utc) > expires_at:
                raise HTTPException(status_code=400, detail="Invite link has expired")

        # Atomic increment: only increment used_count if below max_uses.
        # This prevents TOCTOU race where two concurrent accepts both pass
        # the max_uses check and both succeed.
        current_count = invite_data.get("used_count", 0)
        max_uses = invite_data.get("max_uses")

        if max_uses and current_count >= max_uses:
            raise HTTPException(status_code=400, detail="Invite link has reached maximum uses")

        # Atomic conditional update: only succeeds if used_count hasn't changed
        update_result = await asyncio.to_thread(lambda: db.table("private_group_invites").update({
            "used_count": current_count + 1,
        }).eq("id", invite_data["id"]).eq("used_count", current_count).execute())

        if not update_result.data:
            # Another request incremented first — retry check
            raise HTTPException(status_code=409, detail="Invite was used concurrently, please try again")

        existing = await asyncio.to_thread(lambda: db.table("user_groups").select("id").eq("user_id", current_user.id).eq("group_id", invite_data["group_id"]).execute())

        if not existing.data:
            await asyncio.to_thread(lambda: db.table("user_groups").insert({
                "user_id": current_user.id,
                "group_id": invite_data["group_id"],
            }).execute())

        return {"success": True, "group_id": invite_data["group_id"]}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Groups API error: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/{group_id}/invite-link/{invite_id}/revoke")
async def revoke_invite_link(
    group_id: str,
    invite_id: str,
    current_user: UserResponse = Depends(get_current_user),
    db = Depends(get_db)
):
    """Revoke an invite link"""
    try:
        group = await asyncio.to_thread(lambda: db.table("groups").select("*").eq("id", group_id).eq("registered_by", current_user.id).execute())

        if not group.data:
            raise HTTPException(status_code=404, detail="Group not found or you don't have permission")

        result = await asyncio.to_thread(lambda: db.table("private_group_invites").update({
            "is_revoked": True,
            "revoked_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", invite_id).eq("group_id", group_id).execute())

        if not result.data:
            raise HTTPException(status_code=404, detail="Invite not found")

        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Groups API error: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.patch("/{group_id}/visibility")
async def update_group_visibility(
    group_id: str,
    visibility: GroupVisibility = Query(...),
    current_user: UserResponse = Depends(get_current_user),
    db = Depends(get_db)
):
    """Update group visibility (public/private)"""
    try:
        # Allow owner or admin to change visibility
        group = await asyncio.to_thread(lambda: db.table("groups").select("*").eq("id", group_id).execute())

        if not group.data:
            raise HTTPException(status_code=404, detail="Group not found")

        group_row = group.data[0]

        if group_row["registered_by"] != current_user.id and current_user.role != "admin":
            raise HTTPException(status_code=403, detail="Only the owner or an admin can change visibility")

        await asyncio.to_thread(lambda: db.table("groups").update({
            "visibility": visibility.value,
        }).eq("id", group_id).execute())

        return {"success": True, "visibility": visibility.value}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Groups API error: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/{group_id}")
async def delete_group(
    group_id: str,
    current_user: UserResponse = Depends(get_current_user),
    db = Depends(get_db)
):
    """Delete a group (private groups: owner only, public groups: admin only)"""
    try:
        group = await asyncio.to_thread(lambda: db.table("groups").select("*").eq("id", group_id).execute())

        if not group.data:
            raise HTTPException(status_code=404, detail="Group not found")

        group_row = group.data[0]

        if group_row["visibility"] == GroupVisibility.PRIVATE.value:
            if group_row["registered_by"] != current_user.id:
                raise HTTPException(status_code=403, detail="Only the group owner can delete private groups")
        else:
            if current_user.role != "admin":
                raise HTTPException(status_code=403, detail="Only admins can delete public groups")

        await asyncio.to_thread(lambda: db.table("groups").delete().eq("id", group_id).execute())

        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Groups API error: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")
