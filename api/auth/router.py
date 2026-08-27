"""注册、登录和当前用户 API。"""

import re
import uuid
import hashlib
import json
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy import or_
from sqlalchemy.orm import Session

from api import config
from api.auth import password_reset
from api.adapters import transactional_email
from api.adapters.engine import tenant_slug
from api.auth.deps import get_current_user
from api.auth.security import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    ACCESS_TOKEN_COOKIE,
    REFRESH_TOKEN_COOKIE,
    REFRESH_TOKEN_EXPIRE_DAYS,
    DUMMY_PASSWORD_HASH,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from api.rate_limit import RateLimitUnavailable, check_account
from api.country import request_country_code
from api.analytics.router import request_visitor, sanitize_public_properties
from api.db import get_db
from api.models import Membership, PasswordResetToken, PublicAudit, RefreshToken, Tenant, User
from api.product_events import record_product_event
from api.team.invitations import invitation_for_token, is_expired


router = APIRouter(prefix="/api/v1")


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=128)
    tenant_name: str | None = Field(default=None, max_length=128)
    invitation_token: str | None = Field(default=None, min_length=20, max_length=512)
    audit_id: str | None = Field(default=None, min_length=16, max_length=64)
    acquisition_source: str | None = Field(default=None, max_length=128)
    acquisition_medium: str | None = Field(default=None, max_length=64)
    acquisition_campaign: str | None = Field(default=None, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str):
        value = value.strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
            raise ValueError("invalid email")
        return value


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=128)
    tenant_id: int | None = Field(default=None, ge=1)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str):
        return value.strip().lower()


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=4096)


class ForgotPasswordRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str):
        return value.strip().lower()


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=32, max_length=512)
    password: str = Field(min_length=8, max_length=128)


class SwitchTenantRequest(BaseModel):
    tenant_id: int = Field(ge=1)


def _error(status_code: int, message: str):
    """抛出统一错误响应。"""
    raise HTTPException(status_code=status_code, detail={"error": message})


def _tenant_name(db: Session, requested: str | None, email: str) -> str:
    """生成唯一的默认租户名称，避免文件系统目录冲突。"""
    base = tenant_slug((requested or email.split("@", 1)[0]).strip() or "workspace")
    candidate = base
    while db.query(Tenant.id).filter(or_(
        Tenant.name == candidate,
        Tenant.directory_slug == candidate,
    )).first() is not None:
        candidate = f"{base[:39]}-{uuid.uuid4().hex[:8]}"
    return candidate


def _token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def token_response(
    response: Response,
    user_id: int,
    tenant_id: int,
    db: Session,
    expose_tokens=True,
    refresh_family_id=None,
):
    """签发令牌并设置同站 HttpOnly 会话 Cookie。"""
    # 令牌绑定到当前会话版本，密码重置后旧令牌立即失效。
    user = db.get(User, user_id)
    session_version = user.session_version if user is not None else 0
    access_token = create_access_token(user_id, tenant_id, session_version)
    family_id = refresh_family_id or str(uuid.uuid4())
    token_id = str(uuid.uuid4())
    refresh_token = create_refresh_token(
        user_id, tenant_id, session_version,
        family_id=family_id, token_id=token_id,
    )
    db.add(RefreshToken(
        family_id=family_id,
        token_hash=_token_hash(refresh_token),
        user_id=user_id,
        tenant_id=tenant_id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
    ))
    db.commit()
    cookie_secure = config.session_cookie_secure()
    response.set_cookie(
        ACCESS_TOKEN_COOKIE,
        access_token,
        path="/",
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True,
        secure=cookie_secure,
        samesite="strict",
    )
    response.set_cookie(
        REFRESH_TOKEN_COOKIE,
        refresh_token,
        path="/",
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        httponly=True,
        secure=cookie_secure,
        samesite="strict",
    )
    response.headers["Cache-Control"] = "no-store"
    if not expose_tokens:
        return {"authenticated": True, "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60}
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }


