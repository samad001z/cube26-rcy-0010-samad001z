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


def _unsourced() -> ChannelRules:
    """The shipped rules with every filing window set back to null."""
    data = _rules()
    for ct in data["filing_windows"]:
        data["filing_windows"][ct] = {
            k: None for k in data["filing_windows"][ct] if k != "secondary_sources"
        } | {"secondary_sources": []}
    return parse_rules(data)


RULES_UNSOURCED = _unsourced()


def rules_with_window(
    days: int, ct: str = "inbound_defect_fee", open_days: int | None = None
) -> ChannelRules:
    data = _rules()
    data["filing_windows"][ct] = {
        **SOURCED,
        "window_open_days": open_days,
        "window_close_days": days,
    }
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
    assert d.outcome.decided_by == DECIDED_BY == "rules@0.3.0"
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


def test_passed_window_is_do_not_claim_filing_window_expired_with_evidence_kept():
    # D-015a (human lead, 2026-09-25): a known, passed deadline is DO_NOT_CLAIM, not REVIEW.
    d = run(charge(defect_category="label"), [prep_all_pass()], rules=rules_with_window(30))
    assert d.decision == Decision.DO_NOT_CLAIM and d.rule_id == "R_FILING_WINDOW_PASSED"
    assert d.reason_code == ReasonCode.FILING_WINDOW_EXPIRED
    assert d.claim is None
    assert d.check("within_filing_window").verdict == Verdict.FAIL
    # the evidence checks still show that the evidence supports recovery
    assert d.evidence_status == EvidenceStatus.CONTRADICTED
    assert d.check("evidence_contradicts_charge").verdict == Verdict.PASS
    assert [c.role for c in d.citations] == ["contradicts"]


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


def test_duplicate_past_filing_window_is_do_not_claim_filing_window_expired():
    first = charge("L-1", posted=date(2026, 7, 1))
    dup = charge("L-2", posted=date(2026, 7, 5))
    d = run(dup, [], others=[first], rules=rules_with_window(10))
    assert d.decision == Decision.DO_NOT_CLAIM
    assert d.reason_code == ReasonCode.FILING_WINDOW_EXPIRED
    assert d.check("not_duplicate").verdict == Verdict.FAIL
    assert [(c.id, c.role) for c in d.citations] == [("L-1", "canonical_charge")]


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


def test_loss_events_are_never_claim_even_with_supporting_evidence():
    # D-016: prep-only evidence is consistent with a loss (SUPPORTED); still REVIEW (D-011).
    for ct, records in (
        (ChargeType.LOST_INBOUND, [prep_all_pass()]),
        (ChargeType.DAMAGED_IN_WAREHOUSE, [prep_all_pass()]),
    ):
        for amount in ("0.00", "14.00"):
            # No filing window: the evidence mapping alone (expiry is tested separately).
            d = run(charge(charge_type=ct, amount=amount), records, rules=RULES_UNSOURCED)
            assert d.decision == Decision.REVIEW, (ct, amount)
            assert d.rule_id == "R_AMOUNT_NOT_COMPUTABLE"
            assert d.evidence_status == EvidenceStatus.SUPPORTED
            assert _verdicts(d)["amount_computable"] == Verdict.FAIL
            assert d.claim is None
            assert d.next_action is not None and "unit value" in d.next_action


# --- loss events: one test per row of config loss_event_outcomes (D-016) ------------------

# Words that would steer a reviewer towards claiming. Never in a next action where the
# evidence refutes the seller's claim.
CLAIM_WORDS = ("override", "claim the", "to claim", "CLAIM", "amount")


def _returns(
    record_id: str = "RTN-1",
    *,
    identity: str = "PASS",
    parts: str | None = "PASS",
    condition: str | None = "PASS",
    captured: datetime = datetime(2026, 6, 24, 8, tzinfo=UTC),
    status: RecordStatus = RecordStatus.FINAL,
) -> EvidenceRecord:
    checks = [check("identity_match", identity)]
    if parts is not None:
        checks.append(check("parts_complete", parts))
    if condition is not None:
        checks.append(check("returned_item_condition", condition))
    return record(
        record_id,
        agent="returns",
        order_id="ORD-1",
        fba_shipment_id=None,
        captured=captured,
        checks=checks,
        status=status,
    )


def _refund_line() -> Charge:
    return charge(
        charge_type=ChargeType.REFUND_ISSUED_ITEM_NOT_RETURNED,
        amount="0.00",
        order_id="ORD-1",
        posted=date(2026, 6, 24),
    )


