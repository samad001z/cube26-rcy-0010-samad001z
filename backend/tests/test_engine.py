"""Rule engine: one test (at least) per rule path, plus the three approval-time decisions
(filing window blocks only on FAIL; defect_category required for CLAIM; D-011)."""

from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal

from app.core.rules import ChannelRules, load_engine_config, load_rules, parse_rules
from app.engine import DECIDED_BY, decide
from app.models.charge import Charge
from app.models.contract import EvidenceRecord
from app.models.decision import DecisionRecord
from app.models.vocab import (
    ChargeType,
    Decision,
    EvidenceStatus,
    ReasonCode,
    RecordStatus,
    ReportType,
    Verdict,
)
from app.precheck import run_prechecks
from app.resolution import resolve_unit
from app.retrieval import retrieve
from tests.factories import charge, check, prep_all_pass, record
from tests.test_rules_config import SOURCED, _rules

CFG = load_engine_config()
RULES = load_rules()
AS_OF = date(2026, 9, 25)
NOW = datetime(2026, 9, 25, 12, tzinfo=UTC)
RUN = "00000000-0000-0000-0000-000000000001"


def run(
    c: Charge,
    records: Sequence[EvidenceRecord],
    *,
    others: Sequence[Charge] = (),
    rules: ChannelRules = RULES,
    as_of: date = AS_OF,
) -> DecisionRecord:
    pre = run_prechecks([c, *others], rules, CFG, as_of)[c.line_id]
    res = resolve_unit(c, records)
    return decide(c, pre, res, retrieve(c, res, CFG), rules, CFG, run_id=RUN, decided_at=NOW)


def rules_with_window(days: int, ct: str = "inbound_defect_fee") -> ChannelRules:
    data = _rules()
    data["filing_window_days"][ct] = {**SOURCED, "value": days}
    return parse_rules(data)


def _verdicts(d: DecisionRecord) -> dict[str, Verdict]:
    return {c.check_key: c.verdict for c in d.checks}


HANDBOOK_CHECKS = {
    "unit_resolved",
    "evidence_present",
    "evidence_in_custody_window",
    "evidence_contradicts_charge",
    "not_duplicate",
    "not_already_reimbursed",
    "amount_computable",
    "within_filing_window",
}


# --- every decision carries the full trace --------------------------------------------


def test_every_decision_has_all_checks_with_verdict_and_confidence_and_a_valid_hash():
    d = run(charge(defect_category="label"), [prep_all_pass()])
    assert {c.check_key for c in d.checks} == HANDBOOK_CHECKS
    assert all(c.confidence is not None for c in d.checks)
    assert d.verify_hash()
    assert d.outcome.decided_by == DECIDED_BY == "rules@0.2.0"
    assert d.outcome.decision == d.decision.value
    assert d.status == RecordStatus.FINAL
    assert d.model_version is None
    assert d.rules_hash == RULES.rules_hash and d.config_hash == CFG.config_hash


# --- inbound defect fee (Option C) ----------------------------------------------------


def test_category_present_and_covering_checks_pass_is_claim_for_full_amount():
    d = run(charge(defect_category="label", amount="2.00"), [prep_all_pass()])
    assert d.decision == Decision.CLAIM
    assert d.rule_id == "R_CONTRADICTED_FULL"
    assert d.evidence_status == EvidenceStatus.CONTRADICTED
    assert d.claim is not None and d.claim.amount == Decimal("2.00")
    cite = [c for c in d.citations if c.kind == "evidence"]
    assert [(c.id, c.role) for c in cite] == [("PRP-1", "contradicts")]
    assert cite[0].check_keys == ["fnsku_label_placement", "original_barcode_covered"]
    assert cite[0].content_hash == prep_all_pass().content_hash
    assert d.confidence == Decimal("0.90")


def test_category_absent_all_pass_is_review_contradicted_with_next_action():
    d = run(charge(defect_category=None), [prep_all_pass()])
    assert d.decision == Decision.REVIEW
    assert d.evidence_status == EvidenceStatus.CONTRADICTED
    assert d.rule_id == "R_DEFECT_CATEGORY_MISSING"
    assert d.claim is None
    assert d.next_action is not None and "Seller Central" in d.next_action
    assert "override" in d.next_action
    assert "prep/label checks only" in (d.check("evidence_contradicts_charge").detail or "")