@router.post("/auth/register", status_code=status.HTTP_201_CREATED)
def register(
    request: Request,
    payload: RegisterRequest,
    background_tasks: BackgroundTasks,
    response: Response,
    db: Session = Depends(get_db),
):
    """创建用户、默认租户和 owner membership。"""
    try:
        decision = check_account(payload.email)
    except RateLimitUnavailable:
        _error(status.HTTP_503_SERVICE_UNAVAILABLE, "rate_limit_unavailable")
    if not decision.allowed:
        _error(status.HTTP_429_TOO_MANY_REQUESTS, "rate_limit_exceeded")
    if db.query(User.id).filter(User.email == payload.email).first() is not None:
        verify_password(payload.password, DUMMY_PASSWORD_HASH)
        response.status_code = status.HTTP_202_ACCEPTED
        return {"accepted": True}

    invitation = invitation_for_token(db, payload.invitation_token, for_update=True) if payload.invitation_token else None
    country_code = request_country_code(request)
    public_audit = None
    if payload.audit_id:
        public_audit = db.query(PublicAudit).filter(
            PublicAudit.audit_id == payload.audit_id,
            PublicAudit.expires_at > datetime.now(timezone.utc),
        ).first()
        if public_audit is None:
            _error(status.HTTP_400_BAD_REQUEST, "audit_handoff_expired")
    if payload.invitation_token:
        if invitation is None:
            _error(status.HTTP_400_BAD_REQUEST, "invitation_invalid")
        if invitation.accepted_at is not None:
            _error(status.HTTP_409_CONFLICT, "invitation_already_accepted")
        if is_expired(invitation):
            _error(status.HTTP_410_GONE, "invitation_expired")
        if invitation.email != payload.email:
            _error(status.HTTP_403_FORBIDDEN, "invitation_email_mismatch")
        tenant = db.get(Tenant, invitation.tenant_id)
        if tenant is None:
            _error(status.HTTP_400_BAD_REQUEST, "invitation_invalid")
    else:
        tenant = Tenant(
            name=_tenant_name(db, payload.tenant_name, payload.email),
            plan="trial",
            acquisition_country_code=country_code,
            country_source="cloudflare_signup" if country_code else None,
            trial_ends_at=datetime.now(timezone.utc) + timedelta(days=14),
        )
        tenant.directory_slug = tenant.name

    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        registration_kind="invited" if invitation else "self_service",
        signup_country_code=country_code,
    )
    db.add(user)
    if not payload.invitation_token:
        db.add(tenant)
    try:
        db.flush()
        role = invitation.role if invitation else "owner"
        db.add(Membership(tenant_id=tenant.id, user_id=user.id, role=role))
        record_product_event(
            db,
            "signup_completed",
            tenant_id=tenant.id,
            user_id=user.id,
            anonymous_id=request_visitor(request),
            country_code=country_code,
            properties={"registration_kind": user.registration_kind},
        )
        if payload.acquisition_source or payload.acquisition_medium or payload.acquisition_campaign:
            record_product_event(
                db,
                "signup_attribution",
                tenant_id=tenant.id,
                user_id=user.id,
                anonymous_id=request_visitor(request),
                country_code=country_code,
                properties=sanitize_public_properties({
                    "source": payload.acquisition_source or "direct",
                    "medium": payload.acquisition_medium or "none",
                    "campaign": payload.acquisition_campaign or "",
                    "audit_id": payload.audit_id or "",
                }),
            )
        if invitation:
            invitation.accepted_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(user)
        db.refresh(tenant)
    except IntegrityError:
        db.rollback()
        _error(status.HTTP_409_CONFLICT, "email_already_registered")

    background_tasks.add_task(
        transactional_email.send_welcome_email_safe,
        user.email,
        tenant.name,
        user.id,
    )
    return {
        "user": {"id": user.id, "email": user.email},
        "tenant": {
            "id": tenant.id,
            "name": tenant.name,
            "plan": tenant.plan,
            "trial_ends_at": tenant.trial_ends_at,
        },
        "role": role,
        "audit": json.loads(public_audit.result_json) if public_audit is not None else None,
    }


@router.post("/auth/login")
def login(request: Request, payload: LoginRequest, response: Response, db: Session = Depends(get_db)):
    """验证密码并返回 access/refresh JWT。"""
    try:
        decision = check_account(payload.email)
    except RateLimitUnavailable:
        _error(status.HTTP_503_SERVICE_UNAVAILABLE, "rate_limit_unavailable")
    if not decision.allowed:
        _error(status.HTTP_429_TOO_MANY_REQUESTS, "rate_limit_exceeded")
    user = db.query(User).filter(User.email == payload.email).first()
    if user is None:
        verify_password(payload.password, DUMMY_PASSWORD_HASH)
        _error(status.HTTP_401_UNAUTHORIZED, "invalid_credentials")
    if not verify_password(payload.password, user.password_hash):
        _error(status.HTTP_401_UNAUTHORIZED, "invalid_credentials")

    membership_query = db.query(Membership).filter(Membership.user_id == user.id)
    if payload.tenant_id is not None:
        membership_query = membership_query.filter(Membership.tenant_id == payload.tenant_id)
    membership = membership_query.order_by(Membership.tenant_id).first()
    if membership is None:
        _error(status.HTTP_403_FORBIDDEN, "no_tenant_membership")
    tenant = db.get(Tenant, membership.tenant_id)
    if user.status != "active" or tenant is None or tenant.status != "active":
        _error(status.HTTP_403_FORBIDDEN, "account_disabled")

    user.last_login_at = datetime.now(timezone.utc)
    db.commit()

    return token_response(
        response,
        user.id,
        membership.tenant_id,
        db,
        expose_tokens=request.headers.get("X-CiteAura-Session") != "cookie",
    )


