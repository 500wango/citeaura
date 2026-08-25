"""保存 Stripe 事件顺序水印及非 USD 交易金额。"""

from alembic import op
import sqlalchemy as sa


revision = "0032_billing_amounts_and_event_watermark"
down_revision = "0031_job_history_index"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("subscriptions") as batch_op:
        batch_op.add_column(sa.Column("provider_event_created_at", sa.DateTime(timezone=True), nullable=True))
    with op.batch_alter_table("payment_transactions") as batch_op:
        batch_op.add_column(sa.Column("amount_cny_fen", sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table("payment_transactions") as batch_op:
        batch_op.drop_column("amount_cny_fen")
    with op.batch_alter_table("subscriptions") as batch_op:
        batch_op.drop_column("provider_event_created_at")
