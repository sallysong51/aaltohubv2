"""Admin message management routes."""
import json
import logging
import traceback
from fastapi import APIRouter, Depends, HTTPException, Query
from datetime import datetime, timedelta, timezone
from app.models import MessagesListResponse, UserResponse
from app.auth import get_current_admin_user
from app.config import settings
from app.database import db
from app.queries.messages import fetch_messages_paginated

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/groups/{group_id}/messages", response_model=MessagesListResponse)
async def get_group_messages_admin(
    group_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    days: int = Query(30, ge=1, le=365, description="Number of days to look back"),
    topic_id: int = Query(None, description="Filter by topic ID"),
    current_user: UserResponse = Depends(get_current_admin_user),
):
    """Get messages from a group for the last N days (admin only)"""
    try:
        gid = int(group_id)
        date_threshold = datetime.now(timezone.utc) - timedelta(days=days)

        return await fetch_messages_paginated(
            group_ids=[gid],
            page=page,
            page_size=page_size,
            topic_id=topic_id,
            source_filter=None,  # Admin sees all sources
            date_threshold=date_threshold,
        )
    except Exception as e:
        logger.error(
            "get_group_messages_admin error for group_id=%s, page=%s: %s\n%s",
            group_id, page, e, traceback.format_exc()
        )
        error_detail = f"Failed to fetch messages: {type(e).__name__}"
        if settings.ENVIRONMENT == "development":
            error_detail += f" - {str(e)}"
        raise HTTPException(status_code=500, detail=error_detail)


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
            """INSERT INTO messages (telegram_message_id, group_id, sender_id, sender_name, "text",
                   media_type, media_url, reply_to_message_id, topic_id, sent_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
               ON CONFLICT (telegram_message_id, group_id) DO NOTHING""",
            payload.get("telegram_message_id"),
            payload.get("group_id"),
            payload.get("sender_id"),
            payload.get("sender_name"),
            payload.get("content") or payload.get("text"),
            payload.get("media_type"),
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
