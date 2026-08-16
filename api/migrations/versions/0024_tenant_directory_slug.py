"""Add an explicit unique tenant workspace directory identifier."""

from alembic import op
import sqlalchemy as sa


revision = "0024_tenant_directory_slug"
down_revision = "0023_platform_usage_outbox"
branch_labels = None
depends_on = None


def _slug(value):
    import re

    text = re.sub(r"^https?://", "", str(value or "").strip().lower())
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", text).strip("-")
    return (text[:48] or "workspace")


def upgrade():
    op.add_column("tenants", sa.Column("directory_slug", sa.String(length=48), nullable=True))
    connection = op.get_bind()
    rows = list(connection.execute(sa.text("SELECT id, name FROM tenants ORDER BY id")))
    used = set()
    for tenant_id, name in rows:
        base = _slug(name)
        candidate = base
        if candidate in used:
            candidate = f"{base[:39]}-{int(tenant_id):08d}"
            while candidate in used:
                candidate = f"{base[:30]}-{int(tenant_id):08d}-{len(used)}"
        used.add(candidate)
        connection.execute(
            sa.text("UPDATE tenants SET directory_slug = :directory_slug WHERE id = :tenant_id"),
            {"directory_slug": candidate, "tenant_id": tenant_id},
        )
    with op.batch_alter_table("tenants") as batch_op:
        batch_op.alter_column(
            "directory_slug",
            existing_type=sa.String(length=48),
            nullable=False,
        )
    op.create_index("uq_tenants_directory_slug", "tenants", ["directory_slug"], unique=True)


def downgrade():
    op.drop_index("uq_tenants_directory_slug", table_name="tenants")
    op.drop_column("tenants", "directory_slug")
