"""企业 OIDC SSO 配置、登录和审计日志 API。"""

import hmac
import json
import re
import secrets

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from api import config
from api.audit import event_payload, record_event
from api.auth import oidc
from api.auth.deps import get_current_user, require_owner
from api.auth.router import token_response
from api.auth.security import create_sso_state, decode_token, hash_password
from api.db import get_db
from api.models import AuditEvent, Membership, SsoConfiguration, Tenant, User
from api.settings.crypto import decrypt_key, encrypt_key


router = APIRouter(prefix="/api/v1/sso", tags=["sso"])
SSO_CONTEXT_COOKIE = "disvorai_sso_context"


class SsoConfigRequest(BaseModel):
    provider_name: str = Field(min_length=1, max_length=128)
    issuer_url: str = Field(min_length=1, max_length=2048)
    client_id: str = Field(min_length=1, max_length=512)
    client_secret: str | None = Field(default=None, max_length=4096)
    allowed_domains: list[str] = Field(min_length=1, max_length=20)
    default_role: str = "viewer"
    enabled: bool = False

    @field_validator("provider_name", "client_id")
    @classmethod
    def normalize_text(cls, value):
        return value.strip()

    @field_validator("issuer_url")
    @classmethod
    def validate_issuer(cls, value):
        return oidc.normalize_issuer_url(value)

    @field_validator("allowed_domains")
    @classmethod
    def normalize_domains(cls, values):
        domains = []
        for value in values:
            domain = str(value).strip().lower().lstrip("@")
            if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?\.[a-z]{2,63}", domain):
                raise ValueError("invalid allowed domain")
            if domain not in domains:
                domains.append(domain)
        return domains

    @field_validator("default_role")
    @classmethod
    def validate_default_role(cls, value):
        if value not in ("editor", "viewer"):
            raise ValueError("default role must be editor or viewer")
        return value


def _error(status_code, message):
    raise HTTPException(status_code=status_code, detail={"error": message})


def _tenant(db, tenant_id):
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        _error(status.HTTP_404_NOT_FOUND, "sso_not_configured")
    return tenant


def _domains(configuration):
    try:
        values = json.loads(configuration.allowed_domains or "[]")
    except (TypeError, ValueError):
        values = []
    return [value for value in values if isinstance(value, str)]


def _configuration_payload(configuration, tenant, can_edit):
    if configuration is None:
        return {
            "available": tenant.plan == "enterprise",
            "plan": tenant.plan,
            "can_edit": can_edit,
            "configured": False,
            "enabled": False,
            "login_url": None,
        }
    return {
        "available": tenant.plan == "enterprise",
        "plan": tenant.plan,
        "can_edit": can_edit,
        "configured": True,
        "provider_name": configuration.provider_name,
        "issuer_url": configuration.issuer_url,
        "client_id": configuration.client_id,
        "client_secret_configured": bool(configuration.encrypted_client_secret),
        "allowed_domains": _domains(configuration),
        "default_role": configuration.default_role,
        "enabled": bool(configuration.enabled),
        "login_url": f"/api/v1/sso/login/{tenant.id}" if configuration.enabled else None,
        "updated_at": configuration.updated_at,
    }


