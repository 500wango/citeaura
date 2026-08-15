from api.adapters import action_scope


def _page(url, checks, *, excluded=False):
    return {
        "url": url,
        "evaluation_status": "excluded" if excluded else "evaluated",
        "checks": [{"id": check, "status": status} for check, status in checks.items()],
    }


def _audit():
    return {
        "audited_at": "2026-08-14T11:00:00+00:00",
        "applicable_avg_score": 87.4,
        "page_count": 5,
        "site": {"has_sitemap": False, "has_llms_txt": False, "ai_bots_blocked": ["GPTBot"]},
        "site_findings": [
            {"code": "NO_SITEMAP"},
            {"code": "NO_LLMS_TXT"},
            {"code": "AI_BOTS_BLOCKED"},
        ],
        "pages": [
            _page("https://example.com/app", {}, excluded=True),
            _page("https://example.com/privacy", {"canonical": "failed", "date": "failed", "rendered_content": "passed"}),
            _page("https://example.com/terms", {"canonical": "failed", "date": "passed", "rendered_content": "passed"}),
            _page("https://example.com/docs", {"structured_data": "failed", "steps": "failed", "rendered_content": "passed"}),
            _page("https://example.com", {"structured_data": "passed", "definition": "failed", "rendered_content": "passed"}),
        ],
    }


def _task(task_id, check, affected=None):
    return {
        "id": task_id,
        "priority": "P1",
        "package": "Content matrix",
        "market": "global",
        "title": task_id,
        "why": "raw rationale",
        "action": "raw action",
        "owner": "Content",
        "effort": "M",
        "window": "60 days",
        "affected": affected or [],
        "acceptance": {"type": "auto", "check": check, "desc": "raw acceptance"},
        "status": "todo",
    }


def _limited_quality():
    return {
        "current": {"effective_visibility_samples": 14, "platform_count": 1},
        "confidence": {"sufficient": False, "minimum_samples": 20, "minimum_platforms": 2},
    }


def test_scope_uses_applicable_pages_and_defers_global_metric_targets():
    data = {
        "baseline": {"avg_score": 48.5, "pages": 5},
        "tasks": [
            _task("T-007", "pages.static_text", ["https://example.com/app"]),
            _task("T-008", "pages.has_jsonld", ["https://example.com/app", "https://example.com/privacy", "https://example.com/terms", "https://example.com/docs"]),
            _task("T-009", "pages.block:\u64cd\u4f5c\u6b65\u9aa4"),
            _task("T-010", "pages.block:\u5b9a\u4e49"),
            _task("T-011", "pages.block:\u6570\u5b57\u4e8b\u5b9e"),
            _task("T-014", "site.avg_score_gte:70"),
            _task("T-015", "metrics.mention_rate_gte:global:0.5"),
            _task("T-016", "metrics.own_cite_gte:global:0.1"),
        ],
    }

    scoped = action_scope.scope_task_data(data, _audit(), _limited_quality())
    tasks = {task["id"]: task for task in scoped["tasks"]}

    assert scoped["baseline"]["avg_score"] == 87.4
    assert scoped["baseline"]["raw_avg_score"] == 48.5
    assert tasks["T-008"]["affected"] == ["https://example.com/docs"]
    assert tasks["T-009"]["affected"] == ["https://example.com/docs"]
    assert tasks["T-010"]["affected"] == ["https://example.com"]
    assert "sitewide" not in tasks["T-008"]["title"].lower()
    assert "T-007" not in tasks
    excluded = {task["id"]: task for task in scoped["scope_excluded_tasks"]}
    assert excluded["T-007"]["scope_exclusion_reason"] == "no_applicable_failure"
    assert tasks["T-008"]["verification_cohort"] == ["https://example.com/docs"]
    assert "T-011" not in tasks
    assert "T-014" not in tasks
    assert "T-015" not in tasks
    assert "T-016" not in tasks
    assert "T-MEASUREMENT-BASELINE" in tasks
    assert tasks["T-AUDIT-CANONICAL"]["affected"] == [
        "https://example.com/privacy", "https://example.com/terms",
    ]
    assert tasks["T-AUDIT-DATE"]["affected"] == ["https://example.com/privacy"]
    assert {task["id"] for task in scoped["scope_deferred_tasks"]} == {"T-015", "T-016"}



def test_scope_retains_workflow_tasks_without_current_failures():
    audit = _audit()
    retained = _task("T-RETAINED", "pages.static_text", ["https://example.com/terms"])
    retained["status"] = "doing"
    todo = _task("T-TODO", "pages.static_text", ["https://example.com/terms"])

    scoped = action_scope.scope_task_data({"tasks": [retained, todo]}, audit, _limited_quality())
    tasks = {task["id"]: task for task in scoped["tasks"]}
    excluded = {task["id"]: task for task in scoped["scope_excluded_tasks"]}

    assert tasks["T-RETAINED"]["affected"] == []
    assert tasks["T-RETAINED"]["verification_cohort"] == ["https://example.com/terms"]
    assert excluded["T-TODO"]["scope_exclusion_reason"] == "no_applicable_failure"


