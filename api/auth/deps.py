"""认证依赖。"""

import jwt
from fastapi import BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker

from api.audit import record_event
from api.db import get_db
from api.models import Membership, Tenant, User
from api.auth.security import ACCESS_TOKEN_COOKIE, decode_token


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


def _write_request_audit(bind, tenant_id, action, target, outcome, user_id, ip_address):
    audit_session = sessionmaker(bind=bind, autocommit=False, autoflush=False)
    with audit_session() as audit_db:
        record_event(
            audit_db,
            tenant_id,
            action,
            target,
            outcome=outcome,
            user_id=user_id,
            ip_address=ip_address,
        )
        audit_db.commit()


def _write_scheduled_request_audit(payload):
    if payload.get("skip"):
        return
    _write_request_audit(
        payload["bind"],
        payload["tenant_id"],
        payload["action"],
        payload["target"],
        payload["outcome"],
        payload["user_id"],
        payload["ip_address"],
    )


def _unauthorized(error: str):
    """构造统一的 401 错误。"""
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"error": error},
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    request: Request,
    background_tasks: BackgroundTasks,
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
):
    """验证 access token 并返回当前用户。"""
    bearer_token = token
    token = bearer_token or request.cookies.get(ACCESS_TOKEN_COOKIE)
    if not token:
        _unauthorized("invalid_token")
    if (
        bearer_token is None
        and request.method in ("POST", "PUT", "PATCH", "DELETE")
        and request.headers.get("X-CiteAura-Session") != "cookie"
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": "csrf_validation_failed"})
    try:
        payload = decode_token(token, expected_type="access")
        user_id = int(payload["sub"])
        tenant_id = int(payload["tenant_id"])
    except (KeyError, TypeError, ValueError, jwt.PyJWTError, RuntimeError):
        _unauthorized("invalid_token")

    user = db.get(User, user_id)
    membership = db.get(Membership, {"tenant_id": tenant_id, "user_id": user_id})
    tenant = db.get(Tenant, tenant_id)
    if (
        user is None
        or membership is None
        or tenant is None
        or user.status != "active"
        or tenant.status != "active"
        or int(payload.get("sv", -1)) != int(user.session_version)
    ):
        _unauthorized("invalid_token")

    # 后续租户路由统一从 current_user.tenant_id 读取当前 token 的租户。
    user.tenant_id = tenant_id
    user.tenant_role = membership.role
    audit_payload = None
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        audit_payload = {
            "bind": db.get_bind(),
            "tenant_id": tenant_id,
            "action": f"api.{request.method.lower()}",
            "target": request.url.path,
            "outcome": "succeeded",
            "user_id": user.id,
            "ip_address": request.client.host if request.client else None,
            "skip": False,
        }
        background_tasks.add_task(_write_scheduled_request_audit, audit_payload)
    try:
        yield user
    except Exception:
        if audit_payload is not None:
            audit_payload["outcome"] = "failed"
            audit_payload["skip"] = True
            try:
                _write_request_audit(
                    audit_payload["bind"],
                    audit_payload["tenant_id"],
                    audit_payload["action"],
                    audit_payload["target"],
                    audit_payload["outcome"],
                    audit_payload["user_id"],
                    audit_payload["ip_address"],
                )
            except Exception:  # noqa: BLE001 - 审计写入失败不能覆盖业务响应
                pass
        raise


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
