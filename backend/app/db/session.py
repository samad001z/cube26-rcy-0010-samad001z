"""Database engine and org-scoped sessions.

Every read or write goes through `org_session`, which sets the transaction-local
`app.current_org` setting that the row-level-security policies check. The engine
connects as the non-superuser app role, so RLS always applies.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session

from app.core.config import get_settings


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True)


@contextmanager
def org_session(engine: Engine, organization_id: str) -> Iterator[Session]:
    if not organization_id or not organization_id.strip():
        raise ValueError("organization_id is required")
    with Session(engine) as session, session.begin():
        session.execute(
            text("SELECT set_config('app.current_org', :org, true)"), {"org": organization_id}
        )
        yield session
