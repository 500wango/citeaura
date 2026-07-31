"""增加项目周期复跑调度。"""

from alembic import op
import sqlalchemy as sa


revision = "0002_project_schedules"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("projects") as batch_op:
        batch_op.add_column(sa.Column("schedule_interval_days", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("schedule_next_run_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("schedule_last_enqueued_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_check_constraint(
            "ck_projects_schedule_interval_days",
            "schedule_interval_days IS NULL OR schedule_interval_days IN (7, 14, 30)",
        )
        batch_op.create_index(
            "ix_projects_schedule_next_run_at",
            ["schedule_next_run_at"],
            unique=False,
        )


def downgrade():
    with op.batch_alter_table("projects") as batch_op:
        batch_op.drop_index("ix_projects_schedule_next_run_at")
        batch_op.drop_constraint("ck_projects_schedule_interval_days", type_="check")
        batch_op.drop_column("schedule_last_enqueued_at")
        batch_op.drop_column("schedule_next_run_at")
        batch_op.drop_column("schedule_interval_days")
