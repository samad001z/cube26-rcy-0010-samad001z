import os
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text

from alembic import command
from app.adapters.csv_v0 import Quarantined
from app.core.config import REPO_ROOT
from app.db import repo
from app.db.session import org_session
from app.ingest.loader import IngestSummary, ingest_org
from app.models.vocab import Decision
from app.pipeline import run_org
from app.review import OverrideRequest, apply_override

BACKEND = Path(__file__).resolve().parents[1]
SECRET = "test-secret"
ALPHA = "org_demo_alpha"
BRAVO = "org_demo_bravo"
AS_OF = date(2026, 9, 25)


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.fail(f"{name} is not set; run tests via `make test` (see Makefile)")
    return value


@pytest.fixture(scope="session")
def migrated_db() -> str:
    """Recreate the public schema on the test database and migrate it as the owner role."""
    mig_url = _env("TEST_MIGRATION_DATABASE_URL")
    owner = create_engine(mig_url, isolation_level="AUTOCOMMIT")
    with owner.connect() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public AUTHORIZATION alibi_owner"))
        conn.execute(text("REVOKE ALL ON SCHEMA public FROM PUBLIC"))
        conn.execute(text("GRANT USAGE ON SCHEMA public TO alibi_app"))
    owner.dispose()
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    cfg.set_main_option("sqlalchemy.url", mig_url.replace("%", "%%"))
    command.upgrade(cfg, "head")
    return mig_url


@pytest.fixture(scope="session")
def owner_engine(migrated_db: str) -> Iterator[Engine]:
    engine = create_engine(migrated_db)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def app_engine(migrated_db: str) -> Iterator[Engine]:
    engine = create_engine(_env("TEST_DATABASE_URL"))
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def loaded(app_engine: Engine) -> dict[str, IngestSummary]:
    """Both orgs ingested from the sample files through the real adapter and repo."""
    data = REPO_ROOT / "data"
    summaries = {
        org: ingest_org(app_engine, org, data / "fee_report_sample.csv", data / "upstream", SECRET)
        for org in (ALPHA, BRAVO)
    }
    # The sample files quarantine nothing, so give each org one quarantined row through the
    # real repo function; otherwise the isolation test on that table would read zero rows.
    for org in (ALPHA, BRAVO):
        with org_session(app_engine, org) as session:
            repo.insert_quarantined(
                session, org, [Quarantined("bad.csv", 1, "unmapped value 'x'", {"line_id": "X"})]
            )
    # Decide every charge through the real pipeline so the decisions table has rows per org.
    # One human override per org through the real review code, so decision_overrides has
    # rows per org for the isolation tests.
    for org in (ALPHA, BRAVO):
        result = run_org(app_engine, org, AS_OF)
        target = next(d for d in result.decisions if d.decision == Decision.REVIEW)
        with org_session(app_engine, org) as session:
            apply_override(
                session,
                org,
                target.record_id,
                OverrideRequest(
                    new_decision=Decision.DO_NOT_CLAIM,
                    reason="fixture: reviewer judged the fee correct",
                    reviewer="fixture",
                ),
                datetime(2026, 9, 25, 12, 0, tzinfo=UTC),
            )
    return summaries
