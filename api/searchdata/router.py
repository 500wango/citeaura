"""Search Console 连接、候选与快照 API。"""

import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from api import config
from api.adapters.engine import with_tenant_context, with_tenant_read_context
from api.adapters import workspace
from api.auth.deps import get_current_user, require_editor
from api.db import get_db
from api.models import Job, Membership, Project, Tenant, User
from api.product_events import record_product_event
from api.rate_limit import RateLimitUnavailable, check_scope
from api.searchdata import candidates, demand, ga4, ga4_snapshot, gsc, oauth


logger = logging.getLogger(__name__)
router = APIRouter(tags=["searchdata"])
EDITOR_ROLES = frozenset(("owner", "editor"))


class SelectPropertyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=16, max_length=128)
    site_url: str = Field(min_length=1, max_length=2048)


class SelectGa4PropertyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=16, max_length=128)
    property_id: str = Field(min_length=1, max_length=128)


class AddCandidatesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[dict] = Field(min_length=1, max_length=candidates.MAX_CANDIDATES)


def _error(status_code, message):
    raise HTTPException(status_code=status_code, detail={"error": message})


def _project(db, tenant_id, project_id):
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        _error(status.HTTP_403_FORBIDDEN, "no_tenant_membership")
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.tenant_id == tenant.id,
        Project.archived_at.is_(None),
        Project.status != "archived",
    ).first()
    if project is None:
        _error(status.HTTP_404_NOT_FOUND, "project_not_found")
    return tenant, project


def _ensure_idle(db, project):
    if db.query(Job.id).filter(
        Job.project_id == project.id, Job.status.in_(("queued", "running")),
    ).first() is not None:
        _error(status.HTTP_409_CONFLICT, "project_job_already_running")


def _require_configured(flow="gsc"):
    if not config.google_oauth_configured():
        _error(status.HTTP_404_NOT_FOUND, f"{flow}_not_configured")


def _event(db, name, tenant_id, user_id, properties):
    try:
        record_product_event(db, name, tenant_id=tenant_id, user_id=user_id, properties=properties)
        db.commit()
    except Exception:  # noqa: BLE001 - 埋点失败不能影响授权流程
        db.rollback()
        logger.exception("searchdata product event failed: %s", name)


def _app_redirect(project_id, outcome, session_id=None, flow="gsc"):
    if flow == oauth.FLOW_GA4:
        target = f"{config.public_base_url()}/app/#/report?ga4={quote(outcome)}"
        session_param = "ga4_session"
    else:
        target = f"{config.public_base_url()}/app/#/questions?gsc={quote(outcome)}"
        session_param = "gsc_session"
    if project_id:
        target += f"&project={int(project_id)}"
    if session_id:
        target += f"&{session_param}={quote(session_id)}"
    response = RedirectResponse(target, status_code=status.HTTP_303_SEE_OTHER)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def _bank_keys(questions):
    """已入库的候选：按 GSC 候选 ID 或问题文本识别，用户编辑过的问题也能对上。"""
    ids, texts = set(), set()
    for item in questions or []:
        if not isinstance(item, dict):
            continue
        texts.add(str(item.get("text") or "").strip())
        candidate_id = (item.get("gsc") or {}).get("candidate_id") if isinstance(item.get("gsc"), dict) else None
        if candidate_id:
            ids.add(str(candidate_id))
    return ids, texts


def _snapshot_summary(snapshot, questions=()):
    if not snapshot:
        return {"status": "not_connected", "configured": config.google_oauth_configured()}
    ids, texts = _bank_keys(questions)
    return {
        "status": "ready",
        "configured": config.google_oauth_configured(),
        "source_label": "GSC·第一方",
        "property": snapshot["property"],
        "window": snapshot["window"],
        "search_type": snapshot["search_type"],
        "data_state": snapshot["data_state"],
        "fetched_at": snapshot["fetched_at"],
        "totals": snapshot["totals"],
        "query_count": snapshot["query_count"],
        "anonymous_click_share": snapshot["anonymous_click_share"],
        "excluded": snapshot["excluded"],
        "low_volume": snapshot["low_volume"],
        "candidates": [
            {**item, "in_question_bank": item["id"] in ids or item["prompt"] in texts}
            for item in snapshot["candidates"]
        ],
    }


