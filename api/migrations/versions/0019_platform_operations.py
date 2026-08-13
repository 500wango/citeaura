"""新增平台运营、国家归因和管理员数据。"""

from alembic import op
import sqlalchemy as sa


revision = "0019_platform_operations"
down_revision = "0018_global_market_scope"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("tenants") as batch_op:
        batch_op.add_column(sa.Column("status", sa.String(length=32), server_default="active", nullable=False))
        batch_op.add_column(sa.Column("acquisition_country_code", sa.String(length=2), nullable=True))
        batch_op.add_column(sa.Column("country_source", sa.String(length=32), nullable=True))
        batch_op.create_index("ix_tenants_acquisition_country_code", ["acquisition_country_code"])
        batch_op.create_check_constraint("ck_tenants_status", "status IN ('active', 'disabled')")
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("status", sa.String(length=32), server_default="active", nullable=False))
        batch_op.add_column(sa.Column("registration_kind", sa.String(length=32), server_default="self_service", nullable=False))
        batch_op.add_column(sa.Column("signup_country_code", sa.String(length=2), nullable=True))
        batch_op.add_column(sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_index("ix_users_signup_country_code", ["signup_country_code"])
        batch_op.create_index("ix_users_last_login_at", ["last_login_at"])
        batch_op.create_check_constraint("ck_users_status", "status IN ('active', 'disabled')")
        batch_op.create_check_constraint(
            "ck_users_registration_kind", "registration_kind IN ('self_service', 'invited', 'sso')",
        )
    op.execute(sa.text(
        "UPDATE users SET registration_kind = 'invited' WHERE id IN ("
        "SELECT memberships.user_id FROM memberships JOIN team_invitations "
        "ON team_invitations.tenant_id = memberships.tenant_id "
        "JOIN users invited_users ON invited_users.id = memberships.user_id "
        "WHERE team_invitations.accepted_at IS NOT NULL AND team_invitations.email = invited_users.email)"
    ))
    op.create_table(
        "platform_admins",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(length=320), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=32), server_default="superadmin", nullable=False),
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
        sa.Column("session_version", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("role IN ('support', 'ops', 'finance', 'superadmin')", name="ck_platform_admins_role"),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_platform_admins_status"),
    )
    op.create_table(
        "admin_audit_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("admin_id", sa.Integer(), sa.ForeignKey("platform_admins.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("target", sa.String(length=2048), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("details", sa.Text(), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    for column in ("admin_id", "action", "created_at"):
        op.create_index(f"ix_admin_audit_events_{column}", "admin_audit_events", [column])
    op.create_table(
        "product_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("anonymous_id", sa.String(length=64), nullable=True),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=True),
        sa.Column("properties", sa.Text(), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    for column in ("tenant_id", "user_id", "anonymous_id", "name", "country_code", "created_at"):
        op.create_index(f"ix_product_events_{column}", "product_events", [column])
    op.create_table(
        "payment_transactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subscription_id", sa.Integer(), sa.ForeignKey("subscriptions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_event_id", sa.String(length=255), nullable=False),
        sa.Column("provider_invoice_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("amount_usd_cents", sa.Integer(), nullable=True),
        sa.Column("billing_country_code", sa.String(length=2), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('succeeded', 'failed', 'refunded')", name="ck_payment_transactions_status"),
        sa.UniqueConstraint("provider", "provider_event_id", name="uq_payment_transactions_provider_event"),
    )
    for column in ("tenant_id", "subscription_id", "provider_invoice_id", "billing_country_code"):
        op.create_index(f"ix_payment_transactions_{column}", "payment_transactions", [column])


def downgrade():
    op.drop_table("payment_transactions")
    op.drop_table("product_events")
    op.drop_table("admin_audit_events")
    op.drop_table("platform_admins")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("ck_users_registration_kind", type_="check")
        batch_op.drop_constraint("ck_users_status", type_="check")
        batch_op.drop_index("ix_users_last_login_at")
        batch_op.drop_index("ix_users_signup_country_code")
        batch_op.drop_column("last_login_at")
        batch_op.drop_column("signup_country_code")
        batch_op.drop_column("registration_kind")
        batch_op.drop_column("status")
    with op.batch_alter_table("tenants") as batch_op:
        batch_op.drop_constraint("ck_tenants_status", type_="check")
        batch_op.drop_index("ix_tenants_acquisition_country_code")
        batch_op.drop_column("country_source")
        batch_op.drop_column("acquisition_country_code")
        batch_op.drop_column("status")
