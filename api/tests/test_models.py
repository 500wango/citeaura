from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateIndex

from api.db import Base
from api.models import (
    Membership,
    Job,
    PasswordResetToken,
    Project,
    Subscription,
    TeamInvitation,
    Tenant,
    UsageCounter,
    User,
)


def test_models_create_and_preserve_tenant_relationships():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    tenant = Tenant(name="acme", plan="trial")
    user = User(email="owner@example.com", password_hash="hash")
    tenant.memberships.append(Membership(user=user, role="owner"))
    tenant.projects.append(Project(slug="example", url="https://example.com", market="cn"))
    tenant.usage_counters.append(UsageCounter(
        month=date(2026, 7, 1),
        sample_runs=1,
        projects_active=1,
        platform_calls=2,
        platform_cost_cny_fen=6,
    ))
    tenant.invitations.append(TeamInvitation(
        email="editor@example.com",
        role="editor",
        token_hash="a" * 64,
        expires_at=datetime(2026, 8, 7, tzinfo=timezone.utc),
    ))
    tenant.subscriptions.append(Subscription(
        plan="pro",
        billing_interval="annual",
        amount_cny_fen=199000,
        amount_usd_cents=29000,
        status="active",
        provider="stripe",
        provider_subscription_id="sub_annual",
        expires_at=datetime(2027, 7, 31, tzinfo=timezone.utc),
    ))
    session.add(tenant)
    session.commit()

    assert session.query(Tenant).one().projects[0].slug == "example"
    assert session.query(Membership).one().role == "owner"
    assert session.query(UsageCounter).one().sample_runs == 1
    assert session.query(UsageCounter).one().platform_cost_cny_fen == 6
    assert session.query(TeamInvitation).one().role == "editor"
    assert session.query(Subscription).one().billing_interval == "annual"
    assert session.query(Subscription).one().provider_subscription_id == "sub_annual"
    reset = PasswordResetToken(
        user_id=user.id,
        token_hash="b" * 64,
        expires_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
    )
    session.add(reset)
    session.commit()
    assert session.query(PasswordResetToken).one().user.email == "owner@example.com"


def test_initial_schema_contains_all_tables():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    assert set(inspect(engine).get_table_names()) == {
        "tenants",
        "users",
        "memberships",
        "password_reset_tokens",
        "platform_usage",
        "projects",
        "api_keys",
        "prompt_projections",
        "run_projections",
        "sample_projections",
        "projection_states",
        "custom_providers",
        "audit_events",
        "admin_audit_events",
        "billing_events",
        "jobs",
        "integration_credentials",
        "payment_transactions",
        "platform_admins",
        "product_events",
        "subscriptions",
        "team_invitations",
        "usage_counters",
        "refresh_tokens",
        "platform_usage_outbox",
        "delivery_shares",
        "public_audits",
        "api_access_tokens",
        "subscription_demotions",
    }
    project_columns = {item["name"] for item in inspect(engine).get_columns("projects")}
    assert {
        "monthly_budget_cny_fen",
        "sample_call_limit",
        "pause_on_budget_exceeded",
        "alert_on_regression",
    } <= project_columns
    # 0038 新增列：掩码、任务心跳、集成令牌过期时间。
    assert "key_suffix" in {item["name"] for item in inspect(engine).get_columns("api_keys")}
    assert "heartbeat_at" in {item["name"] for item in inspect(engine).get_columns("jobs")}
    assert "expires_at" in {
        item["name"] for item in inspect(engine).get_columns("api_access_tokens")
    }


def _indexes(engine, table):
    return {item["name"]: item for item in inspect(engine).get_indexes(table)}


def _declared_indexes(table):
    """Index objects as declared on the model (authoritative unique/predicate)."""
    return {index.name: index for index in Base.metadata.tables[table].indexes}


def _create_index_sql(index, engine):
    """Render the DDL the model asks the database to emit for one index."""
    return str(CreateIndex(index).compile(dialect=engine.dialect))


def test_models_declare_the_reliability_indexes_from_migration_0038():
    """模型与 0038 的索引清单必须一致，否则 autogenerate 会永远报告漂移。"""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    # SQLite 反射把唯一标记返回成 1/0（整型），因此断言真值而不是 `is True`。
    directory_slug = _indexes(engine, "tenants")["uq_tenants_directory_slug"]
    assert directory_slug["unique"]
    assert directory_slug["column_names"] == ["directory_slug"]

    current = _indexes(engine, "subscriptions")["uq_subscriptions_tenant_current"]
    assert current["unique"]
    assert current["column_names"] == ["tenant_id"]
    current_ddl = _create_index_sql(
        _declared_indexes("subscriptions")["uq_subscriptions_tenant_current"], engine,
    )
    assert current_ddl.startswith("CREATE UNIQUE INDEX")
    assert "(tenant_id)" in current_ddl
    assert " WHERE " in current_ddl
    assert "status IN ('active', 'trialing', 'past_due')" in current_ddl

    billing = _indexes(engine, "billing_events")
    notification = billing["uq_billing_events_notification_key"]
    assert notification["unique"]
    assert notification["column_names"] == ["notification_key"]
    notification_ddl = _create_index_sql(
        _declared_indexes("billing_events")["uq_billing_events_notification_key"], engine,
    )
    assert notification_ddl.startswith("CREATE UNIQUE INDEX")
    assert " WHERE " in notification_ddl
    assert "notification_key IS NOT NULL" in notification_ddl
    # 唯一的通知键索引取代了原来普通 index=True。
    assert "ix_billing_events_notification_key" not in billing
    assert "ix_billing_events_notification_key" not in _declared_indexes("billing_events")

    assert "ix_memberships_user_id" in _indexes(engine, "memberships")
    assert "ix_platform_usage_tenant_created" in _indexes(engine, "platform_usage")
    assert "ix_platform_usage_outbox_pending" in _indexes(engine, "platform_usage_outbox")
    assert "ix_api_access_tokens_expires_at" in _indexes(engine, "api_access_tokens")


def test_project_allows_only_one_active_job():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    tenant = Tenant(name="active-job", plan="trial")
    project = Project(tenant=tenant, slug="example", url="https://example.com", market="both")
    session.add_all([tenant, project])
    session.flush()
    first = Job(project_id=project.id, action="sample", status="queued")
    session.add(first)
    session.commit()

    session.add(Job(project_id=project.id, action="verify", status="running"))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()

    first.status = "done"
    session.add_all([
        Job(project_id=project.id, action="verify", status="running"),
        Job(project_id=project.id, action="sample", status="failed"),
    ])
    session.commit()
    assert session.query(Job).count() == 3


def test_tenant_allows_only_one_current_subscription():
    """uq_subscriptions_tenant_current：应用层加锁挡不住"两条新行并发插入"。"""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    tenant = Tenant(name="two-subscriptions", plan="pro")
    session.add(tenant)
    session.flush()
    session.add(Subscription(tenant_id=tenant.id, plan="pro", status="active", provider="stripe"))
    session.commit()

    session.add(Subscription(tenant_id=tenant.id, plan="pro", status="trialing", provider="stripe"))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()

    # 已取消的历史订阅不占用"当前订阅"的唯一位置。
    session.add(Subscription(tenant_id=tenant.id, plan="pro", status="canceled", provider="stripe"))
    session.commit()
    assert session.query(Subscription).count() == 2
