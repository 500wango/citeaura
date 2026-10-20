"""企业 OIDC SSO 配置、登录和审计日志 API。"""

import hmac
import json
import re
import secrets
from datetime import datetime, timezone

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
from api.billing.access import effective_tenant_plan
from api.country import request_country_code
from api.db import get_db
from api.models import AuditEvent, Membership, SsoConfiguration, SsoIdentity, Tenant, User
from api.product_events import record_product_event
from api.settings.crypto import SSO_STATE_AAD, decrypt_key, encrypt_key


router = APIRouter(prefix="/api/v1/sso", tags=["sso"])
SSO_CONTEXT_COOKIE = "citeaura_sso_context"


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

def _verified_domains(configuration):
    try:
        values = json.loads(configuration.verified_domains or "[]")
    except (TypeError, ValueError):
        values = []
    return [value for value in values if isinstance(value, str)]

def _verification_token(tenant_id, domain):
    return f"citeaura-domain-verification={tenant_id}:{domain}"

def _domain_verified(tenant_id, domain):
    try:
        import dns.resolver
        answers = dns.resolver.resolve(f"_citeaura.{domain}", "TXT", lifetime=3)
        return any(_verification_token(tenant_id, domain) in "".join(part.decode() if isinstance(part, bytes) else str(part) for part in answer.strings) for answer in answers)
    except Exception:
        return False


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
        "verified_domains": _verified_domains(configuration),
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
    issuer_changed = configuration.issuer_url != payload.issuer_url or configuration.client_id != payload.client_id
    configuration.issuer_url = payload.issuer_url
    configuration.client_id = payload.client_id
    configuration.allowed_domains = json.dumps(payload.allowed_domains, ensure_ascii=True)
    # 换 IdP 必须重新做 DNS 验证：否则一个已证明过的域名可以被指向任意旁路 IdP。
    existing_verified = set() if issuer_changed else set(_verified_domains(configuration))
    configuration.verified_domains = json.dumps(sorted(existing_verified.intersection(payload.allowed_domains)), ensure_ascii=True)
    configuration.default_role = payload.default_role
    configuration.enabled = payload.enabled
    if payload.enabled and config.sso_require_domain_verification():
        missing = [domain for domain in payload.allowed_domains if domain not in existing_verified]
        if missing:
            _error(status.HTTP_409_CONFLICT, "sso_domains_unverified")
    if payload.client_secret is not None:
        value = payload.client_secret.strip()
        configuration.encrypted_client_secret = encrypt_key(value) if value else None
    db.commit()
    db.refresh(configuration)
    return _configuration_payload(configuration, tenant, True)

@router.post("/domains/verify")
def verify_sso_domains(current_user: User = Depends(require_owner), db: Session = Depends(get_db)):
    configuration = db.get(SsoConfiguration, current_user.tenant_id)
    if configuration is None:
        _error(status.HTTP_404_NOT_FOUND, "sso_not_configured")
    verified = set(_verified_domains(configuration))
    results = {}
    for domain in _domains(configuration):
        ok = _domain_verified(current_user.tenant_id, domain)
        results[domain] = {"verified": ok, "txt_name": f"_citeaura.{domain}", "txt_value": _verification_token(current_user.tenant_id, domain)}
        if ok:
            verified.add(domain)
    configuration.verified_domains = json.dumps(sorted(verified.intersection(_domains(configuration))), ensure_ascii=True)
    db.commit()
    return {"verified_domains": _verified_domains(configuration), "results": results}


@router.delete("/config")
def delete_sso_config(current_user: User = Depends(require_owner), db: Session = Depends(get_db)):
    configuration = db.get(SsoConfiguration, current_user.tenant_id)
    if configuration is None:
        _error(status.HTTP_404_NOT_FOUND, "sso_not_configured")
    db.delete(configuration)
    db.commit()
    return {"deleted": True}


def _email_domain(email):
    return str(email or "").rsplit("@", 1)[-1].strip().lower()


def _domain_is_verified(configuration, email):
    """只判断**本次登录邮箱所属的域**是否已验证。

    以前用集合差（allowed - verified），只要配置里多一个尚未验证的域，所有
    已有域的登录都会被 409 挡住。
    """
    domain = _email_domain(email)
    return bool(domain) and domain in set(_verified_domains(configuration))


