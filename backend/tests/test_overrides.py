"""Human overrides (D-021) against real Postgres as the non-superuser app role: overrides
are data, the engine's decision row is never changed, a human CLAIM respects rule 9, the
history is a verifiable chain, and the database refuses what the code would refuse."""

import threading
import time
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
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
from app.models.decision import DecisionRecord
from app.models.vocab import Decision, RecordStatus
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
    "over",
    [
        {"new_decision": "REVIEW"},  # changes nothing
        {"new_decision": "CLAIM"},  # CLAIM without an amount
        {"new_decision": "DO_NOT_CLAIM", "claim_amount": Decimal("1.00")},  # amount on non-claim
        {"new_decision": "CLAIM", "claim_amount": Decimal("0.00")},
        {"reason": "   "},
        {"reviewer": ""},
        {"sequence": 0},
        {"new_decision": "MAYBE"},
        {"decision_record_id": "DEC-does-not-exist"},  # must point at a stored decision
    ],
)
def test_database_constraints_refuse_bad_override_rows(app_engine, loaded, over):
    org = _org()
    d = _setup(app_engine, org)["SYN-2"]
    with pytest.raises((IntegrityError, DBAPIError)):
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
