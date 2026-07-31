"""增加订阅周期和成交价格快照。"""

from alembic import op
import sqlalchemy as sa


revision = "0007_annual_billing"
down_revision = "0006_external_integrations"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "subscriptions",
        sa.Column("billing_interval", sa.String(length=16), server_default="monthly", nullable=False),
    )
    op.add_column("subscriptions", sa.Column("amount_cny_fen", sa.Integer(), nullable=True))
    op.add_column("subscriptions", sa.Column("amount_usd_cents", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "ck_subscriptions_billing_interval",
        "subscriptions",
        "billing_interval IN ('monthly', 'annual')",
    )


def downgrade():
    op.drop_constraint("ck_subscriptions_billing_interval", "subscriptions", type_="check")
    op.drop_column("subscriptions", "amount_usd_cents")
    op.drop_column("subscriptions", "amount_cny_fen")
    op.drop_column("subscriptions", "billing_interval")
