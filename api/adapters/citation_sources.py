"""从租户样本 JSONL 聚合可追溯的联网引用来源。"""
import json
import re
import time
import logging
from datetime import datetime, timezone
from urllib.parse import urlparse

from api.adapters.engine import geolib
from api import config

logger = logging.getLogger(__name__)

_TYPE_HINTS = (("wikipedia", "knowledge"), ("wikidata", "knowledge"), ("reddit", "community"), ("quora", "community"), ("review", "review"))
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
MAX_BYTES = 32 * 1024 * 1024
MAX_LINES = 100_000

def _domain(url):
    try:
        host = (urlparse(str(url)).hostname or "").lower().removeprefix("www.")
        return host if host and re.fullmatch(r"[a-z0-9.-]+", host) else ""
    except ValueError:
        return ""

def _kind(domain):
    for hint, value in _TYPE_HINTS:
        if hint in domain:
            return value
    return "editorial"

def _url_key(url):
    try:
        parsed = urlparse(str(url))
        domain = (parsed.hostname or "").lower().removeprefix("www.")
        port = f":{parsed.port}" if parsed.port and parsed.port not in (80, 443) else ""
        return f"{domain}{port}{parsed.path or '/'}?{parsed.query}".rstrip("?")
    except ValueError:
        return str(url).lower()

def _urls(row):
    values = []
    for key in ("citations", "sources", "references"):
        value = row.get(key)
        if isinstance(value, list):
            values.extend(value)
    out = []
    for value in values:
        url = value.get("url") if isinstance(value, dict) else value
        if isinstance(url, str) and url.startswith(("http://", "https://")):
            out.append(url)
    return out

def _complete(path, rows):
    if not rows or any(isinstance(r, dict) and str(r.get("status", "")).lower() in ("running", "started") for r in rows):
        return False
    return any(isinstance(r, dict) and (r.get("terminal") is True or str(r.get("status", "")).lower() in ("succeeded", "completed", "success", "done")) for r in rows) or any(isinstance(r, dict) and r.get("ok") is not None for r in rows)

def shadow_diff(rows, domains):
    """比较旧 Channels 域名计数与新 URL 聚合结果。"""
    legacy = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("ok") is not True: continue
        for domain in (row.get("analysis") or {}).get("cited_domains") or []:
            normalized = _domain("https://" + str(domain).lstrip("/"))
            if normalized: legacy[normalized] = legacy.get(normalized, 0) + 1
    current = {item["domain"]: item["count"] for item in domains}
    return {"legacy": legacy, "current": current} if legacy != current else None

def aggregate(project_slug):
    directory = geolib.project_dir(project_slug)
    candidates = sorted((directory / "samples").glob("*.jsonl"), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    warnings = []
    selected = None
    rows = []
    for path in candidates[:2]:
        try:
            if not _RUN_ID.fullmatch(path.stem):
                warnings.append(f"invalid_run_id:{path.name}")
                continue
            before = (path.stat().st_ino, path.stat().st_size, path.stat().st_mtime_ns)
            if time.time() - path.stat().st_mtime < 2:
                continue
            if before[1] > MAX_BYTES:
                warnings.append(f"run_too_large:{path.name}")
                continue
            parsed = []
            for line_no, line in enumerate(path.read_text("utf-8", errors="replace").splitlines(), 1):
                if line_no > MAX_LINES:
                    warnings.append(f"run_line_limit:{path.name}")
                    break
                if not line.strip(): continue
                try: parsed.append(json.loads(line))
                except json.JSONDecodeError: warnings.append(f"invalid_json:{path.name}")
            after = (path.stat().st_ino, path.stat().st_size, path.stat().st_mtime_ns)
            if before != after or not _complete(path, parsed): continue
            selected, rows = path, parsed
            break
        except OSError:
            continue
    domains = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("ok") is not True or row.get("search_enabled") is not True:
            continue
        citations = row.get("citations")
        if not isinstance(citations, list): continue
        for raw in _urls(row):
            domain = _domain(raw)
            if not domain: continue
            item = domains.setdefault(domain, {"domain": domain, "type": _kind(domain), "count": 0, "evidence_urls": [], "_seen": set()})
            key = _url_key(raw)
            if key in item["_seen"]: continue
            item["_seen"].add(key); item["count"] += 1
            if len(item["evidence_urls"]) < 3: item["evidence_urls"].append(raw)
    total = sum(item["count"] for item in domains.values())
    if not selected or not total:
        return {"status": "unmeasured", "run_id": selected.stem if selected else None, "sampled_at": datetime.fromtimestamp(selected.stat().st_mtime, timezone.utc).isoformat() if selected else None, "total_citations": total, "domains": [], "warnings": warnings, "unmeasured_reason": "no_valid_citations" if selected else "no_complete_run"}
    result = []
    for item in sorted(domains.values(), key=lambda x: (-x["count"], x["domain"])):
        item.pop("_seen", None); item["share"] = item["count"] / total; item["evidence_count"] = len(item["evidence_urls"]); result.append(item)
    diff = shadow_diff(rows, result) if config.citation_shadow_enabled() else None
    if diff:
        warnings.append("shadow_mismatch")
        logger.warning("citation shadow mismatch for %s run %s: %s", project_slug, selected.stem, diff)
    return {"status": "measured", "run_id": selected.stem, "sampled_at": datetime.fromtimestamp(selected.stat().st_mtime, timezone.utc).isoformat(), "total_citations": total, "domains": result, "warnings": warnings, "unmeasured_reason": None}
