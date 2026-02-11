"""Admin group management routes."""
import asyncio
import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List
from telethon.errors import (
    FloodWaitError, ChannelPrivateError, ChatAdminRequiredError,
    InviteHashInvalidError, InviteHashExpiredError
)
from app.models import TelegramGroupResponse, UserResponse
from app.auth import get_current_admin_user
from app.database import db
from app.queries.groups import db_group_to_api

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/groups", response_model=List[TelegramGroupResponse])
async def get_all_groups(
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    current_user: UserResponse = Depends(get_current_admin_user),
):
    """Get all registered groups (admin only). Includes connection_id and message_count."""
    try:
        offset = (page - 1) * page_size
        rows = await db.fetch(
            """SELECT g.*,
               (
                   SELECT ug.connection_id::text
                   FROM user_groups ug
                   WHERE ug.group_id = g.id
                     AND ug.user_id = $3
                     AND ug.connection_id IS NOT NULL
                   LIMIT 1
               ) AS connection_id,
               (
                   SELECT COUNT(*)
                   FROM messages m
                   WHERE m.group_id = g.id AND m.is_deleted = FALSE
               ) AS message_count_total
               FROM groups g
               ORDER BY g.created_at DESC
               LIMIT $1 OFFSET $2""",
            page_size, offset, current_user.id,
        )
        result = []
        for g in rows:
            api_dict = db_group_to_api(dict(g))
            api_dict["connection_id"] = g.get("connection_id")
            api_dict["message_count_total"] = g.get("message_count_total", 0)
            result.append(TelegramGroupResponse(**api_dict))
        return result
    except Exception as e:
        logger.error("get_all_groups error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to fetch groups")


@router.patch("/groups/{group_id}")
async def update_group_settings(
    group_id: str,
    current_user: UserResponse = Depends(get_current_admin_user),
    crawl_enabled: bool = Query(..., description="Enable or disable crawling"),
):
    """Toggle crawl_enabled for a group (admin only)."""
    try:
        gid = int(group_id)
        result = await db.execute(
            "UPDATE groups SET crawl_enabled = $1, updated_at = NOW() WHERE id = $2",
            crawl_enabled, gid,
        )
        if "UPDATE 0" in result:
            raise HTTPException(status_code=404, detail="Group not found")
        return {"success": True, "group_id": gid, "crawl_enabled": crawl_enabled}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("update_group_settings error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to update group")


@router.delete("/groups/{group_id}")
async def delete_group_admin(
    group_id: str,
    current_user: UserResponse = Depends(get_current_admin_user),
):
    """Delete a group and all related data (admin only).

    Deletes regardless of crawling status or any other state.
    All related data is cascaded or explicitly deleted.
    """
    try:
        gid = int(group_id)

        # Use transaction for atomic delete
        async with db.pool.acquire() as conn:
            async with conn.transaction():
                # Delete tables WITHOUT CASCADE first (manual cleanup)
                await conn.execute("DELETE FROM telegram_join_queue WHERE joined_group_id = $1", gid)

                # Delete tables with CASCADE (explicit delete for clarity, though CASCADE handles it)
                # Order: child tables first, parent last
                await conn.execute("DELETE FROM group_topics WHERE group_id = $1", gid)
                await conn.execute("DELETE FROM context_keywords WHERE group_id = $1", gid)
                await conn.execute("DELETE FROM group_contexts WHERE group_id = $1", gid)
                await conn.execute("DELETE FROM connection_accessible_groups WHERE group_id = $1", gid)
                await conn.execute("DELETE FROM failed_messages WHERE group_id = $1", gid)
                await conn.execute("DELETE FROM private_group_invites WHERE group_id = $1", gid)
                await conn.execute("DELETE FROM crawl_logs WHERE group_id = $1", gid)
                await conn.execute("DELETE FROM crawler_events WHERE group_id = $1", gid)
                await conn.execute("DELETE FROM crawler_metrics WHERE group_id = $1", gid)
                await conn.execute("DELETE FROM crawler_status WHERE group_id = $1", gid)
                await conn.execute("DELETE FROM user_groups WHERE group_id = $1", gid)
                await conn.execute("DELETE FROM messages WHERE group_id = $1", gid)

                # Finally delete the parent
                result = await conn.execute("DELETE FROM groups WHERE id = $1", gid)

                if "DELETE 0" in result:
                    raise HTTPException(status_code=404, detail="Group not found")

        logger.info("delete_group_admin: successfully deleted group %s and all related data", gid)
        return {"success": True, "group_id": gid, "message": f"Group {gid} and all related data deleted"}

    except HTTPException:
        raise
    except Exception as e:
        # Detailed error logging for debugging
        import traceback
        logger.error("delete_group_admin error for group %s: %s\n%s", group_id, e, traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete group: {str(e)}"
        )


