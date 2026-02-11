"""
Shared pytest fixtures for AaltoHub v2 backend tests.
"""
import asyncio
import sys
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

# Pre-mock heavy external dependencies not available in test env
for mod in ("telethon", "telethon.sessions", "telethon.errors",
            "telethon.tl", "telethon.tl.functions", "telethon.tl.functions.channels",
            "telethon.tl.types", "telethon.tl.functions.messages",
            "sentry_sdk", "sentry_sdk.integrations", "sentry_sdk.integrations.asyncio",
            "pythonjsonlogger", "pythonjsonlogger.json",
            "asyncpg", "supabase", "tenacity",
            "pydantic_settings", "pydantic", "pydantic.functional_validators",
            "jwt", "resend",
            "fastapi", "fastapi.security", "fastapi.responses",
            "starlette", "starlette.requests", "starlette.responses",
            "uvicorn", "httpx"):
    sys.modules.setdefault(mod, MagicMock())


class FakeSettings:
    """Test-safe settings that never touch real services."""
    SUPABASE_URL = "https://fake.supabase.co"
    SUPABASE_SERVICE_ROLE_KEY = "fake-service-role-key"
    JWT_SECRET = "test-jwt-secret-that-is-long-enough"
    JWT_ALGORITHM = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES = 60
    JWT_REFRESH_TOKEN_EXPIRE_DAYS = 30
    TELEGRAM_API_ID = 12345
    TELEGRAM_API_HASH = "test"
    ENCRYPTION_KEY = "a" * 32
    ENVIRONMENT = "testing"
    CORS_ORIGINS = "http://localhost:3000,https://aaltohub.com"
    API_HOST = "0.0.0.0"
    API_PORT = 8000
    ADMIN_PHONE = ""
    ADMIN_USERNAME = ""
    SENTRY_DSN = ""
    RESEND_API_KEY = ""
    CRAWLER_API_PORT = 8001
    COOKIE_DOMAIN = ""
    COOKIE_SECURE = False
    crawler_api_secret = "test-crawler-secret"
    is_production = False
    DATABASE_URL = "postgresql://test:test@localhost:5432/test"


@pytest.fixture()
def mock_settings():
    """Patch app.config.settings with safe test defaults."""
    fake = FakeSettings()
    with patch("app.config.settings", fake), \
         patch("app.auth.settings", fake):
        yield fake


@pytest.fixture()
def mock_db():
    """AsyncMock that mimics the asyncpg-based Database wrapper.

    Supports: fetch, fetchrow, fetchval, execute, is_connected
    """
    db = AsyncMock()
    db.is_connected = True
    db.fetch = AsyncMock(return_value=[])
    db.fetchrow = AsyncMock(return_value=None)
    db.fetchval = AsyncMock(return_value=None)
    db.execute = AsyncMock(return_value=None)
    with patch("app.database.db", db):
        yield db
