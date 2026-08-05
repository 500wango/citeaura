"""增加项目采样预算和单次调用上限。"""

from alembic import op
import sqlalchemy as sa


revision = "0013_project_sampling_budgets"
down_revision = "0012_job_progress_and_retry"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("projects", sa.Column("monthly_budget_cny_fen", sa.Integer(), nullable=True))
    op.add_column("projects", sa.Column("sample_call_limit", sa.Integer(), nullable=True))
    op.add_column(
        "projects",
        sa.Column("pause_on_budget_exceeded", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )
    op.create_check_constraint(
        "ck_projects_monthly_budget_nonnegative",
        "projects",
        "monthly_budget_cny_fen IS NULL OR monthly_budget_cny_fen >= 0",
    )
    op.create_check_constraint(
        "ck_projects_sample_call_limit_positive",
        "projects",
        "sample_call_limit IS NULL OR sample_call_limit > 0",
    )


def downgrade():
    op.drop_constraint("ck_projects_sample_call_limit_positive", "projects", type_="check")
    op.drop_constraint("ck_projects_monthly_budget_nonnegative", "projects", type_="check")
    op.drop_column("projects", "pause_on_budget_exceeded")
    op.drop_column("projects", "sample_call_limit")
    op.drop_column("projects", "monthly_budget_cny_fen")
