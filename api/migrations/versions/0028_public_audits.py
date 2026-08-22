"""Persist short-lived public audit results for signup handoff."""

from alembic import op
import sqlalchemy as sa


revision = "0028_public_audits"
down_revision = "0027_daily_monitoring"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "public_audits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("audit_id", sa.String(length=64), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("anonymous_id", sa.String(length=64), nullable=True),
        sa.Column("result_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("audit_id", name="uq_public_audits_audit_id"),
    )
    op.create_index("ix_public_audits_audit_id", "public_audits", ["audit_id"], unique=False)
    op.create_index("ix_public_audits_anonymous_id", "public_audits", ["anonymous_id"], unique=False)
    op.create_index("ix_public_audits_expires_at", "public_audits", ["expires_at"], unique=False)
    op.create_index("ix_public_audits_created_at", "public_audits", ["created_at"], unique=False)


def downgrade():
    op.drop_index("ix_public_audits_created_at", table_name="public_audits")
    op.drop_index("ix_public_audits_expires_at", table_name="public_audits")
    op.drop_index("ix_public_audits_anonymous_id", table_name="public_audits")
    op.drop_index("ix_public_audits_audit_id", table_name="public_audits")
    op.drop_table("public_audits")
