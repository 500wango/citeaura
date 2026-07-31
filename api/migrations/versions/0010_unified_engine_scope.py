"""统一项目为全引擎范围。"""

from alembic import op
import sqlalchemy as sa


revision = "0010_unified_engine_scope"
down_revision = "0009_auth_password_reset"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(sa.text("UPDATE projects SET market = 'both' WHERE market <> 'both'"))


def downgrade():
    pass