@router.post("/backfill-connection-ids")
async def backfill_connection_ids(
    current_user: UserResponse = Depends(get_current_admin_user),
):
    """Backfill NULL connection_id values in user_groups for the current admin.

    If the admin has exactly one telegram_connection, assigns it to all their
    user_groups rows that have NULL connection_id.
    """
    try:
        connections = await db.fetch(
            "SELECT id, username, first_name, last_name, phone_masked FROM telegram_connections WHERE user_id = $1",
            current_user.id,
        )

        if len(connections) == 0:
            return {"success": False, "message": "No Telegram connections found", "updated": 0}

        if len(connections) == 1:
            conn = connections[0]
            conn_id = conn["id"]
            result = await db.execute(
                """UPDATE user_groups
                   SET connection_id = $1
                   WHERE user_id = $2 AND connection_id IS NULL""",
                conn_id, current_user.id,
            )
            count = int(result.split()[-1]) if result else 0

            # Build display name for UI feedback
            connection_username = conn.get("username")
            if connection_username:
                connection_display_name = f"@{connection_username}"
            elif conn.get("first_name"):
                connection_display_name = conn.get("first_name")
            else:
                connection_display_name = conn.get("phone_masked") or "Unknown"

            return {
                "success": True,
                "updated": count,
                "connection_id": str(conn_id),
                "connection_username": connection_username,
                "connection_display_name": connection_display_name,
            }

        # Multiple connections: try smart detection
        logger.info(
            "backfill_connection_ids: admin %s has %d connections, attempting smart detection",
            current_user.id, len(connections)
        )

        # Try to auto-assign using discovered connection-group accessibility
        updated = await _detect_and_assign_group_connections(current_user.id)
        if updated > 0:
            return {
                "success": True,
                "message": "Auto-detected and assigned groups to connections",
                "updated": updated,
                "connection_count": len(connections),
            }

        return {
            "success": False,
            "message": "Multiple connections found. Run detect-group-connections to auto-assign, or re-register groups per connection.",
            "updated": 0,
            "connection_count": len(connections),
        }
    except Exception as e:
        logger.error("backfill_connection_ids error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to backfill connection IDs")


async def _detect_and_assign_group_connections(user_id: int) -> int:
    """Helper: Auto-assign groups to connections based on accessibility discovery.

    Uses connection_accessible_groups table to determine which connection should
    manage each group. For groups accessible by multiple connections, picks the first.

    Returns: number of groups assigned
    """
    try:
        # Get groups with NULL connection_id for this user
        unlinked = await db.fetch(
            """SELECT ug.group_id
               FROM user_groups ug
               WHERE ug.user_id = $1 AND ug.connection_id IS NULL""",
            user_id,
        )

        if not unlinked:
            logger.debug("_detect_and_assign_group_connections: no unlinked groups for user %s", user_id)
            return 0

        unlinked_group_ids = [row["group_id"] for row in unlinked]
        logger.info(
            "_detect_and_assign_group_connections: found %d unlinked groups for user %s",
            len(unlinked_group_ids), user_id
        )

        updated_count = 0

        # For each unlinked group, find an accessible connection
        for group_id in unlinked_group_ids:
            try:
                # Find a connection that can access this group
                accessible = await db.fetchval(
                    """SELECT connection_id
                       FROM connection_accessible_groups cag
                       WHERE cag.group_id = $1
                         AND cag.connection_id IN (
                             SELECT id FROM telegram_connections
                             WHERE user_id = $2
                         )
                       LIMIT 1""",
                    group_id, user_id
                )

                if accessible:
                    # Auto-assign this group to the accessible connection
                    await db.execute(
                        """UPDATE user_groups
                           SET connection_id = $1
                           WHERE user_id = $2 AND group_id = $3""",
                        accessible, user_id, group_id
                    )
                    updated_count += 1
                    logger.debug(
                        "_detect_and_assign_group_connections: assigned group %s to connection %s",
                        group_id, accessible
                    )
            except Exception as e:
                logger.warning(
                    "_detect_and_assign_group_connections: failed to assign group %s: %s",
                    group_id, e
                )
                continue

        logger.info(
            "_detect_and_assign_group_connections: assigned %d groups for user %s",
            updated_count, user_id
        )
        return updated_count

    except Exception as e:
        logger.error("_detect_and_assign_group_connections error: %s", e)
        return 0


