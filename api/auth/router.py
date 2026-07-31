"""注册、登录和当前用户 API。"""

import re
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api import config
from api.adapters.engine import tenant_slug
from api.auth.deps import get_current_user
from api.auth.security import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    ACCESS_TOKEN_COOKIE,
    REFRESH_TOKEN_COOKIE,
    REFRESH_TOKEN_EXPIRE_DAYS,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from api.db import get_db
from api.models import Membership, Tenant, User
from api.team.invitations import invitation_for_token, is_expired


router = APIRouter(prefix="/api/v1")


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=128)
    tenant_name: str | None = Field(default=None, max_length=128)
    invitation_token: str | None = Field(default=None, min_length=20, max_length=512)

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


class SwitchTenantRequest(BaseModel):
    tenant_id: int = Field(ge=1)


def _error(status_code: int, message: str):
    """抛出统一错误响应。"""
    raise HTTPException(status_code=status_code, detail={"error": message})


def _tenant_name(db: Session, requested: str | None, email: str) -> str:
    """生成唯一的默认租户名称，避免文件系统目录冲突。"""
    base = tenant_slug((requested or email.split("@", 1)[0]).strip() or "workspace")
    candidate = base
    while db.query(Tenant.id).filter(Tenant.name == candidate).first() is not None:
        candidate = f"{base[:39]}-{uuid.uuid4().hex[:8]}"
    return candidate


def token_response(response: Response, user_id: int, tenant_id: int):
    """签发令牌并设置同站 HttpOnly 会话 Cookie。"""
    access_token = create_access_token(user_id, tenant_id)
    refresh_token = create_refresh_token(user_id, tenant_id)
    cookie_secure = config.session_cookie_secure()
    response.set_cookie(
        ACCESS_TOKEN_COOKIE,
        access_token,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True,
        secure=cookie_secure,
        samesite="strict",
    )
    response.set_cookie(
        REFRESH_TOKEN_COOKIE,
        refresh_token,
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        httponly=True,
        secure=cookie_secure,
        samesite="strict",
    )
    response.headers["Cache-Control"] = "no-store"
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }


@router.post("/auth/register", status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    """创建用户、默认租户和 owner membership。"""
    if db.query(User.id).filter(User.email == payload.email).first() is not None:
        _error(status.HTTP_409_CONFLICT, "email_already_registered")

    invitation = invitation_for_token(db, payload.invitation_token, for_update=True) if payload.invitation_token else None
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
            trial_ends_at=datetime.now(timezone.utc) + timedelta(days=14),
        )

    user = User(email=payload.email, password_hash=hash_password(payload.password))
    db.add(user)
    if not payload.invitation_token:
        db.add(tenant)
    try:
        db.flush()
        role = invitation.role if invitation else "owner"
        db.add(Membership(tenant_id=tenant.id, user_id=user.id, role=role))
        if invitation:
            invitation.accepted_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(user)
        db.refresh(tenant)
    except IntegrityError:
        db.rollback()
        _error(status.HTTP_409_CONFLICT, "email_already_registered")

    return {
        "user": {"id": user.id, "email": user.email},
        "tenant": {
            "id": tenant.id,
            "name": tenant.name,
            "plan": tenant.plan,
            "trial_ends_at": tenant.trial_ends_at,
        },
        "role": role,
    }


@router.post("/auth/login")
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)):
    """验证密码并返回 access/refresh JWT。"""
    user = db.query(User).filter(User.email == payload.email).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        _error(status.HTTP_401_UNAUTHORIZED, "invalid_credentials")

    membership_query = db.query(Membership).filter(Membership.user_id == user.id)
    if payload.tenant_id is not None:
        membership_query = membership_query.filter(Membership.tenant_id == payload.tenant_id)
    membership = membership_query.order_by(Membership.tenant_id).first()
    if membership is None:
        _error(status.HTTP_403_FORBIDDEN, "no_tenant_membership")

    return token_response(response, user.id, membership.tenant_id)


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
    if user is None or membership is None:
        _error(status.HTTP_401_UNAUTHORIZED, "invalid_refresh_token")
    return token_response(response, user_id, tenant_id)


@router.post("/auth/switch-tenant")
def switch_tenant(
    payload: SwitchTenantRequest,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """切换到当前用户所属的另一个工作区。"""
    membership = db.get(Membership, {"tenant_id": payload.tenant_id, "user_id": current_user.id})
    if membership is None:
        _error(status.HTTP_404_NOT_FOUND, "tenant_membership_not_found")
    return token_response(response, current_user.id, payload.tenant_id)


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
