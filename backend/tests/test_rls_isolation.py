"""Tenancy isolation, against real Postgres, connected as the non-superuser app role."""

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from app.db import repo
from app.db import tables as t
from app.db.session import org_session
from app.ingest.loader import IngestSummary
from tests.conftest import ALPHA, BRAVO

ALL_TABLES = [
    t.ingest_files,
    t.evidence_records,
    t.charges,
    t.attachments,
    t.quarantined_rows,
    t.audit_events,
]


def test_ingest_loaded_expected_rows_per_org(loaded):
    a: IngestSummary = loaded[ALPHA]
    b: IngestSummary = loaded[BRAVO]
    assert (a.db_charges, b.db_charges) == (40, 21)
    assert a.db_records == 67 + 41 + 20 + 11
    assert b.db_records == 33 + 21 + 9 + 13
    assert a.quarantined == 0 and b.quarantined == 0


def test_ingest_is_idempotent(app_engine, loaded):
    from app.core.config import REPO_ROOT
    from app.ingest.loader import ingest_org
    from tests.conftest import SECRET

    data = REPO_ROOT / "data"
    again = ingest_org(app_engine, ALPHA, data / "fee_report_sample.csv", data / "upstream", SECRET)
    assert again.charges_inserted == 0
    assert all(ins == 0 for ins, _ in again.records.values())
    assert again.db_charges == 40


@pytest.mark.parametrize("table", ALL_TABLES, ids=lambda x: x.name)
def test_each_org_sees_only_its_own_rows_in_every_table(app_engine, loaded, table):
    for me, other in ((BRAVO, ALPHA), (ALPHA, BRAVO)):
        with org_session(app_engine, me) as s:
            total = repo.count_rows(s, table)
            foreign = s.execute(
                sa.select(sa.func.count())
                .select_from(table)
                .where(table.c.organization_id == other)
            ).scalar_one()
        assert total > 0, f"{me} should see its own rows in {table.name}"
        assert foreign == 0, f"{me} can read {foreign} {other} rows in {table.name}"


def test_bravo_cannot_fetch_alpha_record_by_id(app_engine, loaded):
    with org_session(app_engine, ALPHA) as s:
        assert repo.get_record(s, "RCV-0001") is not None  # UNIT-0001 is alpha
    with org_session(app_engine, BRAVO) as s:
        assert repo.get_record(s, "RCV-0001") is None


def test_bravo_cannot_fetch_alpha_attachment_by_key(app_engine, loaded):
    with org_session(app_engine, ALPHA) as s:
        key: str = s.execute(sa.select(t.attachments.c.key).limit(1)).scalar_one()
        assert repo.get_attachment(s, key) is not None
    with org_session(app_engine, BRAVO) as s:
        assert repo.get_attachment(s, key) is None


def test_attachment_keys_are_not_guessable(app_engine, loaded):
    with org_session(app_engine, ALPHA) as s:
        rows = s.execute(sa.select(t.attachments.c.key, t.attachments.c.source_path)).all()
    assert rows
    for key, path in rows:
        assert len(key) == 64 and int(key, 16) >= 0
        assert path not in key and "fixtures" not in key


def test_bravo_cannot_insert_a_row_tagged_alpha(app_engine, loaded):
    with pytest.raises(DBAPIError, match="row-level security"), org_session(app_engine, BRAVO) as s:
        s.execute(
            sa.insert(t.audit_events).values(organization_id=ALPHA, event_type="FORGED", payload={})
        )


def test_no_org_set_means_zero_rows(app_engine, loaded):
    with app_engine.begin() as conn:
        for table in ALL_TABLES:
            n = conn.execute(sa.select(sa.func.count()).select_from(table)).scalar_one()
            assert n == 0, f"{table.name} readable with no org set"


def test_org_session_rejects_empty_org(app_engine):
    with pytest.raises(ValueError), org_session(app_engine, "  "):
        pass


def test_app_role_cannot_update_or_delete_anything(app_engine, loaded):
    for table in ALL_TABLES:
        for stmt in (
            f"UPDATE {table.name} SET organization_id = organization_id",
            f"DELETE FROM {table.name}",
        ):
            with (
                pytest.raises(ProgrammingError, match="permission denied"),
                org_session(app_engine, ALPHA) as s,
            ):
                s.execute(text(stmt))


def test_every_table_has_rls_enabled_and_forced(owner_engine):
    with owner_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity "
                "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relname <> 'alembic_version'"
            )
        ).all()
    assert {r[0] for r in rows} == {tb.name for tb in ALL_TABLES}, "table without a test entry"
    for name, enabled, forced in rows:
        assert enabled, f"RLS not enabled on {name}"
        assert forced, f"RLS not forced on {name}"


def test_every_table_has_an_organization_scoped_policy(owner_engine):
    with owner_engine.connect() as conn:
        rows = conn.execute(
            text("SELECT tablename, qual, with_check FROM pg_policies WHERE schemaname = 'public'")
        ).all()
    assert {r[0] for r in rows} == {tb.name for tb in ALL_TABLES}
    for name, qual, with_check in rows:
        assert "app.current_org" in qual and "app.current_org" in with_check, name


def test_app_role_is_not_superuser_and_cannot_bypass_rls(app_engine: Engine):
    with app_engine.connect() as conn:
        is_super, bypass = conn.execute(
            text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
        ).one()
        who: str = conn.execute(text("SELECT current_user")).scalar_one()
    assert who == "alibi_app"
    assert not is_super and not bypass


def test_table_definitions_match_migrated_schema(owner_engine):
    insp = sa.inspect(owner_engine)
    for table in ALL_TABLES:
        db_cols = {c["name"] for c in insp.get_columns(table.name)}
        assert db_cols == {c.name for c in table.columns}, table.name
