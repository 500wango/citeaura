"""Add regression alert flag and sendable delivery share tokens."""

from alembic import op
import sqlalchemy as sa


revision = "0025_regression_alerts_and_delivery_shares"
down_revision = "0024_tenant_directory_slug"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "projects",
        sa.Column("alert_on_regression", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.create_table(
        "delivery_shares",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("delivery_date", sa.String(length=10), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("recipient_email", sa.String(length=320), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("token_hash", name="uq_delivery_shares_token_hash"),
    )
    op.create_index("ix_delivery_shares_project_id", "delivery_shares", ["project_id"])
    op.create_index("ix_delivery_shares_expires_at", "delivery_shares", ["expires_at"])


def downgrade():
    op.drop_index("ix_delivery_shares_expires_at", table_name="delivery_shares")
    op.drop_index("ix_delivery_shares_project_id", table_name="delivery_shares")
    op.drop_table("delivery_shares")
    op.drop_column("projects", "alert_on_regression")
