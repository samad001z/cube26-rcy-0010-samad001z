"""Cache of validated model explanations (D-022), keyed by trace hash. Append-only for the
app role, forced RLS. The trace hash covers the trace, the prompt version and the model, so
a cached text is only reused for exactly what it was written from.

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

APP_ROLE = "alibi_app"


def upgrade() -> None:
    op.create_table(
        "llm_explanations",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("organization_id", sa.Text, nullable=False),
        sa.Column("trace_hash", sa.Text, nullable=False),
        sa.Column("prompt_version", sa.Text, nullable=False),
        sa.Column("model_id", sa.Text, nullable=False),
        sa.Column("explanation", sa.Text, nullable=False),
        sa.Column("input_tokens", sa.Integer, nullable=False),
        sa.Column("output_tokens", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organization_id", "trace_hash", name="uq_llm_explanations_trace"),
        sa.CheckConstraint(
            r"length(regexp_replace(explanation, '\s', '', 'g')) > 0",
            name="ck_llm_explanations_text",
        ),
    )
    op.execute("ALTER TABLE llm_explanations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE llm_explanations FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY org_isolation ON llm_explanations "
        "USING (organization_id = current_setting('app.current_org', true)) "
        "WITH CHECK (organization_id = current_setting('app.current_org', true))"
    )
    op.execute(f"GRANT SELECT, INSERT ON llm_explanations TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_table("llm_explanations")
