"""Human overrides of a decision (D-021). One row per override, append-only for the app
role, forced RLS. The decision row an override points at is never changed: the effective
decision is the newest override, or the engine's decision when there is none.

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

APP_ROLE = "alibi_app"
DECISIONS = "('CLAIM', 'DO_NOT_CLAIM', 'REVIEW')"


def upgrade() -> None:
    op.create_table(
        "decision_overrides",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("organization_id", sa.Text, nullable=False),
        sa.Column("decision_record_id", sa.Text, nullable=False),
        sa.Column("line_id", sa.Text, nullable=False),
        # 1 for the first override of a decision, 2 for the next, ... (unique per decision)
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("original_decision", sa.Text, nullable=False),
        sa.Column("new_decision", sa.Text, nullable=False),
        sa.Column("claim_amount", sa.Numeric(12, 2)),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("reviewer", sa.Text, nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_hash", sa.Text, nullable=False),
        sa.Column("body", pg.JSONB, nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id", "decision_record_id"],
            ["decisions.organization_id", "decisions.record_id"],
            name="fk_overrides_decision",
        ),
        sa.UniqueConstraint(
            "organization_id", "decision_record_id", "sequence", name="uq_overrides_sequence"
        ),
        sa.CheckConstraint("sequence >= 1", name="ck_overrides_sequence"),
        sa.CheckConstraint(f"original_decision IN {DECISIONS}", name="ck_overrides_original"),
        sa.CheckConstraint(f"new_decision IN {DECISIONS}", name="ck_overrides_new"),
        sa.CheckConstraint("new_decision <> original_decision", name="ck_overrides_changes"),
        sa.CheckConstraint(
            "(new_decision = 'CLAIM') = (claim_amount IS NOT NULL AND claim_amount > 0)",
            name="ck_overrides_claim_amount",
        ),
        sa.CheckConstraint("length(btrim(reason)) > 0", name="ck_overrides_reason"),
        sa.CheckConstraint("length(btrim(reviewer)) > 0", name="ck_overrides_reviewer"),
    )
    op.execute("ALTER TABLE decision_overrides ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE decision_overrides FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY org_isolation ON decision_overrides "
        "USING (organization_id = current_setting('app.current_org', true)) "
        "WITH CHECK (organization_id = current_setting('app.current_org', true))"
    )
    op.execute(f"GRANT SELECT, INSERT ON decision_overrides TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_table("decision_overrides")
