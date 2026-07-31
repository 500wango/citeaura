"""Semrush 与 Google Search Console 集成 API。"""

import json
from datetime import datetime, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from api import config
from api.adapters import integrations
from api.adapters.engine import job_log_path, with_tenant_context
from api.auth.deps import get_current_user, require_editor, require_owner
from api.auth.security import create_google_oauth_state, decode_token
from api.db import get_db
from api.models import IntegrationCredential, Job, Membership, Project, Tenant, User
from api.settings.crypto import encrypt_key, mask_key
from api.worker.tasks import task_sync_integration


router = APIRouter(prefix="/api/v1", tags=["integrations"])


class SemrushConfigRequest(BaseModel):
    api_key: str = Field(min_length=1, max_length=4096)
    database: str = Field(default="us", min_length=2, max_length=2)

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, value):
        value = value.strip()
        if not value or "\n" in value or "\r" in value:
            raise ValueError("api_key must be a non-empty single line")
        return value

    @field_validator("database")
    @classmethod
    def validate_database(cls, value):
        value = value.strip().lower()
        if not value.isalpha() or len(value) != 2:
            raise ValueError("database must be a two-letter Semrush database code")
        return value


def _error(status_code, message, detail=None):
    body = {"error": message}
    if detail:
        body["detail"] = detail
    raise HTTPException(status_code=status_code, detail=body)


def _tenant(db, user):
    tenant = db.get(Tenant, user.tenant_id)
    if tenant is None:
        _error(status.HTTP_403_FORBIDDEN, "no_tenant_membership")
    return tenant


def _project(db, user, project_id):
    tenant = _tenant(db, user)
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.tenant_id == tenant.id,
    ).first()
    if project is None:
        _error(status.HTTP_404_NOT_FOUND, "project_not_found")
    return tenant, project


def _credential(db, tenant_id, provider):
    return db.query(IntegrationCredential).filter(
        IntegrationCredential.tenant_id == tenant_id,
        IntegrationCredential.provider == provider,
    ).first()


def _settings_payload(db, tenant, can_edit):
    rows = {
        row.provider: row
        for row in db.query(IntegrationCredential).filter(
            IntegrationCredential.tenant_id == tenant.id,
            IntegrationCredential.provider.in_(integrations.PROVIDERS),
        )
    }
    semrush = rows.get("semrush")
    semrush_settings = integrations.credential_config(semrush) if semrush else {}
    return {
        "can_edit": can_edit,
        "providers": {
            "semrush": {
                "configured": semrush is not None,
                "masked": semrush_settings.get("masked") if semrush else None,
                "database": semrush_settings.get("database", "us"),
            },
            "search_console": {
                "configured": rows.get("search_console") is not None,
                "oauth_available": bool(
                    config.google_oauth_client_id() and config.google_oauth_client_secret()
                ),
            },
        },
    }


@router.get("/integrations")
def integration_settings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """返回当前租户的外部数据源连接状态。"""
    tenant = _tenant(db, current_user)
    return _settings_payload(db, tenant, current_user.tenant_role == "owner")