@router.get("/config")
def get_sso_config(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    tenant = _tenant(db, current_user.tenant_id)
    configuration = db.get(SsoConfiguration, tenant.id)
    return _configuration_payload(configuration, tenant, current_user.tenant_role == "owner")


@router.put("/config")
def save_sso_config(
    payload: SsoConfigRequest,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    tenant = _tenant(db, current_user.tenant_id)
    if tenant.plan != "enterprise":
        _error(status.HTTP_403_FORBIDDEN, "enterprise_plan_required")
    configuration = db.get(SsoConfiguration, tenant.id)
    if configuration is None:
        configuration = SsoConfiguration(tenant_id=tenant.id)
        db.add(configuration)
    configuration.provider_name = payload.provider_name
    configuration.issuer_url = payload.issuer_url
    configuration.client_id = payload.client_id
    configuration.allowed_domains = json.dumps(payload.allowed_domains, ensure_ascii=True)
    configuration.default_role = payload.default_role
    configuration.enabled = payload.enabled
    if payload.client_secret is not None:
        value = payload.client_secret.strip()
        configuration.encrypted_client_secret = encrypt_key(value) if value else None
    db.commit()
    db.refresh(configuration)
    return _configuration_payload(configuration, tenant, True)


@router.delete("/config")
def delete_sso_config(current_user: User = Depends(require_owner), db: Session = Depends(get_db)):
    configuration = db.get(SsoConfiguration, current_user.tenant_id)
    if configuration is None:
        _error(status.HTTP_404_NOT_FOUND, "sso_not_configured")
    db.delete(configuration)
    db.commit()
    return {"deleted": True}


@router.get("/login/{tenant_id}")
def start_sso_login(tenant_id: int, response: Response, db: Session = Depends(get_db)):
    tenant = _tenant(db, tenant_id)
    configuration = db.get(SsoConfiguration, tenant.id)
    if tenant.plan != "enterprise" or configuration is None or not configuration.enabled:
        _error(status.HTTP_404_NOT_FOUND, "sso_not_configured")
    state = create_sso_state(tenant.id)
    redirect_uri = f"{config.public_base_url()}/api/v1/sso/callback"
    try:
        authorization_url, context = oidc.authorization_request(configuration, redirect_uri, state)
        encrypted_context = encrypt_key(json.dumps(context, separators=(",", ":")))
    except (oidc.OidcError, RuntimeError, ValueError) as exc:
        _error(status.HTTP_502_BAD_GATEWAY, str(exc))
    redirect = RedirectResponse(authorization_url, status_code=status.HTTP_303_SEE_OTHER)
    redirect.set_cookie(
        SSO_CONTEXT_COOKIE,
        encrypted_context,
        max_age=600,
        httponly=True,
        secure=config.session_cookie_secure(),
        samesite="lax",
    )
    return redirect


@router.get("/callback")
def sso_callback(
    request: Request,
    code: str = Query(min_length=1, max_length=4096),
    state: str = Query(min_length=1, max_length=4096),
    db: Session = Depends(get_db),
):
    encrypted_context = request.cookies.get(SSO_CONTEXT_COOKIE)
    if not encrypted_context:
        _error(status.HTTP_400_BAD_REQUEST, "sso_context_invalid")
    try:
        context = json.loads(decrypt_key(encrypted_context))
        if not hmac.compare_digest(str(context.get("state") or ""), state):
            raise ValueError("state mismatch")
        claims = decode_token(state, expected_type="sso_state")
        tenant_id = int(claims["tenant_id"])
    except (ValueError, TypeError, KeyError, jwt.PyJWTError, RuntimeError):
        _error(status.HTTP_400_BAD_REQUEST, "sso_context_invalid")
    tenant = _tenant(db, tenant_id)
    configuration = db.get(SsoConfiguration, tenant.id)
    if tenant.plan != "enterprise" or configuration is None or not configuration.enabled:
        _error(status.HTTP_404_NOT_FOUND, "sso_not_configured")
    redirect_uri = f"{config.public_base_url()}/api/v1/sso/callback"
    try:
        identity = oidc.complete_login(configuration, redirect_uri, code, context)
    except oidc.OidcError as exc:
        record_event(
            db, tenant.id, "sso.login", f"sso:{configuration.provider_name}",
            outcome="failed", ip_address=request.client.host if request.client else None,
            details={"error": str(exc)},
        )
        db.commit()
        _error(status.HTTP_401_UNAUTHORIZED, str(exc))
    email = identity["email"]
    if email.rsplit("@", 1)[-1] not in _domains(configuration):
        record_event(
            db, tenant.id, "sso.login", f"sso:{configuration.provider_name}",
            outcome="failed", ip_address=request.client.host if request.client else None,
            details={"error": "sso_domain_not_allowed"},
        )
        db.commit()
        _error(status.HTTP_403_FORBIDDEN, "sso_domain_not_allowed")
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        user = User(email=email, password_hash=hash_password(secrets.token_urlsafe(48)))
        db.add(user)
        db.flush()
    membership = db.get(Membership, {"tenant_id": tenant.id, "user_id": user.id})
    if membership is None:
        membership = Membership(tenant_id=tenant.id, user_id=user.id, role=configuration.default_role)
        db.add(membership)
    record_event(
        db, tenant.id, "sso.login", f"sso:{configuration.provider_name}",
        user_id=user.id, ip_address=request.client.host if request.client else None,
        details={"subject": identity["subject"]},
    )
    db.commit()
    redirect = RedirectResponse(url="/#overview", status_code=status.HTTP_303_SEE_OTHER)
    token_response(redirect, user.id, tenant.id)
    redirect.delete_cookie(SSO_CONTEXT_COOKIE)
    return redirect


@router.get("/audit-events")
def list_audit_events(
    before_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    query = db.query(AuditEvent).filter(AuditEvent.tenant_id == current_user.tenant_id)
    if before_id is not None:
        query = query.filter(AuditEvent.id < before_id)
    events = query.order_by(AuditEvent.id.desc()).limit(limit).all()
    return {"events": [event_payload(event) for event in events], "soc2_status": "controls_ready_not_certified"}
