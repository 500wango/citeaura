"""增加自定义供应商的请求头、协议与联网检索配置。"""

from alembic import op
import sqlalchemy as sa

revision = "0037_custom_provider_transport"
down_revision = "0036_checkout_idempotency"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("custom_providers") as batch_op:
        batch_op.add_column(sa.Column("protocol", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("extra_headers", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("search", sa.Boolean(), nullable=False, server_default="false"))
        batch_op.create_check_constraint(
            "ck_custom_providers_protocol",
            "protocol IS NULL OR protocol IN ('anthropic', 'openai', 'gemini')",
        )


def downgrade():
    with op.batch_alter_table("custom_providers") as batch_op:
        batch_op.drop_constraint("ck_custom_providers_protocol", type_="check")
        batch_op.drop_column("search")
        batch_op.drop_column("extra_headers")
        batch_op.drop_column("protocol")
