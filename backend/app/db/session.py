"""Database engine. Connects as the app role, which is subject to row-level security."""

from functools import lru_cache

from sqlalchemy import Engine, create_engine

from app.core.config import get_settings


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True)
