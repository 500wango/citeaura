"""项目 CRUD、Bootstrap 和任务查询 API。"""

from datetime import datetime, timezone
from types import SimpleNamespace
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from api.adapters.engine import geolib, with_tenant_context
from api.adapters.exceptions import GeoEngineError
from api.auth.deps import get_current_user
from api.db import get_db
from api.models import Job, Project, Tenant, User
from api.worker.tasks import task_bootstrap


router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


class ProjectCreate(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    market: str = Field(default="both")
    skip_llm: bool = False

    @field_validator("url")
    @classmethod
    def normalize_url(cls, value: str):
        value = value.strip()
        if not value:
            raise ValueError("url is required")
        if "://" not in value:
            value = "https://" + value
        parsed = urlparse(value)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("url must be a valid http(s) URL")
        return value.rstrip("/")

    @field_validator("market")
    @classmethod
    def validate_market(cls, value: str):
        if value not in ("cn", "global", "both"):
            raise ValueError("market must be cn, global, or both")
        return value


def _error(status_code: int, message: str):
    """抛出统一 API 错误。"""
    raise HTTPException(status_code=status_code, detail={"error": message})


def _tenant_for_user(db: Session, user: User) -> Tenant:
    tenant = db.get(Tenant, user.tenant_id)
    if tenant is None:
        _error(status.HTTP_403_FORBIDDEN, "no_tenant_membership")
    return tenant


def _project_for_user(db: Session, user: User, project_id: int) -> Project:
    tenant = _tenant_for_user(db, user)
    project = (
        db.query(Project)
        .filter(Project.id == project_id, Project.tenant_id == tenant.id)
        .first()
    )
    if project is None:
        _error(status.HTTP_404_NOT_FOUND, "project_not_found")
    return project


def _job_payload(job: Job, include_log: bool = True) -> dict:
    log = ""
    if include_log and job.log_path:
        try:
            with open(job.log_path, "r", encoding="utf-8", errors="replace") as handle:
                log = handle.read()[-20000:]
        except OSError:
            log = ""
    return {
        "id": job.id,
        "project_id": job.project_id,
        "action": job.action,
        "status": job.status,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "error": job.error,
        "log_path": job.log_path,
        "log": log,
    }


@router.post("", status_code=status.HTTP_202_ACCEPTED)
def create_project(
    payload: ProjectCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """创建项目、初始化引擎目录并投递 Bootstrap 任务。"""
    tenant = _tenant_for_user(db, current_user)
    slug = geolib.slugify(payload.url)
    if db.query(Project.id).filter(Project.tenant_id == tenant.id, Project.slug == slug).first() is not None:
        _error(status.HTTP_409_CONFLICT, "project_already_exists")

    project = Project(
        tenant_id=tenant.id,
        slug=slug,
        url=payload.url,
        market=payload.market,
        status="initializing",
    )
    db.add(project)
    db.flush()
    job = Job(project_id=project.id, action="bootstrap", status="queued")
    db.add(job)
    db.commit()
    db.refresh(project)
    db.refresh(job)

    try:
        import geo

        args = SimpleNamespace(
            url=payload.url,
            name=None,
            slug=slug,
            market=payload.market,
            max_pages=25,
            force=False,
        )
        with with_tenant_context(tenant.name, slug):
            geo.cmd_init(args)
    except GeoEngineError as exc:
        project.status = "failed"
        job.status = "failed"
        job.error = str(exc)
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
        _error(status.HTTP_400_BAD_REQUEST, "engine_init_failed")
    except Exception as exc:  # noqa: BLE001
        project.status = "failed"
        job.status = "failed"
        job.error = f"{type(exc).__name__}: {exc}"
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
        _error(status.HTTP_500_INTERNAL_SERVER_ERROR, "project_init_failed")

    project.status = "bootstrapping"
    db.commit()
    try:
        task = task_bootstrap.delay(
            tenant.name,
            slug,
            skip_llm=payload.skip_llm,
            job_id=job.id,
        )
        # Celery task id 不是管线日志路径，但保存后便于排障和轮询关联。
        job.log_path = f"celery://{task.id}"
        db.commit()
    except Exception as exc:  # noqa: BLE001
        project.status = "failed"
        job.status = "failed"
        job.error = f"{type(exc).__name__}: {exc}"
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
        _error(status.HTTP_503_SERVICE_UNAVAILABLE, "worker_unavailable")

    return {"project_id": project.id, "job_id": job.id, "slug": project.slug, "status": project.status}


@router.get("")
def list_projects(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """列出当前租户项目。"""
    tenant = _tenant_for_user(db, current_user)
    projects = (
        db.query(Project)
        .filter(Project.tenant_id == tenant.id)
        .order_by(Project.created_at.desc(), Project.id.desc())
        .all()
    )
    return {
        "projects": [
            {
                "id": p.id,
                "slug": p.slug,
                "url": p.url,
                "market": p.market,
                "status": p.status,
                "created_at": p.created_at,
            }
            for p in projects
        ]
    }


@router.get("/{project_id}")
def project_detail(project_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """返回项目索引和引擎 dashboard 聚合详情。"""
    project = _project_for_user(db, current_user, project_id)
    tenant = _tenant_for_user(db, current_user)
    try:
        with with_tenant_context(tenant.name, project.slug):
            import dashboard

            detail = dashboard.project(project.slug)
            cfg = geolib.load_config(project.slug)
            detail["questions"] = cfg.get("questions", [])
    except GeoEngineError:
        detail = {"slug": project.slug, "brand": {}, "questions": []}
    detail["project"] = {
        "id": project.id,
        "slug": project.slug,
        "url": project.url,
        "market": project.market,
        "status": project.status,
        "created_at": project.created_at,
    }
    return detail


@router.get("/{project_id}/jobs")
def project_jobs(project_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """返回当前项目任务历史。"""
    project = _project_for_user(db, current_user, project_id)
    jobs = db.query(Job).filter(Job.project_id == project.id).order_by(Job.id.desc()).all()
    return {"jobs": [_job_payload(job, include_log=False) for job in jobs]}


@router.get("/{project_id}/jobs/{job_id}")
def project_job(
    project_id: int,
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """返回任务状态、错误和可用日志尾部。"""
    project = _project_for_user(db, current_user, project_id)
    job = db.query(Job).filter(Job.id == job_id, Job.project_id == project.id).first()
    if job is None:
        _error(status.HTTP_404_NOT_FOUND, "job_not_found")
    return {"job": _job_payload(job)}

