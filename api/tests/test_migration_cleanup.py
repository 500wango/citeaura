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
