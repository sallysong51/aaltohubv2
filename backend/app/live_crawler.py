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
    InviteHashInvalidError,
    InviteHashExpiredError,
)
from telethon.tl.types import (
    InputPeerChannel,
    InputPeerChat,
    MessageActionChatMigrateTo,
    PeerChannel,
    PeerChat,
    Channel,
    Chat,
)
import asyncpg
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.entity_parser import MessageEntityParser
from app.error_recovery import GetMeErrorRecovery
from app.media_uploader import MediaUploader
from app.metrics import GapFillMetrics, MessageMetrics
from app.reference_discovery import ReferenceDiscovery
from app.web_scraper import WebScraper
from app.telegram_auto_join import TelegramAutoJoin
from app.context_aggregator import ContextAggregator
from app.ai.classifier import AIClassifier

# Transient exceptions that justify a retry (not programming bugs)
_TRANSIENT_EXCEPTIONS = (
    ConnectionError, TimeoutError, OSError,
    asyncpg.PostgresConnectionError, asyncpg.InterfaceError,
)

from app.config import settings
from app.database import db, get_storage_client
from app.encryption import session_encryption, ENCRYPTION_VERSION
from app.models import UserRole
from app.crawler.circuit_breaker import CircuitBreaker, CB_FAILURE_THRESHOLD, CB_FAILURE_WINDOW, CB_RECOVERY_TIMEOUT
from app.crawler.utils import normalize_chat_id, detect_media_type, select_photo_size

logger = logging.getLogger(__name__)

GROUP_REFRESH_INTERVAL = 60  # 1 minute — reduced from 5min so newly registered groups start live listening faster
ENABLED_CACHE_TTL = 60  # seconds
HISTORICAL_CRAWL_DAYS = 14
RECONNECT_DELAY = 10  # seconds
MAX_RECONNECT_ATTEMPTS = 10
MSG_QUEUE_MAXSIZE = 10000
BATCH_SIZE = 50  # max messages per batch insert
BATCH_TIMEOUT = 2.0  # seconds to wait for more messages before flushing
GAP_FILL_INTERVAL = 900  # 15 minutes (2x frequency for 3-hour SLA)
GAP_FILL_LOOKBACK_HOURS = 3  # re-check last 3 hours of messages (3-hour SLA guarantee)
GAP_FILL_MAX_MESSAGES = 2000  # max messages per group during gap-fill (covers high-volume groups)
DIALOGS_COOLDOWN = 600  # 10 minutes — minimum interval between get_dialogs() calls
QUEUE_DRAIN_TIMEOUT = 60  # seconds — max wait for queue to drain after historical crawl
MAX_MEDIA_BYTES = 10 * 1024 * 1024  # 10 MB — skip media larger than this
ENTITY_CACHE_MAX_SIZE = 5000  # max entries before LRU-style eviction
ENABLED_CACHE_MAX_SIZE = 1000  # max entries before eviction
MEDIA_CONCURRENCY = 5  # max concurrent media downloads during batch operations
MEDIA_DOWNLOAD_BATCH = 50  # process media in chunks for progress tracking


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


