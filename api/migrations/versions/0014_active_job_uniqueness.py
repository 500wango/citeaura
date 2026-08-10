"""限制每个项目只能有一个活动任务。"""

from alembic import op
import sqlalchemy as sa


revision = "0014_active_job_uniqueness"
down_revision = "0013_project_sampling_budgets"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "uq_jobs_project_active",
        "jobs",
        ["project_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
        sqlite_where=sa.text("status IN ('queued', 'running')"),
    )


def downgrade():
    op.drop_index("uq_jobs_project_active", table_name="jobs")
