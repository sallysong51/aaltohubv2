"""Admin Auto-Join API endpoints for automatic Telegram group joining.

This module provides REST API endpoints for automatically joining Telegram groups
using smart connection selection based on FloodWait penalties and rate limits.

Key Features:
- Smart connection selection (weighted penalty scoring)
- Automatic fallback to next-best connection on FloodWait
- Join attempt tracking for analytics
- Support for invite links, usernames, and group IDs
"""

import re
import logging
import asyncio
from typing import Optional, Dict, List, Tuple
from uuid import UUID
import sentry_sdk
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from telethon import TelegramClient
from telethon.errors import (
    FloodWaitError,
    ChannelPrivateError,
    ChatAdminRequiredError,
    InviteHashInvalidError,
    InviteHashExpiredError,
    UsernameInvalidError,
    UsernameNotOccupiedError,
)

from app.auth import get_current_admin_user
from app.database import db
from app.models import UserResponse
from app.telegram_client import telegram_manager
from app.utils.connection_health_tracker import ConnectionHealthTracker

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================================
# Request/Response Models
# ============================================================================


class AutoJoinRequest(BaseModel):
    """Request model for auto-join endpoint."""

    identifier: str = Field(
        ...,
        description="Telegram link (t.me/...), @username, or group ID",
        examples=["https://t.me/joinchat/ABC123", "@aalto_official", "-1001234567890"],
    )


class AutoJoinResponse(BaseModel):
    """Response model for auto-join endpoint."""

    success: bool
    message: str
    group_id: Optional[int] = None
    group_title: Optional[str] = None
    connection_id: Optional[str] = None
    estimated_wait_seconds: Optional[int] = None  # If queued


class JoinAttempt(BaseModel):
    """Response model for join attempt history."""

    id: str
    connection_id: str
    telegram_user_id: int
    group_link: Optional[str] = None
    group_username: Optional[str] = None
    group_id: Optional[int] = None
    success: bool
    error_type: Optional[str] = None
    flood_wait_seconds: Optional[int] = None
    attempted_at: str
    connection_name: str  # Joined from telegram_connections


# ============================================================================
# Helper Functions
# ============================================================================


def parse_telegram_identifier(identifier: str) -> Dict:
    """Parse a Telegram identifier into its components.

    Supports three formats:
    1. Invite link: https://t.me/joinchat/ABC or t.me/+ABC
    2. Username: @username or t.me/username
    3. Group ID: -1001234567890

    Args:
        identifier: Telegram link, username, or ID

    Returns:
        Dict with 'type' and relevant fields:
        - {'type': 'invite_link', 'hash': 'ABC123...'}
        - {'type': 'username', 'username': 'aalto_official'}
        - {'type': 'id', 'id': -1001234567890}

    Raises:
        HTTPException: If identifier format is invalid
    """
    identifier = identifier.strip()

    # Pattern 1: Invite link (t.me/joinchat/HASH or t.me/+HASH)
    invite_patterns = [
        r"(?:https?://)?t\.me/joinchat/([A-Za-z0-9_-]+)",
        r"(?:https?://)?t\.me/\+([A-Za-z0-9_-]+)",
    ]
    for pattern in invite_patterns:
        match = re.match(pattern, identifier)
        if match:
            return {"type": "invite_link", "hash": match.group(1)}

    # Pattern 2: Username (@username or t.me/username)
    if identifier.startswith("@"):
        username = identifier[1:]  # Remove @
        if re.match(r"^[a-zA-Z0-9_]{5,32}$", username):
            return {"type": "username", "username": username}
        else:
            raise HTTPException(
                status_code=400,
                detail="Invalid username format. Must be 5-32 characters (letters, numbers, underscore).",
            )

    # Pattern 3: t.me/username
    match = re.match(r"(?:https?://)?t\.me/([a-zA-Z0-9_]{5,32})$", identifier)
    if match:
        return {"type": "username", "username": match.group(1)}

    # Pattern 4: Group ID (negative integer)
    if identifier.startswith("-") and identifier[1:].isdigit():
        try:
            group_id = int(identifier)
            return {"type": "id", "id": group_id}
        except ValueError:
            pass

    # No pattern matched
    raise HTTPException(
        status_code=400,
        detail=(
            "Invalid Telegram identifier. Supported formats: "
            "t.me/joinchat/HASH, t.me/+HASH, @username, t.me/username, or -1001234567890"
        ),
    )


