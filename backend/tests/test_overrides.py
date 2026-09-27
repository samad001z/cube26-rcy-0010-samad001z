"""Human overrides (D-021) against real Postgres as the non-superuser app role: overrides
are data, the engine's decision row is never changed, a human CLAIM respects rule 9, the
history is a verifiable chain, and the database refuses what the code would refuse."""

import threading
import time
import uuid
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.db import repo
from app.db import tables as t
from app.db.session import org_session
from app.models.charge import SourceRef
from app.models.contract import Check
from app.models.decision import DecisionRecord
from app.models.vocab import ChargeType, Decision, RecordStatus, ReportType, Verdict
from app.pipeline import run_org
from app.review import (
    OverrideError,
    OverrideRequest,
    apply_override,
    check_chain,
    effective_record,
)
from tests.conftest import ALPHA, AS_OF, BRAVO
from tests.factories import charge, prep_all_pass

AT = datetime(2026, 9, 26, 10, 0, tzinfo=UTC)


def _org() -> str:
    return f"org_test_ovr_{uuid.uuid4().hex[:8]}"


def _setup(app_engine: Engine, org: str) -> dict[str, DecisionRecord]:
    """SYN-1: CLAIM 2.00 (label defect, prep evidence). SYN-2: REVIEW (no evidence)."""
    c = charge("SYN-1", defect_category="label", org=org)
    other = charge("SYN-2", unit_id="U-2", org=org)
    r = prep_all_pass("SYN-PRP-1", org=org)
    with org_session(app_engine, org) as s:
        fid = repo.upsert_ingest_file(s, org, "synthetic.csv", uuid.uuid4().hex * 2, "fee_report")
        repo.insert_charges(s, [c, other], fid)
        repo.insert_records(
            s, [r], {(r.agent, r.record_id): SourceRef(file_sha256="b" * 64, row=1, raw={})}, fid
        )
    decided = run_org(app_engine, org, AS_OF).decisions
    by_line = {d.subject.line_id: d for d in decided}
    assert by_line["SYN-1"].decision == Decision.CLAIM
    assert by_line["SYN-2"].decision == Decision.REVIEW
    return by_line


def _req(
    new: Decision, reason: str = "checked the photos myself", who: str = "asha"
) -> OverrideRequest:
    return OverrideRequest(new_decision=new, reason=reason, reviewer=who)


def _override(engine: Engine, org: str, record_id: str, req: OverrideRequest, at: datetime = AT):
    with org_session(engine, org) as s:
        return apply_override(s, org, record_id, req, at)


def test_override_is_stored_and_the_engine_row_is_unchanged(app_engine, loaded):
    org = _org()
    d = _setup(app_engine, org)["SYN-2"]
    rec, eff = _override(app_engine, org, d.record_id, _req(Decision.DO_NOT_CLAIM))
    assert rec.sequence == 1 and rec.verify_hash()
    assert rec.override.original_decision == "REVIEW"
    assert rec.override.new_decision == "DO_NOT_CLAIM"
    assert rec.engine_record_hash == d.content_hash and rec.previous_override_hash is None
    assert eff.decision == Decision.DO_NOT_CLAIM and eff.status == RecordStatus.OVERRIDDEN
    assert eff.outcome.decided_by == "human:asha" and eff.outcome.decided_at == AT
    assert eff.overrides[0].reason == "checked the photos myself"
    assert eff.verify_hash() and eff.content_hash != d.content_hash
    # Rule-level fields stay the engine's: the reviewer changed the outcome, not the trace.
    assert (eff.rule_id, eff.reason, eff.citations) == (d.rule_id, d.reason, d.citations)
    # Guardian finding 5: the effective record's own explanation and model_version, not the
    # engine's (a human DO NOT CLAIM must never show text starting with the engine's REVIEW).
    assert eff.model_version is None
    assert eff.explanation is not None
    assert eff.explanation.text.startswith("DO_NOT_CLAIM.")
    assert eff.explanation.source == "template"
    assert "asha" in eff.explanation.text
    with org_session(app_engine, org) as s:
        stored = repo.get_decision(s, d.record_id)
        events: Sequence[Any] = (
            s.execute(
                sa.select(t.audit_events.c.payload).where(
                    t.audit_events.c.event_type == "DECISION_OVERRIDDEN"
                )
            )
            .scalars()
            .all()
        )
    assert stored == d and stored is not None and stored.verify_hash()
    assert len(events) == 1 and events[0]["reviewer"] == "asha"
    assert events[0]["content_hash"] == rec.content_hash


