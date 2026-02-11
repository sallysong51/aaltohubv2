"""
Telethon client manager for Telegram API interactions
"""
import asyncio
import logging
import time
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    FloodWaitError,
    PhoneNumberInvalidError,
    PhoneNumberBannedError,
    UsernameInvalidError,
    UsernameNotOccupiedError,
    PasswordHashInvalidError,
)


class TelegramAuthError(Exception):
    """User-facing Telegram auth error with HTTP status code.
    These are NOT server errors — they should become 400-level responses."""

    def __init__(self, detail: str, status_code: int = 400):
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)

from telethon.tl.functions.channels import InviteToChannelRequest
from telethon.tl.types import InputUser, Chat, Channel
from typing import Optional, List, Dict
from app.config import settings
from app.encryption import session_encryption, ENCRYPTION_VERSION
from app.database import db
from app.models import UserRole

logger = logging.getLogger(__name__)

# Telegram warm client ping interval (seconds)
# Reduced from 120s to 45s for faster disconnection detection (#7)
_TELEGRAM_PING_INTERVAL = 45


# Auth flow client entry: stores the TelegramClient between send_code → verify_code → verify_2fa
class _AuthFlow:
    __slots__ = ("client", "created_at")

    def __init__(self, client: TelegramClient):
        self.client = client
        self.created_at = time.monotonic()


class _CachedSession:
    __slots__ = ("session_string", "cached_at")

    def __init__(self, session_string: str):
        self.session_string = session_string
        self.cached_at = time.monotonic()


