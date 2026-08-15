"""Add durable platform usage accounting events."""

from alembic import op
import sqlalchemy as sa


revision = "0023_platform_usage_outbox"
down_revision = "0022_security_reliability"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "platform_usage_outbox",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_key", sa.String(length=255), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("engine_code", sa.String(length=64), nullable=False),
        sa.Column("calls", sa.Integer(), nullable=False),
        sa.Column("unit_price_cny_fen", sa.Integer(), nullable=False),
        sa.Column("amount_cny_fen", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("calls > 0", name="ck_platform_usage_outbox_calls_positive"),
        sa.CheckConstraint("status IN ('pending', 'processed')", name="ck_platform_usage_outbox_status"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_key", name="uq_platform_usage_outbox_event_key"),
    )
    op.create_index("ix_platform_usage_outbox_tenant_id", "platform_usage_outbox", ["tenant_id"])
    op.create_index("ix_platform_usage_outbox_project_id", "platform_usage_outbox", ["project_id"])
    op.create_index("ix_platform_usage_outbox_job_id", "platform_usage_outbox", ["job_id"])
    op.create_index("ix_platform_usage_outbox_status", "platform_usage_outbox", ["status"])
    op.create_index("ix_platform_usage_outbox_next_attempt_at", "platform_usage_outbox", ["next_attempt_at"])
    op.create_index("ix_platform_usage_outbox_created_at", "platform_usage_outbox", ["created_at"])


def downgrade():
    op.drop_index("ix_platform_usage_outbox_created_at", table_name="platform_usage_outbox")
    op.drop_index("ix_platform_usage_outbox_next_attempt_at", table_name="platform_usage_outbox")
    op.drop_index("ix_platform_usage_outbox_status", table_name="platform_usage_outbox")
    op.drop_index("ix_platform_usage_outbox_job_id", table_name="platform_usage_outbox")
    op.drop_index("ix_platform_usage_outbox_project_id", table_name="platform_usage_outbox")
    op.drop_index("ix_platform_usage_outbox_tenant_id", table_name="platform_usage_outbox")
    op.drop_table("platform_usage_outbox")
