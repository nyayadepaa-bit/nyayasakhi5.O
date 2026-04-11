"""Application configuration loaded from environment variables."""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # ── App ───────────────────────────────────────────
    APP_NAME: str = "NyayaDepaaAI Auth"
    DEBUG: bool = False
    ALLOW_START_WITHOUT_DB: bool = True
    FRONTEND_URL: str = "http://localhost:5173"
    # Comma-separated extra origins for CORS (e.g. Vercel domains)
    ALLOWED_ORIGINS: str = ""

    # ── Database ──────────────────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://neondb_owner:npg_EvAn6UBPHTW5@ep-withered-scene-a1oimtu5-pooler.ap-southeast-1.aws.neon.tech/neondb?sslmode=require"
    # Connection pool tuning for ~150 concurrent users
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 30
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800  # recycle connections every 30 min

    # ── JWT ───────────────────────────────────────────
    JWT_SECRET_KEY: str = "717d633a27dde74c64967d38711a9fce"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ── Email (SMTP via Resend) ──────────────────────
    SMTP_HOST: str = "smtp.resend.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = "resend"
    SMTP_PASSWORD: str = "re_HBKHkANE_9ALyWLbW4zs3Z5VEFpk2qmNc"
    EMAIL_FROM: str = "noreply@NyayaDepaaAI.com"
    EMAIL_FROM_NAME: str = "NyayaDepaaAI"

    # ── Redis ─────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"
    CACHE_TTL: int = 60  # seconds

    # ── Rate Limiting ─────────────────────────────────
    RATE_LOGIN: str = "5/minute"
    RATE_SIGNUP: str = "3/minute"
    RATE_AI_QUERY: str = "20/minute"

    # ── Admin seed ────────────────────────────────────
    ADMIN_EMAIL: str = "nyayadepaa@gmail.com"
    ADMIN_PASSWORD: str = "Adminlogin@12345678"
    ADMIN_NAME: str = "System Admin"

    model_config = {"env_file": ".env", "extra": "ignore"}


@lru_cache()
def get_settings() -> Settings:
    return Settings()
