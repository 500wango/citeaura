"""Search Console 属性匹配与 90 天查询拉取。"""

from datetime import date, timedelta
from urllib.parse import quote, urlparse

import requests


API_ROOT = "https://searchconsole.googleapis.com/webmasters/v3"
WINDOW_DAYS = 90
# Search Console 最近 2–3 天的数据仍可能修订，结束日避开未定稿区间。
FINAL_LAG_DAYS = 3
ROW_LIMIT = 25000
UNVERIFIED = "siteUnverifiedUser"


class GscError(RuntimeError):
    """携带稳定错误码，不包含 token。"""


def _host(url):
    return (urlparse(str(url or "")).hostname or "").lower().removeprefix("www.")


def _request(method, path, token, **kwargs):
    try:
        response = requests.request(
            method, f"{API_ROOT}{path}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30, **kwargs,
        )
    except requests.RequestException as exc:
        raise GscError("gsc_upstream_error") from exc
    if response.status_code in (401, 403):
        raise GscError("gsc_permission_denied")
    if response.status_code == 429:
        raise GscError("gsc_rate_limited")
    if not response.ok:
        raise GscError("gsc_upstream_error")
    try:
        return response.json()
    except ValueError as exc:
        raise GscError("gsc_upstream_error") from exc


def list_sites(token):
    payload = _request("GET", "/sites", token)
    return [
        {"site_url": item["siteUrl"], "permission": item.get("permissionLevel") or ""}
        for item in (payload.get("siteEntry") or [])
        if isinstance(item, dict) and item.get("siteUrl") and item.get("permissionLevel") != UNVERIFIED
    ]


def _site_host(site_url):
    if site_url.startswith("sc-domain:"):
        return site_url.split(":", 1)[1].lower().removeprefix("www.")
    return _host(site_url)


def match_sites(project_url, sites):
    """返回与项目域名相关的属性，按 domain → https → https://www → http 排序。"""
    host = _host(project_url)
    if not host:
        return []
    order = [
        f"sc-domain:{host}",
        f"https://{host}/",
        f"https://www.{host}/",
        f"http://{host}/",
        f"http://www.{host}/",
    ]
    rank = {value: index for index, value in enumerate(order)}
    related = [item for item in sites if _site_host(item["site_url"]) == host]
    return sorted(related, key=lambda item: (rank.get(item["site_url"].lower(), len(order)), item["site_url"]))


def window(today=None):
    end = (today or date.today()) - timedelta(days=FINAL_LAG_DAYS)
    start = end - timedelta(days=WINDOW_DAYS - 1)
    return start.isoformat(), end.isoformat()


def _query(token, site_url, body):
    return _request(
        "POST", f"/sites/{quote(site_url, safe='')}/searchAnalytics/query", token, json=body,
    )


def fetch_queries(token, site_url, today=None):
    """一次单维度查询 + 一次总量查询；返回原始行和总量。"""
    start, end = window(today)
    base = {"startDate": start, "endDate": end, "type": "web", "dataState": "final"}
    rows = _query(token, site_url, {**base, "dimensions": ["query"], "rowLimit": ROW_LIMIT}).get("rows") or []
    totals_rows = _query(token, site_url, base).get("rows") or []
    totals = totals_rows[0] if totals_rows else {}
    return {
        "window": {"start": start, "end": end},
        "rows": [
            {
                "query": str((row.get("keys") or [""])[0]),
                "clicks": int(row.get("clicks") or 0),
                "impressions": int(row.get("impressions") or 0),
                "position": round(float(row.get("position") or 0), 1),
            }
            for row in rows
            if isinstance(row, dict) and (row.get("keys") or [""])[0]
        ],
        "totals": {
            "clicks": int(totals.get("clicks") or 0),
            "impressions": int(totals.get("impressions") or 0),
        },
    }
