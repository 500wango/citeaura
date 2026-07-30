from datetime import date

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from api.db import Base
from api.models import Membership, Project, Tenant, UsageCounter, User


def test_models_create_and_preserve_tenant_relationships():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    tenant = Tenant(name="acme", plan="trial")
    user = User(email="owner@example.com", password_hash="hash")
    tenant.memberships.append(Membership(user=user, role="owner"))
    tenant.projects.append(Project(slug="example", url="https://example.com", market="cn"))
    tenant.usage_counters.append(UsageCounter(month=date(2026, 7, 1), sample_runs=1, projects_active=1))
    session.add(tenant)
    session.commit()

    assert session.query(Tenant).one().projects[0].slug == "example"
    assert session.query(Membership).one().role == "owner"
    assert session.query(UsageCounter).one().sample_runs == 1


def test_initial_schema_contains_all_tables():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    assert set(inspect(engine).get_table_names()) == {
        "tenants",
        "users",
        "memberships",
        "projects",
        "api_keys",
        "jobs",
        "subscriptions",
        "usage_counters",
    }

