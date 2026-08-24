"""Add the composite index used by bounded project job history queries."""

from alembic import op


revision = "0031_job_history_index"
down_revision = "0030_restore_market_scope"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("ix_jobs_project_id_id", "jobs", ["project_id", "id"], unique=False)


def downgrade():
    op.drop_index("ix_jobs_project_id_id", table_name="jobs")
