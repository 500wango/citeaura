import base64
import json
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.adapters import engine as engine_adapter
from api.adapters import integrations
from api.db import Base, get_db
from api.main import app
from api.models import IntegrationCredential, Job, Project
from api.settings.crypto import decrypt_key


@pytest.fixture()
def integration_client(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-that-is-long-enough-32")
    monkeypatch.setenv("AES_KEY", base64.urlsafe_b64encode(b"0" * 32).decode())
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "google-client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "google-client-secret")
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://testserver")
    monkeypatch.setattr(engine_adapter, "WORK_ROOT", tmp_path / "work")
    engine = create_engine(f"sqlite:///{tmp_path / 'integrations.sqlite'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client, session_factory, tmp_path
    app.dependency_overrides.clear()


def _register(client, email="owner@example.com", tenant_name="tenant-a"):
    registered = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "correct-horse-battery", "tenant_name": tenant_name},
    ).json()
    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "correct-horse-battery"},
    ).json()
    return registered, {"Authorization": f"Bearer {login['access_token']}"}


def _project(session_factory, tenant_id):
    with session_factory() as db:
        project = Project(
            tenant_id=tenant_id,
            slug="example-com",
            url="https://www.example.com",
            market="global",
            status="ready",
        )
        db.add(project)
        db.commit()
        db.refresh(project)
        return project.id


def test_semrush_config_is_encrypted_and_sync_is_tenant_isolated(integration_client, monkeypatch):
    client, session_factory, _tmp_path = integration_client
    registered, headers = _register(client)
    tenant_id = registered["tenant"]["id"]
    project_id = _project(session_factory, tenant_id)

    initial = client.get("/api/v1/integrations", headers=headers)
    assert initial.status_code == 200
    assert initial.json()["providers"]["semrush"]["configured"] is False
    configured = client.put(
        "/api/v1/integrations/semrush",
        headers=headers,
        json={"api_key": "semrush-secret-value", "database": "gb"},
    )
    assert configured.status_code == 200
    assert configured.json()["providers"]["semrush"] == {
        "configured": True,
        "masked": "****alue",
        "database": "gb",
    }
    assert "semrush-secret-value" not in configured.text
    with session_factory() as db:
        row = db.query(IntegrationCredential).one()
        assert row.provider == "semrush"
        assert row.encrypted_value != "semrush-secret-value"
        assert decrypt_key(row.encrypted_value) == "semrush-secret-value"

    queued = []
    from api.integrations import router as integration_router

    monkeypatch.setattr(
        integration_router.task_sync_integration,
        "delay",
        lambda *args, **kwargs: queued.append((args, kwargs)),
    )
    sync = client.post(
        f"/api/v1/projects/{project_id}/integrations/semrush/sync",
        headers=headers,
    )
    assert sync.status_code == 202
    assert sync.json()["provider"] == "semrush"
    assert queued[0][0] == ("tenant-a", "example-com", "semrush")

    _other, other_headers = _register(client, "other@example.net", "tenant-b")
    assert client.get(f"/api/v1/projects/{project_id}/integrations", headers=other_headers).status_code == 404
    assert client.post(
        f"/api/v1/projects/{project_id}/integrations/semrush/sync",
        headers=other_headers,
    ).status_code == 404


def test_search_console_oauth_binds_verified_project_property(integration_client, monkeypatch):
    client, session_factory, _tmp_path = integration_client
    registered, headers = _register(client)
    tenant_id = registered["tenant"]["id"]
    project_id = _project(session_factory, tenant_id)

    started = client.get(
        "/api/v1/integrations/search-console/authorize",
        params={"project_id": project_id},
        headers=headers,
        follow_redirects=False,
    )
    assert started.status_code == 303
    location = started.headers["location"]
    query = parse_qs(urlparse(location).query)
    assert query["client_id"] == ["google-client-id"]
    assert query["scope"] == [integrations.GOOGLE_SCOPE]
    state = query["state"][0]

    monkeypatch.setattr(
        integrations,
        "exchange_google_code",
        lambda code: {"access_token": "temporary-access", "refresh_token": "google-refresh-secret"},
    )
    monkeypatch.setattr(
        integrations,
        "search_console_sites",
        lambda token: [{"siteUrl": "sc-domain:example.com", "permissionLevel": "siteOwner"}],
    )
    callback = client.get(
        "/api/v1/integrations/search-console/callback",
        params={"code": "google-code", "state": state},
        follow_redirects=False,
    )
    assert callback.status_code == 303
    assert callback.headers["location"] == "/?integration=search_console#settings"
    with session_factory() as db:
        row = db.query(IntegrationCredential).one()
        assert row.provider == "search_console"
        assert decrypt_key(row.encrypted_value) == "google-refresh-secret"
        assert json.loads(row.config_json)["properties"][str(project_id)] == "sc-domain:example.com"

    overview = client.get(f"/api/v1/projects/{project_id}/integrations", headers=headers)
    assert overview.status_code == 200
    assert overview.json()["search_console_property"] == "sc-domain:example.com"
    assert overview.json()["latest"] == {"semrush": None, "search_console": None}
    assert "google-refresh-secret" not in overview.text