def test_category_covering_check_fails_is_do_not_claim():
    r = record(
        checks=[
            check("fnsku_label_placement", "FAIL", "missing"),
            check("original_barcode_covered", "PASS"),
        ]
    )
    d = run(charge(defect_category="label"), [r])
    assert d.decision == Decision.DO_NOT_CLAIM
    assert d.evidence_status == EvidenceStatus.SUPPORTED
    assert d.rule_id == "R_SUPPORTED"
    assert [c.role for c in d.citations] == ["supports"]


def test_failure_outside_the_named_category_does_not_count():
    r = record(
        checks=[
            check("fnsku_label_placement", "PASS"),
            check("original_barcode_covered", "PASS"),
            check("handling_marks", "FAIL", "some_missing"),
        ]
    )
    assert run(charge(defect_category="label"), [r]).decision == Decision.CLAIM


def test_uncertain_covering_check_is_review_insufficient():
    r = record(
        checks=[
            check("fnsku_label_placement", "UNCERTAIN", "on_seam"),
            check("original_barcode_covered", "PASS"),
        ]
    )
    d = run(charge(defect_category="label"), [r])
    assert d.decision == Decision.REVIEW and d.rule_id == "R_INSUFFICIENT"
    assert d.evidence_status == EvidenceStatus.INSUFFICIENT


def test_covering_check_not_recorded_is_review():
    r = record(checks=[check("fnsku_label_placement", "PASS")])
    d = run(charge(defect_category="label"), [r])
    assert d.decision == Decision.REVIEW
    assert "not recorded: original_barcode_covered" in d.reason


def test_unmapped_category_is_review():
    d = run(charge(defect_category="box_content"), [prep_all_pass()])
    assert d.decision == Decision.REVIEW
    assert "no mapping" in d.reason


def test_two_prep_records_disagreeing_is_conflicting():
    good = prep_all_pass("PRP-1")
    bad = record("PRP-2", checks=[check("fnsku_label_placement", "FAIL", "missing")])
    d = run(charge(defect_category="label"), [good, bad])
    assert d.decision == Decision.REVIEW
    assert d.evidence_status == EvidenceStatus.CONFLICTING and d.rule_id == "R_CONFLICTING"


def test_pending_prep_record_cannot_contradict():
    r = prep_all_pass(status=RecordStatus.PENDING)
    d = run(charge(defect_category="label"), [r])
    assert d.decision == Decision.REVIEW and d.evidence_status == EvidenceStatus.INSUFFICIENT


def test_quantity_above_one_with_one_unit_record_is_partial_review():
    d = run(charge(defect_category="label", quantity=2), [prep_all_pass()])
    assert d.decision == Decision.REVIEW and d.rule_id == "R_PARTIAL_COVERAGE"
    assert d.coverage == Decimal("0.5000")
    assert d.check("evidence_contradicts_charge").confidence == Decimal("0.45")


def test_prep_on_other_shipment_only_is_no_relevant_evidence():
    d = run(charge(defect_category="label"), [prep_all_pass(fba_shipment_id="FBA-9")])
    assert d.decision == Decision.REVIEW
    assert d.reason_code == ReasonCode.NO_RELEVANT_EVIDENCE


def test_prep_after_posting_is_evidence_outside_window():
    late = prep_all_pass(captured=datetime(2026, 7, 20, tzinfo=UTC))
    d = run(charge(defect_category="label", posted=date(2026, 7, 18)), [late])
    assert d.decision == Decision.REVIEW
    assert d.reason_code == ReasonCode.EVIDENCE_OUTSIDE_WINDOW
    assert _verdicts(d)["evidence_in_custody_window"] == Verdict.FAIL


# --- filing window (change 1) ---------------------------------------------------------


def test_unknown_filing_window_allows_claim_with_warning_in_reason_and_detail():
    d = run(charge(defect_category="label"), [prep_all_pass()])
    assert d.decision == Decision.CLAIM
    assert _verdicts(d)["within_filing_window"] == Verdict.UNCERTAIN
    assert "filing deadline not verified" in d.reason
    assert "filing deadline not verified" in (d.check("within_filing_window").detail or "")
    assert d.warnings == ["filing deadline not verified"]


