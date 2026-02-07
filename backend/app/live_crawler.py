"""
Live Crawler Service - Real-time Telegram message crawler integrated into FastAPI.

Features:
- Initial 14-day historical crawl for groups with no/few messages
- Real-time event listening (NewMessage, MessageEdited, MessageDeleted)
- asyncio.Queue buffer between Telethon events and DB writer
- Adaptive batching: bulk inserts when volume is high, single inserts when low
- Periodic group refresh (detects newly registered groups)
- Auto-reconnect on disconnect
- crawler_status table management
- Multiple admin accounts support
"""
import asyncio
import io
import logging
import time
import traceback
from datetime import datetime, timedelta, timezone
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import (
    FloodWaitError,
    ChannelPrivateError,
    ChatAdminRequiredError,
    SessionPasswordNeededError,
)
from telethon.tl.types import (
    InputPeerChannel,
    InputPeerChat,
    MessageMediaPhoto,
    MessageMediaDocument,
    MessageMediaWebPage,
    PeerChannel,
    PeerChat,
    Channel,
    Chat,
)
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from supabase import create_client, Client

from app.config import settings
from app.encryption import session_encryption
from app.models import UserRole

logger = logging.getLogger(__name__)

GROUP_REFRESH_INTERVAL = 300  # 5 minutes
ENABLED_CACHE_TTL = 60  # seconds
HISTORICAL_CRAWL_DAYS = 14
RECONNECT_DELAY = 10  # seconds
MAX_RECONNECT_ATTEMPTS = 10
MSG_QUEUE_MAXSIZE = 10000
BATCH_SIZE = 50  # max messages per batch insert
BATCH_TIMEOUT = 2.0  # seconds to wait for more messages before flushing
GAP_FILL_INTERVAL = 1800  # 30 minutes
GAP_FILL_LOOKBACK_HOURS = 1  # re-check last 1 hour of messages
GAP_FILL_MAX_MESSAGES = 500  # max messages per group during gap-fill

# Circuit breaker settings
CB_FAILURE_THRESHOLD = 5  # failures before opening
CB_FAILURE_WINDOW = 60  # seconds
CB_RECOVERY_TIMEOUT = 30  # seconds to wait before retrying


class CircuitBreaker:
    """Simple circuit breaker for DB operations.

    States: closed (normal) → open (paused) → half-open (testing).
    Opens after CB_FAILURE_THRESHOLD failures within CB_FAILURE_WINDOW seconds.
    Stays open for CB_RECOVERY_TIMEOUT seconds, then allows one test request.
    """

    def __init__(self) -> None:
        self._failures: list[float] = []
        self._state = "closed"  # closed | open | half-open
        self._opened_at: float = 0

    @property
    def is_open(self) -> bool:
        if self._state == "closed":
            return False
        if self._state == "open":
            if time.monotonic() - self._opened_at >= CB_RECOVERY_TIMEOUT:
                self._state = "half-open"
                return False  # allow one attempt
            return True
        return False  # half-open allows one attempt

    def record_success(self) -> None:
        self._state = "closed"
        self._failures.clear()

    def record_failure(self) -> None:
        now = time.monotonic()
        self._failures = [t for t in self._failures if now - t < CB_FAILURE_WINDOW]
        self._failures.append(now)
        if len(self._failures) >= CB_FAILURE_THRESHOLD:
            self._state = "open"
            self._opened_at = now
            logger.warning("Circuit breaker OPEN — pausing DB writes for %ds", CB_RECOVERY_TIMEOUT)


