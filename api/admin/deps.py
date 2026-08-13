"""平台管理员权限依赖。"""

import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session, sessionmaker

from api.admin.audit import record_admin_event
from api.admin.security import ADMIN_COOKIE
from api.auth.security import decode_token
from api.db import get_db
from api.models import PlatformAdmin


ROLE_PERMISSIONS = {
    "support": frozenset(("read",)),
    "ops": frozenset(("read", "operate")),
    "finance": frozenset(("read", "finance")),
    "superadmin": frozenset(("read", "operate", "finance", "admin")),
}


def _unauthorized():
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"error": "invalid_admin_session"},
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_admin(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get(ADMIN_COOKIE)
    if not token:
        _unauthorized()
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and request.headers.get("X-CiteAura-Admin") != "console":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": "csrf_validation_failed"})
    try:
        claims = decode_token(token, expected_type="admin_access")
        admin_id = int(claims["sub"])
    except (KeyError, TypeError, ValueError, RuntimeError, jwt.PyJWTError):
        _unauthorized()
    admin = db.get(PlatformAdmin, admin_id)
    if admin is None or admin.status != "active" or int(claims.get("sv", -1)) != int(admin.session_version):
        _unauthorized()
    outcome = "succeeded"
    try:
        yield admin
    except Exception:
        outcome = "failed"
        raise
    finally:
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            try:
                audit_session = sessionmaker(bind=db.get_bind(), autocommit=False, autoflush=False)
                with audit_session() as audit_db:
                    record_admin_event(
                        audit_db,
                        admin.id,
                        f"admin.api.{request.method.lower()}",
                        request.url.path,
                        outcome=outcome,
                        ip_address=request.client.host if request.client else None,
                    )
                    audit_db.commit()
            except Exception:  # noqa: BLE001 - 审计失败不能覆盖业务响应
                pass


def require_permission(permission):
    def dependency(admin: PlatformAdmin = Depends(get_current_admin)):
        if permission not in ROLE_PERMISSIONS.get(admin.role, ()):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": "insufficient_admin_role"})
        return admin
    return dependency


require_admin_read = require_permission("read")
require_admin_operate = require_permission("operate")
require_admin_finance = require_permission("finance")
require_superadmin = require_permission("admin")
