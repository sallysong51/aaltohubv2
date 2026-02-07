"""
SSE (Server-Sent Events) manager — replaces Supabase Realtime.

Uses Postgres LISTEN/NOTIFY as the inter-process bridge between the
crawler process (which persists messages and sends NOTIFY) and the
API process (which holds SSE connections to frontend clients).

Architecture:
  Crawler → NOTIFY new_message → Postgres → LISTEN → SSEManager → fan-out → EventSource (browser)
"""
import asyncio
import json
import logging
from typing import Optional

import asyncpg

from app.config import settings

logger = logging.getLogger(__name__)


class SSEManager:
    """Manages SSE client connections and Postgres LISTEN fan-out."""

    def __init__(self) -> None:
        # group_id (str) → set of per-client asyncio.Queues
        self._subscribers: dict[str, set[asyncio.Queue]] = {}
        self._listen_conn: Optional[asyncpg.Connection] = None

    async def start(self) -> None:
        """Acquire a dedicated connection (outside pool) and start listening."""
        dsn = settings.DATABASE_URL
        if not dsn:
            logger.error("DATABASE_URL not set — SSE manager cannot start")
            return
        try:
            self._listen_conn = await asyncpg.connect(dsn=dsn)
            await self._listen_conn.add_listener("new_message", self._on_notification)
            logger.info("SSEManager started — listening on 'new_message' channel")
        except Exception as e:
            logger.error("SSEManager failed to start: %s", e)

    async def stop(self) -> None:
        """Clean up listener connection."""
        if self._listen_conn:
            try:
                await self._listen_conn.remove_listener("new_message", self._on_notification)
                await self._listen_conn.close()
            except Exception as e:
                logger.warning("SSEManager stop error: %s", e)
            self._listen_conn = None
        self._subscribers.clear()
        logger.info("SSEManager stopped")

    def _on_notification(
        self,
        conn: asyncpg.Connection,
        pid: int,
        channel: str,
        payload: str,
    ) -> None:
        """Called by asyncpg when a NOTIFY fires on the new_message channel.

        Parses the JSON payload, extracts group_id, and pushes the event
        to all client queues subscribed to that group.
        """
        try:
            data = json.loads(payload)
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning("SSE: invalid NOTIFY payload: %s", e)
            return

        group_id = str(data.get("payload", {}).get("group_id", ""))
        if not group_id:
            return

        subscribers = self._subscribers.get(group_id)
        if not subscribers:
            return

        for queue in subscribers:
            try:
                queue.put_nowait(data)
            except asyncio.QueueFull:
                pass  # Drop event — client is too slow (backpressure)

    def subscribe(self, group_ids: list[str]) -> asyncio.Queue:
        """Register a new SSE client. Returns a queue to read events from."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        for gid in group_ids:
            self._subscribers.setdefault(gid, set()).add(queue)
        return queue

    def unsubscribe(self, group_ids: list[str], queue: asyncio.Queue) -> None:
        """Unregister an SSE client and clean up empty subscriber sets."""
        for gid in group_ids:
            s = self._subscribers.get(gid)
            if s:
                s.discard(queue)
                if not s:
                    del self._subscribers[gid]

    @property
    def active_connections(self) -> int:
        """Total number of active SSE client queues (for monitoring)."""
        return sum(len(s) for s in self._subscribers.values())


# Global singleton
sse_manager = SSEManager()
