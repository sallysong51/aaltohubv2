"""
Configuration settings for AaltoHub v2 Backend
"""
import hmac
import logging
from enum import Enum
from urllib.parse import urlparse
from pydantic_settings import BaseSettings
from typing import Callable, List, Optional

_config_logger = logging.getLogger(__name__)


class Environment(str, Enum):
    """Environment types for configuration"""
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


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

    # Anthropic (AI Classification)
    ANTHROPIC_API_KEY: str = ""

    # Cookie settings (for httpOnly refresh token)
    COOKIE_DOMAIN: str = ""  # Set to your domain in production (e.g. "aaltohub.com")
    COOKIE_SECURE: bool = True  # Set to False for local development without HTTPS

    # Environment (normalized to lowercase)
    ENVIRONMENT: str = "development"

    # Logging
    LOG_LEVEL: str = "INFO"  # DEBUG, INFO, WARNING, ERROR, CRITICAL

    # ==================== Database Connection Pool ====================
    DB_POOL_MIN: int = 2  # Minimum connections in pool
    DB_POOL_MAX: int = 10  # Maximum connections in pool

    # ==================== Crawler Performance Settings ====================
    # Message Queue & Batch Processing
    MSG_QUEUE_MAXSIZE: int = 10000  # Max queued messages before backpressure
    BATCH_SIZE: int = 50  # Messages per batch INSERT
    BATCH_TIMEOUT: float = 2.0  # Seconds to wait before flushing partial batch

    # Historical Crawl
    HISTORICAL_CRAWL_DAYS: int = 14  # Days to fetch during historical crawl

    # Gap-Fill (Message Recovery)
    GAP_FILL_INTERVAL: int = 900  # Seconds between gap-fill runs (15 min)
    GAP_FILL_LOOKBACK_HOURS: int = 3  # Hours to re-check for missed messages
    GAP_FILL_MAX_MESSAGES: int = 2000  # Max messages per group during gap-fill

    # Media Downloads
    MEDIA_CONCURRENCY: int = 5  # Max parallel media downloads
    MEDIA_DOWNLOAD_BATCH: int = 50  # Media items per chunk (for progress tracking)
    MEDIA_DOWNLOAD_TIMEOUT: int = 30  # Seconds per media download

    # Telegram Client Connection Settings
    TELEGRAM_REQUEST_RETRIES: int = 5  # API request retry attempts
    TELEGRAM_CONNECTION_RETRIES: int = 10  # Connection retry attempts
    TELEGRAM_RETRY_DELAY: int = 2  # Seconds between retries
    TELEGRAM_TIMEOUT: int = 120  # Seconds for Telegram API calls
    TELEGRAM_FLOOD_SLEEP_THRESHOLD: int = 60  # Auto-wait if FloodWait ≤ this (seconds)

    # Crawler Reconnection
    RECONNECT_DELAY: int = 10  # Seconds to wait before reconnecting
    MAX_RECONNECT_ATTEMPTS: int = 10  # Max reconnection attempts

    # Caching
    ENABLED_CACHE_TTL: int = 60  # Seconds for enabled groups cache
    ENABLED_CACHE_MAX_SIZE: int = 1000  # Max cached entries before eviction

    # ==================== Monitoring ====================
    SENTRY_TRACES_SAMPLE_RATE: float = 0.1  # 10% of traces sent to Sentry

    def model_post_init(self, __context) -> None:
        # Normalize ENVIRONMENT to lowercase to avoid case-sensitivity issues
        object.__setattr__(self, "ENVIRONMENT", self.ENVIRONMENT.strip().lower())

        # Apply environment-specific configuration overrides
        self.configure_for_env()

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

    def configure_for_env(self) -> None:
        """Apply environment-specific configuration overrides.

        Development environment optimized for:
        - Fast iteration (smaller batches, shorter intervals)
        - Verbose logging (DEBUG level, 100% Sentry traces)
        - Lower resource usage (smaller DB pool, shorter crawl period)

        Production environment optimized for:
        - Efficiency (larger batches, longer intervals)
        - Lower overhead (INFO level, 10% Sentry traces)
        - Higher throughput (larger DB pool, full 14-day crawl)
        """
        if self.ENVIRONMENT == Environment.DEVELOPMENT:
            _config_logger.info("Applying DEVELOPMENT environment configuration overrides")
            # Database: smaller pool for local dev
            object.__setattr__(self, "DB_POOL_MIN", 1)
            object.__setattr__(self, "DB_POOL_MAX", 5)

            # Crawler: fast iteration for testing
            object.__setattr__(self, "BATCH_SIZE", 10)  # Smaller batches
            object.__setattr__(self, "BATCH_TIMEOUT", 1.0)  # Faster flush
            object.__setattr__(self, "GAP_FILL_INTERVAL", 300)  # 5 min (faster testing)
            object.__setattr__(self, "HISTORICAL_CRAWL_DAYS", 3)  # Only 3 days

            # Monitoring: verbose for debugging
            object.__setattr__(self, "SENTRY_TRACES_SAMPLE_RATE", 1.0)  # 100% traces
            if self.LOG_LEVEL == "INFO":  # Only override if not explicitly set
                object.__setattr__(self, "LOG_LEVEL", "DEBUG")

        elif self.ENVIRONMENT == Environment.PRODUCTION:
            _config_logger.info("Applying PRODUCTION environment configuration overrides")
            # Database: larger pool for concurrent requests
            object.__setattr__(self, "DB_POOL_MIN", 5)
            object.__setattr__(self, "DB_POOL_MAX", 20)

            # Crawler: efficiency optimized (use defaults from field definitions)
            # Monitoring: reduced overhead
            object.__setattr__(self, "SENTRY_TRACES_SAMPLE_RATE", 0.1)  # 10% traces

        elif self.ENVIRONMENT == Environment.STAGING:
            _config_logger.info("Applying STAGING environment configuration overrides")
            # Staging: production-like settings with more monitoring
            object.__setattr__(self, "DB_POOL_MIN", 3)
            object.__setattr__(self, "DB_POOL_MAX", 15)
            object.__setattr__(self, "SENTRY_TRACES_SAMPLE_RATE", 0.5)  # 50% traces

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

    @property
    def is_development(self) -> bool:
        """Check if running in development environment."""
        return self.ENVIRONMENT == "development"

    @property
    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.ENVIRONMENT == "production"

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"  # Ignore extra environment variables


# Global settings instance
settings = Settings()
