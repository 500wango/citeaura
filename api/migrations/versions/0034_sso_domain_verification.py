"""Add SSO DNS domain verification state."""
from alembic import op
import sqlalchemy as sa

revision = "0034_sso_domain_verification"
down_revision = "0033_visibility_plan"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("sso_configurations", sa.Column("verified_domains", sa.Text(), nullable=False, server_default="[]"))

def downgrade():
    op.drop_column("sso_configurations", "verified_domains")
