import json
import sys
import types
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.adapters import engine as engine_adapter
from api.adapters import measurement, workspace
from api.adapters.engine import with_tenant_context
from api.adapters.exceptions import GeoEngineError
from api.adapters.workspace import resilient_crawl_evidence
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
        "questions": [{"id": "q001", "group": "recommendation", "market": "both", "text": "Is Example recommended?"}],
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
    (root / "evidence" / "html").mkdir(parents=True)
    (root / "evidence" / "site.json").write_text(
        json.dumps({"root": "https://example.com", "pages_ok": 1}), "utf-8",
    )
    return root


def test_manual_sample_import_normalizes_after_releasing_project_lock(tmp_path, monkeypatch):
    project = tmp_path / "example"
    sample_path = project / "samples" / "2026-08-14-manual.md"
    sample_path.parent.mkdir(parents=True)
    sample_path.write_text("# Manual samples\n", "utf-8")
    calls = []

    @contextmanager
    def fake_project_lock(project_slug):
        calls.append(("lock-enter", project_slug))
        try:
            yield
        finally:
            calls.append(("lock-exit", project_slug))

    def fake_sample_import(project_slug, filename):
        calls.append(("sample-import", project_slug, filename))
        return {"sample_count": 1}

    sample_module = types.SimpleNamespace(
        PROVIDERS={"chatgpt": {}},
        MANUAL_ONLY={},
        sample_import=fake_sample_import,
    )
    monkeypatch.setitem(sys.modules, "sample", sample_module)
    monkeypatch.setattr(workspace.geolib, "project_dir", lambda slug: project)
    monkeypatch.setattr(workspace.geolib, "load_config", lambda slug: {
        "questions": [{"id": "q001", "text": "What is Example?"}],
    })
    monkeypatch.setattr(workspace.geolib, "project_lock", fake_project_lock)
    monkeypatch.setattr(measurement, "record_sampling", lambda slug, **kwargs: calls.append(("record", slug)))
    monkeypatch.setattr(workspace.global_scope, "normalize_project", lambda slug: calls.append(("normalize", slug)))

    result = workspace.import_sample_sheet(
        "example",
        "2026-08-14-manual.md",
        "## platform: chatgpt\n\n### q001 · What is Example?\n\n```answer\nExample is visible.\n```\n",
    )

    assert result == {"sample_count": 1}


def test_product_surface_import_writes_sheet_and_labels_manual(tmp_path, monkeypatch):
    project = tmp_path / "example"
    (project / "samples").mkdir(parents=True)
    captured = {}

    @contextmanager
    def fake_project_lock(project_slug):
        yield

    def fake_sample_import(project_slug, filename):
        captured["filename"] = filename
        captured["text"] = Path(filename).read_text("utf-8")
        return {"sample_count": 1, "date": "2026-08-18"}

    sample_module = types.SimpleNamespace(
        PROVIDERS={},
        MANUAL_ONLY={"chatgpt": ("ChatGPT Search", "global")},
        sample_import=fake_sample_import,
    )
    monkeypatch.setitem(sys.modules, "sample", sample_module)
    monkeypatch.setattr(workspace.geolib, "project_dir", lambda slug: project)
    monkeypatch.setattr(workspace.geolib, "today", lambda: "2026-08-18")
    monkeypatch.setattr(workspace.geolib, "load_config", lambda slug: {
        "questions": [{"id": "q001", "text": "Does ChatGPT mention Example?"}],
    })
    monkeypatch.setattr(workspace.geolib, "project_lock", fake_project_lock)
    monkeypatch.setattr(measurement, "record_sampling", lambda slug, **kwargs: None)
    monkeypatch.setattr(workspace.global_scope, "normalize_project", lambda slug: None)

    result = workspace.import_product_surface(
        "example",
        "chatgpt",
        [{"question_id": "q001", "answer": "I do not see Example in this answer."}],
    )
    assert result["sample_count"] == 1
    assert captured["filename"].endswith("2026-08-18-manual.md")
    assert "## platform: chatgpt" in captured["text"]
    assert "I do not see Example in this answer." in captured["text"]


