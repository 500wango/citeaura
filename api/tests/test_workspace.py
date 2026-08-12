import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.adapters import engine as engine_adapter
from api.adapters import workspace
from api.adapters.engine import with_tenant_context
from api.db import Base, get_db
from api.main import app
from api.models import Job, Project


@pytest.fixture()
def workspace_client(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-that-is-long-enough-32")
    monkeypatch.setattr(engine_adapter, "WORK_ROOT", tmp_path / "work")
    engine = create_engine(f"sqlite:///{tmp_path / 'workspace.sqlite'}")
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
        yield client, session_factory, tmp_path
    app.dependency_overrides.clear()


def _register(client, email, tenant_name):
    registered = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "correct-horse-battery", "tenant_name": tenant_name},
    )
    assert registered.status_code == 201
    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "correct-horse-battery"},
    )
    return registered.json()["tenant"]["id"], {"Authorization": f"Bearer {login.json()['access_token']}"}


def _project(session_factory, tenant_id):
    with session_factory() as db:
        project = Project(
            tenant_id=tenant_id,
            slug="example-com",
            url="https://example.com",
            market="both",
            status="ready",
        )
        db.add(project)
        db.commit()
        return project.id


def _seed_workspace(tmp_path):
    root = tmp_path / "work" / "tenant-a" / "example-com"
    root.mkdir(parents=True)
    (root / "geo.json").write_text(json.dumps({
        "slug": "example-com",
        "market": "global",
        "brand": {"name": "Example", "site": "https://example.com"},
        "questions": [{"id": "q001", "group": "推荐", "market": "both", "text": "推荐 Example 吗？"}],
    }), "utf-8")
    (root / "audit.json").write_text(json.dumps({"avg_score": 72, "page_count": 3, "pages": []}), "utf-8")
    (root / "tasks.json").write_text(json.dumps({
        "summary": {"total": 1, "by_status": {"done": 0}},
        "tasks": [{
            "id": "T-001", "priority": "P0", "package": "页面技术", "market": "both",
            "title": "Fix site", "why": "Audit finding", "action": "Deploy fix", "owner": "开发",
            "effort": "S", "window": "30天", "affected": [],
            "acceptance": {"type": "manual", "desc": "Check fix"},
            "status": "todo", "assets": [], "evidence": [], "closed_at": None,
        }],
    }), "utf-8")
    (root / "content").mkdir()
    (root / "content" / "facts.md").write_text("# Facts\n", "utf-8")
    (root / "assets" / "outlines").mkdir(parents=True)
    (root / "assets" / "outlines" / "q001.md").write_text("# Outline\n", "utf-8")
    (root / "expand.json").write_text(json.dumps({"terms": [{"question": "Example 价格？"}]}), "utf-8")
    (root / "samples").mkdir()
    (root / "samples" / "2026-07-31-manual.md").write_text(
        "# Manual samples\n\n## platform: chatgpt\n\n### q001 · 推荐 Example 吗？\n\n```answer\n\n```\n",
        "utf-8",
    )
    (root / "reports").mkdir()
    (root / "reports" / "2026-07-31.html").write_text("report", "utf-8")
    (root / "deliverables").mkdir()
    (root / "deliverables" / "1-GEO诊断报告.html").write_text("deliverable", "utf-8")
    (root / "delivery" / "2026-07-31").mkdir(parents=True)
    return root


