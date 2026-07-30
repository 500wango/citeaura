"""注册、登录和当前用户 API。"""

import re
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.auth.deps import get_current_user
from api.auth.security import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
)
from api.db import get_db
from api.models import Membership, Tenant, User


router = APIRouter(prefix="/api/v1")


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=128)
    tenant_name: str | None = Field(default=None, max_length=128)

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

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str):
        return value.strip().lower()


def _error(status_code: int, message: str):
    """抛出统一错误响应。"""
    raise HTTPException(status_code=status_code, detail={"error": message})


def _tenant_name(db: Session, requested: str | None, email: str) -> str:
    """生成唯一的默认租户名称，避免文件系统目录冲突。"""
    base = (requested or email.split("@", 1)[0]).strip() or "workspace"
    base = re.sub(r"[^a-zA-Z0-9一-鿿_-]+", "-", base).strip("-_")[:110] or "workspace"
    candidate = base
    if db.query(Tenant.id).filter(Tenant.name == candidate).first() is None:
        return candidate
    return f"{base[:100]}-{uuid.uuid4().hex[:8]}"


@router.post("/auth/register", status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    """创建用户、默认租户和 owner membership。"""
    if db.query(User.id).filter(User.email == payload.email).first() is not None:
        _error(status.HTTP_409_CONFLICT, "email_already_registered")

    user = User(email=payload.email, password_hash=hash_password(payload.password))
    tenant = Tenant(
        name=_tenant_name(db, payload.tenant_name, payload.email),
        plan="trial",
        trial_ends_at=datetime.now(timezone.utc) + timedelta(days=14),
    )
    db.add_all([user, tenant])
    try:
        db.flush()
        db.add(Membership(tenant_id=tenant.id, user_id=user.id, role="owner"))
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
    }


@router.post("/auth/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    """验证密码并返回 access/refresh JWT。"""
    user = db.query(User).filter(User.email == payload.email).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        _error(status.HTTP_401_UNAUTHORIZED, "invalid_credentials")

    membership = (
        db.query(Membership)
        .filter(Membership.user_id == user.id)
        .order_by(Membership.tenant_id)
        .first()
    )
    if membership is None:
        _error(status.HTTP_403_FORBIDDEN, "no_tenant_membership")

    return {
        "access_token": create_access_token(user.id, membership.tenant_id),
        "refresh_token": create_refresh_token(user.id, membership.tenant_id),
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }


@router.get("/me")
def me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """返回当前用户及其当前租户。"""
    tenant = db.get(Tenant, current_user.tenant_id)
    if tenant is None:
        _error(status.HTTP_403_FORBIDDEN, "no_tenant_membership")
    return {
        "user": {"id": current_user.id, "email": current_user.email},
        "tenant": {
            "id": tenant.id,
            "name": tenant.name,
            "plan": tenant.plan,
            "trial_ends_at": tenant.trial_ends_at,
        },
        "role": getattr(current_user, "tenant_role", "viewer"),
    }