def test_workspace_read_write_flow_and_project_summary(workspace_client, monkeypatch):
    client, session_factory, tmp_path = workspace_client
    monkeypatch.setattr(workspace.geolib, "today", lambda: "2026-07-31")
    tenant_id, headers = _register(client, "owner@example.com", "tenant-a")
    project_id = _project(session_factory, tenant_id)
    root = _seed_workspace(tmp_path)

    read_paths = [root / "geo.json", root / "content" / "facts.md", root / "assets" / "outlines" / "q001.md"]
    before_reads = {path: path.stat().st_mtime_ns for path in read_paths}
    assert client.get(f"/api/v1/projects/{project_id}/config", headers=headers).status_code == 200
    assert client.get(f"/api/v1/projects/{project_id}/facts", headers=headers).status_code == 200
    assert client.get(f"/api/v1/projects/{project_id}/assets", headers=headers).status_code == 200
    assert client.get(
        f"/api/v1/projects/{project_id}/asset",
        headers=headers,
        params={"path": "outlines/q001.md"},
    ).status_code == 200
    assert {path: path.stat().st_mtime_ns for path in read_paths} == before_reads

    config = client.get(f"/api/v1/projects/{project_id}/config", headers=headers)
    assert config.status_code == 200
    assert config.json()["market"] == "global"
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
    assert updated.json()["config"]["market"] == "global"

    changed_url = client.patch(
        f"/api/v1/projects/{project_id}/config",
        headers=headers,
        json={"url": "https://new.example.com/"},
    )
    assert changed_url.status_code == 200
    with session_factory() as db:
        assert db.get(Project, project_id).url == "https://new.example.com"
    assert changed_url.json()["config"]["brand"]["site"] == "https://new.example.com"
    assert not (root / "evidence").exists()
    assert (root / "content" / "facts.md").is_file()
    assert (root / "delivery" / "2026-07-31").is_dir()
    with session_factory() as db:
        assert db.get(Project, project_id).market == "global"
    assert json.loads((root / "geo.json").read_text("utf-8"))["market"] == "global"
    forbidden = client.patch(
        f"/api/v1/projects/{project_id}/config",
        headers=headers,
        json={"publishing": {"webhook": {"url": "https://127.0.0.1"}}},
    )
    assert forbidden.status_code == 422

    added = client.post(
        f"/api/v1/projects/{project_id}/questions",
        headers=headers,
        json={"items": [{"text": "Example pricing?", "market": "global", "group": "价格"}]},
    )
    assert added.status_code == 200
    assert added.json()["ids"] == ["q101"]

    chinese_question = client.post(
        f"/api/v1/projects/{project_id}/questions",
        headers=headers,
        json={"items": [{"text": "Example 的价格是多少？", "market": "global"}]},
    )
    assert chinese_question.status_code == 400
    assert chinese_question.json()["error"] == "workspace_operation_failed"
    assert "must not contain Chinese characters" in chinese_question.json()["detail"]

    invalid_global_update = client.patch(
        f"/api/v1/projects/{project_id}/questions/q101",
        headers=headers,
        json={"text": "Example 的价格是多少？", "market": "global"},
    )
    assert invalid_global_update.status_code == 400
    assert invalid_global_update.json()["error"] == "workspace_operation_failed"
    assert "must not contain Chinese characters" in invalid_global_update.json()["detail"]

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
    assert stored_tickets["summary"]["total"] == len(stored_tickets["tasks"])
    assert {"T-001", "M-001", "M-002"} <= {item["id"] for item in stored_tickets["tasks"]}

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
    sample_artifact = sorted((root / "samples").glob("sample-*.jsonl"))[-1]
    sample_rows = [json.loads(line) for line in sample_artifact.read_text("utf-8").splitlines()]
    assert sample_rows[0]["sample_mode"] == "manual"
    assert sample_rows[0]["terminal"] == "manual"
    engine_rows = client.get(f"/api/v1/projects/{project_id}/engines", headers=headers).json()["engines"]
    assert engine_rows[0]["sampling_mode"] == "人工·产品端"

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
    facts_response = client.get(f"/api/v1/projects/{project_id}/facts", headers=headers).json()
    assert facts_response["text"] == "# Updated facts\n"
    assert facts_response["reviewed"] is False
    assert facts_response["review_status"] == "review_required"
    approved = client.put(
        f"/api/v1/projects/{project_id}/facts",
        headers=headers,
        json={"text": "# Updated facts\n", "approve": True},
    )
    assert approved.status_code == 200
    facts_response = client.get(f"/api/v1/projects/{project_id}/facts", headers=headers).json()
    assert facts_response["reviewed"] is True
    assert facts_response["review_status"] == "approved"
    non_english = client.put(
        f"/api/v1/projects/{project_id}/facts",
        headers=headers,
        json={"text": "# \u54c1\u724c\u4e8b\u5b9e\n"},
    )
    assert non_english.status_code == 400
    assert "must be written in English" in non_english.json()["detail"]
    assert client.get(f"/api/v1/projects/{project_id}/facts", headers=headers).json()["text"] == "# Updated facts\n"

    external = client.post(
        f"/api/v1/projects/{project_id}/evidence/external",
        headers=headers,
        json={
            "url": "https://directory.example/vendors/example",
            "source_type": "directory",
            "fact_supported": "Example is the official product name.",
            "question_ids": ["q001"],
            "reviewer": "owner@example.com",
        },
    )
    assert external.status_code == 201
    assert external.json()["record"]["status"] == "manual_confirmation_required"
    evidence = client.get(f"/api/v1/projects/{project_id}/evidence/external", headers=headers)
    assert evidence.status_code == 200
    assert evidence.json()["records"][0]["question_ids"] == ["q001"]
    invalid_external = client.post(
        f"/api/v1/projects/{project_id}/evidence/external",
        headers=headers,
        json={"url": "file:///tmp/evidence", "source_type": "directory", "fact_supported": "Invalid."},
    )
    assert invalid_external.status_code == 400

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
    non_english_asset = client.put(
        f"/api/v1/projects/{project_id}/asset",
        headers=headers,
        json={"path": "outlines/q001.md", "text": r"# \u4e2d\u6587 outline"},
    )
    assert non_english_asset.status_code == 400
    assert "must be written in English" in non_english_asset.json()["detail"]
    assert (root / "assets" / "outlines" / "q001.md").read_text("utf-8") == "# Better outline\n"

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
    assert projects[0]["tasks_total"] == stored_tickets["summary"]["total"]
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


