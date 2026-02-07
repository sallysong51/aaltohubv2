"""
Unit tests for app.config — Settings validation and derived properties.
"""
import pytest
from app.config import Settings


def _make_settings(**overrides):
    """Create a Settings instance with required fields filled in.

    Uses _env_file=None to prevent pydantic-settings from reading the
    real .env file or environment variables, ensuring test isolation.
    """
    defaults = {
        "SUPABASE_URL": "https://fake.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": "fake-key",
        "JWT_SECRET": "test-secret",
        "TELEGRAM_API_ID": 12345,
        "TELEGRAM_API_HASH": "testhash",
        "ENCRYPTION_KEY": "a" * 32,
        "_env_file": None,
    }
    defaults.update(overrides)
    return Settings(**defaults)


# ------------------------------------------------------------------
# ENVIRONMENT normalisation
# ------------------------------------------------------------------

class TestEnvironmentNormalisation:
    def test_lowercase_passthrough(self):
        s = _make_settings(ENVIRONMENT="production")
        assert s.ENVIRONMENT == "production"

    def test_uppercase_normalised(self):
        s = _make_settings(ENVIRONMENT="PRODUCTION")
        assert s.ENVIRONMENT == "production"

    def test_mixed_case_normalised(self):
        s = _make_settings(ENVIRONMENT="Staging")
        assert s.ENVIRONMENT == "staging"

    def test_whitespace_stripped(self):
        s = _make_settings(ENVIRONMENT="  testing  ")
        assert s.ENVIRONMENT == "testing"

    def test_default_is_development(self, monkeypatch):
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        s = _make_settings()
        assert s.ENVIRONMENT == "development"


# ------------------------------------------------------------------
# CORS origins parsing
# ------------------------------------------------------------------

class TestCorsOrigins:
    def test_default_origins(self):
        s = _make_settings()
        origins = s.cors_origins_list
        assert "http://localhost:3000" in origins
        assert "https://aaltohub.com" in origins
        assert len(origins) == 2

    def test_custom_single_origin(self):
        s = _make_settings(CORS_ORIGINS="https://example.com")
        assert s.cors_origins_list == ["https://example.com"]

    def test_custom_multiple_origins(self):
        s = _make_settings(CORS_ORIGINS="https://a.com, https://b.com, https://c.com")
        origins = s.cors_origins_list
        assert origins == ["https://a.com", "https://b.com", "https://c.com"]

    def test_whitespace_trimmed(self):
        s = _make_settings(CORS_ORIGINS="  https://a.com  ,  https://b.com  ")
        origins = s.cors_origins_list
        assert origins == ["https://a.com", "https://b.com"]


# ------------------------------------------------------------------
# is_admin helper
# ------------------------------------------------------------------

class TestIsAdmin:
    def test_admin_by_phone(self):
        s = _make_settings(ADMIN_PHONE="+358123456789")
        assert s.is_admin(phone="+358123456789") is True
        assert s.is_admin(phone="+358000000000") is False

    def test_admin_by_username(self):
        s = _make_settings(ADMIN_USERNAME="admin_user")
        assert s.is_admin(username="admin_user") is True
        assert s.is_admin(username="other") is False

    def test_not_admin_when_empty(self):
        s = _make_settings()
        assert s.is_admin(phone="+358123456789") is False
        assert s.is_admin(username="anyone") is False
