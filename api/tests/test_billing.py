import base64
import types
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.db import Base, get_db
from api.main import app
from api.models import Job, Project, Subscription, Tenant
from api.projects import router as project_router


@pytest.fixture()
def billing_client(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-that-is-long-enough-32")
    monkeypatch.setattr("api.adapters.engine.WORK_ROOT", tmp_path / "work")
    engine = create_engine(f"sqlite:///{tmp_path / 'billing.sqlite'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client, session_factory
    app.dependency_overrides.clear()


def _register(client, email):
    assert client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "correct-horse-battery"},
    ).status_code == 201
    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "correct-horse-battery"},
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_trial_project_limit_and_usage(billing_client, monkeypatch):
    client, session_factory = billing_client
    headers = _register(client, "owner@example.com")
    monkeypatch.setitem(__import__("sys").modules, "geo", types.SimpleNamespace(cmd_init=lambda args: None))
    monkeypatch.setattr(project_router.task_bootstrap, "delay", lambda *a, **kw: types.SimpleNamespace(id="boot"))

    for index in range(3):
        response = client.post(
            "/api/v1/projects",
            headers=headers,
            json={"url": f"example{index}.com"},
        )
        assert response.status_code == 202
    blocked = client.post(
        "/api/v1/projects",
        headers=headers,
        json={"url": "example3.com"},
    )
    assert blocked.status_code == 403
    assert blocked.json()["error"] == "trial_limit_exceeded"

    usage = client.get("/api/v1/billing/usage", headers=headers)
    assert usage.status_code == 200
    assert usage.json()["projects_active"] == 3
    assert usage.json()["projects_limit"] == 3


def test_trial_sample_limit_is_per_project(billing_client, monkeypatch):
    client, session_factory = billing_client
    headers = _register(client, "owner@example.com")
    monkeypatch.setitem(__import__("sys").modules, "geo", types.SimpleNamespace(cmd_init=lambda args: None))
    monkeypatch.setattr(project_router.task_bootstrap, "delay", lambda *a, **kw: types.SimpleNamespace(id="boot"))
    created = client.post("/api/v1/projects", headers=headers, json={"url": "example.com"})
    project_id = created.json()["project_id"]
    monkeypatch.setattr(project_router.task_sample, "delay", lambda *a, **kw: types.SimpleNamespace(id="sample"))

    with session_factory() as db:
        db.query(Job).filter(Job.project_id == project_id, Job.action == "bootstrap").one().status = "done"
        db.commit()

    for _ in range(2):
        response = client.post(f"/api/v1/projects/{project_id}/sample", headers=headers)
        assert response.status_code == 202
        with session_factory() as db:
            job = db.query(Job).filter(Job.project_id == project_id, Job.action == "sample").order_by(Job.id.desc()).first()
            job.status = "done"
            db.commit()
    blocked = client.post(f"/api/v1/projects/{project_id}/sample", headers=headers)
    assert blocked.status_code == 403
    assert blocked.json()["error"] == "trial_limit_exceeded"
    blocked_cycle = client.post(
        f"/api/v1/projects/{project_id}/actions/serve",
        headers=headers,
        json={"params": {}},
    )
    assert blocked_cycle.status_code == 403
    assert blocked_cycle.json()["error"] == "trial_limit_exceeded"


def test_subscribe_upgrades_plan_and_opens_limits(billing_client):
    client, _ = billing_client
    headers = _register(client, "owner@example.com")
    plans = client.get("/api/v1/billing/plans")
    assert plans.status_code == 200
    assert {plan["code"] for plan in plans.json()["plans"]} == {"pro", "agency", "enterprise"}

    subscribed = client.post("/api/v1/billing/subscribe", headers=headers, json={"plan": "pro"})
    assert subscribed.status_code == 200
    assert subscribed.json()["plan"] == "pro"
    assert subscribed.json()["payment"] == "mock"
    usage = client.get("/api/v1/billing/usage", headers=headers)
    assert usage.json()["plan"] == "pro"
    assert usage.json()["projects_limit"] is None
    assert usage.json()["sample_runs_limit_per_project"] is None


def test_annual_plan_catalog_and_subscription_snapshot(billing_client, monkeypatch):
    client, session_factory = billing_client
    headers = _register(client, "annual-owner@example.com")
    monkeypatch.setenv("BILLING_ANNUAL_DISCOUNT_PERCENT", "16.67")

    plans = client.get("/api/v1/billing/plans").json()["plans"]
    pro = next(plan for plan in plans if plan["code"] == "pro")
    assert pro["prices"]["monthly"] == {"cny": 199, "usd": 29, "months": 1}
    assert pro["prices"]["annual"] == {"cny": 1990, "usd": 290, "months": 12}
    assert pro["annual_savings_cny"] == 398
    assert pro["annual_discount_percent"] == 16.67

    subscribed = client.post(
        "/api/v1/billing/subscribe",
        headers=headers,
        json={"plan": "pro", "billing_interval": "annual"},
    )
    assert subscribed.status_code == 200
    result = subscribed.json()
    assert result["billing_interval"] == "annual"
    assert result["amount_cny_fen"] == 199000
    assert result["amount_usd_cents"] == 29000
    started = datetime.fromisoformat(result["started_at"])
    expires = datetime.fromisoformat(result["expires_at"])
    assert (expires.year, expires.month, expires.day) == (started.year + 1, started.month, started.day)

    with session_factory() as db:
        snapshot = db.query(Subscription).one()
        assert snapshot.billing_interval == "annual"
        assert snapshot.amount_cny_fen == 199000

    usage = client.get("/api/v1/billing/usage", headers=headers).json()
    assert usage["subscription"]["billing_interval"] == "annual"
    assert usage["subscription"]["amount_cny_fen"] == 199000


def test_subscribe_rejects_invalid_billing_interval(billing_client):
    client, _ = billing_client
    headers = _register(client, "invalid-interval@example.com")
    response = client.post(
        "/api/v1/billing/subscribe",
        headers=headers,
        json={"plan": "pro", "billing_interval": "weekly"},
    )
    assert response.status_code == 422


def test_expired_trial_cannot_create_projects(billing_client):
    client, session_factory = billing_client
    headers = _register(client, "expired@example.com")
    with session_factory() as db:
        tenant = db.query(Tenant).filter(Tenant.name == "expired").one()
        tenant.trial_ends_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()

    blocked = client.post(
        "/api/v1/projects",
        headers=headers,
        json={"url": "expired.example"},
    )
    assert blocked.status_code == 403
    assert blocked.json() == {"error": "trial_limit_exceeded", "detail": "trial has expired"}