@router.post("/auth/refresh")
def refresh(
    request: Request,
    response: Response,
    payload: RefreshRequest | None = None,
    db: Session = Depends(get_db),
):
    """使用 refresh token 轮换 access 和 refresh token。"""
    token = payload.refresh_token if payload else request.cookies.get(REFRESH_TOKEN_COOKIE)
    if not token:
        _error(status.HTTP_401_UNAUTHORIZED, "invalid_refresh_token")
    try:
        claims = decode_token(token, expected_type="refresh")
        user_id = int(claims["sub"])
        tenant_id = int(claims["tenant_id"])
    except (KeyError, TypeError, ValueError, jwt.PyJWTError, RuntimeError):
        _error(status.HTTP_401_UNAUTHORIZED, "invalid_refresh_token")
    user = db.get(User, user_id)
    membership = db.get(Membership, {"tenant_id": tenant_id, "user_id": user_id})
    tenant = db.get(Tenant, tenant_id)
    if (
        user is None
        or membership is None
        or tenant is None
        or user.status != "active"
        or tenant.status != "active"
        or int(claims.get("sv", -1)) != int(user.session_version)
    ):
        _error(status.HTTP_401_UNAUTHORIZED, "invalid_refresh_token")
    now = datetime.now(timezone.utc)
    stored = db.query(RefreshToken).filter(
        RefreshToken.token_hash == _token_hash(token),
    ).with_for_update().first()
    if (
        stored is None
        or stored.user_id != user_id
        or stored.tenant_id != tenant_id
        or stored.family_id != claims.get("fid")
    ):
        _error(status.HTTP_401_UNAUTHORIZED, "invalid_refresh_token")
    expires_at = stored.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if stored.revoked_at is not None:
        _error(status.HTTP_401_UNAUTHORIZED, "invalid_refresh_token")
    if stored.used_at is not None:
        used_at = stored.used_at
        if used_at.tzinfo is None:
            used_at = used_at.replace(tzinfo=timezone.utc)
        if now - used_at > timedelta(seconds=8):
            db.query(RefreshToken).filter(
                RefreshToken.family_id == stored.family_id,
            ).update({RefreshToken.revoked_at: now}, synchronize_session=False)
            user.session_version += 1
            db.commit()
            _error(status.HTTP_401_UNAUTHORIZED, "refresh_token_reused")
        return token_response(
            response,
            user_id,
            tenant_id,
            db,
            expose_tokens=request.headers.get("X-CiteAura-Session") != "cookie",
            refresh_family_id=stored.family_id,
        )
    if expires_at <= now:
        stored.revoked_at = now
        db.commit()
        _error(status.HTTP_401_UNAUTHORIZED, "invalid_refresh_token")
    stored.used_at = now
    return token_response(
        response,
        user_id,
        tenant_id,
        db,
        expose_tokens=request.headers.get("X-CiteAura-Session") != "cookie",
        refresh_family_id=stored.family_id,
    )


