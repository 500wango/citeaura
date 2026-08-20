"""Add cross-event deduplication keys for payment notifications."""

from alembic import op
import sqlalchemy as sa


revision = "0026_transactional_email_dedup"
down_revision = "0025_regression_alerts_and_delivery_shares"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "billing_events",
        sa.Column("notification_key", sa.String(length=255), nullable=True),
    )
    op.create_index(
        "ix_billing_events_notification_key",
        "billing_events",
        ["notification_key"],
    )


def downgrade():
    op.drop_index("ix_billing_events_notification_key", table_name="billing_events")
    op.drop_column("billing_events", "notification_key")
