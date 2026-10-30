"""GA4 AI 引荐快照：把 runReport 行按引擎聚合，并生成给前端的摘要。"""

from datetime import datetime, timezone

from api.searchdata import ai_sources, snapshot_store


SNAPSHOT_FILE = "ga4_snapshot.json"
SCHEMA_VERSION = 1
SOURCE_LABEL = "GA4·第一方"
NOTES = (
    "ga4_reporting_delay",
    "referrer_loss_direct",
    "medium_not_filtered",
    "users_not_deduplicated",
)


def _share(value, total):
    if not total or total <= 0:
        return None
    return round(max(0.0, min(1.0, float(value) / float(total))), 4)


def build_snapshot(choice, fetched, key_event_status, property_meta=None, now=None):
    property_meta = property_meta or {}
    site_totals = fetched.get("site_totals") or {}
    site_sessions = int(site_totals.get("sessions") or 0)
    site_key_events = int(site_totals.get("key_events") or 0)

    by_source = {}
    recognized_rows = 0
    for row in fetched.get("rows") or []:
        matched = ai_sources.classify((row or {}).get("source"))
        if matched is None:
            continue
        recognized_rows += 1
        key = (matched["source"], matched["engine_code"], matched["engine_name"])
        current = by_source.setdefault(key, {"sessions": 0, "total_users": 0, "key_events": 0})
        current["sessions"] += int(row.get("sessions") or 0)
        current["total_users"] += int(row.get("total_users") or 0)
        current["key_events"] += int(row.get("key_events") or 0)

    source_items = []
    engines = {}
    for (source, engine_code, engine_name), totals in by_source.items():
        source_items.append({
            "source": source,
            "engine_code": engine_code,
            "engine_name": engine_name,
            "sessions": totals["sessions"],
            "total_users": totals["total_users"],
            "key_events": totals["key_events"],
        })
        engine = engines.setdefault(engine_code, {
            "engine_code": engine_code,
            "engine_name": engine_name,
            "sessions": 0,
            "key_events": 0,
            "user_values": [],
            "sources": [],
        })
        engine["sessions"] += totals["sessions"]
        engine["key_events"] += totals["key_events"]
        engine["user_values"].append(totals["total_users"])
        engine["sources"].append(source)

    source_items.sort(key=lambda item: (-item["sessions"], item["source"]))
    engine_items = []
    for engine in engines.values():
        # 同一用户可能从多个来源进入，跨来源相加会重复计数。
        users = engine["user_values"][0] if len(engine["user_values"]) == 1 else None
        engine_items.append({
            "engine_code": engine["engine_code"],
            "engine_name": engine["engine_name"],
            "sessions": engine["sessions"],
            "total_users": users,
            "key_events": engine["key_events"],
            "share_of_sessions": _share(engine["sessions"], site_sessions),
            "sources": sorted(engine["sources"]),
        })
    engine_items.sort(key=lambda item: (-item["sessions"], item["engine_code"]))

    ai_sessions = sum(item["sessions"] for item in source_items)
    ai_key_events = sum(item["key_events"] for item in source_items)
    source_rows = int(fetched.get("source_rows") or len(fetched.get("rows") or []))
    return {
        "schema_version": SCHEMA_VERSION,
        "source": "google_analytics_4",
        "property": choice["property"],
        "property_display_name": choice["display_name"],
        "stream_id": choice["stream_id"],
        "stream_uri": choice["stream_uri"],
        "match": choice["match_type"],
        "project_host": choice["project_host"],
        "stream_host": choice["stream_host"],
        "time_zone": property_meta.get("time_zone") or "",
        "window": fetched["window"],
        "fetched_at": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
        "ai_sources_version": ai_sources.TABLE_VERSION,
        "ai_sources": source_items,
        "engines": engine_items,
        "site_totals": {
            "sessions": site_sessions,
            "total_users": int(site_totals.get("total_users") or 0),
            "key_events": site_key_events,
        },
        "ai_totals": {
            "sessions": ai_sessions,
            "total_users": None,
            "total_users_note": "not_deduplicated",
            "key_events": ai_key_events,
            "share_of_sessions": _share(ai_sessions, site_sessions),
            "share_of_key_events": _share(ai_key_events, site_key_events),
        },
        "key_events": key_event_status or {"status": "unavailable", "count": None, "error": None},
        "coverage": {
            "source_rows": source_rows,
            "recognized_rows": recognized_rows,
            "unrecognized_rows": max(0, source_rows - recognized_rows),
            "truncated": bool(fetched.get("truncated")),
        },
        "no_ai_traffic": ai_sessions == 0,
        "notes": list(NOTES),
    }


def read_snapshot(project_slug):
    return snapshot_store.read(project_slug, SNAPSHOT_FILE, SCHEMA_VERSION)


def write_snapshot(project_slug, snapshot):
    return snapshot_store.write(project_slug, SNAPSHOT_FILE, snapshot)


def delete_snapshot(project_slug):
    return snapshot_store.delete(project_slug, SNAPSHOT_FILE)


def summary(snapshot, configured=True):
    current_version = ai_sources.TABLE_VERSION
    if not snapshot:
        return {
            "status": "not_connected",
            "configured": configured,
            "source_label": SOURCE_LABEL,
            "ai_sources_version_current": current_version,
        }
    return {
        "status": "ready",
        "configured": configured,
        "source_label": SOURCE_LABEL,
        "property": snapshot["property"],
        "property_display_name": snapshot["property_display_name"],
        "stream_uri": snapshot["stream_uri"],
        "match": snapshot["match"],
        "time_zone": snapshot.get("time_zone") or "",
        "window": snapshot["window"],
        "fetched_at": snapshot["fetched_at"],
        "ai_sources_version": snapshot["ai_sources_version"],
        "ai_sources_version_current": current_version,
        "ai_sources_version_stale": snapshot["ai_sources_version"] != current_version,
        "site_totals": snapshot["site_totals"],
        "ai_totals": snapshot["ai_totals"],
        "engines": snapshot["engines"],
        "key_events": snapshot["key_events"],
        "coverage": snapshot["coverage"],
        "no_ai_traffic": snapshot["no_ai_traffic"],
        "notes": snapshot["notes"],
    }
