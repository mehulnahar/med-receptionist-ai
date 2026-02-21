import logging
import os
from functools import lru_cache

from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@db:5432/ai_receptionist"
    DATABASE_URL_SYNC: str = "postgresql+psycopg2://postgres:postgres@db:5432/ai_receptionist"
    JWT_SECRET: str = "change-me-in-production"
    JWT_EXPIRY_HOURS: int = 24
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:5173"
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    VAPI_API_KEY: str = ""
    VAPI_WEBHOOK_SECRET: str = ""
    STEDI_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    APP_URL: str = "http://localhost:8000"
    APP_ENV: str = "development"

    # Voice Stack (Phase 2)
    ANTHROPIC_API_KEY: str = ""
    CLAUDE_SONNET_MODEL: str = "claude-sonnet-4-5-20250929"
    CLAUDE_HAIKU_MODEL: str = "claude-haiku-4-5-20251001"
    WHISPER_ENDPOINT: str = ""
    WHISPER_MODEL_NAME: str = "whisper-medical-v1"
    CHATTERBOX_ENDPOINT: str = ""
    CHATTERBOX_VOICE_ID: str = "professional-warm"

    # PHI Encryption (Phase 1 - HIPAA)
    PHI_ENCRYPTION_BACKEND: str = "fernet"  # "fernet" or "kms"
    AWS_KMS_KEY_ID: str = ""
    AWS_REGION: str = "us-east-1"

    # EHR Integration (Phase 4)
    ATHENA_CLIENT_ID: str = ""
    ATHENA_CLIENT_SECRET: str = ""
    DRCHRONO_CLIENT_ID: str = ""
    DRCHRONO_CLIENT_SECRET: str = ""

    # Stripe Payments (Phase 6)
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""

    # Concurrent call limit (Phase 5)
    MAX_CONCURRENT_CALLS: int = 20

    # Rate limiting (requests per minute per IP)
    RATE_LIMIT_GENERAL: int = 100
    RATE_LIMIT_AUTH: int = 20
    RATE_LIMIT_WEBHOOKS: int = 200
    RATE_LIMIT_ADMIN: int = 30

    # Database connection pool (tune per environment via env vars)
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30

    model_config = {"env_file": "../.env", "env_file_encoding": "utf-8", "extra": "ignore"}


@lru_cache()
def get_settings() -> Settings:
    settings = Settings()

    # Fail loudly if JWT_SECRET is the insecure default in production
    if settings.APP_ENV == "production" and settings.JWT_SECRET == "change-me-in-production":
        raise RuntimeError(
            "FATAL: JWT_SECRET is still the default value. "
            "Set a strong random secret via environment variable before running in production. "
            "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(64))\""
        )

    if settings.APP_ENV == "production" and not settings.VAPI_WEBHOOK_SECRET:
        logger.warning(
            "WARNING: VAPI_WEBHOOK_SECRET is not set. "
            "Vapi webhook signature verification will be skipped."
        )

    # Reject wildcard CORS in production — allows CSRF attacks
    if settings.APP_ENV == "production":
        origins = [o.strip() for o in settings.CORS_ORIGINS.split(",")]
        if "*" in origins:
            raise RuntimeError(
                "FATAL: CORS_ORIGINS contains '*' which is not allowed in production. "
                "Set explicit allowed origins, e.g. CORS_ORIGINS=https://app.example.com"
            )

    # Warn about missing optional-but-important service keys
    if settings.APP_ENV == "production":
        if not settings.TWILIO_ACCOUNT_SID or not settings.TWILIO_AUTH_TOKEN:
            logger.warning(
                "TWILIO_ACCOUNT_SID/TWILIO_AUTH_TOKEN not set — "
                "SMS confirmations and reminders will be disabled."
            )
        if not settings.OPENAI_API_KEY:
            logger.warning(
                "OPENAI_API_KEY not set — feedback loop LLM analysis will be disabled."
            )
        if not settings.STEDI_API_KEY:
            logger.warning(
                "STEDI_API_KEY not set — insurance eligibility verification will fail "
                "unless practice-level keys are configured."
            )

    return settings


def clear_settings_cache() -> None:
    """Clear the cached Settings so the next call to ``get_settings()``
    re-reads environment variables.  Useful after rotating API keys
    without a full process restart.
    """
    get_settings.cache_clear()
