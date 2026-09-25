"""Claim amounts, citation validator, and property tests over the engine's invariants."""

from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from app.claims import compute_full_amount_claim
from app.claims.validator import RULE_ID, StoredRecord, enforce, validate
from app.core.rules import load_engine_config
from app.models.charge import Charge
from app.models.contract import EvidenceRecord
from app.models.decision import Citation, Claim, DecisionRecord
from app.models.vocab import ChargeType, Decision, RecordStatus, ReportType, Verdict
from tests.factories import charge, check, prep_all_pass, record
from tests.test_engine import run

CFG = load_engine_config()


class DictLookup:
    """In-memory store for unit tests. The DB-backed lookup is tested in test_pipeline_db."""

    def __init__(self, records: Sequence[EvidenceRecord] = (), charges: Sequence[Charge] = ()):
        self.records = {r.record_id: StoredRecord(r, r.content_hash or "") for r in records}
        self.charges = {c.line_id: c for c in charges}

    def evidence(self, record_id: str) -> StoredRecord | None:
        return self.records.get(record_id)

    def charge(self, line_id: str) -> Charge | None:
        return self.charges.get(line_id)


# --- amounts --------------------------------------------------------------------------


def test_full_amount_claim_writes_every_step():
    c = charge(amount="2.00")
    claim = compute_full_amount_claim(c, Decimal(1), Decimal("0.50"), ["R-1"])
    assert claim is not None and claim.amount == Decimal("1.50")
    assert claim.computation[-1] == "claim = min(2.00, 2.00 - 0.50) = 1.50 USD"
    assert "(R-1)" in claim.computation[2]


def test_fully_reimbursed_gives_no_claim():
    assert compute_full_amount_claim(charge(amount="2.00"), Decimal(1), Decimal("2.00"), []) is None


def test_coverage_out_of_range_is_refused():
    import pytest

    with pytest.raises(ValueError):
        compute_full_amount_claim(charge(), Decimal("1.01"), Decimal(0), [])


@settings(max_examples=200)
@given(
    amount=st.decimals(min_value=0, max_value=10000, places=2),
    reimbursed=st.decimals(min_value=0, max_value=10000, places=2),
    coverage=st.decimals(min_value=0, max_value=1, places=4),
)
def test_claim_never_exceeds_charge_minus_reimbursed(amount, reimbursed, coverage):
    c = charge(amount=str(amount))
    claim = compute_full_amount_claim(c, coverage, reimbursed, [])
    if claim is not None:
        assert Decimal("0.00") < claim.amount <= c.amount - reimbursed
        assert claim.amount <= c.amount
        assert claim.amount == claim.amount.quantize(Decimal("0.01"))


# --- validator ------------------------------------------------------------------------


def _claim_case() -> tuple[DecisionRecord, Charge, EvidenceRecord]:
    c = charge(defect_category="label")
    r = prep_all_pass()
    d = run(c, [r])
    assert d.decision == Decision.CLAIM
    return d, c, r


def test_honest_claim_validates():
    d, c, r = _claim_case()
    assert validate(d, c, DictLookup([r], [c]), CFG) == []
    assert enforce(d, []) is d


def test_missing_record_fails_closed_to_pending_review():
    d, c, _ = _claim_case()
    errors = validate(d, c, DictLookup([], [c]), CFG)
    assert errors == ["cited record PRP-1 not found"]
    out = enforce(d, errors)
    assert out.decision == Decision.REVIEW and out.status == RecordStatus.PENDING
    assert out.rule_id == RULE_ID and out.rule_path == ["R_CONTRADICTED_FULL", RULE_ID]
    assert out.claim is None and out.outcome.decision == "REVIEW"
    assert out.verify_hash()


def test_tampered_record_body_is_detected():
    d, c, r = _claim_case()
    tampered = r.model_copy(
        update={
            "checks": [
                check("fnsku_label_placement", "PASS"),
                check("original_barcode_covered", "PASS", "edited"),
            ]
        }
    )
    lookup = DictLookup([], [c])
    lookup.records["PRP-1"] = StoredRecord(tampered, r.content_hash or "")
    assert "cited record PRP-1 body does not match its hash" in validate(d, c, lookup, CFG)


def test_stored_hash_different_from_cited_is_detected():
    d, c, r = _claim_case()
    lookup = DictLookup([], [c])
    lookup.records["PRP-1"] = StoredRecord(r, "f" * 64)
    assert "cited record PRP-1 hash mismatch" in validate(d, c, lookup, CFG)


def test_record_of_another_org_is_rejected():
    d, c, _ = _claim_case()
    foreign = prep_all_pass(org="org_other")
    errors = validate(d, c, DictLookup([foreign], [c]), CFG)
    assert "cited record PRP-1 belongs to another organisation" in errors


def test_cited_check_key_must_exist():
    d, c, r = _claim_case()
    bad = d.model_copy(
        update={"citations": [d.citations[0].model_copy(update={"check_keys": ["invented"]})]}
    ).with_hash()
    errors = validate(bad, c, DictLookup([r], [c]), CFG)
    assert "cited record PRP-1 has no check ['invented']" in errors


def test_citation_outside_custody_window_is_rejected():
    c = charge(defect_category="label", posted=date(2026, 7, 18))
    late = prep_all_pass(captured=datetime(2026, 7, 20, tzinfo=UTC))
    d, _, _ = _claim_case()
    forged = d.model_copy(
        update={
            "citations": [
                Citation(
                    kind="evidence",
                    id="PRP-1",
                    content_hash=late.content_hash or "",
                    role="contradicts",
                    check_keys=["fnsku_label_placement"],
                )
            ]
        }
    ).with_hash()
    assert "cited record PRP-1 is outside the custody window" in validate(
        forged, c, DictLookup([late], [c]), CFG
    )


