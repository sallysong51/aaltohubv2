"""Shared message query helpers — single source of truth for message SQL."""
import logging
from datetime import datetime
from typing import Optional

from app.database import db
from app.models import MessageResponse, MessagesListResponse

logger = logging.getLogger(__name__)

# The canonical SELECT column list for messages.
# DB column is "text" but API field is "content", so we alias here.
MESSAGE_SELECT_COLUMNS = """id, telegram_message_id, group_id, sender_id, sender_name,
       "text" AS content, media_type, media_url,
       reply_to_message_id, topic_id, sent_at, is_deleted, created_at"""


def message_upsert_sql(ignore_duplicates: bool = True) -> str:
    """Return the INSERT...ON CONFLICT SQL for messages."""
    conflict = (
        "ON CONFLICT (telegram_message_id, group_id) DO NOTHING"
        if ignore_duplicates
        else 'ON CONFLICT (telegram_message_id, group_id) DO UPDATE SET '
             '"text" = EXCLUDED."text", media_type = EXCLUDED.media_type, '
             'media_url = EXCLUDED.media_url, is_edited = TRUE, '
             'is_deleted = EXCLUDED.is_deleted'
    )
    return f"""INSERT INTO messages
        (telegram_message_id, group_id, sender_id, sender_name, "text",
         media_type, media_url, reply_to_message_id, topic_id, is_deleted, sent_at, message_source)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
        {conflict}"""


def parse_message_rows(rows) -> list[MessageResponse]:
    """Defensively parse DB rows into MessageResponse, skipping malformed rows."""
    messages = []
    for m in rows:
        try:
            row_dict = dict(m)
            # Ensure datetimes are timezone-aware
            for dt_field in ("sent_at", "created_at"):
                val = row_dict.get(dt_field)
                if isinstance(val, datetime) and not val.tzinfo:
                    from datetime import timezone
                    row_dict[dt_field] = val.replace(tzinfo=timezone.utc)
            messages.append(MessageResponse(**row_dict))
        except Exception as exc:
            logger.warning("Skipping malformed message row id=%s: %s", dict(m).get("id"), exc)
    return messages


async def fetch_messages_paginated(
    *,
    group_ids: list[int],
    page: int,
    page_size: int,
    topic_id: Optional[int] = None,
    search_pattern: Optional[str] = None,
    source_filter: Optional[str] = "realtime",
    date_threshold: Optional[datetime] = None,
) -> MessagesListResponse:
    """Unified message fetch with count. Used by all message-listing endpoints.

    Args:
        group_ids: List of integer group IDs to query.
        page: 1-based page number.
        page_size: Number of messages per page.
        topic_id: Optional topic filter.
        search_pattern: Optional ILIKE pattern (e.g. "%query%").
        source_filter: message_source filter. None = no filter (admin).
        date_threshold: Optional minimum sent_at cutoff.
    """
    offset = (page - 1) * page_size

    # Build WHERE clause dynamically
    conditions = ["group_id = ANY($1::bigint[])", "is_deleted = FALSE"]
    params: list = [group_ids]
    idx = 2  # next parameter index

    if source_filter:
        conditions.append(f"message_source = ${idx}")
        params.append(source_filter)
        idx += 1

    if topic_id is not None:
        conditions.append(f"topic_id = ${idx}")
        params.append(topic_id)
        idx += 1

    if search_pattern:
        conditions.append(f'"text" ILIKE ${idx}')
        params.append(search_pattern)
        idx += 1

    if date_threshold:
        conditions.append(f"sent_at >= ${idx}")
        params.append(date_threshold)
        idx += 1

    where = " AND ".join(conditions)

    # Count
    total = await db.fetchval(
        f"SELECT COUNT(*) FROM messages WHERE {where}", *params
    )

    # Fetch
    limit_idx = idx
    offset_idx = idx + 1
    rows = await db.fetch(
        f"""SELECT {MESSAGE_SELECT_COLUMNS}
            FROM messages
            WHERE {where}
            ORDER BY sent_at ASC LIMIT ${limit_idx} OFFSET ${offset_idx}""",
        *params, page_size, offset,
    )

    messages = parse_message_rows(rows)

    return MessagesListResponse(
        messages=messages,
        total=total,
        page=page,
        page_size=page_size,
        has_more=offset + page_size < total,
    )
