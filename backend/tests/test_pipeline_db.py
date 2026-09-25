"""The decision pipeline against real Postgres, connected as the non-superuser app role."""

import re
from collections import Counter
from datetime import UTC, date, datetime

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine, text
from typer.testing import CliRunner

from app import cli, pipeline
from app.adapters.csv_v0 import load_fee_report
from app.claims.validator import validate
from app.core.config import REPO_ROOT, get_settings
from app.core.hashing import content_hash
from app.core.rules import load_engine_config
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
    checked = 0
    for org in (ALPHA, BRAVO):
        with org_session(app_engine, org) as s:
            for d in _latest_run(app_engine, org):
                for c in d.citations:
                    if c.kind == "evidence":
                        assert c.agent is not None
                        found = repo.get_record_with_hash(s, c.agent, c.id)
                        assert found is not None and found[1] == c.content_hash
                    else:
                        ch = repo.get_charge(s, c.id)
                        assert ch is not None and ch.compute_hash() == c.content_hash
                    checked += 1
    assert checked == 22  # snapshot: 9 on inbound defect fees + 13 on loss events


def test_bravo_cannot_read_alpha_decisions_by_record_id(app_engine, loaded):
    alpha = _latest_run(app_engine, ALPHA)[0]
    with org_session(app_engine, BRAVO) as s:
        n = s.execute(
            sa.select(sa.func.count())
            .select_from(t.decisions)
            .where(t.decisions.c.record_id == alpha.record_id)
        ).scalar_one()
    assert n == 0


LOSS_EVENT_RULES = {
    # D-016 / D-017: every rule a loss event may end on. Never CLAIM (D-011).
    "R_NO_RELEVANT_EVIDENCE": Decision.REVIEW,
    "R_EVIDENCE_OUTSIDE_WINDOW": Decision.REVIEW,
    "R_UNRESOLVED_UNIT": Decision.REVIEW,
    "R_FILING_WINDOW_NOT_OPEN": Decision.REVIEW,
    "R_CONFLICTING": Decision.REVIEW,
    "R_INSUFFICIENT": Decision.REVIEW,
    "R_AMOUNT_NOT_COMPUTABLE": Decision.REVIEW,
    "R_LOSS_DOUBTFUL": Decision.REVIEW,
    "R_RETURNED_INCOMPLETE_OR_DAMAGED": Decision.REVIEW,
    "R_ITEM_RETURNED": Decision.DO_NOT_CLAIM,
    "R_FILING_WINDOW_PASSED": Decision.DO_NOT_CLAIM,
}
# Charge types with no sourced filing deadline yet (D-017): these carry the warning.
UNSOURCED_WINDOW_TYPES = {"inbound_defect_fee", "fulfilment_fee_weight_tier", "lost_inbound"}


