"""Add refresh-token rotation and platform budget reservations."""

from alembic import op
import sqlalchemy as sa


revision = "0022_security_reliability"
down_revision = "0021_remove_seo_integrations"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.add_column(sa.Column(
            "reserved_platform_calls", sa.Integer(), server_default="0", nullable=False,
        ))
        batch_op.add_column(sa.Column(
            "reserved_platform_cost_cny_fen", sa.Integer(), server_default="0", nullable=False,
        ))
        batch_op.add_column(sa.Column("budget_reservation_status", sa.String(length=32), nullable=True))
        batch_op.create_index(
            "ix_jobs_budget_reservation_status", ["budget_reservation_status"], unique=False,
        )

    # Jobs closed by the pre-0022 active-job migration cannot retain a
    # reservation once the reservation columns exist.
    op.execute(sa.text("""
        UPDATE jobs
        SET budget_reservation_status = 'released'
        WHERE status = 'failed'
          AND budget_reservation_status IS NULL
    """))

    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("family_id", sa.String(length=36), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_refresh_tokens_family_id", "refresh_tokens", ["family_id"], unique=False)
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"], unique=False)
    op.create_index("ix_refresh_tokens_tenant_id", "refresh_tokens", ["tenant_id"], unique=False)
    op.create_index("ix_refresh_tokens_expires_at", "refresh_tokens", ["expires_at"], unique=False)


def downgrade():
    op.drop_index("ix_refresh_tokens_expires_at", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_tenant_id", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_user_id", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_family_id", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.drop_index("ix_jobs_budget_reservation_status")
        batch_op.drop_column("budget_reservation_status")
        batch_op.drop_column("reserved_platform_cost_cny_fen")
        batch_op.drop_column("reserved_platform_calls")