def test_override_that_changes_nothing_is_refused(app_engine, loaded):
    org = _org()
    d = _setup(app_engine, org)["SYN-2"]
    with pytest.raises(OverrideError, match="already REVIEW") as err:
        _override(app_engine, org, d.record_id, _req(Decision.REVIEW))
    assert err.value.status == 409
    with org_session(app_engine, org) as s:
        assert repo.list_overrides(s, d.record_id) == []


def test_human_claim_is_the_charge_minus_reimbursed_never_more(app_engine, loaded):
    org = _org()
    d = _setup(app_engine, org)["SYN-2"]
    _, eff = _override(app_engine, org, d.record_id, _req(Decision.CLAIM))
    assert eff.claim is not None
    assert eff.claim.amount == d.amount_charged - d.amount_reimbursed
    assert Decimal("0") < eff.claim.amount <= d.amount_charged
    assert any("human override by asha" in line for line in eff.claim.computation)
    with org_session(app_engine, org) as s:
        row: Decimal = s.execute(sa.select(t.decision_overrides.c.claim_amount)).scalar_one()
    assert row == eff.claim.amount


def test_claiming_an_already_reimbursed_charge_is_refused(app_engine, loaded):
    org = _org()
    d = _setup(app_engine, org)["SYN-2"]
    # Store a copy of the decision whose charge was fully reimbursed, as the engine would.
    paid = d.model_copy(
        update={"record_id": f"{d.record_id}-paid", "amount_reimbursed": d.amount_charged}
    ).with_hash()
    with org_session(app_engine, org) as s:
        repo.insert_decision(s, paid.model_copy(update={"run_id": str(uuid.uuid4())}).with_hash())
    with pytest.raises(OverrideError, match="nothing left to claim"):
        _override(app_engine, org, paid.record_id, _req(Decision.CLAIM))


def test_pending_record_cannot_be_claimed_but_can_be_closed(app_engine, loaded, monkeypatch):
    org = _org()
    real = __import__("app.engine", fromlist=["decide"]).decide

    def boom(c, *a, **k):
        if c.line_id == "SYN-2":
            raise RuntimeError("engine down")
        return real(c, *a, **k)

    monkeypatch.setattr("app.pipeline.decide", boom)
    d = _setup(app_engine, org)["SYN-2"]
    assert d.status == RecordStatus.PENDING
    with pytest.raises(OverrideError, match="pending") as err:
        _override(app_engine, org, d.record_id, _req(Decision.CLAIM))
    assert err.value.status == 409
    _, eff = _override(app_engine, org, d.record_id, _req(Decision.DO_NOT_CLAIM))
    assert eff.decision == Decision.DO_NOT_CLAIM and eff.claim is None


def test_overriding_a_claim_drops_the_claim_amount(app_engine, loaded):
    org = _org()
    d = _setup(app_engine, org)["SYN-1"]
    _, eff = _override(app_engine, org, d.record_id, _req(Decision.DO_NOT_CLAIM))
    assert eff.claim is None and eff.decision == Decision.DO_NOT_CLAIM


def test_second_override_chains_to_the_first(app_engine, loaded):
    org = _org()
    d = _setup(app_engine, org)["SYN-2"]
    first, _ = _override(app_engine, org, d.record_id, _req(Decision.DO_NOT_CLAIM))
    second, eff = _override(
        app_engine, org, d.record_id, _req(Decision.CLAIM, "new photo from the warehouse", "ravi")
    )
    assert second.sequence == 2
    assert second.override.original_decision == "DO_NOT_CLAIM"
    assert second.previous_override_hash == first.content_hash
    assert eff.decision == Decision.CLAIM and eff.outcome.decided_by == "human:ravi"
    assert [o.reviewer for o in eff.overrides] == ["asha", "ravi"]
    with org_session(app_engine, org) as s:
        assert check_chain(d, repo.list_overrides(s, d.record_id)) == []


def test_edited_override_history_is_detected_and_blocks_new_overrides(
    app_engine, owner_engine, loaded
):
    org = _org()
    d = _setup(app_engine, org)["SYN-2"]
    _override(app_engine, org, d.record_id, _req(Decision.DO_NOT_CLAIM))
    # Rewrite the stored reason as the owner (the app role cannot UPDATE).
    with owner_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_org', :org, true)"), {"org": org})
        changed = conn.execute(
            text(
                "UPDATE decision_overrides SET body = jsonb_set(body, '{override,reason}', "
                "'\"edited later\"') WHERE organization_id = :org"
            ),
            {"org": org},
        ).rowcount
    assert changed == 1
    with org_session(app_engine, org) as s:
        problems = check_chain(d, repo.list_overrides(s, d.record_id))
    assert problems and "content hash does not verify" in problems[0]
    with pytest.raises(OverrideError, match="does not verify") as err:
        _override(app_engine, org, d.record_id, _req(Decision.CLAIM))
    assert err.value.status == 409


