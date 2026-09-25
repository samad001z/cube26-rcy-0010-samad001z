"""Resolve a charge to its unit and the upstream records that carry that unit.

Resolution fails, naming the missing or conflicting link, when no upstream record carries
the charge's unit_id, or when a record's identity keys (sku, fnsku) disagree with the
charge. Keys that identify an event rather than the item (fba_shipment_id, order_id) are
not identity keys; retrieval uses them to decide scope.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from app.models.charge import Charge
from app.models.contract import EvidenceRecord

IDENTITY_KEYS = ("sku", "fnsku")


@dataclass(frozen=True)
class Resolution:
    unit_id: str | None
    records: tuple[EvidenceRecord, ...]
    failure: str | None
    notes: tuple[str, ...] = ()

    @property
    def resolved(self) -> bool:
        return self.failure is None


def resolve_unit(charge: Charge, candidates: Sequence[EvidenceRecord]) -> Resolution:
    records = tuple(
        sorted(
            (
                r
                for r in candidates
                if r.subject.unit_id == charge.unit_id
                and r.organization_id == charge.organization_id
            ),
            key=lambda r: (r.captured_at, r.record_id),
        )
    )
    if not records:
        return Resolution(None, (), f"no upstream record carries unit_id {charge.unit_id}")
    for r in records:
        for key in IDENTITY_KEYS:
            ours, theirs = getattr(charge, key), getattr(r.subject, key)
            if ours is not None and theirs is not None and ours != theirs:
                return Resolution(
                    None,
                    records,
                    f"{key} conflict for {charge.unit_id}: charge has {ours}, "
                    f"{r.record_id} has {theirs}",
                )
    notes = tuple(
        f"{r.record_id} is a receiving record per PO line (lot), not per unit"
        for r in records
        if r.agent == "receiving"
    )
    return Resolution(charge.unit_id, records, None, notes)
