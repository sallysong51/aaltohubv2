"""
Shared pytest fixtures for AaltoHub v2 backend tests.
"""
import pytest
from unittest.mock import MagicMock, patch


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


@pytest.fixture()
def mock_settings():
    """Patch app.config.settings with safe test defaults.

    Also patches app.auth.settings so that auth functions pick up the
    fake values without importing the real Settings() (which reads .env).
    """
    fake = FakeSettings()
    with patch("app.config.settings", fake), \
         patch("app.auth.settings", fake):
        yield fake


@pytest.fixture()
def mock_db():
    """Return a MagicMock that stands in for the Supabase Client.

    The mock supports chaining like:
        db.table("x").select("*").eq("id", 1).execute()
    """
    db = MagicMock()
    with patch("app.database.get_db", return_value=db):
        yield db