def test_other_org_cannot_override_or_see_the_override(app_engine, loaded):
    with org_session(app_engine, ALPHA) as s:
        alpha_ids = [d.record_id for d in repo.list_decisions(s)]
    with pytest.raises(OverrideError) as err:
        _override(app_engine, BRAVO, alpha_ids[0], _req(Decision.DO_NOT_CLAIM))
    assert err.value.status == 404
    with org_session(app_engine, BRAVO) as s:
        assert repo.list_overrides(s, alpha_ids[0]) == []
        assert repo.overrides_by_record(s, alpha_ids) == {}


def test_concurrent_overrides_from_the_same_start_do_not_both_apply(
    app_engine, loaded, monkeypatch
):
    org = _org()
    d = _setup(app_engine, org)["SYN-2"]
    outcomes: list[str] = []
    barrier = threading.Barrier(2)
    real_list = repo.list_overrides

    def slow_list(session, record_id):  # widen the read-then-write gap so the race is real
        found = real_list(session, record_id)
        time.sleep(0.4)
        return found

    monkeypatch.setattr("app.review.repo.list_overrides", slow_list)

    def worker(who: str) -> None:
        barrier.wait()
        try:
            _override(app_engine, org, d.record_id, _req(Decision.DO_NOT_CLAIM, who=who))
            outcomes.append("ok")
        except OverrideError as exc:
            outcomes.append(f"refused {exc.status}")
        except Exception as exc:  # e.g. a unique violation when both read the same start
            outcomes.append(f"error {type(exc).__name__}")

    threads = [threading.Thread(target=worker, args=(w,)) for w in ("asha", "ravi")]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert sorted(outcomes) == ["ok", "refused 409"]
    with org_session(app_engine, org) as s:
        assert len(repo.list_overrides(s, d.record_id)) == 1


@pytest.mark.parametrize(
    "reason, reviewer",
    [("", "asha"), ("  ", "asha"), ("ok", "asha"), ("fine reason", ""), ("fine reason", "a;drop")],
)
def test_empty_reason_or_bad_reviewer_is_refused(reason, reviewer):
    with pytest.raises(ValidationError):
        OverrideRequest(new_decision=Decision.CLAIM, reason=reason, reviewer=reviewer)


def test_effective_record_without_overrides_is_the_engine_record(app_engine, loaded):
    with org_session(app_engine, ALPHA) as s:
        d = repo.list_decisions(s)[0]
    assert effective_record(d, []) is d


# --- the database refuses what the code refuses ----------------------------------------


def _raw_insert(engine: Engine, org: str, record_id: str, **over: object) -> None:
    values: dict[str, object] = {
        "organization_id": org,
        "decision_record_id": record_id,
        "line_id": "SYN-2",
        "sequence": 1,
        "original_decision": "REVIEW",
        "new_decision": "DO_NOT_CLAIM",
        "claim_amount": None,
        "reason": "raw insert",
        "reviewer": "asha",
        "at": AT,
        "content_hash": "x",
        "body": {},
    }
    values.update(over)
    with org_session(engine, org) as s:
        s.execute(sa.insert(t.decision_overrides).values(**values))


@pytest.mark.parametrize(
    "over, constraint",
    [
        ({"new_decision": "REVIEW"}, "ck_overrides_changes"),  # changes nothing
        ({"new_decision": "CLAIM"}, "ck_overrides_claim_amount"),  # CLAIM without an amount
        (
            {"new_decision": "DO_NOT_CLAIM", "claim_amount": Decimal("1.00")},
            "ck_overrides_claim_amount",
        ),  # amount on non-claim
        ({"new_decision": "CLAIM", "claim_amount": Decimal("0.00")}, "ck_overrides_claim_amount"),
        ({"reason": "   "}, "ck_overrides_reason"),
        ({"reason": "\t\n "}, "ck_overrides_reason"),
        ({"reviewer": ""}, "ck_overrides_reviewer"),
        ({"sequence": 0}, "ck_overrides_sequence"),
        ({"new_decision": "MAYBE"}, "ck_overrides_new"),
        # must point at a stored decision
        ({"decision_record_id": "DEC-does-not-exist"}, "fk_overrides_decision"),
    ],
)
def test_database_constraints_refuse_bad_override_rows(app_engine, loaded, over, constraint):
    org = _org()
    d = _setup(app_engine, org)["SYN-2"]
    with pytest.raises((IntegrityError, DBAPIError), match=constraint):
        _raw_insert(app_engine, org, d.record_id, **over)


def test_database_refuses_two_overrides_with_the_same_sequence(app_engine, loaded):
    org = _org()
    d = _setup(app_engine, org)["SYN-2"]
    _raw_insert(app_engine, org, d.record_id)
    with pytest.raises(IntegrityError):
        _raw_insert(app_engine, org, d.record_id, new_decision="CLAIM", claim_amount="1.00")


