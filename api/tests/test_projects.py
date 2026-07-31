import json
import sys
import types
import zipfile
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

    created = client.post(
        "/api/v1/projects",
        headers=headers,
        json={"url": "example.com", "name": "Example Brand", "market": "global"},
    )
    assert created.status_code == 202
    body = created.json()
    assert body["project_id"] == 1
    assert body["job_id"] == 1
    assert calls[0].url == "https://example.com"
    assert calls[0].name == "Example Brand"

    listed = client.get("/api/v1/projects", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["projects"][0]["slug"] == "example-com"

    detail = client.get(f"/api/v1/projects/{body['project_id']}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["brand"]["name"] == "Example"
    assert detail.json()["questions"][0]["id"] == "q001"

    with session_factory() as db:
        db.get(Job, body["job_id"]).status = "done"
        db.commit()

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
    with session_factory() as db:
        db.get(Job, sampled.json()["job_id"]).status = "done"
        db.commit()

    geolib.write_json(
        project_dir / "tasks.json",
        {
            "summary": {"total": 1, "by_status": {"todo": 1}},
            "tasks": [{
                "id": "T-001", "title": "Fix it", "priority": "P0", "package": "页面技术",
                "market": "both", "status": "todo", "evidence": [],
                "acceptance": {"type": "manual", "desc": "done"},
            }],
        },
    )
    tickets = client.get(f"/api/v1/projects/{body['project_id']}/tickets", headers=headers)
    assert tickets.status_code == 200
    assert tickets.json()["tickets"][0]["id"] == "T-001"
    updated = client.patch(
        f"/api/v1/projects/{body['project_id']}/tickets/T-001",
        headers=headers,
        json={"status": "done", "note": "verified manually"},
    )
    assert updated.status_code == 200
    assert updated.json()["ticket"]["status"] == "done"

    geolib.write_json(
        project_dir / "verify" / "2026-07-31-120000.json",
        {"verified_at": "2026-07-31T12:00:00+00:00", "changed": 1, "results": []},
    )
    history = client.get(f"/api/v1/projects/{body['project_id']}/verify/history", headers=headers)
    assert history.status_code == 200
    assert history.json()["history"][0]["changed"] == 1

    monkeypatch.setattr(project_router.task_verify, "delay", lambda *a, **kw: types.SimpleNamespace(id="celery-3"))
    verified = client.post(f"/api/v1/projects/{body['project_id']}/verify", headers=headers)
    assert verified.status_code == 202
    assert verified.json()["job_id"] == 3
    with session_factory() as db:
        db.get(Job, verified.json()["job_id"]).status = "done"
        db.commit()

    (project_dir / "delivery" / "2026-07-31").mkdir(parents=True, exist_ok=True)
    (project_dir / "delivery" / "2026-07-31" / "index.html").write_text("<h1>Delivery</h1>", "utf-8")
    deliveries = client.get(f"/api/v1/projects/{body['project_id']}/deliveries", headers=headers)
    assert deliveries.status_code == 200
    assert deliveries.json()["deliveries"] == ["2026-07-31"]
    monkeypatch.setattr(project_router.task_deliver, "delay", lambda *a, **kw: types.SimpleNamespace(id="celery-4"))
    delivered = client.post(f"/api/v1/projects/{body['project_id']}/deliver", headers=headers)
    assert delivered.status_code == 202
    assert delivered.json()["job_id"] == 4
    archive = client.get(f"/api/v1/projects/{body['project_id']}/deliveries/2026-07-31", headers=headers)
    assert archive.status_code == 200
    assert archive.headers["content-type"] == "application/zip"
    import io
    with zipfile.ZipFile(io.BytesIO(archive.content)) as bundle:
        assert bundle.namelist() == ["index.html"]

    jobs = client.get(f"/api/v1/projects/{body['project_id']}/jobs", headers=headers)
    assert jobs.status_code == 200
    assert jobs.json()["jobs"][0]["status"] == "queued"

    job = client.get(f"/api/v1/projects/{body['project_id']}/jobs/{body['job_id']}", headers=headers)
    assert job.status_code == 200
    assert job.json()["job"]["log_path"] == str(project_dir / ".jobs" / "1.log")

    log_path = project_dir / ".jobs" / "1.log"
    log_path.parent.mkdir(parents=True)
    log_path.write_text("first\nsecond\n", "utf-8")
    incremental = client.get(
        f"/api/v1/projects/{body['project_id']}/jobs/{body['job_id']}?offset=6",
        headers=headers,
    )
    assert incremental.status_code == 200
    assert incremental.json()["job"]["log"] == "second\n"
    assert incremental.json()["job"]["log_offset"] == 13


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


def test_pipeline_actions_are_whitelisted_and_project_serialized(project_client, monkeypatch):
    client, session_factory = project_client
    headers = _register(client, "owner@example.com")
    monkeypatch.setattr(project_router, "with_tenant_context", lambda *args, **kwargs: _empty_context())
    monkeypatch.setitem(sys.modules, "geo", types.SimpleNamespace(cmd_init=lambda args: None))
    monkeypatch.setattr(project_router.task_bootstrap, "delay", lambda *a, **kw: None)

    created = client.post("/api/v1/projects", headers=headers, json={"url": "example.com"}).json()
    blocked = client.post(
        f"/api/v1/projects/{created['project_id']}/actions/audit",
        headers=headers,
        json={"params": {}},
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"] == "project_job_already_running"

    with session_factory() as db:
        db.get(Job, created["job_id"]).status = "done"
        db.commit()
    queued = []
    monkeypatch.setattr(project_router.task_pipeline, "delay", lambda *args, **kwargs: queued.append((args, kwargs)))
    started = client.post(
        f"/api/v1/projects/{created['project_id']}/actions/audit",
        headers=headers,
        json={"params": {"ignored": "value"}},
    )
    assert started.status_code == 202
    assert started.json()["action"] == "audit"
    assert queued[0][0][:3] == ("owner", "example-com", "audit")
    assert queued[0][1]["params"] == {"ignored": "value"}

    actions = client.get("/api/v1/projects/actions", headers=headers)
    assert actions.status_code == 200
    assert {"autopilot", "serve", "audit", "generate", "deliverables"} <= set(actions.json()["actions"])
    unsupported = client.post(
        f"/api/v1/projects/{created['project_id']}/actions/publish",
        headers=headers,
        json={"params": {}},
    )
    assert unsupported.status_code == 400


@contextmanager
def _empty_context():
    yield
