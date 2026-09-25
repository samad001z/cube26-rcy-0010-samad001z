"""Recovery's decision record, in the official evidence contract shape plus the recovery
fields CLAUDE.md requires for traceability (rule 10).

Contract fields: record_id, schema_version, organization_id, client_id, agent, subject,
captured_at, operator_label, images, checks, outcome, overrides, status, content_hash.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.hashing import content_hash
from app.models.contract import Check, Image, Outcome, Override
from app.models.vocab import (
    ChargeType,
    Decision,
    EvidenceStatus,
    ReasonCode,
    RecordStatus,
    ReportType,
)

SCHEMA_VERSION = "recovery_v1"
CitationRole = Literal["contradicts", "supports", "uncertain", "canonical_charge", "reimbursement"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Citation(_Frozen):
    """A pointer to ingested data the decision relies on. Never free text."""

    kind: Literal["evidence", "charge"]
    id: str  # evidence record_id or charge line_id
    content_hash: str
    role: CitationRole
    check_keys: list[str] = Field(default_factory=list)


class ConsideredRecord(_Frozen):
    """Every upstream record read for the charge, used or not, and why."""

    record_id: str
    agent: str
    content_hash: str
    used: bool
    reason: str


class DecisionSubject(_Frozen):
    line_id: str
    unit_id: str
    charge_type: ChargeType
    report_type: ReportType
    fba_shipment_id: str | None
    order_id: str | None
    defect_category: str | None
    charge_content_hash: str


class Claim(_Frozen):
    amount: Decimal
    currency: str
    computation: list[str]


class DecisionRecord(_Frozen):
    # contract fields
    record_id: str
    schema_version: str = SCHEMA_VERSION
    organization_id: str
    client_id: str
    agent: Literal["recovery"] = "recovery"
    subject: DecisionSubject
    captured_at: datetime
    operator_label: str | None = None
    images: list[Image] = Field(default_factory=list)
    checks: list[Check]
    outcome: Outcome
    overrides: list[Override] = Field(default_factory=list)
    status: RecordStatus
    content_hash: str | None = None
    # recovery fields
    run_id: str
    decision: Decision
    evidence_status: EvidenceStatus
    reason_code: ReasonCode | None
    rule_id: str
    rule_path: list[str]
    reason: str
    warnings: list[str] = Field(default_factory=list)
    next_action: str | None = None
    confidence: Decimal = Field(ge=0, le=1)
    coverage: Decimal | None = None
    amount_charged: Decimal
    amount_reimbursed: Decimal
    currency: str
    claim: Claim | None
    citations: list[Citation]
    evidence_considered: list[ConsideredRecord]
    resolved_unit: str | None
    engine_version: str
    rules_hash: str
    config_hash: str
    model_version: str | None = None

    @field_validator("captured_at")
    @classmethod
    def _aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")
        return v

    def check(self, key: str) -> Check:
        return next(c for c in self.checks if c.check_key == key)

    def _hash_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="python", exclude={"content_hash"})

    def compute_hash(self) -> str:
        return content_hash(self._hash_payload())

    def with_hash(self) -> Self:
        return self.model_copy(update={"content_hash": self.compute_hash()})

    def verify_hash(self) -> bool:
        return self.content_hash is not None and self.content_hash == self.compute_hash()
