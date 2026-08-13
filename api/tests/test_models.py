from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

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
        "custom_providers",
        "audit_events",
        "admin_audit_events",
        "billing_events",
        "jobs",
        "integration_credentials",
        "payment_transactions",
        "platform_admins",
        "product_events",
        "sso_configurations",
        "subscriptions",
        "team_invitations",
        "usage_counters",
    }
    project_columns = {item["name"] for item in inspect(engine).get_columns("projects")}
    assert {"monthly_budget_cny_fen", "sample_call_limit", "pause_on_budget_exceeded"} <= project_columns


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
