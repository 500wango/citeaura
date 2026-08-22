"""可撤销的只读集成令牌。"""

import hashlib
import secrets
from datetime import datetime, timezone

from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session

from api.models import ApiAccessToken, Tenant


TOKEN_PREFIX = "ca_"


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def issue(db: Session, tenant: Tenant, name: str):
    """签发只读令牌；原文只在创建响应中返回一次。"""
    raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
    row = ApiAccessToken(
        tenant_id=tenant.id,
        name=name.strip(),
        token_prefix=raw[:12],
        token_hash=_hash(raw),
        scopes='["read"]',
    )
    db.add(row)
    db.flush()
    return row, raw


def resolve(db: Session, raw: str | None):
    """按摘要解析未撤销令牌，并记录最近使用时间。"""
    value = str(raw or "").strip()
    if not value.startswith(TOKEN_PREFIX) or len(value) < 24:
        return None
    row = db.query(ApiAccessToken).filter(
        ApiAccessToken.token_hash == _hash(value),
        ApiAccessToken.revoked_at.is_(None),
    ).first()
    if row is None:
        return None
    row.last_used_at = datetime.now(timezone.utc)
    db.commit()
    return row


def require(request: Request, db: Session):
    """解析 Authorization Bearer 中的 API Token。"""
    header = request.headers.get("Authorization", "")
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer" or not value:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "api_token_required"},
            headers={"WWW-Authenticate": "Bearer"},
        )
    row = resolve(db, value)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "api_token_invalid"},
            headers={"WWW-Authenticate": "Bearer"},
        )
    return row
