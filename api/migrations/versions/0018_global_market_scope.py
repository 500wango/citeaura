"""将项目和自定义模型供应商归一为国际市场。"""

from alembic import op
import sqlalchemy as sa


revision = "0018_global_market_scope"
down_revision = "0017_custom_model_providers"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(sa.text("UPDATE projects SET market = 'global' WHERE market <> 'global'"))
    op.execute(sa.text("UPDATE custom_providers SET market = 'global' WHERE market <> 'global'"))
    with op.batch_alter_table("projects") as batch_op:
        batch_op.alter_column("market", server_default="global", existing_type=sa.String(length=16))
    with op.batch_alter_table("custom_providers") as batch_op:
        batch_op.drop_constraint("ck_custom_providers_market", type_="check")
        batch_op.create_check_constraint("ck_custom_providers_market", "market = 'global'")


def downgrade():
    with op.batch_alter_table("custom_providers") as batch_op:
        batch_op.drop_constraint("ck_custom_providers_market", type_="check")
        batch_op.create_check_constraint("ck_custom_providers_market", "market IN ('cn', 'global')")
    with op.batch_alter_table("projects") as batch_op:
        batch_op.alter_column("market", server_default="both", existing_type=sa.String(length=16))