def test_override_cannot_point_at_another_orgs_decision(app_engine, loaded):
    with org_session(app_engine, ALPHA) as s:
        alpha_id = repo.list_decisions(s)[0].record_id
    # The foreign key is (organization_id, record_id): a bravo row naming an alpha decision
    # has no matching decision in bravo.
    with pytest.raises(IntegrityError):
        _raw_insert(app_engine, BRAVO, alpha_id)


# --- a human CLAIM goes through the same guards as the engine's (rules-guardian review) ---


def _store_variant(engine: Engine, org: str, d: DecisionRecord, **update: Any) -> DecisionRecord:
    """Store a copy of `d` as the newest decision of its line (a later run), changed as the
    engine would have written it for another situation."""
    v = d.model_copy(
        update={"record_id": f"{d.record_id}-v{uuid.uuid4().hex[:6]}", "run_id": str(uuid.uuid4())}
        | update
    ).with_hash()
    with org_session(engine, org) as s:
        repo.insert_decision(s, v)
    return v


def _with_check(
    d: DecisionRecord, key: str, verdict: str | None, detail: str | None
) -> list[Check]:
    if verdict is None:  # the check is missing from the record altogether
        return [c for c in d.checks if c.check_key != key]
    return [
        c.model_copy(update={"verdict": Verdict(verdict), "detail": detail})
        if c.check_key == key
        else c
        for c in d.checks
    ]


def test_sample_loss_event_past_its_deadline_cannot_be_claimed(app_engine, loaded):
    """Reproduces the review finding: FEE-0071-2 (damaged in warehouse, a reimbursement the
    channel paid, filing window passed) was accepted as a 14.00 USD human CLAIM."""
    with org_session(app_engine, ALPHA) as s:
        d = repo.list_decisions_for_line(s, "FEE-0071-2")[-1]
        before = len(repo.list_overrides(s, d.record_id))
    assert d.decision == Decision.DO_NOT_CLAIM
    with pytest.raises(OverrideError, match="loss event is never CLAIM") as err:
        _override(app_engine, ALPHA, d.record_id, _req(Decision.CLAIM))
    assert err.value.status == 409
    with org_session(app_engine, ALPHA) as s:
        assert len(repo.list_overrides(s, d.record_id)) == before


@pytest.mark.parametrize(
    "variant, refusal",
    [
        ({"charge_type": ChargeType.LOST_INBOUND}, "loss event is never CLAIM"),
        # rules-guardian H1: a weight-tier fee is owed only the overcharge, not the fee
        ({"charge_type": ChargeType.FULFILMENT_FEE_WEIGHT_TIER}, "fee_difference"),
        (
            ("amount_computable", "FAIL", "needs an unsourced fee schedule"),
            "could not be worked out",
        ),
        ({"report_type": ReportType.REIMBURSEMENT_REPORT}, "refund of a fee"),
        (("within_filing_window", "FAIL", "deadline 2026-01-01 passed"), "filing window"),
        (("within_filing_window", None, None), "filing window does not allow a claim: not"),
        (("within_filing_window", "FAIL", "not yet eligible"), "filing window"),
        (("not_already_reimbursed", "UNCERTAIN", "refund may belong to FEE-9"), "not settled"),
        (("not_already_reimbursed", "FAIL", "fully reimbursed"), "not settled"),
    ],
)
def test_human_claim_is_refused_when_the_engine_could_not_settle_what_is_owed(
    app_engine, loaded, variant, refusal
):
    org = _org()
    d = _setup(app_engine, org)["SYN-2"]
    if isinstance(variant, dict):
        v = _store_variant(app_engine, org, d, subject=d.subject.model_copy(update=variant))
    else:
        v = _store_variant(app_engine, org, d, checks=_with_check(d, *variant))
    with pytest.raises(OverrideError, match=refusal) as err:
        _override(app_engine, org, v.record_id, _req(Decision.CLAIM))
    assert err.value.status == 409
    # Closing the line is still possible: only CLAIM is guarded.
    _, eff = _override(app_engine, org, v.record_id, _req(Decision.DO_NOT_CLAIM))
    assert eff.decision == Decision.DO_NOT_CLAIM
    with org_session(app_engine, org) as s:
        assert [o.override.new_decision for o in repo.list_overrides(s, v.record_id)] == [
            "DO_NOT_CLAIM"
        ]


