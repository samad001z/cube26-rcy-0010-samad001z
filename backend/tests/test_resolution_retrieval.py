from datetime import UTC, date, datetime

from app.core.rules import load_engine_config
from app.models.contract import EvidenceRecord
from app.models.vocab import ChargeType
from app.resolution import resolve_unit
from app.retrieval import in_custody_window, retrieve
from tests.factories import charge, record

CFG = load_engine_config()


def _at(y: int, m: int, d: int, h: int = 12) -> datetime:
    return datetime(y, m, d, h, tzinfo=UTC)


# --- resolution -----------------------------------------------------------------------


def test_no_record_for_the_unit_names_the_missing_link():
    res = resolve_unit(charge(unit_id="U-404"), [record(unit_id="U-1")])
    assert not res.resolved
    assert res.failure == "no upstream record carries unit_id U-404"


def test_sku_or_fnsku_conflict_fails_and_names_the_record():
    res = resolve_unit(charge(sku="SKU-1"), [record("PRP-9", sku="SKU-OTHER")])
    assert not res.resolved
    assert "sku conflict" in (res.failure or "") and "PRP-9" in (res.failure or "")
    res = resolve_unit(charge(fnsku="X-1"), [record("PRP-9", fnsku="X-2")])
    assert "fnsku conflict" in (res.failure or "")


def test_missing_key_on_either_side_is_not_a_conflict():
    res = resolve_unit(charge(sku=None), [record(sku="SKU-1"), record("RTN-1", sku=None)])
    assert res.resolved and res.unit_id == "U-1"


def test_records_of_another_org_are_ignored_even_if_passed_in():
    res = resolve_unit(charge(), [record(org="org_other")])
    assert not res.resolved


def test_receiving_records_are_noted_as_lot_level():
    res = resolve_unit(charge(), [record("RCV-1", agent="receiving"), record()])
    assert res.resolved
    assert res.notes == ("RCV-1 is a receiving record per PO line (lot), not per unit",)


def test_records_are_ordered_by_capture_time():
    late = record("PRP-2", captured=_at(2026, 6, 9))
    early = record("PRP-1", captured=_at(2026, 6, 1))
    assert [r.record_id for r in resolve_unit(charge(), [late, early]).records] == [
        "PRP-1",
        "PRP-2",
    ]


# --- retrieval ------------------------------------------------------------------------


def _one(c, r):
    cands = retrieve(c, resolve_unit(c, [r]), CFG)
    assert len(cands) == 1
    return cands[0]


def test_prep_before_posting_on_same_shipment_is_usable():
    cand = _one(charge(posted=date(2026, 7, 18)), record(captured=_at(2026, 6, 6)))
    assert cand.usable and "inside custody window" in cand.reason


def test_prep_on_or_after_posting_day_is_outside_window():
    cand = _one(charge(posted=date(2026, 7, 18)), record(captured=_at(2026, 7, 18, 0)))
    assert cand.in_scope and not cand.in_window


def test_prep_older_than_lookback_is_outside_window():
    cand = _one(charge(posted=date(2026, 7, 18)), record(captured=_at(2026, 3, 1)))
    assert not cand.in_window


def test_prep_on_another_shipment_is_out_of_scope():
    cand = _one(charge(fba_shipment_id="FBA-1"), record(fba_shipment_id="FBA-2"))
    assert not cand.in_scope
    assert "fba_shipment_id differs: charge FBA-1, PRP-1 FBA-2" in cand.reason


def test_pods_not_relevant_to_the_charge_type_are_not_returned():
    c = charge()
    res = resolve_unit(c, [record("RCV-1", agent="receiving"), record("RTN-1", agent="returns")])
    assert retrieve(c, res, CFG) == ()


def test_returns_window_around_posting_for_refund_line_matches_order():
    c = charge(
        charge_type=ChargeType.REFUND_ISSUED_ITEM_NOT_RETURNED,
        order_id="ORD-1",
        posted=date(2026, 6, 24),
    )
    same_day = record("RTN-1", agent="returns", order_id="ORD-1", captured=_at(2026, 6, 24, 8))
    other_order = record("RTN-2", agent="returns", order_id="ORD-2", captured=_at(2026, 6, 24))
    # D-019: the window after posting runs to the filing window's close (+120 days), so
    # the first day outside it is +121 (was +61 before D-019).
    too_late = record("RTN-3", agent="returns", order_id="ORD-1", captured=_at(2026, 10, 23))
    res = resolve_unit(c, [same_day, other_order, too_late])
    cands = {x.record.record_id: x for x in retrieve(c, res, CFG)}
    assert cands["RTN-1"].usable
    assert not cands["RTN-2"].in_scope
    assert cands["RTN-3"].in_scope and not cands["RTN-3"].in_window


def test_charge_without_the_match_key_cannot_scope_a_record():
    c = charge(charge_type=ChargeType.REFUND_ISSUED_ITEM_NOT_RETURNED, order_id=None)
    cand = _one(c, record("RTN-1", agent="returns", order_id="ORD-1"))
    assert not cand.in_scope and "charge has no order_id" in cand.reason


def test_lost_inbound_reads_later_returns_of_the_unit():
    c = charge(charge_type=ChargeType.LOST_INBOUND, posted=date(2026, 6, 19))
    ret = record("RTN-1", agent="returns", fba_shipment_id=None, captured=_at(2026, 6, 29))
    cand = _one(c, ret)
    assert cand.usable


def test_in_custody_window_helper_agrees_with_retrieve():
    c = charge(posted=date(2026, 7, 18))
    for captured in (_at(2026, 6, 6), _at(2026, 7, 18), _at(2026, 1, 1)):
        r = record(captured=captured)
        assert in_custody_window(c, r, CFG) == _one(c, r).in_window
    assert not in_custody_window(c, record("RTN-1", agent="returns"), CFG)


def test_refund_returns_custody_window_runs_to_the_filing_window_close():
    # D-019: posted 2026-06-24; the sourced filing window closes 120 days later (2026-10-22).
    c = charge(
        charge_type=ChargeType.REFUND_ISSUED_ITEM_NOT_RETURNED,
        amount="0.00",
        order_id="ORD-1",
        posted=date(2026, 6, 24),
    )

    def ret(when: datetime) -> EvidenceRecord:
        return record(
            "RTN-1", agent="returns", fba_shipment_id=None, order_id="ORD-1", captured=when
        )

    assert in_custody_window(c, ret(datetime(2026, 4, 25, tzinfo=UTC)), CFG)  # -60 days
    assert not in_custody_window(c, ret(datetime(2026, 4, 24, 23, tzinfo=UTC)), CFG)
    assert in_custody_window(c, ret(datetime(2026, 8, 23, tzinfo=UTC)), CFG)  # +60 (old end)
    assert in_custody_window(c, ret(datetime(2026, 9, 22, tzinfo=UTC)), CFG)  # +90
    assert in_custody_window(c, ret(datetime(2026, 10, 22, 23, 59, tzinfo=UTC)), CFG)  # +120
    assert not in_custody_window(c, ret(datetime(2026, 10, 23, tzinfo=UTC)), CFG)  # +121
