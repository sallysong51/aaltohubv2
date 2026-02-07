"""
Database connection layer — asyncpg for all DB operations.

supabase-py is kept ONLY for Supabase Storage uploads (live_crawler._upload_media).
All query/insert/update/delete operations go through asyncpg directly.
"""
import logging
from typing import Any, Optional

import asyncpg
from supabase import create_client, Client

from app.config import settings

logger = logging.getLogger(__name__)


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
        self._pool = await asyncpg.create_pool(
            dsn=dsn,
            min_size=5,
            max_size=20,
            command_timeout=30,
            statement_cache_size=100,
        )
        logger.info("asyncpg pool created (min=5, max=20)")

    async def close(self) -> None:
        """Close the connection pool. Call at app shutdown."""
        if self._pool:
            await self._pool.close()
            self._pool = None
            logger.info("asyncpg pool closed")

    def _ensure_pool(self) -> asyncpg.Pool:
        if self._pool is None:
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
