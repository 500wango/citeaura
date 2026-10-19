"""公开审计交接改为一次性消费。

`public_audits.audit_id` 之前可以在 24 小时内反复用来把同一份审计结果挂到任意多个
新账号上；这里加 `consumed_at`（消费标记）和 `tenant_id`（归属），注册成功后置位。
"""

from alembic import op
import sqlalchemy as sa

revision = "0039_public_audit_consumed"
down_revision = "0038_security_reliability"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("public_audits") as batch_op:
        batch_op.add_column(sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(
            sa.Column(
                "tenant_id",
                sa.Integer(),
                sa.ForeignKey("tenants.id", ondelete="SET NULL"),
                nullable=True,
            )
        )


def downgrade():
    with op.batch_alter_table("public_audits") as batch_op:
        batch_op.drop_column("tenant_id")
        batch_op.drop_column("consumed_at")