@router.get("/login/{tenant_id}")
def start_sso_login(tenant_id: int, response: Response, db: Session = Depends(get_db)):
    tenant = _tenant(db, tenant_id)
    if tenant.status != "active":
        _error(status.HTTP_403_FORBIDDEN, "account_disabled")
    configuration = db.get(SsoConfiguration, tenant.id)
    if effective_tenant_plan(db, tenant.id) != "enterprise" or configuration is None or not configuration.enabled:
        _error(status.HTTP_404_NOT_FOUND, "sso_not_configured")
    if config.sso_require_domain_verification() and not (
        set(_domains(configuration)) & set(_verified_domains(configuration))
    ):
        # 发起登录时还不知道邮箱：只要至少有一个已通过的域就允许进入 IdP。
        _error(status.HTTP_409_CONFLICT, "sso_domains_unverified")
    state = create_sso_state(tenant.id)
    redirect_uri = f"{config.public_base_url()}/api/v1/sso/callback"
    try:
        authorization_url, context = oidc.authorization_request(configuration, redirect_uri, state)
        encrypted_context = encrypt_key(json.dumps(context, separators=(",", ":")), SSO_STATE_AAD)
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
        context = json.loads(decrypt_key(encrypted_context, SSO_STATE_AAD))
        if not hmac.compare_digest(str(context.get("state") or ""), state):
            raise ValueError("state mismatch")
        claims = decode_token(state, expected_type="sso_state")
        tenant_id = int(claims["tenant_id"])
    except (ValueError, TypeError, KeyError, jwt.PyJWTError, RuntimeError):
        _error(status.HTTP_400_BAD_REQUEST, "sso_context_invalid")
    tenant = _tenant(db, tenant_id)
    configuration = db.get(SsoConfiguration, tenant.id)
    if effective_tenant_plan(db, tenant.id) != "enterprise" or configuration is None or not configuration.enabled:
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
    if config.sso_require_domain_verification() and not _domain_is_verified(configuration, email):
        _error(status.HTTP_409_CONFLICT, "sso_domains_unverified")
    issuer = str(configuration.issuer_url or "").strip()
    subject = str(identity["subject"])
    binding = db.query(SsoIdentity).filter(
        SsoIdentity.tenant_id == tenant.id,
        SsoIdentity.issuer == issuer,
        SsoIdentity.subject == subject,
    ).first()
    if binding is not None:
        user = db.get(User, binding.user_id)
        if user is None or user.status != "active":
            _error(status.HTTP_403_FORBIDDEN, "sso_identity_not_bound")
        if db.get(Membership, {"tenant_id": tenant.id, "user_id": user.id}) is None:
            _error(status.HTTP_403_FORBIDDEN, "sso_identity_not_bound")
        binding.last_login_at = datetime.now(timezone.utc)
    else:
        user = db.query(User).filter(User.email == email).first()
        if user is None:
            if not _domain_is_verified(configuration, email):
                _error(status.HTTP_403_FORBIDDEN, "sso_domain_verification_required_for_provisioning")
            country_code = request_country_code(request)
            user = User(
                email=email,
                password_hash=hash_password(secrets.token_urlsafe(48)),
                registration_kind="sso",
                signup_country_code=country_code,
            )
            db.add(user)
            db.flush()
            record_product_event(
                db,
                "signup_completed",
                tenant_id=tenant.id,
                user_id=user.id,
                country_code=country_code,
                properties={"registration_kind": "sso"},
            )
        elif user.status != "active":
            _error(status.HTTP_403_FORBIDDEN, "account_disabled")
        else:
            # 已有全局身份：只有该用户在这个租户下还没被任何 IdP 绑定时才允许首次绑定。
            # 之后一律以 (issuer, subject) 为准，不再用 email 断言身份。
            conflicting = db.query(SsoIdentity.id).filter(
                SsoIdentity.user_id == user.id,
                SsoIdentity.tenant_id == tenant.id,
            ).first()
            if conflicting is not None or db.get(Membership, {"tenant_id": tenant.id, "user_id": user.id}) is None:
                _error(status.HTTP_403_FORBIDDEN, "sso_identity_not_bound")
        db.add(SsoIdentity(
            tenant_id=tenant.id,
            issuer=issuer,
            subject=subject,
            user_id=user.id,
            last_login_at=datetime.now(timezone.utc),
        ))
    membership = db.get(Membership, {"tenant_id": tenant.id, "user_id": user.id})
    if membership is None:
        membership = Membership(tenant_id=tenant.id, user_id=user.id, role=configuration.default_role)
        db.add(membership)
    user.last_login_at = datetime.now(timezone.utc)
    record_event(
        db, tenant.id, "sso.login", f"sso:{configuration.provider_name}",
        user_id=user.id, ip_address=request.client.host if request.client else None,
        details={"subject": subject, "issuer": issuer},
    )
    db.commit()
    redirect = RedirectResponse(url="/app#overview", status_code=status.HTTP_303_SEE_OTHER)
    token_response(redirect, user.id, tenant.id, db, expose_tokens=False, sso_tenant_id=tenant.id)
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
