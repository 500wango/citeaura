"""增加外部数据源加密凭证。"""

from alembic import op
import sqlalchemy as sa


revision = "0006_external_integrations"
down_revision = "0005_enterprise_sso_audit"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "integration_credentials",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("encrypted_value", sa.Text(), nullable=False),
        sa.Column("config_json", sa.Text(), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", "provider", name="uq_integration_credentials_tenant_provider"),
    )
    op.create_index(
        "ix_integration_credentials_tenant_id",
        "integration_credentials",
        ["tenant_id"],
    )


def downgrade():
    op.drop_index("ix_integration_credentials_tenant_id", table_name="integration_credentials")
    op.drop_table("integration_credentials")
