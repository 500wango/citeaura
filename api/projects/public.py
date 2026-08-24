"""Public, unauthenticated delivery links and low-cost audit entry points."""

from collections import OrderedDict
import hashlib
import json
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from api.adapters import delivery, delivery_share
from api.adapters.engine import geolib, with_tenant_context
from api.adapters.exceptions import GeoEngineError
from api.adapters import preflight
from api.db import get_db
from api.models import Project, PublicAudit, Tenant
from api.product_events import record_product_event
from api.projects.router import _delivery_package_kind, _stream_delivery_zip


router = APIRouter(prefix="/api/v1/public", tags=["public"])


class PublicAuditRequest(BaseModel):
    """匿名审计只接受公开的站点根 URL，不接受查询参数或凭据。"""

    url: str = Field(min_length=1, max_length=2048)

    @field_validator("url")
    @classmethod
    def normalize_url(cls, value: str):
        return preflight.normalize_url(value)


_AUDIT_CACHE: "OrderedDict[str, tuple[float, dict]]" = OrderedDict()
_AUDIT_CACHE_LOCK = threading.Lock()
_AUDIT_CACHE_TTL = 15 * 60
_AUDIT_CACHE_LIMIT = 256
_AUDIT_WINDOW = 60 * 60
_AUDIT_MAX_PER_WINDOW = 3
_AUDIT_REQUESTS: dict[str, list[float]] = {}


def _client_key(request: Request) -> str:
    value = str(request.client.host if request.client else "unknown")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _allow_public_audit(request: Request) -> bool:
    now = time.time()
    key = _client_key(request)
    with _AUDIT_CACHE_LOCK:
        recent = [value for value in _AUDIT_REQUESTS.get(key, []) if value > now - _AUDIT_WINDOW]
        if len(recent) >= _AUDIT_MAX_PER_WINDOW:
            _AUDIT_REQUESTS[key] = recent
            return False
        recent.append(now)
        _AUDIT_REQUESTS[key] = recent
        if len(_AUDIT_REQUESTS) > 2048:
            oldest = min(_AUDIT_REQUESTS, key=lambda item: _AUDIT_REQUESTS[item][-1])
            _AUDIT_REQUESTS.pop(oldest, None)
    return True


def _cached_audit(url: str):
    now = time.time()
    with _AUDIT_CACHE_LOCK:
        item = _AUDIT_CACHE.get(url)
        if item and item[0] > now:
            _AUDIT_CACHE.move_to_end(url)
            return item[1]
        if item:
            _AUDIT_CACHE.pop(url, None)
    return None


def _cache_audit(url: str, result: dict):
    with _AUDIT_CACHE_LOCK:
        _AUDIT_CACHE[url] = (time.time() + _AUDIT_CACHE_TTL, result)
        _AUDIT_CACHE.move_to_end(url)
        while len(_AUDIT_CACHE) > _AUDIT_CACHE_LIMIT:
            _AUDIT_CACHE.popitem(last=False)


def _persist_audit(db, result, request):
    """Create a handoff record for one public audit response."""
    audit_id = uuid.uuid4().hex
    payload = {**result, "audit_id": audit_id}
    db.add(PublicAudit(
        audit_id=audit_id,
        url=result["url"],
        anonymous_id=_client_key(request),
        result_json=json.dumps(payload, ensure_ascii=False, sort_keys=True),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    ))
    return payload


def _machine_signal(root: str, path: str, label: str) -> dict:
    """Fetch only bounded machine-file text and never return its contents."""
    url = root.rstrip("/") + path
    try:
        body = geolib.fetch_text(url, timeout=5, allow_machine_file=True)
        return {
            "key": label,
            "path": path,
            "present": bool(body),
            "status": 200 if body else 0,
            "_body": body,
        }
    except (OSError, ValueError, GeoEngineError) as exc:
        return {"key": label, "path": path, "present": False, "status": 0, "error": type(exc).__name__}


def _robots_blocked(root: str, text: str | None = None) -> list[str]:
    try:
        text = text if text is not None else geolib.fetch_text(root.rstrip("/") + "/robots.txt", timeout=5, allow_machine_file=True)
    except (OSError, ValueError, GeoEngineError):
        return []
    try:
        from crawl import robots_disallows_root
    except ImportError:
        return []
    bots = ("GPTBot", "OAI-SearchBot", "ClaudeBot", "PerplexityBot", "Bytespider", "Google-Extended")
    return [bot for bot in bots if robots_disallows_root(text, bot)]


