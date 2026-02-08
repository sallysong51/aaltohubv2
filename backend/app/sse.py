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
import re
from typing import Optional

import asyncpg

from app.config import settings

logger = logging.getLogger(__name__)

_RECONNECT_DELAY = 5  # initial seconds between reconnection attempts
_RECONNECT_DELAY_MAX = 300  # cap backoff at 5 minutes
_PING_INTERVAL = 60  # seconds between health pings on the LISTEN connection

# Permanent errors that should stop reconnection (retrying won't help)
_PERMANENT_ERRORS = (
    "Tenant or user not found",
    "password authentication failed",
    "no pg_hba.conf entry",
    "database .* does not exist",
)


class SSEManager:
    """Manages SSE client connections and Postgres LISTEN fan-out.

    Maintains a dedicated asyncpg connection (outside the pool) for
    LISTEN/NOTIFY. Automatically reconnects if the connection drops.
    """

    def __init__(self) -> None:
        # group_id (str) → set of per-client asyncio.Queues
        self._subscribers: dict[str, set[asyncio.Queue]] = {}
        self._listen_conn: Optional[asyncpg.Connection] = None
        self._running = False
        self._reconnect_task: Optional[asyncio.Task] = None
        self._ping_task: Optional[asyncio.Task] = None
        self._permanent_failure = False
        self._consecutive_failures = 0

    @property
    def is_connected(self) -> bool:
        """Whether the LISTEN connection is alive and receiving notifications."""
        return (
            self._listen_conn is not None
            and not self._listen_conn.is_closed()
        )

    async def start(self) -> None:
        """Acquire a dedicated connection (outside pool) and start listening."""
        self._running = True
        await self._connect()
        # Don't start background tasks if we hit a permanent error (bad credentials, etc.)
        if self._permanent_failure:
            logger.error(
                "SSEManager not starting background tasks — permanent connection error. "
                "Fix DATABASE_URL or wake the Supabase project, then restart the server."
            )
            self._running = False
            return
        # Start background tasks for reconnection monitoring and health pings
        self._reconnect_task = asyncio.create_task(self._reconnect_loop())
        self._ping_task = asyncio.create_task(self._ping_loop())

    async def stop(self) -> None:
        """Clean up listener connection and background tasks."""
        self._running = False
        # Cancel background tasks
        for task in [self._reconnect_task, self._ping_task]:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._reconnect_task = None
        self._ping_task = None
        # Close connection
        await self._disconnect()
        self._subscribers.clear()
        logger.info("SSEManager stopped")

    def _is_permanent_error(self, error: Exception) -> bool:
        """Check if an error is permanent (retrying won't help)."""
        msg = str(error)
        return any(re.search(pat, msg) for pat in _PERMANENT_ERRORS)

    async def _connect(self) -> bool:
        """Establish the LISTEN connection. Returns True on success.
        Sets self._permanent_failure = True if the error is non-recoverable.
        """
        dsn = settings.DATABASE_URL
        if not dsn:
            logger.error("DATABASE_URL not set — SSE manager cannot start")
            self._permanent_failure = True
            return False
        try:
            self._listen_conn = await asyncpg.connect(dsn=dsn)
            await self._listen_conn.add_listener("new_message", self._on_notification)
            self._consecutive_failures = 0
            logger.info("SSEManager started — listening on 'new_message' channel")
            return True
        except Exception as e:
            logger.error("SSEManager failed to connect: %s", e)
            self._listen_conn = None
            self._consecutive_failures += 1
            if self._is_permanent_error(e):
                self._permanent_failure = True
            return False

    async def _disconnect(self) -> None:
        """Close the LISTEN connection if open."""
        if self._listen_conn:
            try:
                await self._listen_conn.remove_listener("new_message", self._on_notification)
                await self._listen_conn.close()
            except Exception as e:
                logger.warning("SSEManager disconnect error: %s", e)
            self._listen_conn = None

    async def _reconnect_loop(self) -> None:
        """Monitor the LISTEN connection and reconnect if it drops.

        Uses exponential backoff and stops on permanent errors (e.g. bad credentials).
        """
        while self._running:
            # Exponential backoff: 5s, 10s, 20s, 40s, ... capped at 5min
            delay = min(_RECONNECT_DELAY * (2 ** max(0, self._consecutive_failures - 1)), _RECONNECT_DELAY_MAX)
            await asyncio.sleep(delay)
            if not self._running:
                break
            if self._permanent_failure:
                logger.error(
                    "SSEManager detected permanent connection error — stopping reconnection. "
                    "Fix DATABASE_URL or wake the Supabase project, then restart the server."
                )
                self._running = False
                break
            if not self.is_connected:
                logger.warning("SSEManager LISTEN connection lost — reconnecting (attempt %d)...", self._consecutive_failures + 1)
                await self._disconnect()  # clean up stale connection object
                if await self._connect():
                    logger.info("SSEManager reconnected successfully")
                else:
                    next_delay = min(_RECONNECT_DELAY * (2 ** self._consecutive_failures), _RECONNECT_DELAY_MAX)
                    logger.warning("SSEManager reconnect failed — will retry in %ds", next_delay)

    async def _ping_loop(self) -> None:
        """Periodic health ping to detect dead connections proactively.

        A silently-dead connection (no TCP RST, just dropped packets) won't
        be detected by is_closed(). Sending a lightweight query forces the
        connection to discover it's broken, which triggers reconnect_loop.
        """
        while self._running:
            await asyncio.sleep(_PING_INTERVAL)
            if not self._running:
                break
            if self._listen_conn and not self._listen_conn.is_closed():
                try:
                    await self._listen_conn.fetchval("SELECT 1")
                except Exception as e:
                    logger.warning("SSEManager ping failed (will reconnect): %s", e)
                    # Mark connection as dead — reconnect_loop will pick it up
                    try:
                        await self._listen_conn.close()
                    except Exception:
                        pass
                    self._listen_conn = None

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

        dropped = 0
        for queue in subscribers:
            try:
                queue.put_nowait(data)
            except asyncio.QueueFull:
                dropped += 1
                # Push an overflow marker so the client knows to refresh
                try:
                    # Evict oldest event and replace with overflow signal
                    queue.get_nowait()
                    queue.put_nowait({"event": "overflow", "payload": {"group_id": group_id}})
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass
        if dropped:
            logger.debug("SSE: dropped events for %d slow client(s) on group %s", dropped, group_id)

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
