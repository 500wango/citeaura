import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.adapters import engine as engine_adapter
from api.adapters import measurement, preflight, report_quality, sampling_control, ticket_workflow
from api.adapters.engine import geolib, with_tenant_context
from api.db import Base
from api.models import Project, Tenant


def _metrics(date, version, mention_rate, samples=100, successful=100, failed=0):
    return {
        "date": date,
        "question_set_version": version,
        "sample_summary": {"total": successful + failed, "successful": successful, "failed": failed},
        "platforms": {"deepseek": {"mention_rate": mention_rate, "samples": samples}},
        "provenance": {
            "platforms": [{
                "engine_code": "deepseek",
                "sampling_mode": "API·参数化知识",
                "model": "deepseek-chat",
            }],
        },
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
        assert result["trend"]["label"] == "值得关注"
        assert result["trend"]["delta_pp"] == 10.0

        changed = _metrics("2026-08-01", "v2", 0.20)
        geolib.write_json(directory / "metrics" / "2026-08-01.json", changed)
        result = measurement.sampling_quality("project")
        assert result["comparable"] is False
        assert result["trend"]["status"] == "not_comparable"
        assert "问题集版本" in result["comparison_reason"]


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
    assert result["components"]["measurement"]["successful_samples"] == 4


def test_preflight_failures_always_include_a_repair_action(monkeypatch):
    monkeypatch.setattr(preflight, "_resolve_public", lambda hostname, port: ["203.0.113.10"])

    class Response:
        def __init__(self, status_code):
            self.status_code = status_code

        def close(self):
            pass

    responses = iter((Response(301), Response(503)))
    monkeypatch.setattr(preflight.requests, "get", lambda *args, **kwargs: next(responses))

    result = preflight.run("https://example.com")
    failures = [item for item in result["checks"] if not item["ok"]]
    assert result["ready"] is False
    assert {item["name"] for item in failures} == {"homepage", "robots"}
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
            "results": [{"id": "T-001", "verdict": "未达标", "note": "GPTBot still receives 403",
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
            "byok_cost_note": "BYOK 费用由 API 供应商直接收取，DisvorAI 无法读取供应商账单。",
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
