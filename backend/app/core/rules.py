"""Load channel rules (config/rules/) and engine configuration (config/engine.yaml).

Channel rules are authoritative only when sourced: a non-null value without a source URL,
retrieval date, `retrieved_by: human` and a verbatim excerpt is refused at load time.
Secondary sources are kept as notes and never supply a value.
"""

from datetime import date
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.config import REPO_ROOT
from app.core.hashing import content_hash
from app.models.vocab import ChargeType

RULES_PATH = REPO_ROOT / "config" / "rules" / "amazon_us.yaml"
ENGINE_PATH = REPO_ROOT / "config" / "engine.yaml"


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SecondarySource(_Strict):
    url: str
    note: str


class RuleValue(_Strict):
    value: int | str | list[str] | dict[str, Any] | None
    source_url: str | None
    retrieved_on: date | None
    retrieved_by: Literal["human"] | None
    excerpt: str | None
    secondary_sources: list[SecondarySource] = Field(default_factory=list)

    @field_validator("value", mode="before")
    @classmethod
    def _no_floats(cls, v: Any) -> Any:
        if isinstance(v, float):
            raise ValueError("rule values must not be floats; quote decimals as strings")
        return v

    @model_validator(mode="after")
    def _sourced(self) -> Self:
        if self.value is None:
            return self
        missing = [
            name
            for name in ("source_url", "retrieved_on", "retrieved_by", "excerpt")
            if not getattr(self, name)
        ]
        if missing:
            raise ValueError(f"rule value {self.value!r} has no {', '.join(missing)}")
        assert self.source_url is not None
        if not self.source_url.startswith("https://"):
            raise ValueError(f"source_url must be an https URL: {self.source_url!r}")
        return self

    @property
    def verified(self) -> bool:
        return self.value is not None


class ChannelRules(_Strict):
    channel: str
    filing_window_days: dict[ChargeType, RuleValue]
    fulfilment_fee_schedule: RuleValue
    # sha256 of the parsed file, stored on every decision so the rules used are traceable.
    rules_hash: str = ""

    @field_validator("filing_window_days")
    @classmethod
    def _every_type_listed(cls, v: dict[ChargeType, RuleValue]) -> dict[ChargeType, RuleValue]:
        missing = set(ChargeType) - set(v)
        if missing:
            raise ValueError(f"filing_window_days missing {sorted(missing)} (use value: null)")
        for ct, rule in v.items():
            if rule.value is not None and (not isinstance(rule.value, int) or rule.value <= 0):
                raise ValueError(f"filing window for {ct} must be a positive integer of days")
        return v


PodName = Literal["receiving", "prep", "pack", "returns"]


class PodRelevance(_Strict):
    window: Literal["before_posting", "after_posting", "around_posting"]
    max_days_before: int | None = None
    max_days_after: int | None = None
    match_keys: list[Literal["fba_shipment_id", "order_id"]] = Field(default_factory=list)

    @model_validator(mode="after")
    def _bounds(self) -> Self:
        need_before = self.window in ("before_posting", "around_posting")
        need_after = self.window in ("after_posting", "around_posting")
        if need_before and self.max_days_before is None:
            raise ValueError(f"{self.window} needs max_days_before")
        if need_after and self.max_days_after is None:
            raise ValueError(f"{self.window} needs max_days_after")
        return self


class ChargeTypeConfig(_Strict):
    kind: Literal["fee", "loss_event"]
    # full_amount: the whole fee; fee_difference: charged - correct fee (needs the fee
    # schedule); unit_value: needs an authoritative unit value (none in upstream data).
    claim_basis: Literal["full_amount", "fee_difference", "unit_value"]
    pods: dict[PodName, PodRelevance]
    scope_checks: list[str] = Field(default_factory=list)
    required_checks: list[str] = Field(default_factory=list)


class ConfidenceTable(_Strict):
    exact: Decimal
    operator_check: Decimal

    @field_validator("exact", "operator_check", mode="before")
    @classmethod
    def _decimal_str(cls, v: Any) -> Decimal:
        if not isinstance(v, str):
            raise ValueError("confidence values must be quoted decimal strings")
        d = Decimal(v)
        if not (Decimal(0) <= d <= Decimal(1)):
            raise ValueError("confidence must be within [0, 1]")
        return d


class DuplicateConfig(_Strict):
    window_days: int = Field(ge=0)


class EngineConfig(_Strict):
    charge_types: dict[ChargeType, ChargeTypeConfig]
    inbound_defect_categories: dict[str, list[str]]
    duplicate: DuplicateConfig
    confidence: ConfidenceTable
    config_hash: str = ""

    @field_validator("charge_types")
    @classmethod
    def _every_type(
        cls, v: dict[ChargeType, ChargeTypeConfig]
    ) -> dict[ChargeType, ChargeTypeConfig]:
        missing = set(ChargeType) - set(v)
        if missing:
            raise ValueError(f"charge_types missing {sorted(missing)}")
        return v


def _read(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a mapping")
    return data


def parse_rules(data: dict[str, Any]) -> ChannelRules:
    rules = ChannelRules.model_validate(data)  # validate first: it rejects floats clearly
    return rules.model_copy(update={"rules_hash": content_hash(data)})


def parse_engine_config(data: dict[str, Any]) -> EngineConfig:
    cfg = EngineConfig.model_validate(data)
    return cfg.model_copy(update={"config_hash": content_hash(data)})


@lru_cache
def load_rules(path: Path = RULES_PATH) -> ChannelRules:
    return parse_rules(_read(path))


@lru_cache
def load_engine_config(path: Path = ENGINE_PATH) -> EngineConfig:
    return parse_engine_config(_read(path))
