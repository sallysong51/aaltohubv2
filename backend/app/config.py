"""
Configuration settings for AaltoHub v2 Backend
"""
import hmac
import logging
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
