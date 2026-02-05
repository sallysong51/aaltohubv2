"""
Configuration settings for AaltoHub v2 Backend
"""
from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    """Application settings"""
    
    # Supabase
    SUPABASE_URL: str
    SUPABASE_SERVICE_ROLE_KEY: str  # Used as SUPABASE_KEY
    JWT_SECRET: str  # Used as SUPABASE_JWT_SECRET
    
    # Telegram API
    TELEGRAM_API_ID: int
    TELEGRAM_API_HASH: str
    
    # Admin credentials
    ADMIN_PHONE: str = "+358449598622"
    ADMIN_USERNAME: str = "chaeyeonsally"
    
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
    RESEND_API_KEY: str
    
    # Environment
    ENVIRONMENT: str = "development"
    
    @property
    def cors_origins_list(self) -> List[str]:
        """Parse CORS origins into a list"""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",")]
    
    @property
    def is_admin(self) -> callable:
        """Check if user is admin"""
        def check(phone: str = None, username: str = None) -> bool:
            if phone and phone == self.ADMIN_PHONE:
                return True
            if username and username == self.ADMIN_USERNAME:
                return True
            return False
        return check
    
    class Config:
        env_file = ".env"
        case_sensitive = True


# Global settings instance
settings = Settings()
