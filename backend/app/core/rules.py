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
        if isinstance(v, bool):
            raise ValueError("rule values must not be booleans; a window must be a positive int")
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


class FilingWindowRule(_Strict):
    """A sourced filing window: a claim may be filed from `window_open_days` after the anchor
    date (null: from day 0) up to `window_close_days` after it (null: not sourced)."""

    window_open_days: int | None = None
    window_close_days: int | None = None
    # The event the published window counts from, in the source's words.
    anchor: str | None = None
    source_url: str | None
    source_type: str | None = None
    retrieved_on: date | None
    retrieved_by: Literal["human"] | None
    excerpt: str | None
    # How this project applies the rule where the data differs from the source (e.g. a proxy).
    assumption: str | None = None
    caveat: str | None = None
    secondary_sources: list[SecondarySource] = Field(default_factory=list)

    @field_validator("window_open_days", "window_close_days", mode="before")
    @classmethod
    def _positive_int(cls, v: Any) -> Any:
        if v is None:
            return v
        if isinstance(v, float):
            raise ValueError("window days must not be floats")
        if isinstance(v, bool):
            raise ValueError("window days must not be booleans; use a positive int")
        if not isinstance(v, int) or v <= 0:
            raise ValueError("window days must be a positive integer")
        return v

    @model_validator(mode="after")
    def _sourced(self) -> Self:
        if not self.verified:
            return self
        missing = [
            name
            for name in ("source_url", "retrieved_on", "retrieved_by", "excerpt")
            if not getattr(self, name)
        ]
        if missing:
            raise ValueError(f"filing window has no {', '.join(missing)}")
        assert self.source_url is not None
        if not self.source_url.startswith("https://"):
            raise ValueError(f"source_url must be an https URL: {self.source_url!r}")
        if (
            self.window_open_days is not None
            and self.window_close_days is not None
            and self.window_open_days >= self.window_close_days
        ):
            raise ValueError("window_open_days must be less than window_close_days")
        return self

    @property
    def verified(self) -> bool:
        return self.window_open_days is not None or self.window_close_days is not None


class UnmappedRule(FilingWindowRule):
    """A sourced rule for a claim type no charge type maps to yet. Stored, never read by the
    engine."""

    id: str
    claim_type: str
    applies_to: None = None


class ChannelRules(_Strict):
    channel: str
    filing_windows: dict[ChargeType, FilingWindowRule]
    fulfilment_fee_schedule: RuleValue
    unmapped_rules: list[UnmappedRule] = Field(default_factory=list)
    # sha256 of the parsed file, stored on every decision so the rules used are traceable.
    rules_hash: str = ""

    @field_validator("filing_windows")
    @classmethod
    def _every_type_listed(
        cls, v: dict[ChargeType, FilingWindowRule]
    ) -> dict[ChargeType, FilingWindowRule]:
        missing = set(ChargeType) - set(v)
        if missing:
            raise ValueError(f"filing_windows missing {sorted(missing)} (use null values)")
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


class LossOutcome(_Strict):
    """One row of the per-charge-type loss-event mapping (D-016)."""

    evidence_status: Literal["CONTRADICTED", "SUPPORTED"]
    # A loss event is never CLAIM: what is owed needs a unit value (D-011).
    decision: Literal["DO_NOT_CLAIM", "REVIEW"]
    rule_id: str
    reason: str
    next_action: str | None = None
    # True on the claim path: evidence supports the loss, REVIEW until an amount exists.
    amount_needed: bool = False

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.amount_needed and (
            self.decision != "REVIEW" or self.evidence_status != "SUPPORTED"
        ):
            raise ValueError("amount_needed rows must be REVIEW with SUPPORTED evidence")
        if self.decision == "REVIEW" and not self.amount_needed and not self.next_action:
            raise ValueError(f"{self.rule_id}: a REVIEW row needs a next_action")
        if self.decision == "DO_NOT_CLAIM" and self.next_action:
            raise ValueError(f"{self.rule_id}: a DO_NOT_CLAIM row takes no next_action")
        return self


class LossEventMapping(_Strict):
    outcomes: dict[str, LossOutcome]
    no_evidence: str | None = None


class DuplicateConfig(_Strict):
    window_days: int = Field(ge=0)


class EngineConfig(_Strict):
    charge_types: dict[ChargeType, ChargeTypeConfig]
    inbound_defect_categories: dict[str, list[str]]
    loss_event_outcomes: dict[ChargeType, LossEventMapping]
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

    @model_validator(mode="after")
    def _loss_mapping_matches_kinds(self) -> Self:
        loss = {ct for ct, c in self.charge_types.items() if c.kind == "loss_event"}
        if set(self.loss_event_outcomes) != loss:
            raise ValueError(
                "loss_event_outcomes must list exactly the loss_event charge types "
                f"{sorted(loss)}, got {sorted(self.loss_event_outcomes)}"
            )
        return self


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
