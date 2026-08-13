"""增加租户级自定义 OpenAI-compatible 模型供应商。"""

from alembic import op
import sqlalchemy as sa


revision = "0017_custom_model_providers"
down_revision = "0016_backfill_trial_expiration"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "custom_providers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("base_url", sa.String(length=2048), nullable=False),
        sa.Column("model_id", sa.String(length=255), nullable=False),
        sa.Column("market", sa.String(length=16), server_default="global", nullable=False),
        sa.Column("encrypted_api_key", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_custom_providers_tenant_id_tenants", ondelete="CASCADE",
        ),
        sa.CheckConstraint("market IN ('cn', 'global')", name="ck_custom_providers_market"),
        sa.UniqueConstraint("tenant_id", "code", name="uq_custom_providers_tenant_code"),
    )
    op.create_index("ix_custom_providers_tenant_id", "custom_providers", ["tenant_id"], unique=False)


def downgrade():
    op.drop_index("ix_custom_providers_tenant_id", table_name="custom_providers")
    op.drop_table("custom_providers")
