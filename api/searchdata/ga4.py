"""Google Analytics 4 Admin / Data API：属性匹配与 28 天 AI 引荐流量。"""

import time
from datetime import date, timedelta

import requests

from api.searchdata.ai_sources import normalize_host


ADMIN_ROOT = "https://analyticsadmin.googleapis.com/v1beta"
DATA_ROOT = "https://analyticsdata.googleapis.com/v1beta"
WINDOW_DAYS = 28
# GA4 当天与前一天的数据仍可能修订，窗口结束日避开未定稿区间。
FINAL_LAG_DAYS = 1
PAGE_SIZE = 200
MAX_ACCOUNT_PAGES = 20
MAX_PROPERTY_SCAN = 40
SCAN_DEADLINE_SECONDS = 20
MAX_STREAM_PAGES = 5
REPORT_LIMIT = 1000
MAX_REPORT_PAGES = 5
MAX_KEY_EVENT_PAGES = 5
FALLBACK_CHOICES = 10
WEB_STREAM = "WEB_DATA_STREAM"
_TWO_LEVEL_SUFFIXES = frozenset((
    "co.uk", "org.uk", "ac.uk", "com.cn", "net.cn", "org.cn", "gov.cn",
    "co.jp", "ne.jp", "or.jp", "co.kr", "com.au", "net.au", "com.br",
    "co.in", "com.tw", "co.nz", "co.za",
))


class Ga4Error(RuntimeError):
    """携带稳定错误码，不包含 token。"""


def _request(method, url, token, timeout=30, **kwargs):
    try:
        response = requests.request(
            method, url, headers={"Authorization": f"Bearer {token}"},
            timeout=timeout, **kwargs,
        )
    except requests.RequestException as exc:
        raise Ga4Error("ga4_upstream_error") from exc
    if response.status_code in (401, 403):
        raise Ga4Error("ga4_permission_denied")
    if response.status_code == 429:
        raise Ga4Error("ga4_rate_limited")
    if not response.ok:
        raise Ga4Error("ga4_upstream_error")
    try:
        return response.json()
    except ValueError as exc:
        raise Ga4Error("ga4_upstream_error") from exc


def _pages(url, token, key, page_size, max_pages):
    page_token = None
    for _ in range(max_pages):
        params = {"pageSize": page_size}
        if page_token:
            params["pageToken"] = page_token
        payload = _request("GET", url, token, params=params)
        for item in payload.get(key) or []:
            if isinstance(item, dict):
                yield item
        page_token = payload.get("nextPageToken")
        if not page_token:
            return


def list_properties(token):
    """列出账号下所有普通 GA4 属性，按 property 去重。"""
    properties, seen = [], set()
    for account in _pages(
        f"{ADMIN_ROOT}/accountSummaries", token, "accountSummaries",
        PAGE_SIZE, MAX_ACCOUNT_PAGES,
    ):
        for item in account.get("propertySummaries") or []:
            if not isinstance(item, dict):
                continue
            property_id = str(item.get("property") or "")
            if not property_id or property_id in seen:
                continue
            if item.get("propertyType") not in (None, "", "PROPERTY_TYPE_ORDINARY"):
                continue
            seen.add(property_id)
            properties.append({
                "property": property_id,
                "display_name": str(item.get("displayName") or property_id),
                "account": str(item.get("parent") or account.get("account") or ""),
                "can_edit": bool(item.get("canEdit")),
            })
    return properties


def list_web_streams(token, property_id):
    """返回属性下可用的 web 流；空 defaultUri 与非 web 流一律跳过。"""
    streams = []
    for item in _pages(
        f"{ADMIN_ROOT}/{property_id}/dataStreams", token, "dataStreams",
        PAGE_SIZE, MAX_STREAM_PAGES,
    ):
        if item.get("type") != WEB_STREAM:
            continue
        uri = str((item.get("webStreamData") or {}).get("defaultUri") or "").strip()
        host = normalize_host(uri)
        if not host:
            continue
        streams.append({
            "stream_id": str(item.get("name") or ""),
            "display_name": str(item.get("displayName") or ""),
            "uri": uri,
            "host": host,
        })
    return streams


def list_key_events(token, property_id):
    events = []
    for item in _pages(
        f"{ADMIN_ROOT}/{property_id}/keyEvents", token, "keyEvents",
        PAGE_SIZE, MAX_KEY_EVENT_PAGES,
    ):
        if item.get("deletionTime"):
            continue
        name = str(item.get("eventName") or "").strip()
        if not name:
            continue
        events.append({
            "event_name": name,
            "counting_method": str(item.get("countingMethod") or ""),
        })
    return events


def key_events_status(token, property_id):
    """key events 配置只用于解释 0 值，读取失败不阻断主流程。"""
    try:
        events = list_key_events(token, property_id)
    except Ga4Error as exc:
        return {"status": "unavailable", "count": None, "error": str(exc)}
    return {
        "status": "ok" if events else "not_configured",
        "count": len(events),
        "error": None,
    }


def property_time_zone(token, property_id):
    try:
        payload = _request("GET", f"{ADMIN_ROOT}/{property_id}", token, timeout=10)
    except Ga4Error:
        return ""
    return str(payload.get("timeZone") or "")


def _parent_allowed(stream_host):
    labels = stream_host.split(".")
    if len(labels) < 2:
        return False
    if ".".join(labels[-2:]) in _TWO_LEVEL_SUFFIXES:
        return len(labels) >= 3
    return True


