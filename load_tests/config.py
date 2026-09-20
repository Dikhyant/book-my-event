import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class LoadTestSettings(BaseSettings):
    BASE_URL: str = "http://localhost:8000"
    LOAD_TEST_USER_PASSWORD: str = "loadtestpassword123!"
    SUPABASE_URL: str = ""
    SUPABASE_ANON_KEY: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""
    LOAD_TEST_USER_PREFIX: str = "loadtest"
    DEFAULT_TIMEOUT: float = 30.0
    LOAD_TEST_USER_CREATION_CONCURRENCY: int = 5

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = LoadTestSettings()

LOAD_TESTS_DIR = Path(__file__).parent
TEST_USERS_FILE = LOAD_TESTS_DIR / "test_users.json"