class LiveCrawlerService:
    """Real-time Telegram message crawler running inside FastAPI.

    Supports multiple admin accounts — each admin's Telegram session crawls
    the groups they're members of. Multiple crawlers run in parallel.

    Architecture:
        Telethon event handlers → asyncio.Queue → DB writer coroutine (batched)
    """

    def __init__(self) -> None:
        self.clients: dict[int, TelegramClient] = {}  # user_id -> TelegramClient
        self.supabase: Client | None = None
        self.running = False
        self.connected = False
        self.group_id_map: dict[int, str] = {}  # telegram_id -> group_uuid
        self.group_info_map: dict[int, dict] = {}  # telegram_id -> group row
        self._enabled_cache: dict[str, tuple[bool, float]] = {}
        self._listener_tasks: dict[int, asyncio.Task] = {}  # user_id -> listener task
        self._refresh_task: asyncio.Task | None = None
        self._historical_task: asyncio.Task | None = None
        self._writer_task: asyncio.Task | None = None
        self._started_at: datetime | None = None
        self._message_count = 0
        self._historical_crawl_running = False
        self._crawled_groups: set[int] = set()
        # Queue buffer between Telethon event handlers and DB writer
        self._msg_queue: asyncio.Queue = asyncio.Queue(maxsize=MSG_QUEUE_MAXSIZE)
        # Entity cache: telegram_id -> (access_hash, entity_type)
        # Persisted to Supabase `entity_cache` table to survive restarts
        self._entity_cache: dict[int, tuple[int, str]] = {}  # gid -> (access_hash, "channel"|"chat")
        # Circuit breaker for DB operations
        self._circuit_breaker = CircuitBreaker()
        # Gap-fill task
        self._gap_fill_task: asyncio.Task | None = None
        # Async HTTP client for broadcasts
        self._http_client = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Initialize multiple Telegram clients (one per admin user) and start crawling."""
        if self.running:
            logger.warning("Live crawler is already running")
            return

        logger.info("=" * 60)
        logger.info("Initializing live crawler with multiple admin accounts...")
        logger.info("=" * 60)

        try:
            self.supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)

            # Find all admin users
            admin_resp = self.supabase.table("users").select("*").eq("role", UserRole.ADMIN.value).execute()
            if not admin_resp.data:
                logger.error("Live crawler: No admin user found. Please login as admin first.")
                return

            logger.info("Live crawler: Found %d admin user(s)", len(admin_resp.data))

            # Initialize a Telethon client for each admin user
            for admin_user in admin_resp.data:
                admin_id = admin_user["id"]
                admin_name = admin_user.get("first_name", "?")
                admin_username = admin_user.get("username", "N/A")

                try:
                    # Load encrypted session
                    session_resp = (
                        self.supabase.table("telethon_sessions")
                        .select("session_data")
                        .eq("user_id", admin_id)
                        .execute()
                    )
                    if not session_resp.data:
                        logger.warning("Live crawler: Admin %s (id=%s) has no session. Skipping.", admin_name, admin_id)
                        continue

                    session_string = session_encryption.decrypt(session_resp.data[0]["session_data"])

                    # Create Telethon client
                    client = TelegramClient(
                        StringSession(session_string),
                        settings.TELEGRAM_API_ID,
                        settings.TELEGRAM_API_HASH,
                        use_ipv6=True,
                        request_retries=3,
                        connection_retries=5,
                        retry_delay=3,
                        timeout=120,
                        flood_sleep_threshold=300,
                        auto_reconnect=True,
                    )
                    logger.info("Live crawler: Connecting for %s (@%s) [id=%s]...", admin_name, admin_username, admin_id)
                    await client.connect()

                    me = await client.get_me()
                    if not me:
                        logger.warning("Live crawler: Auth failed for %s (id=%s). Skipping.", admin_name, admin_id)
                        await client.disconnect()
                        continue

                    self.clients[admin_id] = client
                    logger.info("Live crawler: ✓ Connected as %s (@%s) [id=%s]", me.first_name, me.username, admin_id)

                except Exception as e:
                    logger.error("Live crawler: Failed to initialize client for %s (id=%s): %s", admin_name, admin_id, e)
                    continue

            if not self.clients:
                logger.error("Live crawler: Failed to initialize any admin clients.")
                return

            self.running = True
            self._started_at = datetime.now(timezone.utc)
            self._message_count = 0

            # Load groups (shared across all clients)
            await self.refresh_groups()

            # Load persisted entity cache (avoids get_entity API calls on restart)
            await self._load_entity_cache()

            # Ensure crawler_status rows exist for all groups
            await self._ensure_crawler_status_rows()

            # Register event handlers on all clients
            self._register_event_handlers()

            # Start DB writer coroutine (consumes from queue)
            self._writer_task = asyncio.create_task(self._db_writer())

            # Start listener tasks (one per admin client)
            for user_id, client in self.clients.items():
                self._listener_tasks[user_id] = asyncio.create_task(
                    self._run_listener_with_reconnect(user_id, client)
                )

            # Initialize async HTTP client for broadcasts
            import httpx as _httpx
            self._http_client = _httpx.AsyncClient(timeout=5.0)

            self._refresh_task = asyncio.create_task(self._periodic_group_refresh())
            self._historical_task = asyncio.create_task(self._crawl_all_groups_historical())
            self._gap_fill_task = asyncio.create_task(self._periodic_gap_fill())

            logger.info("Live crawler started!")
            logger.info("  - %d admin account(s) connected", len(self.clients))
            logger.info("  - %d groups loaded", len(self.group_id_map))
            logger.info("  - DB writer active (queue maxsize=%d, batch_size=%d)", MSG_QUEUE_MAXSIZE, BATCH_SIZE)
            logger.info("  - Historical crawl starting...")
            logger.info("  - Real-time events active")

        except Exception as e:
            logger.error("Live crawler failed to start: %s", e)
            logger.error(traceback.format_exc())
            await self._cleanup()

    async def stop(self) -> None:
        """Gracefully stop the crawler.

        Shutdown order:
        1. Set running=False so listeners/refresh stop accepting new work
        2. Cancel refresh & historical tasks (no new messages enqueued)
        3. Wait briefly for listener tasks to finish in-flight enqueues, then cancel
        4. Wait for DB writer to drain the queue (up to 15s)
        5. Disconnect Telethon clients
        """
        logger.info("Stopping live crawler...")
        self.running = False

        # Cancel background housekeeping tasks first
        for task in [self._refresh_task, self._historical_task, self._gap_fill_task]:
            if task and not task.done():
                task.cancel()

        # Close async HTTP client
        if self._http_client:
            try:
                await self._http_client.aclose()
            except Exception:
                pass
            self._http_client = None

        # Give listeners a moment to finish any in-flight enqueue, then cancel
        listener_tasks = [t for t in self._listener_tasks.values() if t and not t.done()]
        if listener_tasks:
            _, pending = await asyncio.wait(listener_tasks, timeout=3.0)
            for task in pending:
                task.cancel()

        # Now drain the queue — writer loop exits when running=False AND queue empty
        if self._writer_task and not self._writer_task.done():
            try:
                await asyncio.wait_for(self._writer_task, timeout=15.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                logger.warning("DB writer did not drain in time, cancelling")
                self._writer_task.cancel()

        await self._cleanup()
        logger.info("Live crawler stopped.")

    async def restart(self) -> None:
        """Restart the crawler."""
        await self.stop()
        await asyncio.sleep(1)
        await self.start()

    async def _cleanup(self) -> None:
        self.connected = False
        for user_id, client in self.clients.items():
            try:
                await client.disconnect()
            except Exception:
                pass
        self.clients.clear()

    def get_status(self) -> dict:
        return {
            "running": self.running,
            "connected": self.connected,
            "groups_count": len(self.group_id_map),
            "messages_received": self._message_count,
            "historical_crawl_running": self._historical_crawl_running,
            "crawled_groups": len(self._crawled_groups),
            "queue_size": self._msg_queue.qsize(),
            "started_at": self._started_at.isoformat() if self._started_at else None,
            "uptime_seconds": (
                int((datetime.now(timezone.utc) - self._started_at).total_seconds())
                if self._started_at and self.running
                else 0
            ),
        }

    # ------------------------------------------------------------------
    # DB writer coroutine with adaptive batching
    # ------------------------------------------------------------------

    async def _db_writer(self) -> None:
        """Background coroutine that drains the message queue and writes to DB.

        Adaptive batching:
        - Waits for the first message, then collects up to BATCH_SIZE more
          within BATCH_TIMEOUT seconds.
        - 1 message → single insert (low-latency for real-time).
        - 2+ messages → batch insert for new messages, individual updates for edits.
        """
        logger.info("DB writer started (batch_size=%d, timeout=%.1fs)", BATCH_SIZE, BATCH_TIMEOUT)

        while self.running or not self._msg_queue.empty():
            batch: list[dict] = []
            try:
                # Block until first item arrives (or timeout to check self.running)
                item = await asyncio.wait_for(self._msg_queue.get(), timeout=5.0)
                batch.append(item)

                # Collect more items up to BATCH_SIZE within BATCH_TIMEOUT
                loop = asyncio.get_running_loop()
                deadline = loop.time() + BATCH_TIMEOUT
                while len(batch) < BATCH_SIZE:
                    remaining = deadline - loop.time()
                    if remaining <= 0:
                        break
                    try:
                        item = await asyncio.wait_for(self._msg_queue.get(), timeout=remaining)
                        batch.append(item)
                    except asyncio.TimeoutError:
                        break

            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            if batch:
                await self._flush_batch(batch)

        # Final drain on shutdown
        remaining_items: list[dict] = []
        while not self._msg_queue.empty():
            try:
                remaining_items.append(self._msg_queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        if remaining_items:
            await self._flush_batch(remaining_items)

        logger.info("DB writer stopped.")

    # Retry decorator for transient DB failures (exponential backoff: 1s, 2s, 4s)
    @retry(
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    def _db_upsert_batch(self, rows: list[dict], ignore_duplicates: bool = True) -> None:
        self.supabase.table("messages").upsert(
            rows,
            on_conflict="telegram_message_id,group_id",
            ignore_duplicates=ignore_duplicates,
        ).execute()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=4),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    def _db_upsert_single(self, row: dict, ignore_duplicates: bool = True) -> None:
        self.supabase.table("messages").upsert(
            row,
            on_conflict="telegram_message_id,group_id",
            ignore_duplicates=ignore_duplicates,
        ).execute()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=4),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    def _db_update(self, data: dict, record_id: str) -> None:
        self.supabase.table("messages").update(data).eq("id", record_id).execute()

    async def _broadcast(self, event: str, payload: dict) -> None:
        """Send a Supabase Broadcast message to the 'messages' channel.

        Uses the Supabase Realtime HTTP broadcast endpoint instead of
        Postgres Changes (WAL) to avoid single-thread WAL replication bottleneck.
        Uses async httpx client for non-blocking I/O.
        """
        if not self._http_client:
            return
        try:
            url = f"{settings.SUPABASE_URL}/realtime/v1/api/broadcast"
            await self._http_client.post(
                url,
                json={
                    "channel": "messages",
                    "event": event,
                    "payload": payload,
                },
                headers={
                    "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
                    "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
                    "Content-Type": "application/json",
                },
            )
        except Exception as e:
            logger.warning("Broadcast failed for event=%s: %s", event, e)

    def _write_to_dead_letter(self, row: dict, error: str) -> None:
        """Write a failed message to the dead letter table for later retry."""
        if not self.supabase:
            return
        try:
            self.supabase.table("failed_messages").insert({
                "telegram_message_id": row.get("telegram_message_id"),
                "group_id": row.get("group_id"),
                "payload": row,
                "error_message": str(error)[:500],
                "retry_count": 0,
            }).execute()
        except Exception as e:
            logger.error("Dead letter write failed: %s", e)

    async def _flush_batch(self, batch: list[dict]) -> None:
        """Write a batch of messages to the database.

        Separates inserts (new messages) from upserts (edits) and uses
        Supabase's batch insert for new messages. All DB calls use
        tenacity exponential backoff (up to 4 attempts).

        Circuit breaker: if DB is down, writes to dead letter table instead.
        """
        # Circuit breaker check — send everything to dead letter if open
        if self._circuit_breaker.is_open:
            logger.warning("[CB] Circuit breaker open — sending %d messages to dead letter", len(batch))
            for item in batch:
                await asyncio.to_thread(self._write_to_dead_letter, item["data"], "circuit_breaker_open")
            return

        inserts: list[dict] = []
        upserts: list[dict] = []

        for item in batch:
            if item.get("action") == "upsert":
                upserts.append(item)
            else:
                inserts.append(item)

        # --- Handle new messages (batch upsert, ON CONFLICT DO NOTHING) ---
        if inserts:
            rows = [item["data"] for item in inserts]
            try:
                await asyncio.to_thread(self._db_upsert_batch, rows, True)
                self._circuit_breaker.record_success()
                logger.info("[BATCH] Upserted %d new messages", len(rows))
            except Exception as e:
                logger.warning("[BATCH] Bulk upsert failed (%s), falling back to individual", e)
                for row in rows:
                    try:
                        await asyncio.to_thread(self._db_upsert_single, row, True)
                        self._circuit_breaker.record_success()
                    except Exception as e2:
                        self._circuit_breaker.record_failure()
                        logger.error("Upsert failed for msg %s: %s", row.get("telegram_message_id"), e2)
                        await asyncio.to_thread(self._write_to_dead_letter, row, str(e2))

            # Broadcast new messages to frontend
            for row in rows:
                await self._broadcast("insert", row)

        # --- Handle upserts (edits — ON CONFLICT DO UPDATE) ---
        for item in upserts:
            data = item["data"]
            if not data.get("media_url"):
                data.pop("media_url", None)
            try:
                await asyncio.to_thread(self._db_upsert_single, data, False)
                self._circuit_breaker.record_success()
                await self._broadcast("update", data)
            except Exception as e:
                self._circuit_breaker.record_failure()
                logger.error("Edit upsert failed for msg %s: %s", data.get("telegram_message_id"), e)
                await asyncio.to_thread(self._write_to_dead_letter, data, str(e))

        if len(batch) > 1:
            logger.info("[BATCH] Flushed %d messages (%d inserts, %d upserts)", len(batch), len(inserts), len(upserts))

    async def _enqueue_message(
        self,
        message,
        group_telegram_id: int,
        group_uuid: str,
        is_edit: bool = False,
        download_media: bool = False,
        client: TelegramClient | None = None,
    ) -> None:
        """Prepare message data and put it on the queue for the DB writer."""
        try:
            media_type = None  # DB enum: photo, video, document, audio, sticker, voice (NULL = text)
            media_url = None

            if message.media:
                if isinstance(message.media, MessageMediaPhoto):
                    media_type = "photo"
                elif isinstance(message.media, MessageMediaDocument):
                    doc = message.media.document
                    if doc.mime_type:
                        if doc.mime_type.startswith("video"):
                            media_type = "video"
                        elif doc.mime_type.startswith("audio"):
                            media_type = "audio"
                        elif "sticker" in doc.mime_type or "webp" in doc.mime_type or "tgsticker" in doc.mime_type:
                            media_type = "sticker"
                        elif "ogg" in doc.mime_type:
                            media_type = "voice"
                        else:
                            media_type = "document"
                    if hasattr(doc, "attributes"):
                        for attr in doc.attributes:
                            attr_name = type(attr).__name__
                            if attr_name == "DocumentAttributeVideo" and getattr(attr, "round_message", False):
                                media_type = "video"  # DB enum has no video_note
                            elif attr_name == "DocumentAttributeAudio" and getattr(attr, "voice", False):
                                media_type = "voice"
                            elif attr_name == "DocumentAttributeSticker":
                                media_type = "sticker"
                elif isinstance(message.media, MessageMediaWebPage):
                    media_type = None  # WebPage links are just text

            if download_media and media_type is not None and client:
                media_url, _ = await self._upload_media(message, group_uuid, media_type, client)

            sender_id = message.sender_id
            sender_name = None
            if message.sender:
                sender_name = getattr(message.sender, "first_name", None)
                if hasattr(message.sender, "last_name") and message.sender.last_name:
                    sender_name = f"{sender_name} {message.sender.last_name}"

            topic_id = None
            if hasattr(message, "reply_to") and message.reply_to:
                if hasattr(message.reply_to, "forum_topic") and message.reply_to.forum_topic:
                    topic_id = getattr(message.reply_to, "reply_to_top_id", None) or getattr(
                        message.reply_to, "reply_to_msg_id", None
                    )

            message_data = {
                "telegram_message_id": message.id,
                "group_id": group_uuid,
                "sender_id": sender_id,
                "sender_name": sender_name,
                "text": message.text,
                "media_type": media_type,
                "media_url": media_url,
                "reply_to_message_id": message.reply_to_msg_id,
                "topic_id": topic_id,
                "is_deleted": False,
                "sent_at": message.date.isoformat(),
            }

            queue_item = {
                "action": "upsert" if is_edit else "insert",
                "data": message_data,
                "group_uuid": group_uuid,
            }

            try:
                self._msg_queue.put_nowait(queue_item)
            except asyncio.QueueFull:
                logger.warning("Message queue full (size=%d), sending msg %d to dead letter", MSG_QUEUE_MAXSIZE, message.id)
                asyncio.create_task(asyncio.to_thread(
                    self._write_to_dead_letter, message_data, "queue_full"
                ))

        except Exception as e:
            logger.error("Enqueue message %d error: %s", message.id, e)

    # ------------------------------------------------------------------
    # crawler_status management
    # ------------------------------------------------------------------

    async def _ensure_crawler_status_rows(self) -> None:
        """Ensure every registered group has a crawler_status row."""
        if not self.supabase:
            return
        for gid, group_uuid in self.group_id_map.items():
            try:
                existing = await asyncio.to_thread(
                    lambda guuid=group_uuid: self.supabase.table("crawler_status")
                    .select("id").eq("group_id", guuid).execute()
                )
                if not existing.data:
                    await asyncio.to_thread(
                        lambda guuid=group_uuid: self.supabase.table("crawler_status").insert({
                            "group_id": guuid,
                            "status": "initializing",
                            "is_enabled": True,
                            "error_count": 0,
                            "initial_crawl_progress": 0,
                            "initial_crawl_total": 0,
                        }).execute()
                    )
                    logger.info("Created crawler_status for group %s", group_uuid)
            except Exception as e:
                logger.warning("Failed to create crawler_status for %s: %s", group_uuid, e)

    # ------------------------------------------------------------------
    # Group management
    # ------------------------------------------------------------------

    async def refresh_groups(self) -> None:
        """Load crawl-enabled groups from DB."""
        if not self.supabase:
            return
        try:
            resp = await asyncio.to_thread(
                lambda: self.supabase.table("groups").select("*").eq("crawl_enabled", True).execute()
            )
            if not resp.data:
                logger.info("Live crawler: no crawl-enabled groups found.")
                return

            old_ids = set(self.group_id_map.keys())
            self.group_id_map.clear()
            self.group_info_map.clear()

            for group in resp.data:
                gid = group["id"]
                self.group_id_map[gid] = str(gid)
                self.group_info_map[gid] = group

            new_ids = set(self.group_id_map.keys()) - old_ids
            if new_ids:
                for nid in new_ids:
                    title = self._get_group_title(nid)
                    logger.info("Live crawler: new group detected — %s (id=%s)", title, nid)

            logger.info("Live crawler: %d groups loaded", len(self.group_id_map))
        except Exception as e:
            logger.error("Live crawler: failed to refresh groups: %s", e)

    def _get_group_title(self, gid: int) -> str:
        info = self.group_info_map.get(gid, {})
        return info.get("title") or info.get("name") or str(gid)

    @staticmethod
    def _normalize_chat_id(chat_id: int) -> int:
        """Convert Telethon's negative chat_id to the bare positive ID stored in our DB."""
        if chat_id is None:
            return 0
        if chat_id < 0:
            s = str(chat_id)
            if s.startswith("-100"):
                return int(s[4:])
            return -chat_id
        return chat_id

    # ------------------------------------------------------------------
    # Entity cache — avoids repeated get_entity() / get_dialogs() API calls
    # ------------------------------------------------------------------

    async def _load_entity_cache(self) -> None:
        """Load persisted entity cache from Supabase on startup."""
        if not self.supabase:
            return
        try:
            resp = await asyncio.to_thread(
                lambda: self.supabase.table("entity_cache").select("*").execute()
            )
            for row in (resp.data or []):
                self._entity_cache[row["telegram_id"]] = (row["access_hash"], row["entity_type"])
            logger.info("Entity cache: loaded %d entries from DB", len(self._entity_cache))
        except Exception as e:
            # Table may not exist yet — that's fine, cache starts empty
            logger.debug("Entity cache load failed (table may not exist): %s", e)

    def _save_entity_to_cache(self, gid: int, access_hash: int, entity_type: str) -> None:
        """Persist a single entity cache entry to memory + DB."""
        self._entity_cache[gid] = (access_hash, entity_type)
        if not self.supabase:
            return
        try:
            self.supabase.table("entity_cache").upsert({
                "telegram_id": gid,
                "access_hash": access_hash,
                "entity_type": entity_type,
            }, on_conflict="telegram_id").execute()
        except Exception as e:
            logger.debug("Entity cache DB write failed for %s: %s", gid, e)

    def _cache_entity(self, entity) -> None:
        """Extract access_hash from a resolved entity and cache it."""
        if isinstance(entity, Channel):
            self._save_entity_to_cache(entity.id, entity.access_hash, "channel")
        elif isinstance(entity, Chat):
            self._save_entity_to_cache(entity.id, 0, "chat")

    async def _get_entity_for_group_with_client(self, gid: int, client: TelegramClient):
        """Resolve a bare group ID using a specific Telethon client.

        Resolution order:
        1. In-memory entity cache (InputPeerChannel/InputPeerChat — zero API calls)
        2. Direct get_entity(PeerChannel/PeerChat)
        3. get_dialogs() to warm Telethon's internal cache, then retry
        """
        # 1) Try cached access_hash first (no API call)
        cached = self._entity_cache.get(gid)
        if cached:
            access_hash, entity_type = cached
            try:
                if entity_type == "channel":
                    entity = await client.get_entity(InputPeerChannel(channel_id=gid, access_hash=access_hash))
                else:
                    entity = await client.get_entity(InputPeerChat(chat_id=gid))
                return entity
            except Exception:
                # Stale cache entry — remove from memory AND DB
                self._entity_cache.pop(gid, None)
                try:
                    if self.supabase:
                        self.supabase.table("entity_cache").delete().eq("telegram_id", gid).execute()
                except Exception:
                    pass

        # 2) Direct resolution attempts
        for peer_cls in (PeerChannel, PeerChat):
            try:
                kwarg = "channel_id" if peer_cls is PeerChannel else "chat_id"
                entity = await client.get_entity(peer_cls(**{kwarg: gid}))
                self._cache_entity(entity)
                return entity
            except Exception:
                pass

        # 3) Warm cache via get_dialogs() and cache ALL discovered entities
        logger.debug("Entity cache miss for %s — warming cache via get_dialogs()...", gid)
        dialogs = await client.get_dialogs()
        target_entity = None
        for dialog in dialogs:
            entity = dialog.entity
            if isinstance(entity, (Channel, Chat)):
                self._cache_entity(entity)
            if entity.id == gid:
                target_entity = entity

        if target_entity:
            return target_entity

        # 4) Final retry after cache warm
        try:
            entity = await client.get_entity(PeerChannel(channel_id=gid))
            self._cache_entity(entity)
            return entity
        except Exception as e:
            logger.debug("PeerChannel(%s) still failed after cache warm: %s", gid, e)

        raise ValueError(f"Could not resolve entity for group ID {gid}. Is the admin a member of this group?")

    async def _get_entity_for_group(self, gid: int):
        """Resolve using the first available client."""
        if not self.clients:
            raise ValueError("No admin clients available")
        client = next(iter(self.clients.values()))
        return await self._get_entity_for_group_with_client(gid, client)

    async def _periodic_group_refresh(self) -> None:
        """Refresh groups every 5 minutes. Trigger historical crawl for new groups."""
        while self.running:
            await asyncio.sleep(GROUP_REFRESH_INTERVAL)
            try:
                old_ids = set(self.group_id_map.keys())
                await self.refresh_groups()
                new_ids = set(self.group_id_map.keys()) - old_ids

                if new_ids:
                    await self._ensure_crawler_status_rows()
                    for nid in new_ids:
                        if nid not in self._crawled_groups:
                            title = self._get_group_title(nid)
                            logger.info("[NEW GROUP] Starting historical crawl for: %s", title)
                            await self._crawl_historical_for_group(nid)
            except Exception as e:
                logger.error("Live crawler: group refresh error: %s", e)

    # ------------------------------------------------------------------
    # Gap-fill re-check (catches messages missed during disconnects)
    # ------------------------------------------------------------------

    async def _periodic_gap_fill(self) -> None:
        """Every 30 minutes, re-fetch the last hour of messages per group.

        This catches any messages missed during brief disconnects that
        Telethon's auto_reconnect may not recover. Uses ON CONFLICT DO NOTHING
        so duplicates are harmlessly ignored.
        """
        while self.running:
            await asyncio.sleep(GAP_FILL_INTERVAL)
            if not self.running:
                break
            logger.info("[GAP-FILL] Starting gap-fill re-check (%d groups)...", len(self.group_id_map))
            filled = 0
            for gid in list(self.group_id_map.keys()):
                if not self.running:
                    break
                group_uuid = self.group_id_map.get(gid)
                if not group_uuid:
                    continue
                try:
                    if not await self._is_group_enabled(group_uuid):
                        continue

                    # Find a working client
                    working_client = None
                    entity = None
                    for uid, client in self.clients.items():
                        try:
                            entity = await self._get_entity_for_group_with_client(gid, client)
                            working_client = client
                            break
                        except Exception:
                            continue

                    if not entity or not working_client:
                        continue

                    lookback = datetime.now(timezone.utc) - timedelta(hours=GAP_FILL_LOOKBACK_HOURS)
                    count = 0
                    async for message in working_client.iter_messages(entity, offset_date=lookback, reverse=True):
                        if not self.running:
                            break
                        if message.text or message.media:
                            await self._enqueue_message(message, gid, group_uuid, client=working_client)
                            count += 1
                        if count >= GAP_FILL_MAX_MESSAGES:
                            break
                        if count % 200 == 0 and count > 0:
                            await asyncio.sleep(1.5)
                    filled += count

                except FloodWaitError as e:
                    logger.warning("[GAP-FILL] FloodWait: %ds, pausing...", e.seconds)
                    await asyncio.sleep(e.seconds)
                except Exception as e:
                    logger.debug("[GAP-FILL] Error for group %s: %s", gid, e)

            logger.info("[GAP-FILL] Complete — %d messages re-enqueued (duplicates ignored via ON CONFLICT)", filled)

    # ------------------------------------------------------------------
    # Historical crawl (14-day backfill)
    # ------------------------------------------------------------------

    async def _crawl_all_groups_historical(self) -> None:
        """Crawl historical messages for all groups that need it."""
        self._historical_crawl_running = True
        try:
            for gid in list(self.group_id_map.keys()):
                if not self.running:
                    break
                if gid in self._crawled_groups:
                    continue
                group_uuid = self.group_id_map[gid]
                try:
                    msg_count = await asyncio.to_thread(
                        lambda guuid=group_uuid: self.supabase.table("messages")
                        .select("id", count="exact")
                        .eq("group_id", guuid)
                        .eq("is_deleted", False)
                        .execute()
                    )
                    existing_count = msg_count.count if hasattr(msg_count, "count") and msg_count.count else 0
                    if existing_count > 50:
                        logger.info(
                            "Group %s already has %d messages, skipping historical crawl",
                            self._get_group_title(gid), existing_count
                        )
                        self._crawled_groups.add(gid)
                        await self._update_crawler_status(group_uuid, "active")
                        continue
                except Exception:
                    pass

                await self._crawl_historical_for_group(gid)
        except Exception as e:
            logger.error("Historical crawl error: %s", e)
        finally:
            self._historical_crawl_running = False

    async def _crawl_historical_for_group(self, gid: int) -> None:
        """Crawl last 14 days of messages for a single group.

        Tries each admin client until one succeeds. Messages are enqueued
        for the DB writer coroutine which handles batching.
        """
        group_uuid = self.group_id_map.get(gid)
        if not group_uuid:
            return

        title = self._get_group_title(gid)
        logger.info("=" * 50)
        logger.info("Historical crawl starting: %s (id=%s)", title, gid)
        logger.info("=" * 50)

        try:
            await self._update_crawler_status(group_uuid, "initializing")

            group_entity = None
            working_client = None
            for user_id, client in self.clients.items():
                try:
                    logger.info("  Trying entity resolution for %s with admin user_id=%s", title, user_id)
                    group_entity = await self._get_entity_for_group_with_client(gid, client)
                    working_client = client
                    logger.info("  ✓ Success! Using admin user_id=%s for %s", user_id, title)
                    break
                except Exception as e:
                    logger.debug("  ✗ Admin user_id=%s failed: %s", user_id, e)
                    continue

            if not group_entity or not working_client:
                raise ValueError(f"Could not resolve entity for group ID {gid} with any admin client")

            date_threshold = datetime.now(timezone.utc) - timedelta(days=HISTORICAL_CRAWL_DAYS)

            enqueued_count = 0
            async for message in working_client.iter_messages(group_entity, offset_date=date_threshold, reverse=True):
                if not self.running:
                    break
                try:
                    if message.text or message.media:
                        await self._enqueue_message(message, gid, group_uuid, client=working_client)
                        enqueued_count += 1

                        if enqueued_count % 100 == 0:
                            logger.info("  [%s] %d messages enqueued...", title, enqueued_count)
                            await self._update_crawler_status(
                                group_uuid, "initializing",
                                progress=enqueued_count, total=enqueued_count
                            )

                        # Rate limiting
                        if enqueued_count % 200 == 0:
                            await asyncio.sleep(1.5)
                except FloodWaitError as e:
                    logger.warning("FloodWait: %ds, pausing...", e.seconds)
                    await asyncio.sleep(e.seconds)
                except Exception as e:
                    logger.warning("Error enqueuing msg %d: %s", message.id, e)

            # Wait for queue to drain before marking complete
            while not self._msg_queue.empty():
                await asyncio.sleep(0.5)

            await self._update_crawler_status(
                group_uuid, "active",
                progress=enqueued_count, total=enqueued_count
            )
            self._crawled_groups.add(gid)
            await asyncio.to_thread(self._update_group_last_error, gid, "")
            logger.info("Historical crawl complete: %s — %d messages enqueued", title, enqueued_count)

        except (ChannelPrivateError, ChatAdminRequiredError) as e:
            logger.error("Access denied for %s: %s", title, e)
            await self._update_crawler_status(group_uuid, "error", error=str(e))
            await asyncio.to_thread(self._update_group_last_error, gid, str(e))
        except FloodWaitError as e:
            logger.error("FloodWait for %s: %ds", title, e.seconds)
            await self._update_crawler_status(group_uuid, "error", error=f"FloodWait: {e.seconds}s")
            await asyncio.sleep(e.seconds)
        except Exception as e:
            logger.error("Historical crawl failed for %s: %s", title, e)
            logger.error(traceback.format_exc())
            await self._update_crawler_status(group_uuid, "error", error=str(e))
            await asyncio.to_thread(self._update_group_last_error, gid, str(e))

    def _update_crawler_status_safe(
        self, group_uuid: str, status: str,
        error: str | None = None, progress: int | None = None, total: int | None = None
    ) -> None:
        """Update crawler_status without raising exceptions. Sync — use via run_in_executor."""
        try:
            update_data: dict = {
                "status": status,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            if error:
                update_data["last_error"] = error
            if progress is not None:
                update_data["initial_crawl_progress"] = progress
            if total is not None:
                update_data["initial_crawl_total"] = total
            if status == "active":
                update_data["last_message_at"] = datetime.now(timezone.utc).isoformat()

            self.supabase.table("crawler_status").update(update_data).eq("group_id", group_uuid).execute()
        except Exception as e:
            logger.warning("Failed to update crawler_status for %s: %s", group_uuid, e)

    async def _update_crawler_status(
        self, group_uuid: str, status: str,
        error: str | None = None, progress: int | None = None, total: int | None = None
    ) -> None:
        """Async wrapper for _update_crawler_status_safe — non-blocking."""
        await asyncio.to_thread(
            self._update_crawler_status_safe, group_uuid, status, error, progress, total
        )

    def _update_group_last_error(self, gid: int, error: str) -> None:
        """Update groups.last_error so admin dashboard can show it. Sync."""
        try:
            self.supabase.table("groups").update({
                "last_error": error,
            }).eq("id", gid).execute()
        except Exception as e:
            logger.warning("Failed to update groups.last_error for %s: %s", gid, e)

    # ------------------------------------------------------------------
    # Enabled check (cached)
    # ------------------------------------------------------------------

    def _fetch_group_enabled(self, group_uuid: str) -> bool:
        """Sync DB call to check if group crawling is enabled."""
        try:
            resp = (
                self.supabase.table("crawler_status")
                .select("is_enabled")
                .eq("group_id", group_uuid)
                .execute()
            )
            return resp.data[0].get("is_enabled", True) if resp.data else True
        except Exception:
            return True

    async def _is_group_enabled(self, group_uuid: str) -> bool:
        now = time.monotonic()
        cached = self._enabled_cache.get(group_uuid)
        if cached and (now - cached[1]) < ENABLED_CACHE_TTL:
            return cached[0]
        enabled = await asyncio.to_thread(self._fetch_group_enabled, group_uuid)
        self._enabled_cache[group_uuid] = (enabled, now)
        return enabled

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _register_event_handlers(self) -> None:
        """Register event handlers on all admin clients.

        NewMessage and MessageEdited enqueue to the async queue.
        MessageDeleted is handled directly (low volume, needs immediate effect).
        """
        for user_id, client in self.clients.items():
            # Capture client in closure
            _client = client

            @_client.on(events.NewMessage)
            async def on_new_message(event, _c=_client):
                try:
                    chat_id = self._normalize_chat_id(event.chat_id)
                    if chat_id not in self.group_id_map:
                        return

                    group_uuid = self.group_id_map[chat_id]
                    group_title = self._get_group_title(chat_id)

                    if not await self._is_group_enabled(group_uuid):
                        return

                    logger.info("[NEW] %s: %s", group_title, (event.text or "[media]")[:80])
                    await self._enqueue_message(
                        event.message, chat_id, group_uuid,
                        download_media=True, client=_c,
                    )
                    self._message_count += 1
                    await self._update_crawler_status(group_uuid, "active")
                except Exception as e:
                    logger.error("Live crawler new message error: %s", e)

            @_client.on(events.MessageEdited)
            async def on_message_edited(event, _c=_client):
                try:
                    chat_id = self._normalize_chat_id(event.chat_id)
                    if chat_id not in self.group_id_map:
                        return
                    group_uuid = self.group_id_map[chat_id]
                    logger.info("[EDIT] %s: msg %d", self._get_group_title(chat_id), event.message.id)
                    await self._enqueue_message(
                        event.message, chat_id, group_uuid,
                        is_edit=True, client=_c,
                    )
                except Exception as e:
                    logger.error("Live crawler edit error: %s", e)

            @_client.on(events.MessageDeleted)
            async def on_message_deleted(event):
                try:
                    chat_id = self._normalize_chat_id(event.chat_id)
                    if chat_id not in self.group_id_map:
                        return
                    group_uuid = self.group_id_map[chat_id]
                    logger.info("[DELETE] %s: %d msgs", self._get_group_title(chat_id), len(event.deleted_ids))
                    for msg_id in event.deleted_ids:
                        await asyncio.to_thread(
                            lambda mid=msg_id, guuid=group_uuid: self.supabase.table("messages").update({
                                "is_deleted": True,
                            }).eq("telegram_message_id", mid).eq("group_id", guuid).execute()
                        )
                        await self._broadcast("update", {
                            "telegram_message_id": msg_id,
                            "group_id": group_uuid,
                            "is_deleted": True,
                        })
                except Exception as e:
                    logger.error("Live crawler delete error: %s", e)

    # ------------------------------------------------------------------
    # Listener with auto-reconnect
    # ------------------------------------------------------------------

    async def _run_listener_with_reconnect(self, user_id: int, client: TelegramClient) -> None:
        """Keep a Telethon client running with auto-reconnect."""
        attempts = 0
        while self.running:
            try:
                await client.run_until_disconnected()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Live crawler [user_id=%s] disconnected: %s", user_id, e)

            attempts += 1

            if not self.running:
                break
            if attempts > MAX_RECONNECT_ATTEMPTS:
                logger.error("Live crawler [user_id=%s]: Max reconnect attempts reached.", user_id)
                break

            logger.info("Live crawler [user_id=%s]: Reconnecting in %ds (attempt %d/%d)...", user_id, RECONNECT_DELAY, attempts, MAX_RECONNECT_ATTEMPTS)
            await asyncio.sleep(RECONNECT_DELAY)

            try:
                if client and not client.is_connected():
                    await client.connect()
                    me = await client.get_me()
                    if me:
                        attempts = 0
                        logger.info("Live crawler [user_id=%s]: Reconnected successfully as %s", user_id, me.first_name)
                    else:
                        logger.error("Live crawler [user_id=%s]: Reconnect auth failed", user_id)
            except Exception as e:
                logger.error("Live crawler [user_id=%s]: Reconnect failed: %s", user_id, e)

    # ------------------------------------------------------------------
    # Media upload
    # ------------------------------------------------------------------

    async def _upload_media(self, message, group_uuid: str, media_type: str, client: TelegramClient) -> tuple[str | None, str | None]:
        """Download media from Telegram and upload to Supabase Storage."""
        try:
            buffer = io.BytesIO()
            if media_type == "photo":
                await client.download_media(message, buffer)
                content_type = "image/jpeg"
            else:
                if hasattr(message.media, "document") and message.media.document:
                    thumbs = message.media.document.thumbs
                    if thumbs:
                        await client.download_media(message, buffer, thumb=0)
                        content_type = "image/jpeg"
                    else:
                        return None, None
                else:
                    return None, None

            buffer.seek(0)
            file_bytes = buffer.read()
            if not file_bytes:
                return None, None

            file_ext = "jpg" if "jpeg" in content_type or "jpg" in content_type else "bin"
            file_path = f"{group_uuid}/{message.id}.{file_ext}"

            self.supabase.storage.from_("message-media").upload(
                file_path, file_bytes, {"content-type": content_type}
            )
            public_url = self.supabase.storage.from_("message-media").get_public_url(file_path)

            if media_type == "photo":
                return public_url, None
            else:
                return None, public_url
        except Exception as e:
            if "not found" not in str(e).lower() and "bucket" not in str(e).lower():
                logger.warning("Media upload failed for msg %d: %s", message.id, e)
            return None, None


# Global singleton
live_crawler = LiveCrawlerService()