def test_sample_decisions_follow_the_approved_rules(app_engine, loaded):
    by_line = {d.subject.line_id: d for org in (ALPHA, BRAVO) for d in _latest_run(app_engine, org)}
    for d in by_line.values():
        ct = d.subject.charge_type.value
        # D-011, D-016: loss events are never CLAIM and end only on the approved rules.
        if ct in ("lost_inbound", "damaged_in_warehouse", "refund_issued_item_not_returned"):
            assert LOSS_EVENT_RULES.get(d.rule_id) == d.decision, (d.subject.line_id, d.rule_id)
        if ct == "fulfilment_fee_weight_tier":
            assert d.decision == Decision.REVIEW
        # Option C: the sample has no defect_category, so no inbound defect fee is CLAIM.
        if ct == "inbound_defect_fee":
            assert d.decision != Decision.CLAIM
        # Only types with no sourced deadline carry the warning (D-014, D-017).
        warned = "filing deadline not verified" in d.warnings
        assert warned == (ct in UNSOURCED_WINDOW_TYPES), d.subject.line_id
    assert by_line["FEE-0014-1"].rule_id == "R_DEFECT_CATEGORY_MISSING"
    assert by_line["FEE-0035-1"].rule_id == "R_INSUFFICIENT"  # barcode uncertain
    assert by_line["FEE-0064-1"].evidence_status.value == "CONTRADICTED"  # later sighting

    def pinned(line: str) -> tuple[str, str, str, str | None]:
        d = by_line[line]
        code = d.reason_code.value if d.reason_code else None
        return d.decision.value, d.evidence_status.value, d.rule_id, code

    # Lost inbound: prep, then a customer return after the loss (D-016).
    assert pinned("FEE-0014-2") == ("REVIEW", "CONTRADICTED", "R_LOSS_DOUBTFUL", None)
    assert "loss is doubtful" in by_line["FEE-0014-2"].reason
    # Lost inbound: prep only, no later record.
    assert pinned("FEE-0031-1") == ("REVIEW", "SUPPORTED", "R_AMOUNT_NOT_COMPUTABLE", None)
    # Refund, item returned: parts missing / damaged / condition uncertain.
    for line in ("FEE-0038-2", "FEE-0041-2", "FEE-0014-4"):
        assert pinned(line) == (
            "REVIEW",
            "CONTRADICTED",
            "R_RETURNED_INCOMPLETE_OR_DAMAGED",
            None,
        ), line
        assert "possible separate claim" in by_line[line].reason
    # Refund, item returned complete: nothing owed for a non-return.
    assert pinned("FEE-0048-2") == ("DO_NOT_CLAIM", "CONTRADICTED", "R_ITEM_RETURNED", None)
    # Damaged in warehouse: sourced 60-day deadline passed (Q3 / D-016).
    assert pinned("FEE-0071-2") == (
        "DO_NOT_CLAIM",
        "SUPPORTED",
        "R_FILING_WINDOW_PASSED",
        "FILING_WINDOW_EXPIRED",
    )
    assert (
        "computed from the posted date as a proxy for the date the item was reported lost or "
        "damaged" in by_line["FEE-0071-2"].reason
    )


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
            s, [r], {(r.agent, r.record_id): SourceRef(file_sha256="b" * 64, row=1, raw={})}, fid
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
    assert failed.reason_code is not None and failed.reason_code.value == "ENGINE_ERROR"
    assert failed.verify_hash()
    assert by_line["SYN-2"].status == RecordStatus.FINAL
    with org_session(app_engine, org) as s:
        assert len(repo.list_decisions(s, result.run_id)) == 2
        events = s.execute(sa.select(t.audit_events.c.event_type, t.audit_events.c.payload)).all()
    kinds = [e.event_type for e in events]
    assert kinds.count("DECISION") == 2 and kinds.count("DECISION_FAILED_OPEN") == 1
    assert "RUN_STARTED" in kinds and "RUN_COMPLETED" in kinds


def _forged_row(d: DecisionRecord, decision: str, amount: str | None) -> dict[str, object]:
    body = d.model_dump(mode="json")
    return dict(
        organization_id=ALPHA,
        run_id=d.run_id,
        record_id=f"DEC-forged-{decision}",
        line_id="FORGED",
        decision=decision,
        evidence_status="CONTRADICTED",
        rule_id="R_X",
        status="final",
        claim_amount=amount,
        content_hash=content_hash(body),
        body=body,
        decided_at=d.captured_at,
    )


@pytest.mark.parametrize(
    ("decision", "amount"), [("CLAIM", None), ("CLAIM", "0.00"), ("REVIEW", "1.00")]
)
def test_database_refuses_claim_amount_inconsistent_with_decision(
    app_engine, loaded, decision, amount
):
    d = _latest_run(app_engine, ALPHA)[0]
    with (
        pytest.raises(sa.exc.IntegrityError, match="ck_decisions_claim_amount"),
        org_session(app_engine, ALPHA) as s,
    ):
        s.execute(sa.insert(t.decisions).values(**_forged_row(d, decision, amount)))


def test_duplicate_charge_claim_cites_canonical_charge_read_back_from_postgres(app_engine, loaded):
    org = "org_test_duplicate"
    first = charge("DUP-1", org=org, posted=date(2026, 7, 1))
    second = charge("DUP-2", org=org, posted=date(2026, 7, 5))
    with org_session(app_engine, org) as s:
        fid = repo.upsert_ingest_file(s, org, "dup.csv", "c" * 64, "fee_report")
        repo.insert_charges(s, [first, second], fid)
    by_line = {d.subject.line_id: d for d in run_org(app_engine, org, AS_OF).decisions}
    d = by_line["DUP-2"]
    assert d.decision == Decision.CLAIM and d.status == RecordStatus.FINAL
    assert d.reason_code is not None and d.reason_code.value == "DUPLICATE_CHARGE"
    assert [(c.kind, c.id, c.role) for c in d.citations] == [
        ("charge", "DUP-1", "canonical_charge")
    ]
    assert by_line["DUP-1"].decision == Decision.REVIEW  # the canonical line has no evidence


