"""认证依赖。"""

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker

from api.audit import record_event
from api.db import get_db
from api.models import Membership, User
from api.auth.security import ACCESS_TOKEN_COOKIE, decode_token


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


def _unauthorized(error: str):
    """构造统一的 401 错误。"""
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"error": error},
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    request: Request,
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
):
    """验证 access token 并返回当前用户。"""
    token = token or request.cookies.get(ACCESS_TOKEN_COOKIE)
    if not token:
        _unauthorized("invalid_token")
    try:
        payload = decode_token(token, expected_type="access")
        user_id = int(payload["sub"])
        tenant_id = int(payload["tenant_id"])
    except (KeyError, TypeError, ValueError, jwt.PyJWTError, RuntimeError):
        _unauthorized("invalid_token")

    user = db.get(User, user_id)
    membership = db.get(Membership, {"tenant_id": tenant_id, "user_id": user_id})
    if user is None or membership is None:
        _unauthorized("invalid_token")

    # 后续租户路由统一从 current_user.tenant_id 读取当前 token 的租户。
    user.tenant_id = tenant_id
    user.tenant_role = membership.role
    outcome = "succeeded"
    try:
        yield user
    except Exception:
        outcome = "failed"
        raise
    finally:
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            try:
                audit_session = sessionmaker(bind=db.get_bind(), autocommit=False, autoflush=False)
                with audit_session() as audit_db:
                    record_event(
                        audit_db,
                        tenant_id,
                        f"api.{request.method.lower()}",
                        request.url.path,
                        outcome=outcome,
                        user_id=user.id,
                        ip_address=request.client.host if request.client else None,
                    )
                    audit_db.commit()
            except Exception:  # noqa: BLE001 - 审计写入失败不能覆盖业务响应
                pass


def require_roles(*allowed_roles):
    """构造按当前租户 membership 校验的角色依赖。"""
    allowed = frozenset(allowed_roles)

    def dependency(current_user: User = Depends(get_current_user)):
        if getattr(current_user, "tenant_role", None) not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": "insufficient_role"})
        return current_user

    return dependency


require_owner = require_roles("owner")
require_editor = require_roles("owner", "editor")
