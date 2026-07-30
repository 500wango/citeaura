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
from api.adapters import engine as engine_adapter


@pytest.fixture()
def project_client(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-that-is-long-enough-32")
    monkeypatch.setattr(engine_adapter, "WORK_ROOT", tmp_path / "work")
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

    from api.adapters.engine import geolib

    project_dir = tmp_path / "work" / "owner" / "example-com"
    geolib.write_json(
        project_dir / "metrics" / "2026-07-31.json",
        {
            "date": "2026-07-31",
            "platforms": {
                "deepseek": {
                    "market": "global",
                    "mention_rate": 0.5,
                    "top3_rate": 0.5,
                    "avg_rank": 1,
                    "own_domain_cite_rate": 0,
                }
            },
        },
    )
    geolib.write_jsonl(
        project_dir / "samples" / "2026-07-31.jsonl",
        [
            {
                "platform": "deepseek",
                "platform_name": "DeepSeek",
                "market": "global",
                "sample_mode": "api",
                "search_enabled": False,
                "question": "What is Example?",
                "answer": "Example is a product.",
                "elapsed_ms": 12,
                "analysis": {
                    "brand_mentioned": True,
                    "brand_rank": 1,
                    "own_domain_cited": False,
                    "cited_domains": [],
                    "competitors_mentioned": [],
                    "candidates": ["Example"],
                    "negative_cues": [],
                },
            }
        ],
    )
    report = client.get(f"/api/v1/projects/{body['project_id']}/report", headers=headers)
    assert report.status_code == 200
    assert report.json()["report"]["platforms"]["deepseek"]["mention_rate"] == 0.5
    engines = client.get(f"/api/v1/projects/{body['project_id']}/engines", headers=headers)
    assert engines.status_code == 200
    assert engines.json()["engines"][0]["sampling_mode"] == "API·参数化"
    samples = client.get(f"/api/v1/projects/{body['project_id']}/samples/2026-07-31", headers=headers)
    assert samples.status_code == 200
    assert samples.json()["samples"][0]["answer"] == "Example is a product."

    monkeypatch.setattr(project_router.task_sample, "delay", lambda *a, **kw: types.SimpleNamespace(id="celery-2"))
    sampled = client.post(
        f"/api/v1/projects/{body['project_id']}/sample",
        headers=headers,
        json={"limit": 2, "platforms": ["deepseek"]},
    )
    assert sampled.status_code == 202
    assert sampled.json()["job_id"] == 2

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