@router.post("/detect-group-connections")
async def detect_group_connections(
    current_user: UserResponse = Depends(get_current_admin_user),
):
    """Manually trigger group-connection detection for multi-connection admins.

    This endpoint uses the connection_accessible_groups table (populated by
    live_crawler.discover_group_accessibility() at startup) to auto-assign
    groups to their correct connections.

    Call this endpoint after:
    1. Adding new Telegram connections
    2. Registering new groups (if multi-connection)
    3. After getting "Multiple connections found" error from backfill endpoint

    Returns:
    - updated: number of groups auto-assigned
    - unlinked_remaining: groups still without connection_id
    - message: summary of results
    """
    try:
        # Trigger detection
        updated = await _detect_and_assign_group_connections(current_user.id)

        # Check how many unlinked groups remain
        remaining = await db.fetchval(
            """SELECT COUNT(*)
               FROM user_groups
               WHERE user_id = $1 AND connection_id IS NULL""",
            current_user.id,
        )

        return {
            "success": True,
            "updated": updated,
            "unlinked_remaining": remaining or 0,
            "message": f"Auto-assigned {updated} groups. {remaining or 0} groups still unlinked (register manually or check if connections have access).",
        }
    except Exception as e:
        logger.error("detect_group_connections error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to detect group connections")


@router.get("/unmapped-groups")
async def get_unmapped_groups(
    current_user: UserResponse = Depends(get_current_admin_user),
):
    """Get groups registered by users that admin accounts haven't joined yet.

    Shows which groups need manual join + crawling setup.
    Returns: groups registered but not yet accessible via admin accounts.
    """
    try:
        # Get all registered groups
        all_groups = await db.fetch(
            """SELECT g.id, g.name, g.username, g.invite_link, g.type, g.member_count,
                      g.visibility, g.crawl_status, g.registered_by,
                      u.first_name, u.last_name, u.username as registrant_username
               FROM groups g
               LEFT JOIN users u ON g.registered_by = u.id
               ORDER BY g.created_at DESC"""
        )

        # Get groups currently being crawled (accessible by admin accounts)
        crawler_status = await db.fetch(
            "SELECT DISTINCT group_id FROM crawler_status WHERE status IN ('active', 'initializing')"
        )
        accessible_group_ids = {row["group_id"] for row in crawler_status}

        # Find unmapped groups (registered but not accessible)
        unmapped = []
        for g in all_groups:
            gid = g["id"]
            if gid not in accessible_group_ids:
                registrant_name = g.get("first_name") or ""
                if g.get("last_name"):
                    registrant_name += f" {g['last_name']}"
                registrant_name = registrant_name.strip() or f"@{g.get('registrant_username', 'unknown')}"

                unmapped.append({
                    "group_id": gid,
                    "name": g.get("name") or "Unknown",
                    "username": g.get("username"),
                    "invite_link": g.get("invite_link"),
                    "type": g.get("type") or "group",
                    "member_count": g.get("member_count") or 0,
                    "visibility": g.get("visibility", "public"),
                    "crawl_status": g.get("crawl_status"),
                    "registered_by": g.get("registered_by"),
                    "registrant_name": registrant_name,
                })

        return {
            "total": len(unmapped),
            "groups": unmapped,
        }
    except Exception as e:
        logger.error("get_unmapped_groups error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to fetch unmapped groups")


