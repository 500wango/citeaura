"""项目题库语言、报告语言与试用自动复测水位。"""

from alembic import op
import sqlalchemy as sa


revision = "0042_project_language"
down_revision = "0041_revoke_legacy_api_tokens"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("projects") as batch_op:
        batch_op.add_column(sa.Column(
            "question_language", sa.String(length=16), nullable=False, server_default="auto",
        ))
        batch_op.add_column(sa.Column(
            "report_language", sa.String(length=16), nullable=False, server_default="en",
        ))
        batch_op.add_column(sa.Column("trial_retests_json", sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table("projects") as batch_op:
        batch_op.drop_column("trial_retests_json")
        batch_op.drop_column("report_language")
        batch_op.drop_column("question_language")
