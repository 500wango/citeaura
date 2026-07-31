"""Semrush 与 Google Search Console 数据适配。"""

import csv
import io
import json
import re
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote, urlencode, urlparse

import requests

from api import config
from api.adapters.engine import geolib


SEMRUSH_ENDPOINT = "https://api.semrush.com/"
GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_SEARCH_CONSOLE_ENDPOINT = "https://searchconsole.googleapis.com/webmasters/v3"
GOOGLE_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
PROVIDERS = frozenset(("semrush", "search_console"))


class IntegrationError(RuntimeError):
    pass


def google_redirect_uri():
    return f"{config.public_base_url()}/api/v1/integrations/search-console/callback"


def google_authorization_url(state):
    client_id = config.google_oauth_client_id()
    if not client_id:
        raise IntegrationError("google_oauth_not_configured")
    return GOOGLE_AUTH_ENDPOINT + "?" + urlencode({
        "client_id": client_id,
        "redirect_uri": google_redirect_uri(),
        "response_type": "code",
        "scope": GOOGLE_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    })


def exchange_google_code(code):
    client_id = config.google_oauth_client_id()
    client_secret = config.google_oauth_client_secret()
    if not client_id or not client_secret:
        raise IntegrationError("google_oauth_not_configured")
    try:
        response = requests.post(
            GOOGLE_TOKEN_ENDPOINT,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": google_redirect_uri(),
            },
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise IntegrationError("google_oauth_exchange_failed") from exc
    if not payload.get("access_token"):
        raise IntegrationError("google_oauth_exchange_failed")
    return payload


