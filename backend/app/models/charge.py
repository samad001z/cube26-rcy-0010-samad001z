"""A parsed line from a channel fee, adjustment or reimbursement report."""

from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from app.core.hashing import content_hash
from app.core.money import to_money
from app.models.vocab import ChargeType, ReportType


class SourceRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    file_sha256: str
    row: int  # 1-based data row (header excluded)
    raw: dict[str, str]  # the untouched original row


class Charge(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    line_id: str
    report_type: ReportType
    organization_id: str
    unit_id: str
    sku: str | None = None
    fnsku: str | None = None
    fba_shipment_id: str | None = None
    order_id: str | None = None
    charge_type: ChargeType
    quantity: int
    # Exactly as reported. 0.00 is ingested faithfully; its meaning is a Day 2 rule question.
    amount: Decimal
    currency: str = "USD"
    posted_date: date
    # Optional column, absent in the csv_v0 sample. For inbound defect fees it names the
    # defect the channel charged for; without it evidence cannot cover the charge (D-013).
    defect_category: str | None = None
    source: SourceRef

    @field_validator("amount", mode="before")
    @classmethod
    def _money(cls, value: Any) -> Decimal:
        try:
            return to_money(value)
        except TypeError as exc:
            raise ValueError(str(exc)) from exc

    @field_validator("quantity")
    @classmethod
    def _positive_qty(cls, value: int) -> int:
        if value < 1:
            raise ValueError("quantity must be >= 1")
        return value

    def compute_hash(self) -> str:
        """Content hash of the charge as ingested, so decisions can cite it."""
        return content_hash(self.model_dump(mode="python"))
