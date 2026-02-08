"""
Configuration settings for AaltoHub v2 Backend
"""
import hmac
import logging
from urllib.parse import urlparse
from pydantic_settings import BaseSettings
from typing import Callable, List, Optional

_config_logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Application settings"""

    # Supabase
    SUPABASE_URL: str
    SUPABASE_SERVICE_ROLE_KEY: str  # Used as SUPABASE_KEY — kept for Storage uploads
    JWT_SECRET: str  # Used as SUPABASE_JWT_SECRET

    # Direct Postgres connection (asyncpg) — replaces PostgREST for all DB ops
    DATABASE_URL: str = ""

    # Crawler process API (Fix 2: process separation)
    CRAWLER_API_PORT: int = 8001
    CRAWLER_API_SECRET: str = ""  # defaults to JWT_SECRET if empty
    CRAWLER_API_URL: str = "http://127.0.0.1:8001"

    # Telegram API
    TELEGRAM_API_ID: int
    TELEGRAM_API_HASH: str

    # Admin credentials (must be set in .env)
    ADMIN_PHONE: str = ""
    ADMIN_USERNAME: str = ""

    # Encryption
    # ⚠️ CRITICAL: Do not change ENCRYPTION_KEY after deployment!
    # Changing it will break all existing Telegram sessions (users will need to re-login).
    # This key is permanent — treat it like JWT_SECRET.
    # If you must rotate: keep the old key and implement a migration strategy.
    ENCRYPTION_KEY: str  # Used as SESSION_ENCRYPTION_KEY

    # JWT
    # JWT_SECRET is already defined above
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # API
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    CORS_ORIGINS: str = "http://localhost:3000,https://aaltohub.com"

    # Sentry
    SENTRY_DSN: str = ""

    # Resend
    RESEND_API_KEY: str = ""

    # Environment (normalized to lowercase)
    ENVIRONMENT: str = "development"

    def model_post_init(self, __context) -> None:
        # Normalize ENVIRONMENT to lowercase to avoid case-sensitivity issues
        object.__setattr__(self, "ENVIRONMENT", self.ENVIRONMENT.strip().lower())
        # Validate critical secrets are sufficiently long
        if len(self.JWT_SECRET) < 32:
            _config_logger.warning("JWT_SECRET is shorter than 32 characters — weak secret")
        if len(self.ENCRYPTION_KEY) < 32:
            _config_logger.warning("ENCRYPTION_KEY is shorter than 32 characters — weak key")
        # Validate DATABASE_URL early with deep parsing
        if not self.DATABASE_URL:
            _config_logger.error(
                "DATABASE_URL is empty! Set it in backend/.env. "
                "Get from: Supabase Dashboard > Settings > Database > Connection string (URI)"
            )
        elif not self.DATABASE_URL.startswith(("postgresql://", "postgres://")):
            _config_logger.error(
                "DATABASE_URL has invalid scheme (expected postgresql:// or postgres://): %s...",
                self.DATABASE_URL[:20],
            )
        else:
            parsed = urlparse(self.DATABASE_URL)
            if not parsed.hostname:
                _config_logger.error("DATABASE_URL has no hostname — check URL format")
            elif ".." in parsed.hostname:
                _config_logger.error("DATABASE_URL hostname contains '..': %s", parsed.hostname)
            if parsed.port and not (1 <= parsed.port <= 65535):
                _config_logger.error("DATABASE_URL port out of range: %s", parsed.port)
            if not parsed.path or parsed.path == "/":
                _config_logger.warning("DATABASE_URL has no database name (path is empty or '/')")
            if not parsed.password or parsed.password in ("YOUR_DB_PASSWORD", "[YOUR-PASSWORD]", "YOUR-PASSWORD"):
                _config_logger.error(
                    "DATABASE_URL contains a placeholder password — replace with your actual Supabase DB password"
                )

    @property
    def crawler_api_secret(self) -> str:
        """Crawler API secret — defaults to JWT_SECRET if not explicitly set."""
        return self.CRAWLER_API_SECRET or self.JWT_SECRET

    @property
    def cors_origins_list(self) -> List[str]:
        """Parse CORS origins into a list"""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",")]

    @property
    def is_admin(self) -> Callable[..., bool]:
        """Check if user is admin (constant-time comparison to prevent timing attacks)"""
        def check(phone: Optional[str] = None, username: Optional[str] = None) -> bool:
            if phone and self.ADMIN_PHONE and hmac.compare_digest(phone, self.ADMIN_PHONE):
                return True
            if username and self.ADMIN_USERNAME and hmac.compare_digest(username, self.ADMIN_USERNAME):
                return True
            return False
        return check
    
    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"  # Ignore extra environment variables


# Global settings instance
settings = Settings()
