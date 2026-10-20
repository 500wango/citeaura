"""吊销 0040 之前签发的集成令牌。

这些令牌没有 created_by_user_id，用户被停用或移除时无法定位吊销，
最长还能读取租户报告 90 天。这里统一吊销，要求客户端重新签发。
"""

from alembic import op
import sqlalchemy as sa

revision = "0041_revoke_legacy_api_tokens"
down_revision = "0040_api_token_creator"
branch_labels = None
depends_on = None


def upgrade():
    tokens = sa.table(
        "api_access_tokens",
        sa.column("created_by_user_id", sa.Integer()),
        sa.column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.execute(
        tokens.update()
        .where(tokens.c.created_by_user_id.is_(None))
        .where(tokens.c.revoked_at.is_(None))
        .values(revoked_at=sa.func.now())
    )


def downgrade():
    # 无法区分本次吊销与正常吊销，恢复会重新暴露无主令牌，故不做回滚。
    pass