def test_claim_above_cap_or_without_contradicting_citation_is_rejected():
    d, c, r = _claim_case()
    big = d.model_copy(
        update={"claim": Claim(amount=Decimal("2.01"), currency="USD", computation=[])}
    ).with_hash()
    errors = validate(big, c, DictLookup([r], [c]), CFG)
    assert "claim 2.01 exceeds charged - reimbursed = 2.00" in errors
    bare = d.model_copy(update={"citations": []}).with_hash()
    assert "CLAIM cites no contradicting evidence or canonical charge" in validate(
        bare, c, DictLookup([r], [c]), CFG
    )


def test_non_claim_with_amount_and_bad_self_hash_are_rejected():
    d, c, r = _claim_case()
    review = d.model_copy(update={"decision": Decision.REVIEW}).with_hash()
    assert "REVIEW carries a claim amount" in validate(review, c, DictLookup([r], [c]), CFG)
    unhashed = d.model_copy(update={"reason": "edited after hashing"})
    errors = validate(unhashed, c, DictLookup([r], [c]), CFG)
    assert "decision content hash does not verify" in errors


def test_changed_charge_is_rejected():
    d, c, r = _claim_case()
    changed = c.model_copy(update={"amount": Decimal("9.99")})
    assert "charge L-1 not found in the store or changed" in validate(
        d, c, DictLookup([r], [changed]), CFG
    )


# --- engine invariants (property) -----------------------------------------------------

VERDICTS = st.sampled_from([Verdict.PASS, Verdict.FAIL, Verdict.UNCERTAIN, None])
PREP_KEYS = CFG.charge_types[ChargeType.INBOUND_DEFECT_FEE].scope_checks


@st.composite
def cases(draw):
    ct = draw(st.sampled_from(list(ChargeType)))
    amount = draw(st.decimals(min_value=0, max_value=500, places=2))
    qty = draw(st.integers(min_value=1, max_value=3))
    cat = draw(st.sampled_from([None, "label", "polybag", "expiry_date", "box_content"]))
    posted = date(2026, 7, 18)
    c = charge(
        "L-1",
        charge_type=ct,
        amount=str(amount),
        quantity=qty,
        defect_category=cat,
        order_id=draw(st.sampled_from([None, "ORD-1"])),
        posted=posted,
    )
    records = []
    for i in range(draw(st.integers(min_value=0, max_value=2))):
        checks = [check(k, v) for k in PREP_KEYS if (v := draw(VERDICTS)) is not None]
        records.append(
            record(
                f"PRP-{i}",
                checks=checks,
                captured=datetime(2026, 7, 18, tzinfo=UTC)
                - timedelta(days=draw(st.integers(min_value=-5, max_value=150))),
                fba_shipment_id=draw(st.sampled_from(["FBA-1", "FBA-2"])),
                status=draw(st.sampled_from([RecordStatus.FINAL, RecordStatus.PENDING])),
            )
        )
    if draw(st.booleans()):
        records.append(
            record(
                "RTN-1",
                agent="returns",
                order_id="ORD-1",
                fba_shipment_id=None,
                captured=datetime(2026, 7, 20, tzinfo=UTC),
                checks=[check("identity_match", draw(st.sampled_from(["PASS", "FAIL"])))],
            )
        )
    others = []
    if draw(st.booleans()):
        others.append(
            charge(
                "R-1",
                charge_type=ct,
                report_type=ReportType.REIMBURSEMENT_REPORT,
                amount=str(draw(st.decimals(min_value=0, max_value=500, places=2))),
                posted=date(2026, 7, 20),
            )
        )
    if draw(st.booleans()):
        others.append(
            charge(
                "L-0",
                charge_type=ct,
                amount=str(amount),
                quantity=qty,
                defect_category=cat,
                order_id=c.order_id,
                posted=date(2026, 7, 10),
            )
        )
    return c, records, others


@settings(max_examples=200, deadline=None)
@given(cases())
def test_engine_invariants_hold_for_any_input(case):
    c, records, others = case
    d = run(c, records, others=others)
    kind = CFG.charge_types[c.charge_type].kind
    assert {x.check_key for x in d.checks} == {
        "unit_resolved",
        "evidence_present",
        "evidence_in_custody_window",
        "evidence_contradicts_charge",
        "not_duplicate",
        "not_already_reimbursed",
        "amount_computable",
        "within_filing_window",
    }
    assert all(x.confidence is not None and 0 <= x.confidence <= 1 for x in d.checks)
    assert d.verify_hash()
    assert d.reason
    if d.decision == Decision.CLAIM:
        assert kind == "fee" and c.amount > 0
        assert d.claim is not None
        assert Decimal("0.00") < d.claim.amount <= c.amount - d.amount_reimbursed
        if d.rule_id == "R_CONTRADICTED_FULL" and c.charge_type == ChargeType.INBOUND_DEFECT_FEE:
            assert c.defect_category is not None
    else:
        assert d.claim is None
    if kind == "loss_event" or c.amount == 0:
        assert d.decision != Decision.CLAIM
    # Engine output always passes the validator against an honest store.
    lookup = DictLookup(records, [c, *others])
    assert validate(d, c, lookup, CFG) == []
