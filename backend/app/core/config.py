"""Runtime settings, read from the environment and the repo-root .env (loaded automatically,
whatever the working directory). Environment variables win over .env."""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]
ENV_FILE = REPO_ROOT / ".env"


class SettingsError(RuntimeError):
    """A required setting is missing or invalid. The message is one line for the operator."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    # Connects as the non-superuser app role; row-level security applies.
    database_url: str
    # Connects as the table owner; used only by Alembic.
    migration_database_url: str
    # HMAC secret for attachment keys. Keys cannot be derived without it.
    attachment_key_secret: SecretStr
    llm_enabled: bool = False
    # API keys for POST /agent: `org_id:sha256hex,...` (hashes only; see app/api/auth.py).
    # Empty means no key is valid, so POST /agent answers 401 to everyone.
    alibi_api_keys: str = ""


def _one_line(exc: ValidationError) -> str:
    missing = [str(e["loc"][0]).upper() for e in exc.errors() if e["type"] == "missing"]
    if missing:
        return f"missing setting {', '.join(missing)}: copy .env.example to .env and fill it in"
    first = exc.errors()[0]
    return f"invalid setting {str(first['loc'][0]).upper()}: {first['msg']}"


@lru_cache
def get_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as exc:
        raise SettingsError(_one_line(exc)) from None
