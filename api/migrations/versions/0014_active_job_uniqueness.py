"""限制每个项目只能有一个活动任务。"""

from alembic import op
import sqlalchemy as sa


revision = "0014_active_job_uniqueness"
down_revision = "0013_project_sampling_budgets"
branch_labels = None
depends_on = None


def upgrade():
    # Older databases may contain multiple active rows. Keep the earliest row
    # for each project and close the rest before adding the unique index.
    op.execute(sa.text("""
        UPDATE jobs
        SET status = 'failed',
            stage = 'failed',
            finished_at = CURRENT_TIMESTAMP,
            error = 'duplicate_active_job'
        WHERE id IN (
            SELECT id FROM (
                SELECT id,
                       ROW_NUMBER() OVER (PARTITION BY project_id ORDER BY id) AS duplicate_rank
                FROM jobs
                WHERE status IN ('queued', 'running')
            ) ranked
            WHERE duplicate_rank > 1
        )
    """))
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
