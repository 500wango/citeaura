from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.db import Base, get_db
from api.main import app
from api.models import Job, Project


@pytest.fixture()
def schedule_client(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-that-is-long-enough-32")
    engine = create_engine(f"sqlite:///{tmp_path / 'schedules.sqlite'}")
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
    registered = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "correct-horse-battery"},
    )
    assert registered.status_code == 201
    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "correct-horse-battery"},
    )
    return registered.json()["tenant"]["id"], {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_project_schedule_can_be_enabled_read_and_disabled(schedule_client):
    client, session_factory = schedule_client
    tenant_id, headers = _register(client, "owner@example.com")
    _, other_headers = _register(client, "other@example.com")
    with session_factory() as db:
        project = Project(
            tenant_id=tenant_id,
            slug="example",
            url="https://example.com",
            market="both",
            status="ready",
        )
        db.add(project)
        db.commit()
        project_id = project.id

    initial = client.get(f"/api/v1/projects/{project_id}/schedule", headers=headers)
    assert initial.status_code == 200
    assert initial.json()["schedule"]["enabled"] is False
    assert initial.json()["schedule"]["interval_days"] == 0
    assert initial.json()["schedule"]["next_run_at"] is None
    assert initial.json()["schedule"]["last_enqueued_at"] is None
    assert initial.json()["schedule"]["alert_on_regression"] is False

    before = datetime.now(timezone.utc)
    enabled = client.post(
        f"/api/v1/projects/{project_id}/schedule",
        headers=headers,
        json={"interval_days": 14},
    )
    assert enabled.status_code == 200
    schedule = enabled.json()["schedule"]
    assert schedule["enabled"] is True
    assert schedule["interval_days"] == 14
    next_run = datetime.fromisoformat(schedule["next_run_at"]).replace(tzinfo=timezone.utc)
    assert 13.9 < (next_run - before).total_seconds() / 86400 < 14.1

    repeated = client.post(
        f"/api/v1/projects/{project_id}/schedule",
        headers=headers,
        json={"interval_days": 14},
    )
    assert repeated.json()["schedule"]["next_run_at"] == schedule["next_run_at"]
    assert client.get(f"/api/v1/projects/{project_id}/schedule", headers=other_headers).status_code == 404
    assert client.post(
        f"/api/v1/projects/{project_id}/schedule",
        headers=headers,
        json={"interval_days": 10},
    ).status_code == 422

    disabled = client.post(
        f"/api/v1/projects/{project_id}/schedule",
        headers=headers,
        json={"interval_days": 0},
    )
    assert disabled.status_code == 200
    assert disabled.json()["schedule"]["enabled"] is False
    assert disabled.json()["schedule"]["next_run_at"] is None


def test_trial_limit_blocks_new_schedule(schedule_client):
    client, session_factory = schedule_client
    tenant_id, headers = _register(client, "limited@example.com")
    with session_factory() as db:
        project = Project(
            tenant_id=tenant_id,
            slug="limited",
            url="https://limited.example",
            market="both",
            status="ready",
        )
        db.add(project)
        db.flush()
        db.add_all([
            Job(project_id=project.id, action="sample", status="done"),
            Job(project_id=project.id, action="cycle", status="done"),
        ])
        db.commit()
        project_id = project.id

    blocked = client.post(
        f"/api/v1/projects/{project_id}/schedule",
        headers=headers,
        json={"interval_days": 7},
    )
    assert blocked.status_code == 403
    assert blocked.json()["error"] == "trial_limit_exceeded"


def test_schedule_can_enable_regression_email_alerts(schedule_client):
    client, session_factory = schedule_client
    tenant_id, headers = _register(client, "alerts@example.com")
    with session_factory() as db:
        project = Project(
            tenant_id=tenant_id,
            slug="alerts",
            url="https://alerts.example",
            market="global",
            status="ready",
        )
        db.add(project)
        db.commit()
        project_id = project.id

    enabled = client.post(
        f"/api/v1/projects/{project_id}/schedule",
        headers=headers,
        json={"interval_days": 7, "alert_on_regression": True},
    )
    assert enabled.status_code == 200
    assert enabled.json()["schedule"]["alert_on_regression"] is True
    saved = client.get(f"/api/v1/projects/{project_id}/schedule", headers=headers)
    assert saved.json()["schedule"]["alert_on_regression"] is True
    disabled = client.post(
        f"/api/v1/projects/{project_id}/schedule",
        headers=headers,
        json={"interval_days": 7, "alert_on_regression": False},
    )
    assert disabled.json()["schedule"]["alert_on_regression"] is False
