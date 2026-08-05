"""增加任务可观测进度和失败重试链。"""

from alembic import op
import sqlalchemy as sa


revision = "0012_job_progress_and_retry"
down_revision = "0011_session_and_project_lifecycle"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("jobs", sa.Column("stage", sa.String(length=64), server_default="queued", nullable=False))
    op.add_column("jobs", sa.Column("progress", sa.Integer(), server_default="0", nullable=False))
    op.add_column("jobs", sa.Column("attempt", sa.Integer(), server_default="1", nullable=False))
    op.add_column("jobs", sa.Column("request_json", sa.Text(), nullable=True))
    op.add_column("jobs", sa.Column("celery_task_id", sa.String(length=255), nullable=True))
    op.add_column("jobs", sa.Column("retry_of_job_id", sa.Integer(), nullable=True))
    op.create_index("ix_jobs_retry_of_job_id", "jobs", ["retry_of_job_id"])
    op.create_foreign_key(
        "fk_jobs_retry_of_job_id_jobs", "jobs", "jobs", ["retry_of_job_id"], ["id"], ondelete="SET NULL",
    )


def downgrade():
    op.drop_constraint("fk_jobs_retry_of_job_id_jobs", "jobs", type_="foreignkey")
    op.drop_index("ix_jobs_retry_of_job_id", table_name="jobs")
    op.drop_column("jobs", "retry_of_job_id")
    op.drop_column("jobs", "celery_task_id")
    op.drop_column("jobs", "request_json")
    op.drop_column("jobs", "attempt")
    op.drop_column("jobs", "progress")
    op.drop_column("jobs", "stage")
