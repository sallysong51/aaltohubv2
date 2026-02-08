"""
Supabase Auth client wrapper for server-side operations.

This module provides a high-level interface for creating and managing
Supabase Auth users from the backend. Uses the admin API to bypass
email verification requirements.
"""
import logging
from typing import Optional, Dict
import asyncio
from supabase import create_client, Client
from gotrue.errors import AuthApiError
from app.config import settings
from app.database import db

logger = logging.getLogger(__name__)


class SupabaseAuthManager:
    """Manage Supabase Auth operations from backend."""

    def __init__(self):
        self.client: Client = create_client(
            settings.SUPABASE_URL,
            settings.SUPABASE_SERVICE_ROLE_KEY
        )

    async def create_user(
        self,
        email: str,
        password: str,
        metadata: Optional[Dict] = None
    ) -> Dict:
        """Create a new Supabase Auth user (server-side, no email verification required).

        Args:
            email: User's email address
            password: User's password (min 8 chars enforced by Supabase)
            metadata: Optional user metadata (telegram_id, etc.)

        Returns:
            Dict with:
                - success: bool
                - user: dict (if success)
                - auth_user_id: str (if success)
                - error: str (if failure)
        """
        try:
            # Admin API: create user with auto-confirmed email
            response = await asyncio.to_thread(
                self.client.auth.admin.create_user,
                {
                    "email": email,
                    "password": password,
                    "email_confirm": True,  # Auto-confirm (we're admin)
                    "user_metadata": metadata or {}
                }
            )

            if not response or not response.user:
                return {"success": False, "error": "User creation failed"}

            logger.info(
                "Created Supabase Auth user: email=%s, auth_user_id=%s",
                email, response.user.id
            )

            return {
                "success": True,
                "user": response.user.model_dump() if hasattr(response.user, 'model_dump') else dict(response.user),
                "auth_user_id": response.user.id
            }

        except AuthApiError as e:
            logger.error("Supabase Auth create_user failed: %s", e)
            return {"success": False, "error": str(e.message)}
        except Exception as e:
            logger.error("Supabase Auth create_user unexpected error: %s", e)
            return {"success": False, "error": str(e)}

    async def link_telegram_to_auth_user(
        self,
        auth_user_id: str,
        telegram_user_id: int,
        public_user_id: int,
        session_encrypted: str,
        key_hash: str,
        phone_masked: Optional[str] = None,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None
    ) -> bool:
        """Create telegram_connections entry linking Telegram to Supabase Auth user.

        Args:
            auth_user_id: UUID from auth.users.id (as string)
            telegram_user_id: Telegram user ID (from Telethon)
            public_user_id: users.id (BIGSERIAL, used as AAD for encryption)
            session_encrypted: Encrypted Telethon session string
            key_hash: Encryption key hash
            phone_masked: Last 4 digits of phone (optional)
            username: Telegram username (optional)
            first_name: Telegram first name (optional)
            last_name: Telegram last name (optional)

        Returns:
            True if successful, False otherwise
        """
        try:
            # Check if entry already exists
            existing = await db.fetchrow(
                "SELECT id FROM telegram_connections WHERE telegram_user_id = $1",
                telegram_user_id
            )

            if existing:
                # Update existing entry instead of ignoring
                await db.execute(
                    """UPDATE telegram_connections
                       SET user_id = $1, auth_user_id = $2, session_encrypted = $3,
                           key_hash = $4, phone_masked = $5, username = $6,
                           first_name = $7, last_name = $8, updated_at = NOW()
                       WHERE telegram_user_id = $9""",
                    public_user_id, auth_user_id, session_encrypted, key_hash,
                    phone_masked, username, first_name, last_name, telegram_user_id
                )
                logger.info(
                    "Updated existing Telegram connection: telegram_id=%s, user_id=%s, auth_user_id=%s",
                    telegram_user_id, public_user_id, auth_user_id
                )
            else:
                # Insert new entry
                await db.execute(
                    """INSERT INTO telegram_connections
                       (user_id, auth_user_id, telegram_user_id, session_encrypted, key_hash,
                        phone_masked, username, first_name, last_name)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)""",
                    public_user_id, auth_user_id, telegram_user_id,
                    session_encrypted, key_hash,
                    phone_masked, username, first_name, last_name
                )
                logger.info(
                    "Created new Telegram connection: telegram_id=%s, user_id=%s, auth_user_id=%s",
                    telegram_user_id, public_user_id, auth_user_id
                )

            # Verify the entry was created/updated
            verify = await db.fetchrow(
                "SELECT user_id, auth_user_id FROM telegram_connections WHERE telegram_user_id = $1",
                telegram_user_id
            )
            if not verify:
                logger.error(
                    "Verification failed: telegram_connections entry not found after INSERT/UPDATE for telegram_id=%s",
                    telegram_user_id
                )
                return False

            return True

        except Exception as e:
            logger.error(
                "Failed to link Telegram to auth user: telegram_id=%s, user_id=%s, error=%s",
                telegram_user_id, public_user_id, e
            )
            return False

    async def get_user_by_email(self, email: str) -> Optional[Dict]:
        """Get Supabase Auth user by email (admin API).

        Args:
            email: Email address to lookup

        Returns:
            User dict if found, None otherwise
        """
        try:
            # Admin API: list users (no pagination, single query)
            response = await asyncio.to_thread(
                self.client.auth.admin.list_users
            )

            if not response:
                return None

            # Search for matching email
            for user in response:
                if user.email and user.email.lower() == email.lower():
                    return user.model_dump() if hasattr(user, 'model_dump') else dict(user)

            return None

        except Exception as e:
            logger.error("Failed to get user by email %s: %s", email, e)
            return None

    async def sign_in_with_password(
        self,
        email: str,
        password: str
    ) -> Dict:
        """Authenticate user with email/password.

        Args:
            email: User's email
            password: User's password

        Returns:
            Dict with:
                - success: bool
                - user: dict (if success)
                - session: dict (if success)
                - error: str (if failure)
        """
        try:
            response = await asyncio.to_thread(
                self.client.auth.sign_in_with_password,
                {"email": email, "password": password}
            )

            if not response or not response.user:
                return {"success": False, "error": "Authentication failed"}

            logger.info(
                "User signed in: email=%s, auth_user_id=%s",
                email, response.user.id
            )

            return {
                "success": True,
                "user": response.user.model_dump() if hasattr(response.user, 'model_dump') else dict(response.user),
                "session": response.session.model_dump() if hasattr(response.session, 'model_dump') else dict(response.session) if response.session else None
            }

        except AuthApiError as e:
            logger.warning("Sign in failed for %s: %s", email, e.message)
            return {"success": False, "error": str(e.message)}
        except Exception as e:
            logger.error("Sign in unexpected error for %s: %s", email, e)
            return {"success": False, "error": str(e)}


# Global instance
supabase_auth_manager = SupabaseAuthManager()
