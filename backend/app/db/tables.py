"""SQLAlchemy Core table definitions. The schema itself is created by Alembic; a test
checks these definitions match the migrated database."""

from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

metadata = sa.MetaData()


def _id() -> sa.Column[Any]:
    return sa.Column(
        "id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
    )


ingest_files = sa.Table(
    "ingest_files",
    metadata,
    _id(),
    sa.Column("organization_id", sa.Text),
    sa.Column("file_name", sa.Text),
    sa.Column("sha256", sa.Text),
    sa.Column("kind", sa.Text),
    sa.Column("ingested_at", sa.DateTime(timezone=True)),
)
evidence_records = sa.Table(
    "evidence_records",
    metadata,
    _id(),
    sa.Column("organization_id", sa.Text),
    sa.Column("record_id", sa.Text),
    sa.Column("agent", sa.Text),
    sa.Column("unit_id", sa.Text),
    sa.Column("fba_shipment_id", sa.Text),
    sa.Column("order_id", sa.Text),
    sa.Column("captured_at", sa.DateTime(timezone=True)),
    sa.Column("status", sa.Text),
    sa.Column("content_hash", sa.Text),
    sa.Column("body", pg.JSONB),
    sa.Column("source", pg.JSONB),
    sa.Column("ingest_file_id", pg.UUID(as_uuid=True)),
)
charges = sa.Table(
    "charges",
    metadata,
    _id(),
    sa.Column("organization_id", sa.Text),
    sa.Column("line_id", sa.Text),
    sa.Column("report_type", sa.Text),
    sa.Column("charge_type", sa.Text),
    sa.Column("unit_id", sa.Text),
    sa.Column("fba_shipment_id", sa.Text),
    sa.Column("order_id", sa.Text),
    sa.Column("quantity", sa.Integer),
    sa.Column("amount", sa.Numeric(12, 2)),
    sa.Column("currency", sa.Text),
    sa.Column("posted_date", sa.Date),
    sa.Column("body", pg.JSONB),
    sa.Column("ingest_file_id", pg.UUID(as_uuid=True)),
)
attachments = sa.Table(
    "attachments",
    metadata,
    sa.Column("key", sa.Text, primary_key=True),
    sa.Column("organization_id", sa.Text),
    sa.Column("agent", sa.Text),
    sa.Column("record_id", sa.Text),
    sa.Column("source_path", sa.Text),
)
quarantined_rows = sa.Table(
    "quarantined_rows",
    metadata,
    _id(),
    sa.Column("organization_id", sa.Text),
    sa.Column("file_name", sa.Text),
    sa.Column("row", sa.Integer),
    sa.Column("reason", sa.Text),
    sa.Column("raw", pg.JSONB),
    sa.Column("recorded_at", sa.DateTime(timezone=True)),
)
audit_events = sa.Table(
    "audit_events",
    metadata,
    _id(),
    sa.Column("organization_id", sa.Text),
    sa.Column("at", sa.DateTime(timezone=True)),
    sa.Column("event_type", sa.Text),
    sa.Column("payload", pg.JSONB),
)
decisions = sa.Table(
    "decisions",
    metadata,
    _id(),
    sa.Column("organization_id", sa.Text),
    sa.Column("run_id", pg.UUID(as_uuid=True)),
    sa.Column("record_id", sa.Text),
    sa.Column("line_id", sa.Text),
    sa.Column("decision", sa.Text),
    sa.Column("evidence_status", sa.Text),
    sa.Column("reason_code", sa.Text),
    sa.Column("rule_id", sa.Text),
    sa.Column("status", sa.Text),
    sa.Column("claim_amount", sa.Numeric(12, 2)),
    sa.Column("content_hash", sa.Text),
    sa.Column("body", pg.JSONB),
    sa.Column("decided_at", sa.DateTime(timezone=True)),
)