def test_integration_adapters_parse_metrics_and_store_snapshots(tmp_path, monkeypatch):
    class SemrushResponse:
        text = (
            "Keyword;Position;Search Volume;CPC;Url;Traffic (%);Traffic Cost;Competition;Number of Results;Trends\n"
            "geo platform;3;120;1.2;https://example.com/geo;15.5;42.5;0.7;9000;1,2,3\n"
            "ai visibility;14;80;0.8;https://example.com/ai;4.5;10;0.4;7000;3,2,1\n"
        )

        def raise_for_status(self):
            return None

    monkeypatch.setattr(integrations.requests, "get", lambda *args, **kwargs: SemrushResponse())
    semrush = integrations.sync_semrush("https://example.com", "secret", database="us")
    assert semrush["metrics"] == {
        "keywords_returned": 2,
        "top_10_keywords": 1,
        "search_volume": 200,
        "traffic_cost": 52.5,
    }

    monkeypatch.setattr(integrations, "refresh_google_access_token", lambda token: "access")
    monkeypatch.setattr(
        integrations,
        "search_console_sites",
        lambda token: [{"siteUrl": "sc-domain:example.com", "permissionLevel": "siteOwner"}],
    )

    class SearchResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"rows": [
                {"keys": ["geo", "https://example.com/geo"], "clicks": 4, "impressions": 100, "ctr": .04, "position": 3},
                {"keys": ["ai", "https://example.com/ai"], "clicks": 2, "impressions": 50, "ctr": .04, "position": 9},
            ]}

    monkeypatch.setattr(integrations.requests, "post", lambda *args, **kwargs: SearchResponse())
    search_console = integrations.sync_search_console("https://example.com", "refresh")
    assert search_console["metrics"] == {
        "clicks": 6.0,
        "impressions": 150.0,
        "ctr": 0.04,
        "average_position": 5.0,
        "rows": 2,
    }

    from api.adapters import engine as adapter

    monkeypatch.setattr(adapter, "WORK_ROOT", tmp_path / "work")
    with adapter.with_tenant_context("tenant-a", "example-com"):
        integrations.save_snapshot("example-com", "semrush", semrush)
        assert integrations.latest_snapshot("example-com", "semrush")["metrics"]["keywords_returned"] == 2
    assert (tmp_path / "work" / "tenant-a" / "example-com" / "integrations" / "semrush" / "latest.json").exists()


def test_integration_worker_uses_encrypted_credential_and_updates_job(integration_client, monkeypatch):
    client, session_factory, tmp_path = integration_client
    registered, headers = _register(client)
    tenant_id = registered["tenant"]["id"]
    project_id = _project(session_factory, tenant_id)
    assert client.put(
        "/api/v1/integrations/semrush",
        headers=headers,
        json={"api_key": "worker-sem-secret", "database": "de"},
    ).status_code == 200
    with session_factory() as db:
        job = Job(project_id=project_id, action="integration_semrush", status="queued")
        db.add(job)
        db.commit()
        db.refresh(job)
        job_id = job.id

    from api.worker import tasks

    monkeypatch.setattr(tasks, "SessionLocal", session_factory)
    captured = {}

    def fake_sync(url, api_key, database, limit=100):
        captured.update({"url": url, "api_key": api_key, "database": database})
        return {
            "provider": "semrush",
            "source": "Semrush API",
            "synced_at": "2026-07-31T12:00:00+00:00",
            "metrics": {"keywords_returned": 0},
            "rows": [],
        }

    monkeypatch.setattr(integrations, "sync_semrush", fake_sync)
    result = tasks.task_sync_integration.run("tenant-a", "example-com", "semrush", job_id=job_id)
    assert result["metrics"] == {"keywords_returned": 0}
    assert captured == {
        "url": "https://www.example.com",
        "api_key": "worker-sem-secret",
        "database": "de",
    }
    with session_factory() as db:
        assert db.get(Job, job_id).status == "done"
    assert (
        tmp_path / "work" / "tenant-a" / "example-com" / "integrations" / "semrush" / "latest.json"
    ).exists()


def test_integration_worker_marks_job_failed_if_credential_was_removed(integration_client, monkeypatch):
    client, session_factory, _tmp_path = integration_client
    registered, _headers = _register(client)
    project_id = _project(session_factory, registered["tenant"]["id"])
    with session_factory() as db:
        job = Job(project_id=project_id, action="integration_semrush", status="queued")
        db.add(job)
        db.commit()
        db.refresh(job)
        job_id = job.id

    from api.worker import tasks

    monkeypatch.setattr(tasks, "SessionLocal", session_factory)
    with pytest.raises(ValueError, match="integration_not_configured"):
        tasks.task_sync_integration.run("tenant-a", "example-com", "semrush", job_id=job_id)
    with session_factory() as db:
        job = db.get(Job, job_id)
        assert job.status == "failed"
        assert "integration_not_configured" in job.error
