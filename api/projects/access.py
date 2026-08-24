"""项目 API 的租户和项目访问边界。"""

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from api.models import Project, Tenant, User


def error(status_code: int, message: str):
    """抛出统一 API 错误。"""
    raise HTTPException(status_code=status_code, detail={"error": message})


def tenant_for_user(db: Session, user: User, for_update=False) -> Tenant:
    if for_update:
        tenant = db.query(Tenant).filter(Tenant.id == user.tenant_id).with_for_update().first()
    else:
        tenant = db.get(Tenant, user.tenant_id)
    if tenant is None:
        error(status.HTTP_403_FORBIDDEN, "no_tenant_membership")
    return tenant


def project_for_user(db: Session, user: User, project_id: int) -> Project:
    tenant = tenant_for_user(db, user)
    project = (
        db.query(Project)
        .filter(
            Project.id == project_id,
            Project.tenant_id == tenant.id,
            Project.archived_at.is_(None),
            Project.status != "archived",
        )
        .first()
    )
    if project is None:
        error(status.HTTP_404_NOT_FOUND, "project_not_found")
    return project