def refresh_google_access_token(refresh_token):
    try:
        response = requests.post(
            GOOGLE_TOKEN_ENDPOINT,
            data={
                "client_id": config.google_oauth_client_id(),
                "client_secret": config.google_oauth_client_secret(),
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise IntegrationError("search_console_token_refresh_failed") from exc
    if not payload.get("access_token"):
        raise IntegrationError("search_console_token_refresh_failed")
    return payload["access_token"]


def search_console_sites(access_token):
    try:
        response = requests.get(
            f"{GOOGLE_SEARCH_CONSOLE_ENDPOINT}/sites",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise IntegrationError("search_console_sites_failed") from exc
    return [item for item in payload.get("siteEntry", []) if item.get("siteUrl")]


def select_search_console_property(project_url, sites):
    hostname = (urlparse(project_url).hostname or "").lower().removeprefix("www.")
    domain_property = f"sc-domain:{hostname}"
    for item in sites:
        if (
            item.get("siteUrl", "").lower() == domain_property
            and item.get("permissionLevel") != "siteUnverifiedUser"
        ):
            return item["siteUrl"]
    candidates = []
    for item in sites:
        site_url = item.get("siteUrl", "")
        parsed = urlparse(site_url)
        site_host = (parsed.hostname or "").lower().removeprefix("www.")
        if site_host == hostname and item.get("permissionLevel") != "siteUnverifiedUser":
            candidates.append(site_url)
    return sorted(candidates, key=len)[0] if candidates else None


def _number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def sync_semrush(project_url, api_key, database="us", limit=100):
    domain = (urlparse(project_url).hostname or "").lower().removeprefix("www.")
    if not domain:
        raise IntegrationError("project_domain_invalid")
    try:
        response = requests.get(
            SEMRUSH_ENDPOINT,
            params={
                "type": "domain_organic",
                "key": api_key,
                "domain": domain,
                "database": database,
                "display_limit": max(1, min(int(limit), 10000)),
                "export_columns": "Ph,Po,Nq,Cp,Ur,Tr,Tc,Co,Nr,Td",
            },
            timeout=30,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise IntegrationError("semrush_request_failed") from exc
    body = response.text.strip()
    if not body or body.startswith("ERROR"):
        raise IntegrationError("semrush_api_error")
    rows = []
    try:
        for row in csv.DictReader(io.StringIO(body), delimiter=";"):
            rows.append({
                "keyword": row.get("Keyword", ""),
                "position": int(_number(row.get("Position"))),
                "search_volume": int(_number(row.get("Search Volume"))),
                "cpc": round(_number(row.get("CPC")), 4),
                "url": row.get("Url", ""),
                "traffic_percent": round(_number(row.get("Traffic (%)")), 4),
                "traffic_cost": round(_number(row.get("Traffic Cost")), 4),
                "competition": round(_number(row.get("Competition")), 4),
                "results": int(_number(row.get("Number of Results"))),
                "trend": row.get("Trends", ""),
            })
    except (TypeError, ValueError) as exc:
        raise IntegrationError("semrush_response_invalid") from exc
    return {
        "provider": "semrush",
        "source": "Semrush API",
        "domain": domain,
        "database": database,
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "metrics": {
            "keywords_returned": len(rows),
            "top_10_keywords": sum(1 for row in rows if 0 < row["position"] <= 10),
            "search_volume": sum(row["search_volume"] for row in rows),
            "traffic_cost": round(sum(row["traffic_cost"] for row in rows), 2),
        },
        "rows": rows,
    }


def sync_search_console(project_url, refresh_token, property_url=None, days=28):
    access_token = refresh_google_access_token(refresh_token)
    sites = search_console_sites(access_token)
    selected = property_url or select_search_console_property(project_url, sites)
    if not selected or selected not in {item["siteUrl"] for item in sites}:
        raise IntegrationError("search_console_property_not_found")
    end_date = date.today() - timedelta(days=1)
    start_date = end_date - timedelta(days=max(1, min(int(days), 90)) - 1)
    try:
        response = requests.post(
            f"{GOOGLE_SEARCH_CONSOLE_ENDPOINT}/sites/{quote(selected, safe='')}/searchAnalytics/query",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "startDate": start_date.isoformat(),
                "endDate": end_date.isoformat(),
                "dimensions": ["query", "page"],
                "rowLimit": 25000,
                "dataState": "final",
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise IntegrationError("search_console_query_failed") from exc
    rows = []
    for row in payload.get("rows", []):
        keys = row.get("keys") or []
        rows.append({
            "query": str(keys[0]) if keys else "",
            "page": str(keys[1]) if len(keys) > 1 else "",
            "clicks": _number(row.get("clicks")),
            "impressions": _number(row.get("impressions")),
            "ctr": _number(row.get("ctr")),
            "position": _number(row.get("position")),
        })
    impressions = sum(row["impressions"] for row in rows)
    return {
        "provider": "search_console",
        "source": "Google Search Console API",
        "property_url": selected,
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "period": {"start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
        "metrics": {
            "clicks": round(sum(row["clicks"] for row in rows), 2),
            "impressions": round(impressions, 2),
            "ctr": round(sum(row["clicks"] for row in rows) / impressions, 6) if impressions else 0,
            "average_position": round(
                sum(row["position"] * row["impressions"] for row in rows) / impressions,
                2,
            ) if impressions else None,
            "rows": len(rows),
        },
        "rows": rows,
    }


def save_snapshot(project_slug, provider, snapshot):
    if provider not in PROVIDERS:
        raise ValueError("unsupported integration provider")
    directory = geolib.project_dir(project_slug) / "integrations" / provider
    stamp = re.sub(r"[^0-9]", "", snapshot["synced_at"])[:14]
    with geolib.project_lock(project_slug):
        geolib.write_json(directory / f"{stamp}.json", snapshot)
        geolib.write_json(directory / "latest.json", snapshot)
    return snapshot


def latest_snapshot(project_slug, provider):
    if provider not in PROVIDERS:
        raise ValueError("unsupported integration provider")
    return geolib.read_json(
        geolib.project_dir(project_slug) / "integrations" / provider / "latest.json",
        None,
    )


def credential_config(row):
    try:
        value = json.loads(row.config_json or "{}")
    except (TypeError, ValueError):
        value = {}
    return value if isinstance(value, dict) else {}
