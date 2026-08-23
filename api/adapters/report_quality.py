"""首份报告完整度和缺失项诊断。"""

from api.adapters import brand_identity, global_scope, measurement
from api.adapters.engine import geolib
from api.adapters.measurement import MIN_COMPARABLE_SAMPLES, MIN_REPRESENTATIVE_PLATFORMS, sampling_quality


def _latest(directory, pattern="*.json"):
    files = sorted(directory.glob(pattern)) if directory.exists() else []
    return files[-1] if files else None


def _issue(code, severity, message, action, route):
    return {"code": code, "severity": severity, "message": message, "action": action, "route": route}


def assess(project_slug, has_sampling_access=False):
    """按审计、采样、工单和交付物计算报告完整度。"""
    directory = geolib.project_dir(project_slug)
    audit = geolib.read_json(directory / "audit.json", {}) or {}
    metrics_path = _latest(directory / "metrics")
    metrics = geolib.read_json(metrics_path, {}) if metrics_path else {}
    tasks = geolib.read_json(directory / "tasks.json", {}) or {}
    measurement_quality = sampling_quality(project_slug)
    issues = []

    try:
        config = geolib.load_config(project_slug)
    except Exception:  # noqa: BLE001 - report completeness must survive a partial workspace
        config = {}
    sample_files = sorted((directory / "samples").glob("*.jsonl")) if (directory / "samples").exists() else []
    current_rows = []
    if sample_files:
        current_rows = [
            row for row in geolib.read_jsonl(sample_files[-1])
            if row.get("ok") and global_scope.is_global_sample(row, config) and brand_identity.is_current_sample(row, config)
        ]
    question_ids = [
        str(item.get("id")) for item in config.get("questions") or []
        if isinstance(item, dict) and item.get("id")
    ]
    question_evidence = measurement.question_cohort_evidence(
        current_rows,
        config,
        measurement.MIN_QUESTION_SAMPLES,
        expected_cohorts=((metrics.get("provenance") or {}).get("platforms") or []),
    )
    measured_questions = int(question_evidence.get("measured") or 0)
    sufficient_questions = int(question_evidence.get("sufficient") or 0)
    question_ready = bool(question_ids) and sufficient_questions == len(question_ids)
    if question_ids and not question_ready:
        gap_count = len(question_evidence.get("gaps") or [])
        missing = sum(int(item.get("missing_samples") or 0) for item in question_evidence.get("gaps") or [])
        issues.append(_issue(
            "question_evidence_limited",
            "info",
            f"{gap_count} question(s) are missing {missing} comparable provider/mode sample(s)",
            "Fill cohort gaps before ranking content opportunities or attributing changes",
            "engines",
        ))
    asset_index = geolib.read_json(directory / "assets" / "index.json", {}) or {}

    page_count = int(audit.get("page_count") or 0)
    site = audit.get("site") or {}
    pages_crawled = int(site.get("pages_crawled") or page_count or 0)
    pages_ok = int(site.get("pages_ok") or page_count or 0)
    crawl_ratio = pages_ok / pages_crawled if pages_crawled else 0
    audit_ratio = 0 if not page_count else max(0.2, min(1.0, crawl_ratio or 1.0))
    audit_score = round(35 * audit_ratio)
    if not page_count:
        issues.append(_issue("audit_missing", "critical", "Site-wide GEO audit pending", "Re-run site crawl and page audit", "siteaudit"))
    elif crawl_ratio < 0.8:
        issues.append(_issue(
            "crawl_limited", "warning", f"Only {pages_ok}/{pages_crawled} pages accessible",
            "Check WAF, rate limits, login gates, and robots.txt, then re-crawl", "siteaudit",
        ))
    if site.get("ai_bots_blocked"):
        issues.append(_issue(
            "ai_bots_blocked", "critical", "robots.txt is blocking AI search crawlers",
            "Remove sitewide Disallow, retain restrictions only for admin or sensitive routes", "siteaudit",
        ))

    current = measurement_quality.get("current") or {}
    confidence = measurement_quality.get("confidence") or {}
    successful = int(current.get("successful") or 0)
    platform_count = int(confidence.get("platform_count") or 0)
    sample_coverage = min(1.0, successful / MIN_COMPARABLE_SAMPLES) if metrics else 0
    platform_coverage = min(1.0, platform_count / MIN_REPRESENTATIVE_PLATFORMS) if metrics else 0
    sampling_ratio = sample_coverage * platform_coverage
    sampling_score = round(35 * sampling_ratio)
    if not has_sampling_access:
        issues.append(_issue(
            "api_key_missing", "info",
            "API keys are optional. The diagnostic pack still reports site and content findings",
            "Add a key or import a manual sheet only if you want measured mention rates", "engine-settings",
        ))
    if not metrics:
        issues.append(_issue(
            "sampling_missing", "info",
            "AI visibility is not measured yet. That does not block the diagnostic pack",
            "Run sampling only if you want measured mention rates in the next cycle", "engines",
        ))
    elif successful < MIN_COMPARABLE_SAMPLES:
        issues.append(_issue(
            "sampling_insufficient", "info",
            f"Currently only {successful} valid samples; mention rates stay limited",
            f"Collect at least {MIN_COMPARABLE_SAMPLES} valid samples before publishing visibility claims", "engines",
        ))
    if metrics and platform_count < MIN_REPRESENTATIVE_PLATFORMS:
        issues.append(_issue(
            "sampling_platforms_limited", "info",
            f"Currently only {platform_count} sampled platform(s); do not generalize across engines",
            f"Sample at least {MIN_REPRESENTATIVE_PLATFORMS} platforms before publishing cross-engine claims",
            "engines",
        ))
    if current.get("failure_rate") is not None and current["failure_rate"] > 0.2:
        issues.append(_issue(
            "sampling_failure_high", "warning", f"Sampling failure rate is {current['failure_rate']:.0%}",
            "Test corresponding API key and verify provider quotas/rate limits", "engine-settings",
        ))

    ticket_count = len(tasks.get("tasks", [])) if isinstance(tasks.get("tasks"), list) else 0
    playbook_score = 20 if ticket_count else 0
    if not ticket_count:
        issues.append(_issue("playbook_missing", "warning", "Action tickets pending", "Generate action plan", "plan"))

    delivery_directory = directory / "delivery"
    has_delivery = delivery_directory.exists() and any(delivery_directory.iterdir())
    delivery_score = 10 if has_delivery else 0
    if not has_delivery:
        issues.append(_issue(
            "delivery_missing", "info", "Diagnostic pack not compiled yet",
            "Build the diagnostic pack", "report",
        ))

    score = audit_score + sampling_score + playbook_score + delivery_score
    if score >= 85:
        level = "complete"
    elif score >= 60:
        level = "usable"
    elif score > 0:
        level = "partial"
    else:
        level = "missing"
    diagnostic_ready = page_count > 0 and ticket_count > 0
    asset_records = [
        item for item in (asset_index.get("asset_records") or [])
        if isinstance(item, dict)
    ]
    asset_summary = asset_index.get("summary") if isinstance(asset_index.get("summary"), dict) else {}
    workflow_summary = asset_index.get("workflow_summary") if isinstance(asset_index.get("workflow_summary"), dict) else {}
    ready_assets = int(asset_summary.get("ready") or 0) or sum(
        item.get("status") in ("ready", "deployable") for item in asset_records
    )
    needs_review_assets = int(asset_summary.get("needs_review") or 0) or sum(
        item.get("status") in ("needs_review", "review_required") for item in asset_records
    )
    template_assets = int(asset_summary.get("template") or 0) or int(workflow_summary.get("draft") or 0)
    implementation_ready = bool(asset_index.get("implementation_ready")) or bool(
        asset_records and all(item.get("status") in ("ready", "deployable") for item in asset_records)
    )
    readiness = {
        "audit": {
            "ready": bool(page_count and crawl_ratio >= 0.8 and not site.get("ai_bots_blocked")),
            "label": "Site audit ready" if page_count else "Site audit pending",
            "pages_crawled": pages_crawled,
            "pages_ok": pages_ok,
        },
        "measurement": {
            "ready": bool(confidence.get("sufficient")),
            "label": confidence.get("label", "No baseline"),
            "samples": successful,
            "platforms": platform_count,
        },
        "question": {
            "ready": question_ready,
            "label": "Question-level evidence ready" if question_ready else "Per-question cohort evidence still limited",
            "total": len(question_ids),
            "measured": measured_questions,
            "sufficient": sufficient_questions,
            "minimum_samples": measurement.MIN_QUESTION_SAMPLES,
            "cohorts": question_evidence.get("cohorts") or [],
            "gaps": [
                {
                    "question_id": item.get("id"),
                    "samples": item.get("samples", 0),
                    "required": item.get("required", measurement.MIN_QUESTION_SAMPLES),
                    "missing_samples": item.get("missing_samples", measurement.MIN_QUESTION_SAMPLES),
                    "cohorts": item.get("cohorts") or [],
                }
                for item in question_evidence.get("gaps") or []
            ],
        },
        "attribution": measurement_quality.get("attribution") or {
            "ready": False,
            "status": "unavailable",
            "label": "No comparable period",
        },
        "implementation": {
            "ready": implementation_ready,
            "label": "Implementation assets ready" if implementation_ready else "Implementation assets require review",
            "ready_assets": ready_assets,
            "needs_review": needs_review_assets,
            "templates": template_assets,
        },
    }
    return {
        "score": score,
        "level": level,
        "effective_report": diagnostic_ready,
        "diagnostic_ready": diagnostic_ready,
        "measured_visibility": bool(confidence.get("sufficient")),
        "measurement_baseline_ready": bool(confidence.get("sufficient")),
        "implementation_ready": implementation_ready,
        "readiness": readiness,
        "confidence": confidence,
        "components": {
            "site_audit": {"score": audit_score, "max": 35, "pages_ok": pages_ok, "pages_crawled": pages_crawled},
            "measurement": {
                "score": sampling_score, "max": 35, "successful_samples": successful,
                "sampled_platforms": platform_count, "confidence": confidence.get("level", "unavailable"),
            },
            "playbook": {"score": playbook_score, "max": 20, "tickets": ticket_count},
            "delivery": {"score": delivery_score, "max": 10, "available": has_delivery},
        },
        "issues": issues,
        "measurement_quality": measurement_quality,
    }