def _fetch_and_store(db, tenant, project, token, site_url, user_id):
    fetched = gsc.fetch_queries(token, site_url)
    with with_tenant_context(tenant.directory_slug, project.slug):
        project_config = workspace.read_config(project.slug)
        snapshot = candidates.build_snapshot(site_url, fetched, project_config)
        candidates.write_snapshot(project.slug, snapshot)
    _event(db, "gsc_candidates_shown", tenant.id, user_id, {
        "project_id": project.id,
        "candidate_count": len(snapshot["candidates"]),
        "low_volume": snapshot["low_volume"],
    })
    return snapshot


@router.get("/api/v1/searchdata/gsc/status")
def gsc_status(current_user: User = Depends(get_current_user)):
    return {"configured": config.google_oauth_configured()}


@router.get("/api/v1/projects/{project_id}/searchdata/gsc")
def get_gsc_snapshot(project_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    tenant, project = _project(db, current_user.tenant_id, project_id)
    with with_tenant_read_context(tenant, project.slug):
        snapshot = candidates.read_snapshot(project.slug)
        questions = workspace.read_config(project.slug).get("questions") or [] if snapshot else []
    return _snapshot_summary(snapshot, questions)


@router.post("/api/v1/projects/{project_id}/searchdata/gsc/authorize")
def authorize_gsc(request: Request, project_id: int, current_user: User = Depends(require_editor), db: Session = Depends(get_db)):
    _require_configured()
    tenant, project = _project(db, current_user.tenant_id, project_id)
    try:
        decision = check_scope(request, "gsc-authorize", 10, 60)
    except RateLimitUnavailable:
        _error(status.HTTP_503_SERVICE_UNAVAILABLE, "rate_limit_unavailable")
    if not decision.allowed:
        _error(status.HTTP_429_TOO_MANY_REQUESTS, "rate_limit_exceeded")
    try:
        url = oauth.authorization_url(current_user.id, tenant.id, project.id)
    except oauth.OAuthError as exc:
        _error(status.HTTP_400_BAD_REQUEST, str(exc))
    _event(db, "gsc_connect_started", tenant.id, current_user.id, {"project_id": project.id})
    return {"authorization_url": url}


def _callback_user(db, user_id, tenant_id, flow="gsc"):
    user = db.get(User, user_id)
    membership = db.get(Membership, {"tenant_id": tenant_id, "user_id": user_id})
    tenant = db.get(Tenant, tenant_id)
    if (
        user is None or membership is None or tenant is None
        or user.status != "active" or tenant.status != "active"
        or membership.role not in EDITOR_ROLES
    ):
        raise oauth.OAuthError(f"{flow}_state_invalid")
    return user


def _google_error_outcome(error):
    text = str(error or "").strip()
    if text == "access_denied":
        return "denied"
    if text in ("invalid_scope", "invalid_request"):
        return "scope_not_granted"
    return "failed"


def _gsc_callback(db, project_id, code, error, nonce, user_id, tenant_id):
    if error or not code:
        return _app_redirect(project_id, "denied")
    try:
        user = _callback_user(db, user_id, tenant_id)
        tenant, project = _project(db, tenant_id, project_id)
        token = oauth.exchange_code(code, nonce)
    except oauth.OAuthError as exc:
        return _app_redirect(project_id, str(exc).removeprefix("gsc_"))
    except HTTPException:
        return _app_redirect(project_id, "state_invalid")
    try:
        sites = gsc.list_sites(token)
        matched = gsc.match_sites(project.url, sites)
        _event(db, "gsc_connect_completed", tenant.id, user.id, {
            "project_id": project.id, "matched_properties": len(matched), "properties": len(sites),
        })
        if len(matched) == 1:
            _fetch_and_store(db, tenant, project, token, matched[0]["site_url"], user.id)
            oauth.revoke(token)
            return _app_redirect(project.id, "ready")
        choices = matched or sites
        if not choices:
            oauth.revoke(token)
            return _app_redirect(project.id, "no_property")
        session_id = oauth.open_session(token, user.id, tenant.id, project.id, [item["site_url"] for item in choices])
        return _app_redirect(project.id, "choose", session_id)
    except gsc.GscError as exc:
        oauth.revoke(token)
        return _app_redirect(project.id, str(exc).removeprefix("gsc_"))


def _ga4_fetch_and_store(db, tenant, project, token, choice, user_id):
    fetched = ga4.fetch_ai_referrals(token, choice["property"])
    key_event_status = ga4.key_events_status(token, choice["property"])
    property_meta = {"time_zone": ga4.property_time_zone(token, choice["property"])}
    snapshot = ga4_snapshot.build_snapshot(choice, fetched, key_event_status, property_meta)
    with with_tenant_context(tenant.directory_slug, project.slug):
        ga4_snapshot.write_snapshot(project.slug, snapshot)
    _event(db, "ga4_referrals_shown", tenant.id, user_id, {
        "project_id": project.id,
        "sources": len(snapshot["ai_sources"]),
        "truncated": snapshot["coverage"]["truncated"],
    })
    return snapshot


def _ga4_callback(db, project_id, code, error, nonce, user_id, tenant_id):
    if error or not code:
        return _app_redirect(project_id, _google_error_outcome(error), flow=oauth.FLOW_GA4)
    token = None
    try:
        user = _callback_user(db, user_id, tenant_id, oauth.FLOW_GA4)
        tenant, project = _project(db, tenant_id, project_id)
        token = oauth.exchange_code(code, nonce, oauth.FLOW_GA4)
        properties = ga4.list_properties(token)
        matched = ga4.match_properties(project.url, properties, token)
        _event(db, "ga4_connect_completed", tenant.id, user.id, {
            "project_id": project.id,
            "matched_properties": len(matched["matched"]),
            "properties": matched["properties_total"],
        })
        exact = [item for item in matched["matched"] if item["match_type"] == "exact"]
        if len(exact) == 1:
            _ga4_fetch_and_store(db, tenant, project, token, exact[0], user.id)
            oauth.revoke(token)
            token = None
            return _app_redirect(project.id, "ready", flow=oauth.FLOW_GA4)
        choices = matched["offered"]
        if not choices:
            return _app_redirect(project.id, "no_property", flow=oauth.FLOW_GA4)
        session_id = oauth.open_session(
            token, user.id, tenant.id, project.id,
            flow=oauth.FLOW_GA4, choices=choices,
        )
        token = None
        return _app_redirect(project.id, "choose", session_id, flow=oauth.FLOW_GA4)
    except oauth.OAuthError as exc:
        return _app_redirect(project_id, str(exc).removeprefix("ga4_"), flow=oauth.FLOW_GA4)
    except HTTPException:
        return _app_redirect(project_id, "state_invalid", flow=oauth.FLOW_GA4)
    except ga4.Ga4Error as exc:
        return _app_redirect(project_id, str(exc).removeprefix("ga4_"), flow=oauth.FLOW_GA4)
    finally:
        if token:
            oauth.revoke(token)


@router.get("/api/v1/searchdata/gsc/callback", include_in_schema=False)
def google_callback(state: str = "", code: str = "", error: str = "", db: Session = Depends(get_db)):
    """Google 跳回的入口：按 state 中的 flow 分流，身份以验签后的 claims 为准。"""
    if not config.google_oauth_configured():
        return _app_redirect(None, "not_configured")
    flow = oauth.peek_flow(state)
    try:
        user_id, tenant_id, project_id, nonce = oauth.verify_state(state, flow)
    except oauth.OAuthError:
        return _app_redirect(None, "state_invalid", flow=flow)
    if flow == oauth.FLOW_GA4:
        return _ga4_callback(db, project_id, code, error, nonce, user_id, tenant_id)
    return _gsc_callback(db, project_id, code, error, nonce, user_id, tenant_id)


@router.get("/api/v1/projects/{project_id}/searchdata/gsc/session/{session_id}")
def gsc_session(project_id: int, session_id: str, current_user: User = Depends(require_editor), db: Session = Depends(get_db)):
    tenant, project = _project(db, current_user.tenant_id, project_id)
    try:
        data = oauth.read_session(session_id, current_user.id, tenant.id, project.id)
    except oauth.OAuthError as exc:
        _error(status.HTTP_410_GONE, str(exc))
    return {"properties": data["sites"], "project_url": project.url}


@router.post("/api/v1/projects/{project_id}/searchdata/gsc/select")
def gsc_select(project_id: int, payload: SelectPropertyRequest, current_user: User = Depends(require_editor), db: Session = Depends(get_db)):
    tenant, project = _project(db, current_user.tenant_id, project_id)
    try:
        data = oauth.read_session(payload.session_id, current_user.id, tenant.id, project.id)
    except oauth.OAuthError as exc:
        _error(status.HTTP_410_GONE, str(exc))
    if payload.site_url not in data["sites"]:
        _error(status.HTTP_400_BAD_REQUEST, "gsc_property_not_offered")
    try:
        snapshot = _fetch_and_store(db, tenant, project, data["token"], payload.site_url, current_user.id)
    except gsc.GscError as exc:
        _error(status.HTTP_502_BAD_GATEWAY, str(exc))
    finally:
        oauth.close_session(payload.session_id)
    return _snapshot_summary(snapshot)


@router.post("/api/v1/projects/{project_id}/searchdata/gsc/questions")
def add_gsc_questions(project_id: int, payload: AddCandidatesRequest, current_user: User = Depends(require_editor), db: Session = Depends(get_db)):
    """按快照中的候选写入问题库；GSC 元数据由服务端回填。"""
    tenant, project = _project(db, current_user.tenant_id, project_id)
    _ensure_idle(db, project)
    with with_tenant_context(tenant.directory_slug, project.slug):
        snapshot = candidates.read_snapshot(project.slug)
        if snapshot is None:
            _error(status.HTTP_404_NOT_FOUND, "gsc_snapshot_not_found")
        items = []
        for raw in payload.items:
            candidate = candidates.candidate_by_id(snapshot, str((raw or {}).get("id") or ""))
            if candidate is None:
                _error(status.HTTP_400_BAD_REQUEST, "gsc_candidate_not_found")
            text = str((raw or {}).get("text") or candidate["prompt"]).strip()
            if not text or len(text) > 1000:
                _error(status.HTTP_400_BAD_REQUEST, "invalid_question_text")
            items.append({
                "text": text,
                "market": candidate["market"],
                "group": "Search demand",
                "source": "gsc",
                "gsc": candidates.question_metadata(snapshot, candidate),
            })
        try:
            added = workspace.add_questions(project.slug, items)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "workspace_operation_failed", "detail": str(exc)},
            ) from exc
    _event(db, "gsc_questions_added", tenant.id, current_user.id, {"project_id": project.id, "count": len(added)})
    return {"ok": True, "added": len(added), "ids": [item["id"] for item in added]}


