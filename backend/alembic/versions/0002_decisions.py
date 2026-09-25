"""Decisions table: one row per charge per run. Append-only for the app role, forced RLS.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

APP_ROLE = "alibi_app"


def upgrade() -> None:
    op.create_table(
        "decisions",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("organization_id", sa.Text, nullable=False),
        sa.Column("run_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("record_id", sa.Text, nullable=False),
        sa.Column("line_id", sa.Text, nullable=False),
        sa.Column("decision", sa.Text, nullable=False),
        sa.Column("evidence_status", sa.Text, nullable=False),
        sa.Column("reason_code", sa.Text),
        sa.Column("rule_id", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("claim_amount", sa.Numeric(12, 2)),
        sa.Column("content_hash", sa.Text, nullable=False),
        sa.Column("body", pg.JSONB, nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organization_id", "record_id", name="uq_decisions_org_record"),
        sa.UniqueConstraint("organization_id", "run_id", "line_id", name="uq_decisions_run_line"),
        sa.CheckConstraint(
            "decision IN ('CLAIM', 'DO_NOT_CLAIM', 'REVIEW')", name="ck_decisions_decision"
        ),
        sa.CheckConstraint(
            "(decision = 'CLAIM') = (claim_amount IS NOT NULL AND claim_amount > 0)",
            name="ck_decisions_claim_amount",
        ),
    )
    op.create_index("ix_decisions_org_line", "decisions", ["organization_id", "line_id"])
    op.execute("ALTER TABLE decisions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE decisions FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY org_isolation ON decisions "
        "USING (organization_id = current_setting('app.current_org', true)) "
        "WITH CHECK (organization_id = current_setting('app.current_org', true))"
    )
    # Append-only for the app role: a re-run writes new rows; nothing is updated in place.
    op.execute(f"GRANT SELECT, INSERT ON decisions TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_table("decisions")
