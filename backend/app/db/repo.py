"""Typed reads and writes. Callers pass an org-scoped session (see db.session.org_session);
row-level security, not these functions, is what enforces tenancy."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.adapters.csv_v0 import AttachmentRef, Quarantined
from app.db import tables as t
from app.models.charge import Charge, SourceRef
from app.models.contract import EvidenceRecord
from app.models.decision import DecisionRecord


@dataclass(frozen=True)
class AttachmentRow:
    key: str
    organization_id: str
    record_id: str
    source_path: str


def upsert_ingest_file(
    session: Session, organization_id: str, file_name: str, sha256: str, kind: str
) -> uuid.UUID:
    stmt = (
        insert(t.ingest_files)
        .values(organization_id=organization_id, file_name=file_name, sha256=sha256, kind=kind)
        .on_conflict_do_nothing(index_elements=["organization_id", "sha256"])
        .returning(t.ingest_files.c.id)
    )
    new_id = session.execute(stmt).scalar_one_or_none()
    if new_id is not None:
        return new_id
    return session.execute(
        sa.select(t.ingest_files.c.id).where(t.ingest_files.c.sha256 == sha256)
    ).scalar_one()


def insert_records(
    session: Session,
    records: Sequence[EvidenceRecord],
    sources: dict[str, SourceRef],
    ingest_file_id: uuid.UUID,
) -> int:
    """Returns the number of newly inserted rows; existing (org, record_id) rows are kept."""
    inserted = 0
    for r in records:
        stmt = (
            insert(t.evidence_records)
            .values(
                organization_id=r.organization_id,
                record_id=r.record_id,
                agent=r.agent,
                unit_id=r.subject.unit_id,
                fba_shipment_id=r.subject.fba_shipment_id,
                order_id=r.subject.order_id,
                captured_at=r.captured_at,
                status=r.status.value,
                content_hash=r.content_hash,
                body=r.model_dump(mode="json"),
                source=sources[r.record_id].model_dump(mode="json"),
                ingest_file_id=ingest_file_id,
            )
            .on_conflict_do_nothing(index_elements=["organization_id", "record_id"])
            .returning(t.evidence_records.c.id)
        )
        inserted += len(session.execute(stmt).all())
    return inserted


def insert_attachments(session: Session, attachments: Sequence[AttachmentRef]) -> int:
    inserted = 0
    for a in attachments:
        stmt = (
            insert(t.attachments)
            .values(
                key=a.key,
                organization_id=a.organization_id,
                record_id=a.record_id,
                source_path=a.source_path,
            )
            .on_conflict_do_nothing(index_elements=["key"])
            .returning(t.attachments.c.key)
        )
        inserted += len(session.execute(stmt).all())
    return inserted


def insert_charges(session: Session, charges: Sequence[Charge], ingest_file_id: uuid.UUID) -> int:
    inserted = 0
    for c in charges:
        stmt = (
            insert(t.charges)
            .values(
                organization_id=c.organization_id,
                line_id=c.line_id,
                report_type=c.report_type.value,
                charge_type=c.charge_type.value,
                unit_id=c.unit_id,
                fba_shipment_id=c.fba_shipment_id,
                order_id=c.order_id,
                quantity=c.quantity,
                amount=c.amount,
                currency=c.currency,
                posted_date=c.posted_date,
                body=c.model_dump(mode="json"),
                ingest_file_id=ingest_file_id,
            )
            .on_conflict_do_nothing(index_elements=["organization_id", "line_id"])
            .returning(t.charges.c.id)
        )
        inserted += len(session.execute(stmt).all())
    return inserted


def insert_quarantined(session: Session, organization_id: str, rows: Sequence[Quarantined]) -> None:
    for q in rows:
        session.execute(
            insert(t.quarantined_rows).values(
                organization_id=organization_id,
                file_name=q.file,
                row=q.row,
                reason=q.reason,
                raw=q.raw,
            )
        )


def add_audit_event(
    session: Session, organization_id: str, event_type: str, payload: dict[str, object]
) -> None:
    session.execute(
        insert(t.audit_events).values(
            organization_id=organization_id, event_type=event_type, payload=payload
        )
    )


def get_record(session: Session, record_id: str) -> EvidenceRecord | None:
    body = session.execute(
        sa.select(t.evidence_records.c.body).where(t.evidence_records.c.record_id == record_id)
    ).scalar_one_or_none()
    return EvidenceRecord.model_validate(body) if body is not None else None


def get_attachment(session: Session, key: str) -> AttachmentRow | None:
    row = session.execute(sa.select(t.attachments).where(t.attachments.c.key == key)).first()
    if row is None:
        return None
    return AttachmentRow(row.key, row.organization_id, row.record_id, row.source_path)


def list_charges(session: Session) -> list[Charge]:
    bodies: Sequence[Any] = (
        session.execute(sa.select(t.charges.c.body).order_by(t.charges.c.line_id)).scalars().all()
    )
    return [Charge.model_validate(b) for b in bodies]


def count_rows(session: Session, table: sa.Table) -> int:
    return session.execute(sa.select(sa.func.count()).select_from(table)).scalar_one()


def list_records(session: Session) -> list[EvidenceRecord]:
    bodies: Sequence[Any] = (
        session.execute(
            sa.select(t.evidence_records.c.body).order_by(t.evidence_records.c.record_id)
        )
        .scalars()
        .all()
    )
    return [EvidenceRecord.model_validate(b) for b in bodies]


def get_record_with_hash(session: Session, record_id: str) -> tuple[EvidenceRecord, str] | None:
    """The record body and the content_hash column written at ingestion."""
    row = session.execute(
        sa.select(t.evidence_records.c.body, t.evidence_records.c.content_hash).where(
            t.evidence_records.c.record_id == record_id
        )
    ).first()
    if row is None:
        return None
    return EvidenceRecord.model_validate(row.body), row.content_hash


def get_charge(session: Session, line_id: str) -> Charge | None:
    body = session.execute(
        sa.select(t.charges.c.body).where(t.charges.c.line_id == line_id)
    ).scalar_one_or_none()
    return Charge.model_validate(body) if body is not None else None


def insert_decision(session: Session, d: DecisionRecord) -> None:
    session.execute(
        insert(t.decisions).values(
            organization_id=d.organization_id,
            run_id=uuid.UUID(d.run_id),
            record_id=d.record_id,
            line_id=d.subject.line_id,
            decision=d.decision.value,
            evidence_status=d.evidence_status.value,
            reason_code=d.reason_code.value if d.reason_code else None,
            rule_id=d.rule_id,
            status=d.status.value,
            claim_amount=d.claim.amount if d.claim else None,
            content_hash=d.content_hash,
            body=d.model_dump(mode="json"),
            decided_at=d.captured_at,
        )
    )


def list_decisions(session: Session, run_id: str | None = None) -> list[DecisionRecord]:
    stmt = sa.select(t.decisions.c.body).order_by(t.decisions.c.line_id)
    if run_id is not None:
        stmt = stmt.where(t.decisions.c.run_id == uuid.UUID(run_id))
    bodies: Sequence[Any] = session.execute(stmt).scalars().all()
    return [DecisionRecord.model_validate(b) for b in bodies]