def test_known_open_window_claims_without_warning():
    d = run(charge(defect_category="label"), [prep_all_pass()], rules=rules_with_window(365))
    assert d.decision == Decision.CLAIM and d.warnings == []
    assert "not verified" not in d.reason


def test_passed_window_blocks_claim():
    d = run(charge(defect_category="label"), [prep_all_pass()], rules=rules_with_window(30))
    assert d.decision == Decision.REVIEW and d.rule_id == "R_FILING_WINDOW_PASSED"
    assert d.claim is None
    assert d.evidence_status == EvidenceStatus.CONTRADICTED


# --- duplicates and reimbursements ----------------------------------------------------


def test_duplicate_is_claimed_citing_the_canonical_line():
    first = charge("L-1", posted=date(2026, 7, 1))
    dup = charge("L-2", posted=date(2026, 7, 5))
    d = run(dup, [], others=[first])
    assert d.decision == Decision.CLAIM and d.reason_code == ReasonCode.DUPLICATE_CHARGE
    assert d.claim is not None and d.claim.amount == Decimal("2.00")
    assert d.citations[0].kind == "charge" and d.citations[0].id == "L-1"
    assert d.citations[0].content_hash == first.compute_hash()
    # the canonical line itself is not a duplicate
    assert run(first, [], others=[dup]).reason_code != ReasonCode.DUPLICATE_CHARGE


def test_duplicate_past_filing_window_is_review():
    first = charge("L-1", posted=date(2026, 7, 1))
    dup = charge("L-2", posted=date(2026, 7, 5))
    d = run(dup, [], others=[first], rules=rules_with_window(10))
    assert d.decision == Decision.REVIEW and d.reason_code == ReasonCode.DUPLICATE_CHARGE


def test_fully_reimbursed_fee_is_do_not_claim():
    fee = charge("L-1", amount="2.00", posted=date(2026, 7, 1), defect_category="label")
    refund = charge(
        "R-1", report_type=ReportType.REIMBURSEMENT_REPORT, amount="2.00", posted=date(2026, 7, 9)
    )
    d = run(fee, [prep_all_pass()], others=[refund])
    assert d.decision == Decision.DO_NOT_CLAIM
    assert d.reason_code == ReasonCode.ALREADY_REIMBURSED
    assert [c.id for c in d.citations if c.role == "reimbursement"] == ["R-1"]


def test_partially_reimbursed_fee_claims_only_the_remainder():
    fee = charge("L-1", amount="2.00", posted=date(2026, 7, 1), defect_category="label")
    refund = charge(
        "R-1", report_type=ReportType.REIMBURSEMENT_REPORT, amount="0.75", posted=date(2026, 7, 9)
    )
    d = run(fee, [prep_all_pass()], others=[refund])
    assert d.decision == Decision.CLAIM
    assert d.claim is not None and d.claim.amount == Decimal("1.25")
    assert d.amount_reimbursed == Decimal("0.75")


def test_fee_refund_line_itself_is_do_not_claim():
    refund = charge("R-1", report_type=ReportType.REIMBURSEMENT_REPORT, amount="2.00")
    d = run(refund, [prep_all_pass()])
    assert d.decision == Decision.DO_NOT_CLAIM and d.rule_id == "R_FEE_REFUND_LINE"


# --- D-011 zero amounts and loss events -----------------------------------------------


def test_zero_fee_is_do_not_claim():
    d = run(charge(amount="0.00", defect_category="label"), [prep_all_pass()])
    assert d.decision == Decision.DO_NOT_CLAIM and d.rule_id == "R_ZERO_FEE"
    assert d.claim is None


def test_loss_events_are_never_claim_even_with_contradicting_evidence():
    for ct, records in (
        (ChargeType.LOST_INBOUND, [prep_all_pass()]),
        (ChargeType.DAMAGED_IN_WAREHOUSE, [prep_all_pass()]),
    ):
        for amount in ("0.00", "14.00"):
            d = run(charge(charge_type=ct, amount=amount), records)
            assert d.decision == Decision.REVIEW, (ct, amount)
            assert d.rule_id == "R_AMOUNT_NOT_COMPUTABLE"
            assert d.evidence_status == EvidenceStatus.CONTRADICTED
            assert _verdicts(d)["amount_computable"] == Verdict.FAIL
            assert d.claim is None
            assert d.next_action is not None and "unit value" in d.next_action


