"""Evidence record in the official contract shape (field list in CLAUDE.md).

The exact types of `subject`, `agent`, `images`, `outcome` and `status` were not in the
repo; the choices made here are recorded in docs/DECISIONS.md (D-008).
"""

from datetime import datetime
from decimal import Decimal
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.hashing import content_hash
from app.models.vocab import RecordStatus, Verdict


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def _require_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return value


class Check(_Frozen):
    check_key: str
    verdict: Verdict
    # None = no model or rule produced a confidence (e.g. a human operator's judgment).
    confidence: Decimal | None = Field(default=None, ge=0, le=1)
    detail: str | None = None
    model_version: str | None = None
    latency_ms: int | None = Field(default=None, ge=0)


class Outcome(_Frozen):
    decision: str
    decided_by: str
    decided_at: datetime

    _aware = field_validator("decided_at")(_require_aware)


class Override(_Frozen):
    """A human override. Stored as data; never overwrites the original outcome."""

    original_decision: str
    new_decision: str
    reason: str = Field(min_length=1)
    reviewer: str
    at: datetime

    _aware = field_validator("at")(_require_aware)


class Image(_Frozen):
    # Non-guessable, org-scoped key (HMAC). The raw source path is not exposed here.
    key: str
    source_ref: str | None = None


class Subject(_Frozen):
    unit_id: str
    sku: str | None = None
    fnsku: str | None = None
    asin: str | None = None
    fba_shipment_id: str | None = None
    order_id: str | None = None
    po_number: str | None = None
    po_line: str | None = None
    # Requirement flags the operator's work order carried (e.g. wo_polybag). Recorded so
    # rules can see what was required without parsing the raw row. Not authoritative.
    requirements: dict[str, str] = Field(default_factory=dict)


class EvidenceRecord(_Frozen):
    record_id: str
    schema_version: str
    organization_id: str
    client_id: str
    agent: str
    subject: Subject
    captured_at: datetime
    operator_label: str | None = None
    images: list[Image] = Field(default_factory=list)
    checks: list[Check] = Field(default_factory=list)
    outcome: Outcome | None = None
    overrides: list[Override] = Field(default_factory=list)
    status: RecordStatus
    content_hash: str | None = None

    _aware = field_validator("captured_at")(_require_aware)

    def _hash_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="python", exclude={"content_hash"})

    def compute_hash(self) -> str:
        return content_hash(self._hash_payload())

    def with_hash(self) -> Self:
        return self.model_copy(update={"content_hash": self.compute_hash()})

    def verify_hash(self) -> bool:
        return self.content_hash is not None and self.content_hash == self.compute_hash()


__all__ = ["Check", "EvidenceRecord", "Image", "Outcome", "Override", "Subject"]
