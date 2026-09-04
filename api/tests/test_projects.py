import base64
import io
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
from api.models import CustomProvider, Job, Project, Tenant
from api.projects import router as project_router
from api.adapters import engine as engine_adapter, sampling_control
from api.adapters.network import validate_outbound_url as real_validate_outbound_url
from api.settings.crypto import encrypt_key


@pytest.fixture()
def project_client(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-that-is-long-enough-32")
    monkeypatch.setattr(engine_adapter, "WORK_ROOT", tmp_path / "work")
    monkeypatch.setattr(project_router, "validate_outbound_url", lambda value, **kwargs: value)
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
                "questions": [{"id": "q001", "text": "Which AI visibility platform is reliable?", "market": "global"}],
                "competitors": [
                    {
                        "name": "Confirmed Rival", "aliases": ["CR"], "market": "global", "confirmed": True,
                        "domain": "https://confirmed.example", "relationship": "direct_competitor",
                        "relationship_source": "ai_site_profile", "relationship_confidence": "high",
                        "category_overlap": "Same category", "buyer_overlap": "Same buyer", "job_overlap": "Same job",
                    },
                    {
                        "name": "Candidate Rival", "aliases": [], "market": "global", "confirmed": False,
                        "domain": "https://candidate.example", "relationship": "direct_competitor",
                        "relationship_source": "ai_site_profile", "relationship_confidence": "high",
                        "category_overlap": "Same category", "buyer_overlap": "Same buyer", "job_overlap": "Same job",
                    },
                    {
                        "name": "Configured Rival", "aliases": [], "market": "both",
                        "domain": "https://configured.example", "relationship": "direct_competitor",
                        "relationship_source": "ai_site_profile", "relationship_confidence": "high",
                        "category_overlap": "Same category", "buyer_overlap": "Same buyer", "job_overlap": "Same job",
                    },
                ],
            }),
            "utf-8",
        )
        return {"slug": args.slug}

    fake_geo = types.SimpleNamespace(cmd_init=fake_init)
    monkeypatch.setitem(sys.modules, "geo", fake_geo)
    monkeypatch.setattr(project_router.task_bootstrap, "delay", lambda *a, **kw: types.SimpleNamespace(id="celery-1"))

    create_schema = client.app.openapi()["components"]["schemas"]["ProjectCreate"]
    assert create_schema["properties"]["market"]["default"] == "both"

    created = client.post(
        "/api/v1/projects",
        headers=headers,
        json={"url": "example.com", "name": "Example Brand", "market": "global"},
    )
    assert created.status_code == 202
    body = created.json()
    assert body["project_id"] == 1
    assert body["job_id"] == 1
    assert body["action"] == "bootstrap"
    assert calls[0].url == "https://example.com"
    assert calls[0].name == "Example Brand"
    assert calls[0].market == "global"

    config_path = next((tmp_path / "work").glob("*/example-com/geo.json"))
    legacy_config = json.loads(config_path.read_text("utf-8"))
    legacy_config["market"] = "global"
    config_path.write_text(json.dumps(legacy_config), "utf-8")

    listed = client.get("/api/v1/projects", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["projects"][0]["slug"] == "example-com"
    assert listed.json()["projects"][0]["market"] == "global"
    assert json.loads(config_path.read_text("utf-8"))["market"] == "global"
    detail = client.get(f"/api/v1/projects/{body['project_id']}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["brand"]["name"] == "Example"
    assert detail.json()["questions"][0]["id"] == "q001"
    assert set(detail.json()["insights"]) == {
        "prompt_explorer", "competitor_heatmap", "takeover_alerts", "sentiment", "campaign_proposals",
    }
    assert detail.json()["insights"]["prompt_explorer"]["total_count"] == 1
    campaigns = detail.json()["insights"]["campaign_proposals"]
    assert campaigns["counts"]["blocked"] == 1
    assert campaigns["policy"]["automatic_publication"] is False
    discovery = detail.json()["competitor_discovery"]
    assert discovery["summary"] == {"total": 3, "sample_confirmed": 1, "candidate": 1, "configured": 1}
    assert [item["discovery_status"] for item in discovery["items"]] == [
        "sample_confirmed", "candidate", "configured",
    ]
    assert discovery["items"][0]["aliases"] == []
    assert discovery["items"][0]["alias_review"] == [{
        "value": "CR", "status": "pending", "reason": "identity_evidence_required",
    }]
    current_status = client.get(f"/api/v1/projects/{body['project_id']}/status", headers=headers)
    assert current_status.status_code == 200
    assert current_status.json()["status"] == "bootstrapping"
    assert current_status.json()["summary"]["name"] == "Example"
    assert current_status.json()["latest_job"]["id"] == body["job_id"]
    assert current_status.json()["latest_job"]["log"] == ""

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
                    "openai": {
                    "market": "global",
                    "mention_rate": 0.5,
                    "top3_rate": 0.5,
                    "avg_rank": 1,
                    "own_domain_cite_rate": 0,
                },
                "chatgpt": {
                    "market": "global",
                    "label": "ChatGPT 网页版",
                    "mention_rate": 0,
                    "top3_rate": 0,
                    "avg_rank": None,
                    "own_domain_cite_rate": 0,
                },
            },
        },
    )
    contact_url = "https://example.com/en/contact"
    geolib.write_json(project_dir / "audit.json", {
        "slug": "example-com",
        "market": "global",
        "page_count": 1,
        "avg_score": 12,
        "grade_distribution": {"A": 0, "B": 0, "C": 0, "D": 1},
        "site": {
            "root": "https://example.com", "pages_crawled": 1, "pages_ok": 1,
            "has_sitemap": True, "has_llms_txt": True, "ai_bots_blocked": [],
        },
        "language_coverage": {"distribution": {"en": 1}, "en_pages": 1},
        "site_issues": ["\u4e0d\u5e94\u8fdb\u5165\u4ea7\u54c1\u5c55\u793a\u7684\u5f15\u64ce\u6587\u6848"],
        "pages": [{
            "url": contact_url, "title": "Contact", "word_count": 44,
            "score": 12, "grade": "D", "jsonld_types": [],
            "blocks": {
                "\u5b9a\u4e49": False, "\u6570\u5b57\u4e8b\u5b9e": False, "\u5bf9\u6bd4": False,
                "\u64cd\u4f5c\u6b65\u9aa4": False, "FAQ": False,
            },
            "issues": ["\u6240\u6709\u9875\u9762\u5171\u7528\u7684\u4e2d\u6587\u7ed3\u8bba"],
            "issue_codes": [
                "SHORT_CONTENT", "FEW_H2", "NO_DEFINITION", "NO_NUMBERS",
                "NO_COMPARISON", "NO_HOWTO", "NO_FAQ", "NO_DATE",
                "FEW_EXTERNAL_LINKS", "NO_JSONLD", "LOW_RELEVANCE",
            ],
        }],
    })
    geolib.write_jsonl(project_dir / "evidence" / "pages.jsonl", [{
        "url": contact_url, "final_url": contact_url, "status": 200,
        "title": "Contact", "meta_robots": "", "canonical": contact_url,
        "h1": ["Contact"], "h2": [], "para_count": 3, "word_count": 44,
        "external_links": 0, "jsonld_types": [], "text": "Contact our sales and support teams.",
    }])
    geolib.write_json(project_dir / "evidence" / "site.json", {
        "root": "https://example.com", "pages_crawled": 1, "pages_ok": 1,
        "has_sitemap": True, "has_llms_txt": True, "ai_bots_blocked": [],
    })
    geolib.write_jsonl(
        project_dir / "samples" / "2026-07-31.jsonl",
        [
            {
                "platform": "openai",
                "platform_name": "OpenAI",
                "market": "global",
                    "sample_mode": "api",
                    "search_enabled": True,
                    "question_id": "q001",
                    "question": "Which AI visibility platform is reliable?",
                    "ok": True,
                "answer": "Example is a reliable AI visibility platform.",
                "citations": [{"url": "https://g2.com/categories/geo", "title": "G2"}],
                "elapsed_ms": 12,
                "analysis": {
                    "brand_mentioned": True,
                    "brand_rank": 1,
                    "own_domain_cited": False,
                    "cited_domains": ["g2.com"],
                    "competitors_mentioned": [],
                    "candidates": ["Example"],
                    "negative_cues": [],
                },
            },
            {
                "platform": "chatgpt",
                "platform_name": "ChatGPT 网页版",
                "market": "global",
                "terminal": "web",
                    "sample_mode": "manual",
                    "search_enabled": True,
                    "question_id": "q001",
                    "question": "Which AI visibility platform is reliable?",
                    "ok": True,
                "answer": "No result.",
                "analysis": {
                    "brand_mentioned": False,
                    "brand_rank": 0,
                    "own_domain_cited": False,
                    "cited_domains": [],
                    "competitors_mentioned": [],
                    "candidates": [],
                    "negative_cues": [],
                },
            },
        ],
    )
    report = client.get(f"/api/v1/projects/{body['project_id']}/report", headers=headers)
    assert report.status_code == 200
    assert report.json()["report"]["platforms"]["openai"]["mention_rate"] == 1.0
    assert report.json()["report"]["channels"] == [{
        "domain": "g2.com",
        "count": 1,
        "engines": ["OpenAI"],
        "question_count": 1,
        "sample_questions": ["Which AI visibility platform is reliable?"],
    }]
    audit = report.json()["report"]["audit"]
    assert audit["presentation_version"] == 1
    assert audit["applicable_avg_score"] is None
    assert audit["pages"][0]["evaluation_status"] == "excluded"
    assert "Contact pages are excluded" in audit["pages"][0]["evaluation_note"]
    assert audit["pages"][0]["role"]["id"] == "contact"
    assert audit["pages"][0]["issues"] == []
    engines = client.get(f"/api/v1/projects/{body['project_id']}/engines", headers=headers)
    assert engines.status_code == 200
    assert engines.json()["project_id"] == body["project_id"]
    assert engines.json()["project_slug"] == "example-com"
    modes = {item["platform"]: item["sampling_mode"] for item in engines.json()["engines"]}
    assert modes["openai"] == "API·联网检索"
    assert modes["chatgpt"] == "人工·产品端"
    assert modes["perplexity"] == "API·联网检索"
    assert all("market" not in item for item in engines.json()["engines"])
    samples = client.get(f"/api/v1/projects/{body['project_id']}/samples/2026-07-31", headers=headers)
    assert samples.status_code == 200
    assert samples.json()["project_id"] == body["project_id"]
    assert samples.json()["project_slug"] == "example-com"
    assert samples.json()["samples"][0]["answer"] == "Example is a reliable AI visibility platform."
    framing = client.get(f"/api/v1/projects/{body['project_id']}/framing", headers=headers)
    assert framing.status_code == 200
    assert framing.json()["framing"]["terms"][0]["term"] == "reliable AI visibility platform"
    assert framing.json()["framing"]["terms"][0]["evidence"][0]["sampling_mode"] == "API·联网检索"

    monkeypatch.setattr(project_router.task_sample, "delay", lambda *a, **kw: types.SimpleNamespace(id="celery-2"))
    sampled = client.post(
        f"/api/v1/projects/{body['project_id']}/sample",
        headers=headers,
        json={"limit": 2, "platforms": ["openai"]},
    )
    assert sampled.status_code == 202
    assert sampled.json()["job_id"] == 2
    with session_factory() as db:
        db.get(Job, sampled.json()["job_id"]).status = "done"
        db.commit()

    geolib.write_json(
        project_dir / "tasks.json",
        {
            "generated_at": "2026-07-31T12:00:00+08:00",
            "summary": {"total": 3, "by_status": {"todo": 3}},
            "tasks": [
                {
                    "id": "T-003", "title": "Later", "priority": "P1", "effort": "S",
                    "package": "内容矩阵", "market": "both", "status": "todo", "evidence": [],
                    "acceptance": {"type": "manual", "desc": "done"},
                },
                {
                    "id": "T-002", "title": "First tie", "priority": "P0", "effort": "M",
                    "package": "页面技术", "market": "both", "status": "todo", "evidence": [],
                    "acceptance": {"type": "manual", "desc": "done"},
                },
                {
                    "id": "T-001", "title": "Second tie", "priority": "P0", "effort": "M",
                    "package": "页面技术", "market": "both", "status": "todo", "evidence": [],
                    "acceptance": {"type": "manual", "desc": "done"},
                },
            ],
        },
    )
    tickets = client.get(f"/api/v1/projects/{body['project_id']}/tickets", headers=headers)
    assert tickets.status_code == 200
    assert tickets.json()["tickets"][0]["id"] == "T-003"
    playbook = client.get(f"/api/v1/projects/{body['project_id']}/playbook", headers=headers)
    assert any(item["package_en"] == "Content matrix" for item in playbook.json()["playbook"])
    assert playbook.status_code == 200
    assert [item["id"] for item in playbook.json()["playbook"]] == [
        "T-002", "T-001", "T-003", "T-MEASUREMENT-BASELINE",
    ]
    assert playbook.json()["generated_at"] == "2026-07-31T12:00:00+08:00"
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
    assert deliveries.json()["packages"] == [{
        "date": "2026-07-31",
        "readiness": "unknown",
        "pack_kind": "unknown",
        "diagnostic_ready": False,
        "visibility_ready": False,
        "implementation_ready": False,
        "implementation_backlog": [],
        "asset_summary": {"ready": 0, "needs_review": 0, "template": 0},
        "can_send": False,
    }]
    assert deliveries.json()["can_send"] is False
    monkeypatch.setattr(project_router.task_deliver, "delay", lambda *a, **kw: types.SimpleNamespace(id="celery-4"))
    delivered = client.post(f"/api/v1/projects/{body['project_id']}/deliver", headers=headers)
    assert delivered.status_code == 202
    assert delivered.json()["job_id"] == 4
    monkeypatch.setattr(project_router.delivery, "ensure_delivery_contract", lambda slug, directory: directory)
    archive = client.get(f"/api/v1/projects/{body['project_id']}/deliveries/2026-07-31", headers=headers)
    assert archive.status_code == 200
    assert archive.headers["content-type"] == "application/zip"
    assert archive.headers["x-citeaura-delivery-readiness"] == "unknown"
    assert archive.headers["content-disposition"] == 'attachment; filename="delivery-review-2026-07-31.zip"'
    import io
    with zipfile.ZipFile(io.BytesIO(archive.content)) as bundle:
        assert bundle.namelist() == ["index.html"]

    jobs = client.get(f"/api/v1/projects/{body['project_id']}/jobs", headers=headers)
    assert jobs.status_code == 200
    assert jobs.json()["jobs"][0]["status"] == "queued"

    job = client.get(f"/api/v1/projects/{body['project_id']}/jobs/{body['job_id']}", headers=headers)
    assert job.status_code == 200
    assert "log_path" not in job.json()["job"]

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