def _lost_line(**kw: object) -> Charge:
    return charge(charge_type=ChargeType.LOST_INBOUND, amount="0.00", **kw)  # type: ignore[arg-type]


def _no_claim_steer(d: DecisionRecord) -> None:
    assert d.next_action is None or not any(w in d.next_action for w in CLAIM_WORDS), d.next_action


def test_refund_returned_complete_is_do_not_claim():
    d = run(_refund_line(), [_returns()])
    assert d.decision == Decision.DO_NOT_CLAIM and d.rule_id == "R_ITEM_RETURNED"
    assert d.evidence_status == EvidenceStatus.CONTRADICTED
    assert d.claim is None and d.next_action is None
    assert "nothing is owed" in d.reason
    assert [c.id for c in d.citations if c.role == "contradicts"] == ["RTN-1"]


def test_refund_returned_parts_missing_is_review_possible_separate_claim():
    # FEE-0038-2 pattern: identity PASS, parts_complete FAIL (tub missing), condition PASS.
    d = run(_refund_line(), [_returns(parts="FAIL")])
    assert d.decision == Decision.REVIEW and d.rule_id == "R_RETURNED_INCOMPLETE_OR_DAMAGED"
    assert d.evidence_status == EvidenceStatus.CONTRADICTED
    assert "possible separate claim" in d.reason and d.claim is None
    _no_claim_steer(d)


def test_refund_returned_damaged_is_review_possible_separate_claim():
    # FEE-0041-2 pattern: identity PASS, parts complete, condition FAIL (damaged).
    d = run(_refund_line(), [_returns(condition="FAIL")])
    assert d.decision == Decision.REVIEW and d.rule_id == "R_RETURNED_INCOMPLETE_OR_DAMAGED"
    assert d.evidence_status == EvidenceStatus.CONTRADICTED
    _no_claim_steer(d)


def test_refund_returned_condition_uncertain_is_review_not_do_not_claim():
    # FEE-0014-4 pattern: identity PASS, parts complete, condition UNCERTAIN (signs_of_use).
    d = run(_refund_line(), [_returns(condition="UNCERTAIN")])
    assert d.decision == Decision.REVIEW and d.rule_id == "R_RETURNED_INCOMPLETE_OR_DAMAGED"
    assert "condition uncertain" in d.reason
    _no_claim_steer(d)


def test_refund_returned_without_condition_recorded_is_not_complete():
    d = run(_refund_line(), [_returns(parts=None, condition=None)])
    assert d.decision == Decision.REVIEW and d.rule_id == "R_RETURNED_INCOMPLETE_OR_DAMAGED"


def test_refund_wrong_item_returned_is_supported_review_until_amount():
    d = run(_refund_line(), [_returns(identity="FAIL")])
    assert d.decision == Decision.REVIEW and d.rule_id == "R_AMOUNT_NOT_COMPUTABLE"
    assert d.evidence_status == EvidenceStatus.SUPPORTED
    assert d.next_action is not None and "unit value" in d.next_action


def test_refund_no_return_in_window_is_insufficient_noting_consistency():
    # The unit resolves through its prep record; no returns record exists for the order.
    d = run(_refund_line(), [prep_all_pass()])
    assert d.decision == Decision.REVIEW
    assert d.reason_code == ReasonCode.NO_RELEVANT_EVIDENCE
    assert d.evidence_status == EvidenceStatus.INSUFFICIENT
    assert "consistent with the seller's claim" in d.reason


def test_refund_pending_return_record_is_insufficient():
    d = run(_refund_line(), [_returns(status=RecordStatus.PENDING)])
    assert d.decision == Decision.REVIEW and d.rule_id == "R_INSUFFICIENT"
    assert d.evidence_status == EvidenceStatus.INSUFFICIENT


def test_lost_inbound_prep_only_is_supported_review_until_amount():
    # FEE-0031-1 pattern: prep on the shipment, no later record of the unit.
    d = run(_lost_line(posted=date(2026, 6, 22)), [prep_all_pass()])
    assert d.decision == Decision.REVIEW and d.rule_id == "R_AMOUNT_NOT_COMPUTABLE"
    assert d.evidence_status == EvidenceStatus.SUPPORTED
    assert _verdicts(d)["evidence_contradicts_charge"] == Verdict.FAIL
    assert [c.role for c in d.citations] == ["supports"]


