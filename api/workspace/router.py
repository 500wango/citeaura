"""问题库、资产、事实库和内容工作台 API。"""

from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.adapters.engine import with_tenant_context
from api.adapters.exceptions import GeoEngineError
from api.adapters import workspace
from api.adapters.preflight import PreflightError, normalize_url
from api.auth.deps import get_current_user, require_editor
from api.billing.limits import check_sample_run
from api.db import get_db
from api.models import Job, Project, Tenant, User


router = APIRouter(tags=["workspace"])


class TextRequest(BaseModel):
    text: str = Field(default="", max_length=2_000_000)


class AssetRequest(TextRequest):
    path: str = Field(min_length=1, max_length=1024)


class FactcheckRequest(BaseModel):
    items: list[dict] = Field(max_length=1000)


class DistributionRequest(BaseModel):
    qid: str = Field(min_length=1, max_length=64)
    channel: str = Field(min_length=1, max_length=256)
    on: bool = False


class QuestionsRequest(BaseModel):
    items: list[dict] = Field(min_length=1, max_length=200)


class SampleImportRequest(BaseModel):
    file: str = Field(min_length=1, max_length=128)
    text: str = Field(max_length=5_000_000)


def _error(status_code: int, message: str):
    raise HTTPException(status_code=status_code, detail={"error": message})


def _tenant_project(db: Session, user: User, project_id: int):
    tenant = db.get(Tenant, user.tenant_id)
    if tenant is None:
        _error(status.HTTP_403_FORBIDDEN, "no_tenant_membership")
    project = db.query(Project).filter(Project.id == project_id, Project.tenant_id == tenant.id).first()
    if project is None:
        _error(status.HTTP_404_NOT_FOUND, "project_not_found")
    return tenant, project


def _ensure_idle(db: Session, project: Project):
    active = db.query(Job.id).filter(
        Job.project_id == project.id,
        Job.status.in_(("queued", "running")),
    ).first()
    if active is not None:
        _error(status.HTTP_409_CONFLICT, "project_job_already_running")


def _call(db, user, project_id, function, *args):
    tenant, project = _tenant_project(db, user, project_id)
    try:
        with with_tenant_context(tenant.name, project.slug):
            return function(project.slug, *args)
    except FileNotFoundError:
        _error(status.HTTP_404_NOT_FOUND, "workspace_file_not_found")
    except (GeoEngineError, PermissionError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "workspace_operation_failed", "detail": str(exc)},
        ) from exc


@router.get("/api/v1/projects/{project_id}/config")
def project_config(project_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _call(db, current_user, project_id, workspace.read_config)


@router.get("/api/v1/projects/{project_id}/questions")
def project_questions(project_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    config = _call(db, current_user, project_id, workspace.read_config)
    return {"questions": config.get("questions", [])}


@router.patch("/api/v1/projects/{project_id}/config")
def update_project_config(
    project_id: int,
    payload: dict = Body(...),
    current_user: User = Depends(require_editor),
    db: Session = Depends(get_db),
):
    _, project = _tenant_project(db, current_user, project_id)
    _ensure_idle(db, project)
    updates = dict(payload)
    normalized_url = None
    if "url" in updates:
        try:
            normalized_url = normalize_url(updates["url"])
        except PreflightError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"error": "invalid_project_url", "detail": str(exc)},
            ) from exc
        updates["url"] = normalized_url
    config = _call(db, current_user, project_id, workspace.update_config, updates)
    if normalized_url is not None:
        project.url = normalized_url
    project.market = "both"
    db.commit()
    return {"ok": True, "config": config}