def test_resilient_crawl_evidence_recovers_visible_snapshot_text(tmp_path, monkeypatch):
    import crawl

    monkeypatch.setattr(workspace.geolib, "WORK", tmp_path)
    root = tmp_path / "example"
    evidence = root / "evidence"
    snapshot = evidence / "html" / "001.html"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text(
        "<html><head><script>ignored()</script></head><body><main>Visible brand evidence</main></body></html>",
        "utf-8",
    )
    rows = [{
        "url": "https://example.com",
        "status": 200,
        "text": "",
        "snapshot": "evidence/html/001.html",
    }]
    workspace.geolib.write_jsonl(evidence / "pages.jsonl", rows)
    monkeypatch.setattr(crawl, "run", lambda slug: {"pages_ok": 1, "pages_crawled": 1})

    with resilient_crawl_evidence("example"):
        result = crawl.run("example")

    pages = workspace.geolib.read_jsonl(evidence / "pages.jsonl")
    assert result == {"pages_ok": 1, "pages_crawled": 1}
    assert pages[0]["text"] == "Visible brand evidence"
    assert pages[0]["word_count"] == 3


def test_resilient_crawl_evidence_recovers_page_metadata(tmp_path, monkeypatch):
    import crawl

    monkeypatch.setattr(workspace.geolib, "WORK", tmp_path)
    evidence = tmp_path / "example" / "evidence"
    rows = [{
        "url": "https://example.com",
        "status": 200,
        "text": "",
        "title": "Example Analytics",
        "meta_description": "Official analytics platform for product teams.",
        "h1": [],
        "h2": [],
        "snapshot": "evidence/html/001.html",
    }]
    workspace.geolib.write_jsonl(evidence / "pages.jsonl", rows)
    monkeypatch.setattr(crawl, "run", lambda slug: {"pages_ok": 1, "pages_crawled": 1})

    with resilient_crawl_evidence("example"):
        crawl.run("example")

    page = workspace.geolib.read_jsonl(evidence / "pages.jsonl")[0]
    assert page["text"] == "Example Analytics\nOfficial analytics platform for product teams."
    assert page["word_count"] == 8


def test_resilient_crawl_evidence_retains_previous_usable_pages(tmp_path, monkeypatch):
    import crawl

    monkeypatch.setattr(workspace.geolib, "WORK", tmp_path)
    root = tmp_path / "example"
    evidence = root / "evidence"
    evidence.mkdir(parents=True)
    previous_pages = [{
        "url": "https://example.com",
        "status": 200,
        "text": "Previous verified brand evidence",
        "snapshot": "evidence/html/001.html",
    }]
    previous_site = {"pages_ok": 1, "pages_crawled": 1, "crawled_at": "previous"}
    workspace.geolib.write_jsonl(evidence / "pages.jsonl", previous_pages)
    workspace.geolib.write_json(evidence / "site.json", previous_site)

    def empty_run(slug):
        workspace.geolib.write_jsonl(evidence / "pages.jsonl", [{
            "url": "https://example.com",
            "status": 200,
            "text": "",
            "snapshot": "evidence/html/002.html",
        }])
        workspace.geolib.write_json(evidence / "site.json", {"pages_ok": 1, "pages_crawled": 1, "crawled_at": "current"})
        return {"pages_ok": 1, "pages_crawled": 1, "crawled_at": "current"}

    monkeypatch.setattr(crawl, "run", empty_run)

    with resilient_crawl_evidence("example"):
        result = crawl.run("example")

    assert result == previous_site
    assert workspace.geolib.read_jsonl(evidence / "pages.jsonl") == previous_pages
    assert workspace.geolib.read_json(evidence / "site.json") == previous_site


