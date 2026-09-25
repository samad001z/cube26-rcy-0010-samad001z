"""Channel rules are accepted only with a source; engine config is typed and hashed."""

import copy
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from app.core.rules import (
    ENGINE_PATH,
    RULES_PATH,
    load_engine_config,
    load_rules,
    parse_engine_config,
    parse_rules,
)
from app.models.vocab import ChargeType

SOURCED = {
    "value": 90,
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
    assert set(rules.filing_window_days) == set(ChargeType)
    for rule in [*rules.filing_window_days.values(), rules.fulfilment_fee_schedule]:
        if rule.value is not None:
            assert rule.source_url and rule.retrieved_on and rule.excerpt
            assert rule.retrieved_by == "human"
    assert len(rules.rules_hash) == 64


def test_sourced_value_is_accepted():
    data = _rules()
    data["filing_window_days"]["inbound_defect_fee"] = SOURCED
    rules = parse_rules(data)
    rule = rules.filing_window_days[ChargeType.INBOUND_DEFECT_FEE]
    assert rule.verified and rule.value == 90


@pytest.mark.parametrize("missing", ["source_url", "retrieved_on", "retrieved_by", "excerpt"])
def test_value_without_full_source_is_refused(missing):
    data = _rules()
    entry = dict(SOURCED)
    entry[missing] = None
    data["filing_window_days"]["lost_inbound"] = entry
    with pytest.raises(ValidationError, match=missing):
        parse_rules(data)


def test_only_a_human_retrieval_is_accepted():
    data = _rules()
    data["filing_window_days"]["lost_inbound"] = {**SOURCED, "retrieved_by": "model"}
    with pytest.raises(ValidationError):
        parse_rules(data)


def test_secondary_source_never_supplies_a_value():
    data = _rules()
    data["filing_window_days"]["lost_inbound"] = {
        **SOURCED,
        "value": None,
        "secondary_sources": [{"url": "https://blog.example/guide", "note": "says 60 days"}],
    }
    rule = parse_rules(data).filing_window_days[ChargeType.LOST_INBOUND]
    assert rule.value is None and not rule.verified


def test_float_and_non_positive_windows_are_refused():
    data = _rules()
    data["filing_window_days"]["lost_inbound"] = {**SOURCED, "value": 60.0}
    with pytest.raises(ValidationError, match="float"):
        parse_rules(data)
    data["filing_window_days"]["lost_inbound"] = {**SOURCED, "value": 0}
    with pytest.raises(ValidationError, match="positive"):
        parse_rules(data)


def test_every_charge_type_must_be_listed():
    data = _rules()
    del data["filing_window_days"]["lost_inbound"]
    with pytest.raises(ValidationError, match="lost_inbound"):
        parse_rules(data)


def test_non_https_source_is_refused():
    data = _rules()
    data["filing_window_days"]["lost_inbound"] = {**SOURCED, "source_url": "http://x.org"}
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
