"""
SSE streaming endpoint — replaces Supabase Realtime for frontend event delivery.

Frontend connects via EventSource (native browser API) with JWT token
passed as a query parameter (EventSource does not support custom headers).
"""
import asyncio
import json
import logging
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.auth import decode_token
from app.database import db
from app.sse import sse_manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["events"])

# SSE keepalive interval — prevents proxies/browsers from closing idle connections
_KEEPALIVE_INTERVAL = 30  # seconds
# Max connection duration — prevents zombie TCP connections from accumulating.
# Frontend useSSE hook auto-reconnects after server-initiated close.
_MAX_CONNECTION_SECONDS = 7200  # 2 hours


@router.get("/events/stream")
async def event_stream(request: Request, token: str, groups: str):
    """SSE endpoint for realtime message events.

    Auth via query param because EventSource cannot set custom headers.
    Query params:
      - token: JWT access token
      - groups: comma-separated group IDs to subscribe to
    """
    # Validate JWT token
    try:
        payload = decode_token(token)
    except HTTPException:
        raise HTTPException(status_code=401, detail="Invalid token")

    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Invalid token type")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    # Parse group IDs
    group_ids = [g.strip() for g in groups.split(",") if g.strip()]
    if not group_ids:
        raise HTTPException(status_code=400, detail="No groups specified")

    # Authorization check: only subscribe to groups the user has access to.
    # Public groups are accessible to all authenticated users; private groups
    # require a user_groups entry.
    try:
        authorized_rows = await db.fetch(
            """SELECT g.id::text AS gid FROM groups g
               WHERE g.id = ANY($1::bigint[])
                 AND (g.visibility = 'public'
                      OR EXISTS(SELECT 1 FROM user_groups ug
                                WHERE ug.group_id = g.id AND ug.user_id = $2))""",
            [int(gid) for gid in group_ids],
            int(user_id),
        )
        authorized_ids = {row["gid"] for row in authorized_rows}
        group_ids = [gid for gid in group_ids if gid in authorized_ids]
    except Exception as e:
        logger.warning("SSE auth check failed (allowing none): %s", e)
        group_ids = []

    if not group_ids:
        raise HTTPException(status_code=403, detail="No authorized groups")

    queue = sse_manager.subscribe(group_ids)

    async def generate():
        started = time.monotonic()
        try:
            while True:
                # Check if client disconnected
                if await request.is_disconnected():
                    break
                # Force reconnect after max duration to prevent zombie connections.
                # Frontend useSSE hook will auto-reconnect seamlessly.
                if time.monotonic() - started > _MAX_CONNECTION_SECONDS:
                    yield "event: reconnect\ndata: {}\n\n"
                    break
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=_KEEPALIVE_INTERVAL)
                    event_type = data.get("event", "message")
                    event_payload = json.dumps(data.get("payload", {}))
                    yield f"event: {event_type}\ndata: {event_payload}\n\n"
                except asyncio.TimeoutError:
                    # Send SSE comment as keepalive to prevent connection timeout
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            sse_manager.unsubscribe(group_ids, queue)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )
