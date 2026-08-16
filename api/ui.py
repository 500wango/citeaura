"""CiteAura SPA 静态文件服务与项目交付物访问。"""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from api.adapters import engine as engine_adapter
from api.auth.deps import get_current_user
from api.db import get_db
from api.models import Project, Tenant, User

router = APIRouter(tags=["ui"])
WEB_ROOT = Path(__file__).resolve().parents[1] / "web"
APP_INDEX = WEB_ROOT / "app" / "index.html"


@router.get("/app", include_in_schema=False)
@router.get("/app/{path:path}", include_in_schema=False)
@router.get("/ui", include_in_schema=False)
def serve_app():
    """返回 CiteAura SPA 应用外壳。"""
    if not APP_INDEX.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"error": "app_shell_not_found"})
    return FileResponse(APP_INDEX, media_type="text/html; charset=utf-8")


@router.get("/files/{path:path}")
def serve_project_file(path: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """为 UI 提供当前租户项目交付文件，禁止跨租户和路径穿越。"""
    parts = path.split("/", 1)
    if len(parts) != 2 or not parts[0] or ".." in path or "\\" in path:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"error": "invalid_file_path"})
    tenant = db.get(Tenant, current_user.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": "no_tenant_membership"})
    project = db.query(Project).filter(Project.tenant_id == tenant.id, Project.slug == parts[0]).first()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"error": "file_not_found"})
    tenant_directory = engine_adapter.tenant_slug(tenant)
    root = (engine_adapter.WORK_ROOT / tenant_directory / project.slug).resolve()
    target = (root / parts[1]).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"error": "invalid_file_path"}) from None
    if not target.is_file() or parts[1] != "delivery" and not parts[1].startswith("delivery/"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"error": "file_not_found"})
    return FileResponse(target)
