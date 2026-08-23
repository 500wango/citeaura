"""恢复国内、全球和双市场的项目与自定义 Provider 范围。"""

from alembic import op
import sqlalchemy as sa


revision = "0030_restore_market_scope"
down_revision = "0029_api_access_tokens"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(sa.text("UPDATE projects SET market = 'both' WHERE market = 'global'"))
    op.execute(sa.text("UPDATE custom_providers SET market = 'both' WHERE market = 'global'"))
    with op.batch_alter_table("projects") as batch_op:
        batch_op.alter_column("market", server_default="both", existing_type=sa.String(length=16))
    with op.batch_alter_table("custom_providers") as batch_op:
        batch_op.drop_constraint("ck_custom_providers_market", type_="check")
        batch_op.create_check_constraint(
            "ck_custom_providers_market", "market IN ('cn', 'global', 'both')",
        )


def downgrade():
    op.execute(sa.text("UPDATE projects SET market = 'global' WHERE market <> 'global'"))
    op.execute(sa.text("UPDATE custom_providers SET market = 'global' WHERE market <> 'global'"))
    with op.batch_alter_table("projects") as batch_op:
        batch_op.alter_column("market", server_default="global", existing_type=sa.String(length=16))
    with op.batch_alter_table("custom_providers") as batch_op:
        batch_op.drop_constraint("ck_custom_providers_market", type_="check")
        batch_op.create_check_constraint("ck_custom_providers_market", "market = 'global'")
