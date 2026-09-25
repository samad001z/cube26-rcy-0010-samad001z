"""Channel rules are accepted only with a source; engine config is typed and hashed."""

import copy
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from app.core.rules import (
    ENGINE_PATH,
    RULES_PATH,
    FilingWindowRule,
    RuleValue,
    check_windows_consistent,
    load_engine_config,
    load_rules,
    parse_engine_config,
    parse_rules,
)
from app.models.vocab import ChargeType

SOURCED: dict[str, Any] = {
    "window_open_days": None,
    "window_close_days": 90,
    "source_url": "https://example.org/help/page",
    "retrieved_on": "2026-09-25",
    "retrieved_by": "human",
    "excerpt": "verbatim text from the page",
    "secondary_sources": [],
}


def _rules() -> dict[str, Any]:
    return copy.deepcopy(yaml.safe_load(RULES_PATH.read_text()))


def test_shipped_rules_load_and_every_value_is_either_null_or_sourced():
    rules = load_rules()
    assert set(rules.filing_windows) == set(ChargeType)
    windows: list[FilingWindowRule] = [*rules.filing_windows.values(), *rules.unmapped_rules]
    sourced: list[FilingWindowRule | RuleValue] = [*windows, rules.fulfilment_fee_schedule]
    for rule in sourced:
        if rule.verified:
            assert rule.source_url and rule.retrieved_on and rule.excerpt
            assert rule.retrieved_by == "human"
    assert len(rules.rules_hash) == 64


def test_sourced_value_is_accepted():
    data = _rules()
    data["filing_windows"]["inbound_defect_fee"] = SOURCED
    rules = parse_rules(data)
    rule = rules.filing_windows[ChargeType.INBOUND_DEFECT_FEE]
    assert rule.verified and rule.window_close_days == 90


@pytest.mark.parametrize("missing", ["source_url", "retrieved_on", "retrieved_by", "excerpt"])
def test_value_without_full_source_is_refused(missing):
    data = _rules()
    entry = dict(SOURCED)
    entry[missing] = None
    data["filing_windows"]["lost_inbound"] = entry
    with pytest.raises(ValidationError, match=missing):
        parse_rules(data)


def test_only_a_human_retrieval_is_accepted():
    data = _rules()
    data["filing_windows"]["lost_inbound"] = {**SOURCED, "retrieved_by": "model"}
    with pytest.raises(ValidationError):
        parse_rules(data)


def test_secondary_source_never_supplies_a_value():
    data = _rules()
    data["filing_windows"]["lost_inbound"] = {
        **SOURCED,
        "window_close_days": None,
        "secondary_sources": [{"url": "https://blog.example/guide", "note": "says 60 days"}],
    }
    rule = parse_rules(data).filing_windows[ChargeType.LOST_INBOUND]
    assert rule.window_close_days is None and not rule.verified


def test_float_and_non_positive_windows_are_refused():
    data = _rules()
    data["filing_windows"]["lost_inbound"] = {**SOURCED, "window_close_days": 60.0}
    with pytest.raises(ValidationError, match="float"):
        parse_rules(data)
    data["filing_windows"]["lost_inbound"] = {**SOURCED, "window_close_days": 0}
    with pytest.raises(ValidationError, match="positive"):
        parse_rules(data)


def test_every_charge_type_must_be_listed():
    data = _rules()
    del data["filing_windows"]["lost_inbound"]
    with pytest.raises(ValidationError, match="lost_inbound"):
        parse_rules(data)


def test_non_https_source_is_refused():
    data = _rules()
    data["filing_windows"]["lost_inbound"] = {**SOURCED, "source_url": "http://x.org"}
    with pytest.raises(ValidationError, match="https"):
        parse_rules(data)


def test_engine_config_loads_with_every_charge_type_and_decimal_confidence():
    cfg = load_engine_config()
    assert set(cfg.charge_types) == set(ChargeType)
    assert str(cfg.confidence.exact) == "1.00"
    assert len(cfg.config_hash) == 64
    # Every category maps to checks the prep adapter can produce.
    prep_checks = set(cfg.charge_types[ChargeType.INBOUND_DEFECT_FEE].scope_checks)
    for checks in cfg.inbound_defect_categories.values():
        assert set(checks) <= prep_checks