def test_human_claim_rechecks_reimbursements_in_the_store(app_engine, loaded):
    """The decision says 0.50 was reimbursed but no refund line in the store backs it (or a
    refund arrived after the run): the reimbursements are re-matched now and the CLAIM is
    refused until the charge is re-run (rules-guardian H2)."""
    org = _org()
    d = _setup(app_engine, org)["SYN-2"]
    v = _store_variant(app_engine, org, d, amount_reimbursed=Decimal("0.50"))
    with pytest.raises(OverrideError, match=r"store now shows 0\.00 USD reimbursed") as err:
        _override(app_engine, org, v.record_id, _req(Decision.CLAIM))
    assert err.value.status == 409
    with org_session(app_engine, org) as s:
        assert repo.list_overrides(s, v.record_id) == []


def test_refund_ingested_after_the_run_blocks_a_human_claim(app_engine, loaded):
    org = _org()
    d = _setup(app_engine, org)["SYN-2"]
    refund = charge("SYN-R", unit_id="U-2", org=org, report_type=ReportType.REIMBURSEMENT_REPORT)
    with org_session(app_engine, org) as s:
        fid = repo.upsert_ingest_file(s, org, "refunds.csv", uuid.uuid4().hex * 2, "fee_report")
        repo.insert_charges(s, [refund], fid)
    with pytest.raises(OverrideError, match="re-run the charge") as err:
        _override(app_engine, org, d.record_id, _req(Decision.CLAIM))
    assert err.value.status == 409
    _, eff = _override(app_engine, org, d.record_id, _req(Decision.DO_NOT_CLAIM))
    assert eff.decision == Decision.DO_NOT_CLAIM


def test_refund_that_could_belong_to_two_fees_blocks_a_human_claim(app_engine, loaded):
    """After the run, a second fee on the same unit and one refund arrive: the refund could
    belong to either fee, so nothing is allocated (reimbursed stays 0.00, as decided) and
    only the ambiguity check stops a CLAIM of the full fee."""
    org = _org()
    d = _setup(app_engine, org)["SYN-2"]
    later_fee = charge("SYN-3", unit_id="U-2", org=org, amount="3.00")
    refund = charge("SYN-R", unit_id="U-2", org=org, report_type=ReportType.REIMBURSEMENT_REPORT)
    with org_session(app_engine, org) as s:
        fid = repo.upsert_ingest_file(s, org, "later.csv", uuid.uuid4().hex * 2, "fee_report")
        repo.insert_charges(s, [later_fee, refund], fid)
    with pytest.raises(OverrideError, match="SYN-R could now belong to this fee") as err:
        _override(app_engine, org, d.record_id, _req(Decision.CLAIM))
    assert err.value.status == 409


def test_filing_window_is_judged_on_the_override_day(app_engine, loaded, monkeypatch):
    """A window open at the run's as-of date but closed on the day of the override."""
    org = _org()
    d = _setup(app_engine, org)["SYN-2"]
    real = __import__("app.review", fromlist=["run_prechecks"]).run_prechecks

    def closed_today(charges, rules, cfg, today):
        out = real(charges, rules, cfg, today)
        pre = out[d.subject.line_id]
        out[d.subject.line_id] = replace(
            pre, filing=replace(pre.filing, verdict=Verdict.FAIL, detail="deadline passed")
        )
        return out

    monkeypatch.setattr("app.review.run_prechecks", closed_today)
    with pytest.raises(OverrideError, match="does not allow a claim today: deadline passed"):
        _override(app_engine, org, d.record_id, _req(Decision.CLAIM))


def test_human_claim_goes_through_the_citation_validator(app_engine, loaded):
    """Everything claim_refusal checks is fine, but the decision's subject hash no longer
    matches the stored charge: the validator, re-reading the store, refuses the CLAIM."""
    org = _org()
    d = _setup(app_engine, org)["SYN-2"]
    v = _store_variant(
        app_engine,
        org,
        d,
        subject=d.subject.model_copy(update={"charge_content_hash": "0" * 64}),
    )
    with pytest.raises(OverrideError, match="does not validate: charge SYN-2 hash") as err:
        _override(app_engine, org, v.record_id, _req(Decision.CLAIM))
    assert err.value.status == 409
    with org_session(app_engine, org) as s:
        assert repo.list_overrides(s, v.record_id) == []


def test_only_the_newest_decision_of_a_line_can_be_overridden(app_engine, loaded):
    org = _org()
    old = _setup(app_engine, org)["SYN-2"]
    new = {d.subject.line_id: d for d in run_org(app_engine, org, AS_OF).decisions}["SYN-2"]
    with pytest.raises(OverrideError, match="newer run") as err:
        _override(app_engine, org, old.record_id, _req(Decision.DO_NOT_CLAIM))
    assert err.value.status == 409
    _, eff = _override(app_engine, org, new.record_id, _req(Decision.DO_NOT_CLAIM))
    assert eff.decision == Decision.DO_NOT_CLAIM


