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
import fcntl
import io
import json
import logging
import os
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
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
    MessageActionChatMigrateTo,
    PeerChannel,
    PeerChat,
    Channel,
    Chat,
)
import asyncpg
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# Transient exceptions that justify a retry (not programming bugs)
_TRANSIENT_EXCEPTIONS = (
    ConnectionError, TimeoutError, OSError,
    asyncpg.PostgresConnectionError, asyncpg.InterfaceError,
)

from app.config import settings
from app.database import db, get_storage_client
from app.encryption import session_encryption, ENCRYPTION_VERSION
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
DIALOGS_COOLDOWN = 600  # 10 minutes — minimum interval between get_dialogs() calls
QUEUE_DRAIN_TIMEOUT = 60  # seconds — max wait for queue to drain after historical crawl
MAX_MEDIA_BYTES = 10 * 1024 * 1024  # 10 MB — skip media larger than this
ENTITY_CACHE_MAX_SIZE = 5000  # max entries before LRU-style eviction
ENABLED_CACHE_MAX_SIZE = 1000  # max entries before eviction


def _safe_create_task(coro, *, name: str | None = None) -> asyncio.Task:
    """Create an asyncio task with automatic exception logging (prevents silent failures)."""
    task = asyncio.create_task(coro, name=name)

    def _log_exception(t: asyncio.Task) -> None:
        if t.cancelled():
            return
        exc = t.exception()
        if exc:
            logger.error("Background task %s failed: %s", name or t.get_name(), exc)

    task.add_done_callback(_log_exception)
    return task

# Circuit breaker settings
CB_FAILURE_THRESHOLD = 5  # failures before opening
CB_FAILURE_WINDOW = 60  # seconds
CB_RECOVERY_TIMEOUT = 30  # seconds to wait before retrying