def test_scope_restores_metric_targets_after_representative_sampling():
    first = action_scope.scope_task_data({
        "tasks": [
            _task("T-015", "metrics.mention_rate_gte:global:0.5"),
            _task("T-016", "metrics.own_cite_gte:global:0.1"),
        ],
    }, _audit(), _limited_quality())
    representative = {
        "current": {"effective_visibility_samples": 40, "platform_count": 2},
        "confidence": {"sufficient": True, "minimum_samples": 20, "minimum_platforms": 2},
    }

    second = action_scope.scope_task_data(first, _audit(), representative)
    ids = {task["id"] for task in second["tasks"]}

    assert "T-MEASUREMENT-BASELINE" not in ids
    assert {"T-015", "T-016"} <= ids
    assert second["scope_deferred_tasks"] == []


def test_score_task_replaces_raw_scope_and_progress_with_applicable_evidence():
    audit = _audit()
    audit["applicable_avg_score"] = 64.2
    audit["pages"].append(_page("https://example.com/sitemap.xml", {"structured_data": "failed"}, excluded=False))
    audit["pages"][-1]["evaluation_status"] = "insufficient_evidence"
    score_task = _task("T-SCORE", "site.avg_score_gte:70", ["https://example.com/app"])
    score_task.update({
        "action": "Apply the same content checklist sitewide.",
        "progress": {"label": "Raw score", "cur": 32.5, "target": 70, "op": "gte"},
        "progress_first": {"label": "Raw score", "cur": 32.5, "target": 70, "op": "gte"},
    })

    scoped = action_scope.scope_task_data(
        {"tasks": [score_task]},
        audit,
        {"confidence": {"sufficient": True}},
    )
    task = next(item for item in scoped["tasks"] if item["id"] == "T-SCORE")

    assert "https://example.com/app" not in task["affected"]
    assert "https://example.com/sitemap.xml" not in task["affected"]
    assert task["progress"]["cur"] == 64.2
    assert scoped["baseline"]["applicable_pages"] == 4
    assert "progress_first" not in task
    assert "role-aware" in task["action"]


def test_scope_adds_baseline_without_metric_targets_and_removes_resolved_site_tasks():
    audit = _audit()
    audit["site"] = {"has_sitemap": True, "has_llms_txt": True, "ai_bots_blocked": []}
    audit["site_findings"] = []
    scoped = action_scope.scope_task_data({
        "tasks": [
            _task("T-SITEMAP", "site.has_sitemap"),
            _task("T-LLMS", "site.has_llms_txt"),
            _task("T-BOTS", "site.no_ai_bot_block"),
        ],
    }, audit, _limited_quality())

    assert {task["id"] for task in scoped["tasks"]} >= {"T-MEASUREMENT-BASELINE"}
    assert not {"T-SITEMAP", "T-LLMS", "T-BOTS"} & {task["id"] for task in scoped["tasks"]}
    assert {task["scope_exclusion_reason"] for task in scoped["scope_excluded_tasks"]} == {
        "site_check_already_passes",
    }


def test_missing_crawler_evidence_does_not_pass_the_unblocked_check():
    audit = _audit()
    audit["site"] = {"has_sitemap": True, "has_llms_txt": True}
    audit["site_findings"] = []

    scoped = action_scope.scope_task_data({
        "tasks": [_task("T-BOTS", "site.no_ai_bot_block")],
    }, audit, {"confidence": {"sufficient": True}})
    verification = action_scope.scope_verification({}, scoped, audit, {"confidence": {"sufficient": True}})

    assert "T-BOTS" in {task["id"] for task in scoped["tasks"]}
    results = {item["id"]: item for item in verification["results"]}
    assert results["T-BOTS"]["verdict"] == "fail"


def test_verification_recomputes_role_aware_progress_and_sampling_evidence():
    task_data = action_scope.scope_task_data({
        "tasks": [
            _task("T-008", "pages.has_jsonld"),
            _task("T-015", "metrics.mention_rate_gte:global:0.5"),
        ],
    }, _audit(), _limited_quality())
    verification = action_scope.scope_verification(
        {"verified_at": "2026-08-14T12:00:00+00:00", "audit_avg_score": 48.5, "results": []},
        task_data,
        _audit(),
        _limited_quality(),
    )
    results = {result["id"]: result for result in verification["results"]}

    assert verification["audit_avg_score"] == 87.4
    assert verification["score_method"] == "applicable_page_role_v1"
    assert results["T-008"]["progress"]["cur"] == 1
    assert results["T-008"]["progress"]["target"] == 0
    assert "14 valid sample(s) across 1 platform(s)" in results["T-MEASUREMENT-BASELINE"]["note_en"]