# --- history: kept, ordered, and every tampering is visible (test-guardian review) -------


def test_three_overrides_keep_the_full_ordered_history(app_engine, owner_engine, loaded):
    org = _org()
    d = _setup(app_engine, org)["SYN-2"]
    steps = [(Decision.DO_NOT_CLAIM, "asha"), (Decision.CLAIM, "ravi"), (Decision.REVIEW, "meera")]
    for new, who in steps:
        _override(app_engine, org, d.record_id, _req(new, f"step by {who}", who))
    # Re-insert the rows in reverse order as the owner: order must come from `sequence`.
    with owner_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_org', :org, true)"), {"org": org})
        rows = (
            conn.execute(
                sa.select(t.decision_overrides).where(t.decision_overrides.c.organization_id == org)
            )
            .mappings()
            .all()
        )
        conn.execute(
            sa.delete(t.decision_overrides).where(t.decision_overrides.c.organization_id == org)
        )
        for r in sorted(rows, key=lambda r: -r["sequence"]):
            conn.execute(sa.insert(t.decision_overrides).values(**dict(r)))
    with org_session(app_engine, org) as s:
        history = repo.list_overrides(s, d.record_id)
    assert [o.sequence for o in history] == [1, 2, 3]
    assert [o.override.reviewer for o in history] == ["asha", "ravi", "meera"]
    assert [o.override.original_decision for o in history] == ["REVIEW", "DO_NOT_CLAIM", "CLAIM"]
    assert [o.previous_override_hash for o in history] == [
        None,
        history[0].content_hash,
        history[1].content_hash,
    ]
    assert check_chain(d, history) == []
    eff = effective_record(d, history)
    assert eff.decision == Decision.REVIEW and eff.claim is None
    assert [o.reason for o in eff.overrides] == ["step by asha", "step by ravi", "step by meera"]


def _decision_row(owner_engine: Engine, org: str, record_id: str) -> tuple[dict[str, Any], int]:
    with owner_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_org', :org, true)"), {"org": org})
        row = dict(
            conn.execute(sa.select(t.decisions).where(t.decisions.c.record_id == record_id))
            .mappings()
            .one()
        )
        n = conn.execute(sa.select(sa.func.count()).select_from(t.decisions)).scalar_one()
    return row, n


def test_overriding_never_edits_the_engine_decision_row(app_engine, owner_engine, loaded):
    """Every column of the stored decision row, read as the owner, is identical after two
    overrides (one of them a CLAIM), and no decision row was added or removed."""
    org = _org()
    d = _setup(app_engine, org)["SYN-2"]
    before, n_before = _decision_row(owner_engine, org, d.record_id)
    _override(app_engine, org, d.record_id, _req(Decision.CLAIM))
    _override(app_engine, org, d.record_id, _req(Decision.DO_NOT_CLAIM, who="ravi"))
    after, n_after = _decision_row(owner_engine, org, d.record_id)
    assert after == before and n_after == n_before
    assert before["decision"] == "REVIEW" and before["content_hash"] == d.content_hash


def test_a_column_changed_without_its_body_is_detected(app_engine, owner_engine, loaded):
    org = _org()
    d = _setup(app_engine, org)["SYN-2"]
    _override(app_engine, org, d.record_id, _req(Decision.DO_NOT_CLAIM))
    with owner_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_org', :org, true)"), {"org": org})
        conn.execute(
            text("UPDATE decision_overrides SET reason = 'edited' WHERE organization_id = :o"),
            {"o": org},
        )
    with org_session(app_engine, org) as s:
        assert repo.override_column_problems(s, d.record_id) == [
            "override 1: stored columns do not match its body"
        ]
    with pytest.raises(OverrideError, match="stored columns do not match"):
        _override(app_engine, org, d.record_id, _req(Decision.CLAIM))


def test_a_rehashed_claim_above_the_cap_is_detected(app_engine, owner_engine, loaded):
    """Someone who can write rows recomputes the (unkeyed) hash with a bigger claim: the
    chain check recomputes the cap from the engine record and reports it."""
    org = _org()
    d = _setup(app_engine, org)["SYN-2"]
    rec, _ = _override(app_engine, org, d.record_id, _req(Decision.CLAIM))
    assert rec.claim is not None
    forged = rec.model_copy(
        update={"claim": rec.claim.model_copy(update={"amount": Decimal("999.00")})}
    ).with_hash()
    with owner_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_org', :org, true)"), {"org": org})
        conn.execute(
            sa.update(t.decision_overrides)
            .where(t.decision_overrides.c.organization_id == org)
            .values(
                body=forged.model_dump(mode="json"),
                content_hash=forged.content_hash,
                claim_amount=Decimal("999.00"),
            )
        )
    with org_session(app_engine, org) as s:
        stored = repo.list_overrides(s, d.record_id)
        assert repo.override_column_problems(s, d.record_id) == []
    assert stored[0].verify_hash()
    problems = check_chain(d, stored)
    assert len(problems) == 1 and "is not the charge not yet reimbursed" in problems[0]


