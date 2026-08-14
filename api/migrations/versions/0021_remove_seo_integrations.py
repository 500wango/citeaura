"""删除已下线 SEO 集成保存的租户凭据。"""

from alembic import op
import sqlalchemy as sa


revision = "0021_remove_seo_integrations"
down_revision = "0020_job_created_at"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(sa.text(
        "DELETE FROM integration_credentials "
        "WHERE provider IN ('search_console', 'semrush', 'tabapi')"
    ))


def downgrade():
    pass