@router.put("/integrations/semrush")
def configure_semrush(
    payload: SemrushConfigRequest,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """加密保存 Semrush API Key。"""
    tenant = _tenant(db, current_user)
    row = _credential(db, tenant.id, "semrush")
    settings = {"database": payload.database, "masked": mask_key(payload.api_key)}
    if row is None:
        row = IntegrationCredential(tenant_id=tenant.id, provider="semrush")
        db.add(row)
    row.encrypted_value = encrypt_key(payload.api_key)
    row.config_json = json.dumps(settings, sort_keys=True)
    db.commit()
    return _settings_payload(db, tenant, True)


@router.delete("/integrations/{provider}")
def disconnect_integration(
    provider: str,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """删除租户级外部数据源凭证，不删除历史项目快照。"""
    if provider not in integrations.PROVIDERS:
        _error(status.HTTP_404_NOT_FOUND, "integration_not_found")
    tenant = _tenant(db, current_user)
    row = _credential(db, tenant.id, provider)
    if row is None:
        _error(status.HTTP_404_NOT_FOUND, "integration_not_found")
    db.delete(row)
    db.commit()
    return {"deleted": True, "provider": provider}


@router.get("/integrations/search-console/authorize")
def authorize_search_console(
    project_id: int = Query(ge=1),
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """发起 Search Console OAuth 只读授权。"""
    _tenant_project, project = _project(db, current_user, project_id)
    state = create_google_oauth_state(current_user.id, current_user.tenant_id, project.id)
    try:
        return RedirectResponse(
            integrations.google_authorization_url(state),
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except integrations.IntegrationError as exc:
        _error(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc))


@router.get("/integrations/search-console/callback")
def search_console_callback(
    code: str = Query(min_length=1, max_length=4096),
    state: str = Query(min_length=1, max_length=4096),
    db: Session = Depends(get_db),
):
    """校验 OAuth state，保存 refresh token 并绑定项目站点资源。"""
    try:
        claims = decode_token(state, expected_type="google_oauth_state")
        user_id = int(claims["sub"])
        tenant_id = int(claims["tenant_id"])
        project_id = int(claims["project_id"])
    except (KeyError, TypeError, ValueError, jwt.PyJWTError, RuntimeError):
        _error(status.HTTP_400_BAD_REQUEST, "google_oauth_state_invalid")
    membership = db.get(Membership, {"tenant_id": tenant_id, "user_id": user_id})
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.tenant_id == tenant_id,
    ).first()
    if membership is None or membership.role != "owner" or project is None:
        _error(status.HTTP_403_FORBIDDEN, "google_oauth_state_invalid")
    row = _credential(db, tenant_id, "search_console")
    try:
        token_data = integrations.exchange_google_code(code)
        refresh_token = token_data.get("refresh_token")
        if not refresh_token and row is None:
            raise integrations.IntegrationError("google_refresh_token_missing")
        sites = integrations.search_console_sites(token_data["access_token"])
        selected = integrations.select_search_console_property(project.url, sites)
        if selected is None:
            raise integrations.IntegrationError("search_console_property_not_found")
    except integrations.IntegrationError as exc:
        _error(status.HTTP_400_BAD_REQUEST, str(exc))
    settings = integrations.credential_config(row) if row else {}
    properties = settings.get("properties") if isinstance(settings.get("properties"), dict) else {}
    properties[str(project.id)] = selected
    settings["properties"] = properties
    if row is None:
        row = IntegrationCredential(tenant_id=tenant_id, provider="search_console")
        db.add(row)
    if refresh_token:
        row.encrypted_value = encrypt_key(refresh_token)
    row.config_json = json.dumps(settings, sort_keys=True)
    db.commit()
    return RedirectResponse("/?integration=search_console#settings", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/projects/{project_id}/integrations")
def project_integrations(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """返回项目连接状态与最新同步快照。"""
    tenant, project = _project(db, current_user, project_id)
    settings = _settings_payload(db, tenant, current_user.tenant_role == "owner")
    search_console = _credential(db, tenant.id, "search_console")
    search_settings = integrations.credential_config(search_console) if search_console else {}
    with with_tenant_context(tenant.name, project.slug):
        latest = {
            provider: integrations.latest_snapshot(project.slug, provider)
            for provider in integrations.PROVIDERS
        }
    settings.update({
        "project_id": project.id,
        "latest": latest,
        "search_console_property": (search_settings.get("properties") or {}).get(str(project.id)),
        "search_console_authorize_url": (
            f"/api/v1/integrations/search-console/authorize?project_id={project.id}"
        ),
    })
    return settings


@router.post("/projects/{project_id}/integrations/{provider}/sync", status_code=status.HTTP_202_ACCEPTED)
def sync_project_integration(
    project_id: int,
    provider: str,
    current_user: User = Depends(require_editor),
    db: Session = Depends(get_db),
):
    """把外部数据源同步投递到 Celery。"""
    if provider not in integrations.PROVIDERS:
        _error(status.HTTP_404_NOT_FOUND, "integration_not_found")
    tenant, project = _project(db, current_user, project_id)
    if _credential(db, tenant.id, provider) is None:
        _error(status.HTTP_409_CONFLICT, "integration_not_configured")
    active = db.query(Job.id).filter(
        Job.project_id == project.id,
        Job.status.in_(("queued", "running")),
    ).first()
    if active is not None:
        _error(status.HTTP_409_CONFLICT, "project_job_already_running")
    action = f"integration_{provider}"
    job = Job(project_id=project.id, action=action, status="queued")
    db.add(job)
    project.status = "processing"
    db.commit()
    db.refresh(job)
    job.log_path = str(job_log_path(tenant.name, project.slug, job.id))
    db.commit()
    try:
        task_sync_integration.delay(tenant.name, project.slug, provider, job_id=job.id)
    except Exception as exc:  # noqa: BLE001
        job.status = "failed"
        job.error = f"{type(exc).__name__}: {exc}"
        job.finished_at = datetime.now(timezone.utc)
        project.status = "failed"
        db.commit()
        _error(status.HTTP_503_SERVICE_UNAVAILABLE, "worker_unavailable")
    return {"job_id": job.id, "project_id": project.id, "provider": provider}
