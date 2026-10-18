import importlib

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.exc import IntegrityError


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


def _pre_0038_schema(engine):
    """重建 0038 之前的表结构：只保留该迁移读写到的列和索引。"""
    metadata = sa.MetaData()
    sa.Table("tenants", metadata, sa.Column("id", sa.Integer, primary_key=True))
    sa.Table("users", metadata, sa.Column("id", sa.Integer, primary_key=True))
    sa.Table(
        "jobs",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("project_id", sa.Integer, nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
    )
    sa.Table(
        "api_keys",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tenant_id", sa.Integer, nullable=False),
        sa.Column("engine_code", sa.String(64), nullable=False),
        sa.Column("encrypted_value", sa.Text, nullable=False),
    )
    sa.Table(
        "api_access_tokens",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tenant_id", sa.Integer, nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
    )
    subscriptions = sa.Table(
        "subscriptions",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tenant_id", sa.Integer, nullable=False),
        sa.Column("plan", sa.String(32), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_subscription_id", sa.String(255), nullable=True),
    )
    billing_events = sa.Table(
        "billing_events",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("notification_key", sa.String(255), nullable=True),
    )
    sa.Index("ix_billing_events_notification_key", billing_events.c.notification_key)
    sa.Table(
        "platform_usage",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tenant_id", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    sa.Table(
        "platform_usage_outbox",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    sa.Table(
        "memberships",
        metadata,
        sa.Column("tenant_id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, primary_key=True),
    )
    metadata.create_all(engine)
    return metadata, subscriptions, billing_events


def test_security_reliability_migration_repairs_data_before_unique_indexes():
    """0038 必须先修数据再建唯一索引，否则真实库会直接迁移失败。"""
    from datetime import datetime

    migration = importlib.import_module("api.migrations.versions.0038_security_reliability")
    engine = sa.create_engine("sqlite:///:memory:")
    _metadata, subscriptions, billing_events = _pre_0038_schema(engine)

    with engine.begin() as connection:
        connection.execute(subscriptions.insert(), [
            {"id": 1, "tenant_id": 1, "status": "active", "started_at": datetime(2026, 1, 1)},
            {"id": 2, "tenant_id": 1, "status": "active", "started_at": datetime(2026, 2, 1)},
            {"id": 3, "tenant_id": 2, "status": "trialing", "started_at": datetime(2026, 1, 5)},
            {"id": 4, "tenant_id": 2, "status": "canceled", "started_at": datetime(2025, 12, 1)},
        ])
        connection.execute(billing_events.insert(), [
            {"id": 1, "notification_key": "pay_1"},
            {"id": 2, "notification_key": "pay_1"},
            {"id": 3, "notification_key": "pay_2"},
            {"id": 4, "notification_key": None},
        ])

    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()

    with engine.begin() as connection:
        statuses = dict(connection.execute(
            sa.text("SELECT id, status FROM subscriptions ORDER BY id")
        ).all())
        keys = dict(connection.execute(
            sa.text("SELECT id, notification_key FROM billing_events ORDER BY id")
        ).all())

    # 只保留最新的当前订阅，旧行被降级为 incomplete。
    assert statuses == {1: "incomplete", 2: "active", 3: "trialing", 4: "canceled"}
    # 重复的通知键被置空，保留 id 最小的一条。
    assert keys == {1: "pay_1", 2: None, 3: "pay_2", 4: None}

    inspector = sa.inspect(engine)
    assert "sso_identities" in inspector.get_table_names()
    assert "heartbeat_at" in {column["name"] for column in inspector.get_columns("jobs")}
    assert "key_suffix" in {column["name"] for column in inspector.get_columns("api_keys")}
    assert "expires_at" in {
        column["name"] for column in inspector.get_columns("api_access_tokens")
    }
    indexes = {
        table: {item["name"] for item in inspector.get_indexes(table)}
        for table in (
            "subscriptions",
            "billing_events",
            "memberships",
            "platform_usage",
            "platform_usage_outbox",
            "api_access_tokens",
            "sso_identities",
        )
    }
    assert "uq_subscriptions_tenant_current" in indexes["subscriptions"]
    assert "uq_billing_events_notification_key" in indexes["billing_events"]
    assert "ix_billing_events_notification_key" not in indexes["billing_events"]
    assert "ix_memberships_user_id" in indexes["memberships"]
    assert "ix_platform_usage_tenant_created" in indexes["platform_usage"]
    assert "ix_platform_usage_outbox_pending" in indexes["platform_usage_outbox"]
    assert "ix_api_access_tokens_expires_at" in indexes["api_access_tokens"]
    assert {"ix_sso_identities_tenant_id", "ix_sso_identities_user"} <= indexes["sso_identities"]

    # 索引真的生效：第二条"当前订阅"和重复通知键都必须被数据库拒绝。
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(subscriptions.insert(), {
                "id": 5, "tenant_id": 2, "status": "active",
                "started_at": datetime(2026, 3, 1),
            })
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(billing_events.insert(), [
                {"id": 6, "notification_key": "pay_9"},
                {"id": 7, "notification_key": "pay_9"},
            ])