@router.post("/auto-join-groups")
async def auto_join_unmapped_groups(
    current_user: UserResponse = Depends(get_current_admin_user),
):
    """Automatically join unmapped groups using admin accounts.

    Returns: List of join results (success/failed with reason)
    """
    try:
        # Get unmapped groups
        unmapped = await db.fetch(
            """SELECT g.id, g.invite_link, g.username, g.name
               FROM groups g
               LEFT JOIN crawler_status cs ON g.id = cs.group_id
               WHERE cs.status NOT IN ('active', 'initializing')
               OR cs.group_id IS NULL
               ORDER BY g.created_at ASC
               LIMIT 50"""
        )

        if not unmapped:
            return {"success": True, "total": 0, "joined": 0, "results": []}

        # Get live crawler clients
        from app.live_crawler import live_crawler
        if not live_crawler or not live_crawler.running or not live_crawler.clients:
            raise HTTPException(
                status_code=503,
                detail="Live crawler not running. Cannot join groups without active admin clients."
            )

        results = []
        joined_count = 0

        for group in unmapped:
            gid = group["id"]
            gname = group["name"]
            invite_link = group["invite_link"]
            username = group["username"]

            try:
                # Try to join using one of the admin clients
                joined = False
                last_error = None

                for admin_id, client in list(live_crawler.clients.items()):
                    try:
                        if not client.is_connected():
                            logger.warning("Admin client %s disconnected, skipping", admin_id)
                            continue

                        # Try invite link first (works for both public and private)
                        if invite_link:
                            await client.join_chat(invite_link)
                            logger.info("Auto-join success: %s (id=%s) via invite link", gname, gid)
                            results.append({
                                "group_id": gid,
                                "group_name": gname,
                                "success": True,
                                "method": "invite_link",
                            })
                            joined = True
                            joined_count += 1
                            break
                        # Fallback: try username
                        elif username:
                            await client.join_chat(f"@{username}")
                            logger.info("Auto-join success: %s (id=%s) via username", gname, gid)
                            results.append({
                                "group_id": gid,
                                "group_name": gname,
                                "success": True,
                                "method": "username",
                            })
                            joined = True
                            joined_count += 1
                            break

                    except FloodWaitError as e:
                        last_error = f"Rate limited: wait {e.seconds}s"
                        logger.warning("FloodWait for group %s: %ds", gname, e.seconds)
                        # Wait and retry with next client or move to next group
                        await asyncio.sleep(min(e.seconds + 5, 60))
                        continue

                    except (InviteHashInvalidError, InviteHashExpiredError):
                        last_error = "Invalid or expired invite link"
                        continue

                    except ChannelPrivateError:
                        last_error = "Channel is private (no access)"
                        continue

                    except ChatAdminRequiredError:
                        last_error = "Admin permission required"
                        continue

                    except Exception as e:
                        last_error = f"Error: {type(e).__name__}: {str(e)[:50]}"
                        logger.warning("Failed to join %s: %s", gname, e)
                        continue

                if not joined:
                    results.append({
                        "group_id": gid,
                        "group_name": gname,
                        "success": False,
                        "error": last_error or "All admin clients failed",
                    })

                # Delay between groups to avoid rate limiting
                await asyncio.sleep(30)

            except Exception as e:
                logger.error("Unexpected error joining group %s: %s", gid, e)
                results.append({
                    "group_id": gid,
                    "group_name": gname,
                    "success": False,
                    "error": str(e)[:100],
                })

        logger.info("Auto-join completed: %d/%d groups joined", joined_count, len(unmapped))

        return {
            "success": True,
            "total": len(unmapped),
            "joined": joined_count,
            "results": results,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("auto_join_unmapped_groups error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to auto-join groups")


@router.post("/ensure-admin-membership")
async def ensure_admin_membership(
    current_user: UserResponse = Depends(get_current_admin_user),
):
    """Ensure admin has user_groups rows for all groups.

    Creates missing user_groups entries (with connection_id=NULL initially)
    so that connection filtering works correctly. This is necessary because:
    - Admin needs visibility into ALL groups for management purposes
    - The get_all_groups() subquery returns NULL connection_id unless admin has a user_groups row
    - Without this endpoint, groups registered by other users won't show in connection tabs
    """
    try:
        # Get all group IDs
        all_groups = await db.fetch("SELECT id FROM groups")
        all_group_ids = [row["id"] for row in all_groups]

        # Get group IDs admin already has in user_groups
        existing = await db.fetch(
            "SELECT group_id FROM user_groups WHERE user_id = $1",
            current_user.id
        )
        existing_ids = {row["group_id"] for row in existing}

        # Find missing groups (groups admin doesn't have user_groups rows for)
        missing_ids = [gid for gid in all_group_ids if gid not in existing_ids]

        if not missing_ids:
            return {"success": True, "added": 0}

        # Insert missing user_groups rows (connection_id will be NULL)
        # The backfill_connection_ids endpoint can later set connection_id if needed
        for group_id in missing_ids:
            await db.execute(
                """INSERT INTO user_groups (user_id, group_id, connection_id)
                   VALUES ($1, $2, NULL)
                   ON CONFLICT (user_id, group_id) DO NOTHING""",
                current_user.id, group_id
            )

        logger.info("ensure_admin_membership: Added %d groups for admin user %s", len(missing_ids), current_user.id)
        return {"success": True, "added": len(missing_ids)}

    except Exception as e:
        logger.error("ensure_admin_membership error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to ensure admin membership")
