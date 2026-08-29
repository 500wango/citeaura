"""Add tenant customer segment for funnel breakdown."""
from alembic import op
import sqlalchemy as sa

revision = "0035_tenant_segment"
down_revision = "0034_sso_domain_verification"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("tenants", sa.Column("segment", sa.String(32), nullable=False, server_default="unknown"))
    op.create_index("ix_tenants_segment", "tenants", ["segment"])


def downgrade():
    op.drop_index("ix_tenants_segment", table_name="tenants")
    op.drop_column("tenants", "segment")
