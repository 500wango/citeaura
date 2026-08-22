"""Allow a daily monitoring cadence for the self-serve retention loop."""

from alembic import op


revision = "0027_daily_monitoring"
down_revision = "0026_transactional_email_dedup"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("projects") as batch_op:
        batch_op.drop_constraint("ck_projects_schedule_interval_days", type_="check")
        batch_op.create_check_constraint(
            "ck_projects_schedule_interval_days",
            "schedule_interval_days IS NULL OR schedule_interval_days IN (1, 7, 14, 30)",
        )


def downgrade():
    with op.batch_alter_table("projects") as batch_op:
        batch_op.drop_constraint("ck_projects_schedule_interval_days", type_="check")
        batch_op.create_check_constraint(
            "ck_projects_schedule_interval_days",
            "schedule_interval_days IS NULL OR schedule_interval_days IN (7, 14, 30)",
        )