def test_project_create_rejects_private_target_before_persisting(project_client, monkeypatch):
    client, session_factory = project_client
    headers = _register(client, "private-target@example.com")
    monkeypatch.setattr(project_router, "validate_outbound_url", real_validate_outbound_url)
    response = client.post(
        "/api/v1/projects",
        headers=headers,
        json={"url": "http://127.0.0.1/internal"},
    )

    assert response.status_code == 422
    assert response.json() == {"error": "network_private_address_blocked"}
    with session_factory() as db:
        assert db.query(project_router.Project).count() == 0
        assert db.query(Job).count() == 0


def test_custom_llm_alone_unlocks_sampling_and_brand_creation(project_client, monkeypatch):
    client, session_factory = project_client
    monkeypatch.setenv("AES_KEY", base64.urlsafe_b64encode(b"0" * 32).decode())
    headers = _register(client, "custom-only@example.com")
    with session_factory() as db:
        tenant = db.query(Tenant).one()
        db.add(CustomProvider(
            tenant_id=tenant.id,
            code="custom_budget",
            name="Budget Gateway",
            base_url="https://gateway.example.com/v1",
            model_id="vendor/budget-model",
            market="global",
            encrypted_api_key=encrypt_key("sk-custom"),
        ))
        db.commit()

    monkeypatch.setattr(
        project_router.preflight,
        "run",
        lambda url: {"ready": True, "checks": [{"name": "https", "ok": True}]},
    )
    preflight = client.post(
        "/api/v1/projects/preflight",
        headers=headers,
        json={"url": "https://custom-only.example"},
    )
    assert preflight.status_code == 200
    body = preflight.json()
    assert body["can_sample"] is True
    assert "custom_budget" in body["effective_platforms"]
    assert "custom_budget" in body["byok_engines"]

    monkeypatch.setitem(sys.modules, "geo", types.SimpleNamespace(cmd_init=lambda args: None))
    monkeypatch.setattr(
        project_router.task_bootstrap,
        "delay",
        lambda *args, **kwargs: types.SimpleNamespace(id="celery-custom"),
    )
    created = client.post(
        "/api/v1/projects",
        headers=headers,
        json={"url": "https://custom-only.example"},
    )
    assert created.status_code == 202
    assert created.json()["action"] == "autopilot"


