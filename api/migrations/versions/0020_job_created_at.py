"""记录 Job 入队时间，支持回收丢失的 queued 任务。"""

from alembic import op
import sqlalchemy as sa


revision = "0020_job_created_at"
down_revision = "0019_platform_operations"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.add_column(
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )


def downgrade():
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.drop_column("created_at")
