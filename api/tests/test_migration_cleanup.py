import importlib

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_removed_seo_credentials_are_deleted_without_touching_outreach_smtp():
    migration = importlib.import_module("api.migrations.versions.0021_remove_seo_integrations")
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    table = sa.Table(
        "integration_credentials",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("provider", sa.String(64), nullable=False),
    )
    metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(table.insert(), [
            {"provider": "search_console"},
            {"provider": "semrush"},
            {"provider": "tabapi"},
            {"provider": "outreach_smtp"},
        ])
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        providers = list(
            connection.execute(sa.select(table.c.provider).order_by(table.c.provider)).scalars()
        )

    assert providers == ["outreach_smtp"]


def test_tenant_directory_slug_migration_backfills_collisions_deterministically():
    migration = importlib.import_module("api.migrations.versions.0024_tenant_directory_slug")
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    tenants = sa.Table(
        "tenants",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
    )
    metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(tenants.insert(), [
            {"id": 1, "name": "Acme Co"},
            {"id": 2, "name": "acme_co"},
        ])
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        rows = list(connection.execute(sa.text(
            "SELECT directory_slug FROM tenants ORDER BY id"
        )).scalars())

    assert rows == ["acme-co", "acme-co-00000002"]


def test_restore_market_scope_drops_legacy_provider_check_before_backfill():
    migration = importlib.import_module("api.migrations.versions.0030_restore_market_scope")
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    sa.Table(
        "projects",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("market", sa.String(16), server_default="global", nullable=False),
    )
    providers = sa.Table(
        "custom_providers",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("market", sa.String(16), server_default="global", nullable=False),
        sa.CheckConstraint("market = 'global'", name="ck_custom_providers_market"),
    )
    metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(providers.insert(), {"id": 1, "market": "global"})
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        connection.execute(providers.insert(), [
            {"id": 2, "market": "cn"},
            {"id": 3, "market": "both"},
        ])
        markets = list(connection.execute(
            sa.select(providers.c.market).order_by(providers.c.id)
        ).scalars())

    assert markets == ["both", "cn", "both"]
