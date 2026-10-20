"""移除 Enterprise 套餐与 SSO 数据表。

历史上购买 enterprise 的租户统一迁移为 agency；SSO 表直接删除。
降级只能恢复表结构，无法恢复已删除的 IdP 配置与身份绑定。
"""

from alembic import op
import sqlalchemy as sa


revision = "0044_remove_enterprise_sso"
down_revision = "0043_measurement_projection"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE tenants SET plan = 'agency' WHERE plan = 'enterprise'")
    op.execute("UPDATE subscriptions SET plan = 'agency' WHERE plan = 'enterprise'")

    op.drop_index("ix_sso_identities_user", table_name="sso_identities")
    op.drop_index("ix_sso_identities_tenant_id", table_name="sso_identities")
    op.drop_table("sso_identities")
    op.drop_table("sso_configurations")


def downgrade():
    op.create_table(
        "sso_configurations",
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("provider_name", sa.String(length=128), nullable=False),
        sa.Column("issuer_url", sa.String(length=2048), nullable=False),
        sa.Column("client_id", sa.String(length=512), nullable=False),
        sa.Column("encrypted_client_secret", sa.Text(), nullable=True),
        sa.Column("allowed_domains", sa.Text(), server_default="[]", nullable=False),
        sa.Column("verified_domains", sa.Text(), server_default="[]", nullable=False),
        sa.Column("default_role", sa.String(length=32), server_default="viewer", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("default_role IN ('editor', 'viewer')", name="ck_sso_configurations_default_role"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("tenant_id"),
    )
    op.create_table(
        "sso_identities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("issuer", sa.String(length=2048), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "issuer", "subject", name="uq_sso_identities_issuer_subject"),
    )
    op.create_index("ix_sso_identities_tenant_id", "sso_identities", ["tenant_id"])
    op.create_index("ix_sso_identities_user", "sso_identities", ["user_id"])
