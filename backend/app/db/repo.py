"""Typed reads and writes. Callers pass an org-scoped session (see db.session.org_session);
row-level security, not these functions, is what enforces tenancy."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.adapters.csv_v0 import AttachmentRef, Quarantined
from app.db import tables as t
from app.models.charge import Charge, SourceRef
from app.models.contract import EvidenceRecord
from app.models.decision import DecisionRecord

if TYPE_CHECKING:
    from app.review import OverrideRecord


@dataclass(frozen=True)
class AttachmentRow:
    key: str
    organization_id: str
    agent: str | None  # null for rows ingested before migration 0003
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
    sources: dict[tuple[str, str], SourceRef],
    ingest_file_id: uuid.UUID,
) -> int:
    """Returns the number of newly inserted rows; existing (org, agent, record_id) rows are kept."""
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
                source=sources[(r.agent, r.record_id)].model_dump(mode="json"),
                ingest_file_id=ingest_file_id,
            )
            .on_conflict_do_nothing(index_elements=["organization_id", "agent", "record_id"])
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
                agent=a.agent,
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


def _record_key(agent: str, record_id: str) -> sa.ColumnElement[bool]:
    """Evidence is keyed by pod and record_id: record_id is unique only within a pod (D-018)."""
    return sa.and_(t.evidence_records.c.agent == agent, t.evidence_records.c.record_id == record_id)


def get_record(session: Session, agent: str, record_id: str) -> EvidenceRecord | None:
    body = session.execute(
        sa.select(t.evidence_records.c.body).where(_record_key(agent, record_id))
    ).scalar_one_or_none()
    return EvidenceRecord.model_validate(body) if body is not None else None


def get_attachment(session: Session, key: str) -> AttachmentRow | None:
    row = session.execute(sa.select(t.attachments).where(t.attachments.c.key == key)).first()
    if row is None:
        return None
    return AttachmentRow(row.key, row.organization_id, row.agent, row.record_id, row.source_path)


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
            sa.select(t.evidence_records.c.body).order_by(
                t.evidence_records.c.agent, t.evidence_records.c.record_id
            )
        )
        .scalars()
        .all()
    )
    return [EvidenceRecord.model_validate(b) for b in bodies]


def get_record_with_hash(
    session: Session, agent: str, record_id: str
) -> tuple[EvidenceRecord, str] | None:
    """The record body and the content_hash column written at ingestion."""
    row = session.execute(
        sa.select(t.evidence_records.c.body, t.evidence_records.c.content_hash).where(
            _record_key(agent, record_id)
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


def get_decision(session: Session, record_id: str) -> DecisionRecord | None:
    body = session.execute(
        sa.select(t.decisions.c.body).where(t.decisions.c.record_id == record_id)
    ).scalar_one_or_none()
    return DecisionRecord.model_validate(body) if body is not None else None


def list_decisions_for_line(session: Session, line_id: str) -> list[DecisionRecord]:
    """Every decision ever made for a charge line, oldest first."""
    bodies: Sequence[Any] = (
        session.execute(
            sa.select(t.decisions.c.body)
            .where(t.decisions.c.line_id == line_id)
            .order_by(t.decisions.c.decided_at, t.decisions.c.record_id)
        )
        .scalars()
        .all()
    )
    return [DecisionRecord.model_validate(b) for b in bodies]


@dataclass(frozen=True)
class RunRow:
    run_id: str
    decided_at: datetime
    charges: int
    counts: dict[str, int]


def list_runs(session: Session) -> list[RunRow]:
    """Runs with at least one decision, newest first."""
    rows = session.execute(
        sa.select(
            t.decisions.c.run_id,
            sa.func.min(t.decisions.c.decided_at).label("at"),
            t.decisions.c.decision,
            sa.func.count().label("n"),
        ).group_by(t.decisions.c.run_id, t.decisions.c.decision)
    ).all()
    runs: dict[str, RunRow] = {}
    for r in rows:
        key = str(r.run_id)
        run = runs.get(key)
        if run is None:
            run = runs[key] = RunRow(key, r.at, 0, {})
        run.counts[r.decision] = r.n
        runs[key] = RunRow(key, min(run.decided_at, r.at), run.charges + r.n, run.counts)
    return sorted(runs.values(), key=lambda x: (x.decided_at, x.run_id), reverse=True)


def insert_override(session: Session, organization_id: str, rec: "OverrideRecord") -> None:
    session.execute(
        insert(t.decision_overrides).values(
            organization_id=organization_id,
            decision_record_id=rec.decision_record_id,
            line_id=rec.line_id,
            sequence=rec.sequence,
            original_decision=rec.override.original_decision,
            new_decision=rec.override.new_decision,
            claim_amount=rec.claim.amount if rec.claim else None,
            reason=rec.override.reason,
            reviewer=rec.override.reviewer,
            at=rec.override.at,
            content_hash=rec.content_hash,
            body=rec.model_dump(mode="json"),
        )
    )


def _override_bodies(session: Session, where: sa.ColumnElement[bool]) -> Sequence[Any]:
    return (
        session.execute(
            sa.select(t.decision_overrides.c.body)
            .where(where)
            .order_by(t.decision_overrides.c.decision_record_id, t.decision_overrides.c.sequence)
        )
        .scalars()
        .all()
    )


def list_overrides(session: Session, record_id: str) -> list["OverrideRecord"]:
    from app.review import OverrideRecord

    bodies = _override_bodies(session, t.decision_overrides.c.decision_record_id == record_id)
    return [OverrideRecord.model_validate(b) for b in bodies]


def overrides_by_record(
    session: Session, record_ids: Sequence[str]
) -> dict[str, list["OverrideRecord"]]:
    from app.review import OverrideRecord

    out: dict[str, list[OverrideRecord]] = {}
    if not record_ids:
        return out
    bodies = _override_bodies(
        session, t.decision_overrides.c.decision_record_id.in_(list(record_ids))
    )
    for b in bodies:
        o = OverrideRecord.model_validate(b)
        out.setdefault(o.decision_record_id, []).append(o)
    return out
