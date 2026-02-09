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
    MessagesListResponse,
    UserResponse, GroupVisibility, UserRole
)
from app.auth import get_current_user, get_current_admin_user
from app.database import db
from app.telegram_client import telegram_manager, TelegramAuthError
from app.queries.groups import db_group_to_api, filter_accessible_group_ids
from app.queries.messages import fetch_messages_paginated
from telethon.errors import (
    FloodWaitError, ChannelPrivateError, ChatAdminRequiredError,
    InviteHashInvalidError, InviteHashExpiredError
)


router = APIRouter(prefix="/groups", tags=["Groups"])


async def _auto_join_admin_to_group(
    group_id: int, group_name: str, invite_link: str = None, username: str = None
) -> bool:
    """Auto-join admin to a group via invite link or username (non-blocking, best-effort)."""
    try:
        from app.live_crawler import live_crawler

        if not live_crawler.clients:
            logger.debug(f"No admin clients available to join group {group_name}")
            return False

        for admin_id, client in list(live_crawler.clients.items()):
            try:
                if not client.is_connected():
                    logger.debug(f"Admin client {admin_id} disconnected, trying next")
                    continue

                # Try invite link first (works for both public and private)
                if invite_link:
                    await client.join_chat(invite_link)
                    logger.info(f"Admin {admin_id} auto-joined group {group_name} (id={group_id}) via invite link")
                    return True

                # Fallback: try username
                elif username:
                    await client.join_chat(f"@{username}")
                    logger.info(f"Admin {admin_id} auto-joined group {group_name} (id={group_id}) via username")
                    return True

            except FloodWaitError as e:
                logger.debug(f"FloodWait on join {group_name}: wait {e.seconds}s")
                await asyncio.sleep(min(e.seconds + 2, 10))
                continue

            except (InviteHashInvalidError, InviteHashExpiredError):
                logger.debug(f"Invalid/expired invite link for {group_name}")
                continue

            except ChannelPrivateError:
                logger.debug(f"Cannot access private group {group_name} — admin not member")
                continue

            except ChatAdminRequiredError:
                logger.debug(f"Admin permission required for {group_name}")
                continue

            except Exception as e:
                logger.debug(f"Failed to auto-join {group_name}: {type(e).__name__}: {e}")
                continue

        logger.warning(f"All admin clients failed to join {group_name}")
        return False

    except Exception as e:
        logger.warning(f"Unexpected error in auto_join: {e}")
        return False




