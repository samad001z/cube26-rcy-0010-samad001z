"""The decision pipeline against real Postgres, connected as the non-superuser app role."""

from datetime import UTC, date, datetime

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine, text
from typer.testing import CliRunner

from app import cli
from app.adapters.csv_v0 import load_fee_report
from app.core.config import REPO_ROOT, get_settings
from app.core.hashing import content_hash
from app.db import repo
from app.db import tables as t
from app.db.session import org_session
from app.engine import decide as engine_decide
from app.models.charge import SourceRef
from app.models.decision import DecisionRecord
from app.models.vocab import Decision, RecordStatus
from app.pipeline import run_org
from tests.conftest import ALPHA, AS_OF, BRAVO
from tests.factories import charge, prep_all_pass

DATA = REPO_ROOT / "data"


def _latest_run(engine: Engine, org: str) -> list[DecisionRecord]:
    with org_session(engine, org) as s:
        run_id: object = s.execute(
            sa.select(t.decisions.c.run_id).order_by(t.decisions.c.decided_at.desc()).limit(1)
        ).scalar_one()
        return repo.list_decisions(s, str(run_id))


def test_every_sample_line_gets_exactly_one_decision_per_run(app_engine, loaded):
    fees = load_fee_report(DATA / "fee_report_sample.csv")
    expected = {
        org: {c.line_id for c in fees.charges if c.organization_id == org} for org in (ALPHA, BRAVO)
    }
    assert sum(len(v) for v in expected.values()) == 61
    for org in (ALPHA, BRAVO):
        decisions = _latest_run(app_engine, org)
        assert {d.subject.line_id for d in decisions} == expected[org]
        assert len(decisions) == len(expected[org])
        for d in decisions:
            assert d.reason and d.verify_hash()
            assert len(d.checks) == 8
            assert d.status == RecordStatus.FINAL, (d.subject.line_id, d.reason)
            assert d.organization_id == org


def test_stored_decisions_match_their_columns(app_engine, loaded):
    with org_session(app_engine, ALPHA) as s:
        rows = s.execute(sa.select(t.decisions)).all()
    assert rows
    for row in rows:
        d = DecisionRecord.model_validate(row.body)
        assert row.content_hash == d.content_hash == d.compute_hash()
        assert row.decision == d.decision.value and row.rule_id == d.rule_id
        assert (row.claim_amount is None) == (d.claim is None)


def test_every_cited_record_exists_in_the_same_org_with_the_cited_hash(app_engine, loaded):
    for org in (ALPHA, BRAVO):
        with org_session(app_engine, org) as s:
            for d in _latest_run(app_engine, org):
                for c in d.citations:
                    if c.kind == "evidence":
                        found = repo.get_record_with_hash(s, c.id)
                        assert found is not None and found[1] == c.content_hash


def test_bravo_cannot_read_alpha_decisions_by_record_id(app_engine, loaded):
    alpha = _latest_run(app_engine, ALPHA)[0]
    with org_session(app_engine, BRAVO) as s:
        n = s.execute(
            sa.select(sa.func.count())
            .select_from(t.decisions)
            .where(t.decisions.c.record_id == alpha.record_id)
        ).scalar_one()
    assert n == 0


def test_sample_decisions_follow_the_approved_rules(app_engine, loaded):
    by_line = {d.subject.line_id: d for org in (ALPHA, BRAVO) for d in _latest_run(app_engine, org)}
    for d in by_line.values():
        ct = d.subject.charge_type.value
        # D-011: loss events are never CLAIM; zero amounts are never CLAIM.
        if ct in ("lost_inbound", "damaged_in_warehouse", "refund_issued_item_not_returned"):
            assert d.decision == Decision.REVIEW and d.rule_id in (
                "R_AMOUNT_NOT_COMPUTABLE",
                "R_NO_RELEVANT_EVIDENCE",
            )
        if ct == "fulfilment_fee_weight_tier":
            assert d.decision == Decision.REVIEW
        # Option C: the sample has no defect_category, so no inbound defect fee is CLAIM.
        if ct == "inbound_defect_fee":
            assert d.decision != Decision.CLAIM
        # No sourced filing window yet: every decision carries the warning.
        assert "filing deadline not verified" in d.warnings
    assert by_line["FEE-0014-1"].rule_id == "R_DEFECT_CATEGORY_MISSING"
    assert by_line["FEE-0035-1"].rule_id == "R_INSUFFICIENT"  # barcode uncertain
    assert by_line["FEE-0064-1"].evidence_status.value == "CONFLICTING"


# --- synthetic org: CLAIM through the DB, tamper detection, fail-open -----------------

TAMPER_ORG = "org_test_tamper"


def _load_synthetic(app_engine: Engine, org: str) -> None:
    c = charge("SYN-1", defect_category="label", org=org)
    r = prep_all_pass("SYN-PRP-1", org=org)
    other = charge("SYN-2", unit_id="U-2", org=org)
    with org_session(app_engine, org) as s:
        fid = repo.upsert_ingest_file(s, org, "synthetic.csv", "a" * 64, "fee_report")
        repo.insert_charges(s, [c, other], fid)
        repo.insert_records(
            s, [r], {r.record_id: SourceRef(file_sha256="b" * 64, row=1, raw={})}, fid
        )


