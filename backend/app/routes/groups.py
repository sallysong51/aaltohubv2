"""
Telegram groups routes

DB `groups` table columns:
  id (bigint PK = telegram group ID), name, type, photo_url, member_count,
  has_topics, visibility, crawl_status, crawl_enabled, last_crawled_at,
  last_error, registered_by (FK users.id), created_at
"""
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
    UserResponse, GroupVisibility, UserRole
)
from app.auth import get_current_user, get_current_admin_user
from app.database import db
from app.telegram_client import telegram_manager


router = APIRouter(prefix="/groups", tags=["Groups"])


async def _filter_accessible_group_ids(group_ids: list, current_user: UserResponse) -> list:
    """Return only group IDs the user is allowed to access (public or member of private)."""
    if not group_ids:
        return []
    int_ids = [int(gid) for gid in group_ids]
    rows = await db.fetch(
        "SELECT id, visibility FROM groups WHERE id = ANY($1::bigint[])", int_ids
    )
    if not rows:
        return []

    public_ids = []
    private_ids = []
    for g in rows:
        if g["visibility"] == GroupVisibility.PRIVATE.value:
            private_ids.append(g["id"])
        else:
            public_ids.append(g["id"])

    accessible = [str(gid) for gid in public_ids]

    if private_ids:
        membership_rows = await db.fetch(
            "SELECT group_id FROM user_groups WHERE user_id = $1 AND group_id = ANY($2::bigint[])",
            current_user.id, private_ids,
        )
        accessible.extend(str(m["group_id"]) for m in membership_rows)

    return accessible


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
):
    """Get all Telegram groups user is member of"""
    try:
        # Get groups from Telegram
        groups = await telegram_manager.get_user_groups(current_user.id)

        # Get registered group IDs from database (groups.id = telegram group ID)
        rows = await db.fetch("SELECT id FROM groups")
        registered_ids = {r["id"] for r in rows}

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
):
    """Register selected groups"""
    try:
        registered_groups = []

        for group_data in request.groups:
            telegram_id = group_data.telegram_id

            # Check if group already exists (groups.id = telegram group ID)
            existing = await db.fetchrow("SELECT id FROM groups WHERE id = $1", telegram_id)
            if existing:
                continue

            # Wrap all per-group DB ops in a transaction to prevent orphaned rows
            async with db.pool.acquire() as conn:
                async with conn.transaction():
                    # Insert group (map API fields → DB columns)
                    await conn.execute(
                        """INSERT INTO groups (id, name, type, member_count, visibility, registered_by, crawl_enabled)
                           VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                        telegram_id,
                        group_data.title,
                        group_data.group_type or "group",
                        group_data.member_count,
                        group_data.visibility or GroupVisibility.PUBLIC.value,
                        current_user.id,
                        True,
                    )

                    # Add to user's group membership
                    await conn.execute(
                        "INSERT INTO user_groups (user_id, group_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                        current_user.id, telegram_id,
                    )

                    # Create crawler_status row for this group
                    await conn.execute(
                        """INSERT INTO crawler_status (group_id, status, is_enabled, error_count, initial_crawl_progress, initial_crawl_total)
                           VALUES ($1, 'inactive', TRUE, 0, 0, 0) ON CONFLICT (group_id) DO NOTHING""",
                        telegram_id,
                    )

            # Build API response from the inserted row (outside txn — read committed)
            updated = await db.fetchrow("SELECT * FROM groups WHERE id = $1", telegram_id)
            registered_groups.append(TelegramGroupResponse(**_db_group_to_api(dict(updated))))

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
):
    """Get user's registered groups"""
    try:
        follows = await db.fetch(
            "SELECT group_id FROM user_groups WHERE user_id = $1", current_user.id
        )
        if not follows:
            return []

        group_ids = [f["group_id"] for f in follows]
        groups = await db.fetch(
            "SELECT * FROM groups WHERE id = ANY($1::bigint[])", group_ids
        )

        return [TelegramGroupResponse(**_db_group_to_api(dict(g))) for g in groups]
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
):
    """Get messages from multiple groups in a single request."""
    try:
        ids = [gid.strip() for gid in group_ids.split(",") if gid.strip()]
        if not ids:
            return MessagesListResponse(messages=[], total=0, page=page, page_size=page_size, has_more=False)

        # IDOR fix: filter out groups the user cannot access
        ids = await _filter_accessible_group_ids(ids, current_user)
        if not ids:
            return MessagesListResponse(messages=[], total=0, page=page, page_size=page_size, has_more=False)

        int_ids = [int(i) for i in ids]
        offset = (page - 1) * page_size

        if topic_id is not None:
            total = await db.fetchval(
                "SELECT COUNT(*) FROM messages WHERE group_id = ANY($1::bigint[]) AND is_deleted = FALSE AND topic_id = $2",
                int_ids, topic_id,
            )
            messages_rows = await db.fetch(
                """SELECT * FROM messages
                   WHERE group_id = ANY($1::bigint[]) AND is_deleted = FALSE AND topic_id = $2
                   ORDER BY sent_at DESC LIMIT $3 OFFSET $4""",
                int_ids, topic_id, page_size, offset,
            )
        else:
            total = await db.fetchval(
                "SELECT COUNT(*) FROM messages WHERE group_id = ANY($1::bigint[]) AND is_deleted = FALSE",
                int_ids,
            )
            messages_rows = await db.fetch(
                """SELECT * FROM messages
                   WHERE group_id = ANY($1::bigint[]) AND is_deleted = FALSE
                   ORDER BY sent_at DESC LIMIT $2 OFFSET $3""",
                int_ids, page_size, offset,
            )

        messages = [MessageResponse(**dict(m)) for m in messages_rows]

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
):
    """Get topics/threads for a group (Telegram forum groups)"""
    try:
        gid = int(group_id)
        group = await db.fetchrow("SELECT id, visibility FROM groups WHERE id = $1", gid)
        if not group:
            raise HTTPException(status_code=404, detail="Group not found")

        # IDOR fix: check private group membership
        if group["visibility"] == GroupVisibility.PRIVATE.value:
            access = await db.fetchrow(
                "SELECT id FROM user_groups WHERE user_id = $1 AND group_id = $2",
                current_user.id, gid,
            )
            if not access:
                raise HTTPException(status_code=403, detail="Access denied: Private group")

        # Query topics from recent messages (limit to 5000 to avoid memory issues)
        topics_rows = await db.fetch(
            """SELECT topic_id FROM messages
               WHERE group_id = $1 AND is_deleted = FALSE AND topic_id IS NOT NULL
               ORDER BY sent_at DESC LIMIT 5000""",
            gid,
        )

        if not topics_rows:
            return []

        # Deduplicate and count messages per topic
        topic_map: Dict[int, dict] = {}
        for row in topics_rows:
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
):
    """Get messages from a specific group"""
    try:
        gid = int(group_id)
        group = await db.fetchrow("SELECT visibility FROM groups WHERE id = $1", gid)
        if not group:
            raise HTTPException(status_code=404, detail="Group not found")

        if group["visibility"] == GroupVisibility.PRIVATE.value:
            access = await db.fetchrow(
                "SELECT id FROM user_groups WHERE user_id = $1 AND group_id = $2",
                current_user.id, gid,
            )
            if not access:
                raise HTTPException(status_code=403, detail="Access denied: Private group")

        offset = (page - 1) * page_size

        if topic_id is not None:
            total = await db.fetchval(
                "SELECT COUNT(*) FROM messages WHERE group_id = $1 AND is_deleted = FALSE AND topic_id = $2",
                gid, topic_id,
            )
            messages_rows = await db.fetch(
                """SELECT * FROM messages
                   WHERE group_id = $1 AND is_deleted = FALSE AND topic_id = $2
                   ORDER BY sent_at DESC LIMIT $3 OFFSET $4""",
                gid, topic_id, page_size, offset,
            )
        else:
            total = await db.fetchval(
                "SELECT COUNT(*) FROM messages WHERE group_id = $1 AND is_deleted = FALSE",
                gid,
            )
            messages_rows = await db.fetch(
                """SELECT * FROM messages
                   WHERE group_id = $1 AND is_deleted = FALSE
                   ORDER BY sent_at DESC LIMIT $2 OFFSET $3""",
                gid, page_size, offset,
            )

        messages = [MessageResponse(**dict(m)) for m in messages_rows]

        return MessagesListResponse(
            messages=messages, total=total, page=page, page_size=page_size,
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
):
    """Get a single group by ID"""
    try:
        gid = int(group_id)
        group = await db.fetchrow("SELECT * FROM groups WHERE id = $1", gid)
        if not group:
            raise HTTPException(status_code=404, detail="Group not found")

        g = dict(group)
        if g["visibility"] == GroupVisibility.PRIVATE.value:
            if g["registered_by"] != current_user.id:
                follow = await db.fetchrow(
                    "SELECT id FROM user_groups WHERE user_id = $1 AND group_id = $2",
                    current_user.id, gid,
                )
                if not follow:
                    raise HTTPException(status_code=403, detail="Access denied")

        return TelegramGroupResponse(**_db_group_to_api(g))
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Groups API error: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/{group_id}/invite-links")
async def get_invite_links(
    group_id: str,
    current_user: UserResponse = Depends(get_current_user),
):
    """Get all invite links for a group"""
    try:
        gid = int(group_id)
        group = await db.fetchrow(
            "SELECT id FROM groups WHERE id = $1 AND registered_by = $2",
            gid, current_user.id,
        )
        if not group:
            raise HTTPException(status_code=404, detail="Group not found or you don't have permission")

        invites = await db.fetch(
            "SELECT * FROM private_group_invites WHERE group_id = $1 ORDER BY created_at DESC",
            gid,
        )

        return [dict(i) for i in invites]
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
):
    """Create an invite link for a private group"""
    try:
        gid = int(group_id)
        group = await db.fetchrow(
            "SELECT id, visibility FROM groups WHERE id = $1 AND registered_by = $2",
            gid, current_user.id,
        )
        if not group:
            raise HTTPException(status_code=404, detail="Group not found or you don't have permission")

        if group["visibility"] != GroupVisibility.PRIVATE.value:
            raise HTTPException(status_code=400, detail="Can only create invite links for private groups")

        token = secrets.token_urlsafe(32)

        expires_ts = None
        if expires_at:
            expires_ts = datetime.fromisoformat(expires_at)

        await db.execute(
            """INSERT INTO private_group_invites (group_id, token, created_by, expires_at, max_uses)
               VALUES ($1, $2, $3, $4, $5)""",
            gid, token, current_user.id, expires_ts, max_uses,
        )

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
):
    """Accept an invite link and gain access to private group"""
    try:
        invite = await db.fetchrow(
            "SELECT * FROM private_group_invites WHERE token = $1", token
        )
        if not invite:
            raise HTTPException(status_code=404, detail="Invite not found")

        invite_data = dict(invite)

        if invite_data.get("is_revoked"):
            raise HTTPException(status_code=400, detail="Invite link has been revoked")

        if invite_data.get("expires_at"):
            if datetime.now(timezone.utc) > invite_data["expires_at"]:
                raise HTTPException(status_code=400, detail="Invite link has expired")

        # Atomic increment: only increment used_count if below max_uses.
        current_count = invite_data.get("used_count", 0)
        max_uses = invite_data.get("max_uses")

        if max_uses and current_count >= max_uses:
            raise HTTPException(status_code=400, detail="Invite link has reached maximum uses")

        # Atomic conditional update: only succeeds if used_count hasn't changed
        update_result = await db.fetchrow(
            """UPDATE private_group_invites SET used_count = $1
               WHERE id = $2 AND used_count = $3 RETURNING id""",
            current_count + 1, invite_data["id"], current_count,
        )

        if not update_result:
            raise HTTPException(status_code=409, detail="Invite was used concurrently, please try again")

        # Add user to group if not already a member
        await db.execute(
            "INSERT INTO user_groups (user_id, group_id) VALUES ($1, $2) ON CONFLICT (user_id, group_id) DO NOTHING",
            current_user.id, invite_data["group_id"],
        )

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
):
    """Revoke an invite link"""
    try:
        gid = int(group_id)
        group = await db.fetchrow(
            "SELECT id FROM groups WHERE id = $1 AND registered_by = $2",
            gid, current_user.id,
        )
        if not group:
            raise HTTPException(status_code=404, detail="Group not found or you don't have permission")

        result = await db.fetchrow(
            """UPDATE private_group_invites SET is_revoked = TRUE, revoked_at = $1
               WHERE id = $2 AND group_id = $3 RETURNING id""",
            datetime.now(timezone.utc), invite_id, gid,
        )

        if not result:
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
):
    """Update group visibility (public/private)"""
    try:
        gid = int(group_id)
        group = await db.fetchrow("SELECT * FROM groups WHERE id = $1", gid)
        if not group:
            raise HTTPException(status_code=404, detail="Group not found")

        g = dict(group)
        if g["registered_by"] != current_user.id and current_user.role != UserRole.ADMIN:
            raise HTTPException(status_code=403, detail="Only the owner or an admin can change visibility")

        await db.execute(
            "UPDATE groups SET visibility = $1 WHERE id = $2",
            visibility.value, gid,
        )

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
):
    """Delete a group (private groups: owner only, public groups: admin only)"""
    try:
        gid = int(group_id)
        group = await db.fetchrow("SELECT * FROM groups WHERE id = $1", gid)
        if not group:
            raise HTTPException(status_code=404, detail="Group not found")

        g = dict(group)
        if g["visibility"] == GroupVisibility.PRIVATE.value:
            if g["registered_by"] != current_user.id:
                raise HTTPException(status_code=403, detail="Only the group owner can delete private groups")
        else:
            if current_user.role != UserRole.ADMIN:
                raise HTTPException(status_code=403, detail="Only admins can delete public groups")

        await db.execute("DELETE FROM groups WHERE id = $1", gid)

        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Groups API error: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")