@router.post("/auth/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    """失效当前用户的历史 Token，并清除浏览器会话 Cookie。"""
    authorization = request.headers.get("authorization", "")
    scheme, separator, bearer_token = authorization.partition(" ")
    candidates = []
    if separator and scheme.lower() == "bearer":
        candidates.append((bearer_token.strip(), "access"))
    candidates.extend((
        (request.cookies.get(ACCESS_TOKEN_COOKIE), "access"),
        (request.cookies.get(REFRESH_TOKEN_COOKIE), "refresh"),
    ))
    for token, token_type in candidates:
        if not token:
            continue
        try:
            claims = decode_token(token, expected_type=token_type)
            user = db.get(User, int(claims["sub"]))
        except (KeyError, TypeError, ValueError, jwt.PyJWTError, RuntimeError):
            continue
        if user is not None and int(claims.get("sv", -1)) == int(user.session_version):
            user.session_version += 1
            db.query(RefreshToken).filter(
                RefreshToken.user_id == user.id,
                RefreshToken.revoked_at.is_(None),
            ).update({RefreshToken.revoked_at: datetime.now(timezone.utc)}, synchronize_session=False)
            db.commit()
        continue
    response.delete_cookie(ACCESS_TOKEN_COOKIE, path="/", httponly=True, secure=config.session_cookie_secure(), samesite="strict")
    response.delete_cookie(REFRESH_TOKEN_COOKIE, path="/", httponly=True, secure=config.session_cookie_secure(), samesite="strict")
    response.headers["Cache-Control"] = "no-store"
    return {"ok": True}


@router.post("/auth/password/forgot", status_code=status.HTTP_202_ACCEPTED)
def forgot_password(
    payload: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """对所有邮箱返回相同结果，仅为现有用户发送一次性链接。"""
    if not config.password_reset_email_enabled():
        _error(status.HTTP_503_SERVICE_UNAVAILABLE, "password_reset_email_disabled")
    user = db.query(User).filter(User.email == payload.email).first()
    if user is not None:
        now = datetime.now(timezone.utc)
        recent = db.query(PasswordResetToken.id).filter(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.created_at >= now - timedelta(seconds=60),
        ).first()
        if recent is not None:
            return {"accepted": True}
        db.query(PasswordResetToken).filter(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used_at.is_(None),
        ).update({"used_at": now}, synchronize_session=False)
        token = password_reset.create_token()
        db.add(PasswordResetToken(
            user_id=user.id,
            token_hash=password_reset.token_hash(token),
            expires_at=now + timedelta(minutes=config.password_reset_ttl_minutes()),
        ))
        db.commit()
        background_tasks.add_task(password_reset.send_password_reset_email_safe, user.email, token)
    return {"accepted": True}


@router.post("/auth/password/reset")
def reset_password(payload: ResetPasswordRequest, response: Response, db: Session = Depends(get_db)):
    """使用未过期的一次性 Token 更新密码并清除现有浏览器会话。"""
    now = datetime.now(timezone.utc)
    row = db.query(PasswordResetToken).filter(
        PasswordResetToken.token_hash == password_reset.token_hash(payload.token),
        PasswordResetToken.used_at.is_(None),
    ).with_for_update().first()
    expires_at = row.expires_at if row is not None else None
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if row is None or expires_at is None or expires_at < now:
        _error(status.HTTP_400_BAD_REQUEST, "password_reset_token_invalid")
    user = db.get(User, row.user_id)
    if user is None:
        _error(status.HTTP_400_BAD_REQUEST, "password_reset_token_invalid")
    user.password_hash = hash_password(payload.password)
    user.session_version += 1
    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.used_at.is_(None),
    ).update({"used_at": now}, synchronize_session=False)
    db.commit()
    response.delete_cookie(ACCESS_TOKEN_COOKIE, path="/", httponly=True, secure=config.session_cookie_secure(), samesite="strict")
    response.delete_cookie(REFRESH_TOKEN_COOKIE, path="/", httponly=True, secure=config.session_cookie_secure(), samesite="strict")
    response.headers["Cache-Control"] = "no-store"
    return {"ok": True}


@router.post("/auth/switch-tenant")
def switch_tenant(
    request: Request,
    payload: SwitchTenantRequest,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """切换到当前用户所属的另一个工作区。"""
    membership = db.get(Membership, {"tenant_id": payload.tenant_id, "user_id": current_user.id})
    target_tenant = db.get(Tenant, payload.tenant_id)
    if membership is None or target_tenant is None:
        _error(status.HTTP_404_NOT_FOUND, "tenant_membership_not_found")
    if target_tenant.status != "active":
        _error(status.HTTP_403_FORBIDDEN, "account_disabled")
    return token_response(
        response,
        current_user.id,
        payload.tenant_id,
        db,
        expose_tokens=request.headers.get("X-CiteAura-Session") != "cookie",
    )


@router.get("/me")
def me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """返回当前用户及其当前租户。"""
    tenant = db.get(Tenant, current_user.tenant_id)
    if tenant is None:
        _error(status.HTTP_403_FORBIDDEN, "no_tenant_membership")
    memberships = (
        db.query(Membership, Tenant)
        .join(Tenant, Tenant.id == Membership.tenant_id)
        .filter(Membership.user_id == current_user.id)
        .order_by(Tenant.name)
        .all()
    )
    return {
        "user": {"id": current_user.id, "email": current_user.email},
        "tenant": {
            "id": tenant.id,
            "name": tenant.name,
            "plan": tenant.plan,
            "trial_ends_at": tenant.trial_ends_at,
        },
        "role": getattr(current_user, "tenant_role", "viewer"),
        "workspaces": [
            {"id": workspace.id, "name": workspace.name, "plan": workspace.plan, "role": membership.role}
            for membership, workspace in memberships
        ],
    }
