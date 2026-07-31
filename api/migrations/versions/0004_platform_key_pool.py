"""增加平台 Key 池开关与按量计费账本。"""

from alembic import op
import sqlalchemy as sa


revision = "0004_platform_key_pool"
down_revision = "0003_team_invitations"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "projects",
        sa.Column("platform_pool_enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "usage_counters",
        sa.Column("platform_calls", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "usage_counters",
        sa.Column("platform_cost_cny_fen", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_table(
        "platform_usage",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("engine_code", sa.String(length=64), nullable=False),
        sa.Column("calls", sa.Integer(), nullable=False),
        sa.Column("unit_price_cny_fen", sa.Integer(), nullable=False),
        sa.Column("amount_cny_fen", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("calls > 0", name="ck_platform_usage_calls_positive"),
        sa.CheckConstraint("unit_price_cny_fen >= 0", name="ck_platform_usage_unit_price_nonnegative"),
        sa.CheckConstraint("amount_cny_fen >= 0", name="ck_platform_usage_amount_nonnegative"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"],
            name="fk_platform_usage_tenant_id_tenants", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"],
            name="fk_platform_usage_project_id_projects", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"],
            name="fk_platform_usage_job_id_jobs", ondelete="SET NULL",
        ),
        sa.UniqueConstraint("job_id", "engine_code", name="uq_platform_usage_job_engine"),
    )
    op.create_index("ix_platform_usage_tenant_id", "platform_usage", ["tenant_id"], unique=False)
    op.create_index("ix_platform_usage_project_id", "platform_usage", ["project_id"], unique=False)
    op.create_index("ix_platform_usage_job_id", "platform_usage", ["job_id"], unique=False)
    op.create_index("ix_platform_usage_created_at", "platform_usage", ["created_at"], unique=False)


def downgrade():
    op.drop_index("ix_platform_usage_created_at", table_name="platform_usage")
    op.drop_index("ix_platform_usage_job_id", table_name="platform_usage")
    op.drop_index("ix_platform_usage_project_id", table_name="platform_usage")
    op.drop_index("ix_platform_usage_tenant_id", table_name="platform_usage")
    op.drop_table("platform_usage")
    op.drop_column("usage_counters", "platform_cost_cny_fen")
    op.drop_column("usage_counters", "platform_calls")
    op.drop_column("projects", "platform_pool_enabled")