def test_lost_inbound_with_a_later_customer_return_is_conflicting():
    ret = record(
        "RTN-1",
        agent="returns",
        fba_shipment_id=None,
        captured=datetime(2026, 6, 29, tzinfo=UTC),
        checks=[check("identity_match", "PASS")],
    )
    c = charge(charge_type=ChargeType.LOST_INBOUND, amount="0.00", posted=date(2026, 6, 19))
    d = run(c, [prep_all_pass(), ret])
    assert d.decision == Decision.REVIEW
    assert d.evidence_status == EvidenceStatus.CONFLICTING


def test_refund_not_returned_with_return_record_is_contradicted_but_review():
    ret = record(
        "RTN-1",
        agent="returns",
        order_id="ORD-1",
        captured=datetime(2026, 6, 24, 8, tzinfo=UTC),
        checks=[check("identity_match", "PASS"), check("returned_item_condition", "PASS")],
    )
    c = charge(
        charge_type=ChargeType.REFUND_ISSUED_ITEM_NOT_RETURNED,
        amount="0.00",
        order_id="ORD-1",
        posted=date(2026, 6, 24),
    )
    d = run(c, [ret])
    assert d.decision == Decision.REVIEW
    assert d.evidence_status == EvidenceStatus.CONTRADICTED


def test_refund_not_returned_wrong_item_back_is_supported_still_review():
    ret = record(
        "RTN-1",
        agent="returns",
        order_id="ORD-1",
        captured=datetime(2026, 6, 24, 8, tzinfo=UTC),
        checks=[check("identity_match", "FAIL")],
    )
    c = charge(
        charge_type=ChargeType.REFUND_ISSUED_ITEM_NOT_RETURNED,
        amount="0.00",
        order_id="ORD-1",
        posted=date(2026, 6, 24),
    )
    d = run(c, [ret])
    assert d.decision == Decision.REVIEW and d.evidence_status == EvidenceStatus.SUPPORTED


# --- weight tier and unresolved -------------------------------------------------------


def test_weight_tier_without_measurements_is_review_no_relevant_evidence():
    c = charge(charge_type=ChargeType.FULFILMENT_FEE_WEIGHT_TIER, amount="4.25")
    d = run(c, [prep_all_pass()])
    assert d.decision == Decision.REVIEW
    assert d.reason_code == ReasonCode.NO_RELEVANT_EVIDENCE
    assert d.evidence_status == EvidenceStatus.INSUFFICIENT
    assert _verdicts(d)["amount_computable"] == Verdict.FAIL
    assert "measured_weight" in (d.next_action or "")


def test_weight_tier_with_measurements_but_no_fee_schedule_is_review():
    r = record(checks=[check("measured_weight", "PASS")])
    c = charge(charge_type=ChargeType.FULFILMENT_FEE_WEIGHT_TIER, amount="4.25")
    d = run(c, [r])
    assert d.decision == Decision.REVIEW and d.evidence_status == EvidenceStatus.INSUFFICIENT


def test_unresolved_unit_is_review_with_reason_code():
    d = run(charge(unit_id="U-404"), [prep_all_pass()])
    assert d.decision == Decision.REVIEW
    assert d.reason_code == ReasonCode.UNRESOLVED_UNIT
    assert "U-404" in d.reason
    assert d.resolved_unit is None
    assert d.citations == []


# --- determinism ----------------------------------------------------------------------


def test_same_inputs_give_identical_record_and_hash():
    a = run(charge(defect_category="label"), [prep_all_pass()])
    b = run(charge(defect_category="label"), [prep_all_pass()])
    assert a == b and a.content_hash == b.content_hash


def test_considered_records_list_every_relevant_record_with_reason():
    other = prep_all_pass("PRP-2", fba_shipment_id="FBA-9")
    d = run(
        charge(defect_category="label"),
        [prep_all_pass(), other, record("RCV-1", agent="receiving")],
    )
    by_id = {c.record_id: c for c in d.evidence_considered}
    assert set(by_id) == {"PRP-1", "PRP-2"}  # receiving is not relevant to this fee
    assert by_id["PRP-1"].usable and not by_id["PRP-2"].usable
    assert "fba_shipment_id differs" in by_id["PRP-2"].reason


