"""
SSE streaming endpoint — replaces Supabase Realtime for frontend event delivery.

Frontend obtains a short-lived SSE ticket via POST /events/ticket (requires JWT),
then connects via EventSource using the ticket (not the JWT itself).
This prevents JWT exposure in URLs, server logs, and browser history.
"""
import asyncio
import json
import logging
import secrets
import time
from typing import Dict, Tuple

from fastapi import APIRouter, HTTPException, Request, Security
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.auth import decode_token, get_current_user
from app.database import db
from app.sse import sse_manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["events"])
_security = HTTPBearer()

# SSE keepalive interval — prevents proxies/browsers from closing idle connections
_KEEPALIVE_INTERVAL = 30  # seconds
# Max connection duration — prevents zombie TCP connections from accumulating.
# Frontend useSSE hook auto-reconnects after server-initiated close.
_MAX_CONNECTION_SECONDS = 7200  # 2 hours

# Short-lived ticket store: ticket_id → (user_id, group_ids, expires_at)
_SSE_TICKET_TTL = 60  # seconds
_SSE_TICKETS: Dict[str, Tuple[str, list[str], float]] = {}
_SSE_TICKETS_MAX = 1000


def _cleanup_expired_tickets() -> None:
    """Remove expired tickets to prevent unbounded growth."""
    now = time.monotonic()
    expired = [k for k, v in _SSE_TICKETS.items() if v[2] < now]
    for k in expired:
        del _SSE_TICKETS[k]


@router.post("/events/ticket")
async def create_sse_ticket(
    request: Request,
    groups: str,
    credentials: HTTPAuthorizationCredentials = Security(_security),
):
    """Exchange JWT for a single-use, short-lived SSE ticket.

    This prevents JWT exposure in EventSource URLs.
    The ticket is valid for 60 seconds and consumed on first use.
    """
    token = credentials.credentials
    try:
        payload = decode_token(token)
    except HTTPException:
        raise HTTPException(status_code=401, detail="Invalid token")

    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Invalid token type")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    group_ids = [g.strip() for g in groups.split(",") if g.strip()]
    if not group_ids:
        raise HTTPException(status_code=400, detail="No groups specified")

    # Cleanup and generate ticket
    _cleanup_expired_tickets()
    if len(_SSE_TICKETS) >= _SSE_TICKETS_MAX:
        _cleanup_expired_tickets()

    ticket = secrets.token_urlsafe(32)
    _SSE_TICKETS[ticket] = (user_id, group_ids, time.monotonic() + _SSE_TICKET_TTL)

    return {"ticket": ticket, "expires_in": _SSE_TICKET_TTL}


@router.get("/events/stream")
async def event_stream(request: Request, ticket: str = "", token: str = "", groups: str = ""):
    """SSE endpoint for realtime message events.

    Accepts either:
      - ticket: short-lived SSE ticket from POST /events/ticket (preferred)
      - token: JWT access token (legacy fallback, will be deprecated)
    """
    # Try ticket-based auth first (preferred — no JWT in URL)
    if ticket:
        ticket_data = _SSE_TICKETS.pop(ticket, None)
        if not ticket_data:
            raise HTTPException(status_code=401, detail="Invalid or expired ticket")
        user_id_str, group_ids, expires_at = ticket_data
        if time.monotonic() > expires_at:
            raise HTTPException(status_code=401, detail="Ticket expired")
        user_id = user_id_str
    elif token:
        # Legacy fallback: JWT in URL (deprecated, kept for backward compatibility)
        try:
            payload = decode_token(token)
        except HTTPException:
            raise HTTPException(status_code=401, detail="Invalid token")

        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")

        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token payload")

        group_ids = [g.strip() for g in groups.split(",") if g.strip()]
    else:
        raise HTTPException(status_code=401, detail="No authentication provided")

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