def get_health_tracker_dependency() -> ConnectionHealthTracker:
    """Dependency to get the global ConnectionHealthTracker instance.

    Returns:
        ConnectionHealthTracker instance

    Raises:
        HTTPException: If tracker not initialized
    """
    # Import here to avoid circular dependency at module level
    import sys

    # Get crawler_main module
    crawler_main = sys.modules.get('crawler_main')
    if crawler_main is None:
        logger.error("crawler_main module not loaded - running in main app?")
        raise HTTPException(
            status_code=503,
            detail="Auto-join service only available via crawler API (port 8001).",
        )

    try:
        return crawler_main.get_health_tracker()
    except RuntimeError as e:
        logger.error(f"Health tracker not initialized: {e}")
        raise HTTPException(
            status_code=503,
            detail="Auto-join service not initialized. Please try again later.",
        )


async def fetch_active_connections(user_id: int) -> List[Dict]:
    """Fetch all active Telegram connections for a user.

    Args:
        user_id: User ID (admin)

    Returns:
        List of connection dicts with fields: id, telegram_user_id, phone_masked, username

    Raises:
        HTTPException: If no active connections found
    """
    connections = await db.fetch(
        """
        SELECT id, telegram_user_id, phone_masked, username
        FROM telegram_connections
        WHERE user_id = $1 AND is_active = true
        ORDER BY created_at ASC
        """,
        user_id,
    )

    if not connections:
        raise HTTPException(
            status_code=404,
            detail="No active Telegram connections found. Please add at least one connection.",
        )

    return [dict(conn) for conn in connections]


async def select_best_connection_for_join(
    tracker: ConnectionHealthTracker,
    connections: List[Dict],
) -> Tuple[Optional[Dict], int]:
    """Select the best connection for joining a group.

    Uses the ConnectionHealthTracker to score each connection and select
    the one with the lowest penalty score.

    Args:
        tracker: ConnectionHealthTracker instance
        connections: List of connection dicts from fetch_active_connections()

    Returns:
        Tuple of (best_connection_dict, estimated_wait_seconds)
        best_connection_dict is None if all connections are unhealthy
    """
    candidate_ids = [conn["telegram_user_id"] for conn in connections]

    best_user_id, best_score, all_scores = tracker.get_best_connection(candidate_ids)

    if best_user_id is None:
        # All connections unhealthy, estimate wait time
        min_wait = min(
            tracker.estimate_wait_time(user_id) for user_id in candidate_ids
        )
        estimated_wait = max(min_wait, 60)  # At least 1 minute
        logger.warning(
            f"All {len(connections)} connections unhealthy. "
            f"Estimated wait: {estimated_wait}s"
        )
        return None, estimated_wait

    # Find the connection dict for best_user_id
    best_conn = next(
        (conn for conn in connections if conn["telegram_user_id"] == best_user_id),
        None,
    )

    if best_conn is None:
        # Should never happen, but handle gracefully
        logger.error(f"Best user_id {best_user_id} not found in connections list")
        raise HTTPException(
            status_code=500, detail="Internal error selecting connection"
        )

    logger.info(
        f"Selected connection {best_conn['id']} "
        f"(user_id={best_user_id}, score={best_score})"
    )
    return best_conn, 0