@router.delete("/api/v1/projects/{project_id}/searchdata/gsc")
def delete_gsc_snapshot(project_id: int, current_user: User = Depends(require_editor), db: Session = Depends(get_db)):
    tenant, project = _project(db, current_user.tenant_id, project_id)
    with with_tenant_context(tenant.directory_slug, project.slug):
        try:
            existed = candidates.delete_snapshot(project.slug)
        except ValueError:
            _error(status.HTTP_400_BAD_REQUEST, "invalid_searchdata_directory")
    return {"ok": True, "deleted": existed}


@router.get("/api/v1/projects/{project_id}/searchdata/gsc/demand")
def gsc_demand(project_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """GSC 来源问题的 Google 需求与最近一次 AI 采样并列；不进入健康分。"""
    tenant, project = _project(db, current_user.tenant_id, project_id)
    with with_tenant_read_context(tenant, project.slug):
        return demand.build(project.slug)


@router.get("/api/v1/searchdata/ga4/status")
def ga4_status(current_user: User = Depends(get_current_user)):
    return {
        "configured": config.google_oauth_configured(),
        "ai_sources_version": ga4_snapshot.ai_sources.TABLE_VERSION,
    }


@router.get("/api/v1/projects/{project_id}/searchdata/ga4")
def get_ga4_snapshot(project_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    tenant, project = _project(db, current_user.tenant_id, project_id)
    with with_tenant_read_context(tenant, project.slug):
        snapshot = ga4_snapshot.read_snapshot(project.slug)
    return ga4_snapshot.summary(snapshot, config.google_oauth_configured())


@router.post("/api/v1/projects/{project_id}/searchdata/ga4/authorize")
def authorize_ga4(request: Request, project_id: int, current_user: User = Depends(require_editor), db: Session = Depends(get_db)):
    _require_configured(oauth.FLOW_GA4)
    tenant, project = _project(db, current_user.tenant_id, project_id)
    try:
        decision = check_scope(request, "ga4-authorize", 10, 60)
    except RateLimitUnavailable:
        _error(status.HTTP_503_SERVICE_UNAVAILABLE, "rate_limit_unavailable")
    if not decision.allowed:
        _error(status.HTTP_429_TOO_MANY_REQUESTS, "rate_limit_exceeded")
    try:
        url = oauth.authorization_url(current_user.id, tenant.id, project.id, oauth.FLOW_GA4)
    except oauth.OAuthError as exc:
        _error(status.HTTP_400_BAD_REQUEST, str(exc))
    _event(db, "ga4_connect_started", tenant.id, current_user.id, {"project_id": project.id})
    return {"authorization_url": url}


@router.get("/api/v1/projects/{project_id}/searchdata/ga4/session/{session_id}")
def ga4_session(project_id: int, session_id: str, current_user: User = Depends(require_editor), db: Session = Depends(get_db)):
    tenant, project = _project(db, current_user.tenant_id, project_id)
    try:
        data = oauth.read_session(session_id, current_user.id, tenant.id, project.id, oauth.FLOW_GA4)
    except oauth.OAuthError as exc:
        _error(status.HTTP_410_GONE, str(exc))
    return {"properties": data.get("choices") or [], "project_url": project.url}


@router.post("/api/v1/projects/{project_id}/searchdata/ga4/select")
def ga4_select(project_id: int, payload: SelectGa4PropertyRequest, current_user: User = Depends(require_editor), db: Session = Depends(get_db)):
    tenant, project = _project(db, current_user.tenant_id, project_id)
    try:
        data = oauth.read_session(payload.session_id, current_user.id, tenant.id, project.id, oauth.FLOW_GA4)
    except oauth.OAuthError as exc:
        _error(status.HTTP_410_GONE, str(exc))
    choice = next(
        (item for item in data.get("choices") or [] if item.get("property") == payload.property_id),
        None,
    )
    if choice is None:
        _error(status.HTTP_400_BAD_REQUEST, "ga4_property_not_offered")
    try:
        snapshot = _ga4_fetch_and_store(db, tenant, project, data["token"], choice, current_user.id)
    except ga4.Ga4Error as exc:
        _error(status.HTTP_502_BAD_GATEWAY, str(exc))
    finally:
        oauth.close_session(payload.session_id, oauth.FLOW_GA4)
    return ga4_snapshot.summary(snapshot, True)


@router.delete("/api/v1/projects/{project_id}/searchdata/ga4")
def delete_ga4_snapshot(project_id: int, current_user: User = Depends(require_editor), db: Session = Depends(get_db)):
    tenant, project = _project(db, current_user.tenant_id, project_id)
    with with_tenant_context(tenant.directory_slug, project.slug):
        try:
            existed = ga4_snapshot.delete_snapshot(project.slug)
        except ValueError:
            _error(status.HTTP_400_BAD_REQUEST, "invalid_searchdata_directory")
    _event(db, "ga4_snapshot_deleted", tenant.id, current_user.id, {"project_id": project.id})
    return {"ok": True, "deleted": existed}
