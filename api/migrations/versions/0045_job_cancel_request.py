"""任务取消请求标记。

只新增一个可空时间戳：运行中的 Job 在被 worker 真正停下之前保持 running，
唯一索引 uq_jobs_project_active 因此仍然生效；worker 轮询该列后终止引擎子进程
或抛出协作式取消异常，再把 Job 落成 canceled 终态。
"""

from alembic import op
import sqlalchemy as sa


revision = "0045_job_cancel_request"
down_revision = "0044_remove_enterprise_sso"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.add_column(sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.drop_column("cancel_requested_at")
