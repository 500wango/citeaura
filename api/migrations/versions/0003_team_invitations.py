"""增加团队邀请和角色约束。"""

from alembic import op
import sqlalchemy as sa


revision = "0003_team_invitations"
down_revision = "0002_project_schedules"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("memberships") as batch_op:
        batch_op.create_check_constraint(
            "ck_memberships_role",
            "role IN ('owner', 'editor', 'viewer')",
        )

    op.create_table(
        "team_invitations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("invited_by_user_id", sa.Integer(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "role IN ('owner', 'editor', 'viewer')",
            name="ck_team_invitations_role",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_team_invitations_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["invited_by_user_id"],
            ["users.id"],
            name="fk_team_invitations_invited_by_user_id_users",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("token_hash", name="uq_team_invitations_token_hash"),
    )
    op.create_index("ix_team_invitations_tenant_id", "team_invitations", ["tenant_id"], unique=False)
    op.create_index("ix_team_invitations_email", "team_invitations", ["email"], unique=False)


def downgrade():
    op.drop_index("ix_team_invitations_email", table_name="team_invitations")
    op.drop_index("ix_team_invitations_tenant_id", table_name="team_invitations")
    op.drop_table("team_invitations")
    with op.batch_alter_table("memberships") as batch_op:
        batch_op.drop_constraint("ck_memberships_role", type_="check")