def test_delivery_download_rejects_noncompliant_legacy_package(project_client, monkeypatch, tmp_path):
    client, _ = project_client
    headers = _register(client, "owner@example.com")
    monkeypatch.setitem(sys.modules, "geo", types.SimpleNamespace(cmd_init=lambda args: None))
    monkeypatch.setattr(project_router.task_bootstrap, "delay", lambda *args, **kwargs: types.SimpleNamespace(id="task-1"))
    created = client.post("/api/v1/projects", headers=headers, json={"url": "example.com"})
    assert created.status_code == 202

    output = tmp_path / "work" / "owner" / "example-com" / "delivery" / "2026-07-31"
    output.mkdir(parents=True)
    (output / "01-诊断报告.md").write_text("# 中文报告\n", "utf-8")

    def reject_delivery(slug, directory):
        raise project_router.GeoEngineError("delivery contains non-English content: 01-诊断报告.md")

    monkeypatch.setattr(project_router.delivery, "ensure_delivery_contract", reject_delivery)
    response = client.get(
        f"/api/v1/projects/{created.json()['project_id']}/deliveries/2026-07-31",
        headers=headers,
    )

    assert response.status_code == 409
    assert "delivery_contract_invalid" in response.text


def test_delivery_download_rebuilds_even_when_legacy_quality_gate_passed(project_client, monkeypatch, tmp_path):
    client, _ = project_client
    headers = _register(client, "owner@example.com")
    monkeypatch.setitem(sys.modules, "geo", types.SimpleNamespace(cmd_init=lambda args: None))
    monkeypatch.setattr(project_router.task_bootstrap, "delay", lambda *args, **kwargs: types.SimpleNamespace(id="task-1"))
    created = client.post("/api/v1/projects", headers=headers, json={"url": "example.com"})
    assert created.status_code == 202

    output = tmp_path / "work" / "owner" / "example-com" / "delivery" / "2026-07-31"
    (output / "assets").mkdir(parents=True)
    (output / "index.html").write_text("legacy", "utf-8")
    (output / "assets" / "index.json").write_text(
        json.dumps({"quality_gate": {"status": "passed"}}), "utf-8",
    )
    calls = []

    def rebuild(slug, directory):
        calls.append((slug, directory))
        (directory / "01-Audit-Report.html").write_text("formal", "utf-8")
        (directory / "assets" / "index.json").write_text(
            json.dumps({"diagnostic_ready": True, "source_revision": "current"}), "utf-8",
        )
        return directory

    monkeypatch.setattr(project_router.delivery, "ensure_delivery_contract", rebuild)
    response = client.get(
        f"/api/v1/projects/{created.json()['project_id']}/deliveries/2026-07-31",
        headers=headers,
    )

    assert response.status_code == 200
    assert calls and calls[0][0] == "example-com"
    assert response.headers["x-citeaura-source-revision"] == "current"
    with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
        assert "01-Audit-Report.html" in bundle.namelist()
        assert "index.html" in bundle.namelist()


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
    hidden_status = client.get(f"/api/v1/projects/{created.json()['project_id']}/status", headers=other_headers)
    assert hidden_status.status_code == 404
    hidden_framing = client.get(f"/api/v1/projects/{created.json()['project_id']}/framing", headers=other_headers)
    assert hidden_framing.status_code == 404
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


