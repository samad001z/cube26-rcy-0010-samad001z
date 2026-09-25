"""Initial schema with forced row-level security on every table.

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

APP_ROLE = "alibi_app"
TABLES = [
    "ingest_files",
    "evidence_records",
    "charges",
    "attachments",
    "quarantined_rows",
    "audit_events",
]


def _id() -> sa.Column:
    return sa.Column(
        "id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
    )


def _org() -> sa.Column:
    return sa.Column("organization_id", sa.Text, nullable=False)


def upgrade() -> None:
    op.create_table(
        "ingest_files",
        _id(),
        _org(),
        sa.Column("file_name", sa.Text, nullable=False),
        sa.Column("sha256", sa.Text, nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "sha256", name="uq_ingest_files_org_sha"),
    )
    op.create_table(
        "evidence_records",
        _id(),
        _org(),
        sa.Column("record_id", sa.Text, nullable=False),
        sa.Column("agent", sa.Text, nullable=False),
        sa.Column("unit_id", sa.Text, nullable=False),
        sa.Column("fba_shipment_id", sa.Text),
        sa.Column("order_id", sa.Text),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("content_hash", sa.Text, nullable=False),
        sa.Column("body", pg.JSONB, nullable=False),
        sa.Column("source", pg.JSONB, nullable=False),
        sa.Column("ingest_file_id", pg.UUID(as_uuid=True)),
        sa.UniqueConstraint("organization_id", "record_id", name="uq_evidence_org_record"),
    )
    op.create_index("ix_evidence_org_unit", "evidence_records", ["organization_id", "unit_id"])
    op.create_table(
        "charges",
        _id(),
        _org(),
        sa.Column("line_id", sa.Text, nullable=False),
        sa.Column("report_type", sa.Text, nullable=False),
        sa.Column("charge_type", sa.Text, nullable=False),
        sa.Column("unit_id", sa.Text, nullable=False),
        sa.Column("fba_shipment_id", sa.Text),
        sa.Column("order_id", sa.Text),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.Text, nullable=False),
        sa.Column("posted_date", sa.Date, nullable=False),
        sa.Column("body", pg.JSONB, nullable=False),
        sa.Column("ingest_file_id", pg.UUID(as_uuid=True)),
        sa.UniqueConstraint("organization_id", "line_id", name="uq_charges_org_line"),
    )
    op.create_index("ix_charges_org_unit", "charges", ["organization_id", "unit_id"])
    op.create_table(
        "attachments",
        sa.Column("key", sa.Text, primary_key=True),  # HMAC, not derivable without the secret
        _org(),
        sa.Column("record_id", sa.Text, nullable=False),
        sa.Column("source_path", sa.Text, nullable=False),
    )
    op.create_table(
        "quarantined_rows",
        _id(),
        _org(),
        sa.Column("file_name", sa.Text, nullable=False),
        sa.Column("row", sa.Integer, nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("raw", pg.JSONB, nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "audit_events",
        _id(),
        _org(),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("event_type", sa.Text, nullable=False),
        sa.Column("payload", pg.JSONB, nullable=False),
    )

    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY org_isolation ON {table} "
            "USING (organization_id = current_setting('app.current_org', true)) "
            "WITH CHECK (organization_id = current_setting('app.current_org', true))"
        )
        # Insert and read only. No UPDATE or DELETE for the app role on any table, so
        # ingested evidence and the audit log cannot be modified through the app role.
        op.execute(f"GRANT SELECT, INSERT ON {table} TO {APP_ROLE}")


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_table(table)
