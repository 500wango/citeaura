"""Add revocable read-only API tokens for integrations and MCP."""

from alembic import op
import sqlalchemy as sa


revision = "0029_api_access_tokens"
down_revision = "0028_public_audits"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "api_access_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("token_prefix", sa.String(length=16), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("scopes", sa.Text(), nullable=False, server_default='["read"]'),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_api_access_tokens_token_hash"),
    )
    for column in ("tenant_id", "revoked_at", "created_at"):
        op.create_index(f"ix_api_access_tokens_{column}", "api_access_tokens", [column], unique=False)


def downgrade():
    for column in ("created_at", "revoked_at", "tenant_id"):
        op.drop_index(f"ix_api_access_tokens_{column}", table_name="api_access_tokens")
    op.drop_table("api_access_tokens")