@router.post("/audit")
def public_audit(payload: PublicAuditRequest, request: Request, db: Session = Depends(get_db)):
    """返回不调用模型的匿名站点诊断摘要，作为首次价值入口。"""
    if not _allow_public_audit(request):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"error": "public_audit_rate_limited", "detail": "Try again later or create a workspace for a full audit."},
            headers={"Retry-After": str(_AUDIT_WINDOW)},
        )
    cached = _cached_audit(payload.url)
    if cached is not None:
        result = _persist_audit(db, {**cached, "cached": True}, request)
        record_product_event(db, "public_audit_completed", anonymous_id=_client_key(request), properties={"url_host": urlparse(payload.url).hostname, "cached": True})
        db.commit()
        return result
    try:
        site = preflight.run(payload.url, timeout=6.0)
        machine_files = site.get("_machine_files") if isinstance(site.get("_machine_files"), dict) else {}
        robots_file = machine_files.get("robots") if isinstance(machine_files.get("robots"), dict) else None
        robots_signal = {
            "key": "robots",
            "path": "/robots.txt",
            "present": bool(robots_file and robots_file.get("body")),
            "status": robots_file.get("status", 0) if robots_file else 0,
            "_body": robots_file.get("body", "") if robots_file else "",
        } if robots_file is not None else _machine_signal(payload.url, "/robots.txt", "robots")
        signals = [robots_signal,
                   _machine_signal(payload.url, "/sitemap.xml", "sitemap"),
                   _machine_signal(payload.url, "/llms.txt", "llms_txt")]
        robots_signal = next((item for item in signals if item.get("key") == "robots"), {})
        blocked = _robots_blocked(payload.url, robots_signal.get("_body"))
        checks = list(site.get("checks") or [])
        present = {item["key"]: bool(item["present"]) for item in signals}
        checks.extend([
            {"name": "sitemap", "ok": present["sitemap"], "message": "sitemap.xml detected" if present["sitemap"] else "sitemap.xml not detected", "action": "Publish a crawlable sitemap.xml" if not present["sitemap"] else None},
            {"name": "llms_txt", "ok": present["llms_txt"], "message": "llms.txt detected" if present["llms_txt"] else "llms.txt not detected", "action": "Add an /llms.txt machine-readable summary" if not present["llms_txt"] else None},
            {"name": "ai_crawlers", "ok": not blocked, "message": "No sampled AI crawler blocks" if not blocked else f"Robots blocks {len(blocked)} AI crawlers", "action": "Review robots.txt AI crawler directives" if blocked else None},
        ])
        passed = sum(1 for item in checks if item.get("ok"))
        result = {
            "url": payload.url,
            "kind": "public_diagnostic_summary",
            "sampling_mode": "No AI sampling · public technical preflight",
            "cached": False,
            "ready": bool(site.get("ready")),
            "score": round(passed / len(checks) * 100) if checks else 0,
            "checks": checks,
            "signals": {"robots": present["robots"], "sitemap": present["sitemap"], "llms_txt": present["llms_txt"], "ai_bots_blocked": blocked},
            "next_step": "Create a workspace to turn findings into tickets and verification runs",
        }
        _cache_audit(payload.url, result)
        result = _persist_audit(db, result, request)
        record_product_event(db, "public_audit_completed", anonymous_id=_client_key(request), properties={"url_host": urlparse(payload.url).hostname, "score": result["score"]})
        db.commit()
        return result
    except (preflight.PreflightError, ValueError) as exc:
        record_product_event(db, "public_audit_failed", anonymous_id=_client_key(request), properties={"error": type(exc).__name__})
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "public_audit_failed", "detail": str(exc)},
        ) from exc


def _error(status_code, message):
    raise HTTPException(status_code=status_code, detail={"error": message})


@router.get("/delivery-packs/{token}")
def download_shared_delivery(token: str, db: Session = Depends(get_db)):
    """Download a sendable diagnostic ZIP with a time-limited Agency share token."""
    share = delivery_share.resolve_share(db, token)
    if share is None:
        _error(status.HTTP_404_NOT_FOUND, "delivery_share_not_found")
    project = db.get(Project, share.project_id)
    tenant = db.get(Tenant, project.tenant_id) if project is not None else None
    if project is None or tenant is None or project.archived_at is not None:
        _error(status.HTTP_404_NOT_FOUND, "delivery_share_not_found")
    with with_tenant_context(tenant.directory_slug, project.slug):
        directory = geolib.project_dir(project.slug) / "delivery" / share.delivery_date
        if not directory.is_dir():
            _error(status.HTTP_404_NOT_FOUND, "delivery_not_found")
        try:
            directory = delivery.validate_existing_delivery_contract(directory)
        except GeoEngineError as exc:
            try:
                directory = delivery.ensure_delivery_contract(project.slug, directory)
            except GeoEngineError as rebuild_exc:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"error": "delivery_contract_invalid", "detail": str(rebuild_exc)},
                ) from rebuild_exc
        asset_index = geolib.read_json(directory / "assets" / "index.json", {}) or {}
        readiness = str(asset_index.get("readiness") or "unknown")
        package_kind = _delivery_package_kind(asset_index, readiness)
        source_revision = str(asset_index.get("source_revision") or "unknown")
        return _stream_delivery_zip(directory, package_kind, share.delivery_date, readiness, source_revision)
