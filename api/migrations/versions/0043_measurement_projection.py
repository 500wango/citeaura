"""可重建的题库、运行与样本投影。

文件系统仍是管线真源；这四张表只保存可重建的索引与水位。
"""

from alembic import op
import sqlalchemy as sa


revision = "0043_measurement_projection"
down_revision = "0042_project_language"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "prompt_projections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("prompt_id", sa.String(length=64), nullable=False),
        sa.Column("market", sa.String(length=16), nullable=True),
        sa.Column("language", sa.String(length=16), nullable=True),
        sa.Column("category", sa.String(length=32), nullable=True),
        sa.Column("group_name", sa.String(length=32), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("project_id", "prompt_id", name="uq_prompt_projections_project_prompt"),
    )
    op.create_index("ix_prompt_projections_tenant_project", "prompt_projections", ["tenant_id", "project_id"])

    op.create_table(
        "run_projections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_id", sa.String(length=128), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("repeat", sa.Integer(), nullable=True),
        sa.Column("platforms_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("aggregation_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("project_id", "run_id", name="uq_run_projections_project_run"),
    )
    op.create_index("ix_run_projections_tenant_project", "run_projections", ["tenant_id", "project_id"])

    op.create_table(
        "sample_projections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_id", sa.String(length=128), nullable=False),
        sa.Column("question_id", sa.String(length=64), nullable=False),
        sa.Column("platform", sa.String(length=64), nullable=False),
        sa.Column("sample_mode", sa.String(length=32), nullable=True),
        sa.Column("round", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("ok", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("mention", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("top1", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("top3", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("raw_model", sa.String(length=128), nullable=True),
        sa.Column("search_enabled", sa.Boolean(), nullable=True),
        sa.Column("answer_text", sa.Text(), nullable=True),
        sa.Column("row_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "project_id", "run_id", "question_id", "platform", "round",
            name="uq_sample_projections_identity",
        ),
    )
    op.create_index("ix_sample_projections_tenant_project", "sample_projections", ["tenant_id", "project_id"])
    op.create_index("ix_sample_projections_question", "sample_projections", ["project_id", "question_id"])

    op.create_table(
        "projection_states",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_digest", sa.String(length=64), nullable=True),
        sa.Column("indexed_digest", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("project_id", name="uq_projection_states_project"),
    )
    op.create_index("ix_projection_states_tenant_project", "projection_states", ["tenant_id", "project_id"])


def downgrade():
    op.drop_index("ix_projection_states_tenant_project", table_name="projection_states")
    op.drop_table("projection_states")
    op.drop_index("ix_sample_projections_question", table_name="sample_projections")
    op.drop_index("ix_sample_projections_tenant_project", table_name="sample_projections")
    op.drop_table("sample_projections")
    op.drop_index("ix_run_projections_tenant_project", table_name="run_projections")
    op.drop_table("run_projections")
    op.drop_index("ix_prompt_projections_tenant_project", table_name="prompt_projections")
    op.drop_table("prompt_projections")