class CircuitBreaker:
    """Simple circuit breaker for DB operations.

    States: closed (normal) → open (paused) → half-open (testing).
    Opens after CB_FAILURE_THRESHOLD failures within CB_FAILURE_WINDOW seconds.
    Stays open for CB_RECOVERY_TIMEOUT seconds, then allows one test request.

    Thread safety: This class is NOT thread-safe. It is only accessed from
    async coroutines on the main event loop (record_success/record_failure
    are called from _flush_batch and its callers, all in the event loop).
    Do NOT call from asyncio.to_thread() executor threads.
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
        self._storage_client = None  # supabase-py Client for Storage uploads only
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
        # _message_count is only mutated from asyncio coroutines (single-threaded
        # event loop), so no lock is needed. Do NOT access from executor threads.
        self._message_count = 0
        self._historical_crawl_running = False
        # _crawled_groups is only mutated from async coroutines on the main event
        # loop (never from executor threads), so no lock is needed.
        self._crawled_groups: set[int] = set()
        # Queue buffer between Telethon event handlers and DB writer
        self._msg_queue: asyncio.Queue = asyncio.Queue(maxsize=MSG_QUEUE_MAXSIZE)
        # Entity cache: telegram_id -> (access_hash, entity_type)
        # Persisted to Supabase `entity_cache` table to survive restarts
        self._entity_cache: dict[int, tuple[int, str, float]] = {}  # gid -> (access_hash, entity_type, last_access_time)
        # Circuit breaker for DB operations
        self._circuit_breaker = CircuitBreaker()
        # Gap-fill task
        self._gap_fill_task: asyncio.Task | None = None
        # File lock to prevent concurrent crawlers
        self._lock_file = None
        # Cooldown for get_dialogs() calls (expensive API call)
        self._last_dialogs_fetch: float = 0
        # Semaphore to limit concurrent entity resolution (prevents FloodWaitError storms)
        self._entity_semaphore = asyncio.Semaphore(3)
        # FloodWait penalty tracker: gid -> monotonic time when penalty expires.
        # Groups with active penalties are skipped in gap-fill/historical loops
        # instead of blocking the entire loop.
        self._flood_wait_until: dict[int, float] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Initialize multiple Telegram clients (one per admin user) and start crawling."""
        if self.running:
            logger.warning("Live crawler is already running")
            return

        # Acquire file lock to prevent concurrent crawlers (live + legacy)
        # sharing the same Telegram session, which causes forced disconnects.
        # Use /run if writable (systemd RuntimeDirectory), else app directory.
        lock_dir = Path("/run/aaltohub")
        if not lock_dir.exists():
            lock_dir = Path(__file__).resolve().parent.parent  # backend/
        lock_path = str(lock_dir / "aaltohub-crawler.lock")
        try:
            self._lock_file = open(lock_path, "w")
            fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._lock_file.write(str(os.getpid()))
            self._lock_file.flush()
        except (IOError, OSError):
            logger.error("Another crawler instance is already running (lock: %s). Aborting.", lock_path)
            if hasattr(self, "_lock_file") and self._lock_file:
                self._lock_file.close()
            return

        logger.info("=" * 60)
        logger.info("Initializing live crawler with multiple admin accounts...")
        logger.info("=" * 60)

        try:
            self._storage_client = get_storage_client()

            # Find all admin users
            admin_rows = await db.fetch(
                "SELECT * FROM users WHERE role = $1", UserRole.ADMIN.value
            )
            if not admin_rows:
                logger.error("Live crawler: No admin user found. Please login as admin first.")
                return

            logger.info("Live crawler: Found %d admin user(s)", len(admin_rows))

            # Initialize a Telethon client for each admin user
            for admin_user in admin_rows:
                admin_id = admin_user["id"]
                admin_name = admin_user.get("first_name") or "?"
                admin_username = admin_user.get("username") or "N/A"

                try:
                    # Load encrypted session
                    row = await db.fetchrow(
                        "SELECT session_data, key_hash FROM telethon_sessions WHERE user_id = $1",
                        admin_id,
                    )
                    if not row:
                        logger.warning("Live crawler: Admin %s (id=%s) has no session. Skipping.", admin_name, admin_id)
                        continue
                    aad = str(admin_id)
                    if row["key_hash"] == ENCRYPTION_VERSION:
                        session_string = session_encryption.decrypt(row["session_data"], aad=aad)
                    else:
                        # Legacy session — decrypt and re-encrypt with v2
                        from app.encryption import get_legacy_encryption
                        session_string = get_legacy_encryption().decrypt(row["session_data"])
                        new_encrypted = session_encryption.encrypt(session_string, aad=aad)
                        await db.execute(
                            "UPDATE telethon_sessions SET session_data = $1, key_hash = $2 WHERE user_id = $3",
                            new_encrypted, ENCRYPTION_VERSION, admin_id,
                        )
                        logger.info("Live crawler: Migrated session for admin %s to v2 encryption", admin_name)

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

            # Restore previously crawled groups to avoid re-crawling on restart
            try:
                crawled_rows = await db.fetch(
                    "SELECT group_id FROM crawler_status WHERE status = $1", "active"
                )
                if crawled_rows:
                    for r in crawled_rows:
                        try:
                            self._crawled_groups.add(int(r["group_id"]))
                        except (ValueError, TypeError):
                            pass
                    logger.info("Restored %d previously crawled groups", len(self._crawled_groups))
            except Exception as e:
                logger.warning("Failed to load crawled groups state: %s", e)

            self.connected = True

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

        # Release file lock
        if self._lock_file:
            try:
                fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_UN)
                self._lock_file.close()
            except Exception:
                pass
            self._lock_file = None

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
        retry=retry_if_exception_type(_TRANSIENT_EXCEPTIONS),
        reraise=True,
    )
    async def _db_upsert_batch(self, rows: list[dict], ignore_duplicates: bool = True) -> None:
        """Batch upsert messages via asyncpg executemany."""
        conflict = "ON CONFLICT (telegram_message_id, group_id) DO NOTHING" if ignore_duplicates else \
            "ON CONFLICT (telegram_message_id, group_id) DO UPDATE SET content = EXCLUDED.content, media_type = EXCLUDED.media_type, media_url = EXCLUDED.media_url, edited_at = EXCLUDED.edited_at, is_deleted = EXCLUDED.is_deleted"
        query = f"""INSERT INTO messages
            (telegram_message_id, group_id, sender_id, sender_name, content,
             media_type, media_url, reply_to_message_id, topic_id, is_deleted, sent_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            {conflict}"""
        args_list = [
            (
                r.get("telegram_message_id"), r.get("group_id"), r.get("sender_id"),
                r.get("sender_name"), r.get("content"), r.get("media_type"),
                r.get("media_url"), r.get("reply_to_message_id"), r.get("topic_id"),
                r.get("is_deleted", False), r.get("sent_at"),
            )
            for r in rows
        ]
        await db.executemany(query, args_list)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=4),
        retry=retry_if_exception_type(_TRANSIENT_EXCEPTIONS),
        reraise=True,
    )
    async def _db_upsert_single(self, row: dict, ignore_duplicates: bool = True) -> None:
        """Single message upsert via asyncpg."""
        conflict = "ON CONFLICT (telegram_message_id, group_id) DO NOTHING" if ignore_duplicates else \
            "ON CONFLICT (telegram_message_id, group_id) DO UPDATE SET content = EXCLUDED.content, media_type = EXCLUDED.media_type, media_url = EXCLUDED.media_url, edited_at = EXCLUDED.edited_at, is_deleted = EXCLUDED.is_deleted"
        query = f"""INSERT INTO messages
            (telegram_message_id, group_id, sender_id, sender_name, content,
             media_type, media_url, reply_to_message_id, topic_id, is_deleted, sent_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            {conflict}"""
        await db.execute(
            query,
            row.get("telegram_message_id"), row.get("group_id"), row.get("sender_id"),
            row.get("sender_name"), row.get("content"), row.get("media_type"),
            row.get("media_url"), row.get("reply_to_message_id"), row.get("topic_id"),
            row.get("is_deleted", False), row.get("sent_at"),
        )

    async def _broadcast(self, event: str, payload: dict) -> None:
        """Send a Postgres NOTIFY for SSE fan-out by the API process.

        The API process listens on the 'new_message' channel via SSEManager
        and fans out events to connected EventSource clients by group_id.

        Replaces the previous Supabase Realtime HTTP broadcast approach.
        Postgres NOTIFY payload limit is 8000 bytes — typical messages are
        ~500-1500 bytes, well within the limit.
        """
        try:
            notification = json.dumps({"event": event, "payload": payload}, default=str)
            # Truncate content if notification exceeds Postgres NOTIFY limit (8000 bytes)
            if len(notification) > 7900:
                payload = payload.copy()
                content = payload.get("content", "")
                if content and len(content) > 200:
                    payload["content"] = content[:200] + "..."
                notification = json.dumps({"event": event, "payload": payload}, default=str)
            await db.execute("SELECT pg_notify('new_message', $1)", notification)
        except Exception as e:
            logger.warning("NOTIFY failed for event=%s: %s", event, e)

    _DEAD_LETTER_FILE_MAX_BYTES = 50 * 1024 * 1024  # 50 MB cap

    async def _write_to_dead_letter(self, row: dict, error: str) -> None:
        """Write a failed message to the dead letter table for later retry.
        Falls back to local file if DB is also unreachable."""
        try:
            await db.execute(
                """INSERT INTO failed_messages (telegram_message_id, group_id, payload, error_message, retry_count)
                   VALUES ($1, $2, $3::jsonb, $4, 0)""",
                row.get("telegram_message_id"), row.get("group_id"),
                json.dumps(row), str(error)[:500],
            )
        except Exception as e:
            logger.error("Dead letter DB write failed: %s — writing to local file", e)
            try:
                # Use persistent path (not /tmp which may be private-namespaced by systemd)
                dl_path = Path(__file__).resolve().parent.parent / "dead-letters.jsonl"
                if dl_path.exists() and dl_path.stat().st_size > self._DEAD_LETTER_FILE_MAX_BYTES:
                    logger.error("Dead letter file exceeds %d MB — dropping message", self._DEAD_LETTER_FILE_MAX_BYTES // (1024 * 1024))
                    return
                with open(dl_path, "a") as f:
                    f.write(json.dumps({"row": row, "error": str(error)[:500], "ts": time.time()}) + "\n")
            except Exception as e2:
                logger.error("Local dead letter file write also failed: %s", e2)

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
                await self._write_to_dead_letter(item["data"], "circuit_breaker_open")
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
            persisted_items = inserts  # assume all persisted unless batch fails
            try:
                await self._db_upsert_batch(rows, True)
                self._circuit_breaker.record_success()
                logger.info("[BATCH] Upserted %d new messages", len(rows))
            except Exception as e:
                logger.warning("[BATCH] Bulk upsert failed (%s), falling back to individual", e)
                persisted_items = []
                for i, row in enumerate(rows):
                    try:
                        await self._db_upsert_single(row, True)
                        self._circuit_breaker.record_success()
                        persisted_items.append(inserts[i])
                    except Exception as e2:
                        self._circuit_breaker.record_failure()
                        logger.error("Upsert failed for msg %s: %s", row.get("telegram_message_id"), e2)
                        await self._write_to_dead_letter(row, str(e2))

            # Broadcast only confirmed-persisted messages (skip gap-fill re-checks)
            for item in persisted_items:
                if item.get("broadcast", True):
                    await self._broadcast("insert", item["data"])

        # --- Handle upserts (edits — ON CONFLICT DO UPDATE) ---
        for item in upserts:
            data = item["data"]
            if not data.get("media_url"):
                data.pop("media_url", None)
            try:
                await self._db_upsert_single(data, False)
                self._circuit_breaker.record_success()
                await self._broadcast("update", data)
            except Exception as e:
                self._circuit_breaker.record_failure()
                logger.error("Edit upsert failed for msg %s: %s", data.get("telegram_message_id"), e)
                await self._write_to_dead_letter(data, str(e))

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
        broadcast: bool = True,
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
                "group_id": int(group_uuid),  # Convert to int - DB expects BIGINT
                "sender_id": sender_id,
                "sender_name": sender_name,
                "content": message.text,
                "media_type": media_type,
                "media_url": media_url,
                "reply_to_message_id": message.reply_to_msg_id,
                "topic_id": topic_id,
                "is_deleted": False,
                "sent_at": message.date.isoformat(),
            }

            if is_edit:
                message_data["edited_at"] = datetime.now(timezone.utc).isoformat()

            queue_item = {
                "action": "upsert" if is_edit else "insert",
                "data": message_data,
                "group_uuid": group_uuid,
                "broadcast": broadcast and not is_edit,
            }

            try:
                self._msg_queue.put_nowait(queue_item)
            except asyncio.QueueFull:
                logger.warning("Message queue full (size=%d), sending msg %d to dead letter", MSG_QUEUE_MAXSIZE, message.id)
                _safe_create_task(
                    self._write_to_dead_letter(message_data, "queue_full"),
                    name=f"dead-letter-{message.id}",
                )

        except Exception as e:
            logger.error("Enqueue message %d error: %s", message.id, e)

    # ------------------------------------------------------------------
    # crawler_status management
    # ------------------------------------------------------------------

    async def _ensure_crawler_status_rows(self) -> None:
        """Ensure every registered group has a crawler_status row (single batch upsert)."""
        if not self.group_id_map:
            return
        args_list = [
            (int(gid), "initializing", True, 0, 0, 0)  # Convert to int - DB expects BIGINT
            for gid in self.group_id_map.values()
        ]
        try:
            await db.executemany(
                """INSERT INTO crawler_status (group_id, status, is_enabled, error_count, initial_crawl_progress, initial_crawl_total)
                   VALUES ($1, $2, $3, $4, $5, $6)
                   ON CONFLICT (group_id) DO NOTHING""",
                args_list,
            )
            logger.info("Ensured crawler_status rows for %d groups", len(self.group_id_map))
        except Exception as e:
            logger.warning("Failed to ensure crawler_status rows: %s", e)

    # ------------------------------------------------------------------
    # Group management
    # ------------------------------------------------------------------

    async def refresh_groups(self) -> None:
        """Load crawl-enabled groups from DB."""
        try:
            rows = await db.fetch(
                "SELECT * FROM groups WHERE crawl_enabled = TRUE"
            )
            if not rows:
                logger.info("Live crawler: no crawl-enabled groups found.")
                return

            # Build new dicts, then atomically swap references.
            # This prevents event handlers from seeing empty dicts during rebuild.
            old_ids = set(self.group_id_map.keys())
            new_id_map: dict[int, str] = {}
            new_info_map: dict[int, dict] = {}

            for group in rows:
                gid = group["id"]
                new_id_map[gid] = str(gid)
                new_info_map[gid] = dict(group)

            # Atomic swap — assign both maps in a single tuple unpack so event handlers
            # never see a mix of old id_map + new info_map (or vice versa).
            # CPython's GIL ensures tuple unpacking is atomic at the bytecode level.
            self.group_id_map, self.group_info_map = new_id_map, new_info_map

            new_ids = set(new_id_map.keys()) - old_ids
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
        """Load persisted entity cache from DB on startup."""
        try:
            rows = await db.fetch("SELECT telegram_id, access_hash, entity_type FROM entity_cache")
            import time as _time
            now = _time.monotonic()
            for row in rows:
                self._entity_cache[row["telegram_id"]] = (row["access_hash"], row["entity_type"], now)
            logger.info("Entity cache: loaded %d entries from DB", len(self._entity_cache))
        except Exception as e:
            # Table may not exist yet — that's fine, cache starts empty
            logger.debug("Entity cache load failed (table may not exist): %s", e)

    async def _save_entity_to_cache_db(self, gid: int, access_hash: int, entity_type: str) -> None:
        """Async DB write for entity cache."""
        try:
            await db.execute(
                """INSERT INTO entity_cache (telegram_id, access_hash, entity_type)
                   VALUES ($1, $2, $3)
                   ON CONFLICT (telegram_id) DO UPDATE SET access_hash = $2, entity_type = $3""",
                gid, access_hash, entity_type,
            )
        except Exception as e:
            logger.debug("Entity cache DB write failed for %s: %s", gid, e)

    def _save_entity_to_cache(self, gid: int, access_hash: int, entity_type: str) -> None:
        """Persist a single entity cache entry to memory + fire-and-forget DB write."""
        import time as _time
        # Evict least recently used entries if cache exceeds max size
        if len(self._entity_cache) >= ENTITY_CACHE_MAX_SIZE:
            evict_count = len(self._entity_cache) - ENTITY_CACHE_MAX_SIZE + 1
            lru_keys = sorted(self._entity_cache, key=lambda k: self._entity_cache[k][2])[:evict_count]
            for k in lru_keys:
                del self._entity_cache[k]
        self._entity_cache[gid] = (access_hash, entity_type, _time.monotonic())
        _safe_create_task(
            self._save_entity_to_cache_db(gid, access_hash, entity_type),
            name=f"entity-cache-{gid}",
        )

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
            import time as _time
            access_hash, entity_type = cached[0], cached[1]
            # Update access time for LRU eviction
            self._entity_cache[gid] = (access_hash, entity_type, _time.monotonic())
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
                    await db.execute("DELETE FROM entity_cache WHERE telegram_id = $1", gid)
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
        # Throttle: get_dialogs() is expensive, skip if called recently
        now = time.monotonic()
        if now - self._last_dialogs_fetch < DIALOGS_COOLDOWN:
            logger.debug("Entity cache miss for %s — get_dialogs() on cooldown (%ds remaining)",
                         gid, int(DIALOGS_COOLDOWN - (now - self._last_dialogs_fetch)))
        else:
            logger.debug("Entity cache miss for %s — warming cache via get_dialogs()...", gid)
            self._last_dialogs_fetch = now
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
        """Resolve by iterating all available admin clients until one succeeds.

        Limited by _entity_semaphore to prevent concurrent FloodWaitError storms
        when gap-fill, historical crawl, and event handlers resolve simultaneously.
        """
        async with self._entity_semaphore:
            if not self.clients:
                raise ValueError("No admin clients available")
            last_err = None
            for client in self.clients.values():
                try:
                    return await self._get_entity_for_group_with_client(gid, client)
                except Exception as e:
                    last_err = e
                    continue
            raise ValueError(f"Could not resolve entity for group {gid} with any client: {last_err}")

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

        FloodWaitError does NOT block the loop — penalized groups are skipped
        until their penalty expires, so remaining groups still get gap-filled.
        """
        while self.running:
            await asyncio.sleep(GAP_FILL_INTERVAL)
            if not self.running:
                break
            logger.info("[GAP-FILL] Starting gap-fill re-check (%d groups)...", len(self.group_id_map))
            filled = 0
            skipped_flood = 0
            now = time.monotonic()
            for gid in list(self.group_id_map.keys()):
                if not self.running:
                    break
                # Skip groups with active FloodWait penalty
                penalty_until = self._flood_wait_until.get(gid, 0)
                if now < penalty_until:
                    skipped_flood += 1
                    continue
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
                            await self._enqueue_message(message, gid, group_uuid, client=working_client, broadcast=False)
                            count += 1
                        if count >= GAP_FILL_MAX_MESSAGES:
                            break
                        if count % 200 == 0 and count > 0:
                            await asyncio.sleep(1.5)
                    filled += count

                except FloodWaitError as e:
                    logger.warning("[GAP-FILL] FloodWait %ds for group %s — skipping, will retry after penalty", e.seconds, gid)
                    self._flood_wait_until[gid] = time.monotonic() + e.seconds
                except Exception as e:
                    logger.debug("[GAP-FILL] Error for group %s: %s", gid, e)

            if skipped_flood:
                logger.info("[GAP-FILL] Skipped %d groups with active FloodWait penalties", skipped_flood)
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
                # Skip groups with active FloodWait penalty
                if time.monotonic() < self._flood_wait_until.get(gid, 0):
                    logger.info("Skipping historical crawl for group %s — FloodWait penalty active", gid)
                    continue
                group_uuid = self.group_id_map[gid]
                try:
                    existing_count = await db.fetchval(
                        "SELECT COUNT(*) FROM messages WHERE group_id = $1 AND is_deleted = FALSE",
                        int(group_uuid),
                    ) or 0
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
                    logger.warning(
                        "FloodWait during historical crawl for %s: %ds — recording penalty, breaking iteration",
                        title, e.seconds,
                    )
                    self._flood_wait_until[gid] = time.monotonic() + e.seconds
                    break  # Exit iter_messages; group retries on next _periodic_group_refresh cycle
                except Exception as e:
                    logger.warning("Error enqueuing msg %d: %s", message.id, e)

            # Wait for queue to drain before marking complete (with timeout)
            drain_start = time.monotonic()
            drained = True
            while not self._msg_queue.empty():
                if time.monotonic() - drain_start > QUEUE_DRAIN_TIMEOUT:
                    logger.warning("Queue drain timeout (%ds) for %s — %d items remaining",
                                   QUEUE_DRAIN_TIMEOUT, title, self._msg_queue.qsize())
                    drained = False
                    break
                await asyncio.sleep(0.5)

            # Only mark fully "active" if queue drained completely (P2-1.24)
            if drained:
                await self._update_crawler_status(
                    group_uuid, "active",
                    progress=enqueued_count, total=enqueued_count
                )
            else:
                await self._update_crawler_status(
                    group_uuid, "active",
                    progress=enqueued_count, total=enqueued_count,
                    error=f"Queue drain timeout — {self._msg_queue.qsize()} items pending"
                )
            self._crawled_groups.add(gid)
            await self._update_group_last_error(gid, "")
            logger.info("Historical crawl complete: %s — %d messages enqueued", title, enqueued_count)

        except (ChannelPrivateError, ChatAdminRequiredError) as e:
            logger.error("Access denied for %s: %s", title, e)
            await self._update_crawler_status(group_uuid, "error", error=str(e))
            await self._update_group_last_error(gid, str(e))
        except FloodWaitError as e:
            logger.warning("FloodWait for %s: %ds — recording penalty, moving to next group", title, e.seconds)
            await self._update_crawler_status(group_uuid, "error", error=f"FloodWait: {e.seconds}s")
            self._flood_wait_until[gid] = time.monotonic() + e.seconds
        except Exception as e:
            logger.error("Historical crawl failed for %s: %s", title, e)
            logger.error(traceback.format_exc())
            await self._update_crawler_status(group_uuid, "error", error=str(e))
            await self._update_group_last_error(gid, str(e))

    async def _update_crawler_status(
        self, group_uuid: str, status: str,
        error: str | None = None, progress: int | None = None, total: int | None = None
    ) -> None:
        """Update crawler_status row — async via asyncpg."""
        try:
            now = datetime.now(timezone.utc)
            # Build dynamic SET clause
            sets = ["status = $1", "updated_at = $2"]
            args: list = [status, now]
            idx = 3

            if error:
                sets.append(f"last_error = ${idx}")
                args.append(error)
                idx += 1
            if progress is not None:
                sets.append(f"initial_crawl_progress = ${idx}")
                args.append(progress)
                idx += 1
            if total is not None:
                sets.append(f"initial_crawl_total = ${idx}")
                args.append(total)
                idx += 1
            if status == "active":
                sets.append(f"last_message_at = ${idx}")
                args.append(now)
                idx += 1

            args.append(int(group_uuid))  # Convert to int - DB expects BIGINT
            query = f"UPDATE crawler_status SET {', '.join(sets)} WHERE group_id = ${idx}"
            await db.execute(query, *args)
        except Exception as e:
            logger.warning("Failed to update crawler_status for %s: %s", group_uuid, e)

    async def _update_group_last_error(self, gid: int, error: str) -> None:
        """Update groups.last_error so admin dashboard can show it."""
        try:
            await db.execute("UPDATE groups SET last_error = $1 WHERE id = $2", error, gid)
        except Exception as e:
            logger.warning("Failed to update groups.last_error for %s: %s", gid, e)

    # ------------------------------------------------------------------
    # Enabled check (cached)
    # ------------------------------------------------------------------

    async def _is_group_enabled(self, group_uuid: str) -> bool:
        """Check if group crawling is enabled (cached, async via asyncpg)."""
        now = time.monotonic()
        cached = self._enabled_cache.get(group_uuid)
        if cached and (now - cached[1]) < ENABLED_CACHE_TTL:
            return cached[0]
        try:
            val = await db.fetchval(
                "SELECT is_enabled FROM crawler_status WHERE group_id = $1", int(group_uuid)  # Convert to int - DB expects BIGINT
            )
            enabled = val if val is not None else True
        except Exception:
            enabled = True
        # Evict oldest entries if cache exceeds max size
        if len(self._enabled_cache) >= ENABLED_CACHE_MAX_SIZE:
            oldest = sorted(self._enabled_cache, key=lambda k: self._enabled_cache[k][1])
            for k in oldest[:len(self._enabled_cache) - ENABLED_CACHE_MAX_SIZE + 1]:
                del self._enabled_cache[k]
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
                    deleted_ids = list(event.deleted_ids)
                    logger.info("[DELETE] %s: %d msgs", self._get_group_title(chat_id), len(deleted_ids))
                    # Single batch UPDATE instead of N individual queries
                    await db.execute(
                        "UPDATE messages SET is_deleted = TRUE WHERE telegram_message_id = ANY($1::bigint[]) AND group_id = $2",
                        deleted_ids, int(group_uuid),
                    )
                    for msg_id in deleted_ids:
                        await self._broadcast("update", {
                            "telegram_message_id": msg_id,
                            "group_id": group_uuid,
                            "is_deleted": True,
                        })
                except Exception as e:
                    logger.error("Live crawler delete error: %s", e)

            @_client.on(events.ChatAction)
            async def on_chat_action(event):
                """Detect supergroup migration — log CRITICAL alert and disable crawling."""
                try:
                    if not hasattr(event, 'action_message') or not event.action_message:
                        return
                    action = event.action_message.action
                    if not isinstance(action, MessageActionChatMigrateTo):
                        return
                    old_id = self._normalize_chat_id(event.chat_id)
                    new_id = action.channel_id
                    if old_id not in self.group_id_map:
                        return
                    group_uuid = self.group_id_map[old_id]
                    logger.critical(
                        "SUPERGROUP MIGRATION DETECTED: group %s (uuid=%s) migrated from %d to %d. "
                        "Disabling crawling — manual migration required (update groups.id and all FK references).",
                        self._get_group_title(old_id), group_uuid, old_id, new_id,
                    )
                    await self._update_crawler_status(
                        group_uuid, "error",
                        error=f"Supergroup migration: {old_id} → {new_id}. Manual fix required.",
                    )
                    await self._update_group_last_error(old_id, f"Supergroup migration to {new_id}")
                except Exception as e:
                    logger.error("Chat action handler error: %s", e)

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

            if len(file_bytes) > MAX_MEDIA_BYTES:
                logger.info("Media for msg %d too large (%d bytes), skipping upload", message.id, len(file_bytes))
                return None, None

            file_ext = "jpg" if "jpeg" in content_type or "jpg" in content_type else "bin"
            file_path = f"{group_uuid}/{message.id}.{file_ext}"

            storage = self._storage_client or get_storage_client()
            await asyncio.to_thread(
                lambda: storage.storage.from_("message-media").upload(
                    file_path, file_bytes, {"content-type": content_type}
                )
            )
            public_url = storage.storage.from_("message-media").get_public_url(file_path)

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