def test_workspace_read_write_flow_and_project_summary(workspace_client, monkeypatch):
    client, session_factory, tmp_path = workspace_client
    monkeypatch.setattr(workspace.geolib, "today", lambda: "2026-07-31")
    tenant_id, headers = _register(client, "owner@example.com", "tenant-a")
    project_id = _project(session_factory, tenant_id)
    root = _seed_workspace(tmp_path)

    config = client.get(f"/api/v1/projects/{project_id}/config", headers=headers)
    assert config.status_code == 200
    assert config.json()["market"] == "both"
    assert config.json()["questions"][0]["id"] == "q001"
    updated = client.patch(
        f"/api/v1/projects/{project_id}/config",
        headers=headers,
        json={
            "market": "global",
            "questions": [{"id": "q001", "group": "推荐", "market": "global", "text": "Best Example tools?"}],
        },
    )
    assert updated.status_code == 200
    assert updated.json()["config"]["market"] == "both"

    changed_url = client.patch(
        f"/api/v1/projects/{project_id}/config",
        headers=headers,
        json={"url": "https://new.example.com/"},
    )
    assert changed_url.status_code == 200
    with session_factory() as db:
        assert db.get(Project, project_id).url == "https://new.example.com"
    assert changed_url.json()["config"]["brand"]["site"] == "https://new.example.com"
    with session_factory() as db:
        assert db.get(Project, project_id).market == "both"
    assert json.loads((root / "geo.json").read_text("utf-8"))["market"] == "both"
    forbidden = client.patch(
        f"/api/v1/projects/{project_id}/config",
        headers=headers,
        json={"publishing": {"webhook": {"url": "https://127.0.0.1"}}},
    )
    assert forbidden.status_code == 400

    added = client.post(
        f"/api/v1/projects/{project_id}/questions",
        headers=headers,
        json={"items": [{"text": "Example pricing?", "market": "global", "group": "价格"}]},
    )
    assert added.status_code == 200
    assert added.json()["ids"] == ["q101"]

    first_offsite = client.post(
        f"/api/v1/projects/{project_id}/tickets",
        headers=headers,
        json={
            "url": "https://directory.example/vendors/example/",
            "ask_text": "Add the official site and current pricing source.",
            "influenced_questions": ["q001"],
        },
    )
    assert first_offsite.status_code == 201
    first_ticket = first_offsite.json()["ticket"]
    assert first_ticket["id"] == "M-001"
    assert first_ticket["kind"] == "offsite"
    assert first_ticket["source"] == "manual"
    assert first_ticket["url"] == "https://directory.example/vendors/example"
    assert first_ticket["influenced_questions"] == ["q001"]
    assert first_ticket["acceptance"]["type"] == "manual"
    assert all(first_ticket.get(field) for field in ("why", "action", "owner", "effort"))

    second_offsite = client.post(
        f"/api/v1/projects/{project_id}/tickets",
        headers=headers,
        json={
            "url": "https://reviews.example/example",
            "ask_text": "Correct the product description.",
            "influenced_questions": ["q101"],
        },
    )
    assert second_offsite.status_code == 201
    assert second_offsite.json()["ticket"]["id"] == "M-002"
    stored_tickets = json.loads((root / "tasks.json").read_text("utf-8"))
    assert stored_tickets["summary"]["total"] == 3

    sample_text = (
        "# Manual samples\n\n## platform: chatgpt\n\n### q001 · Best Example tools?\n\n"
        "```answer\nExample is listed with a link to https://example.com.\n```\n"
    )
    imported = client.post(
        f"/api/v1/projects/{project_id}/samples/import",
        headers=headers,
        json={"file": "2026-07-31-manual.md", "text": sample_text},
    )
    assert imported.status_code == 200
    assert imported.json()["sample_count"] == 1
    with session_factory() as db:
        import_job = db.query(Job).filter(Job.project_id == project_id, Job.action == "sample-import").one()
        assert import_job.status == "done"
    sample_rows = [json.loads(line) for line in (root / "samples" / "2026-07-31.jsonl").read_text("utf-8").splitlines()]
    assert sample_rows[0]["sample_mode"] == "manual"
    assert sample_rows[0]["terminal"] == "web"
    engine_rows = client.get(f"/api/v1/projects/{project_id}/engines", headers=headers).json()["engines"]
    assert engine_rows[0]["sampling_mode"] == "Manual - Product interface"

    invalid_import = client.post(
        f"/api/v1/projects/{project_id}/samples/import",
        headers=headers,
        json={"file": "../manual.md", "text": sample_text},
    )
    assert invalid_import.status_code == 400
    with session_factory() as db:
        assert db.query(Job).filter(Job.project_id == project_id, Job.action == "sample-import").count() == 1

    assert client.put(
        f"/api/v1/projects/{project_id}/facts",
        headers=headers,
        json={"text": "# Updated facts\n"},
    ).status_code == 200
    assert client.get(f"/api/v1/projects/{project_id}/facts", headers=headers).json()["text"] == "# Updated facts\n"

    factcheck = [{"field": "price", "said": "unknown", "truth": "$10", "state": "被说错"}]
    assert client.put(
        f"/api/v1/projects/{project_id}/factcheck",
        headers=headers,
        json={"items": factcheck},
    ).status_code == 200
    assert client.get(f"/api/v1/projects/{project_id}/factcheck", headers=headers).json() == factcheck

    distribution = client.put(
        f"/api/v1/projects/{project_id}/distribution",
        headers=headers,
        json={"qid": "q001", "channel": "Wikipedia", "on": True},
    )
    assert distribution.status_code == 200
    assert distribution.json()["distribution"]["q001"]["Wikipedia"]

    assets = client.get(f"/api/v1/projects/{project_id}/assets", headers=headers)
    assert assets.status_code == 200
    assert assets.json()[0]["path"] == "outlines/q001.md"
    asset = client.get(
        f"/api/v1/projects/{project_id}/asset",
        headers=headers,
        params={"path": "outlines/q001.md"},
    )
    assert asset.json()["text"] == "# Outline\n"
    assert client.put(
        f"/api/v1/projects/{project_id}/asset",
        headers=headers,
        json={"path": "outlines/q001.md", "text": "# Better outline\n"},
    ).status_code == 200

    workbench = client.get(
        f"/api/v1/projects/{project_id}/workbench?qid=q001",
        headers=headers,
    )
    assert workbench.status_code == 200
    assert workbench.json()["sources"] == [{"kind": "outline", "path": "outlines/q001.md"}]
    precheck = client.post(
        "/api/v1/workspace/precheck",
        headers=headers,
        json={"text": "# Answer\n\n## Details\n\nA concise answer."},
    )
    assert precheck.status_code == 200
    assert "grade" in precheck.json()

    assert client.put(
        f"/api/v1/projects/{project_id}/content",
        headers=headers,
        json={"path": "q001-成稿.md", "text": "<!-- q001 -->\n# Final"},
    ).status_code == 200
    content = client.get(
        f"/api/v1/projects/{project_id}/content",
        headers=headers,
        params={"path": "q001-成稿.md"},
    )
    assert content.json()["text"].endswith("# Final")
    assert client.get(f"/api/v1/projects/{project_id}/expand", headers=headers).json()["terms"]

    files = client.get(f"/api/v1/projects/{project_id}/files", headers=headers).json()
    assert files["reports"] == ["2026-07-31.html"]
    assert files["deliverables"] == ["1-GEO诊断报告.html"]
    assert files["content"] == ["facts.md", "q001-成稿.md"]
    projects = client.get("/api/v1/projects", headers=headers).json()["projects"]
    assert projects[0]["name"] == "Example"
    assert projects[0]["avg_score"] == 72
    assert projects[0]["tasks_total"] == 3
    assert (root / "assets" / "outlines" / "q001.md").read_text("utf-8") == "# Better outline\n"


