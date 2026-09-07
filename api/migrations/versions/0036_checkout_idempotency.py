"""Persist one idempotent Stripe checkout per tenant."""

from alembic import op
import sqlalchemy as sa


revision = "0036_checkout_idempotency"
down_revision = "0035_tenant_segment"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("subscriptions") as batch_op:
        batch_op.add_column(sa.Column("checkout_url", sa.String(length=2048), nullable=True))
        batch_op.add_column(sa.Column("checkout_idempotency_key", sa.String(length=64), nullable=True))
        batch_op.drop_constraint("ck_subscriptions_status", type_="check")
        batch_op.create_check_constraint(
            "ck_subscriptions_status",
            "status IN ('pending', 'active', 'trialing', 'past_due', 'canceled', 'unpaid', 'incomplete')",
        )
    op.create_index(
        "uq_subscriptions_tenant_pending_checkout",
        "subscriptions",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
        sqlite_where=sa.text("status = 'pending'"),
    )


def downgrade():
    op.drop_index("uq_subscriptions_tenant_pending_checkout", table_name="subscriptions")
    op.execute(sa.text("UPDATE subscriptions SET status = 'incomplete' WHERE status = 'pending'"))
    with op.batch_alter_table("subscriptions") as batch_op:
        batch_op.drop_constraint("ck_subscriptions_status", type_="check")
        batch_op.create_check_constraint(
            "ck_subscriptions_status",
            "status IN ('active', 'trialing', 'past_due', 'canceled', 'unpaid', 'incomplete')",
        )
        batch_op.drop_column("checkout_idempotency_key")
        batch_op.drop_column("checkout_url")
