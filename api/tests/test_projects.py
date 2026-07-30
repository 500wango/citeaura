import json
import sys
import types
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.db import Base, get_db
from api.main import app
from api.models import Job, Project, Tenant
from api.projects import router as project_router


@pytest.fixture()
def project_client(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-that-is-long-enough-32")
    engine = create_engine(f"sqlite:///{tmp_path / 'projects.sqlite'}")
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
        yield test_client, session_factory
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
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_project_create_list_detail_and_jobs(project_client, monkeypatch, tmp_path):
    client, session_factory = project_client
    headers = _register(client, "owner@example.com")
    calls = []

    def fake_init(args):
        calls.append(args)
        from api.adapters.engine import geolib

        config_dir = geolib.project_dir(args.slug)
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "geo.json").write_text(
            json.dumps({
                "brand": {"name": "Example", "site": args.url},
                "market": args.market,
                "questions": [{"id": "q001", "text": "What is Example?", "market": "global"}],
            }),
            "utf-8",
        )
        return {"slug": args.slug}

    fake_geo = types.SimpleNamespace(cmd_init=fake_init)
    monkeypatch.setitem(sys.modules, "geo", fake_geo)
    monkeypatch.setattr(project_router.task_bootstrap, "delay", lambda *a, **kw: types.SimpleNamespace(id="celery-1"))

    created = client.post("/api/v1/projects", headers=headers, json={"url": "example.com", "market": "global"})
    assert created.status_code == 202
    body = created.json()
    assert body["project_id"] == 1
    assert body["job_id"] == 1
    assert calls[0].url == "https://example.com"

    listed = client.get("/api/v1/projects", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["projects"][0]["slug"] == "example-com"

    detail = client.get(f"/api/v1/projects/{body['project_id']}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["brand"]["name"] == "Example"
    assert detail.json()["questions"][0]["id"] == "q001"

    jobs = client.get(f"/api/v1/projects/{body['project_id']}/jobs", headers=headers)
    assert jobs.status_code == 200
    assert jobs.json()["jobs"][0]["status"] == "queued"

    job = client.get(f"/api/v1/projects/{body['project_id']}/jobs/{body['job_id']}", headers=headers)
    assert job.status_code == 200
    assert job.json()["job"]["log_path"] == "celery://celery-1"


def test_project_isolation_and_duplicate_rejection(project_client, monkeypatch):
    client, _ = project_client
    owner_headers = _register(client, "owner@example.com")
    other_headers = _register(client, "other@example.com")
    monkeypatch.setattr(project_router, "with_tenant_context", lambda *args, **kwargs: _empty_context())
    monkeypatch.setattr(project_router.task_bootstrap, "delay", lambda *a, **kw: types.SimpleNamespace(id="celery-1"))
    monkeypatch.setitem(sys.modules, "geo", types.SimpleNamespace(cmd_init=lambda args: None))

    created = client.post("/api/v1/projects", headers=owner_headers, json={"url": "example.com"})
    assert created.status_code == 202
    duplicate = client.post("/api/v1/projects", headers=owner_headers, json={"url": "example.com"})
    assert duplicate.status_code == 409
    hidden = client.get(f"/api/v1/projects/{created.json()['project_id']}", headers=other_headers)
    assert hidden.status_code == 404
    assert client.get("/api/v1/projects", headers=other_headers).json()["projects"] == []


@contextmanager
def _empty_context():
    yield