def test_sample_weight_tier_fee_cannot_be_claimed_in_full(app_engine, loaded):
    """rules-guardian H1 on the sample: FEE-0002-1 (weight-tier, 4.25) is owed only the
    difference to the correct fee, which no sourced schedule gives."""
    with org_session(app_engine, ALPHA) as s:
        d = repo.list_decisions_for_line(s, "FEE-0002-1")[-1]
    with pytest.raises(OverrideError, match="fee_difference") as err:
        _override(app_engine, ALPHA, d.record_id, _req(Decision.CLAIM))
    assert err.value.status == 409


# --- chain checks and audit payload (test-guardian second review) -----------------------


def test_check_chain_catches_claim_on_the_wrong_decision_and_wrong_currency(app_engine, loaded):
    org = _org()
    d = _setup(app_engine, org)["SYN-2"]
    rec, _ = _override(app_engine, org, d.record_id, _req(Decision.CLAIM))
    assert rec.claim is not None
    dnc_with_claim = rec.model_copy(
        update={"override": rec.override.model_copy(update={"new_decision": "DO_NOT_CLAIM"})}
    ).with_hash()
    assert check_chain(d, [dnc_with_claim]) == [
        "override 1: claim amount does not match its decision"
    ]
    claim_without = rec.model_copy(update={"claim": None}).with_hash()
    assert check_chain(d, [claim_without]) == [
        "override 1: claim amount does not match its decision"
    ]
    eur = rec.model_copy(
        update={"claim": rec.claim.model_copy(update={"currency": "EUR"})}
    ).with_hash()
    problems = check_chain(d, [eur])
    assert len(problems) == 1 and "is not the charge not yet reimbursed" in problems[0]


def test_audit_event_carries_reason_and_the_previous_override_hash(app_engine, loaded):
    org = _org()
    d = _setup(app_engine, org)["SYN-2"]
    first, _ = _override(app_engine, org, d.record_id, _req(Decision.DO_NOT_CLAIM, "first why"))
    second, _ = _override(app_engine, org, d.record_id, _req(Decision.REVIEW, "second why"))
    with org_session(app_engine, org) as s:
        events: Sequence[Any] = (
            s.execute(
                sa.select(t.audit_events.c.payload)
                .where(t.audit_events.c.event_type == "DECISION_OVERRIDDEN")
                .order_by(t.audit_events.c.at)
            )
            .scalars()
            .all()
        )
    assert [(e["reason"], e["previous_override_hash"], e["content_hash"]) for e in events] == [
        ("first why", None, first.content_hash),
        ("second why", first.content_hash, second.content_hash),
    ]


@pytest.mark.parametrize(
    "values",
    [
        {"sequence": 7},
        {"original_decision": "CLAIM"},
        # the database refuses new == original, so swap both (the body says REVIEW -> DNC)
        {"original_decision": "DO_NOT_CLAIM", "new_decision": "REVIEW"},
        {"reason": "edited"},
        {"reviewer": "mallory"},
        {"content_hash": "0" * 64},
        {"line_id": "SYN-1"},
    ],
)
def test_every_indexed_column_is_compared_with_the_body(app_engine, owner_engine, loaded, values):
    """One tampered column on one decision is reported for that decision only."""
    org = _org()
    by_line = _setup(app_engine, org)
    d, sibling = by_line["SYN-2"], by_line["SYN-1"]
    _override(app_engine, org, d.record_id, _req(Decision.DO_NOT_CLAIM))
    _override(app_engine, org, sibling.record_id, _req(Decision.REVIEW))
    with owner_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_org', :org, true)"), {"org": org})
        conn.execute(
            sa.update(t.decision_overrides)
            .where(t.decision_overrides.c.decision_record_id == d.record_id)
            .values(values)
        )
    with org_session(app_engine, org) as s:
        assert repo.override_column_problems(s, d.record_id) == [
            f"override {values.get('sequence', 1)}: stored columns do not match its body"
        ]
        assert repo.override_column_problems(s, sibling.record_id) == []


def test_claim_amount_column_is_compared_with_the_body(app_engine, owner_engine, loaded):
    org = _org()
    d = _setup(app_engine, org)["SYN-2"]
    _override(app_engine, org, d.record_id, _req(Decision.CLAIM))
    with owner_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_org', :org, true)"), {"org": org})
        conn.execute(
            sa.update(t.decision_overrides)
            .where(t.decision_overrides.c.decision_record_id == d.record_id)
            .values(claim_amount=Decimal("1.99"))
        )
    with org_session(app_engine, org) as s:
        assert repo.override_column_problems(s, d.record_id) == [
            "override 1: stored columns do not match its body"
        ]