def test_lost_inbound_with_a_later_customer_return_is_loss_doubtful():
    # FEE-0014-2 pattern: prep before the loss, a customer return after it.
    ret = record(
        "RTN-1",
        agent="returns",
        fba_shipment_id=None,
        captured=datetime(2026, 6, 29, tzinfo=UTC),
        checks=[check("identity_match", "PASS")],
    )
    d = run(_lost_line(posted=date(2026, 6, 19)), [prep_all_pass(), ret])
    assert d.decision == Decision.REVIEW and d.rule_id == "R_LOSS_DOUBTFUL"
    assert d.evidence_status == EvidenceStatus.CONTRADICTED
    assert "loss is doubtful" in d.reason and d.claim is None
    assert {c.id: c.role for c in d.citations} == {"PRP-1": "supports", "RTN-1": "contradicts"}
    _no_claim_steer(d)


def test_lost_inbound_pending_later_return_is_insufficient_not_supported():
    ret = record(
        "RTN-1",
        agent="returns",
        fba_shipment_id=None,
        captured=datetime(2026, 6, 29, tzinfo=UTC),
        checks=[check("identity_match", "PASS")],
        status=RecordStatus.PENDING,
    )
    d = run(_lost_line(posted=date(2026, 6, 19)), [prep_all_pass(), ret])
    assert d.decision == Decision.REVIEW and d.rule_id == "R_INSUFFICIENT"


def test_damaged_prep_with_failed_check_is_insufficient():
    prep = record("PRP-1", checks=[check("fnsku_label_placement", "FAIL")])
    c = charge(charge_type=ChargeType.DAMAGED_IN_WAREHOUSE, amount="14.00")
    d = run(c, [prep], rules=RULES_UNSOURCED)
    assert d.decision == Decision.REVIEW and d.rule_id == "R_INSUFFICIENT"


def test_loss_event_past_known_deadline_is_do_not_claim_with_proxy_note():
    # Shipped rules: damaged_in_warehouse closes 60 days after the reported date (D-017).
    c = charge(charge_type=ChargeType.DAMAGED_IN_WAREHOUSE, amount="14.00")  # posted 07-18
    d = run(c, [prep_all_pass()])  # as of 09-25: deadline 09-16 passed
    assert d.decision == Decision.DO_NOT_CLAIM
    assert d.reason_code == ReasonCode.FILING_WINDOW_EXPIRED
    assert d.rule_id == "R_FILING_WINDOW_PASSED"
    assert (
        "computed from the posted date as a proxy for the date the item was reported lost or "
        "damaged" in d.reason
    )
    assert d.evidence_status == EvidenceStatus.SUPPORTED  # evidence checks kept
    assert _verdicts(d)["evidence_contradicts_charge"] == Verdict.FAIL
    assert d.citations and d.claim is None


def test_every_loss_outcome_the_assessors_emit_has_a_config_row():
    emitted = {
        ChargeType.REFUND_ISSUED_ITEM_NOT_RETURNED: {
            "returned_complete",
            "returned_incomplete_or_damaged",
            "wrong_item_returned",
        },
        ChargeType.LOST_INBOUND: {"shipped_no_later_sighting", "later_sighting"},
        ChargeType.DAMAGED_IN_WAREHOUSE: {"left_prep_undamaged"},
    }
    assert {ct: set(m.outcomes) for ct, m in CFG.loss_event_outcomes.items()} == emitted


def test_refuting_rows_never_suggest_an_override_to_claim():
    for mapping in CFG.loss_event_outcomes.values():
        for row in mapping.outcomes.values():
            if row.amount_needed:
                continue
            assert row.next_action is None or not any(w in row.next_action for w in CLAIM_WORDS), (
                row.rule_id
            )


# --- weight tier and unresolved -------------------------------------------------------


def test_weight_tier_without_measurements_is_review_no_relevant_evidence():
    c = charge(charge_type=ChargeType.FULFILMENT_FEE_WEIGHT_TIER, amount="4.25")
    d = run(c, [prep_all_pass()])
    assert d.decision == Decision.REVIEW
    assert d.reason_code == ReasonCode.NO_RELEVANT_EVIDENCE
    assert d.evidence_status == EvidenceStatus.INSUFFICIENT
    assert _verdicts(d)["amount_computable"] == Verdict.FAIL
    assert "measured_weight" in (d.next_action or "")