def test_sampling_requires_questions_before_job_is_queued(project_client, monkeypatch):
    client, session_factory = project_client
    headers = _register(client, "questions-owner@example.com")

    def fake_init(args):
        from api.adapters.engine import geolib

        geolib.write_json(geolib.project_dir(args.slug) / "geo.json", {
            "brand": {"name": "Questions", "site": args.url},
            "market": "both",
            "questions": [],
        })

    monkeypatch.setitem(sys.modules, "geo", types.SimpleNamespace(cmd_init=fake_init))
    monkeypatch.setattr(project_router.task_bootstrap, "delay", lambda *a, **kw: types.SimpleNamespace(id="boot"))
    monkeypatch.setattr(project_router.task_sample, "delay", lambda *a, **kw: pytest.fail("sample must not be queued"))
    monkeypatch.setattr(project_router.task_pipeline, "delay", lambda *a, **kw: pytest.fail("sample must not be queued"))

    created = client.post("/api/v1/projects", headers=headers, json={"url": "questions.example"}).json()
    project_id = created["project_id"]
    with session_factory() as db:
        db.get(Job, created["job_id"]).status = "done"
        db.commit()

    direct = client.post(f"/api/v1/projects/{project_id}/sample", headers=headers)
    pipeline = client.post(
        f"/api/v1/projects/{project_id}/actions/sample",
        headers=headers,
        json={"params": {}},
    )

    assert direct.status_code == 409
    assert direct.json() == {"error": "project_questions_required"}
    assert pipeline.status_code == 409
    assert pipeline.json() == {"error": "project_questions_required"}
    with session_factory() as db:
        assert db.query(Job).filter(Job.project_id == project_id).count() == 1


