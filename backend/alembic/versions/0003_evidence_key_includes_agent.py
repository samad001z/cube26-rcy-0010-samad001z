"""Evidence is keyed by (organization_id, agent, record_id): record_id is unique only
within a pod, so two pods may emit the same id (D-018). Attachments record the pod too.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("uq_evidence_org_record", "evidence_records", type_="unique")
    op.create_unique_constraint(
        "uq_evidence_org_agent_record",
        "evidence_records",
        ["organization_id", "agent", "record_id"],
    )
    # Nullable: rows ingested before this revision have no pod recorded. New rows always do.
    op.add_column("attachments", sa.Column("agent", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("attachments", "agent")
    op.drop_constraint("uq_evidence_org_agent_record", "evidence_records", type_="unique")
    op.create_unique_constraint(
        "uq_evidence_org_record", "evidence_records", ["organization_id", "record_id"]
    )
