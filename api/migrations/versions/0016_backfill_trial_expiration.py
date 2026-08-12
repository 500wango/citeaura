"""为历史试用租户补齐有限的试用截止时间。"""

from alembic import op
import sqlalchemy as sa


revision = "0016_backfill_trial_expiration"
down_revision = "0015_subscription_cancel_period_end"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        bind.execute(sa.text(
            "UPDATE tenants SET trial_ends_at = datetime(created_at, '+14 days') "
            "WHERE plan = 'trial' AND trial_ends_at IS NULL"
        ))
    else:
        bind.execute(sa.text(
            "UPDATE tenants SET trial_ends_at = created_at + INTERVAL '14 days' "
            "WHERE plan = 'trial' AND trial_ends_at IS NULL"
        ))


def downgrade():
    pass
