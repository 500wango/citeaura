"""增加会话撤销和项目归档状态。"""

from alembic import op
import sqlalchemy as sa


revision = "0011_session_and_project_lifecycle"
down_revision = "0010_unified_engine_scope"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("session_version", sa.Integer(), server_default="0", nullable=False))
    op.add_column("projects", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_projects_archived_at", "projects", ["archived_at"])


def downgrade():
    op.drop_index("ix_projects_archived_at", table_name="projects")
    op.drop_column("projects", "archived_at")
    op.drop_column("users", "session_version")
