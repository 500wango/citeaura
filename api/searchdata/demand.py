"""报告中的“真实需求”一节：GSC 来源问题与最近一次 AI 采样并列。"""

from collections import Counter

from api.adapters import sampling_modes
from api.adapters.engine import geolib
from api.projects import reporting
from api.searchdata import candidates


def _gsc_questions(config):
    return [
        item for item in config.get("questions") or []
        if isinstance(item, dict) and item.get("source") == "gsc" and isinstance(item.get("gsc"), dict)
    ]


def _engine_rows(question_id, rows, config):
    by_platform = {}
    for row in rows:
        if str(row.get("question_id") or "") != question_id or row.get("ok") is not True:
            continue
        by_platform.setdefault(str(row.get("platform") or ""), []).append(row)
    engines = []
    for code, platform_rows in sorted(by_platform.items()):
        identity = reporting.provider_identity(code, {}, config)
        mentions = sum(1 for row in platform_rows if (row.get("analysis") or {}).get("brand_mentioned"))
        competitors = Counter(
            name
            for row in platform_rows
            for name in (row.get("analysis") or {}).get("competitors_mentioned") or []
        )
        engines.append({
            "engine_code": code,
            "engine_name": identity["provider_name"],
            "model_id": identity["model_id"],
            **sampling_modes.fields(row=platform_rows[0]),
            "samples": len(platform_rows),
            "mentions": mentions,
            "mentioned": mentions > 0,
            "competitors": [name for name, _ in competitors.most_common(5)],
            "sampled_at": max(str(row.get("ts") or "") for row in platform_rows) or None,
        })
    return engines


def build(project_slug):
    config = geolib.load_config(project_slug)
    snapshot = candidates.read_snapshot(project_slug)
    questions = _gsc_questions(config)
    if not questions:
        return {"status": "no_gsc_questions", "items": [], "snapshot": None}
    sample_path, rows = reporting.current_sample_rows(project_slug, config)
    items = []
    for question in sorted(questions, key=lambda item: -int(item["gsc"].get("impressions") or 0)):
        engines = _engine_rows(str(question.get("id")), rows, config)
        items.append({
            "question_id": question.get("id"),
            "text": question.get("text"),
            "google": {
                "source_label": "GSC·第一方",
                "query": question["gsc"].get("query"),
                "impressions": question["gsc"].get("impressions"),
                "clicks": question["gsc"].get("clicks"),
                "position": question["gsc"].get("position"),
                "property": question["gsc"].get("property"),
                "window": question["gsc"].get("window"),
                "fetched_at": question["gsc"].get("fetched_at"),
            },
            "measured": bool(engines),
            "mentioned_by_any_engine": any(engine["mentioned"] for engine in engines),
            "engines": engines,
        })
    measured = [item for item in items if item["measured"]]
    return {
        "status": "measured" if measured else "awaiting_sample",
        "summary": {
            "questions": len(items),
            "measured": len(measured),
            "mentioned": sum(1 for item in measured if item["mentioned_by_any_engine"]),
        },
        "sample_run": sample_path.name if sample_path and measured else None,
        "snapshot": {
            "property": snapshot["property"],
            "window": snapshot["window"],
            "fetched_at": snapshot["fetched_at"],
            "anonymous_click_share": snapshot["anonymous_click_share"],
        } if snapshot else None,
        "note": "Google figures come from Search Console; AI results come from labeled API sampling. Neither is part of the GEO health score.",
        "items": items,
    }