def test_citation_of_another_orgs_record_is_not_found_under_rls(app_engine, loaded):
    alpha_claim = next(
        d for d in _latest_run(app_engine, ALPHA) if any(c.kind == "evidence" for c in d.citations)
    )
    with org_session(app_engine, ALPHA) as s:
        alpha_charge = repo.get_charge(s, alpha_claim.subject.line_id)
    assert alpha_charge is not None
    # Validate the alpha decision from a bravo session: every alpha row is invisible.
    with org_session(app_engine, BRAVO) as s:
        errors = validate(alpha_claim, alpha_charge, pipeline.DbLookup(s), load_engine_config())
    cited = [c.id for c in alpha_claim.citations if c.kind == "evidence"]
    assert f"cited record {cited[0]} not found" in errors
    assert "charge belongs to another organisation" not in errors  # same org as decision
    assert any("not found in the store" in e for e in errors)


# --- CLI ------------------------------------------------------------------------------


def _invoke_cli(app_engine, monkeypatch, *args: str):
    monkeypatch.setattr(cli, "get_engine", lambda: app_engine)
    monkeypatch.setenv("DATABASE_URL", "unused")
    monkeypatch.setenv("MIGRATION_DATABASE_URL", "unused")
    monkeypatch.setenv("ATTACHMENT_KEY_SECRET", "test-secret")
    get_settings.cache_clear()
    try:
        return CliRunner().invoke(cli.app, list(args))
    finally:
        get_settings.cache_clear()


RUN_ARGS = (
    "run",
    "--report",
    str(DATA / "fee_report_sample.csv"),
    "--upstream",
    str(DATA / "upstream"),
)


@pytest.mark.parametrize("org", [ALPHA, BRAVO])
def test_cli_prints_every_line_matching_the_stored_decision_with_evidence_and_reason(
    app_engine, loaded, monkeypatch, org
):
    out = _invoke_cli(app_engine, monkeypatch, *RUN_ARGS, "--org", org, "--as-of", "2026-09-25")
    assert out.exit_code == 0, out.output
    run_id = re.search(r"  run ([0-9a-f-]{36})  ", out.output)
    assert run_id is not None
    with org_session(app_engine, org) as s:
        stored = {d.subject.line_id: d for d in repo.list_decisions(s, run_id.group(1))}
    fees = load_fee_report(DATA / "fee_report_sample.csv")
    expected = {c.line_id for c in fees.charges if c.organization_id == org}
    assert set(stored) == expected

    blocks = {b.split("  ", 1)[0]: b for b in out.output.split("\n\n") if b.startswith("FEE-")}
    assert set(blocks) == expected  # one printed block per line, no other org's lines
    for line_id, d in stored.items():
        block = blocks[line_id]
        head = block.splitlines()[0]
        assert f"->  {d.decision.value} ({d.evidence_status.value})  {d.rule_id}" in head
        assert f"  reason:   {d.reason}" in block
        if d.citations:
            for c in d.citations:
                short = c.content_hash[:12]
                assert f"  evidence: {c.kind} {c.id} (sha256:{short}) {c.role}" in block
        else:
            assert "  evidence: none cited" in block
        for r in d.evidence_considered:
            assert r.record_id in block
        assert (
            "  checks:   " + " ".join(f"{c.check_key}={c.verdict.value}" for c in d.checks) in block
        )
        assert f"  record:   {d.record_id}" in block
    assert f"decisions: {len(expected)}  " in out.output


def test_cli_rejects_a_bad_as_of_date(app_engine, loaded, monkeypatch):
    out = _invoke_cli(app_engine, monkeypatch, *RUN_ARGS, "--org", ALPHA, "--as-of", "25/09/2026")
    assert out.exit_code == 2
    assert "YYYY-MM-DD" in out.output


# --- regression snapshot --------------------------------------------------------------