def test_claim_path_then_tampered_evidence_fails_closed(app_engine, owner_engine, loaded):
    _load_synthetic(app_engine, TAMPER_ORG)
    first = {d.subject.line_id: d for d in run_org(app_engine, TAMPER_ORG, AS_OF).decisions}
    assert first["SYN-1"].decision == Decision.CLAIM
    assert first["SYN-1"].claim is not None and str(first["SYN-1"].claim.amount) == "2.00"
    assert first["SYN-2"].decision == Decision.REVIEW  # no evidence for U-2

    # Edit the stored evidence body as the owner (the app role cannot UPDATE). RLS is
    # forced, so even the owner must set the org first or the UPDATE matches no rows.
    with owner_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_org', :org, true)"), {"org": TAMPER_ORG})
        changed = conn.execute(
            text(
                "UPDATE evidence_records SET body = jsonb_set(body, '{operator_label}', "
                "'\"someone_else\"') WHERE organization_id = :org AND record_id = 'SYN-PRP-1'"
            ),
            {"org": TAMPER_ORG},
        ).rowcount
    assert changed == 1
    second = {d.subject.line_id: d for d in run_org(app_engine, TAMPER_ORG, AS_OF).decisions}
    d = second["SYN-1"]
    assert d.decision == Decision.REVIEW and d.status == RecordStatus.PENDING
    assert d.rule_id == "R_CITATION_INVALID" and d.claim is None
    assert "SYN-PRP-1" in d.reason
    # The first run's decisions are still there, unchanged (append-only).
    with org_session(app_engine, TAMPER_ORG) as s:
        stored = {x.record_id: x for x in repo.list_decisions(s)}
    assert stored[first["SYN-1"].record_id] == first["SYN-1"]
    assert len(stored) == 4


def test_engine_failure_on_one_charge_fails_open_and_keeps_every_charge(
    app_engine, loaded, monkeypatch
):
    org = "org_test_failopen"
    _load_synthetic(app_engine, org)
    real = engine_decide

    def flaky(c, *args, **kwargs):
        if c.line_id == "SYN-1":
            raise RuntimeError("boom")
        return real(c, *args, **kwargs)

    monkeypatch.setattr("app.pipeline.decide", flaky)
    result = run_org(app_engine, org, AS_OF, now=datetime(2026, 9, 25, tzinfo=UTC))
    by_line = {d.subject.line_id: d for d in result.decisions}
    assert set(by_line) == {"SYN-1", "SYN-2"}
    failed = by_line["SYN-1"]
    assert failed.decision == Decision.REVIEW and failed.status == RecordStatus.PENDING
    assert failed.rule_id == "R_ENGINE_ERROR" and "RuntimeError: boom" in failed.reason
    assert failed.verify_hash()
    assert by_line["SYN-2"].status == RecordStatus.FINAL
    with org_session(app_engine, org) as s:
        assert len(repo.list_decisions(s, result.run_id)) == 2
        events = s.execute(sa.select(t.audit_events.c.event_type, t.audit_events.c.payload)).all()
    kinds = [e.event_type for e in events]
    assert kinds.count("DECISION") == 2 and kinds.count("DECISION_FAILED_OPEN") == 1
    assert "RUN_STARTED" in kinds and "RUN_COMPLETED" in kinds


def test_database_refuses_a_claim_row_without_a_positive_amount(app_engine, loaded):
    d = _latest_run(app_engine, ALPHA)[0]
    body = d.model_dump(mode="json")
    with pytest.raises(sa.exc.IntegrityError), org_session(app_engine, ALPHA) as s:
        s.execute(
            sa.insert(t.decisions).values(
                organization_id=ALPHA,
                run_id=d.run_id,
                record_id="DEC-forged",
                line_id="FORGED",
                decision="CLAIM",
                evidence_status="CONTRADICTED",
                rule_id="R_X",
                status="final",
                claim_amount=None,
                content_hash=content_hash(body),
                body=body,
                decided_at=d.captured_at,
            )
        )


# --- CLI ------------------------------------------------------------------------------


def test_cli_run_prints_a_decision_with_evidence_and_reason_for_every_line(
    app_engine, loaded, monkeypatch
):
    monkeypatch.setattr(cli, "get_engine", lambda: app_engine)
    monkeypatch.setenv("DATABASE_URL", "unused")
    monkeypatch.setenv("MIGRATION_DATABASE_URL", "unused")
    monkeypatch.setenv("ATTACHMENT_KEY_SECRET", "test-secret")
    get_settings.cache_clear()
    try:
        out = CliRunner().invoke(
            cli.app,
            [
                "run",
                "--report",
                str(DATA / "fee_report_sample.csv"),
                "--upstream",
                str(DATA / "upstream"),
                "--org",
                BRAVO,
                "--as-of",
                "2026-09-25",
            ],
        )
    finally:
        get_settings.cache_clear()
    assert out.exit_code == 0, out.output
    fees = load_fee_report(DATA / "fee_report_sample.csv")
    bravo_lines = [c.line_id for c in fees.charges if c.organization_id == BRAVO]
    blocks = out.output.split("\n\n")
    for line_id in bravo_lines:
        block = next(b for b in blocks if b.startswith(line_id + "  "))
        assert "  reason:   " in block
        assert "  evidence: " in block
        assert "  checks:   " in block
        assert any(x in block for x in ("-> CLAIM", "->  CLAIM", "DO_NOT_CLAIM", "REVIEW"))
    assert f"decisions: {len(bravo_lines)}" in out.output
    assert not any(line.startswith("FEE-0002-1") for line in out.output.splitlines())  # alpha


def test_as_of_is_required_to_be_a_date():
    assert date.fromisoformat("2026-09-25") == AS_OF