async def join_group_with_client(
    client: TelegramClient,
    group_info: Dict,
) -> Tuple[bool, Optional[int], Optional[str], Optional[str], Optional[int]]:
    """Attempt to join a group using a Telegram client.

    Args:
        client: Authenticated TelegramClient
        group_info: Dict from parse_telegram_identifier()

    Returns:
        Tuple of (success, group_id, group_title, error_type, flood_wait_seconds)
    """
    try:
        if group_info["type"] == "invite_link":
            # Join via invite hash
            invite_hash = group_info["hash"]
            logger.info(f"Joining via invite link: {invite_hash[:10]}...")
            result = await client.join_chat(f"https://t.me/joinchat/{invite_hash}")

        elif group_info["type"] == "username":
            # Join via username
            username = group_info["username"]
            logger.info(f"Joining via username: @{username}")
            result = await client.join_chat(username)

        elif group_info["type"] == "id":
            # Get entity by ID and join
            group_id = group_info["id"]
            logger.info(f"Joining via ID: {group_id}")
            entity = await client.get_entity(group_id)
            result = await client.join_chat(entity)

        else:
            logger.error(f"Unknown group_info type: {group_info}")
            return False, None, None, "unknown", None

        # Extract group ID and title from result
        if hasattr(result, "chats") and result.chats:
            chat = result.chats[0]
            group_id = int(chat.id)
            group_title = getattr(chat, "title", "Unknown Group")
            logger.info(f"Successfully joined group {group_id}: {group_title}")
            return True, group_id, group_title, None, None
        else:
            logger.warning("Join succeeded but no chat info in result")
            return True, None, None, None, None

    except FloodWaitError as e:
        logger.warning(f"FloodWait error: must wait {e.seconds} seconds")
        return False, None, None, "flood_wait", e.seconds

    except InviteHashInvalidError:
        logger.warning("Invite hash is invalid")
        return False, None, None, "invite_invalid", None

    except InviteHashExpiredError:
        logger.warning("Invite link has expired")
        return False, None, None, "invite_expired", None

    except ChannelPrivateError:
        logger.warning("Channel/group is private and inaccessible")
        return False, None, None, "privacy", None

    except ChatAdminRequiredError:
        logger.warning("Admin privileges required to join")
        return False, None, None, "admin_required", None

    except (UsernameInvalidError, UsernameNotOccupiedError) as e:
        logger.warning(f"Username error: {e}")
        return False, None, None, "username_invalid", None

    except Exception as e:
        logger.error(f"Unexpected error joining group: {e}", exc_info=True)
        return False, None, None, "unknown", None


