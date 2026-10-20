"""记录 API 令牌创建者，便于停用或移除用户时精确吊销。

令牌是租户级凭证，原先只有 tenant_id。用户被停用后其 JWT 会因 session_version
失效，但存量集成令牌仍可继续读取该租户全部报告，直到 90 天过期。
"""

from alembic import op
import sqlalchemy as sa

revision = "0040_api_token_creator"
down_revision = "0039_public_audit_consumed"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("api_access_tokens") as batch_op:
        batch_op.add_column(sa.Column("created_by_user_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_api_access_tokens_created_by_user_id",
            "users",
            ["created_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            "ix_api_access_tokens_created_by_user_id",
            ["created_by_user_id"],
        )


def downgrade():
    with op.batch_alter_table("api_access_tokens") as batch_op:
        batch_op.drop_index("ix_api_access_tokens_created_by_user_id")
        batch_op.drop_constraint("fk_api_access_tokens_created_by_user_id", type_="foreignkey")
        batch_op.drop_column("created_by_user_id")
