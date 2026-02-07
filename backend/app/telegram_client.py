"""
Telethon client manager for Telegram API interactions
"""
import asyncio
import time
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    FloodWaitError,
    PhoneNumberInvalidError,
    PhoneNumberBannedError,
    UsernameInvalidError,
    UsernameNotOccupiedError,
    PasswordHashInvalidError,
)
from telethon.tl.functions.channels import InviteToChannelRequest
from telethon.tl.types import InputUser, Chat, Channel
from typing import Optional, List, Dict
from app.config import settings
from app.encryption import session_encryption, ENCRYPTION_VERSION
from app.database import db
from app.models import UserRole


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

    # Auth flow clients expire after 5 minutes (user has 5 min to complete login)
    AUTH_FLOW_TTL = 300
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
        """Create a TelegramClient with optimized connection parameters."""
        return TelegramClient(
            StringSession(session or ""),
            settings.TELEGRAM_API_ID,
            settings.TELEGRAM_API_HASH,
            connection_retries=1,
            retry_delay=0.5,
            request_retries=2,
            timeout=10,
            flood_sleep_threshold=60,
            use_ipv6=True,
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
            raise Exception(f"너무 많은 요청으로 {wait_str} 후 다시 시도해주세요")
        except PhoneNumberInvalidError:
            await self._finish_auth_flow(phone_or_username)
            raise Exception("올바르지 않은 전화번호 형식입니다. 국제번호 형식(+358...)으로 입력해주세요")
        except PhoneNumberBannedError:
            await self._finish_auth_flow(phone_or_username)
            raise Exception("이 전화번호는 텔레그램에서 차단되었습니다")
        except UsernameInvalidError:
            await self._finish_auth_flow(phone_or_username)
            raise Exception("올바르지 않은 username 형식입니다")
        except UsernameNotOccupiedError:
            await self._finish_auth_flow(phone_or_username)
            raise Exception("존재하지 않는 username입니다")
        except Exception as e:
            await self._finish_auth_flow(phone_or_username)
            raise Exception(f"코드 전송 실패: {str(e)}")

    async def verify_code(
        self,
        phone_or_username: str,
        code: str,
        phone_code_hash: str
    ) -> Dict:
        """Verify authentication code. Reuses the client from send_code (same session)."""
        client = await self._get_or_create_auth_client(phone_or_username)

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
            raise Exception("올바르지 않은 인증 코드입니다")
        except Exception as e:
            await self._finish_auth_flow(phone_or_username)
            raise Exception(f"코드 검증 실패: {str(e)}")

    async def verify_2fa(
        self,
        phone_or_username: str,
        password: str
    ) -> Dict:
        """Verify 2FA password. Reuses the SAME client that got SessionPasswordNeededError."""
        flow = self._auth_flows.get(phone_or_username)
        if not flow or not flow.client.is_connected():
            raise Exception("세션이 만료되었습니다. 처음부터 다시 시작해주세요")

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
            raise Exception("2FA 비밀번호가 올바르지 않습니다")
        except Exception as e:
            await self._finish_auth_flow(phone_or_username)
            raise Exception(f"2FA 검증 실패: {str(e)}")

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
        """Load Telethon session — from cache first, then DB.

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

            # Populate cache
            self._session_cache[user_id] = _CachedSession(session_string)
            return session_string
        except Exception as e:
            raise Exception(f"Failed to load session: {str(e)}")

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
            raise Exception("Session not found for user")

        client = self._make_client(session_string)
        await client.connect()

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

    async def get_user_groups(self, user_id: str) -> List[Dict]:
        """Get all groups/channels user is member of"""
        client = await self.get_user_client(user_id)

        try:
            dialogs = await client.get_dialogs()
            groups = []

            for dialog in dialogs:
                entity = dialog.entity

                # Chat = regular groups, Channel = supergroups & channels
                if isinstance(entity, (Chat, Channel)):
                    if isinstance(entity, Channel):
                        group_type = "supergroup" if entity.megagroup else "channel"
                    else:
                        group_type = "group"

                    group_info = {
                        "telegram_id": entity.id,
                        "title": entity.title,
                        "username": getattr(entity, 'username', None),
                        "member_count": getattr(entity, 'participants_count', None),
                        "group_type": group_type,
                    }
                    groups.append(group_info)

            return groups
        except Exception as e:
            raise Exception(f"Failed to get user groups: {str(e)}")
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
