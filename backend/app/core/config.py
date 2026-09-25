"""Runtime settings, read from the environment (and the repo-root .env in development)."""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Connects as the non-superuser app role; row-level security applies.
    database_url: str
    # Connects as the table owner; used only by Alembic.
    migration_database_url: str
    # HMAC secret for attachment keys. Keys cannot be derived without it.
    attachment_key_secret: SecretStr
    llm_enabled: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