# REGRESSION CHECK ONLY. NOT GROUND TRUTH. EXCLUDED FROM EVAL METRICS.
# These are the rule counts the engine produced on the synthetic sample CSVs on 2026-09-25,
# approved by the human lead as a regression check. They say nothing about whether the
# decisions are right: correctness is measured only by the held-out, human-labelled eval
# set (Day 3). The eval harness must never read this table. Any change must be explained
# and re-approved by the human lead.
# Re-approved 2026-09-25 after D-016 (loss-event mapping) and D-017 (sourced windows).
SAMPLE_RULE_COUNTS = {
    ALPHA: {
        "R_NO_RELEVANT_EVIDENCE": 25,
        "R_DEFECT_CATEGORY_MISSING": 6,
        "R_RETURNED_INCOMPLETE_OR_DAMAGED": 3,
        "R_AMOUNT_NOT_COMPUTABLE": 2,
        "R_LOSS_DOUBTFUL": 2,
        "R_INSUFFICIENT": 1,
        "R_FILING_WINDOW_PASSED": 1,
    },
    BRAVO: {
        "R_NO_RELEVANT_EVIDENCE": 17,
        "R_DEFECT_CATEGORY_MISSING": 1,
        "R_INSUFFICIENT": 1,
        "R_LOSS_DOUBTFUL": 1,
        "R_ITEM_RETURNED": 1,
    },
}
SAMPLE_DO_NOT_CLAIM = {ALPHA: {"FEE-0071-2"}, BRAVO: {"FEE-0048-2"}}


@pytest.mark.parametrize("org", [ALPHA, BRAVO])
def test_regression_snapshot_sample(app_engine, loaded, org):
    """Regression check on the sample; not ground truth, not an eval metric."""
    decisions = _latest_run(app_engine, org)
    assert dict(Counter(d.rule_id for d in decisions)) == SAMPLE_RULE_COUNTS[org]
    assert not any(d.decision == Decision.CLAIM for d in decisions)  # 0 CLAIM on the sample
    dnc = {d.subject.line_id for d in decisions if d.decision == Decision.DO_NOT_CLAIM}
    assert dnc == SAMPLE_DO_NOT_CLAIM[org]


def test_precheck_failure_fails_open_for_every_charge(app_engine, loaded, monkeypatch):
    org = "org_test_precheck_fail"
    _load_synthetic(app_engine, org)

    def broken(*args, **kwargs):
        raise ValueError("bad rules")

    monkeypatch.setattr("app.pipeline.run_prechecks", broken)
    result = run_org(app_engine, org, AS_OF)
    assert {d.subject.line_id for d in result.decisions} == {"SYN-1", "SYN-2"}
    for d in result.decisions:
        assert d.status == RecordStatus.PENDING and d.rule_id == "R_ENGINE_ERROR"
        assert d.reason_code is not None and d.reason_code.value == "ENGINE_ERROR"
        assert "ValueError: bad rules" in d.reason
    with org_session(app_engine, org) as s:
        assert len(repo.list_decisions(s, result.run_id)) == 2


def test_dependency_failure_is_model_unavailable(app_engine, loaded, monkeypatch):
    org = "org_test_dependency_fail"
    _load_synthetic(app_engine, org)

    def db_down(*args, **kwargs):
        raise sa.exc.OperationalError("SELECT 1", {}, Exception("connection lost"))

    monkeypatch.setattr("app.pipeline.decide", db_down)
    result = run_org(app_engine, org, AS_OF)
    for d in result.decisions:
        assert d.status == RecordStatus.PENDING and d.decision == Decision.REVIEW
        assert d.reason_code is not None and d.reason_code.value == "DEPENDENCY_UNAVAILABLE"


def test_run_reports_latency_for_every_charge(app_engine, loaded):
    org = "org_test_latency"
    _load_synthetic(app_engine, org)
    result = run_org(app_engine, org, AS_OF)
    assert set(result.latency_ms) == {d.subject.line_id for d in result.decisions}
    assert all(ms > 0 for ms in result.latency_ms.values())


def test_run_refuses_a_custody_window_that_closes_before_the_filing_window(app_engine, loaded):
    import yaml

    from app.core.rules import ENGINE_PATH, parse_engine_config

    data = yaml.safe_load(ENGINE_PATH.read_text())
    data["charge_types"]["refund_issued_item_not_returned"]["pods"]["returns"]["max_days_after"] = (
        60
    )
    with pytest.raises(ValueError, match="before the sourced filing window closes"):
        run_org(app_engine, ALPHA, AS_OF, cfg=parse_engine_config(data))