def test_resilient_crawl_evidence_uses_project_identity_for_client_only_site(tmp_path, monkeypatch):
    import crawl

    monkeypatch.setattr(workspace.geolib, "WORK", tmp_path)
    project = tmp_path / "example"
    evidence = project / "evidence"
    workspace.geolib.write_json(project / "geo.json", {
        "slug": "example",
        "brand": {"name": "Example", "site": "https://example.com"},
    })

    def empty_run(slug):
        workspace.geolib.write_jsonl(evidence / "pages.jsonl", [{
            "url": "https://example.com",
            "status": 200,
            "text": "",
            "snapshot": "evidence/html/001.html",
        }])
        return {"pages_ok": 1, "pages_crawled": 1}

    monkeypatch.setattr(crawl, "run", empty_run)

    with resilient_crawl_evidence("example"):
        result = crawl.run("example")

    page = workspace.geolib.read_jsonl(evidence / "pages.jsonl")[0]
    assert result == {"pages_ok": 1, "pages_crawled": 1}
    assert "Brand: Example" in page["text"]
    assert "no server-rendered page text" in page["text"]


def test_resilient_crawl_does_not_restore_evidence_from_previous_domain(tmp_path, monkeypatch):
    import crawl

    monkeypatch.setattr(workspace.geolib, "WORK", tmp_path)
    project = tmp_path / "example"
    evidence = project / "evidence"
    workspace.geolib.write_json(project / "geo.json", {
        "slug": "example",
        "brand": {"name": "New Brand", "site": "https://new.example"},
    })
    workspace.geolib.write_json(evidence / "site.json", {
        "root": "https://old.example", "pages_ok": 1, "pages_crawled": 1,
    })
    workspace.geolib.write_jsonl(evidence / "pages.jsonl", [{
        "url": "https://old.example", "status": 200, "text": "Old website content",
    }])

    def failed_new_crawl(slug):
        workspace.geolib.write_json(evidence / "site.json", {
            "root": "https://new.example", "pages_ok": 0, "pages_crawled": 1,
        })
        workspace.geolib.write_jsonl(evidence / "pages.jsonl", [{
            "url": "https://new.example", "status": 403, "text": "",
        }])
        raise GeoEngineError("new website denied crawl")

    monkeypatch.setattr(crawl, "run", failed_new_crawl)

    with pytest.raises(GeoEngineError, match="new website denied crawl"):
        with resilient_crawl_evidence("example"):
            crawl.run("example")

    assert workspace.geolib.read_json(evidence / "site.json")["root"] == "https://new.example"
    assert workspace.geolib.read_jsonl(evidence / "pages.jsonl")[0]["url"] == "https://new.example"


def test_resilient_crawl_evidence_reports_unextractable_without_project_identity(tmp_path, monkeypatch):
    import crawl

    monkeypatch.setattr(workspace.geolib, "WORK", tmp_path)
    evidence = tmp_path / "example" / "evidence"

    def empty_run(slug):
        workspace.geolib.write_jsonl(evidence / "pages.jsonl", [{
            "url": "https://example.com",
            "status": 200,
            "text": "",
            "snapshot": "evidence/html/001.html",
        }])
        return {"pages_ok": 1, "pages_crawled": 1}

    monkeypatch.setattr(crawl, "run", empty_run)

    with resilient_crawl_evidence("example"):
        with pytest.raises(GeoEngineError, match="JavaScript rendering or block automated crawlers"):
            crawl.run("example")


def test_resilient_crawl_evidence_restores_previous_snapshot_after_crawl_failure(tmp_path, monkeypatch):
    import crawl

    monkeypatch.setattr(workspace.geolib, "WORK", tmp_path)
    evidence = tmp_path / "example" / "evidence"
    snapshot = evidence / "html" / "001.html"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text("<main>Previous snapshot</main>", "utf-8")
    previous_pages = [{
        "url": "https://example.com",
        "status": 200,
        "text": "Previous verified brand evidence",
        "snapshot": "evidence/html/001.html",
    }]
    workspace.geolib.write_jsonl(evidence / "pages.jsonl", previous_pages)

    def failed_run(slug):
        snapshot.write_text("<main>Incomplete new snapshot</main>", "utf-8")
        workspace.geolib.write_jsonl(evidence / "pages.jsonl", [])
        raise GeoEngineError("Crawl failed: WAF")

    monkeypatch.setattr(crawl, "run", failed_run)

    with resilient_crawl_evidence("example"):
        with pytest.raises(GeoEngineError, match="Crawl failed: WAF"):
            crawl.run("example")

    assert workspace.geolib.read_jsonl(evidence / "pages.jsonl") == previous_pages
    assert snapshot.read_text("utf-8") == "<main>Previous snapshot</main>"
