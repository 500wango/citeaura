"""增加 Stripe 订阅状态和 Webhook 幂等记录。"""

from alembic import op
import sqlalchemy as sa


revision = "0008_stripe_billing"
down_revision = "0007_annual_billing"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "subscriptions",
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
    )
    op.add_column("subscriptions", sa.Column("provider", sa.String(length=32), nullable=True))
    op.add_column("subscriptions", sa.Column("provider_customer_id", sa.String(length=255), nullable=True))
    op.add_column("subscriptions", sa.Column("provider_subscription_id", sa.String(length=255), nullable=True))
    op.add_column("subscriptions", sa.Column("provider_checkout_session_id", sa.String(length=255), nullable=True))
    op.add_column(
        "subscriptions",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_subscriptions_status",
        "subscriptions",
        "status IN ('active', 'trialing', 'past_due', 'canceled', 'unpaid', 'incomplete')",
    )
    op.create_index(
        "ix_subscriptions_provider_customer_id",
        "subscriptions",
        ["provider_customer_id"],
    )
    op.create_unique_constraint(
        "uq_subscriptions_provider_subscription_id",
        "subscriptions",
        ["provider_subscription_id"],
    )
    op.create_unique_constraint(
        "uq_subscriptions_provider_checkout_session_id",
        "subscriptions",
        ["provider_checkout_session_id"],
    )
    op.create_table(
        "billing_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("event_id", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.UniqueConstraint("provider", "event_id", name="uq_billing_events_provider_event"),
    )


def downgrade():
    op.drop_table("billing_events")
    op.drop_constraint(
        "uq_subscriptions_provider_checkout_session_id",
        "subscriptions",
        type_="unique",
    )
    op.drop_constraint(
        "uq_subscriptions_provider_subscription_id",
        "subscriptions",
        type_="unique",
    )
    op.drop_index("ix_subscriptions_provider_customer_id", table_name="subscriptions")
    op.drop_constraint("ck_subscriptions_status", "subscriptions", type_="check")
    op.drop_column("subscriptions", "updated_at")
    op.drop_column("subscriptions", "provider_checkout_session_id")
    op.drop_column("subscriptions", "provider_subscription_id")
    op.drop_column("subscriptions", "provider_customer_id")
    op.drop_column("subscriptions", "provider")
    op.drop_column("subscriptions", "status")