class TelegramClientManager:
    """Manage Telethon clients for users"""

    # Auth flow clients expire after 15 minutes (user has 15 min to complete login)
    AUTH_FLOW_TTL = 900
    # Session cache entries expire after 30 minutes
    SESSION_CACHE_TTL = 1800

    def __init__(self):
        # Per-phone auth flow clients (send_code → verify_code → verify_2fa)
        self._auth_flows: Dict[str, _AuthFlow] = {}
        self.admin_client: Optional[TelegramClient] = None
        self._admin_client_lock = asyncio.Lock()
        # In-memory session cache with TTL: user_id → _CachedSession
        self._session_cache: Dict[str, _CachedSession] = {}
        # Pre-warmed client for instant send_code (no TCP+TLS wait)
        self._warm_client: Optional[TelegramClient] = None
        self._warming: bool = False

    # ------------------------------------------------------------------
    # Pre-warm client pool (sub-1s code delivery)
    # ------------------------------------------------------------------

    def _make_client(self, session: Optional[str] = None) -> TelegramClient:
        """Create a TelegramClient with optimized connection parameters.

        Optimizations applied:
        - use_ipv6=False (default): avoids 2-10s delay on hosts without IPv6 (#3)
        - timeout=5: faster failure detection, was 10 (#4)
        - flood_sleep_threshold=5: raise FloodWaitError for waits >5s instead of
          silently sleeping up to 60s with no user feedback (#5)
        - request_retries=1: was 2, avoid tripling wait time on failure (#6)
        """
        return TelegramClient(
            StringSession(session or ""),
            settings.TELEGRAM_API_ID,
            settings.TELEGRAM_API_HASH,
            connection_retries=1,
            retry_delay=0.5,
            request_retries=1,
            timeout=5,
            flood_sleep_threshold=5,
        )

    async def warm_up(self):
        """Pre-connect a TelegramClient so the next send_code is instant.
        Call from FastAPI startup event."""
        if self._warming:
            return
        self._warming = True
        try:
            client = self._make_client()
            await client.connect()
            self._warm_client = client
        except Exception:
            self._warm_client = None
        finally:
            self._warming = False

    def _schedule_warm_up(self):
        """Schedule a background warm-up (non-blocking)."""
        if not self._warming and (self._warm_client is None or not self._warm_client.is_connected()):
            asyncio.create_task(self.warm_up())

    async def ping_loop(self) -> None:
        """Periodically verify warm client connectivity and re-warm if disconnected.

        BUG FIX (#2): Previously used get_me() which ALWAYS fails on
        unauthenticated warm clients, causing the warm client to be destroyed
        and recreated every ping cycle. This meant the warm client was often
        unavailable when a user tried to send_code, forcing a cold TCP+TLS
        connection (1-3s delay). Now uses is_connected() only — Telethon's
        internal keepalive pings already verify TCP liveness.
        """
        while True:
            await asyncio.sleep(_TELEGRAM_PING_INTERVAL)
            try:
                if self._warm_client and self._warm_client.is_connected():
                    logger.debug("[TELEGRAM] Warm client alive")
                else:
                    logger.warning("[TELEGRAM] Warm client disconnected — re-warming")
                    if self._warm_client:
                        asyncio.create_task(self._safe_disconnect(self._warm_client))
                    self._warm_client = None
                    self._schedule_warm_up()
            except Exception as e:
                logger.warning("[TELEGRAM] Warm client check failed: %s — re-warming", e)
                if self._warm_client:
                    asyncio.create_task(self._safe_disconnect(self._warm_client))
                self._warm_client = None
                self._schedule_warm_up()

    async def _take_warm_client(self) -> Optional[TelegramClient]:
        """Take the pre-warmed client. Returns None if unavailable."""
        client = self._warm_client
        self._warm_client = None
        if client and client.is_connected():
            return client
        if client:
            asyncio.create_task(self._safe_disconnect(client))
        return None

    # ------------------------------------------------------------------
    # Auth flow client management
    # ------------------------------------------------------------------

    async def _get_or_create_auth_client(self, phone_or_username: str) -> TelegramClient:
        """Get existing auth flow client or create a new one for this phone/username."""
        self._cleanup_stale_auth_flows()

        flow = self._auth_flows.get(phone_or_username)
        if flow and flow.client.is_connected():
            return flow.client

        # Try pre-warmed client first (instant, no connection wait)
        client = await self._take_warm_client()
        if not client:
            # Fall back to fresh connection
            client = self._make_client()
            await client.connect()

        self._auth_flows[phone_or_username] = _AuthFlow(client)

        # Start warming next client in background for the next user
        self._schedule_warm_up()

        return client

    async def _finish_auth_flow(self, phone_or_username: str):
        """Clean up auth flow client after successful authentication."""
        flow = self._auth_flows.pop(phone_or_username, None)
        if flow:
            try:
                await flow.client.disconnect()
            except Exception:
                pass

    def _cleanup_stale_auth_flows(self):
        """Remove auth flow clients older than TTL or already disconnected (P2-1.27)."""
        now = time.monotonic()
        stale = [
            key for key, flow in self._auth_flows.items()
            if now - flow.created_at > self.AUTH_FLOW_TTL or not flow.client.is_connected()
        ]
        for key in stale:
            flow = self._auth_flows.pop(key, None)
            if flow and flow.client.is_connected():
                asyncio.create_task(self._safe_disconnect(flow.client))

    @staticmethod
    async def _safe_disconnect(client: TelegramClient):
        try:
            await client.disconnect()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Authentication endpoints
    # ------------------------------------------------------------------

    async def send_code(self, phone_or_username: str) -> Dict:
        """Send authentication code to user.
        Creates a dedicated client for this auth flow and stores it for reuse
        in verify_code/verify_2fa (same Telethon session = required for 2FA).
        """
        client = await self._get_or_create_auth_client(phone_or_username)

        try:
            sent_code = await client.send_code_request(phone_or_username)
            return {
                "success": True,
                "phone_code_hash": sent_code.phone_code_hash,
                "requires_2fa": False
            }
        except FloodWaitError as e:
            await self._finish_auth_flow(phone_or_username)
            minutes = e.seconds // 60
            if minutes >= 60:
                wait_str = f"{minutes // 60}시간 {minutes % 60}분"
            else:
                wait_str = f"{minutes}분"
            raise TelegramAuthError(f"너무 많은 요청으로 {wait_str} 후 다시 시도해주세요", 429)
        except PhoneNumberInvalidError:
            await self._finish_auth_flow(phone_or_username)
            raise TelegramAuthError("올바르지 않은 전화번호 형식입니다. 국제번호 형식(+358...)으로 입력해주세요")
        except PhoneNumberBannedError:
            await self._finish_auth_flow(phone_or_username)
            raise TelegramAuthError("이 전화번호는 텔레그램에서 차단되었습니다")
        except UsernameInvalidError:
            await self._finish_auth_flow(phone_or_username)
            raise TelegramAuthError("올바르지 않은 username 형식입니다")
        except UsernameNotOccupiedError:
            await self._finish_auth_flow(phone_or_username)
            raise TelegramAuthError("존재하지 않는 username입니다")
        except TelegramAuthError:
            raise
        except Exception as e:
            await self._finish_auth_flow(phone_or_username)
            raise

    async def verify_code(
        self,
        phone_or_username: str,
        code: str,
        phone_code_hash: str
    ) -> Dict:
        """Verify authentication code. Reuses the client from send_code (same session)."""
        # Check if auth flow exists — if not, user took too long or never called send_code
        flow = self._auth_flows.get(phone_or_username)
        if not flow or not flow.client.is_connected():
            raise TelegramAuthError(
                "인증 세션이 만료되었습니다. 처음부터 다시 시도해주세요",
                408,
            )

        client = flow.client

        try:
            await client.sign_in(phone_or_username, code, phone_code_hash=phone_code_hash)

            me = await client.get_me()
            session_string = client.session.save()

            # Auth complete — clean up flow client
            await self._finish_auth_flow(phone_or_username)

            return {
                "success": True,
                "session_string": session_string,
                "user_info": {
                    "telegram_id": me.id,
                    "phone_number": me.phone,
                    "username": me.username,
                    "first_name": me.first_name,
                    "last_name": me.last_name
                },
                "requires_2fa": False
            }
        except SessionPasswordNeededError:
            # 2FA enabled — keep client alive for verify_2fa step
            return {
                "success": False,
                "requires_2fa": True,
                "message": "Two-factor authentication is enabled. Please provide your password."
            }
        except PhoneCodeInvalidError:
            await self._finish_auth_flow(phone_or_username)
            raise TelegramAuthError("올바르지 않은 인증 코드입니다")
        except PhoneCodeExpiredError:
            await self._finish_auth_flow(phone_or_username)
            raise TelegramAuthError("인증 코드가 만료되었습니다. 코드를 재전송해주세요")
        except FloodWaitError as e:
            await self._finish_auth_flow(phone_or_username)
            minutes = e.seconds // 60
            if minutes >= 60:
                wait_str = f"{minutes // 60}시간 {minutes % 60}분"
            else:
                wait_str = f"{minutes}분"
            raise TelegramAuthError(f"너무 많은 요청으로 {wait_str} 후 다시 시도해주세요", 429)
        except TelegramAuthError:
            raise
        except Exception as e:
            await self._finish_auth_flow(phone_or_username)
            raise

    async def verify_2fa(
        self,
        phone_or_username: str,
        password: str
    ) -> Dict:
        """Verify 2FA password. Reuses the SAME client that got SessionPasswordNeededError."""
        flow = self._auth_flows.get(phone_or_username)
        if not flow or not flow.client.is_connected():
            raise TelegramAuthError("세션이 만료되었습니다. 처음부터 다시 시작해주세요", 408)

        client = flow.client

        try:
            await client.sign_in(password=password)

            me = await client.get_me()
            session_string = client.session.save()

            # Auth complete — clean up flow client
            await self._finish_auth_flow(phone_or_username)

            return {
                "success": True,
                "session_string": session_string,
                "user_info": {
                    "telegram_id": me.id,
                    "phone_number": me.phone,
                    "username": me.username,
                    "first_name": me.first_name,
                    "last_name": me.last_name
                }
            }
        except PasswordHashInvalidError:
            await self._finish_auth_flow(phone_or_username)
            raise TelegramAuthError("2FA 비밀번호가 올바르지 않습니다")
        except TelegramAuthError:
            raise
        except Exception as e:
            await self._finish_auth_flow(phone_or_username)
            raise

    # ------------------------------------------------------------------
    # Session persistence (with in-memory cache)
    # ------------------------------------------------------------------

    async def save_session(self, user_id: str, session_string: str):
        """Encrypt and save Telethon session to database. Updates cache.

        Uses user_id as AAD (additional authenticated data) so the encrypted
        blob is bound to this specific user and cannot be swapped.
        """
        aad = str(user_id)
        encrypted_session = session_encryption.encrypt(session_string, aad=aad)
        key_hash = session_encryption.get_key_hash()

        try:
            # Atomic upsert — no TOCTOU race between check and insert
            await db.execute(
                """INSERT INTO telethon_sessions (user_id, session_data, key_hash)
                   VALUES ($1, $2, $3)
                   ON CONFLICT (user_id)
                   DO UPDATE SET session_data = $2, key_hash = $3, updated_at = NOW()""",
                int(user_id), encrypted_session, key_hash,
            )

            # Update cache
            self._session_cache[user_id] = _CachedSession(session_string)
        except Exception as e:
            raise Exception(f"Failed to save session: {str(e)}")

    async def load_session(self, user_id: str) -> Optional[str]:
        """Load Telethon session — from cache first, then telegram_connections, then telethon_sessions.

        Migration strategy:
        1. Check telegram_connections first (new system for Supabase Auth users)
        2. Fall back to telethon_sessions (legacy system during migration)

        Handles migration from legacy encryption (no KDF, no AAD) to v2
        (PBKDF2 + AAD). If a legacy session is detected, it is decrypted
        with the old scheme, re-encrypted with v2, and saved back.
        """
        # Check cache first (with TTL)
        cached = self._session_cache.get(user_id)
        if cached is not None:
            if time.monotonic() - cached.cached_at < self.SESSION_CACHE_TTL:
                return cached.session_string
            else:
                del self._session_cache[user_id]

        # Evict expired entries and enforce max cache size
        SESSION_CACHE_MAX = 200
        if len(self._session_cache) > 50:
            now = time.monotonic()
            expired = [k for k, v in self._session_cache.items() if now - v.cached_at > self.SESSION_CACHE_TTL]
            for k in expired:
                del self._session_cache[k]
            # Hard cap: if still over max, evict oldest cached entries
            if len(self._session_cache) >= SESSION_CACHE_MAX:
                sorted_keys = sorted(self._session_cache, key=lambda k: self._session_cache[k].cached_at)
                for k in sorted_keys[:len(self._session_cache) - SESSION_CACHE_MAX + 1]:
                    del self._session_cache[k]

        try:
            # Try telegram_connections first (new system for Supabase Auth users)
            row = await db.fetchrow(
                """SELECT session_encrypted, key_hash FROM telegram_connections
                   WHERE user_id = $1
                   ORDER BY last_used_at DESC LIMIT 1""",
                int(user_id)
            )

            if row:
                # Found in telegram_connections (new system)
                aad = str(user_id)  # Same AAD as before — user_id unchanged!
                encrypted_session = row["session_encrypted"]
                key_hash = row.get("key_hash", "")

                if key_hash == ENCRYPTION_VERSION:
                    session_string = session_encryption.decrypt(encrypted_session, aad=aad)
                else:
                    # Legacy encryption in telegram_connections (rare)
                    from app.encryption import get_legacy_encryption
                    legacy = get_legacy_encryption()
                    session_string = legacy.decrypt(encrypted_session)

                # Update last_used_at
                await db.execute(
                    "UPDATE telegram_connections SET last_used_at = NOW() WHERE user_id = $1",
                    int(user_id)
                )

                # Populate cache
                self._session_cache[user_id] = _CachedSession(session_string)
                logger.debug("Loaded session from telegram_connections for user %s", user_id)
                return session_string

            # Fall back to telethon_sessions (legacy system during migration)
            row = await db.fetchrow(
                "SELECT * FROM telethon_sessions WHERE user_id = $1", int(user_id)
            )

            if not row:
                return None

            encrypted_session = row["session_data"]
            key_hash = row.get("key_hash", "") if hasattr(row, 'get') else (row["key_hash"] or "")
            aad = str(user_id)

            session_string: Optional[str] = None

            if key_hash == ENCRYPTION_VERSION:
                # v2 encryption — decrypt with AAD
                session_string = session_encryption.decrypt(encrypted_session, aad=aad)
            else:
                # Legacy encryption — try old scheme, then migrate
                from app.encryption import get_legacy_encryption
                legacy = get_legacy_encryption()
                session_string = legacy.decrypt(encrypted_session)

                # Re-encrypt with v2 and save back (migration)
                new_encrypted = session_encryption.encrypt(session_string, aad=aad)
                await db.execute(
                    """UPDATE telethon_sessions SET session_data = $1, key_hash = $2, updated_at = NOW()
                       WHERE user_id = $3""",
                    new_encrypted, ENCRYPTION_VERSION, int(user_id),
                )

            if not session_string:
                raise TelegramAuthError("세션 데이터를 복호화할 수 없습니다. 다시 로그인해주세요.", status_code=401)

            # Populate cache
            self._session_cache[user_id] = _CachedSession(session_string)
            return session_string
        except TelegramAuthError:
            raise
        except Exception as e:
            logger.warning("Session load failed for user %s: %s", user_id, e)
            raise TelegramAuthError("텔레그램 세션을 불러올 수 없습니다. 다시 로그인해주세요.", status_code=401)

    # ------------------------------------------------------------------
    # User / admin client helpers
    # ------------------------------------------------------------------

    async def get_user_client(self, user_id: str) -> TelegramClient:
        """Create a Telethon client for user.

        IMPORTANT: Caller is responsible for disconnecting the returned client
        when done (e.g. via ``try/finally: await client.disconnect()``).
        Each call creates a new connection — intended for short-lived operations
        like get_dialogs(). For long-lived connections, use the live crawler's
        admin client pool instead.
        """
        session_string = await self.load_session(user_id)
        if not session_string:
            raise TelegramAuthError("텔레그램 계정이 연결되지 않았습니다. 프로필에서 텔레그램 계정을 먼저 추가해주세요.", status_code=401)

        client = self._make_client(session_string)
        try:
            await asyncio.wait_for(client.connect(), timeout=10.0)
        except asyncio.TimeoutError:
            await self._safe_disconnect(client)
            raise TelegramAuthError("텔레그램 서버 연결 시간 초과. 잠시 후 다시 시도해주세요.", status_code=504)

        return client

    async def get_admin_client(self) -> TelegramClient:
        """Get admin Telethon client (for inviting to groups).

        Protected by _admin_client_lock to prevent concurrent callers from
        creating duplicate connections.
        """
        async with self._admin_client_lock:
            if self.admin_client and self.admin_client.is_connected():
                return self.admin_client

            admin_row = await db.fetchrow(
                "SELECT * FROM users WHERE role = $1 LIMIT 1", UserRole.ADMIN.value
            )

            if not admin_row:
                raise Exception("Admin user not found")

            admin_id = admin_row["id"]

            session_string = await self.load_session(admin_id)
            if not session_string:
                raise Exception("Admin session not found")

            self.admin_client = self._make_client(session_string)
            await self.admin_client.connect()

            return self.admin_client

    @staticmethod
    def _parse_dialog_entity(entity) -> Optional[Dict]:
        """Convert a Telethon dialog entity to a group info dict, or None if not a group."""
        if not isinstance(entity, (Chat, Channel)):
            return None
        if isinstance(entity, Channel):
            group_type = "supergroup" if entity.megagroup else "channel"
        else:
            group_type = "group"
        return {
            "telegram_id": entity.id,
            "title": entity.title,
            "username": getattr(entity, 'username', None),
            "member_count": getattr(entity, 'participants_count', None),
            "group_type": group_type,
            "has_topics": getattr(entity, 'forum', False),
        }

    async def get_user_groups(self, user_id: str) -> List[Dict]:
        """Get all groups/channels user is member of"""
        client = await self.get_user_client(user_id)

        try:
            # Timeout: get_dialogs() can hang on slow/unreachable Telegram servers
            dialogs = await asyncio.wait_for(client.get_dialogs(), timeout=15.0)
            groups = []

            for dialog in dialogs:
                info = self._parse_dialog_entity(dialog.entity)
                if info:
                    groups.append(info)

            return groups
        except asyncio.TimeoutError:
            raise TelegramAuthError("텔레그램 그룹 목록 로딩 시간 초과. 잠시 후 다시 시도해주세요.", status_code=504)
        except (ConnectionError, OSError) as e:
            raise TelegramAuthError(f"텔레그램 네트워크 오류: {e}", status_code=502)
        except TelegramAuthError:
            raise
        except Exception as e:
            err_str = str(e).lower()
            # Detect expired/revoked Telegram sessions
            if any(kw in err_str for kw in ("auth key", "unauthorized", "session revoked", "user deactivated")):
                raise TelegramAuthError("텔레그램 세션이 만료되었습니다. 다시 로그인해주세요.", status_code=401)
            raise TelegramAuthError(f"텔레그램 그룹 목록을 불러올 수 없습니다.", status_code=500)
        finally:
            await client.disconnect()

    # ------------------------------------------------------------------
    # Multi-connection support (one user → multiple Telegram accounts)
    # ------------------------------------------------------------------

    async def save_connection(self, user_id: str, telegram_user_id: int,
                               session_string: str, phone_masked: str = None,
                               username: str = None, first_name: str = None,
                               last_name: str = None) -> str:
        """Save a Telegram connection for a user. Returns connection UUID."""
        import uuid
        aad = str(user_id)
        encrypted_session = session_encryption.encrypt(session_string, aad=aad)
        key_hash = session_encryption.get_key_hash()
        connection_id = str(uuid.uuid4())

        await db.execute(
            """INSERT INTO telegram_connections
               (id, user_id, telegram_user_id, phone_masked, username,
                session_encrypted, key_hash, first_name, last_name)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
               ON CONFLICT (user_id, telegram_user_id)
               DO UPDATE SET session_encrypted = $6, key_hash = $7,
                             username = $5, first_name = $8, last_name = $9,
                             last_used_at = NOW(), updated_at = NOW()
               """,
            connection_id, int(user_id), telegram_user_id,
            phone_masked, username, encrypted_session, key_hash,
            first_name, last_name,
        )

        # If conflict (ON CONFLICT DO UPDATE), fetch the existing id
        row = await db.fetchrow(
            "SELECT id FROM telegram_connections WHERE user_id = $1 AND telegram_user_id = $2",
            int(user_id), telegram_user_id,
        )
        return str(row["id"]) if row else connection_id

    async def get_connections(self, user_id: str) -> List[Dict]:
        """Get all Telegram connections for a user."""
        rows = await db.fetch(
            """SELECT id, telegram_user_id, phone_masked, username,
                      first_name, last_name, connected_at, last_used_at
               FROM telegram_connections
               WHERE user_id = $1
               ORDER BY connected_at ASC""",
            int(user_id),
        )
        return [dict(r) for r in rows]

    async def delete_connection(self, connection_id: str, user_id: str) -> bool:
        """Delete a Telegram connection. Returns True if deleted."""
        result = await db.execute(
            "DELETE FROM telegram_connections WHERE id = $1 AND user_id = $2",
            connection_id, int(user_id),
        )
        # Clear cache entries that might use this connection
        cache_key = f"conn:{connection_id}"
        self._session_cache.pop(cache_key, None)
        return "DELETE 1" in (result or "")

    async def load_session_by_connection(self, connection_id: str, user_id: str) -> Optional[str]:
        """Load a specific Telegram connection's session."""
        cache_key = f"conn:{connection_id}"
        cached = self._session_cache.get(cache_key)
        if cached and time.monotonic() - cached.cached_at < self.SESSION_CACHE_TTL:
            return cached.session_string

        row = await db.fetchrow(
            """SELECT session_encrypted, key_hash, user_id
               FROM telegram_connections WHERE id = $1 AND user_id = $2""",
            connection_id, int(user_id),
        )
        if not row:
            return None

        aad = str(row["user_id"])
        if row["key_hash"] == ENCRYPTION_VERSION:
            session_string = session_encryption.decrypt(row["session_encrypted"], aad=aad)
        else:
            from app.encryption import get_legacy_encryption
            session_string = get_legacy_encryption().decrypt(row["session_encrypted"])

        await db.execute(
            "UPDATE telegram_connections SET last_used_at = NOW() WHERE id = $1",
            connection_id,
        )
        self._session_cache[cache_key] = _CachedSession(session_string)
        return session_string

    async def get_user_client_by_connection(self, connection_id: str, user_id: str) -> TelegramClient:
        """Create a Telethon client from a specific connection."""
        session_string = await self.load_session_by_connection(connection_id, user_id)
        if not session_string:
            raise TelegramAuthError("텔레그램 연결을 찾을 수 없습니다.", status_code=404)

        client = self._make_client(session_string)
        try:
            await asyncio.wait_for(client.connect(), timeout=10.0)
        except asyncio.TimeoutError:
            await self._safe_disconnect(client)
            raise TelegramAuthError("텔레그램 서버 연결 시간 초과.", status_code=504)
        return client

    async def get_user_groups_by_connection(self, connection_id: str, user_id: str) -> List[Dict]:
        """Get all groups/channels from a specific Telegram connection."""
        client = await self.get_user_client_by_connection(connection_id, user_id)
        try:
            dialogs = await asyncio.wait_for(client.get_dialogs(), timeout=15.0)
            groups = []
            for dialog in dialogs:
                info = self._parse_dialog_entity(dialog.entity)
                if info:
                    groups.append(info)
            return groups
        except asyncio.TimeoutError:
            raise TelegramAuthError("텔레그램 그룹 목록 로딩 시간 초과.", status_code=504)
        except Exception as e:
            err_str = str(e).lower()
            if any(kw in err_str for kw in ("auth key", "unauthorized", "session revoked")):
                raise TelegramAuthError("텔레그램 세션이 만료되었습니다. 다시 연결해주세요.", status_code=401)
            raise TelegramAuthError("텔레그램 그룹 목록을 불러올 수 없습니다.", status_code=500)
        finally:
            await client.disconnect()

    async def invite_admin_to_group(self, group_telegram_id: int) -> Dict:
        """Invite admin to a public group"""
        try:
            admin_client = await self.get_admin_client()

            group = await admin_client.get_entity(group_telegram_id)

            try:
                participants = await admin_client.get_participants(group, limit=1)
                return {
                    "success": True,
                    "message": "Admin is already a member"
                }
            except Exception:
                pass

            admin_user = await admin_client.get_me()

            await admin_client(InviteToChannelRequest(
                group,
                [InputUser(admin_user.id, admin_user.access_hash)]
            ))

            return {
                "success": True,
                "message": "Admin invited successfully"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }


# Global Telegram client manager
telegram_manager = TelegramClientManager()
