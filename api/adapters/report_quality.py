"""首份报告完整度和缺失项诊断。"""

from api.adapters.engine import geolib
from api.adapters.measurement import MIN_COMPARABLE_SAMPLES, sampling_quality


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
        issues.append(_issue("audit_missing", "critical", "尚未形成站点审计", "重新运行抓取站点和页面体检", "automation"))
    elif crawl_ratio < 0.8:
        issues.append(_issue(
            "crawl_limited", "warning", f"仅 {pages_ok}/{pages_crawled} 个页面可访问",
            "检查 WAF、限流、登录墙和 robots.txt 后重新抓取", "siteaudit",
        ))
    if site.get("ai_bots_blocked"):
        issues.append(_issue(
            "ai_bots_blocked", "critical", "robots.txt 正在禁止部分 AI 抓取器",
            "移除整站 Disallow，仅保留后台和敏感路径限制", "siteaudit",
        ))

    current = measurement.get("current") or {}
    successful = int(current.get("successful") or 0)
    sampling_ratio = min(1.0, successful / MIN_COMPARABLE_SAMPLES) if metrics else 0
    sampling_score = round(35 * sampling_ratio)
    if not has_sampling_access:
        issues.append(_issue(
            "api_key_missing", "warning", "未配置 API Key，自动采样和 AI 推导能力受限",
            "配置至少一个 API Key，或导入人工产品端采样表", "engine-settings",
        ))
    if not metrics:
        issues.append(_issue("sampling_missing", "critical", "尚未形成 AI 可见性指标", "运行一次答案采样", "automation"))
    elif successful < MIN_COMPARABLE_SAMPLES:
        issues.append(_issue(
            "sampling_insufficient", "warning", f"当前只有 {successful} 条有效样本",
            f"把有效样本补到至少 {MIN_COMPARABLE_SAMPLES} 条，再判断趋势", "engines",
        ))
    if current.get("failure_rate") is not None and current["failure_rate"] > 0.2:
        issues.append(_issue(
            "sampling_failure_high", "warning", f"采样失败率为 {current['failure_rate']:.0%}",
            "测试对应 API Key，并检查供应商限流或余额", "engine-settings",
        ))

    ticket_count = len(tasks.get("tasks", [])) if isinstance(tasks.get("tasks"), list) else 0
    playbook_score = 20 if ticket_count else 0
    if not ticket_count:
        issues.append(_issue("playbook_missing", "warning", "尚未生成可执行工单", "生成行动计划", "automation"))

    delivery_directory = directory / "delivery"
    has_delivery = delivery_directory.exists() and any(delivery_directory.iterdir())
    delivery_score = 10 if has_delivery else 0
    if not has_delivery:
        issues.append(_issue("delivery_missing", "info", "尚未生成客户交付包", "报告确认后生成交付包", "report"))

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
        "effective_report": score >= 60 and page_count > 0 and bool(metrics),
        "components": {
            "site_audit": {"score": audit_score, "max": 35, "pages_ok": pages_ok, "pages_crawled": pages_crawled},
            "measurement": {"score": sampling_score, "max": 35, "successful_samples": successful},
            "playbook": {"score": playbook_score, "max": 20, "tickets": ticket_count},
            "delivery": {"score": delivery_score, "max": 10, "available": has_delivery},
        },
        "issues": issues,
        "measurement_quality": measurement,
    }
