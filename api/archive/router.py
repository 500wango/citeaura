"""项目对象存储归档和恢复 API。"""

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.adapters import archive
from api.adapters.engine import job_log_path
from api.auth.deps import get_current_user, require_owner
from api.db import get_db
from api.models import Job, Project, Tenant, User
from api.worker.tasks import task_archive_project, task_restore_project


router = APIRouter(prefix="/api/v1/projects", tags=["archives"])


class RestorePayload(BaseModel):
    overwrite: bool = False
    confirmed: bool = False
    confirmation_text: str = ""


def _error(status_code, message):
    raise HTTPException(status_code=status_code, detail={"error": message})


def _records(db, user, project_id):
    tenant = db.get(Tenant, user.tenant_id)
    if tenant is None:
        _error(status.HTTP_403_FORBIDDEN, "no_tenant_membership")
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.tenant_id == tenant.id,
    ).first()
    if project is None:
        _error(status.HTTP_404_NOT_FOUND, "project_not_found")
    return tenant, project


def _archive_entry(tenant, project, archive_id):
    try:
        entries = archive.list_archives(tenant.name, project.slug)
    except archive.ArchiveError as exc:
        _error(status.HTTP_409_CONFLICT, str(exc))
    entry = next((item for item in entries if item.get("id") == archive_id), None)
    if entry is None:
        _error(status.HTTP_404_NOT_FOUND, "archive_not_found")
    if entry.get("status") != "available":
        _error(status.HTTP_409_CONFLICT, "archive_not_available")
    return entry


def _active_job(db, project_id):
    return db.query(Job.id).filter(
        Job.project_id == project_id,
        Job.status.in_(("queued", "running")),
    ).first()


def _enqueue(db, tenant, project, action, task, *task_args):
    if _active_job(db, project.id) is not None:
        _error(status.HTTP_409_CONFLICT, "project_job_already_running")
    previous_status = project.status
    request_json = {}
    if action == "archive_restore":
        request_json = {"archive_id": task_args[0], "overwrite": bool(task_args[1])}
    job = Job(project_id=project.id, action=action, status="queued", request_json=json.dumps(request_json))
    db.add(job)
    project.status = "archiving" if action == "archive" else "restoring"
    db.commit()
    db.refresh(job)
    job.log_path = str(job_log_path(tenant.name, project.slug, job.id))
    db.commit()
    try:
        task.delay(tenant.name, project.slug, *task_args, job_id=job.id)
    except Exception as exc:  # noqa: BLE001
        job.status = "failed"
        job.error = f"{type(exc).__name__}: {exc}"
        job.finished_at = datetime.now(timezone.utc)
        project.status = previous_status
        db.commit()
        _error(status.HTTP_503_SERVICE_UNAVAILABLE, "worker_unavailable")
    return {"job_id": job.id, "project_id": project.id, "action": action, "status": project.status}


@router.get("/{project_id}/archives")
def archives(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """返回项目归档清单和非敏感存储状态。"""
    tenant, project = _records(db, current_user, project_id)
    try:
        entries = archive.list_archives(tenant.name, project.slug)
        storage = archive.storage_status()
    except archive.ArchiveError as exc:
        _error(status.HTTP_409_CONFLICT, str(exc))
    return {
        "project_id": project.id,
        "project_slug": project.slug,
        "can_manage": getattr(current_user, "tenant_role", None) == "owner",
        "storage": storage,
        "archives": entries,
    }


@router.post("/{project_id}/archives", status_code=status.HTTP_202_ACCEPTED)
def create_project_archive(
    project_id: int,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """投递项目快照归档任务。"""
    tenant, project = _records(db, current_user, project_id)
    try:
        if not archive.storage_status()["configured"]:
            _error(status.HTTP_503_SERVICE_UNAVAILABLE, "object_storage_not_configured")
    except archive.ArchiveError as exc:
        _error(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc))
    return _enqueue(db, tenant, project, "archive", task_archive_project)


@router.post("/{project_id}/archives/{archive_id}/restore", status_code=status.HTTP_202_ACCEPTED)
def restore_project_archive(
    project_id: int,
    archive_id: str,
    payload: RestorePayload,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """经人工确认后投递归档恢复任务。"""
    tenant, project = _records(db, current_user, project_id)
    _archive_entry(tenant, project, archive_id)
    if not payload.confirmed or payload.confirmation_text != f"RESTORE {archive_id}":
        _error(status.HTTP_400_BAD_REQUEST, "archive_restore_confirmation_required")
    return _enqueue(
        db,
        tenant,
        project,
        "archive_restore",
        task_restore_project,
        archive_id,
        payload.overwrite,
    )
