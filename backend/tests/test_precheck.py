from datetime import date
from decimal import Decimal

from app.core.rules import load_engine_config, load_rules, parse_rules
from app.models.charge import Charge
from app.models.vocab import ChargeType, ReportType, Verdict
from app.precheck import (
    filing_window,
    find_duplicates,
    match_reimbursements,
    run_prechecks,
)
from tests.factories import charge
from tests.test_rules_config import SOURCED, _rules

CFG = load_engine_config()
RULES = load_rules()


# --- duplicates ------------------------------------------------------------------------


def test_identical_fee_lines_within_window_later_one_is_duplicate():
    a = charge("L-1", posted=date(2026, 7, 1))
    b = charge("L-2", posted=date(2026, 7, 10))
    dups = find_duplicates([b, a], CFG)
    assert dups == {"L-2": a}


def test_same_day_duplicates_use_line_id_order():
    a = charge("L-1")
    b = charge("L-2")
    assert find_duplicates([b, a], CFG) == {"L-2": a}


def test_outside_window_is_not_a_duplicate():
    a = charge("L-1", posted=date(2026, 5, 1))
    b = charge("L-2", posted=date(2026, 7, 1))
    assert find_duplicates([a, b], CFG) == {}


def test_any_differing_key_means_not_duplicate():
    base = charge("L-1")
    for other in (
        charge("L-2", amount="2.01"),
        charge("L-2", unit_id="U-2"),
        charge("L-2", quantity=2),
        charge("L-2", fba_shipment_id="FBA-2"),
        charge("L-2", charge_type=ChargeType.FULFILMENT_FEE_WEIGHT_TIER),
    ):
        assert find_duplicates([base, other], CFG) == {}


def test_zero_amount_and_loss_events_are_never_duplicates():
    z1, z2 = charge("L-1", amount="0.00"), charge("L-2", amount="0.00")
    l1 = charge("L-3", charge_type=ChargeType.LOST_INBOUND, amount="0.00")
    l2 = charge("L-4", charge_type=ChargeType.LOST_INBOUND, amount="0.00")
    assert find_duplicates([z1, z2, l1, l2], CFG) == {}


def test_triplicate_points_every_copy_at_the_first():
    a, b, c = charge("L-1"), charge("L-2"), charge("L-3")
    assert find_duplicates([c, b, a], CFG) == {"L-2": a, "L-3": a}


# --- already reimbursed ---------------------------------------------------------------


def _refund(line_id: str, amount: str, **kw) -> Charge:
    return charge(line_id, report_type=ReportType.REIMBURSEMENT_REPORT, amount=amount, **kw)


def test_refund_on_same_unit_and_type_offsets_the_fee():
    fee = charge("L-1", posted=date(2026, 7, 1))
    r = _refund("R-1", "2.00", posted=date(2026, 7, 5))
    m = match_reimbursements([fee, r], CFG)
    assert m.allocated == {"L-1": ((r, Decimal("2.00")),)} and m.ambiguous == {}


def test_refund_that_fits_two_different_fees_is_ambiguous_not_allocated():
    # Replaces an earlier expectation (allocate to the earliest fee) that let a later fee
    # be claimed after it was refunded; see rules review M2 and D-015.
    f1 = charge("L-1", posted=date(2026, 7, 1))
    f2 = charge("L-2", posted=date(2026, 7, 2), amount="3.00")
    r = _refund("R-1", "2.00", posted=date(2026, 7, 5))
    m = match_reimbursements([f2, f1, r], CFG)
    assert m.allocated == {}
    assert m.ambiguous == {"L-1": (r,), "L-2": (r,)}


def test_refund_within_a_duplicate_group_goes_to_the_duplicate_first():
    f1 = charge("L-1", posted=date(2026, 7, 1))
    f2 = charge("L-2", posted=date(2026, 7, 2))
    r = _refund("R-1", "3.00", posted=date(2026, 7, 5))
    m = match_reimbursements([f1, f2, r], CFG)
    assert m.allocated == {"L-2": ((r, Decimal("2.00")),), "L-1": ((r, Decimal("1.00")),)}