# --- reimbursement matching (rules review M1, M2) --------------------------------------


def _refund(line_id: str, amount: str, posted: date, **kw) -> Charge:
    return charge(
        line_id, report_type=ReportType.REIMBURSEMENT_REPORT, amount=amount, posted=posted, **kw
    )


def test_refund_after_a_duplicate_is_applied_to_the_duplicate_not_claimed_again():
    f1 = charge("F1", posted=date(2026, 7, 18), defect_category="label")
    f2 = charge("F2", posted=date(2026, 7, 19), defect_category="label")
    r1 = _refund("R1", "2.00", date(2026, 7, 25))
    d2 = run(f2, [prep_all_pass()], others=[f1, r1])
    assert d2.decision == Decision.DO_NOT_CLAIM
    assert d2.reason_code == ReasonCode.ALREADY_REIMBURSED
    # the canonical charge is judged on its own evidence, not treated as refunded
    d1 = run(f1, [prep_all_pass()], others=[f2, r1])
    assert d1.amount_reimbursed == Decimal("0.00")
    assert d1.decision == Decision.CLAIM


def test_refund_on_another_shipment_does_not_offset_this_fee():
    f1 = charge("F1", posted=date(2026, 7, 1), fba_shipment_id="FBA-1", defect_category="label")
    f2 = charge("F2", posted=date(2026, 8, 20), fba_shipment_id="FBA-2", defect_category="label")
    r2 = _refund("R2", "2.00", date(2026, 8, 25), fba_shipment_id="FBA-2")
    recs = [
        prep_all_pass("PRP-1"),
        prep_all_pass("PRP-2", fba_shipment_id="FBA-2", captured=datetime(2026, 8, 1, tzinfo=UTC)),
    ]
    d1 = run(f1, recs, others=[f2, r2])
    d2 = run(f2, recs, others=[f1, r2])
    assert d1.amount_reimbursed == Decimal("0.00") and d1.decision == Decision.CLAIM
    assert d2.decision == Decision.DO_NOT_CLAIM
    assert d2.reason_code == ReasonCode.ALREADY_REIMBURSED


def test_refund_that_could_belong_to_two_fees_sends_both_to_review():
    f1 = charge("F1", posted=date(2026, 7, 1), fba_shipment_id="FBA-1", defect_category="label")
    f2 = charge("F2", posted=date(2026, 7, 2), fba_shipment_id="FBA-2", defect_category="label")
    r = _refund("R1", "2.00", date(2026, 7, 25), fba_shipment_id=None)
    recs = [prep_all_pass("PRP-1"), prep_all_pass("PRP-2", fba_shipment_id="FBA-2")]
    for fee in (f1, f2):
        d = run(fee, recs, others=[f1, f2, r])
        assert d.decision == Decision.REVIEW, fee.line_id
        assert d.rule_id == "R_REIMBURSEMENT_AMBIGUOUS"
        assert d.check("not_already_reimbursed").verdict == Verdict.UNCERTAIN
        assert "R1" in d.reason


def test_a_refund_offsets_at_most_its_own_amount():
    fee = charge("F1", amount="5.00", posted=date(2026, 7, 1), defect_category="label")
    r = _refund("R1", "2.00", date(2026, 7, 5))
    d = run(fee, [prep_all_pass()], others=[r])
    assert d.amount_reimbursed == Decimal("2.00")
    assert d.claim is not None and d.claim.amount == Decimal("3.00")


def test_refund_larger_than_the_fee_offsets_only_the_fee():
    fee = charge("F1", amount="2.00", posted=date(2026, 7, 1), defect_category="label")
    r = _refund("R1", "5.00", date(2026, 7, 5))
    d = run(fee, [prep_all_pass()], others=[r])
    assert d.amount_reimbursed == Decimal("2.00")
    assert d.decision == Decision.DO_NOT_CLAIM


def test_overridden_prep_record_cannot_contradict():
    r = prep_all_pass(status=RecordStatus.OVERRIDDEN)
    d = run(charge(defect_category="label"), [r])
    assert d.decision == Decision.REVIEW and d.evidence_status == EvidenceStatus.INSUFFICIENT
    assert "record status overridden" in d.reason
