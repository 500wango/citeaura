"""记录订阅按当前计费周期结束取消的意图。"""

from alembic import op
import sqlalchemy as sa


revision = "0015_subscription_cancel_period_end"
down_revision = "0014_active_job_uniqueness"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "subscriptions",
        sa.Column("cancel_at_period_end", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )


def downgrade():
    op.drop_column("subscriptions", "cancel_at_period_end")
