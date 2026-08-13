"""首份报告完整度和缺失项诊断。"""

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
    measurement = sampling_quality(project_slug)
    issues = []

    page_count = int(audit.get("page_count") or 0)
    site = audit.get("site") or {}
    pages_crawled = int(site.get("pages_crawled") or page_count or 0)
    pages_ok = int(site.get("pages_ok") or page_count or 0)
    crawl_ratio = pages_ok / pages_crawled if pages_crawled else 0
    audit_ratio = 0 if not page_count else max(0.2, min(1.0, crawl_ratio or 1.0))
    audit_score = round(35 * audit_ratio)
    if not page_count:
        issues.append(_issue("audit_missing", "critical", "Site-wide GEO audit pending", "Re-run site crawl and page audit", "automation"))
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

    current = measurement.get("current") or {}
    confidence = measurement.get("confidence") or {}
    successful = int(current.get("successful") or 0)
    platform_count = int(confidence.get("platform_count") or 0)
    sample_coverage = min(1.0, successful / MIN_COMPARABLE_SAMPLES) if metrics else 0
    platform_coverage = min(1.0, platform_count / MIN_REPRESENTATIVE_PLATFORMS) if metrics else 0
    sampling_ratio = sample_coverage * platform_coverage
    sampling_score = round(35 * sampling_ratio)
    if not has_sampling_access:
        issues.append(_issue(
            "api_key_missing", "warning", "API keys unconfigured; automated sampling and inference limited",
            "Configure at least one API key or import manual sampling sheet", "engine-settings",
        ))
    if not metrics:
        issues.append(_issue("sampling_missing", "critical", "AI visibility metrics pending", "Run AI answer sampling", "automation"))
    elif successful < MIN_COMPARABLE_SAMPLES:
        issues.append(_issue(
            "sampling_insufficient", "warning", f"Currently only {successful} valid samples",
            f"Collect at least {MIN_COMPARABLE_SAMPLES} valid samples before evaluating trends", "engines",
        ))
    if metrics and platform_count < MIN_REPRESENTATIVE_PLATFORMS:
        issues.append(_issue(
            "sampling_platforms_limited", "warning", f"Currently only {platform_count} sampled platform(s)",
            f"Sample at least {MIN_REPRESENTATIVE_PLATFORMS} representative platforms before making global conclusions",
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
        issues.append(_issue("playbook_missing", "warning", "Action tickets pending", "Generate action plan", "automation"))

    delivery_directory = directory / "delivery"
    has_delivery = delivery_directory.exists() and any(delivery_directory.iterdir())
    delivery_score = 10 if has_delivery else 0
    if not has_delivery:
        issues.append(_issue("delivery_missing", "info", "Client delivery pack pending", "Compile delivery pack after report review", "report"))

    score = audit_score + sampling_score + playbook_score + delivery_score
    if score >= 85:
        level = "complete"
    elif score >= 60:
        level = "usable"
    elif score > 0:
        level = "partial"
    else:
        level = "missing"
    return {
        "score": score,
        "level": level,
        "effective_report": score >= 60 and page_count > 0 and bool(metrics) and bool(confidence.get("sufficient")),
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
        "measurement_quality": measurement,
    }