def test_sampling_budget_blocks_direct_pipeline_retry_and_schedule(project_client, monkeypatch):
    client, session_factory = project_client
    headers = _register(client, "budget-owner@example.com")

    def fake_init(args):
        from api.adapters.engine import geolib

        geolib.write_json(geolib.project_dir(args.slug) / "geo.json", {
            "brand": {"name": "Budget", "site": args.url},
            "market": "global",
            "platforms": ["openai"],
            "questions": [
                {"id": "q101", "text": "What is the best budget option?", "market": "global"},
                {"id": "q102", "text": "Which tools offer predictable pricing?", "market": "global"},
            ],
        })

    monkeypatch.setitem(sys.modules, "geo", types.SimpleNamespace(cmd_init=fake_init))
    monkeypatch.setattr(project_router.task_bootstrap, "delay", lambda *a, **kw: types.SimpleNamespace(id="boot"))
    monkeypatch.setattr(project_router.task_sample, "delay", lambda *a, **kw: types.SimpleNamespace(id="sample"))
    monkeypatch.setattr(project_router.task_pipeline, "delay", lambda *a, **kw: types.SimpleNamespace(id="pipeline"))
    monkeypatch.setattr(sampling_control, "resolve_funding", lambda *args, **kwargs: {
        "keys": {"openai": "secret"},
        "pool_codes": frozenset(),
        "rates": {},
    })

    created = client.post("/api/v1/projects", headers=headers, json={"url": "budget.example"}).json()
    project_id = created["project_id"]
    with session_factory() as db:
        db.get(Job, created["job_id"]).status = "done"
        db.commit()

    budget = client.put(
        f"/api/v1/projects/{project_id}/sampling-budget",
        headers=headers,
        json={"monthly_budget_cny_fen": None, "sample_call_limit": 1, "pause_on_budget_exceeded": True},
    )
    assert budget.status_code == 200
    assert budget.json()["estimate"]["calls"] == 2
    assert budget.json()["estimate"]["byok_cost_cny_fen"] is None

    estimate = client.post(
        f"/api/v1/projects/{project_id}/sample/estimate",
        headers=headers,
        json={"repeat": 2},
    )
    assert estimate.status_code == 200
    assert estimate.json()["budget"]["paused"] is True
    assert estimate.json()["estimate"]["calls"] == 4

    blocked = client.post(
        f"/api/v1/projects/{project_id}/sample",
        headers=headers,
        json={"repeat": 2},
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"] == "sample_call_limit_exceeded"
    assert blocked.json()["estimate"]["estimate"]["calls"] == 4

    pipeline_blocked = client.post(
        f"/api/v1/projects/{project_id}/actions/sample",
        headers=headers,
        json={"params": {"--repeat": 2}},
    )
    assert pipeline_blocked.status_code == 409
    assert pipeline_blocked.json()["error"] == "sample_call_limit_exceeded"
    string_flag_blocked = client.post(
        f"/api/v1/projects/{project_id}/actions/serve",
        headers=headers,
        json={"params": {"--no-sample": "false", "--limit": 2}},
    )
    assert string_flag_blocked.status_code == 409
    assert string_flag_blocked.json()["error"] == "sample_call_limit_exceeded"

    scheduled = client.post(
        f"/api/v1/projects/{project_id}/schedule",
        headers=headers,
        json={"interval_days": 7},
    )
    assert scheduled.status_code == 409
    assert scheduled.json()["error"] == "sample_call_limit_exceeded"

    with session_factory() as db:
        source = Job(
            project_id=project_id,
            action="sample",
            status="failed",
            request_json=json.dumps({"repeat": 2}),
        )
        db.add(source)
        db.commit()
        source_id = source.id
    retry = client.post(
        f"/api/v1/projects/{project_id}/jobs/{source_id}/retry",
        headers=headers,
    )
    assert retry.status_code == 409
    assert retry.json()["error"] == "sample_call_limit_exceeded"


def test_retry_rejects_job_attempt_limit(project_client, monkeypatch):
    client, session_factory = project_client
    headers = _register(client, "retry-limit@example.com")
    with session_factory() as db:
        tenant = db.query(Tenant).one()
        project = Project(
            tenant_id=tenant.id,
            slug="retry-limit",
            url="https://retry-limit.example",
            market="both",
            status="failed",
        )
        db.add(project)
        db.flush()
        source = Job(
            project_id=project.id,
            action="verify",
            status="failed",
            attempt=3,
            request_json="{}",
        )
        db.add(source)
        db.commit()
        project_id, source_id = project.id, source.id

    monkeypatch.setattr(project_router.task_verify, "delay", lambda *args, **kwargs: pytest.fail("retry should be blocked"))
    response = client.post(
        f"/api/v1/projects/{project_id}/jobs/{source_id}/retry",
        headers=headers,
    )
    assert response.status_code == 409
    assert response.json()["error"] == "job_retry_attempt_limit"
    with session_factory() as db:
        assert db.query(Job).filter(Job.project_id == project_id).count() == 1


@contextmanager
def _empty_context():
    yield