def test_a_charge_missing_from_the_store_blocks_a_human_claim(app_engine, owner_engine, loaded):
    org = _org()
    d = _setup(app_engine, org)["SYN-2"]
    v = _store_variant(
        app_engine, org, d, subject=d.subject.model_copy(update={"line_id": "SYN-GONE"})
    )
    with pytest.raises(OverrideError, match="charge is not in the store"):
        _override(app_engine, org, v.record_id, _req(Decision.CLAIM))


# --- third review --------------------------------------------------------------------


def test_partial_coverage_cannot_be_claimed_in_full(app_engine, loaded):
    org = _org()
    d = _setup(app_engine, org)["SYN-2"]
    v = _store_variant(app_engine, org, d, coverage=Decimal("0.5000"))
    with pytest.raises(OverrideError, match="cannot claim part of a charge") as err:
        _override(app_engine, org, v.record_id, _req(Decision.CLAIM))
    assert err.value.status == 409


def _rules_with_fee_window(close_days: int, open_days: int | None = None):
    """The channel rules with a filing window on inbound defect fees, as if one were
    sourced (none is today; the sourced windows are all on loss events, which can never be
    claimed). Lets the override-day judgement be tested on a claimable charge type."""
    from app.core.rules import load_rules

    rules = load_rules()
    ct = ChargeType.INBOUND_DEFECT_FEE
    fw = rules.filing_windows[ct].model_copy(
        update={"window_close_days": close_days, "window_open_days": open_days}
    )
    return rules.model_copy(update={"filing_windows": {**rules.filing_windows, ct: fw}})


def test_filing_window_is_judged_on_the_date_of_the_override(app_engine, loaded, monkeypatch):
    """No stubbed pre-checks: the window is open today and closed on the override date."""
    org = _org()
    d = _setup(app_engine, org)["SYN-2"]  # posted 2026-07-18; fee windows are unsourced
    today = datetime.now(UTC).date()
    close = (today - date(2026, 7, 18)).days + 30  # deadline 30 days from today
    monkeypatch.setattr("app.review.load_rules", lambda: _rules_with_fee_window(close))
    later = datetime.combine(today + timedelta(days=45), datetime.min.time(), tzinfo=UTC)
    with pytest.raises(OverrideError, match="does not allow a claim today") as err:
        _override(app_engine, org, d.record_id, _req(Decision.CLAIM), at=later)
    assert err.value.status == 409
    _, eff = _override(app_engine, org, d.record_id, _req(Decision.CLAIM), at=AT_NOW())
    assert eff.decision == Decision.CLAIM


def AT_NOW() -> datetime:
    return datetime.now(UTC)


def test_window_opened_since_the_run_asks_for_a_re_run(app_engine, loaded, monkeypatch):
    org = _org()
    d = _setup(app_engine, org)["SYN-2"]
    not_yet = [
        c.model_copy(update={"verdict": Verdict.FAIL, "detail": "not yet eligible: ..."})
        if c.check_key == "within_filing_window"
        else c
        for c in d.checks
    ]
    v = _store_variant(app_engine, org, d, checks=not_yet)
    monkeypatch.setattr("app.review.load_rules", lambda: _rules_with_fee_window(3650, 0))
    with pytest.raises(OverrideError, match="opened since the run; re-run") as err:
        _override(app_engine, org, v.record_id, _req(Decision.CLAIM), at=AT_NOW())
    assert err.value.status == 409


def test_a_run_committed_during_the_override_rolls_it_back(app_engine, loaded, monkeypatch):
    """The newest-decision check is repeated after the insert: if a newer decision of the
    line appeared meanwhile, the override is refused and nothing is stored."""
    org = _org()
    d = _setup(app_engine, org)["SYN-2"]
    newer = d.model_copy(update={"record_id": f"{d.record_id}-newer"})
    real = repo.list_decisions_for_line
    calls = {"n": 0}

    def second_call_sees_a_newer_run(session, line_id):
        calls["n"] += 1
        found = real(session, line_id)
        return found if calls["n"] == 1 else [*found, newer]

    monkeypatch.setattr("app.review.repo.list_decisions_for_line", second_call_sees_a_newer_run)
    with pytest.raises(OverrideError, match="newer run decided this charge line meanwhile") as err:
        _override(app_engine, org, d.record_id, _req(Decision.DO_NOT_CLAIM))
    assert err.value.status == 409 and calls["n"] == 2
    monkeypatch.undo()
    with org_session(app_engine, org) as s:
        assert repo.list_overrides(s, d.record_id) == []
