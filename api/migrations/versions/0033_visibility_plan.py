"""Add project visibility plan and baseline metadata."""

from alembic import op
import sqlalchemy as sa


revision = "0033_visibility_plan"
down_revision = "0032_billing_amounts_and_event_watermark"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("projects") as batch_op:
        batch_op.add_column(sa.Column("visibility_plan_json", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("visibility_baseline_json", sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table("projects") as batch_op:
        batch_op.drop_column("visibility_baseline_json")
        batch_op.drop_column("visibility_plan_json")