async def record_join_attempt(
    connection_id: UUID,
    telegram_user_id: int,
    group_info: Dict,
    success: bool,
    group_id: Optional[int],
    error_type: Optional[str],
    flood_wait_seconds: Optional[int],
) -> None:
    """Record a join attempt in the database.

    Args:
        connection_id: UUID of the connection used
        telegram_user_id: Telegram user ID
        group_info: Dict from parse_telegram_identifier()
        success: Whether join succeeded
        group_id: Group ID if successful
        error_type: Error category if failed
        flood_wait_seconds: FloodWait duration if applicable
    """
    group_link = None
    group_username = None

    if group_info["type"] == "invite_link":
        group_link = f"https://t.me/joinchat/{group_info['hash']}"
    elif group_info["type"] == "username":
        group_username = group_info["username"]
    elif group_info["type"] == "id":
        # Store as group_id only
        pass

    try:
        await db.execute(
            """
            INSERT INTO join_attempts (
                connection_id,
                telegram_user_id,
                group_link,
                group_username,
                group_id,
                success,
                error_type,
                flood_wait_seconds
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            str(connection_id),
            telegram_user_id,
            group_link,
            group_username,
            group_id,
            success,
            error_type,
            flood_wait_seconds,
        )
        logger.debug(f"Recorded join attempt: success={success}, error={error_type}")
    except Exception as e:
        logger.error(f"Failed to record join attempt: {e}", exc_info=True)
        # Don't raise - recording failure shouldn't block the main flow


async def attempt_join_with_fallback(
    tracker: ConnectionHealthTracker,
    connections: List[Dict],
    group_info: Dict,
    user_id: int,
    max_attempts: int = 3,
) -> AutoJoinResponse:
    """Attempt to join a group with automatic fallback to next-best connection.

    Args:
        tracker: ConnectionHealthTracker instance
        connections: List of all available connections
        group_info: Parsed group identifier
        user_id: Admin user ID (for client access)
        max_attempts: Maximum number of connections to try

    Returns:
        AutoJoinResponse with success status and details
    """
    attempted_connections = []

    for attempt_num in range(1, max_attempts + 1):
        logger.info(f"Join attempt {attempt_num}/{max_attempts}")

        # Select best available connection (excluding already attempted ones)
        remaining_connections = [
            conn
            for conn in connections
            if conn["id"] not in attempted_connections
        ]

        if not remaining_connections:
            # Exhausted all connections
            break

        best_conn, wait_time = await select_best_connection_for_join(
            tracker, remaining_connections
        )

        if best_conn is None:
            # All remaining connections unhealthy
            return AutoJoinResponse(
                success=False,
                message=f"모든 계정이 사용 중입니다. {wait_time}초 후 자동 재시도됩니다.",
                estimated_wait_seconds=wait_time,
            )

        # Attempt join with selected connection
        client = None
        try:
            client = await telegram_manager.get_user_client_by_connection(
                connection_id=best_conn["id"],
                user_id=user_id
            )

            (
                success,
                group_id,
                group_title,
                error_type,
                flood_wait_seconds,
            ) = await join_group_with_client(client, group_info)

            # Record attempt
            await record_join_attempt(
                connection_id=UUID(best_conn["id"]),
                telegram_user_id=best_conn["telegram_user_id"],
                group_info=group_info,
                success=success,
                group_id=group_id,
                error_type=error_type,
                flood_wait_seconds=flood_wait_seconds,
            )

            # Update tracker
            tracker.record_join_attempt(
                telegram_user_id=best_conn["telegram_user_id"],
                connection_id=UUID(best_conn["id"]),
                success=success,
                error_type=error_type,
            )

            if success:
                # Success! Return immediately
                return AutoJoinResponse(
                    success=True,
                    message="그룹에 성공적으로 가입했습니다",
                    group_id=group_id,
                    group_title=group_title,
                    connection_id=best_conn["id"],
                )

            # Failed - check if we should retry
            if error_type == "flood_wait":
                # FloodWait - try next connection
                logger.info(f"FloodWait on connection {best_conn['id']}, trying next")
                attempted_connections.append(best_conn["id"])
                continue
            else:
                # Non-retryable error - return immediately
                error_messages = {
                    "invite_invalid": "초대 링크가 유효하지 않습니다",
                    "invite_expired": "초대 링크가 만료되었습니다",
                    "privacy": "비공개 그룹입니다. 관리자에게 초대를 요청하세요",
                    "admin_required": "관리자 권한이 필요합니다",
                    "username_invalid": "존재하지 않는 그룹명입니다",
                    "unknown": "알 수 없는 오류가 발생했습니다",
                }
                return AutoJoinResponse(
                    success=False,
                    message=error_messages.get(error_type, "가입에 실패했습니다"),
                )

        finally:
            if client:
                await client.disconnect()

    # Exhausted all attempts - send Sentry alert
    identifier_str = (
        group_info.get("hash", "")
        or group_info.get("username", "")
        or str(group_info.get("id", ""))
    )

    sentry_sdk.capture_message(
        f"Auto-join failed after {max_attempts} attempts",
        level="warning",
        extras={
            "identifier": identifier_str,
            "group_type": group_info["type"],
            "attempted_connections": attempted_connections,
            "user_id": user_id,
        },
    )

    logger.error(
        f"Auto-join exhausted all {max_attempts} attempts for {identifier_str}. "
        f"Tried connections: {attempted_connections}"
    )

    return AutoJoinResponse(
        success=False,
        message=f"{max_attempts}번의 시도 후에도 가입에 실패했습니다",
    )


# ============================================================================
# API Endpoints
# ============================================================================


@router.post("", response_model=AutoJoinResponse)
async def auto_join_group(
    request: AutoJoinRequest,
    current_user: UserResponse = Depends(get_current_admin_user),
    tracker: ConnectionHealthTracker = Depends(get_health_tracker_dependency),
):
    """Automatically join a Telegram group using smart connection selection.

    This endpoint:
    1. Parses the identifier (link/username/ID)
    2. Selects the best connection based on health score
    3. Attempts to join the group
    4. Falls back to next-best connection on FloodWait (up to 3 attempts)
    5. Records all attempts for analytics

    Args:
        request: AutoJoinRequest with identifier
        current_user: Current admin user (dependency)
        tracker: ConnectionHealthTracker (dependency)

    Returns:
        AutoJoinResponse with success status and details

    Raises:
        HTTPException: On invalid input or service unavailable
    """
    # Parse identifier
    try:
        group_info = parse_telegram_identifier(request.identifier)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error parsing identifier: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail="Invalid identifier format")

    # Fetch active connections
    connections = await fetch_active_connections(current_user.id)

    # Ensure all connections are registered with tracker
    for conn in connections:
        tracker.register_connection(
            telegram_user_id=conn["telegram_user_id"],
            connection_id=UUID(conn["id"]),
        )

    # Attempt join with fallback
    result = await attempt_join_with_fallback(
        tracker=tracker,
        connections=connections,
        group_info=group_info,
        user_id=current_user.id,
        max_attempts=3,
    )

    # If all connections unhealthy and result has estimated_wait_seconds,
    # add to queue for automatic retry
    if not result.success and result.estimated_wait_seconds:
        # Import here to avoid circular dependency
        import sys

        crawler_main = sys.modules.get("crawler_main")
        if crawler_main and hasattr(crawler_main, "queue_join_request"):
            try:
                await crawler_main.queue_join_request(
                    identifier=request.identifier,
                    user_id=current_user.id,
                    delay_seconds=result.estimated_wait_seconds,
                )
                logger.info(
                    f"Added {request.identifier} to queue with "
                    f"{result.estimated_wait_seconds}s delay"
                )
            except Exception as e:
                logger.warning(f"Failed to queue join request: {e}")

    return result


@router.get("/recent", response_model=List[JoinAttempt])
async def get_recent_join_attempts(
    limit: int = 20,
    current_user: UserResponse = Depends(get_current_admin_user),
):
    """Get recent join attempts for analytics and debugging.

    Returns the most recent join attempts across all connections,
    with success/failure status and error details.

    Args:
        limit: Maximum number of attempts to return (default 20, max 100)
        current_user: Current admin user (dependency)

    Returns:
        List of JoinAttempt records, sorted by attempted_at DESC
    """
    # Validate limit
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100

    # Query join attempts with connection info
    rows = await db.fetch(
        """
        SELECT
            ja.id::text,
            ja.connection_id::text,
            ja.telegram_user_id,
            ja.group_link,
            ja.group_username,
            ja.group_id,
            ja.success,
            ja.error_type,
            ja.flood_wait_seconds,
            ja.attempted_at::text,
            COALESCE(
                tc.phone_masked || ' (' || COALESCE(tc.username, 'no username') || ')',
                'Unknown Connection'
            ) AS connection_name
        FROM join_attempts ja
        LEFT JOIN telegram_connections tc ON ja.connection_id = tc.id
        ORDER BY ja.attempted_at DESC
        LIMIT $1
        """,
        limit,
    )

    return [JoinAttempt(**dict(row)) for row in rows]
