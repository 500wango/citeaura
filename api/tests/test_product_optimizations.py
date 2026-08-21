
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.adapters import engine as engine_adapter
from api.adapters import brand_facts, measurement, preflight, product_insights, report_quality, sampling_control, ticket_workflow
from api.adapters.engine import geolib, with_tenant_context
from api.db import Base
from api.models import Project, Tenant


def _metrics(date, version, mention_rate, samples=100, successful=100, failed=0, platforms=2):
    platform_data = {
        f"provider_{index}": {"mention_rate": mention_rate, "samples": samples // platforms}
        for index in range(platforms)
    }
    provenance = [
        {
            "engine_code": code,
            "sampling_mode": "API - Parametric knowledge",
            "model": "test-model",
        }
        for code in platform_data
    ]
    return {
        "date": date,
        "question_set_version": version,
        "sample_summary": {"total": successful + failed, "successful": successful, "failed": failed},
        "platforms": platform_data,
        "provenance": {"platforms": provenance},
    }


def test_measurement_quality_marks_noteworthy_and_incomparable_periods(tmp_path, monkeypatch):
    monkeypatch.setattr(engine_adapter, "WORK_ROOT", tmp_path / "work")
    with with_tenant_context("tenant", "project"):
        directory = geolib.project_dir("project")
        geolib.write_json(directory / "metrics" / "2026-07-01.json", _metrics("2026-07-01", "v1", 0.10))
        geolib.write_json(directory / "metrics" / "2026-08-01.json", _metrics("2026-08-01", "v1", 0.20))

        result = measurement.sampling_quality("project")
        assert result["current"]["effective_visibility_samples"] == 100
        assert result["current"]["failure_rate"] == 0
        assert result["comparable"] is True
        assert result["trend"]["status"] == "noteworthy"
        assert result["trend"]["label"] == "Worth monitoring"
        assert result["trend"]["delta_pp"] == 10.0
        assert result["confidence"]["label"] == "Representative baseline"

        changed = _metrics("2026-08-01", "v2", 0.20)
        geolib.write_json(directory / "metrics" / "2026-08-01.json", changed)
        result = measurement.sampling_quality("project")
        assert result["comparable"] is False
        assert result["trend"]["status"] == "not_comparable"
        assert "Question set version changed" in result["comparison_reason"]


def test_wilson_interval_keeps_small_samples_visibly_uncertain():
    assert measurement.wilson_interval(3, 3) == {
        "confidence_level": 0.95,
        "successes": 3,
        "samples": 3,
        "lower": 0.4385,
        "upper": 1,
    }
    assert measurement.wilson_interval(0, 0) is None
    with pytest.raises(ValueError):
        measurement.wilson_interval(4, 3)


def test_sampling_manifest_records_targeted_question_scope(tmp_path, monkeypatch):
    monkeypatch.setattr(engine_adapter, "WORK_ROOT", tmp_path / "work")
    with with_tenant_context("tenant", "project"):
        directory = geolib.project_dir("project")
        geolib.write_json(directory / "geo.json", {
            "questions": [
                {"id": "q101", "text": "What is Acme?", "market": "global"},
                {"id": "q102", "text": "Which Acme plan fits?", "market": "global"},
            ],
            "platforms": ["openai"],
        })
        (directory / "samples").mkdir(parents=True)
        (directory / "samples" / "2026-08-22.jsonl").write_text(
            '{"platform":"openai","ok":true,"sample_mode":"api"}\n', "utf-8",
        )
        geolib.write_json(directory / "metrics" / "2026-08-22.json", {"platforms": {}})
        manifest = measurement.record_sampling(
            "project", requested_platforms=["openai"], question_ids=["q102", " q101 ", "q102"], job_id=42,
        )

    assert manifest["requested_question_ids"] == ["q102", "q101"]
    assert manifest["question_set"]["version"]
    assert manifest["platforms"][0]["engine_code"] == "openai"


def test_product_insights_prioritize_prompt_gaps_and_keep_cohorts_separate(tmp_path, monkeypatch):
    monkeypatch.setattr(engine_adapter, "WORK_ROOT", tmp_path / "work")
    config = {
        "brand": {"name": "Acme", "site": "https://acme.example", "aliases": []},
        "market": "global",
        "competitors": [{"name": "Rival", "aliases": [], "market": "global"}],
        "questions": [{"id": "q001", "text": "Best proposal platform?", "market": "global", "group": "Recommendation"}],
    }
    rows = [{
        "ok": True, "platform": "openai", "platform_name": "OpenAI", "search_enabled": False,
        "question_id": "q001", "question": config["questions"][0]["text"], "brand_in_question": False,
        "analysis": {"brand_mentioned": False, "competitors_mentioned": ["Rival"], "cited_domains": []},
    } for _ in range(5)]
    with with_tenant_context("tenant", "project"):
        directory = geolib.project_dir("project")
        geolib.write_json(directory / "geo.json", config)
        blueprint = {"contents": [{
            "id": "q001", "question": config["questions"][0]["text"],
            "form": "Comparison guide", "group": "Recommendation", "status": "draft",
        }]}
        (directory / "content" / "facts.md").parent.mkdir(parents=True)
        (directory / "content" / "facts.md").write_text(
            f"# Brand facts\n\n{brand_facts.REVIEWED_MARKER}\n", "utf-8",
        )
        geolib.write_json(directory / "tasks.json", {"tasks": [{
            "id": "T-101", "title": "Ship q001 comparison", "question_id": "q001",
            "status": "todo", "priority": "P1",
        }]})
        geolib.write_json(directory / "assets" / "index.json", {"asset_records": [{
            "path": "drafts/q001.md", "status": "draft", "issues": [],
        }]})
        result = product_insights.build("project", rows, config, blueprint)

    prompt = result["prompt_explorer"]["items"][0]
    assert prompt["priority"] == "high"
    assert prompt["mention_interval"] == {
        "confidence_level": 0.95,
        "successes": 0,
        "samples": 5,
        "lower": 0,
        "upper": 0.4345,
    }
    heatmap = result["competitor_heatmap"]
    assert heatmap["cohorts"][0]["sampling_mode"] == "API·参数化知识"
    assert heatmap["questions"][0]["competitors"][0]["rate"] == 1.0
    assert result["takeover_alerts"][0]["status"] == "takeover_candidate"
    campaign = result["campaign_proposals"]
    assert campaign["counts"] == {"blocked": 0, "review_required": 0, "ready_for_approval": 1}
    assert campaign["policy"] == {
        "human_approval_required": True,
        "automatic_publication": False,
        "impact_claims": "hypothesis_only",
    }
    proposal = campaign["items"][0]
    assert proposal["kind"] == "competitive_takeover"
    assert proposal["status"] == "ready_for_approval"
    assert proposal["target_question"]["id"] == "q001"
    assert proposal["related_tickets"] == [{
        "id": "T-101", "title": "Ship q001 comparison", "status": "todo", "priority": "P1",
    }]
    assert proposal["related_assets"][0]["path"] == "drafts/q001.md"
    assert proposal["expected_impact"]["claim"] == "hypothesis"
    assert proposal["expected_impact"]["cohort_baselines"][0]["sampling_mode"] == "API·参数化知识"
    assert proposal["gates"]["automatic_publication"] is False


def test_campaign_proposals_fail_closed_on_sampling_facts_and_asset_review(tmp_path, monkeypatch):
    monkeypatch.setattr(engine_adapter, "WORK_ROOT", tmp_path / "work")
    config = {
        "brand": {"name": "Acme", "site": "https://acme.example"},
        "questions": [{"id": "q001", "text": "Which platform is reliable?", "market": "global"}],
    }
    row = {
        "ok": True, "platform": "openai", "question_id": "q001",
        "question": config["questions"][0]["text"], "brand_in_question": False,
        "analysis": {"brand_mentioned": False, "competitors_mentioned": []},
    }
    with with_tenant_context("tenant", "project"):
        directory = geolib.project_dir("project")
        geolib.write_json(directory / "geo.json", config)
        blocked = product_insights.build("project", [row, row], config)
        assert blocked["campaign_proposals"]["items"][0]["status"] == "blocked"
        assert blocked["campaign_proposals"]["items"][0]["next_step"]["route"] == "#/engines"

        (directory / "content" / "facts.md").parent.mkdir(parents=True)
        (directory / "content" / "facts.md").write_text("# Brand facts\n", "utf-8")
        review = product_insights.build("project", [row, row, row], config)
        assert review["campaign_proposals"]["items"][0]["status"] == "review_required"
        assert review["campaign_proposals"]["items"][0]["next_step"]["route"] == "#/facts"

        (directory / "content" / "facts.md").write_text(
            f"# Brand facts\n\n{brand_facts.REVIEWED_MARKER}\n", "utf-8",
        )
        geolib.write_json(directory / "assets" / "index.json", {"asset_records": [{
            "path": "drafts/q001.md", "status": "review_required",
            "issues": ["derived_from_unreviewed_brand_facts"],
        }]})
        asset_review = product_insights.build("project", [row, row, row], config)
        proposal = asset_review["campaign_proposals"]["items"][0]
        assert proposal["status"] == "review_required"
        assert proposal["next_step"] == {
            "label": "Resolve asset review gates", "route": "#/assets?question=q001",
        }


def test_report_quality_explains_crawl_sampling_and_delivery_gaps(tmp_path, monkeypatch):
    monkeypatch.setattr(engine_adapter, "WORK_ROOT", tmp_path / "work")
    with with_tenant_context("tenant", "project"):
        directory = geolib.project_dir("project")
        geolib.write_json(directory / "audit.json", {
            "page_count": 10,
            "site": {"pages_crawled": 10, "pages_ok": 4, "ai_bots_blocked": ["GPTBot"]},
        })
        geolib.write_json(
            directory / "metrics" / "2026-08-01.json",
            _metrics("2026-08-01", "v1", 0.10, samples=5, successful=4, failed=2),
        )

        result = report_quality.assess("project", has_sampling_access=False)

    codes = {item["code"] for item in result["issues"]}
    assert {"crawl_limited", "ai_bots_blocked", "api_key_missing", "sampling_insufficient",
            "sampling_failure_high", "playbook_missing", "delivery_missing"} <= codes
    assert all(item["action"] and item["route"] for item in result["issues"])
    assert result["effective_report"] is False
    assert result["diagnostic_ready"] is False
    assert result["components"]["measurement"]["successful_samples"] == 4


def test_single_platform_with_fourteen_samples_is_a_limited_baseline(tmp_path, monkeypatch):
    monkeypatch.setattr(engine_adapter, "WORK_ROOT", tmp_path / "work")
    with with_tenant_context("tenant", "project"):
        directory = geolib.project_dir("project")
        geolib.write_json(directory / "audit.json", {
            "page_count": 3,
            "site": {"pages_crawled": 3, "pages_ok": 3, "ai_bots_blocked": []},
        })
        geolib.write_json(
            directory / "metrics" / "2026-08-13.json",
            _metrics("2026-08-13", "v1", 0.2, samples=14, successful=14, platforms=1),
        )
        geolib.write_json(directory / "tasks.json", {"tasks": [{"id": "T-001"}]})

        measurement_result = measurement.sampling_quality("project")
        report_result = report_quality.assess("project", has_sampling_access=True)

    assert measurement_result["confidence"]["level"] == "limited_baseline"
    assert measurement_result["confidence"]["allows_global_conclusions"] is False
    assert measurement_result["confidence"]["allows_trend_attribution"] is False
    assert report_result["effective_report"] is True
    assert report_result["diagnostic_ready"] is True
    assert report_result["measured_visibility"] is False
    assert "sampling_platforms_limited" in {item["code"] for item in report_result["issues"]}


def test_preflight_failures_always_include_a_repair_action(monkeypatch):
    monkeypatch.setattr(preflight, "_resolve_public", lambda hostname, port: ["203.0.113.10"])

    class Response:
        def __init__(self, status_code):
            self.status_code = status_code

        def close(self):
            pass

    class RedirectResponse(Response):
        def __init__(self):
            super().__init__(301)
            self.headers = {"Location": "https://www.example.com/"}

    monkeypatch.setattr(preflight.requests, "get", lambda *args, **kwargs: RedirectResponse())
    redirected = preflight.run("https://example.com")
    assert next(item for item in redirected["checks"] if item["name"] == "homepage")["ok"] is True

    monkeypatch.setattr(preflight.requests, "get", lambda *args, **kwargs: Response(503))
    result = preflight.run("https://example.com")
    failures = [item for item in result["checks"] if not item["ok"]]
    assert result["ready"] is False
    assert "homepage" in {item["name"] for item in failures}
    assert all(item["action"] for item in failures)


def test_ticket_workflow_tracks_bulk_changes_notes_and_verification(tmp_path, monkeypatch):
    monkeypatch.setattr(engine_adapter, "WORK_ROOT", tmp_path / "work")
    with with_tenant_context("tenant", "project"):
        directory = geolib.project_dir("project")
        geolib.write_json(directory / "tasks.json", {
            "summary": {"total": 2},
            "tasks": [
                {"id": "T-001", "title": "Fix crawl", "priority": "P0", "package": "页面技术",
                 "market": "both", "status": "todo",
                 "owner": "开发", "action": "Allow the crawler", "acceptance": {"type": "auto"}},
                {"id": "T-002", "title": "Add facts", "priority": "P1", "package": "知识库",
                 "market": "both", "status": "todo",
                 "owner": "内容", "action": "Publish facts", "acceptance": {"type": "manual"}},
            ],
        })

        updated = ticket_workflow.update(
            "project", "T-001",
            {"status": "doing", "owner": "alice@example.com", "due_date": "2026-08-20", "note": "Started"},
            "owner@example.com",
        )
        assert updated["owner"] == "alice@example.com"
        assert updated["due_date"] == "2026-08-20"
        assert updated["notes"][-1]["text"] == "Started"
        assert updated["activity"][-1]["changes"]["status"] == {"from": "todo", "to": "doing"}

        bulk = ticket_workflow.bulk_update(
            "project", ["T-001", "T-002"], {"status": "blocked", "note": "Waiting for release"},
            "editor@example.com",
        )
        assert {item["status"] for item in bulk} == {"blocked"}
        assert len(ticket_workflow.filter_tickets(bulk, status="blocked", query="fix")) == 1

        report = ticket_workflow.record_verification("project", {
            "verified_at": "2026-08-05T10:00:00+00:00",
            "results": [{"id": "T-001", "verdict": "fail", "note": "GPTBot still receives 403",
                         "was": "blocked", "now": "blocked"}],
        })
        assert report["results"][0]["failure_evidence"] == "GPTBot still receives 403"
        assert report["results"][0]["next_action"] == "Allow the crawler"
        stored = geolib.read_json(directory / "tasks.json", {})
        verification = stored["tasks"][0]["activity"][-1]
        assert verification["type"] == "verification"
        assert verification["next_action"] == "Allow the crawler"


def test_sampling_estimate_splits_byok_and_platform_cost_and_enforces_limits(tmp_path, monkeypatch):
    monkeypatch.setattr(engine_adapter, "WORK_ROOT", tmp_path / "work")
    engine = create_engine(f"sqlite:///{tmp_path / 'sampling.sqlite'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as db:
        tenant = Tenant(name="tenant", plan="pro")
        db.add(tenant)
        db.flush()
        project = Project(
            tenant_id=tenant.id,
            slug="project",
            url="https://example.com",
            market="both",
            monthly_budget_cny_fen=10,
            sample_call_limit=3,
            pause_on_budget_exceeded=True,
        )
        db.add(project)
        db.commit()
        db.refresh(tenant)
        db.refresh(project)

        with with_tenant_context("tenant", "project"):
            geolib.write_json(geolib.project_dir("project") / "geo.json", {
                "market": "both",
                "platforms": ["deepseek", "openai"],
                "questions": [
                    {"id": "q001", "text": "中文问题", "market": "cn"},
                    {"id": "q101", "text": "English question", "market": "global"},
                ],
            })

        monkeypatch.setattr(sampling_control, "resolve_funding", lambda *args, **kwargs: {
            "keys": {"deepseek": "byok-secret", "openai": "pool-secret"},
            "pool_codes": frozenset(("openai",)),
            "rates": {"openai": 3},
        })
        estimate = sampling_control.estimate(
            db, tenant, project, platforms=["deepseek", "openai"], repeat=2,
        )
        assert estimate["estimate"] == {
            "calls": 4,
            "byok_calls": 2,
            "platform_pool_calls": 2,
            "platform_pool_cost_cny_fen": 6,
            "byok_cost_cny_fen": None,
            "byok_cost_note": "BYOK costs are billed directly by API providers; CiteAura does not read provider invoices.",
            "minutes": 2,
        }
        assert estimate["budget"]["call_limit_exceeded"] is True
        with pytest.raises(sampling_control.SamplingBudgetExceeded) as exc_info:
            sampling_control.ensure_allowed(
                db, tenant, project, platforms=["deepseek", "openai"], repeat=2,
            )
        assert exc_info.value.code == "sample_call_limit_exceeded"

        project.sample_call_limit = None
        project.monthly_budget_cny_fen = 5
        with pytest.raises(sampling_control.SamplingBudgetExceeded) as exc_info:
            sampling_control.ensure_allowed(
                db, tenant, project, platforms=["deepseek", "openai"], repeat=2,
            )
        assert exc_info.value.code == "monthly_budget_exceeded"