def test_no_relevant_evidence_leaves_the_custody_window_uncertain_not_pass():
    # The prep record is in scope and inside the window, but carries no measurement.
    c = charge(charge_type=ChargeType.FULFILMENT_FEE_WEIGHT_TIER, amount="4.25")
    d = run(c, [prep_all_pass()])
    assert _verdicts(d)["evidence_present"] == Verdict.FAIL
    window = d.check("evidence_in_custody_window")
    assert window.verdict == Verdict.UNCERTAIN
    assert window.detail == "no relevant evidence to check"


def test_no_in_scope_record_detail_says_there_is_nothing_to_check():
    c = charge(charge_type=ChargeType.FULFILMENT_FEE_WEIGHT_TIER, amount="4.25")
    d = run(c, [prep_all_pass(fba_shipment_id="FBA-OTHER")])
    window = d.check("evidence_in_custody_window")
    assert window.verdict == Verdict.UNCERTAIN
    assert (window.detail or "").startswith("no relevant evidence to check")


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


# --- filing window with an open day (D-017) ---------------------------------------------

# The shipped refund window (D-017): opens 60 and closes 120 days after the refund date.
REFUND_WINDOW = RULES
_refund_rule = RULES.filing_windows[ChargeType.REFUND_ISSUED_ITEM_NOT_RETURNED]
assert (_refund_rule.window_open_days, _refund_rule.window_close_days) == (60, 120)
# _refund_line() is posted 2026-06-24: the window opens 2026-08-23 and closes 2026-10-22.


def test_before_window_opens_a_would_be_do_not_claim_is_review_not_open():
    d = run(_refund_line(), [_returns()], rules=REFUND_WINDOW, as_of=date(2026, 8, 22))
    assert d.decision == Decision.REVIEW and d.rule_id == "R_FILING_WINDOW_NOT_OPEN"
    assert d.reason_code == ReasonCode.FILING_WINDOW_NOT_OPEN
    c = d.check("within_filing_window")
    assert c.verdict == Verdict.FAIL and "not yet eligible" in (c.detail or "")
    assert d.next_action is not None and "2026-08-23" in d.next_action
    assert "as a proxy for the customer refund or replacement date" in d.reason
    assert d.evidence_status == EvidenceStatus.CONTRADICTED  # evidence still assessed


def test_before_window_opens_a_would_be_claim_is_review_not_open():
    rules = rules_with_window(120, open_days=60)  # charge() posted 07-18: opens 09-16
    d = run(
        charge(defect_category="label"),
        [prep_all_pass()],
        rules=rules,
        as_of=date(2026, 9, 15),
    )
    assert d.decision == Decision.REVIEW and d.rule_id == "R_FILING_WINDOW_NOT_OPEN"
    assert d.claim is None


def test_inside_window_the_evidence_decides():
    d = run(_refund_line(), [_returns()], rules=REFUND_WINDOW, as_of=date(2026, 8, 23))
    assert d.decision == Decision.DO_NOT_CLAIM and d.rule_id == "R_ITEM_RETURNED"
    assert d.check("within_filing_window").verdict == Verdict.PASS
    assert d.warnings == []
    d = run(_refund_line(), [_returns(parts="FAIL")], rules=REFUND_WINDOW, as_of=AS_OF)
    assert d.rule_id == "R_RETURNED_INCOMPLETE_OR_DAMAGED"


def test_after_window_closes_is_do_not_claim_expired():
    d = run(_refund_line(), [_returns(parts="FAIL")], rules=REFUND_WINDOW, as_of=date(2026, 10, 23))
    assert d.decision == Decision.DO_NOT_CLAIM and d.rule_id == "R_FILING_WINDOW_PASSED"
    assert d.reason_code == ReasonCode.FILING_WINDOW_EXPIRED
    assert "as a proxy for the customer refund or replacement date" in d.reason
    assert d.check("within_filing_window").verdict == Verdict.FAIL


def test_unknown_window_on_a_loss_event_keeps_the_warning_and_evidence_decides():
    d = run(_refund_line(), [_returns(parts="FAIL")], rules=RULES_UNSOURCED)
    assert d.rule_id == "R_RETURNED_INCOMPLETE_OR_DAMAGED"
    assert d.check("within_filing_window").verdict == Verdict.UNCERTAIN
    assert d.warnings == ["filing deadline not verified"]


def test_cli_labels_the_decision_confidence_as_routing_confidence():
    from app.report import render_decision

    d = run(charge(defect_category="label"), [prep_all_pass()])
    head = render_decision(d)[0]
    assert f"routing confidence {d.confidence}" in head
    assert " confidence " not in head.replace("routing confidence", "")
