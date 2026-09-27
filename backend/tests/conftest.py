import ipaddress
import os
import socket
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

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


# Installed at import time, not as a fixture: session-scoped fixtures below (migrated_db,
# loaded, ...) run before any function-scoped autouse fixture, so a guard applied only
# through `monkeypatch` in a fixture would leave that setup window unguarded (guardian
# finding 3). conftest.py is imported before any fixture or test runs, so this is active
# for the whole session, permanently, including any model call an early fixture might make.
#
# A loopback proxy (HTTP_PROXY=http://127.0.0.1:<port>) would otherwise let traffic to it
# through the loopback allowance and out to the real internet from there, so proxy env vars
# are cleared too. LLM_ENABLED and GOOGLE_APPLICATION_CREDENTIALS are forced off so a
# developer's or CI's own environment can never turn a test into a real model call.
_PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")
for _proxy_var in _PROXY_VARS:
    os.environ.pop(_proxy_var, None)
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"
os.environ["LLM_ENABLED"] = "false"
os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)


def _is_loopback(address: object) -> bool:
    if not isinstance(address, tuple) or not address:
        return False
    host = str(address[0])
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


def _guard(real: Any) -> Any:
    def inner(self: socket.socket, address: object) -> Any:
        if self.family in (socket.AF_INET, socket.AF_INET6) and not _is_loopback(address):
            raise RuntimeError(f"network access blocked in tests: {address!r}")
        return real(self, address)

    return inner


# psycopg connects through libpq, not Python sockets, so Postgres access (loopback only,
# per docker/postgres/init.sh) is unaffected either way.
socket.socket.connect = _guard(socket.socket.connect)  # type: ignore[method-assign]
socket.socket.connect_ex = _guard(socket.socket.connect_ex)  # type: ignore[method-assign]


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
    # One cached explanation per org through the real repo function, for the isolation
    # tests on llm_explanations (the pipeline only writes it when LLM_ENABLED).
    for org in (ALPHA, BRAVO):
        with org_session(app_engine, org) as session:
            repo.insert_cached_explanation(
                session,
                org,
                repo.CachedExplanation(
                    f"fixture-trace-{org}", "explain-v1", "fixture-model", "fixture text", 1, 1
                ),
                datetime(2026, 9, 25, 12, 0, tzinfo=UTC),
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