# CircuitBreaker imported from app.crawler.circuit_breaker


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
        self._circuit_breaker_was_open = False
        # Gap-fill task
        self._gap_fill_task: asyncio.Task | None = None
        # File lock to prevent concurrent crawlers
        self._lock_file = None
        # Cooldown for get_dialogs() calls (expensive API call)
        self._last_dialogs_fetch: float = 0
        # Semaphore to limit concurrent entity resolution (prevents FloodWaitError storms)
        self._entity_semaphore = asyncio.Semaphore(3)
        # Semaphore for concurrent media downloads (historical crawl, gap-fill)
        self._media_semaphore = asyncio.Semaphore(MEDIA_CONCURRENCY)
        # FloodWait penalty tracker: gid -> monotonic time when penalty expires.
        # Groups with active penalties are skipped in gap-fill/historical loops
        # instead of blocking the entire loop.
        self._flood_wait_until: dict[int, float] = {}
        # Manual crawl tasks triggered via admin API
        self._manual_crawl_tasks: dict[str, asyncio.Task] = {}
        # Granular crawl tracking for dashboard visibility
        self._currently_crawling_group_id: int | None = None
        self._batch_crawl_active = False
        self._last_event_received_at: float = 0
        self._watchdog_task: asyncio.Task | None = None
        # Per-group crawl lock: prevents concurrent crawl of same group by startup + batch
        self._crawling_groups_lock: set[int] = set()
        # Track last gap-fill completion for dynamic lookback after outages
        self._last_gap_fill_at: float = 0
        # Last start failure reason, cleared on success — exposed via get_status()
        self._start_error: str | None = None
        # Auto-join unmapped groups task
        self._auto_join_task: asyncio.Task | None = None
        # Track last auto-join to avoid too frequent attempts
        self._last_auto_join_at: float = 0
        # Dedup set: prevents the same message being enqueued multiple times
        # when multiple admin clients receive the same NewMessage event.
        # Key: (telegram_message_id, group_id) → enqueue timestamp (monotonic)
        self._enqueue_dedup: dict[tuple[int, int], float] = {}
        self._enqueue_dedup_last_cleanup: float = 0
        # Background task that waits for an admin session to appear
        self._admin_wait_task: asyncio.Task | None = None

        # Phase 2: Duplicate Prevention — ensure each group is only listened by correct connection
        # Populated at startup to map:
        # - telegram_user_id (from client.get_me()) → connection_id (UUID)
        # - group_id (telegram group ID) → connection_id (which connection should handle it, or None if unassigned)
        self._telegram_user_id_to_connection_id: dict[int, str] = {}  # telegram_user_id (int) -> connection_id (UUID str)
        self._group_to_connection_id: dict[int, str | None] = {}  # group_id (telegram group ID) -> connection_id (UUID str) or None

        # Phase 2A: Error Recovery & Resilience — extract to separate module
        self._error_recovery = GetMeErrorRecovery()

        # Phase 2B: Logging Optimization — metrics tracking (extract to separate module)
        self._metrics = MessageMetrics(self._get_group_title)
        self._gap_fill_metrics = GapFillMetrics()  # Phase 33: 3-hour SLA monitoring

        # Phase 3: External Reference Discovery & Auto-Crawling
        self._reference_discovery = ReferenceDiscovery()
        self._web_scraper = WebScraper()
        self._telegram_auto_join = TelegramAutoJoin(self)  # Pass self as client manager
        self._context_aggregator = ContextAggregator()

        # Phase 3: AI Classification — async message classification with cost optimization
        self._ai_classifier = AIClassifier()

        # Phase 33: Media uploader — extracted to separate module
        self._media_uploader = MediaUploader()

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
            # Check if the lock holder is still alive
            stale = False
            try:
                with open(lock_path, "r") as f:
                    old_pid = int(f.read().strip())
                os.kill(old_pid, 0)  # Raises OSError if process is dead
            except (OSError, ValueError):
                stale = True

            if stale:
                logger.warning("Stale lock file found (dead PID). Reclaiming lock: %s", lock_path)
                if self._lock_file:
                    self._lock_file.close()
                try:
                    os.unlink(lock_path)
                except OSError:
                    pass
                # Retry once
                try:
                    self._lock_file = open(lock_path, "w")
                    fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    self._lock_file.write(str(os.getpid()))
                    self._lock_file.flush()
                except (IOError, OSError):
                    self._start_error = "Could not acquire lock even after removing stale file"
                    logger.error("Live crawler: %s: %s", self._start_error, lock_path)
                    if self._lock_file:
                        self._lock_file.close()
                    return
            else:
                self._start_error = f"Another crawler instance is already running (PID {old_pid})"
                logger.error("Live crawler: %s (lock: %s)", self._start_error, lock_path)
                if self._lock_file:
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
                self._start_error = "No admin user found. Run: python scripts/bootstrap_session.py --phone +PHONE"
                logger.warning("Live crawler: %s", self._start_error)
                logger.warning("Live crawler: Will retry every 60s until an admin session is available...")
                self._release_lock()
                self._admin_wait_task = asyncio.create_task(self._wait_for_admin_session())
                return

            admin_ids = [r["id"] for r in admin_rows]
            logger.info("Live crawler: Found %d admin user(s)", len(admin_rows))

            # Load sessions: try telegram_connections first (multi-account), then telethon_sessions (legacy)
            tc_rows = await db.fetch(
                """SELECT tc.id AS connection_id, tc.user_id, tc.telegram_user_id,
                          tc.session_encrypted, tc.key_hash, tc.username, tc.first_name
                   FROM telegram_connections tc
                   WHERE tc.user_id = ANY($1::bigint[])""",
                admin_ids,
            )

            # Track which admin_ids have connections (to fallback for those without)
            admins_with_connections = set()
            for tc_row in tc_rows:
                conn_id = str(tc_row["connection_id"])
                admin_id = tc_row["user_id"]
                admin_name = tc_row.get("first_name") or "?"
                admin_username = tc_row.get("username") or "N/A"
                admins_with_connections.add(admin_id)

                try:
                    aad = str(admin_id)
                    if tc_row["key_hash"] == ENCRYPTION_VERSION:
                        session_string = session_encryption.decrypt(tc_row["session_encrypted"], aad=aad)
                    else:
                        from app.encryption import get_legacy_encryption
                        session_string = get_legacy_encryption().decrypt(tc_row["session_encrypted"])

                    client = TelegramClient(
                        StringSession(session_string),
                        settings.TELEGRAM_API_ID,
                        settings.TELEGRAM_API_HASH,
                        use_ipv6=False,
                        request_retries=3,
                        connection_retries=5,
                        retry_delay=3,
                        timeout=120,
                        flood_sleep_threshold=300,
                        auto_reconnect=True,
                    )
                    logger.info("Live crawler: Connecting for %s (@%s) [conn=%s]...", admin_name, admin_username, conn_id[:8])
                    await client.connect()

                    me = await client.get_me()
                    if not me:
                        logger.warning("Live crawler: Auth failed for connection %s. Skipping.", conn_id[:8])
                        await client.disconnect()
                        continue

                    self.clients[admin_id] = client
                    logger.info("Live crawler: ✓ Connected as %s (@%s) [conn=%s]", me.first_name, me.username, conn_id[:8])
                except Exception as e:
                    logger.error("Live crawler: Failed connection %s: %s", conn_id[:8], e)
                    continue

            # Fallback: load from telethon_sessions for admins WITHOUT telegram_connections
            for admin_user in admin_rows:
                admin_id = admin_user["id"]
                if admin_id in admins_with_connections or admin_id in self.clients:
                    continue

                admin_name = admin_user.get("first_name") or "?"
                admin_username = admin_user.get("username") or "N/A"

                try:
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
                        try:
                            from app.encryption import get_legacy_encryption
                            session_string = get_legacy_encryption().decrypt(row["session_data"])
                            new_encrypted = session_encryption.encrypt(session_string, aad=aad)
                            await db.execute(
                                "UPDATE telethon_sessions SET session_data = $1, key_hash = $2 WHERE user_id = $3",
                                new_encrypted, ENCRYPTION_VERSION, admin_id,
                            )
                            logger.info("Live crawler: Migrated session for admin %s to v2 encryption", admin_name)
                        except Exception as decrypt_err:
                            logger.warning(
                                "Live crawler: Cannot decrypt legacy session for %s (id=%s). Error: %s",
                                admin_name, admin_id, type(decrypt_err).__name__,
                            )
                            continue

                    client = TelegramClient(
                        StringSession(session_string),
                        settings.TELEGRAM_API_ID,
                        settings.TELEGRAM_API_HASH,
                        use_ipv6=False,
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
                self._start_error = "Admin users found but no sessions available. Run: python scripts/bootstrap_session.py --phone +PHONE"
                logger.warning("Live crawler: %s", self._start_error)
                logger.warning("Live crawler: Will retry every 60s until a session is available...")
                self._release_lock()
                self._admin_wait_task = asyncio.create_task(self._wait_for_admin_session())
                return

            self.running = True
            self._start_error = None  # Clear any previous error
            self._started_at = datetime.now(timezone.utc)
            self._message_count = 0

            # Auto-register all groups admin is member of
            await self._auto_register_admin_groups()

            # Load groups (shared across all clients)
            await self.refresh_groups()

            # Discover which groups each connection can access (for multi-connection backfill)
            await self.discover_group_accessibility()

            # Load connection-group mappings (prevents duplicate listening for multi-connection admins)
            await self._load_connection_group_mappings()

            # Load persisted entity cache (avoids get_entity API calls on restart)
            await self._load_entity_cache()

            # Ensure crawler_status rows exist for all groups
            await self._ensure_crawler_status_rows()

            # Register event handlers on all clients
            self._register_event_handlers()

            # Start DB writer coroutine (consumes from queue)
            self._writer_task = asyncio.create_task(self._db_writer())

            # Start background workers for new features (must be after event loop is running)
            await self._ai_classifier.start()
            await self._web_scraper.start()
            await self._telegram_auto_join.start()
            await self._context_aggregator.start()

            # Start listener tasks (one per admin client)
            for user_id, client in self.clients.items():
                self._start_listener_task(user_id, client)

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
            self._sla_monitor_task = asyncio.create_task(self._monitor_sla())  # Phase 33: SLA monitoring
            self._watchdog_task = asyncio.create_task(self._listener_watchdog())
            self._auto_join_task = asyncio.create_task(self._periodic_auto_join_groups())

            logger.info("Live crawler started!")
            logger.info("  - %d admin account(s) connected", len(self.clients))
            logger.info("  - %d groups loaded", len(self.group_id_map))
            logger.info("  - DB writer active (queue maxsize=%d, batch_size=%d)", MSG_QUEUE_MAXSIZE, BATCH_SIZE)
            logger.info("  - Historical crawl starting...")
            logger.info("  - Real-time events active")

        except Exception as e:
            self._start_error = f"Startup failed: {e}"
            logger.error("Live crawler failed to start: %s", e)
            logger.error(traceback.format_exc())
            await self._cleanup()
            self._release_lock()

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
        for task in [self._refresh_task, self._historical_task, self._gap_fill_task, self._watchdog_task, self._auto_join_task]:
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
        self._release_lock()

        logger.info("Live crawler stopped.")

    async def restart(self) -> None:
        """Restart the crawler."""
        await self.stop()
        await asyncio.sleep(1)
        await self.start()

    def _release_lock(self) -> None:
        """Release the file lock if held."""
        if self._lock_file:
            try:
                fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_UN)
                self._lock_file.close()
            except Exception:
                pass
            self._lock_file = None

    async def _wait_for_admin_session(self) -> None:
        """Periodically check for admin sessions and auto-start when available."""
        attempt = 0
        while not self.running:
            await asyncio.sleep(60)
            attempt += 1
            try:
                admin_rows = await db.fetch(
                    "SELECT id FROM users WHERE role = $1", UserRole.ADMIN.value
                )
                if not admin_rows:
                    if attempt % 5 == 0:  # log every 5 minutes
                        logger.warning(
                            "Live crawler: Still no admin user (check #%d). "
                            "Run: python scripts/bootstrap_session.py --phone +PHONE",
                            attempt,
                        )
                    continue

                admin_ids = [r["id"] for r in admin_rows]
                session_count = await db.fetchval(
                    "SELECT COUNT(*) FROM telethon_sessions WHERE user_id = ANY($1::bigint[])",
                    admin_ids,
                )
                if session_count > 0:
                    logger.info("Live crawler: Admin session detected! Starting crawler (attempt #%d)...", attempt)
                    self._start_error = None
                    self._admin_wait_task = None
                    await self.start()
                    return
                else:
                    if attempt % 5 == 0:
                        logger.warning(
                            "Live crawler: %d admin(s) found but no sessions stored (check #%d).",
                            len(admin_rows), attempt,
                        )
            except Exception as e:
                if attempt % 5 == 0:
                    logger.warning("Live crawler: Admin session check failed: %s", e)

    async def _cleanup(self) -> None:
        self.connected = False
        for user_id, client in self.clients.items():
            try:
                await client.disconnect()
            except Exception:
                pass
        self.clients.clear()
        # Phase 2: Clear connection-group mappings
        self._telegram_user_id_to_connection_id.clear()
        self._group_to_connection_id.clear()
        # Phase 2A: Clear error recovery tracking (delegate to module)
        self._error_recovery.clear()
        # Phase 2B: Clear metrics tracking (delegate to module)
        self._metrics.clear()
        # Phase 33: Clear gap-fill SLA metrics
        self._gap_fill_metrics.clear()
        # Phase 3: Cleanup AI classifier (delegate to module)
        await self._ai_classifier.cleanup()

    def get_status(self) -> dict:
        # Phase 2B: Get aggregated metrics from metrics module
        metrics_summary = self._metrics.get_summary()

        return {
            "running": self.running,
            "connected": self.connected,
            "start_error": self._start_error,
            "groups_count": len(self.group_id_map),
            "groups_monitored": len(self.group_id_map),
            "messages_received": self._message_count,
            # Phase 2B: Message handling metrics (delegated to metrics module)
            "messages_handled": metrics_summary["messages_handled"],
            "messages_skipped": metrics_summary["messages_skipped"],
            "skip_reasons": metrics_summary["skip_reasons"],
            "historical_crawl_running": self._historical_crawl_running or self._batch_crawl_active,
            "currently_crawling_group_id": self._currently_crawling_group_id,
            "currently_crawling_group_title": (
                self._get_group_title(self._currently_crawling_group_id)
                if self._currently_crawling_group_id else None
            ),
            "crawled_groups": len(self._crawled_groups),
            "queue_size": self._msg_queue.qsize(),
            "started_at": self._started_at.isoformat() if self._started_at else None,
            "uptime_seconds": (
                int((datetime.now(timezone.utc) - self._started_at).total_seconds())
                if self._started_at and self.running
                else 0
            ),
            "seconds_since_last_event": (
                int(time.monotonic() - self._last_event_received_at)
                if self._last_event_received_at > 0 else None
            ),
            "waiting_for_admin": (
                not self.running
                and self._admin_wait_task is not None
                and not self._admin_wait_task.done()
            ),
            # Phase 3: AI classifier stats
            "ai_classifier": self._ai_classifier.get_stats(),
            # Phase 33: Gap-fill SLA monitoring
            "gap_fill_at_risk": self._gap_fill_metrics.get_groups_exceeding_sla(sla_hours=2.5),
            # Phase 34: System diagnostics
            "circuit_breaker": {
                "state": "open" if self._circuit_breaker.is_open else "closed",
                "failure_count": self._circuit_breaker.failure_count,
                "consecutive_opens": getattr(self._circuit_breaker, '_consecutive_opens', 0),
            },
            "dead_letter_queue_size": self._get_dead_letter_queue_size(),
            "floodwait_penalties": self._floodwait_penalties,
            "get_me_cache_size": len(self._error_recovery._get_me_cache) if hasattr(self._error_recovery, '_get_me_cache') else 0,
            "get_me_circuit_open_count": sum(1 for exp in (self._error_recovery._get_me_circuit_open.values() if hasattr(self._error_recovery, '_get_me_circuit_open') else []) if exp > time.time()),
            "manual_crawl_tasks_count": len(self._manual_crawl_tasks),
            "batch_crawl_active": self._batch_crawl_active,
            "batch_crawl_queue_size": getattr(self, '_batch_crawl_queue_size', 0),
            "active_listeners": {
                str(user_id): {
                    "username": client_info.get("username"),
                    "connection_id": client_info.get("connection_id"),
                }
                for user_id, client_info in self.user_id_client_map.items()
            },
            "status": self._get_overall_status(),
            "last_activity": self._started_at.isoformat() if self._started_at else None,
        }

    def _get_overall_status(self) -> str:
        """Calculate overall crawler status for diagnostics."""
        if not self.running:
            return "stopped"
        if self._circuit_breaker.is_open:
            return "degraded"
        if self._batch_crawl_active or self._historical_crawl_running:
            return "crawling"
        if self.connected and len(self.user_id_client_map) > 0:
            return "active"
        return "initializing"

    def _get_dead_letter_queue_size(self) -> int:
        """Get size of dead letter queue (from file)."""
        try:
            dlq_path = Path("data/dead_letter_queue.jsonl")
            if not dlq_path.exists():
                return 0
            # Count lines in file
            with open(dlq_path, "r") as f:
                return sum(1 for _ in f)
        except Exception as e:
            logger.error("Failed to get dead letter queue size: %s", e)
            return 0

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
                try:
                    await self._flush_batch(batch)
                except Exception as e:
                    logger.error(
                        "[DB-WRITER] _flush_batch crashed — writing %d messages to dead letter: %s\n%s",
                        len(batch), e, traceback.format_exc(),
                    )
                    for item in batch:
                        try:
                            await self._write_to_dead_letter(item.get("data", item), f"flush_batch_crash: {e}")
                        except Exception:
                            pass

        # Final drain on shutdown
        remaining_items: list[dict] = []
        while not self._msg_queue.empty():
            try:
                remaining_items.append(self._msg_queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        if remaining_items:
            try:
                await self._flush_batch(remaining_items)
            except Exception as e:
                logger.error("[DB-WRITER] Final drain flush failed: %s", e)
                for item in remaining_items:
                    try:
                        await self._write_to_dead_letter(item.get("data", item), f"final_drain_crash: {e}")
                    except Exception:
                        pass

        logger.info("DB writer stopped.")

    # Retry decorator for transient DB failures (exponential backoff: 1s, 2s, 4s)
    @retry(
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type(_TRANSIENT_EXCEPTIONS),
        reraise=True,
    )
    async def _db_upsert_batch(self, rows: list[dict], ignore_duplicates: bool = True) -> None:
        """Batch upsert messages via asyncpg executemany.

        Phase 34: Extended to 15 params (added links, mentions, photo_count).
        """
        from app.queries.messages import message_upsert_sql
        query = message_upsert_sql(ignore_duplicates)
        args_list = [
            (
                r.get("telegram_message_id"), r.get("group_id"), r.get("sender_id"),
                r.get("sender_name"), r.get("content"), r.get("media_type"),
                r.get("media_url"), r.get("reply_to_message_id"), r.get("topic_id"),
                r.get("is_deleted", False), r.get("sent_at"), r.get("message_source", "realtime"),
                r.get("links"), r.get("mentions"), r.get("photo_count"),  # Phase 34
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
        """Single message upsert via asyncpg.

        Phase 34: Extended to 15 params (added links, mentions, photo_count).
        """
        from app.queries.messages import message_upsert_sql
        query = message_upsert_sql(ignore_duplicates)
        await db.execute(
            query,
            row.get("telegram_message_id"), row.get("group_id"), row.get("sender_id"),
            row.get("sender_name"), row.get("content"), row.get("media_type"),
            row.get("media_url"), row.get("reply_to_message_id"), row.get("topic_id"),
            row.get("is_deleted", False), row.get("sent_at"), row.get("message_source", "realtime"),
            row.get("links"), row.get("mentions"), row.get("photo_count"),  # Phase 34
        )

    async def _check_cb_recovery(self) -> None:
        """If circuit breaker was open and just recovered, notify SSE clients to refresh."""
        if self._circuit_breaker_was_open and not self._circuit_breaker.is_open:
            self._circuit_breaker_was_open = False
            logger.info("[CB] Circuit breaker recovered — sending refresh signal to SSE clients")
            try:
                await db.execute(
                    "SELECT pg_notify('new_message', $1)",
                    json.dumps({"event": "refresh", "payload": {"reason": "circuit_breaker_recovery"}}),
                )
            except Exception as e:
                logger.warning("[CB] Failed to send recovery refresh: %s", e)

    async def _broadcast(self, event: str, payload: dict) -> None:
        """Send a Postgres NOTIFY for SSE fan-out by the API process.

        The API process listens on the 'new_message' channel via SSEManager
        and fans out events to connected EventSource clients by group_id.

        Replaces the previous Supabase Realtime HTTP broadcast approach.
        Postgres NOTIFY payload limit is 8000 bytes — typical messages are
        ~500-1500 bytes, well within the limit.
        """
        notification = json.dumps({"event": event, "payload": payload}, default=str)
        # Truncate content if notification exceeds Postgres NOTIFY limit (8000 bytes)
        if len(notification) > 7900:
            payload = payload.copy()
            content = payload.get("content", "")
            if content and len(content) > 200:
                payload["content"] = content[:200] + "..."
            notification = json.dumps({"event": event, "payload": payload}, default=str)

        last_err = None
        for attempt in range(3):
            try:
                await db.execute("SELECT pg_notify('new_message', $1)", notification)
                return
            except Exception as e:
                last_err = e
                if attempt < 2:
                    await asyncio.sleep(0.5)
        logger.error(
            "NOTIFY failed after 3 attempts for event=%s group=%s msg=%s: %s",
            event, payload.get("group_id"), payload.get("telegram_message_id"), last_err,
        )

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
                import sentry_sdk
                if sentry_sdk.is_initialized():
                    sentry_sdk.capture_message(
                        f"Dead letter DB write failed, using file fallback: {e}",
                        level="warning",
                    )
            except Exception:
                pass
            try:
                # Use persistent path (not /tmp which may be private-namespaced by systemd)
                dl_path = Path(__file__).resolve().parent.parent / "dead-letters.jsonl"
                if dl_path.exists() and dl_path.stat().st_size > self._DEAD_LETTER_FILE_MAX_BYTES:
                    logger.error("Dead letter file exceeds %d MB — DROPPING message", self._DEAD_LETTER_FILE_MAX_BYTES // (1024 * 1024))
                    try:
                        import sentry_sdk
                        if sentry_sdk.is_initialized():
                            sentry_sdk.capture_message(
                                "Dead letter file full — messages being DROPPED",
                                level="error",
                            )
                    except Exception:
                        pass
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
            self._circuit_breaker_was_open = True
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
            # Deduplicate within batch by (telegram_message_id, group_id)
            # to prevent broadcasting the same message multiple times
            seen_keys: set[tuple] = set()
            unique_inserts = []
            for item in inserts:
                key = (item["data"].get("telegram_message_id"), item["data"].get("group_id"))
                if key not in seen_keys:
                    seen_keys.add(key)
                    unique_inserts.append(item)
            if len(unique_inserts) < len(inserts):
                logger.info("[BATCH] Deduplicated %d → %d inserts", len(inserts), len(unique_inserts))
            inserts = unique_inserts

            rows = [item["data"] for item in inserts]
            persisted_items = inserts  # assume all persisted unless batch fails
            try:
                await self._db_upsert_batch(rows, True)
                self._circuit_breaker.record_success()
                await self._check_cb_recovery()
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

                # Enqueue for AI classification
                await self._ai_classifier.enqueue({
                    "id": item["data"].get("id"),
                    "text": item["data"].get("text"),
                    "media_type": item["data"].get("media_type"),
                    "group_id": item["data"].get("group_id"),
                })

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

    # Static helpers delegated to app.crawler.utils
    _detect_media_type = staticmethod(detect_media_type)
    _select_photo_size = staticmethod(select_photo_size)

    @staticmethod
    def _extract_forum_topic_id(message) -> int | None:
        """Extract forum topic ID from a Telethon message object.

        Forum topics use the reply_to_top_id field. Returns None if:
        - Message has no reply_to info
        - Not a forum topic message (forum_topic flag is False)
        - reply_to_top_id is missing (may be root message)

        Args:
            message: Telethon Message object

        Returns:
            Topic ID (int) or None
        """
        if not hasattr(message, "reply_to") or not message.reply_to:
            return None

        if not hasattr(message.reply_to, "forum_topic") or not message.reply_to.forum_topic:
            return None

        topic_id = getattr(message.reply_to, "reply_to_top_id", None)

        # Log edge case for diagnostics
        if topic_id is None:
            logger.debug(
                "Forum topic message with no reply_to_top_id: msg_id=%s, group=%s",
                message.id, getattr(message, "peer_id", "unknown")
            )

        return topic_id

    async def _enqueue_message(
        self,
        message,
        group_telegram_id: int,
        group_uuid: str,
        is_edit: bool = False,
        download_media: bool = False,
        client: TelegramClient | None = None,
        broadcast: bool = True,
        message_source: str = "realtime",
    ) -> None:
        """Prepare message data and put it on the queue for the DB writer."""
        try:
            # --- Dedup guard: skip if same message was recently enqueued ---
            # This prevents duplicates when multiple admin clients receive
            # the same Telegram event for a shared group.
            dedup_key = (message.id, int(group_uuid))
            now_mono = time.monotonic()
            if not is_edit and dedup_key in self._enqueue_dedup:
                logger.debug("Dedup: skipping duplicate enqueue for msg %d in group %s", message.id, group_uuid)
                return
            if not is_edit:
                self._enqueue_dedup[dedup_key] = now_mono
                # Cleanup: size-based (>500) OR time-based (every 5 min)
                should_cleanup = (
                    len(self._enqueue_dedup) > 500
                    or (now_mono - self._enqueue_dedup_last_cleanup > 300)
                )
                if should_cleanup:
                    cutoff = now_mono - 60
                    self._enqueue_dedup = {
                        k: v for k, v in self._enqueue_dedup.items() if v > cutoff
                    }
                    self._enqueue_dedup_last_cleanup = now_mono
            media_type = self._detect_media_type(message)
            media_url = None

            # Phase 34: Extract entity metadata (links, mentions, photo albums)
            links = MessageEntityParser.extract_links(message)
            mentions = MessageEntityParser.extract_mentions(message)
            photo_count = MessageEntityParser.get_photo_count(message)

            # Phase 34: Only download photos (not videos/documents/stickers)
            if download_media and media_type == "photo" and client:
                media_url, _ = await self._upload_media(message, group_uuid, media_type, client)

            sender_id = message.sender_id
            sender_name = None
            if message.sender:
                sender_name = getattr(message.sender, "first_name", None)
                if hasattr(message.sender, "last_name") and message.sender.last_name:
                    sender_name = f"{sender_name} {message.sender.last_name}"

            topic_id = self._extract_forum_topic_id(message)

            # Ensure sent_at is timezone-aware (Telethon may return naive datetime)
            sent_at = message.date
            if sent_at and not sent_at.tzinfo:
                sent_at = sent_at.replace(tzinfo=timezone.utc)

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
                "sent_at": sent_at,
                "message_source": message_source,
                "created_at": datetime.now(timezone.utc),
                "links": links,  # Phase 34: JSONB array of link objects
                "mentions": mentions,  # Phase 34: JSONB array of mention objects
                "photo_count": photo_count,  # Phase 34: INTEGER count for photo albums
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

            # Phase 3: Discover and enqueue external references (URLs, t.me links)
            if message_data.get("content"):
                await self._reference_discovery.discover_and_enqueue(
                    str(message_data["telegram_message_id"]),
                    message_data["content"]
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

    async def _auto_register_admin_groups(self) -> None:
        """Auto-register all groups that admin accounts are members of.

        Called on crawler start — ensures any new groups the admin has joined
        since last restart are automatically picked up for crawling.
        """
        from telethon.tl.types import Channel, Chat

        registered = 0
        for admin_id, client in self.clients.items():
            try:
                dialogs = await asyncio.wait_for(client.get_dialogs(), timeout=30)
                for d in dialogs:
                    entity = d.entity
                    if not isinstance(entity, (Channel, Chat)):
                        continue

                    gid = entity.id
                    name = d.title or "Unknown"
                    is_channel = getattr(entity, "broadcast", False)
                    username = getattr(entity, "username", None)
                    visibility = "public" if username else "private"
                    gtype = "channel" if is_channel else "supergroup"
                    members = getattr(entity, "participants_count", None)
                    has_topics = getattr(entity, "forum", False)  # NEW: Extract forum flag

                    await db.execute(
                        """INSERT INTO groups (id, name, username, visibility, type, member_count, has_topics, crawl_enabled, registered_by)
                           VALUES ($1, $2, $3, $4, $5, $6, $7, true, $8)
                           ON CONFLICT (id) DO UPDATE SET name=$2, username=$3, member_count=$6, has_topics=$7, updated_at=NOW()""",
                        gid, name, username, visibility, gtype, members, has_topics, admin_id,
                    )
                    await db.execute(
                        "INSERT INTO user_groups (user_id, group_id) VALUES ($1, $2) ON CONFLICT (user_id, group_id) DO NOTHING",
                        admin_id, gid,
                    )
                    registered += 1

                logger.info("Auto-registered %d groups for admin %s", registered, admin_id)
            except asyncio.TimeoutError:
                logger.warning("Auto-register: get_dialogs timed out for admin %s", admin_id)
            except Exception as e:
                logger.warning("Auto-register failed for admin %s: %s", admin_id, e)

    # Forum topic constants
    FORUM_TOPICS_TIMEOUT = 10.0  # Timeout for GetForumTopicsRequest
    FORUM_TOPICS_LIMIT = 100  # Max topics per request (Telethon limit)

    async def _fetch_and_store_topics(self, group_id: int, client: TelegramClient) -> None:
        """
        Fetch forum topics from Telegram and store in group_topics table.

        Only called for groups where has_topics=True.

        Flow:
        1. Resolve entity
        2. Verify it's a forum
        3. Fetch topics from Telegram API
        4. Convert to DB format
        5. Batch upsert to DB
        """
        try:
            entity = await self._get_entity_for_group_with_client(group_id, client)
            if not entity:
                logger.warning("Cannot fetch topics for group %s: entity not found", group_id)
                return

            if not getattr(entity, 'forum', False):
                logger.debug("Group %s is not a forum, skipping topic fetch", group_id)
                return

            topics_data = await self._fetch_topics_from_telegram(group_id, entity, client)
            if not topics_data:
                return

            await self._batch_upsert_topics(group_id, topics_data)

        except Exception as e:
            logger.error("Failed to fetch topics for group %s: %s", group_id, e, exc_info=True)

    async def _fetch_topics_from_telegram(self, group_id: int, entity, client: TelegramClient) -> list:
        """Fetch forum topics from Telegram API.

        Returns:
            List of topic data dicts, or empty list if no topics found or error.
        """
        from telethon.tl.functions.channels import GetForumTopicsRequest

        try:
            result = await asyncio.wait_for(
                client(GetForumTopicsRequest(
                    channel=entity,
                    offset_date=0,
                    offset_id=0,
                    offset_topic=0,
                    limit=self.FORUM_TOPICS_LIMIT,
                    q=''
                )),
                timeout=self.FORUM_TOPICS_TIMEOUT
            )
        except asyncio.TimeoutError:
            logger.warning("Timeout fetching topics for group %s (timeout=%fs)", group_id, self.FORUM_TOPICS_TIMEOUT)
            return []

        if not result or not result.topics:
            logger.debug("No topics found for group %s", group_id)
            return []

        return self._convert_telethon_topics_to_db_format(group_id, result.topics)

    @staticmethod
    def _convert_telethon_topics_to_db_format(group_id: int, topics: list) -> list:
        """Convert Telethon ForumTopic objects to database-ready dicts.

        Args:
            group_id: Telegram group ID
            topics: List of Telethon ForumTopic objects

        Returns:
            List of dicts ready for database upsert
        """
        topics_data = []
        for topic in topics:
            topics_data.append({
                'group_id': group_id,
                'topic_id': topic.id,
                'topic_title': topic.title,
                'icon_color': topic.icon_color,
                'icon_emoji_id': getattr(topic, 'icon_emoji_id', None),
                'is_closed': getattr(topic, 'closed', False),
                'is_pinned': getattr(topic, 'pinned', False),
                'top_message_id': topic.top_message,
                'unread_count': topic.unread_count,
            })
        return topics_data

    async def _batch_upsert_topics(self, group_id: int, topics_data: list) -> None:
        """Batch upsert topics to database.

        Uses a single multi-row INSERT with ON CONFLICT for efficiency.

        Args:
            group_id: Telegram group ID (for logging)
            topics_data: List of topic dicts to upsert
        """
        if not topics_data:
            return

        # Build VALUES clause for batch insert
        placeholders = []
        params = []
        for i, topic in enumerate(topics_data):
            base_idx = i * 9  # 9 columns per row
            placeholders.append(
                f"(${base_idx+1}, ${base_idx+2}, ${base_idx+3}, ${base_idx+4}, "
                f"${base_idx+5}, ${base_idx+6}, ${base_idx+7}, ${base_idx+8}, ${base_idx+9})"
            )
            params.extend([
                topic['group_id'],
                topic['topic_id'],
                topic['topic_title'],
                topic['icon_color'],
                topic['icon_emoji_id'],
                topic['is_closed'],
                topic['is_pinned'],
                topic['top_message_id'],
                topic['unread_count'],
            ])

        query = f"""
            INSERT INTO group_topics
            (group_id, topic_id, topic_title, icon_color, icon_emoji_id,
             is_closed, is_pinned, top_message_id, unread_count)
            VALUES {', '.join(placeholders)}
            ON CONFLICT (group_id, topic_id)
            DO UPDATE SET
                topic_title = EXCLUDED.topic_title,
                icon_color = EXCLUDED.icon_color,
                icon_emoji_id = EXCLUDED.icon_emoji_id,
                is_closed = EXCLUDED.is_closed,
                is_pinned = EXCLUDED.is_pinned,
                top_message_id = EXCLUDED.top_message_id,
                unread_count = EXCLUDED.unread_count,
                updated_at = NOW()
        """

        try:
            await db.execute(query, *params)
            logger.info("Upserted %d topics for group %s", len(topics_data), group_id)
        except Exception as e:
            logger.error("Failed to upsert %d topics for group %s: %s", len(topics_data), group_id, e)

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
                # Phase 2: Load connection mapping for new groups
                await self._reload_group_connection_mappings_for_groups(new_ids)

            logger.info("Live crawler: %d groups loaded", len(self.group_id_map))
        except Exception as e:
            logger.error("Live crawler: failed to refresh groups: %s", e)

    async def discover_group_accessibility(self) -> None:
        """Discover which groups each Telegram connection can access.

        Called during startup to populate connection_accessible_groups table.
        This data is used by backfill_connection_ids() to auto-assign groups
        to correct connections for multi-connection admins.

        Algorithm:
        1. For each admin client, call get_dialogs() to list accessible groups
        2. Store (connection_id, group_id) mappings in DB
        3. Clear old entries (stale discoveries are removed)
        """
        if not self.clients:
            logger.debug("discover_group_accessibility: no clients connected")
            return

        try:
            logger.info("discover_group_accessibility: starting for %d connections", len(self.clients))

            # Get all admin's connections
            admin_ids = list(self.clients.keys())
            connections = await db.fetch(
                "SELECT id, user_id FROM telegram_connections WHERE user_id = ANY($1::bigint[])",
                admin_ids,
            )

            if not connections:
                logger.debug("discover_group_accessibility: no telegram_connections found")
                return

            # Build map: user_id -> [connection_ids]
            user_connections: dict[int, list[str]] = {}
            for conn in connections:
                user_id = conn["user_id"]
                conn_id = str(conn["id"])
                if user_id not in user_connections:
                    user_connections[user_id] = []
                user_connections[user_id].append(conn_id)

            # For each admin (user_id -> client)
            for user_id, client in self.clients.items():
                try:
                    # Get this admin's connections
                    admin_conn_ids = user_connections.get(user_id, [])
                    if not admin_conn_ids:
                        logger.debug("discover_group_accessibility: user %s has no connections", user_id)
                        continue

                    # Get this client's accessible groups via get_dialogs()
                    try:
                        dialogs = await asyncio.wait_for(
                            client.get_dialogs(limit=None),
                            timeout=30.0
                        )
                    except asyncio.TimeoutError:
                        logger.warning("discover_group_accessibility: get_dialogs() timed out for user %s", user_id)
                        continue

                    if not dialogs:
                        logger.debug("discover_group_accessibility: user %s has no dialogs", user_id)
                        continue

                    # Extract group IDs from dialogs
                    discovered_group_ids: set[int] = set()
                    for dialog in dialogs:
                        try:
                            entity = dialog.entity
                            if not entity:
                                continue
                            # Get the entity's ID (works for Chat, Channel, User)
                            if hasattr(entity, 'id'):
                                gid = int(entity.id)
                                discovered_group_ids.add(gid)
                        except Exception as e:
                            logger.debug("discover_group_accessibility: failed to extract group ID: %s", e)
                            continue

                    if not discovered_group_ids:
                        logger.debug("discover_group_accessibility: no group IDs found for user %s", user_id)
                        continue

                    logger.info(
                        "discover_group_accessibility: user %s can access %d groups",
                        user_id, len(discovered_group_ids)
                    )

                    # Store mappings: connection_id -> group_id
                    # For multi-connection admins, assign to first available connection
                    # (refined backfill will choose more precisely)
                    primary_conn_id = admin_conn_ids[0]

                    for group_id in discovered_group_ids:
                        try:
                            await db.execute(
                                """INSERT INTO connection_accessible_groups (connection_id, group_id)
                                   VALUES ($1, $2)
                                   ON CONFLICT (connection_id, group_id) DO UPDATE
                                   SET discovered_at = NOW()""",
                                primary_conn_id, group_id
                            )
                        except Exception as e:
                            logger.debug("discover_group_accessibility: failed to store mapping %s/%s: %s",
                                       primary_conn_id, group_id, e)
                            continue

                    logger.info(
                        "discover_group_accessibility: stored %d accessible groups for user %s",
                        len(discovered_group_ids), user_id
                    )

                except Exception as e:
                    logger.warning("discover_group_accessibility failed for user %s: %s", user_id, e)
                    continue

            logger.info("discover_group_accessibility: completed")

        except Exception as e:
            logger.error("discover_group_accessibility: unexpected error: %s", e)

    async def _load_connection_group_mappings(self) -> None:
        """Load connection-group mappings for duplicate prevention.

        Phase 2: Ensures each group is only listened by its assigned connection.

        Maps:
        - telegram_user_id → connection_id (identifies which connection each client is)
        - group_id → connection_id (identifies which connection should handle each group)

        Called at startup, and can be refreshed via admin API.
        """
        try:
            logger.info("_load_connection_group_mappings: building maps")

            # Step 1: Map telegram_user_id -> connection_id
            # For each client, fetch its telegram_user_id and load connections
            for user_id, client in self.clients.items():
                try:
                    me = await client.get_me()
                    if not me or not me.id:
                        logger.warning("_load_connection_group_mappings: get_me() failed for user %s", user_id)
                        continue

                    telegram_user_id = int(me.id)
                    # Load all this user's connections
                    connections = await db.fetch(
                        """SELECT id, telegram_user_id FROM telegram_connections
                           WHERE user_id = $1""",
                        user_id
                    )

                    for conn in connections:
                        conn_id = str(conn["id"])
                        conn_telegram_user_id = int(conn["telegram_user_id"])
                        self._telegram_user_id_to_connection_id[conn_telegram_user_id] = conn_id
                        logger.debug(
                            "_load_connection_group_mappings: mapped telegram_user_id %s -> connection %s",
                            conn_telegram_user_id, conn_id[:8] + "..."
                        )

                except Exception as e:
                    logger.warning("_load_connection_group_mappings: failed to map user %s: %s", user_id, e)
                    continue

            # Step 2: Map group_id -> connection_id
            # Load which connection is assigned to each group (from user_groups)
            # For multi-connection admins, a group may have NULL or have a connection_id
            try:
                group_mappings = await db.fetch(
                    """SELECT DISTINCT group_id, connection_id
                       FROM user_groups
                       WHERE connection_id IS NOT NULL
                       ORDER BY group_id"""
                )

                for row in group_mappings:
                    gid = int(row["group_id"])
                    conn_id = str(row["connection_id"])
                    # If group already mapped to different connection, use the first one
                    if gid not in self._group_to_connection_id:
                        self._group_to_connection_id[gid] = conn_id
                        logger.debug(
                            "_load_connection_group_mappings: mapped group %s -> connection %s",
                            gid, conn_id[:8] + "..."
                        )

                logger.info(
                    "_load_connection_group_mappings: completed. %d telegram_user_ids mapped, %d groups mapped",
                    len(self._telegram_user_id_to_connection_id),
                    len(self._group_to_connection_id)
                )

            except Exception as e:
                logger.warning("_load_connection_group_mappings: failed to load group mappings: %s", e)

        except Exception as e:
            logger.error("_load_connection_group_mappings: unexpected error: %s", e)

    async def _reload_group_connection_mappings_for_groups(self, group_ids: set[int]) -> None:
        """Reload connection mapping for specific groups (after group refresh detects new groups).

        Called when new groups are detected via refresh_groups().
        Ensures newly enabled groups get their connection assignment loaded.
        """
        if not group_ids:
            return

        try:
            # Load which connection is assigned to each of these groups
            group_mappings = await db.fetch(
                """SELECT DISTINCT group_id, connection_id
                   FROM user_groups
                   WHERE group_id = ANY($1::bigint[]) AND connection_id IS NOT NULL
                   ORDER BY group_id""",
                list(group_ids)
            )

            for row in group_mappings:
                gid = int(row["group_id"])
                conn_id = str(row["connection_id"])
                if gid not in self._group_to_connection_id:
                    self._group_to_connection_id[gid] = conn_id
                    logger.debug(
                        "_reload_group_connection_mappings_for_groups: loaded mapping group %s -> connection %s",
                        gid, conn_id[:8] + "..."
                    )

            logger.info(
                "_reload_group_connection_mappings_for_groups: loaded %d group mappings",
                len(group_mappings)
            )

        except Exception as e:
            logger.warning("_reload_group_connection_mappings_for_groups error: %s", e)

    async def _should_handle_group(self, group_id: int, client: TelegramClient, user_id: int | None = None) -> bool:
        """Check if this client should handle events from this group.

        Phase 2: Duplicate prevention with Phase 2A error recovery.

        Rules:
        1. If group has no assigned connection: all clients handle (backward compatible)
        2. If group has assigned connection: only that connection handles
        3. Uses cached telegram_user_id to minimize get_me() calls (5-min TTL)
        4. Implements retry logic (up to 3 attempts) for transient failures
        5. Implements circuit breaker for repeated failures (backoff: 30s→60s→120s)
        6. Alerts Sentry on persistent failures

        Returns:
        - True: this client should handle events
        - False: another client is assigned, skip events
        """
        try:
            # Check if this group has an assigned connection
            assigned_conn_id = self._group_to_connection_id.get(group_id)

            if assigned_conn_id is None:
                # No assignment yet, all connections can handle (backward compatible)
                return True

            # Get this client's telegram_user_id with error recovery (caching, retries, circuit breaker)
            my_telegram_user_id = await self._error_recovery.get_telegram_user_id_with_retry(client, user_id)
            if my_telegram_user_id is None:
                logger.warning(
                    "_should_handle_group: failed to get telegram_user_id for group %s after retries (fail open)",
                    group_id
                )
                return True  # Fail open: handle to avoid losing messages

            # Find this client's connection_id
            my_conn_id = self._telegram_user_id_to_connection_id.get(my_telegram_user_id)

            if my_conn_id is None:
                logger.debug(
                    "_should_handle_group: client telegram_user_id %s not in connection map for group %s",
                    my_telegram_user_id, group_id
                )
                return False

            # Check if this client's connection matches the assigned connection
            should_handle = my_conn_id == assigned_conn_id

            if not should_handle:
                logger.debug(
                    "_should_handle_group: group %s assigned to connection %s, but this client is %s (skip)",
                    group_id, assigned_conn_id[:8] + "...", my_conn_id[:8] + "..."
                )

            return should_handle

        except Exception as e:
            logger.error("_should_handle_group: unexpected error for group %s: %s", group_id, e)
            return True  # Default: handle (fail open)


    def _get_group_title(self, gid: int) -> str:
        info = self.group_info_map.get(gid, {})
        return info.get("title") or info.get("name") or str(gid)

    # _normalize_chat_id imported from app.crawler.utils
    _normalize_chat_id = staticmethod(normalize_chat_id)

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
                    entity = await asyncio.wait_for(
                        client.get_entity(InputPeerChannel(channel_id=gid, access_hash=access_hash)),
                        timeout=10,
                    )
                else:
                    entity = await asyncio.wait_for(
                        client.get_entity(InputPeerChat(chat_id=gid)),
                        timeout=10,
                    )
                return entity
            except asyncio.TimeoutError:
                logger.debug("Cached entity resolution timeout for %s", gid)
            except Exception:
                # Stale cache entry — remove from memory AND DB
                self._entity_cache.pop(gid, None)
                try:
                    await db.execute("DELETE FROM entity_cache WHERE telegram_id = $1", gid)
                except Exception:
                    pass

        # 2) Direct resolution attempts (with timeout to prevent hanging)
        for peer_cls in (PeerChannel, PeerChat):
            try:
                kwarg = "channel_id" if peer_cls is PeerChannel else "chat_id"
                entity = await asyncio.wait_for(
                    client.get_entity(peer_cls(**{kwarg: gid})),
                    timeout=10,
                )
                self._cache_entity(entity)
                return entity
            except asyncio.TimeoutError:
                logger.debug("Entity resolution timeout for %s via %s", gid, peer_cls.__name__)
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
            dialogs = await asyncio.wait_for(client.get_dialogs(), timeout=15)
            target_entity = None
            for dialog in dialogs:
                entity = dialog.entity
                if isinstance(entity, (Channel, Chat)):
                    self._cache_entity(entity)
                if entity.id == gid:
                    target_entity = entity

            if target_entity:
                return target_entity

        # 4) Final retry after cache warm (with timeout)
        try:
            entity = await asyncio.wait_for(
                client.get_entity(PeerChannel(channel_id=gid)),
                timeout=10,
            )
            self._cache_entity(entity)
            return entity
        except asyncio.TimeoutError:
            logger.debug("PeerChannel(%s) final retry timed out", gid)
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
        """Every 30 minutes, re-fetch recent messages per group.

        Uses dynamic lookback: normally 1 hour, but if the last gap-fill was
        more than GAP_FILL_LOOKBACK_HOURS ago (e.g. after a long outage or
        restart), it looks back to the gap-fill interval or 24 hours max.

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

            # Dynamic lookback: if last gap-fill was long ago (restart/outage), look back further
            now_mono = time.monotonic()
            if self._last_gap_fill_at > 0:
                hours_since_last = (now_mono - self._last_gap_fill_at) / 3600
                lookback_hours = min(max(hours_since_last + 0.5, GAP_FILL_LOOKBACK_HOURS), 24)
            else:
                lookback_hours = GAP_FILL_LOOKBACK_HOURS

            logger.info("[GAP-FILL] Starting gap-fill re-check (%d groups, lookback=%.1fh)...",
                        len(self.group_id_map), lookback_hours)
            filled = 0
            skipped_flood = 0
            now = time.monotonic()
            # Cleanup expired FloodWait penalties (prevents unbounded dict growth)
            expired_penalties = [gid for gid, until in self._flood_wait_until.items() if now >= until]
            for gid in expired_penalties:
                del self._flood_wait_until[gid]
            if expired_penalties:
                logger.debug("[GAP-FILL] Cleaned up %d expired FloodWait penalties", len(expired_penalties))

            # Phase 2A: Cleanup get_me() cache and circuit breaker state
            await self._error_recovery.cleanup()

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

                    lookback = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
                    count = 0
                    iterated = 0
                    async for message in working_client.iter_messages(entity, offset_date=lookback, reverse=True):
                        if not self.running:
                            break
                        iterated += 1
                        if message.text or message.media:
                            await self._enqueue_message(
                                message, gid, group_uuid,
                                download_media=True, client=working_client,
                                broadcast=False, message_source="gap_fill",
                            )
                            count += 1
                        if count >= GAP_FILL_MAX_MESSAGES:
                            break
                        if iterated % 200 == 0:
                            await asyncio.sleep(1.5)
                    filled += count

                    # Track successful gap-fill for SLA monitoring
                    self._gap_fill_metrics.record_gap_fill_success(gid, count)

                except FloodWaitError as e:
                    logger.warning("[GAP-FILL] FloodWait %ds for group %s — skipping, will retry after penalty", e.seconds, gid)
                    self._flood_wait_until[gid] = time.monotonic() + e.seconds
                    # Track gap-fill failure for SLA monitoring
                    self._gap_fill_metrics.record_gap_fill_failure(gid, f"FloodWait_{e.seconds}s")
                except Exception as e:
                    logger.debug("[GAP-FILL] Error for group %s: %s", gid, e)

                # Inter-group delay to avoid rapid successive API calls
                await asyncio.sleep(2.0)

            self._last_gap_fill_at = time.monotonic()
            if skipped_flood:
                logger.info("[GAP-FILL] Skipped %d groups with active FloodWait penalties", skipped_flood)
            logger.info("[GAP-FILL] Complete — %d messages re-enqueued (lookback=%.1fh, duplicates ignored via ON CONFLICT)",
                        filled, lookback_hours)

    # ------------------------------------------------------------------
    # Historical crawl (14-day backfill)
    # ------------------------------------------------------------------

    async def _crawl_all_groups_historical(self) -> None:
        """Crawl historical messages for all groups that need it.

        Two passes:
        1. Initial pass: crawl all groups, skip FloodWait-penalized ones
        2. Retry loop: wait for penalties to expire, retry skipped groups (30min deadline)
        """
        self._historical_crawl_running = True
        try:
            all_gids = list(self.group_id_map.keys())

            # --- Pass 1: crawl everything we can ---
            for gid in all_gids:
                if not self.running:
                    break
                if gid in self._crawled_groups:
                    continue
                if time.monotonic() < self._flood_wait_until.get(gid, 0):
                    logger.info("Skipping historical crawl for group %s — FloodWait penalty active", gid)
                    continue
                group_uuid = self.group_id_map[gid]
                # Directly proceed to crawl (no 50-message check)
                # Crawler handles duplicates via ON CONFLICT DO NOTHING
                await self._crawl_historical_for_group(gid)

            # --- Pass 2: retry FloodWait-skipped groups ---
            retry_deadline = time.monotonic() + 7200  # 2 hours max (covers extended FloodWait penalties)
            while self.running:
                pending_gids = [
                    gid for gid in all_gids
                    if gid not in self._crawled_groups and gid in self.group_id_map
                ]
                if not pending_gids:
                    break
                if time.monotonic() > retry_deadline:
                    logger.warning("Historical crawl retry deadline reached — %d groups still pending", len(pending_gids))
                    for gid in pending_gids:
                        group_uuid = self.group_id_map.get(gid)
                        if group_uuid:
                            await self._update_crawler_status(
                                group_uuid, "error",
                                error="Historical crawl skipped: FloodWait retry deadline exceeded",
                            )
                    break

                # Find earliest penalty expiry among pending groups
                earliest_expiry = min(
                    (self._flood_wait_until.get(gid, 0) for gid in pending_gids),
                    default=0,
                )
                wait_time = max(0, earliest_expiry - time.monotonic())
                if wait_time > 0:
                    logger.info(
                        "Waiting %.0fs for FloodWait penalties to expire (%d groups pending)",
                        wait_time, len(pending_gids),
                    )
                    await asyncio.sleep(min(wait_time + 1, 60))  # Sleep in 60s chunks max

                retried_any = False
                for gid in pending_gids:
                    if not self.running:
                        break
                    if gid in self._crawled_groups:
                        continue
                    if time.monotonic() < self._flood_wait_until.get(gid, 0):
                        continue
                    await self._crawl_historical_for_group(gid)
                    retried_any = True

                if not retried_any:
                    # All still penalized — sleep and retry
                    await asyncio.sleep(30)

        except Exception as e:
            logger.error("Historical crawl error: %s", e)
        finally:
            self._historical_crawl_running = False

    async def _crawl_historical_for_group(self, gid: int) -> None:
        """Crawl last 14 days of messages for a single group.

        Tries each admin client until one succeeds. Messages are enqueued
        for the DB writer coroutine which handles batching.

        Concurrent crawl prevention: if another task is already crawling this
        group (e.g. startup crawl vs batch crawl), this call returns immediately.
        """
        group_uuid = self.group_id_map.get(gid)
        if not group_uuid:
            return

        # Prevent concurrent crawl of the same group
        if gid in self._crawling_groups_lock:
            logger.info("Skipping historical crawl for group %s — already being crawled by another task", gid)
            return
        self._crawling_groups_lock.add(gid)

        # Check is_enabled flag (admin can disable crawling for a group)
        try:
            if not await self._is_group_enabled(group_uuid):
                logger.info("Skipping historical crawl for group %s — crawling is disabled", gid)
                self._crawling_groups_lock.discard(gid)
                return
        except Exception:
            pass

        title = self._get_group_title(gid)
        logger.info("=" * 50)
        logger.info("Historical crawl starting: %s (id=%s)", title, gid)
        logger.info("=" * 50)

        self._currently_crawling_group_id = gid

        try:
            await self._update_crawler_status(group_uuid, "initializing", progress=0, total=0)

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

            # Estimate total message count from Telegram (limit=0 trick)
            estimated_total = 0
            try:
                total_result = await working_client.get_messages(group_entity, limit=0)
                estimated_total = getattr(total_result, 'total', 0) or 0
                logger.info("  [%s] Estimated total messages: %d", title, estimated_total)
            except Exception as e:
                logger.debug("  Could not estimate message count for %s: %s", title, e)

            await self._update_crawler_status(group_uuid, "initializing", progress=0, total=estimated_total)

            # NEW: Fetch topics if this is a forum group
            group_info = self.group_info_map.get(gid, {})
            if group_info.get('has_topics', False):
                try:
                    await self._fetch_and_store_topics(gid, working_client)
                except Exception as e:
                    logger.error("Failed to fetch topics for group %s: %s", title, e)

            date_threshold = datetime.now(timezone.utc) - timedelta(days=HISTORICAL_CRAWL_DAYS)

            enqueued_count = 0
            iterated_count = 0  # Count ALL messages (including empty) for accurate rate limiting
            media_pending: list[tuple] = []  # (message, media_type) — collected for batch download

            async def _do_historical_iteration():
                """Inner iteration — wrapped with timeout to prevent hanging."""
                nonlocal enqueued_count, iterated_count
                async for message in working_client.iter_messages(group_entity, offset_date=date_threshold, reverse=True):
                    if not self.running:
                        break
                    iterated_count += 1
                    try:
                        if message.text or message.media:
                            await self._enqueue_message(message, gid, group_uuid, client=working_client, broadcast=False, message_source="crawled")
                            enqueued_count += 1

                            # Collect media messages for parallel batch download after text ingestion
                            media_type = self._detect_media_type(message)
                            if media_type:
                                media_pending.append((message, media_type))

                            if enqueued_count % 100 == 0:
                                logger.info("  [%s] %d messages enqueued (%d with media)...", title, enqueued_count, len(media_pending))
                                await self._update_crawler_status(
                                    group_uuid, "initializing",
                                    progress=enqueued_count, total=estimated_total
                                )

                        # Rate limiting based on iterated count (not enqueued) to avoid
                        # bursts when many empty/system messages are skipped
                        if iterated_count % 200 == 0:
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

            # Per-group timeout: 10 minutes max to prevent one group blocking the batch
            try:
                await asyncio.wait_for(_do_historical_iteration(), timeout=600)
            except asyncio.TimeoutError:
                logger.warning("Historical crawl timeout (10min) for %s — %d messages enqueued so far", title, enqueued_count)
                await self._update_crawler_status(
                    group_uuid, "error",
                    progress=enqueued_count, total=estimated_total,
                    error="Historical crawl timeout (10min)"
                )
                # Do NOT add to _crawled_groups — allow retry via manual trigger
                return

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

            # --- Phase 2: Parallel media download for collected media messages ---
            media_downloaded = 0
            if drained and media_pending and self.running:
                logger.info("  [%s] Starting parallel media download: %d items (concurrency=%d)",
                            title, len(media_pending), MEDIA_CONCURRENCY)
                try:
                    media_downloaded = await asyncio.wait_for(
                        self._download_media_parallel(media_pending, group_uuid, working_client),
                        timeout=300,  # 5 min max for media downloads
                    )
                    logger.info("  [%s] Media download complete: %d/%d successful", title, media_downloaded, len(media_pending))
                except asyncio.TimeoutError:
                    logger.warning("  [%s] Media download timeout (5min) — %d items were pending", title, len(media_pending))
                except Exception as e:
                    logger.warning("  [%s] Media download error: %s", title, e)

            if drained:
                await self._update_crawler_status(
                    group_uuid, "active",
                    progress=enqueued_count, total=estimated_total
                )
            else:
                # Mark as error, not active — messages still processing in queue
                await self._update_crawler_status(
                    group_uuid, "error",
                    progress=enqueued_count, total=estimated_total,
                    error=f"Queue drain timeout ({QUEUE_DRAIN_TIMEOUT}s) — {self._msg_queue.qsize()} items pending"
                )
            self._crawled_groups.add(gid)
            await self._update_group_last_error(gid, None)
            logger.info("Historical crawl complete: %s — %d messages enqueued", title, enqueued_count)

        except (ChannelPrivateError, ChatAdminRequiredError) as e:
            logger.error("Access denied for %s: %s", title, e)
            await self._update_crawler_status(group_uuid, "error", error=str(e))
            await self._update_group_last_error(gid, str(e))
            await self._log_crawler_error(gid, "access_denied", str(e))
        except FloodWaitError as e:
            logger.warning("FloodWait for %s: %ds — recording penalty, moving to next group", title, e.seconds)
            await self._update_crawler_status(group_uuid, "error", error=f"FloodWait: {e.seconds}s")
            self._flood_wait_until[gid] = time.monotonic() + e.seconds
            await self._log_crawler_error(gid, "flood_wait", f"FloodWait: {e.seconds}s")
        except Exception as e:
            logger.error("Historical crawl failed for %s: %s", title, e)
            logger.error(traceback.format_exc())
            await self._update_crawler_status(group_uuid, "error", error=str(e))
            await self._update_group_last_error(gid, str(e))
            await self._log_crawler_error(gid, "crawl_error", str(e), traceback.format_exc())
        finally:
            # Release per-group crawl lock
            self._crawling_groups_lock.discard(gid)
            if self._currently_crawling_group_id == gid:
                self._currently_crawling_group_id = None
            # Safety net: if status is still "initializing", force it to "error"
            try:
                current_status = await db.fetchval(
                    "SELECT status FROM crawler_status WHERE group_id = $1", int(group_uuid)
                )
                if current_status == "initializing" and gid not in self._crawled_groups:
                    await self._update_crawler_status(
                        group_uuid, "error",
                        error="Crawl exited unexpectedly while initializing",
                    )
            except Exception:
                pass

    async def _update_crawler_status(
        self, group_uuid: str, status: str,
        error: str | None = None, progress: int | None = None, total: int | None = None
    ) -> None:
        """Update crawler_status row — fixed query with all columns to avoid dynamic SQL."""
        try:
            now = datetime.now(timezone.utc)
            # Determine field values based on status
            last_error = None if status == "initializing" else error
            last_message_at = now if status == "active" else None

            await db.execute(
                """UPDATE crawler_status SET
                    status = $1,
                    updated_at = $2,
                    last_error = CASE WHEN $3::boolean THEN $4 ELSE last_error END,
                    initial_crawl_progress = COALESCE($5, initial_crawl_progress),
                    initial_crawl_total = COALESCE($6, initial_crawl_total),
                    last_message_at = COALESCE($7, last_message_at)
                WHERE group_id = $8""",
                status, now,
                status == "initializing" or error is not None or last_error is not None,
                last_error,
                progress, total,
                last_message_at,
                int(group_uuid),
            )
        except Exception as e:
            logger.warning("Failed to update crawler_status for %s: %s", group_uuid, e)

    async def _update_group_last_error(self, gid: int, error: str | None) -> None:
        """Update groups.last_error so admin dashboard can show it. Pass None to clear."""
        try:
            await db.execute("UPDATE groups SET last_error = $1 WHERE id = $2", error or None, gid)
        except Exception as e:
            logger.warning("Failed to update groups.last_error for %s: %s", gid, e)

    async def _log_crawler_error(
        self, gid: int, error_type: str, error_message: str, details: str | None = None
    ) -> None:
        """Write an error entry to crawler_error_logs table (populates admin error dashboard)."""
        try:
            await db.execute(
                """INSERT INTO crawler_error_logs (group_id, error_type, error_message, error_details)
                   VALUES ($1, $2, $3, $4::jsonb)""",
                gid, error_type, error_message[:500],
                json.dumps({"traceback": details[:2000]}) if details else None,
            )
        except Exception as e:
            logger.debug("Failed to write crawler_error_log: %s", e)

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
                        # Phase 2B: Track skipped message (group not registered)
                        self._metrics.track_skipped(chat_id, "not_in_map")
                        return

                    # Phase 2: Duplicate prevention — only handle if this client is assigned
                    if not await self._should_handle_group(chat_id, _c, user_id):
                        # Phase 2B: Track skipped message (not assigned to this connection)
                        self._metrics.track_skipped(chat_id, "not_assigned")
                        return

                    group_uuid = self.group_id_map[chat_id]
                    group_title = self._get_group_title(chat_id)

                    if not await self._is_group_enabled(group_uuid):
                        # Phase 2B: Track skipped message (group disabled)
                        self._metrics.track_skipped(chat_id, "not_enabled")
                        return

                    # Phase 2B: Track handled message for metrics
                    self._metrics.track_handled(chat_id)

                    logger.info("[NEW] %s: %s", group_title, (event.text or "[media]")[:80])
                    await self._enqueue_message(
                        event.message, chat_id, group_uuid,
                        download_media=True, client=_c,
                    )
                    self._message_count += 1
                    self._last_event_received_at = time.monotonic()
                    await self._update_crawler_status(group_uuid, "active")
                except Exception as e:
                    logger.error("Live crawler new message error: %s", e)

            @_client.on(events.MessageEdited)
            async def on_message_edited(event, _c=_client):
                try:
                    chat_id = self._normalize_chat_id(event.chat_id)
                    if chat_id not in self.group_id_map:
                        # Phase 2B: Track skipped message (group not registered)
                        self._metrics.track_skipped(chat_id, "not_in_map")
                        return

                    # Phase 2: Duplicate prevention — only handle if this client is assigned
                    if not await self._should_handle_group(chat_id, _c, user_id):
                        # Phase 2B: Track skipped message (not assigned to this connection)
                        self._metrics.track_skipped(chat_id, "not_assigned")
                        return

                    # Phase 2B: Track handled message for metrics
                    self._metrics.track_handled(chat_id)

                    group_uuid = self.group_id_map[chat_id]
                    logger.info("[EDIT] %s: msg %d", self._get_group_title(chat_id), event.message.id)
                    await self._enqueue_message(
                        event.message, chat_id, group_uuid,
                        is_edit=True, client=_c,
                    )
                except Exception as e:
                    logger.error("Live crawler edit error: %s", e)

            @_client.on(events.MessageDeleted)
            async def on_message_deleted(event, _c=_client):
                try:
                    chat_id = self._normalize_chat_id(event.chat_id)
                    if chat_id not in self.group_id_map:
                        # Phase 2B: Track skipped message (group not registered)
                        self._metrics.track_skipped(chat_id, "not_in_map")
                        return

                    # Phase 2: Duplicate prevention — only handle if this client is assigned
                    if not await self._should_handle_group(chat_id, _c, user_id):
                        # Phase 2B: Track skipped message (not assigned to this connection)
                        self._metrics.track_skipped(chat_id, "not_assigned")
                        return

                    # Phase 2B: Track handled messages (counting each deleted ID)
                    for _ in event.deleted_ids:
                        self._metrics.track_handled(chat_id)

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
            async def on_chat_action(event, _c=_client):
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
                        # Phase 2B: Track skipped message (group not registered)
                        self._metrics.track_skipped(old_id, "not_in_map")
                        return

                    # Phase 2: Duplicate prevention — only handle if this client is assigned
                    if not await self._should_handle_group(old_id, _c, user_id):
                        # Phase 2B: Track skipped message (not assigned to this connection)
                        self._metrics.track_skipped(old_id, "not_assigned")
                        return

                    # Phase 2B: Track handled message (migration event)
                    self._metrics.track_handled(old_id)

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
    # Auto-join unmapped groups — background task
    # ------------------------------------------------------------------

    async def _periodic_auto_join_groups(self) -> None:
        """Periodically find unmapped groups and auto-join them with admin accounts.

        Checks every 30 minutes for new groups that:
        1. Are registered in the database
        2. But not yet accessible by any admin account (not in crawler_status active/initializing)

        When found, joins them using available admin clients and initiates historical crawl.
        """
        # Wait a bit before first attempt (let crawler stabilize)
        await asyncio.sleep(5 * 60)  # 5 minutes

        while self.running:
            try:
                now = time.monotonic()

                # Check if enough time has passed since last attempt
                if now - self._last_auto_join_at < 30 * 60:  # 30 minutes
                    await asyncio.sleep(60)  # Check again in 1 minute
                    continue

                # Skip if no clients available
                if not self.clients:
                    logger.debug("No admin clients available, skipping auto-join")
                    await asyncio.sleep(5 * 60)
                    continue

                # Find unmapped groups
                unmapped = await db.fetch(
                    """SELECT g.id, g.name, g.invite_link, g.username
                       FROM groups g
                       WHERE NOT EXISTS (
                           SELECT 1 FROM crawler_status cs
                           WHERE cs.group_id = g.id
                           AND cs.status IN ('active', 'initializing')
                       )
                       ORDER BY g.created_at ASC
                       LIMIT 20"""
                )

                if not unmapped:
                    logger.debug("No unmapped groups found")
                    self._last_auto_join_at = now
                    await asyncio.sleep(5 * 60)
                    continue

                logger.info(f"Found {len(unmapped)} unmapped groups, auto-joining with admin accounts...")
                joined_count = 0

                for group in unmapped:
                    if not self.running:
                        break

                    gid = group["id"]
                    gname = group["name"]
                    invite_link = group["invite_link"]
                    username = group["username"]

                    try:
                        # Try to join with one of the admin clients
                        joined = False
                        for admin_id, client in list(self.clients.items()):
                            try:
                                if not client.is_connected():
                                    continue

                                # Try invite link first
                                if invite_link:
                                    await client.join_chat(invite_link)
                                    logger.info(f"Auto-joined group {gname} (id={gid}) via invite link")
                                    joined = True
                                    break

                                # Fallback to username
                                elif username:
                                    await client.join_chat(f"@{username}")
                                    logger.info(f"Auto-joined group {gname} (id={gid}) via username")
                                    joined = True
                                    break

                            except FloodWaitError as e:
                                logger.warning(f"FloodWait joining {gname}: {e.seconds}s")
                                # Wait and try next client
                                continue
                            except (ChannelPrivateError, InviteHashInvalidError, InviteHashExpiredError):
                                # Private/expired, try next client or move on
                                continue
                            except Exception as e:
                                logger.warning(f"Failed to join {gname} with admin {admin_id}: {e}")
                                continue

                        if joined:
                            joined_count += 1
                            # Trigger historical crawl for the newly joined group
                            asyncio.create_task(self._crawl_historical_for_group(gid))

                        # Delay between groups to avoid rate limiting
                        await asyncio.sleep(30)

                    except Exception as e:
                        logger.error(f"Unexpected error auto-joining group {gid}: {e}")
                        continue

                logger.info(f"Auto-join complete: {joined_count}/{len(unmapped)} groups joined")
                self._last_auto_join_at = now
                await asyncio.sleep(5 * 60)  # Check again in 5 minutes

            except asyncio.CancelledError:
                logger.info("Auto-join task cancelled")
                break
            except Exception as e:
                logger.error(f"Auto-join loop error: {e}")
                await asyncio.sleep(5 * 60)
                continue

    # ------------------------------------------------------------------
    # Listener task management — start, restart, and watchdog
    # ------------------------------------------------------------------

    def _start_listener_task(self, user_id: int, client: TelegramClient) -> None:
        """Start a listener task with a done callback for immediate restart."""
        task = asyncio.create_task(
            self._run_listener_with_reconnect(user_id, client)
        )
        task.add_done_callback(lambda t, uid=user_id: self._on_listener_done(uid, t))
        self._listener_tasks[user_id] = task

    def _on_listener_done(self, user_id: int, task: asyncio.Task) -> None:
        """Immediate restart when a listener exits — don't wait for 60s watchdog cycle."""
        if not self.running:
            return
        if task.cancelled():
            return
        logger.warning("Listener for user_id=%s exited — scheduling immediate restart", user_id)
        asyncio.get_event_loop().call_soon(
            lambda: asyncio.create_task(self._restart_single_listener(user_id))
        )

    async def _restart_single_listener(self, user_id: int) -> None:
        """Reconnect a single admin client and restart its listener task."""
        if not self.running:
            return
        client = self.clients.get(user_id)
        if not client:
            return
        try:
            if not client.is_connected():
                await asyncio.wait_for(client.connect(), timeout=10)
                me = await client.get_me()
                if not me:
                    logger.error("Reconnect auth failed for user_id=%s", user_id)
                    return
            self._start_listener_task(user_id, client)
            logger.info("Restarted listener for user_id=%s", user_id)

            # Trigger emergency gap-fill to catch any messages missed during downtime
            await self._trigger_emergency_gap_fill(f"listener_restart_user_{user_id}")
        except Exception as e:
            logger.error("Failed to restart listener for user_id=%s: %s", user_id, e)

    async def _listener_watchdog(self) -> None:
        """Periodic fallback check for listener health.

        The primary restart mechanism is _on_listener_done (immediate callback).
        This watchdog is a safety net that catches edge cases where the callback
        might not fire (e.g., task stuck, callback exception).
        """
        while self.running:
            await asyncio.sleep(60)
            if not self.running:
                break

            alive = 0
            dead_user_ids: list[int] = []
            for user_id, task in self._listener_tasks.items():
                if task and not task.done():
                    alive += 1
                else:
                    dead_user_ids.append(user_id)

            total = len(self._listener_tasks)

            if dead_user_ids:
                severity = "CRITICAL" if alive == 0 else "WARNING"
                logger.log(
                    logging.CRITICAL if alive == 0 else logging.WARNING,
                    "WATCHDOG: %d/%d listeners dead (%s). Restarting: %s",
                    len(dead_user_ids), total, severity, dead_user_ids,
                )
                for user_id in dead_user_ids:
                    await self._restart_single_listener(user_id)

    async def _trigger_emergency_gap_fill(self, reason: str) -> None:
        """Trigger immediate gap-fill without waiting for periodic cycle.

        Called when:
        - Listener reconnects after disconnect
        - Circuit breaker recovers from open state
        - Watchdog detects and restarts dead listener

        Uses extended lookback based on time since last gap-fill.
        """
        if not self.running:
            return

        logger.warning("[EMERGENCY-GAP-FILL] Triggered: %s", reason)

        # Calculate lookback based on time since last gap-fill
        now_mono = time.monotonic()
        if self._last_gap_fill_at > 0:
            hours_since_last = (now_mono - self._last_gap_fill_at) / 3600
            lookback_hours = min(max(hours_since_last + 0.5, 3.0), 24)
        else:
            lookback_hours = 3.0

        lookback = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
        logger.info("[EMERGENCY-GAP-FILL] Starting (lookback=%.1fh)...", lookback_hours)

        # Reuse gap-fill logic from _periodic_gap_fill
        filled = 0
        for group_uuid in self._groups_map.keys():
            try:
                group_data = self._groups_map.get(group_uuid)
                if not group_data or not group_data.get("is_enabled"):
                    continue

                gid = int(group_uuid)

                # Skip if FloodWait penalty active
                if gid in self._flood_wait_until:
                    penalty_ends = self._flood_wait_until[gid]
                    if time.monotonic() < penalty_ends:
                        continue

                # Get working client and entity
                working_client, entity = await self._get_entity_for_group_with_client(group_uuid, group_data)
                if not working_client or not entity:
                    continue

                # Fetch messages since lookback
                count = 0
                async for message in working_client.iter_messages(entity, offset_date=lookback, reverse=True):
                    if count >= GAP_FILL_MAX_MESSAGES:
                        break

                    if message.text or message.media:
                        await self._enqueue_message(
                            message, group_uuid,
                            broadcast=False,
                            message_source="gap_fill"
                        )
                        count += 1
                        filled += 1

                    # Throttle
                    if count % 200 == 0:
                        await asyncio.sleep(1.5)

                await asyncio.sleep(2.0)  # Inter-group delay

            except FloodWaitError as e:
                self._flood_wait_until[gid] = time.monotonic() + e.seconds
                logger.warning("[EMERGENCY-GAP-FILL] FloodWait %ds for group %s", e.seconds, gid)
            except Exception as e:
                logger.error("[EMERGENCY-GAP-FILL] Error for group %s: %s", group_uuid, e)

        self._last_gap_fill_at = time.monotonic()
        logger.info("[EMERGENCY-GAP-FILL] Complete — %d messages re-enqueued", filled)

    async def _monitor_sla(self) -> None:
        """Monitor gap-fill SLA and send Sentry alerts when at risk.

        Checks every 15 minutes for groups exceeding 2.5-hour threshold
        (provides 30-minute early warning before 3-hour SLA breach).
        """
        while self.running:
            await asyncio.sleep(900)  # 15 minutes
            if not self.running:
                break

            try:
                at_risk = self._gap_fill_metrics.get_groups_exceeding_sla(sla_hours=2.5)
                if not at_risk:
                    continue

                # Determine severity
                critical_groups = [g for g in at_risk if g["hours_since_last_fill"] >= 3.0]
                severity = "critical" if critical_groups else "warning"

                # Send Sentry alert
                try:
                    import sentry_sdk
                    if sentry_sdk.is_initialized():
                        sentry_sdk.capture_message(
                            f"Gap-fill SLA at risk: {len(at_risk)} group(s) not filled in 2.5+ hours",
                            level=severity,
                            extras={
                                "at_risk_groups": at_risk[:10],  # Top 10 worst offenders
                                "total_at_risk": len(at_risk),
                                "critical_count": len(critical_groups),
                            },
                        )
                except Exception:
                    pass  # Sentry unavailable, continue

                logger.warning(
                    "[SLA-MONITOR] %d group(s) exceeding 2.5h gap-fill threshold (severity=%s)",
                    len(at_risk), severity
                )

            except Exception as e:
                logger.error("[SLA-MONITOR] Monitoring failed: %s", e)

    # ------------------------------------------------------------------
    # Listener with auto-reconnect
    # ------------------------------------------------------------------

    async def _run_listener_with_reconnect(self, user_id: int, client: TelegramClient) -> None:
        """Keep a Telethon client running with auto-reconnect.

        Telethon's auto_reconnect=True handles brief disconnections internally.
        This loop catches cases where the connection truly drops and run_until_disconnected returns.
        """
        attempts = 0
        while self.running:
            try:
                await client.run_until_disconnected()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Live crawler [user_id=%s] disconnected: %s", user_id, e)

                # Trigger emergency gap-fill to catch messages missed during disconnect
                if self.running:
                    await self._trigger_emergency_gap_fill(f"disconnect_user_{user_id}")

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
    # Concurrent media download pipeline (for historical crawl / gap-fill)
    # ------------------------------------------------------------------

    async def _download_single_media(self, message, media_type: str, group_uuid: str, client: TelegramClient) -> bool:
        """Delegate to MediaUploader."""
        return await self._media_uploader.download_single_media(message, media_type, group_uuid, client)

    async def _download_media_parallel(self, media_items: list[tuple], group_uuid: str, client: TelegramClient) -> int:
        """Delegate to MediaUploader."""
        return await self._media_uploader.download_media_parallel(
            media_items, group_uuid, client, running_check=lambda: self.running
        )

    async def _upload_media(self, message, group_uuid: str, media_type: str, client: TelegramClient) -> tuple[str | None, str | None]:
        """Delegate to MediaUploader."""
        return await self._media_uploader.upload_media(message, group_uuid, media_type, client)


# Global singleton
live_crawler = LiveCrawlerService()
