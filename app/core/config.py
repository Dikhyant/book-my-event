from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str
    jwt_secret: str = "change-me"
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_jwt_secret: str = ""
    redis_url: str = "redis://localhost:6379/0"
    resend_api_key: str = ""
    email_from: str = ""

    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout: int = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()
