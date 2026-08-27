"""从现有站点审计与采样产物计算 AI 引用准备度。"""

from api.adapters.engine import geolib


def _dimension(key, label, score, evidence, status=None):
    score = None if score is None else max(0, min(100, int(round(score))))
    return {
        "key": key,
        "label": label,
        "score": score,
        "status": status or ("unmeasured" if score is None else "measured"),
        "evidence": evidence if isinstance(evidence, list) else [],
    }


def assess(project_slug):
    """只读聚合 `audit.json`，不触发爬取、写入或 LLM 调用。"""
    directory = geolib.project_dir(project_slug)
    audit = geolib.read_json(directory / "audit.json", {}) or {}
    if not audit:
        return {"status": "unmeasured", "score": None, "dimensions": [], "findings": []}

    site = audit.get("site") or {}
    public_audit = geolib.read_json(directory / "public_audit.json", {}) or {}
    pages = [item for item in (audit.get("pages") or []) if isinstance(item, dict)]
    crawled = int(site.get("pages_crawled") or audit.get("page_count") or len(pages) or 0)
    ok = int(site.get("pages_ok") or len(pages) or 0)
    crawl_score = (ok / crawled * 100) if crawled else None
    crawl_evidence = [{"source": "audit.json", "field": "site.pages_ok", "value": ok}, {"source": "audit.json", "field": "site.pages_crawled", "value": crawled}]
    if site.get("ai_bots_blocked"):
        crawl_score = min(crawl_score or 0, 20)
        crawl_evidence.append({"source": "audit.json", "field": "site.ai_bots_blocked", "value": True})

    evaluated = sum(int((p.get("check_summary") or {}).get("evaluated") or 0) for p in pages)
    passed = sum(int((p.get("check_summary") or {}).get("passed") or 0) for p in pages)
    extract_score = passed / evaluated * 100 if evaluated else None
    schema_hits = sum(1 for p in pages if (p.get("schema") or p.get("schema_markup") or p.get("structured_data")))
    answerable = sum(1 for p in pages if (p.get("title") or p.get("h1") or p.get("text")))
    consistency = audit.get("fact_consistency")
    crawler_checks = []
    for name, value, action in (
        ("robots", site.get("robots_accessible", site.get("robots_ok")), "Make /robots.txt publicly reachable"),
        ("ai_crawlers", not bool(site.get("ai_bots_blocked")), "Review AI crawler directives in robots.txt"),
        ("llms_txt", public_audit.get("llms_txt_ok"), "Publish a concise /llms.txt with canonical documentation links"),
    ):
        if value is None:
            status = "unmeasured"
        else:
            status = "pass" if value else "fail"
        crawler_checks.append({"name": name, "status": status, "action": None if status == "pass" else action, "evidence": [{"source": "audit.json" if name != "llms_txt" else "public_audit.json", "field": name, "value": value}]})
    dimensions = [
        _dimension("crawlability", "Crawlability", crawl_score, crawl_evidence),
        _dimension("extractability", "Extractability", extract_score, [{"source": "audit.json", "field": "pages.check_summary", "value": {"passed": passed, "evaluated": evaluated}}]),
        _dimension("answerability", "Answerability", answerable / len(pages) * 100 if pages else None, [{"source": "audit.json", "field": "pages", "value": len(pages)}]),
        _dimension("fact_consistency", "Fact consistency", float(consistency) * 100 if isinstance(consistency, (int, float)) and consistency <= 1 else consistency, [{"source": "audit.json", "field": "fact_consistency", "value": consistency}] if consistency is not None else [], status="unmeasured" if consistency is None else None),
        _dimension("citation_evidence", "Citation evidence", None, [{"source": "sampling", "field": "citation_rate", "value": None}], status="unmeasured"),
    ]
    measured = [item["score"] for item in dimensions if item["score"] is not None]
    findings = []
    for item in dimensions:
        if item["score"] is not None and item["score"] < 80:
            findings.append({"code": f"{item['key']}_limited", "dimension": item["key"], "severity": "warning", "message": f"{item['label']} needs improvement", "evidence": item["evidence"]})
    return {"status": "measured" if measured else "unmeasured", "score": round(sum(measured) / len(measured)) if measured else None, "dimensions": dimensions, "crawler_checks": crawler_checks, "findings": findings}