def test_workspace_is_tenant_isolated_blocks_active_writes_and_traversal(workspace_client):
    client, session_factory, tmp_path = workspace_client
    first_tenant, first_headers = _register(client, "first@example.com", "tenant-a")
    _, second_headers = _register(client, "second@example.com", "tenant-b")
    project_id = _project(session_factory, first_tenant)
    _seed_workspace(tmp_path)

    assert client.get(f"/api/v1/projects/{project_id}/config", headers=second_headers).status_code == 404
    hidden_ticket = client.post(
        f"/api/v1/projects/{project_id}/tickets",
        headers=second_headers,
        json={"url": "https://outside.example/page", "ask_text": "Update it", "influenced_questions": ["q001"]},
    )
    assert hidden_ticket.status_code == 404
    hidden_import = client.post(
        f"/api/v1/projects/{project_id}/samples/import",
        headers=second_headers,
        json={"file": "2026-07-31-manual.md", "text": "sample"},
    )
    assert hidden_import.status_code == 404
    with session_factory() as db:
        db.add(Job(project_id=project_id, action="audit", status="running"))
        db.commit()
    blocked = client.put(
        f"/api/v1/projects/{project_id}/facts",
        headers=first_headers,
        json={"text": "blocked"},
    )
    assert blocked.status_code == 409
    blocked_ticket = client.post(
        f"/api/v1/projects/{project_id}/tickets",
        headers=first_headers,
        json={"url": "https://outside.example/page", "ask_text": "Update it", "influenced_questions": ["q001"]},
    )
    assert blocked_ticket.status_code == 409
    blocked_status = client.patch(
        f"/api/v1/projects/{project_id}/tickets/T-001",
        headers=first_headers,
        json={"status": "doing"},
    )
    assert blocked_status.status_code == 409
    blocked_import = client.post(
        f"/api/v1/projects/{project_id}/samples/import",
        headers=first_headers,
        json={"file": "2026-07-31-manual.md", "text": "sample"},
    )
    assert blocked_import.status_code == 409

    with session_factory() as db:
        db.query(Job).filter(Job.project_id == project_id).update({"status": "done"})
        db.commit()
    traversal = client.get(
        f"/api/v1/projects/{project_id}/asset",
        headers=first_headers,
        params={"path": "../geo.json"},
    )
    assert traversal.status_code == 400
    invalid_question = client.get(
        f"/api/v1/projects/{project_id}/workbench",
        headers=first_headers,
        params={"qid": "../../geo"},
    )
    assert invalid_question.status_code == 400


def test_manual_offsite_ticket_survives_engine_plan_rebuild(workspace_client):
    client, session_factory, tmp_path = workspace_client
    tenant_id, headers = _register(client, "owner@example.com", "tenant-a")
    project_id = _project(session_factory, tenant_id)
    root = _seed_workspace(tmp_path)

    created = client.post(
        f"/api/v1/projects/{project_id}/tickets",
        headers=headers,
        json={
            "url": "https://directory.example/example",
            "ask_text": "Add the official brand definition and source link.",
            "influenced_questions": ["q001"],
        },
    )
    assert created.status_code == 201

    with with_tenant_context("tenant-a", "example-com"):
        import tasks as engine_tasks

        with workspace.preserve_manual_tickets("example-com"):
            engine_tasks.build("example-com")
            engine_tasks.set_status("example-com", "M-001", "doing", "Outreach started")

    data = json.loads((root / "tasks.json").read_text("utf-8"))
    manual = [ticket for ticket in data["tasks"] if ticket.get("kind") == "offsite"]
    assert len(manual) == 1
    assert manual[0]["id"] == "M-001"
    assert manual[0]["ask_text"] == "Add the official brand definition and source link."
    assert manual[0]["status"] == "doing"
    assert manual[0]["evidence"][-1]["note"] == "Outreach started"
    assert data["summary"]["total"] == len(data["tasks"])