def _match_type(project_host, stream_host):
    if project_host == stream_host:
        return "exact"
    if project_host.endswith("." + stream_host) and _parent_allowed(stream_host):
        return "parent"
    return None


def _choice(item, stream, project_host, match_type):
    return {
        "property": item["property"],
        "display_name": item["display_name"],
        "stream_id": stream["stream_id"],
        "stream_uri": stream["uri"],
        "stream_host": stream["host"],
        "project_host": project_host,
        "match_type": match_type,
        "matched": match_type in ("exact", "parent"),
    }


def _property_rank(item, project_host):
    label = project_host.split(".")[0]
    name = str(item.get("display_name") or "").casefold()
    return (0 if label and label in name else 1, name, item["property"])


def match_properties(project_url, properties, token):
    """按 web stream 的 defaultUri 匹配项目域名；exact 可自动选中，parent 必须由用户确认。"""
    project_host = normalize_host(project_url)
    result = {
        "project_host": project_host or "",
        "matched": [],
        "offered": [],
        "properties_total": len(properties),
        "scanned": 0,
        "truncated": False,
        "lookup_errors": 0,
    }
    if not project_host or not properties:
        return result
    ordered = sorted(properties, key=lambda item: _property_rank(item, project_host))
    deadline = time.monotonic() + SCAN_DEADLINE_SECONDS
    fallback = []
    for item in ordered:
        if result["scanned"] >= MAX_PROPERTY_SCAN or time.monotonic() > deadline:
            result["truncated"] = True
            break
        result["scanned"] += 1
        try:
            streams = list_web_streams(token, item["property"])
        except Ga4Error:
            result["lookup_errors"] += 1
            continue
        best = None
        for stream in streams:
            kind = _match_type(project_host, stream["host"])
            if kind is None:
                continue
            score = (kind == "exact", stream["uri"].casefold().startswith("https://"))
            if best is None or score > best[0]:
                best = (score, stream, kind)
        if best is not None:
            result["matched"].append(_choice(item, best[1], project_host, best[2]))
        elif streams and len(fallback) < FALLBACK_CHOICES:
            fallback.append(_choice(item, streams[0], project_host, None))
    if result["scanned"] and result["lookup_errors"] == result["scanned"]:
        raise Ga4Error("ga4_permission_denied")
    result["matched"].sort(key=lambda choice: (
        choice["match_type"] != "exact", choice["display_name"].casefold(),
    ))
    result["offered"] = result["matched"] + fallback
    return result


def window(today=None):
    end = (today or date.today()) - timedelta(days=FINAL_LAG_DAYS)
    start = end - timedelta(days=WINDOW_DAYS - 1)
    return {"start": start.isoformat(), "end": end.isoformat(), "days": WINDOW_DAYS}


def _run_report(token, property_id, body):
    return _request(
        "POST", f"{DATA_ROOT}/{property_id}:runReport", token, json=body, timeout=60,
    )


def _metric_map(payload, row):
    names = [str(header.get("name") or "") for header in payload.get("metricHeaders") or []]
    values = row.get("metricValues") or []
    result = {}
    for index, name in enumerate(names):
        if index >= len(values):
            continue
        try:
            result[name] = int(float((values[index] or {}).get("value") or 0))
        except (TypeError, ValueError):
            result[name] = 0
    return result


def _dimension_value(row, index=0):
    values = row.get("dimensionValues") or []
    if index >= len(values):
        return ""
    return str((values[index] or {}).get("value") or "")


def fetch_ai_referrals(token, property_id, today=None):
    """按 sessionSource 拉全部来源，分类交给调用方；另拉一次全站总量作分母。"""
    date_range = window(today)
    base = {"dateRanges": [{"startDate": date_range["start"], "endDate": date_range["end"]}]}
    metrics = [{"name": "sessions"}, {"name": "totalUsers"}, {"name": "keyEvents"}]
    rows, offset, total_rows = [], 0, None
    for _ in range(MAX_REPORT_PAGES):
        payload = _run_report(token, property_id, {
            **base,
            "dimensions": [{"name": "sessionSource"}],
            "metrics": metrics,
            "limit": str(REPORT_LIMIT),
            "offset": str(offset),
            "orderBys": [
                {"metric": {"metricName": "sessions"}, "desc": True},
                {"dimension": {"dimensionName": "sessionSource"}},
            ],
        })
        page = payload.get("rows") or []
        if total_rows is None:
            total_rows = int(payload.get("rowCount") or 0)
        for row in page:
            if not isinstance(row, dict):
                continue
            values = _metric_map(payload, row)
            rows.append({
                "source": _dimension_value(row),
                "sessions": int(values.get("sessions") or 0),
                "total_users": int(values.get("totalUsers") or 0),
                "key_events": int(values.get("keyEvents") or 0),
            })
        offset += len(page)
        if not page:
            break
        if total_rows is not None and offset >= total_rows:
            break
        if total_rows is None and len(page) < REPORT_LIMIT:
            break
    truncated = (offset < total_rows) if total_rows is not None else (len(page) >= REPORT_LIMIT)
    totals_payload = _run_report(token, property_id, {**base, "metrics": metrics})
    totals_rows = totals_payload.get("rows") or []
    totals = _metric_map(totals_payload, totals_rows[0]) if totals_rows else {}
    return {
        "window": date_range,
        "rows": rows,
        "site_totals": {
            "sessions": int(totals.get("sessions") or 0),
            "total_users": int(totals.get("totalUsers") or 0),
            "key_events": int(totals.get("keyEvents") or 0),
        },
        "source_rows": len(rows),
        "truncated": truncated,
    }
