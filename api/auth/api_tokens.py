"""可撤销的只读集成令牌。"""

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session

from api.models import ApiAccessToken, Tenant


TOKEN_PREFIX = "ca_"
LAST_USED_WRITE_INTERVAL = timedelta(minutes=15)
DEFAULT_TTL_DAYS = 90
DEFAULT_SCOPES = ("read",)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def issue(db: Session, tenant: Tenant, name: str, ttl_days: int = DEFAULT_TTL_DAYS, created_by_user_id=None):
    """签发只读令牌；原文只在创建响应中返回一次。"""
    raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
    try:
        requested_ttl = int(ttl_days if ttl_days is not None else DEFAULT_TTL_DAYS)
    except (TypeError, ValueError):
        requested_ttl = DEFAULT_TTL_DAYS
    ttl_days = max(1, min(requested_ttl, 365))
    row = ApiAccessToken(
        tenant_id=tenant.id,
        created_by_user_id=created_by_user_id,
        name=name.strip(),
        token_prefix=raw[:12],
        token_hash=_hash(raw),
        scopes=json.dumps(list(DEFAULT_SCOPES)),
        # 没有过期时间的集成令牌等同于永久凭证，一旦泄露无法自然失效。
        expires_at=datetime.now(timezone.utc) + timedelta(days=ttl_days),
    )
    db.add(row)
    db.flush()
    return row, raw


def token_is_expired(row, now=None):
    expires_at = getattr(row, "expires_at", None)
    if expires_at is None:
        return False
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at <= (now or datetime.now(timezone.utc))


def token_scopes(row):
    try:
        values = json.loads(row.scopes or "[]")
    except (TypeError, ValueError):
        return ()
    return tuple(item for item in values if isinstance(item, str))


def require_scopes(row, *scopes):
    """校验令牌具备所需 scopes；未授予时直接 403。"""
    granted = set(token_scopes(row))
    missing = [scope for scope in scopes if scope not in granted]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "api_token_scope_denied", "required": missing},
        )
    return row


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
    if token_is_expired(row):
        row.revoked_at = row.revoked_at or datetime.now(timezone.utc)
        db.commit()
        return None
    now = datetime.now(timezone.utc)
    last_used = row.last_used_at
    if last_used is None or (last_used.tzinfo is None and now - last_used.replace(tzinfo=timezone.utc) >= LAST_USED_WRITE_INTERVAL) or (
        last_used is not None and last_used.tzinfo is not None and now - last_used >= LAST_USED_WRITE_INTERVAL
    ):
        row.last_used_at = now
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
