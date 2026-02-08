"""
Database connection layer — asyncpg for all DB operations.

supabase-py is kept ONLY for Supabase Storage uploads (live_crawler._upload_media).
All query/insert/update/delete operations go through asyncpg directly.

CRITICAL DATABASE_URL REQUIREMENTS:
- This app uses LISTEN/NOTIFY for SSE realtime events (see sse.py)
- LISTEN requires persistent connections across transactions
- You MUST use either:
  1. Session pooler (port 5432) — recommended for production
  2. Direct connection (port 5432) — works for dev/testing
- NEVER use Transaction pooler (port 6543) — it breaks LISTEN entirely

Supabase pooler options:
- Session: postgresql://postgres.PROJECT_REF:PASSWORD@aws-X-region.pooler.supabase.com:5432/postgres
- Direct:  postgresql://postgres:PASSWORD@db.PROJECT_REF.supabase.co:5432/postgres
"""
import logging
from typing import Any, Optional

import asyncpg
from supabase import create_client, Client
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.config import settings

logger = logging.getLogger(__name__)

# Transient errors that warrant a retry during pool creation
_TRANSIENT_ERRORS = (
    ConnectionError, TimeoutError, OSError,
    asyncpg.InternalServerError,
    asyncpg.PostgresConnectionError,
    asyncpg.InterfaceError,
)


class Database:
    """Async Postgres connection pool via asyncpg."""

    def __init__(self) -> None:
        self._pool: Optional[asyncpg.Pool] = None

    async def connect(self) -> None:
        """Create the connection pool. Call once at app startup."""
        if self._pool is not None:
            return
        dsn = settings.DATABASE_URL
        if not dsn:
            raise RuntimeError(
                "DATABASE_URL is not set. Get it from Supabase Dashboard > Settings > Database > Connection string."
            )
        try:
            self._pool = await asyncpg.create_pool(
                dsn=dsn,
                min_size=5,
                max_size=20,
                command_timeout=10,
                statement_cache_size=0,  # Must be 0 for pgbouncer/Supabase pooler compatibility
            )
            logger.info("asyncpg pool created (min=5, max=20)")
        except asyncpg.InternalServerError as e:
            if "Tenant or user not found" in str(e):
                raise RuntimeError(
                    f"Supabase connection rejected: {e}. "
                    "Possible causes: (1) project is PAUSED — wake it at https://app.supabase.com, "
                    "(2) DATABASE_URL has wrong project ref, "
                    "(3) wrong pooler endpoint."
                ) from e
            raise

    async def connect_with_retry(self) -> bool:
        """Connect with exponential backoff. Returns True on success, False on exhaustion."""
        @retry(
            stop=stop_after_attempt(5),
            wait=wait_exponential(multiplier=2, min=2, max=32),
            retry=retry_if_exception_type(_TRANSIENT_ERRORS),
            before_sleep=lambda rs: logger.warning(
                "[DB] Connection attempt %d failed, retrying in %.0fs: %s",
                rs.attempt_number, rs.next_action.sleep, rs.outcome.exception(),
            ),
        )
        async def _try_connect():
            # Reset pool so connect() actually attempts again
            self._pool = None
            await self.connect()

        try:
            await _try_connect()
            return True
        except Exception as e:
            logger.critical("[DB] All connection attempts exhausted: %s", e)
            return False

    async def close(self) -> None:
        """Close the connection pool. Call at app shutdown."""
        if self._pool:
            await self._pool.close()
            self._pool = None
            logger.info("asyncpg pool closed")

    @property
    def is_connected(self) -> bool:
        """Whether the connection pool is initialized and open."""
        return self._pool is not None and not self._pool._closed

    async def try_reconnect(self) -> bool:
        """Single reconnection attempt. Returns True on success, False on failure."""
        if self._pool is not None:
            return True
        try:
            await self.connect()
            logger.warning("[DB] Database connection recovered — exiting degraded mode")
            return True
        except Exception as e:
            logger.debug("[DB] Reconnection attempt failed: %s", e)
            return False

    def _ensure_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            logger.error("[DB] Pool access attempted while disconnected")
            raise RuntimeError("Database pool not initialized — call await db.connect() first")
        return self._pool

    async def fetch(self, query: str, *args: Any) -> list[asyncpg.Record]:
        """Execute a query and return all rows."""
        pool = self._ensure_pool()
        return await pool.fetch(query, *args)

    async def fetchrow(self, query: str, *args: Any) -> Optional[asyncpg.Record]:
        """Execute a query and return the first row (or None)."""
        pool = self._ensure_pool()
        return await pool.fetchrow(query, *args)

    async def fetchval(self, query: str, *args: Any) -> Any:
        """Execute a query and return the first column of the first row."""
        pool = self._ensure_pool()
        return await pool.fetchval(query, *args)

    async def execute(self, query: str, *args: Any) -> str:
        """Execute a statement (INSERT/UPDATE/DELETE). Returns status string."""
        pool = self._ensure_pool()
        return await pool.execute(query, *args)

    async def executemany(self, query: str, args: list) -> None:
        """Execute a statement for each set of args (batch insert/update)."""
        pool = self._ensure_pool()
        await pool.executemany(query, args)

    @property
    def pool(self) -> asyncpg.Pool:
        """Access the underlying pool (e.g. for explicit transactions)."""
        return self._ensure_pool()


# Global singleton — import and use everywhere
db = Database()


async def get_db() -> Database:
    """FastAPI dependency for route handlers."""
    return db


# Supabase client — kept ONLY for Storage uploads
_storage_client: Optional[Client] = None


def get_storage_client() -> Client:
    """Get the supabase-py client for Storage operations only."""
    global _storage_client
    if _storage_client is None:
        _storage_client = create_client(
            settings.SUPABASE_URL,
            settings.SUPABASE_SERVICE_ROLE_KEY,
        )
    return _storage_client