@router.get("/my-telegram-groups", response_model=List[TelegramGroupInfo])
async def get_my_groups(
    connection_id: str = None,
    current_user: UserResponse = Depends(get_current_user),
):
    """Get all Telegram groups user is member of.
    If connection_id is provided, uses that specific Telegram connection.
    Otherwise falls back to legacy single-session lookup."""
    try:
        if connection_id:
            groups = await telegram_manager.get_user_groups_by_connection(
                connection_id, str(current_user.id)
            )
        else:
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
    except HTTPException:
        raise
    except TelegramAuthError as e:
        logger.warning("Telegram auth error for user %s: %s (status=%d)", current_user.id, e.detail, e.status_code)
        raise HTTPException(status_code=e.status_code, detail=e.detail)
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
                # Group exists — still upsert user_groups to link connection_id
                await db.execute(
                    """INSERT INTO user_groups (user_id, group_id, connection_id)
                       VALUES ($1, $2, $3)
                       ON CONFLICT (user_id, group_id)
                       DO UPDATE SET connection_id = EXCLUDED.connection_id
                       WHERE user_groups.connection_id IS NULL""",
                    current_user.id, telegram_id, request.connection_id,
                )
                continue

            # Wrap all per-group DB ops in a transaction to prevent orphaned rows
            async with db.pool.acquire() as conn:
                async with conn.transaction():
                    # Insert group (map API fields → DB columns)
                    await conn.execute(
                        """INSERT INTO groups (id, name, type, member_count, visibility, has_topics, registered_by, crawl_enabled)
                           VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
                        telegram_id,
                        group_data.title,
                        group_data.group_type or "group",
                        group_data.member_count,
                        group_data.visibility or GroupVisibility.PUBLIC.value,
                        group_data.has_topics or False,  # NEW: from frontend payload
                        current_user.id,
                        True,
                    )

                    # Add to user's group membership (with optional connection_id)
                    await conn.execute(
                        "INSERT INTO user_groups (user_id, group_id, connection_id) VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
                        current_user.id, telegram_id, request.connection_id,
                    )

                    # Create crawler_status row for this group
                    await conn.execute(
                        """INSERT INTO crawler_status (group_id, status, is_enabled, error_count, initial_crawl_progress, initial_crawl_total)
                           VALUES ($1, 'inactive', TRUE, 0, 0, 0) ON CONFLICT (group_id) DO NOTHING""",
                        telegram_id,
                    )

            # Auto-join admin to the group (enable crawling)
            # Use invite_link if available, fallback to username
            await _auto_join_admin_to_group(telegram_id, group_data.title, group_data.invite_link, group_data.username)

            # Build API response from the inserted row (outside txn — read committed)
            updated = await db.fetchrow("SELECT * FROM groups WHERE id = $1", telegram_id)
            registered_groups.append(TelegramGroupResponse(**db_group_to_api(dict(updated))))

        # Trigger sequential historical crawl for newly registered groups.
        # Uses asyncio.wait_for with 5s timeout so the API response is fast,
        # but we can report accurate crawl_initiated status to the frontend.
        crawl_initiated = False
        if registered_groups:
            new_group_ids = [str(g.telegram_id) for g in registered_groups]
            try:
                from app import crawler_client
                result = await asyncio.wait_for(
                    crawler_client.trigger_batch_historical_crawl(new_group_ids),
                    timeout=5.0,
                )
                if result and result.get("success"):
                    crawl_initiated = True
                    logger.info("Batch crawl triggered for %d groups: %s", len(new_group_ids), new_group_ids)
                elif result:
                    logger.warning("Batch crawl trigger rejected: %s", result)
                else:
                    logger.warning("Crawler unreachable for batch crawl trigger")
            except asyncio.TimeoutError:
                logger.warning("Batch crawl trigger timed out (5s) — crawler may still start")
            except Exception as exc:
                logger.warning("Failed to trigger batch crawl: %s", exc)

        return RegisterGroupsResponse(
            success=True,
            registered_groups=registered_groups,
            crawl_initiated=crawl_initiated,
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

        return [TelegramGroupResponse(**db_group_to_api(dict(g))) for g in groups]
    except Exception as e:
        logger.error("Groups API error: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/crawl-progress")
async def get_crawl_progress(
    current_user: UserResponse = Depends(get_current_user),
):
    """Get crawl progress for the current user's registered groups."""
    try:
        rows = await db.fetch(
            """SELECT cs.group_id, cs.status, cs.initial_crawl_progress,
                      cs.initial_crawl_total, cs.last_error, cs.updated_at,
                      g.name as group_name
               FROM crawler_status cs
               JOIN user_groups ug ON ug.group_id = cs.group_id
               JOIN groups g ON g.id = cs.group_id
               WHERE ug.user_id = $1""",
            current_user.id,
        )

        # Fetch currently crawling group from crawler process
        currently_crawling_id = None
        try:
            from app import crawler_client
            status = await crawler_client.get_crawler_status()
            if status:
                currently_crawling_id = status.get("currently_crawling_group_id")
        except Exception:
            pass

        result = []
        for r in rows:
            item = dict(r)
            item["is_currently_crawling"] = (
                currently_crawling_id is not None
                and int(item["group_id"]) == currently_crawling_id
            )
            result.append(item)
        return result
    except Exception as e:
        logger.error("get_crawl_progress error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to fetch crawl progress")


@router.get("/messages/search", response_model=MessagesListResponse)
async def search_messages(
    q: str = Query(..., min_length=2, description="Search query"),
    group_ids: str = Query(None, description="Comma-separated group IDs (optional)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    current_user: UserResponse = Depends(get_current_user),
):
    """Search messages by text content using ILIKE."""
    try:
        # Determine which groups to search
        if group_ids:
            ids = [gid.strip() for gid in group_ids.split(",") if gid.strip()]
        else:
            follows = await db.fetch(
                "SELECT group_id FROM user_groups WHERE user_id = $1", current_user.id
            )
            ids = [str(f["group_id"]) for f in follows]

        if not ids:
            return MessagesListResponse(messages=[], total=0, page=page, page_size=page_size, has_more=False)

        ids = await filter_accessible_group_ids(ids, current_user)
        if not ids:
            return MessagesListResponse(messages=[], total=0, page=page, page_size=page_size, has_more=False)

        return await fetch_messages_paginated(
            group_ids=[int(i) for i in ids],
            page=page,
            page_size=page_size,
            search_pattern=f"%{q}%",
        )
    except Exception as e:
        logger.error("search_messages error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to search messages")


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
        ids = await filter_accessible_group_ids(ids, current_user)
        if not ids:
            return MessagesListResponse(messages=[], total=0, page=page, page_size=page_size, has_more=False)

        return await fetch_messages_paginated(
            group_ids=[int(i) for i in ids],
            page=page,
            page_size=page_size,
            topic_id=topic_id,
        )
    except Exception as e:
        logger.error("get_aggregated_messages error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to fetch aggregated messages")


@router.get("/{group_id}/topics")
async def get_group_topics(
    group_id: str,
    current_user: UserResponse = Depends(get_current_user),
):
    """Get topics/threads for a group (Telegram forum groups)

    Returns topics with real metadata (title, icons, status) and message counts.
    Falls back to placeholder names for topics without metadata.
    """
    try:
        gid = int(group_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid group ID: must be numeric")

    try:
        group = await db.fetchrow("SELECT id, visibility, has_topics FROM groups WHERE id = $1", gid)
        if not group:
            raise HTTPException(status_code=404, detail="Group not found")

        # Authorization check (IDOR prevention)
        if group["visibility"] == GroupVisibility.PRIVATE.value:
            access = await db.fetchrow(
                "SELECT id FROM user_groups WHERE user_id = $1 AND group_id = $2",
                current_user.id, gid,
            )
            if not access:
                raise HTTPException(status_code=403, detail="Access denied: Private group")

        # Fetch topic metadata and message counts
        topics_result = await _fetch_and_aggregate_group_topics(gid, group["has_topics"])

        return sorted(topics_result, key=lambda t: t["message_count"], reverse=True)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Topics endpoint error for group_id=%s: %s", group_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


async def _fetch_and_aggregate_group_topics(group_id: int, has_topics: bool) -> list:
    """Fetch and aggregate topic metadata and message counts.

    Combines data from group_topics table (metadata) with message counts.
    Falls back to placeholder names for topics without metadata.

    Args:
        group_id: Telegram group ID
        has_topics: Whether group is a forum

    Returns:
        List of topic dicts with id, title, message_count, and optional metadata
    """
    # Get real topic metadata from group_topics table
    topic_metadata = {}
    if has_topics:
        topic_rows = await db.fetch(
            """SELECT topic_id, topic_title, icon_color, icon_emoji_id, is_closed, is_pinned, unread_count
               FROM group_topics WHERE group_id = $1""",
            group_id,
        )

        for row in topic_rows:
            topic_metadata[row["topic_id"]] = {
                "topic_id": row["topic_id"],
                "topic_title": row["topic_title"],
                "icon_color": row["icon_color"],
                "icon_emoji_id": row["icon_emoji_id"],
                "is_closed": row["is_closed"],
                "is_pinned": row["is_pinned"],
            }

    # Count messages per topic (limit to 5000 rows to avoid memory issues)
    message_rows = await db.fetch(
        """SELECT topic_id FROM messages
           WHERE group_id = $1 AND is_deleted = FALSE AND topic_id IS NOT NULL
           ORDER BY sent_at DESC LIMIT 5000""",
        group_id,
    )

    if not message_rows and not topic_metadata:
        return []

    # Aggregate message counts
    topic_counts = {}
    for row in message_rows:
        tid = row["topic_id"]
        topic_counts[tid] = topic_counts.get(tid, 0) + 1

    # Build final topic list
    final_topics = {}

    # 1. Add all topics from group_topics with real names
    for tid, meta in topic_metadata.items():
        final_topics[tid] = {
            **meta,
            "message_count": topic_counts.get(tid, 0),
        }

    # 2. Add topics from messages without metadata (fallback to placeholder)
    for tid, count in topic_counts.items():
        if tid not in final_topics:
            final_topics[tid] = {
                "topic_id": tid,
                "topic_title": f"Topic {tid}",
                "message_count": count,
            }

    return list(final_topics.values())


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

        return await fetch_messages_paginated(
            group_ids=[gid],
            page=page,
            page_size=page_size,
            topic_id=topic_id,
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

        return TelegramGroupResponse(**db_group_to_api(g))
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
