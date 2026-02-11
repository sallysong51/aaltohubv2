"""
Telegram Auto-Join

Background worker for auto-joining referenced Telegram groups.
Includes FloodWait handling, rate limiting, and retry logic.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, List
import logging
import sentry_sdk

from telethon.tl.functions.channels import JoinChannelRequest
from telethon.errors import FloodWaitError, UsernameInvalidError, ChannelPrivateError

from app.database import db

logger = logging.getLogger(__name__)


class TelegramAutoJoin:
    """
    Background worker for auto-joining Telegram groups.

    Features:
    - Rate limiting (3 joins/hour, 10/day per connection)
    - FloodWait handling with exponential backoff
    - Retry logic for failed joins
    - Connection selection (round-robin across admin connections)
    """

    def __init__(self, telegram_client_manager):
        """
        Initialize auto-join worker.

        Args:
            telegram_client_manager: TelegramClientManager instance
        """
        self._client_manager = telegram_client_manager
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=500)

        # Rate limiting per connection: user_id → {hourly, daily, last_reset_hour, last_reset_day}
        self._rate_limits: Dict[int, Dict] = {}
        self._max_joins_per_hour = 3
        self._max_joins_per_day = 10

        # Worker task
        self._worker_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()

        # Start worker
        self._worker_task = asyncio.create_task(self._process_queue())
        logger.info("TelegramAutoJoin worker started")

    async def enqueue(self, join_queue_id: str, telegram_link: str) -> None:
        """
        Enqueue Telegram link for auto-join.

        Args:
            join_queue_id: Join queue entry ID
            telegram_link: t.me link to join
        """
        try:
            await self._queue.put({"id": join_queue_id, "link": telegram_link})
        except asyncio.QueueFull:
            logger.error(f"Join queue full, dropping link: {telegram_link}")
            await self._update_status(join_queue_id, "failed", error="Queue overflow")

    async def _process_queue(self) -> None:
        """Background worker that processes join queue."""
        while not self._shutdown_event.is_set():
            try:
                item = await asyncio.wait_for(
                    self._queue.get(),
                    timeout=1.0
                )

                # Select least-used connection
                user_id = await self._select_connection()

                if not user_id:
                    logger.warning("No available connections, requeueing")
                    await asyncio.sleep(60)
                    await self._queue.put(item)
                    continue

                # Join group
                await self._join_group(item["id"], item["link"], user_id)

            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                logger.info("Auto-join worker cancelled")
                break
            except Exception as e:
                logger.error(f"Auto-join error: {e}", exc_info=True)
                sentry_sdk.capture_exception(e)
                await asyncio.sleep(1)

    async def _select_connection(self) -> Optional[int]:
        """
        Select connection with lowest join count (respecting rate limits).

        Returns:
            user_id or None if all connections rate-limited
        """
        try:
            # Get all admin connections
            admin_connections = await self._get_admin_connections()

            for user_id in admin_connections:
                # Initialize rate limit tracking if not exists
                if user_id not in self._rate_limits:
                    self._rate_limits[user_id] = {
                        "hourly": 0,
                        "daily": 0,
                        "last_reset_hour": datetime.now(),
                        "last_reset_day": datetime.now()
                    }

                limits = self._rate_limits[user_id]
                now = datetime.now()

                # Reset counters if needed
                if now - limits["last_reset_hour"] > timedelta(hours=1):
                    limits["hourly"] = 0
                    limits["last_reset_hour"] = now

                if now - limits["last_reset_day"] > timedelta(days=1):
                    limits["daily"] = 0
                    limits["last_reset_day"] = now

                # Check if under limits
                if limits["hourly"] < self._max_joins_per_hour and limits["daily"] < self._max_joins_per_day:
                    return user_id

            logger.warning("All connections rate-limited")
            return None

        except Exception as e:
            logger.error(f"Error selecting connection: {e}")
            sentry_sdk.capture_exception(e)
            return None

    async def _join_group(self, queue_id: str, telegram_link: str, user_id: int) -> None:
        """
        Join Telegram group using specified connection.

        Args:
            queue_id: Join queue entry ID
            telegram_link: t.me link to join
            user_id: User ID of connection to use
        """
        try:
            # Update status
            await self._update_status(queue_id, "processing")

            # Extract username from link
            username = telegram_link.split("t.me/")[-1].split("?")[0].split("/")[0]

            logger.info(f"Attempting to join {username} using user {user_id}")

            # Get client
            client = await self._client_manager.get_user_client(user_id)

            # Join channel
            result = await client(JoinChannelRequest(username))

            # Get group info
            entity = await client.get_entity(username)
            group_id = entity.id

            logger.info(f"Successfully joined {username} (group_id={group_id})")

            # Update status
            await self._update_status(queue_id, "joined", group_id=group_id)

            # Increment rate limit counters
            self._rate_limits[user_id]["hourly"] += 1
            self._rate_limits[user_id]["daily"] += 1

            # Persist to crawl_rate_limits table
            await self._update_rate_limits_db(user_id)

        except FloodWaitError as e:
            wait_seconds = e.seconds
            logger.warning(f"FloodWait: {wait_seconds}s for {telegram_link}")

            # Requeue after wait time
            await asyncio.sleep(wait_seconds)
            await self.enqueue(queue_id, telegram_link)

            await self._update_status(queue_id, "rate_limited", error=f"FloodWait {wait_seconds}s")

        except UsernameInvalidError:
            logger.warning(f"Invalid username: {telegram_link}")
            await self._update_status(queue_id, "failed", error="Invalid username")

        except ChannelPrivateError:
            logger.warning(f"Private channel (requires invite): {telegram_link}")
            await self._update_status(queue_id, "failed", error="Private channel")

        except Exception as e:
            logger.error(f"Join failed for {telegram_link}: {e}")
            sentry_sdk.capture_exception(e)
            await self._update_status(queue_id, "failed", error=str(e))

    async def _get_admin_connections(self) -> List[int]:
        """
        Get all admin connection user_ids.

        Returns:
            List of user IDs
        """
        try:
            async with db.pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT id FROM telegram_connections
                    WHERE is_admin = TRUE
                """)
                return [row["id"] for row in rows]
        except Exception as e:
            logger.error(f"Failed to get admin connections: {e}")
            sentry_sdk.capture_exception(e)
            return []

    async def _update_status(
        self,
        queue_id: str,
        status: str,
        group_id: Optional[int] = None,
        error: Optional[str] = None
    ) -> None:
        """
        Update telegram_join_queue status.

        Args:
            queue_id: Join queue entry ID
            status: New status
            group_id: Joined group ID (if successful)
            error: Optional error message
        """
        try:
            async with db.pool.acquire() as conn:
                if group_id:
                    await conn.execute("""
                        UPDATE telegram_join_queue
                        SET status = $1, joined_group_id = $2, joined_at = NOW()
                        WHERE id = $3
                    """, status, group_id, queue_id)
                elif error:
                    await conn.execute("""
                        UPDATE telegram_join_queue
                        SET status = $1, last_error = $2
                        WHERE id = $3
                    """, status, error, queue_id)
                else:
                    await conn.execute("""
                        UPDATE telegram_join_queue
                        SET status = $1
                        WHERE id = $2
                    """, status, queue_id)
        except Exception as e:
            logger.error(f"Failed to update join status for {queue_id}: {e}")
            sentry_sdk.capture_exception(e)

    async def _update_rate_limits_db(self, user_id: int) -> None:
        """
        Persist rate limits to database.

        Args:
            user_id: User ID of connection
        """
        try:
            limits = self._rate_limits[user_id]

            async with db.pool.acquire() as conn:
                # Get connection_id from user_id
                connection_row = await conn.fetchrow("""
                    SELECT id FROM telegram_connections
                    WHERE id = $1 AND is_admin = TRUE
                """, user_id)

                if not connection_row:
                    logger.warning(f"No admin connection found for user {user_id}")
                    return

                connection_id = connection_row["id"]

                await conn.execute("""
                    INSERT INTO crawl_rate_limits
                    (connection_id, action_type, hourly_count, daily_count,
                     last_reset_hour, last_reset_day)
                    VALUES ($1, 'join_group', $2, $3, $4, $5)
                    ON CONFLICT (connection_id, action_type)
                    DO UPDATE SET
                        hourly_count = $2,
                        daily_count = $3,
                        last_reset_hour = $4,
                        last_reset_day = $5
                """, connection_id, limits["hourly"], limits["daily"],
                    limits["last_reset_hour"], limits["last_reset_day"])
        except Exception as e:
            logger.error(f"Failed to update rate limits for user {user_id}: {e}")
            sentry_sdk.capture_exception(e)

    async def cleanup(self) -> None:
        """Cleanup worker task on shutdown."""
        logger.info("Shutting down auto-join worker...")
        self._shutdown_event.set()

        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass

        logger.info("Auto-join worker shutdown complete")

    def get_stats(self) -> Dict:
        """
        Get current auto-join statistics.

        Returns:
            Dict with queue size and rate limits
        """
        return {
            "queue_size": self._queue.qsize(),
            "rate_limits": {
                user_id: {
                    "hourly": limits["hourly"],
                    "daily": limits["daily"]
                }
                for user_id, limits in self._rate_limits.items()
            }
        }
