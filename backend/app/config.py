from functools import lru_cache

from pydantic_settings import BaseSettings


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

    # Rate limiting (requests per minute per IP)
    RATE_LIMIT_GENERAL: int = 100
    RATE_LIMIT_AUTH: int = 10
    RATE_LIMIT_WEBHOOKS: int = 200

    model_config = {"env_file": "../.env", "env_file_encoding": "utf-8", "extra": "ignore"}


@lru_cache()
def get_settings() -> Settings:
    return Settings()