@router.get("/api/v1/projects/{project_id}/facts")
def project_facts(project_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _call(db, current_user, project_id, workspace.facts_source)


@router.put("/api/v1/projects/{project_id}/facts")
def update_project_facts(
    project_id: int,
    payload: TextRequest,
    current_user: User = Depends(require_editor),
    db: Session = Depends(get_db),
):
    _, project = _tenant_project(db, current_user, project_id)
    _ensure_idle(db, project)
    _call(db, current_user, project_id, workspace.save_facts, payload.text)
    return {"ok": True}


@router.get("/api/v1/projects/{project_id}/assets")
def project_assets(project_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _call(db, current_user, project_id, workspace.asset_tree)


@router.get("/api/v1/projects/{project_id}/asset")
def project_asset(
    project_id: int,
    path: str = Query(min_length=1, max_length=1024),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _call(db, current_user, project_id, workspace.read_asset, path)


@router.put("/api/v1/projects/{project_id}/asset")
def update_project_asset(
    project_id: int,
    payload: AssetRequest,
    current_user: User = Depends(require_editor),
    db: Session = Depends(get_db),
):
    _, project = _tenant_project(db, current_user, project_id)
    _ensure_idle(db, project)
    _call(db, current_user, project_id, workspace.save_asset, payload.path, payload.text)
    return {"ok": True}


@router.get("/api/v1/projects/{project_id}/workbench")
def project_workbench(
    project_id: int,
    qid: str = Query(default="", max_length=64),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _call(db, current_user, project_id, workspace.workbench, qid)


@router.post("/api/v1/workspace/precheck")
def content_precheck(payload: TextRequest, current_user: User = Depends(get_current_user)):
    return workspace.precheck(payload.text)


@router.get("/api/v1/projects/{project_id}/factcheck")
def project_factcheck(project_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _call(db, current_user, project_id, workspace.factcheck)


@router.put("/api/v1/projects/{project_id}/factcheck")
def update_project_factcheck(
    project_id: int,
    payload: FactcheckRequest,
    current_user: User = Depends(require_editor),
    db: Session = Depends(get_db),
):
    _, project = _tenant_project(db, current_user, project_id)
    _ensure_idle(db, project)
    _call(db, current_user, project_id, workspace.save_factcheck, payload.items)
    return {"ok": True, "count": len(payload.items)}


@router.put("/api/v1/projects/{project_id}/distribution")
def update_project_distribution(
    project_id: int,
    payload: DistributionRequest,
    current_user: User = Depends(require_editor),
    db: Session = Depends(get_db),
):
    _, project = _tenant_project(db, current_user, project_id)
    _ensure_idle(db, project)
    distribution = _call(
        db,
        current_user,
        project_id,
        workspace.update_distribution,
        payload.qid,
        payload.channel,
        payload.on,
    )
    return {"ok": True, "distribution": distribution}


@router.get("/api/v1/projects/{project_id}/content")
def project_content(
    project_id: int,
    path: str | None = Query(default=None, max_length=1024),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _call(db, current_user, project_id, workspace.read_content, path)


@router.put("/api/v1/projects/{project_id}/content")
def update_project_content(
    project_id: int,
    payload: AssetRequest,
    current_user: User = Depends(require_editor),
    db: Session = Depends(get_db),
):
    _, project = _tenant_project(db, current_user, project_id)
    _ensure_idle(db, project)
    _call(db, current_user, project_id, workspace.save_content, payload.path, payload.text)
    return {"ok": True}


@router.get("/api/v1/projects/{project_id}/expand")
def project_expansion(project_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _call(db, current_user, project_id, workspace.expansion)


@router.post("/api/v1/projects/{project_id}/questions")
def add_project_questions(
    project_id: int,
    payload: QuestionsRequest,
    current_user: User = Depends(require_editor),
    db: Session = Depends(get_db),
):
    _, project = _tenant_project(db, current_user, project_id)
    _ensure_idle(db, project)
    added = _call(db, current_user, project_id, workspace.add_questions, payload.items)
    return {"ok": True, "added": len(added), "ids": [question["id"] for question in added]}


@router.get("/api/v1/projects/{project_id}/files")
def project_files(project_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _call(db, current_user, project_id, workspace.project_files)


@router.post("/api/v1/projects/{project_id}/samples/import")
def import_project_samples(
    project_id: int,
    payload: SampleImportRequest,
    current_user: User = Depends(require_editor),
    db: Session = Depends(get_db),
):
    tenant, project = _tenant_project(db, current_user, project_id)
    check_sample_run(db, tenant, project)
    _ensure_idle(db, project)
    started_at = datetime.now(timezone.utc)
    job = Job(
        project_id=project.id,
        action="sample-import",
        status="running",
        stage="importing",
        progress=25,
        request_json='{"source":"manual"}',
        started_at=started_at,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    try:
        metrics = _call(
            db,
            current_user,
            project_id,
            workspace.import_sample_sheet,
            payload.file,
            payload.text,
        )
    except Exception:
        db.delete(job)
        db.commit()
        raise
    job.status = "done"
    job.stage = "complete"
    job.progress = 100
    job.finished_at = datetime.now(timezone.utc)
    db.commit()
    return {
        "ok": True,
        "job_id": job.id,
        "date": metrics.get("date"),
        "sample_count": metrics.get("sample_count", 0),
    }