def test_engine_config_refuses_unquoted_float_confidence():
    data = yaml.safe_load(ENGINE_PATH.read_text())
    data["confidence"]["exact"] = 1.0
    with pytest.raises(ValidationError, match="quoted"):
        parse_engine_config(data)


def test_zero_amount_kinds_are_as_decided_in_d011():
    cfg = load_engine_config()
    kinds = {ct: c.kind for ct, c in cfg.charge_types.items()}
    assert kinds == {
        ChargeType.INBOUND_DEFECT_FEE: "fee",
        ChargeType.FULFILMENT_FEE_WEIGHT_TIER: "fee",
        ChargeType.LOST_INBOUND: "loss_event",
        ChargeType.DAMAGED_IN_WAREHOUSE: "loss_event",
        ChargeType.REFUND_ISSUED_ITEM_NOT_RETURNED: "loss_event",
    }


def test_boolean_window_is_refused():
    data = _rules()
    data["filing_windows"]["lost_inbound"] = {**SOURCED, "window_close_days": True}
    with pytest.raises(ValidationError, match="boolean"):
        parse_rules(data)


def test_shipped_windows_are_the_sourced_2024_announcement_values():
    rules = load_rules()
    w = rules.filing_windows
    refund = w[ChargeType.REFUND_ISSUED_ITEM_NOT_RETURNED]
    assert (refund.window_open_days, refund.window_close_days) == (60, 120)
    damaged = w[ChargeType.DAMAGED_IN_WAREHOUSE]
    assert (damaged.window_open_days, damaged.window_close_days) == (None, 60)
    for rule in (refund, damaged):
        assert rule.source_type == "official_announcement"
        assert rule.assumption and "posted_date" in rule.assumption
        assert rule.caveat and "superseded" in rule.caveat
    # The announcement does not cover these; they must stay unsourced.
    for ct in (
        ChargeType.LOST_INBOUND,
        ChargeType.INBOUND_DEFECT_FEE,
        ChargeType.FULFILMENT_FEE_WEIGHT_TIER,
    ):
        assert not w[ct].verified, ct
    assert {r.id: (r.window_open_days, r.window_close_days) for r in rules.unmapped_rules} == {
        "removal_lost_in_transit": (15, 75),
        "removal_other": (None, 60),
    }
    assert all(r.applies_to is None and r.excerpt for r in rules.unmapped_rules)


def test_open_day_without_a_source_is_refused():
    data = _rules()
    data["filing_windows"]["lost_inbound"] = {
        **SOURCED,
        "window_open_days": 30,
        "window_close_days": None,
        "excerpt": None,
    }
    with pytest.raises(ValidationError, match="excerpt"):
        parse_rules(data)


def test_open_day_must_be_before_close_day():
    data = _rules()
    data["filing_windows"]["lost_inbound"] = {
        **SOURCED,
        "window_open_days": 90,
        "window_close_days": 90,
    }
    with pytest.raises(ValidationError, match="less than"):
        parse_rules(data)


def test_unmapped_rule_cannot_be_applied_to_a_charge_type():
    data = _rules()
    data["unmapped_rules"][0]["applies_to"] = "lost_inbound"
    with pytest.raises(ValidationError):
        parse_rules(data)


def test_shipped_custody_windows_cover_the_sourced_filing_windows():
    check_windows_consistent(load_rules(), load_engine_config())


def test_custody_window_ending_before_the_filing_window_closes_is_refused():
    # D-019: a returns window that stops at +60 while claims can be filed until +120 would
    # read a late but genuine return as "no return".
    data = yaml.safe_load(ENGINE_PATH.read_text())
    data["charge_types"]["refund_issued_item_not_returned"]["pods"]["returns"]["max_days_after"] = (
        60
    )
    with pytest.raises(ValueError, match="before the sourced filing window closes at 120"):
        check_windows_consistent(load_rules(), parse_engine_config(data))