def test_refund_before_the_fee_other_unit_or_type_does_not_match():
    fee = charge("L-1", posted=date(2026, 7, 10))
    early = _refund("R-1", "2.00", posted=date(2026, 7, 1))
    other_unit = _refund("R-2", "2.00", unit_id="U-9", posted=date(2026, 7, 11))
    other_type = _refund(
        "R-3",
        "2.00",
        charge_type=ChargeType.FULFILMENT_FEE_WEIGHT_TIER,
        posted=date(2026, 7, 11),
    )
    m = match_reimbursements([fee, early, other_unit, other_type], CFG)
    assert m.allocated == {} and m.ambiguous == {}


def test_loss_event_reimbursement_never_offsets_a_fee():
    fee = charge("L-1", posted=date(2026, 6, 1))
    paid = _refund(
        "R-1", "14.00", charge_type=ChargeType.DAMAGED_IN_WAREHOUSE, posted=date(2026, 6, 27)
    )
    m = match_reimbursements([fee, paid], CFG)
    assert m.allocated == {} and m.ambiguous == {}


def test_run_prechecks_sums_reimbursed_amount_as_decimal():
    fee = charge("L-1", amount="5.00", posted=date(2026, 7, 1))
    r1 = _refund("R-1", "1.25", posted=date(2026, 7, 2))
    r2 = _refund("R-2", "0.75", posted=date(2026, 7, 3))
    pre = run_prechecks([fee, r1, r2], RULES, CFG, date(2026, 9, 25))
    assert pre["L-1"].reimbursed_amount == Decimal("2.00")
    assert [r.line_id for r in pre["L-1"].reimbursements] == ["R-1", "R-2"]
    assert pre["R-1"].reimbursed_amount == Decimal("0.00")


# --- filing window --------------------------------------------------------------------


def _rules_with_window(days: int | None, open_days: int | None = None):
    data = _rules()
    data["filing_windows"]["inbound_defect_fee"] = {
        **SOURCED,
        "window_open_days": open_days,
        "window_close_days": days,
    }
    return parse_rules(data)


def test_unknown_window_is_uncertain_with_the_warning_text():
    fw = filing_window(charge(), RULES, date(2026, 9, 25))
    assert fw.verdict == Verdict.UNCERTAIN and fw.state == "unknown"
    assert fw.deadline is None
    assert "filing deadline not verified" in fw.detail


def test_known_window_open_and_passed():
    rules = _rules_with_window(30)
    c = charge(posted=date(2026, 7, 18))
    open_ = filing_window(c, rules, date(2026, 8, 17))
    assert open_.verdict == Verdict.PASS and open_.deadline == date(2026, 8, 17)
    assert open_.state == "open"
    passed = filing_window(c, rules, date(2026, 8, 18))
    assert passed.verdict == Verdict.FAIL and passed.state == "passed"
    assert "https://example.org/help/page" in passed.detail


def test_window_with_open_day_before_inside_and_after():
    # 60-120 days after posting, as the refund window: opens 09-16, closes 11-15.
    rules = _rules_with_window(120, open_days=60)
    c = charge(posted=date(2026, 7, 18))
    before = filing_window(c, rules, date(2026, 9, 15))
    assert before.state == "not_open" and before.verdict == Verdict.FAIL
    assert before.opens == date(2026, 9, 16) and "not yet eligible" in before.detail
    first_day = filing_window(c, rules, date(2026, 9, 16))
    assert first_day.state == "open" and first_day.verdict == Verdict.PASS
    last_day = filing_window(c, rules, date(2026, 11, 15))
    assert last_day.state == "open" and last_day.deadline == date(2026, 11, 15)
    after = filing_window(c, rules, date(2026, 11, 16))
    assert after.state == "passed" and after.verdict == Verdict.FAIL


def test_open_day_known_but_close_unknown_is_uncertain_once_open():
    rules = _rules_with_window(None, open_days=60)
    c = charge(posted=date(2026, 7, 18))
    assert filing_window(c, rules, date(2026, 9, 15)).state == "not_open"
    fw = filing_window(c, rules, date(2026, 9, 16))
    assert fw.state == "unknown" and fw.verdict == Verdict.UNCERTAIN
    assert "filing deadline not verified" in fw.detail
