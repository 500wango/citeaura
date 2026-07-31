"""项目 CRUD、Bootstrap 和任务查询 API。"""

import io
import re
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from api.adapters.engine import ENGINE_KEY_ENV, geolib, job_log_path, load_tenant_keys, with_tenant_context
from api.adapters.exceptions import GeoEngineError
from api.adapters import framing, workspace
from api.auth.deps import get_current_user, require_editor, require_owner
from api.billing.limits import check_project_creation, check_sample_run
from api.billing.platform_pool import PAID_PLANS, public_catalog, usage_summary
from api.db import get_db
from api.models import ApiKey, Job, Project, Tenant, User
from api.worker.tasks import PIPELINE_ACTIONS, task_bootstrap, task_deliver, task_pipeline, task_sample, task_verify


router = APIRouter(prefix="/api/v1/projects", tags=["projects"])
PLAYBOOK_PRIORITY = {"P0": 0, "P1": 1, "P2": 2}
PLAYBOOK_EFFORT = {"S": 0, "M": 1, "L": 2}


class ProjectCreate(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    name: str | None = Field(default=None, max_length=128)
    skip_llm: bool = False
    no_sample: bool = False

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

class SampleRequest(BaseModel):
    limit: int | None = Field(default=None, ge=1, le=1000)
    platforms: list[str] | None = None


class TicketUpdate(BaseModel):
    status: str
    note: str = Field(default="", max_length=2000)

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str):
        if value not in ("todo", "doing", "done", "blocked", "wontfix"):
            raise ValueError("invalid ticket status")
        return value


class OffsiteTicketCreate(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    ask_text: str = Field(min_length=1, max_length=5000)
    influenced_questions: list[str] = Field(min_length=1, max_length=200)


class PipelineActionRequest(BaseModel):
    params: dict = Field(default_factory=dict)


class ScheduleRequest(BaseModel):
    interval_days: int = 0

    @field_validator("interval_days")
    @classmethod
    def validate_interval_days(cls, value: int):
        if value not in (0, 7, 14, 30):
            raise ValueError("interval_days must be 0, 7, 14, or 30")
        return value


class SamplingFundingRequest(BaseModel):
    platform_pool_enabled: bool


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


def _job_payload(job: Job, include_log: bool = True, log_offset: int | None = None) -> dict:
    log = ""
    next_offset = 0
    if include_log and job.log_path:
        try:
            with open(job.log_path, "r", encoding="utf-8", errors="replace") as handle:
                contents = handle.read()
            if log_offset is None:
                log = contents[-20000:]
                next_offset = len(contents)
            else:
                start = min(log_offset, len(contents))
                log = contents[start:start + 20000]
                next_offset = start + len(log)
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
        "log_offset": next_offset,
    }


def _latest_file(directory: Path, pattern: str):
    files = sorted(directory.glob(pattern)) if directory.exists() else []
    return files[-1] if files else None


def _active_job(db: Session, project_id: int):
    return db.query(Job).filter(
        Job.project_id == project_id,
        Job.status.in_(("queued", "running")),
    ).order_by(Job.id.desc()).first()


def _schedule_payload(project: Project):
    return {
        "enabled": project.schedule_interval_days in (7, 14, 30),
        "interval_days": project.schedule_interval_days or 0,
        "next_run_at": project.schedule_next_run_at,
        "last_enqueued_at": project.schedule_last_enqueued_at,
    }


def _competitor_discovery_payload(config):
    """返回自动发现竞品的候选与采样确认状态。"""
    items = []
    for competitor in config.get("competitors", []) or []:
        name = competitor.get("name") if isinstance(competitor, dict) else None
        if not isinstance(name, str) or not name.strip():
            continue
        aliases = competitor.get("aliases", [])
        aliases = aliases if isinstance(aliases, list) else []
        confirmed = competitor.get("confirmed")
        if confirmed is True:
            discovery_status = "sample_confirmed"
        elif confirmed is False:
            discovery_status = "candidate"
        else:
            discovery_status = "configured"
        items.append({
            "name": name.strip(),
            "aliases": [alias for alias in aliases if isinstance(alias, str) and alias],
            "market": competitor.get("market", "both"),
            "discovery_status": discovery_status,
        })
    return {
        "items": items,
        "summary": {
            "total": len(items),
            "sample_confirmed": sum(item["discovery_status"] == "sample_confirmed" for item in items),
            "candidate": sum(item["discovery_status"] == "candidate" for item in items),
            "configured": sum(item["discovery_status"] == "configured" for item in items),
        },
    }


def _sampling_funding_payload(db, tenant, project, user):
    byok = sorted(load_tenant_keys(db, tenant.id))
    catalog = public_catalog()
    pool_codes = {item["engine_code"] for item in catalog}
    effective = []
    for code in sorted(set(ENGINE_KEY_ENV) | pool_codes):
        if code in byok:
            source = "byok"
        elif project.platform_pool_enabled and tenant.plan in PAID_PLANS and code in pool_codes:
            source = "platform_pool"
        else:
            source = "unavailable"
        effective.append({"engine_code": code, "source": source})
    return {
        "project_id": project.id,
        "platform_pool_enabled": bool(project.platform_pool_enabled),
        "eligible": tenant.plan in PAID_PLANS,
        "can_edit": getattr(user, "tenant_role", None) == "owner",
        "plan": tenant.plan,
        "byok_engines": byok,
        "pool_engines": catalog,
        "effective_engines": effective,
        "usage": usage_summary(db, tenant),
    }


@router.post("", status_code=status.HTTP_202_ACCEPTED)
def create_project(
    payload: ProjectCreate,
    current_user: User = Depends(require_editor),
    db: Session = Depends(get_db),
):
    """创建项目、初始化引擎目录并投递 Bootstrap 任务。"""
    tenant = _tenant_for_user(db, current_user)
    check_project_creation(db, tenant)
    slug = geolib.slugify(payload.url)
    if db.query(Project.id).filter(Project.tenant_id == tenant.id, Project.slug == slug).first() is not None:
        _error(status.HTTP_409_CONFLICT, "project_already_exists")

    project = Project(
        tenant_id=tenant.id,
        slug=slug,
        url=payload.url,
        market="both",
        status="initializing",
    )
    db.add(project)
    db.flush()
    has_engine_keys = db.query(ApiKey.id).filter(
        ApiKey.tenant_id == tenant.id,
        ApiKey.engine_code.in_(tuple(ENGINE_KEY_ENV)),
    ).first() is not None
    skip_llm = payload.skip_llm or not has_engine_keys
    no_sample = payload.no_sample or not has_engine_keys
    job_action = "bootstrap" if no_sample else "autopilot"
    job = Job(project_id=project.id, action=job_action, status="queued")
    db.add(job)
    db.commit()
    db.refresh(project)
    db.refresh(job)

    try:
        import geo

        args = SimpleNamespace(
            url=payload.url,
            name=payload.name.strip() if payload.name else None,
            slug=slug,
            market="both",
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
    job.log_path = str(job_log_path(tenant.name, project.slug, job.id))
    db.commit()
    try:
        task_bootstrap.delay(
            tenant.name,
            slug,
            skip_llm=skip_llm,
            no_sample=no_sample,
            job_action=job_action,
            job_id=job.id,
        )
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
    summaries = {}
    if projects:
        try:
            with with_tenant_context(tenant.name, projects[0].slug):
                import dashboard

                for project in projects:
                    workspace.ensure_all_engine_scope(project.slug)
                summaries = {item["slug"]: item for item in dashboard.list_projects()}
        except Exception:  # noqa: BLE001 - 损坏的管线摘要不能阻断 DB 项目列表
            summaries = {}
    return {
        "projects": [
            {
                "id": p.id,
                "slug": p.slug,
                "url": p.url,
                "name": summaries.get(p.slug, {}).get("name", p.slug),
                "site": summaries.get(p.slug, {}).get("site", p.url),
                "market": p.market,
                "status": p.status,
                "avg_score": summaries.get(p.slug, {}).get("avg_score"),
                "pages": summaries.get(p.slug, {}).get("pages"),
                "tasks_total": summaries.get(p.slug, {}).get("tasks_total", 0),
                "tasks_done": summaries.get(p.slug, {}).get("tasks_done", 0),
                "p0_open": summaries.get(p.slug, {}).get("p0_open", 0),
                "created_at": p.created_at,
            }
            for p in projects
        ]
    }


@router.get("/actions")
def pipeline_actions(current_user: User = Depends(get_current_user)):
    """返回 SaaS worker 支持的引擎动作白名单。"""
    return {"actions": PIPELINE_ACTIONS}


@router.get("/{project_id}")
def project_detail(project_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """返回项目索引和引擎 dashboard 聚合详情。"""
    project = _project_for_user(db, current_user, project_id)
    tenant = _tenant_for_user(db, current_user)
    try:
        with with_tenant_context(tenant.name, project.slug):
            import dashboard

            cfg = workspace.ensure_all_engine_scope(project.slug)
            detail = dashboard.project(project.slug)
            detail["questions"] = cfg.get("questions", [])
            detail["competitor_discovery"] = _competitor_discovery_payload(cfg)
    except GeoEngineError:
        detail = {
            "slug": project.slug,
            "brand": {},
            "questions": [],
            "competitor_discovery": _competitor_discovery_payload({}),
        }
    detail["project"] = {
        "id": project.id,
        "slug": project.slug,
        "url": project.url,
        "market": project.market,
        "status": project.status,
        "created_at": project.created_at,
    }
    return detail


@router.get("/{project_id}/status")
def project_status(project_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """返回文件系统项目进度和最近任务状态。"""
    project = _project_for_user(db, current_user, project_id)
    tenant = _tenant_for_user(db, current_user)
    with with_tenant_context(tenant.name, project.slug):
        import dashboard

        workspace.ensure_all_engine_scope(project.slug)
        summary = next(
            (item for item in dashboard.list_projects() if item.get("slug") == project.slug),
            {
                "slug": project.slug,
                "name": project.slug,
                "site": project.url,
                "market": project.market,
                "avg_score": None,
                "pages": None,
                "tasks_total": 0,
                "tasks_done": 0,
                "p0_open": 0,
            },
        )
    latest_job = db.query(Job).filter(Job.project_id == project.id).order_by(Job.id.desc()).first()
    return {
        "project_id": project.id,
        "slug": project.slug,
        "status": project.status,
        "summary": summary,
        "latest_job": _job_payload(latest_job, include_log=False) if latest_job else None,
    }


@router.get("/{project_id}/schedule")
def project_schedule(project_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """返回项目周期复跑设置。"""
    project = _project_for_user(db, current_user, project_id)
    return {"schedule": _schedule_payload(project)}


@router.get("/{project_id}/sampling-funding")
def sampling_funding(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """返回项目采样的 BYOK/平台代付来源及本月计费。"""
    project = _project_for_user(db, current_user, project_id)
    tenant = _tenant_for_user(db, current_user)
    return _sampling_funding_payload(db, tenant, project, current_user)


@router.put("/{project_id}/sampling-funding")
def update_sampling_funding(
    project_id: int,
    payload: SamplingFundingRequest,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """owner 显式启停按量计费的平台 Key 后备。"""
    project = _project_for_user(db, current_user, project_id)
    tenant = _tenant_for_user(db, current_user)
    if payload.platform_pool_enabled:
        if tenant.plan not in PAID_PLANS:
            _error(status.HTTP_403_FORBIDDEN, "platform_pool_paid_plan_required")
        if not public_catalog():
            _error(status.HTTP_409_CONFLICT, "platform_pool_unavailable")
    project.platform_pool_enabled = payload.platform_pool_enabled
    db.commit()
    return _sampling_funding_payload(db, tenant, project, current_user)


@router.post("/{project_id}/schedule")
def update_project_schedule(
    project_id: int,
    payload: ScheduleRequest,
    current_user: User = Depends(require_editor),
    db: Session = Depends(get_db),
):
    """启用 7/14/30 天周期复跑，传 0 时关闭。"""
    project = _project_for_user(db, current_user, project_id)
    tenant = _tenant_for_user(db, current_user)
    if payload.interval_days == 0:
        project.schedule_interval_days = None
        project.schedule_next_run_at = None
    else:
        check_sample_run(db, tenant, project)
        if project.schedule_interval_days != payload.interval_days or project.schedule_next_run_at is None:
            project.schedule_next_run_at = datetime.now(timezone.utc) + timedelta(days=payload.interval_days)
        project.schedule_interval_days = payload.interval_days
    db.commit()
    db.refresh(project)
    return {"schedule": _schedule_payload(project)}


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
    offset: int | None = Query(default=None, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """返回任务状态、错误和可用日志尾部。"""
    project = _project_for_user(db, current_user, project_id)
    job = db.query(Job).filter(Job.id == job_id, Job.project_id == project.id).first()
    if job is None:
        _error(status.HTTP_404_NOT_FOUND, "job_not_found")
    return {"job": _job_payload(job, log_offset=offset)}


@router.post("/{project_id}/sample", status_code=status.HTTP_202_ACCEPTED)
def sample_project(
    project_id: int,
    payload: SampleRequest | None = None,
    current_user: User = Depends(require_editor),
    db: Session = Depends(get_db),
):
    """投递一次 API 采样任务。"""
    project = _project_for_user(db, current_user, project_id)
    tenant = _tenant_for_user(db, current_user)
    check_sample_run(db, tenant, project)
    if _active_job(db, project.id) is not None:
        _error(status.HTTP_409_CONFLICT, "project_job_already_running")
    payload = payload or SampleRequest()
    job = Job(project_id=project.id, action="sample", status="queued")
    db.add(job)
    project.status = "sampling"
    db.commit()
    db.refresh(job)
    job.log_path = str(job_log_path(tenant.name, project.slug, job.id))
    db.commit()
    try:
        task_sample.delay(
            tenant.name,
            project.slug,
            limit=payload.limit,
            platforms=payload.platforms,
            job_id=job.id,
        )
    except Exception as exc:  # noqa: BLE001
        job.status = "failed"
        job.error = f"{type(exc).__name__}: {exc}"
        job.finished_at = datetime.now(timezone.utc)
        project.status = "failed"
        db.commit()
        _error(status.HTTP_503_SERVICE_UNAVAILABLE, "worker_unavailable")
    return {"job_id": job.id, "project_id": project.id, "status": project.status}


@router.post("/{project_id}/actions/{action}", status_code=status.HTTP_202_ACCEPTED)
def run_pipeline_action(
    project_id: int,
    action: str,
    payload: PipelineActionRequest | None = None,
    current_user: User = Depends(require_editor),
    db: Session = Depends(get_db),
):
    """投递一个白名单内的引擎管线动作。"""
    if action not in PIPELINE_ACTIONS:
        _error(status.HTTP_400_BAD_REQUEST, "unsupported_pipeline_action")
    project = _project_for_user(db, current_user, project_id)
    tenant = _tenant_for_user(db, current_user)
    if _active_job(db, project.id) is not None:
        _error(status.HTTP_409_CONFLICT, "project_job_already_running")
    params = (payload or PipelineActionRequest()).params
    if action in ("sample", "cycle", "autopilot", "serve") and not params.get("--no-sample", False):
        check_sample_run(db, tenant, project)

    job = Job(project_id=project.id, action=action, status="queued")
    db.add(job)
    project.status = {
        "sample": "sampling",
        "verify": "verifying",
        "deliver": "delivering",
        "bootstrap": "bootstrapping",
    }.get(action, "processing")
    db.commit()
    db.refresh(job)
    job.log_path = str(job_log_path(tenant.name, project.slug, job.id))
    db.commit()
    try:
        task_pipeline.delay(tenant.name, project.slug, action, params=params, job_id=job.id)
    except Exception as exc:  # noqa: BLE001
        job.status = "failed"
        job.error = f"{type(exc).__name__}: {exc}"
        job.finished_at = datetime.now(timezone.utc)
        project.status = "failed"
        db.commit()
        _error(status.HTTP_503_SERVICE_UNAVAILABLE, "worker_unavailable")
    return {"job_id": job.id, "project_id": project.id, "action": action, "status": project.status}


@router.get("/{project_id}/report")
def project_report(project_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """返回最新 metrics 报告。"""
    project = _project_for_user(db, current_user, project_id)
    tenant = _tenant_for_user(db, current_user)
    with with_tenant_context(tenant.name, project.slug):
        path = _latest_file(geolib.project_dir(project.slug) / "metrics", "*.json")
        if path is None:
            _error(status.HTTP_404_NOT_FOUND, "report_not_found")
        metrics = geolib.read_json(path, None)
    return {"report": metrics, "date": metrics.get("date") if metrics else None}


@router.get("/{project_id}/engines")
def project_engines(project_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """返回分引擎指标，并标明 API 采样模式。"""
    project = _project_for_user(db, current_user, project_id)
    tenant = _tenant_for_user(db, current_user)
    with with_tenant_context(tenant.name, project.slug):
        pdir = geolib.project_dir(project.slug)
        metrics_path = _latest_file(pdir / "metrics", "*.json")
        sample_path = _latest_file(pdir / "samples", "*.jsonl")
        metrics = geolib.read_json(metrics_path, None) if metrics_path else None
        rows = geolib.read_jsonl(sample_path) if sample_path else []
        import analytics

        engines = analytics.engines(project.slug, rows, metrics)
    for item in engines:
        platform_rows = [row for row in rows if row.get("platform") == item.get("platform")]
        manual = any(
            row.get("sample_mode") == "manual" or row.get("terminal") == "web"
            for row in platform_rows
        )
        item["sample_mode"] = "manual" if manual else "api"
        item["sampling_mode"] = (
            "人工·产品端" if manual else ("API·联网检索" if item.get("searched") else "API·参数化知识")
        )
        item.pop("market", None)
    return {"date": metrics.get("date") if metrics else None, "engines": engines}


@router.get("/{project_id}/framing")
def project_framing(project_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """返回最新采样中 AI 对品牌的描述短语和原文证据。"""
    project = _project_for_user(db, current_user, project_id)
    tenant = _tenant_for_user(db, current_user)
    with with_tenant_context(tenant.name, project.slug):
        result = framing.build(project.slug)
    return {"framing": result}


@router.get("/{project_id}/samples/{sample_date}")
def project_samples(
    project_id: int,
    sample_date: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """按日期返回原始答案回放。"""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", sample_date):
        _error(status.HTTP_400_BAD_REQUEST, "invalid_sample_date")
    project = _project_for_user(db, current_user, project_id)
    tenant = _tenant_for_user(db, current_user)
    with with_tenant_context(tenant.name, project.slug):
        path = geolib.project_dir(project.slug) / "samples" / f"{sample_date}.jsonl"
        if not path.is_file():
            _error(status.HTTP_404_NOT_FOUND, "samples_not_found")
        rows = geolib.read_jsonl(path)
    return {"date": sample_date, "samples": rows}


@router.get("/{project_id}/tickets")
def project_tickets(project_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """读取 engine 生成的工单列表。"""
    project = _project_for_user(db, current_user, project_id)
    tenant = _tenant_for_user(db, current_user)
    with with_tenant_context(tenant.name, project.slug):
        import tasks as engine_tasks

        data = engine_tasks.load(project.slug)
    return {"tickets": data.get("tasks", []), "summary": data.get("summary", {})}


@router.get("/{project_id}/playbook")
def project_playbook(project_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """按影响、工作量和原始顺序稳定返回 Playbook。"""
    project = _project_for_user(db, current_user, project_id)
    tenant = _tenant_for_user(db, current_user)
    with with_tenant_context(tenant.name, project.slug):
        import tasks as engine_tasks

        data = engine_tasks.load(project.slug)
    indexed = [
        (index, ticket)
        for index, ticket in enumerate(data.get("tasks", []))
        if isinstance(ticket, dict)
    ]
    indexed.sort(key=lambda pair: (
        pair[1].get("status") in ("done", "wontfix"),
        PLAYBOOK_PRIORITY.get(pair[1].get("priority"), 99),
        PLAYBOOK_EFFORT.get(pair[1].get("effort"), 99),
        pair[0],
    ))
    return {
        "playbook": [ticket for _, ticket in indexed],
        "summary": data.get("summary", {}),
        "generated_at": data.get("generated_at"),
    }


@router.post("/{project_id}/tickets", status_code=status.HTTP_201_CREATED)
def create_ticket(
    project_id: int,
    payload: OffsiteTicketCreate,
    current_user: User = Depends(require_editor),
    db: Session = Depends(get_db),
):
    """创建需要人工验收的 offsite 工单。"""
    project = _project_for_user(db, current_user, project_id)
    tenant = _tenant_for_user(db, current_user)
    if _active_job(db, project.id) is not None:
        _error(status.HTTP_409_CONFLICT, "project_job_already_running")
    try:
        with with_tenant_context(tenant.name, project.slug):
            ticket = workspace.create_offsite_ticket(
                project.slug,
                payload.url,
                payload.ask_text,
                payload.influenced_questions,
            )
    except (GeoEngineError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "ticket_creation_failed", "detail": str(exc)},
        ) from exc
    return {"ticket": ticket}


@router.patch("/{project_id}/tickets/{ticket_id}")
def update_ticket(
    project_id: int,
    ticket_id: str,
    payload: TicketUpdate,
    current_user: User = Depends(require_editor),
    db: Session = Depends(get_db),
):
    """调用 engine tasks.set_status 更新工单状态。"""
    project = _project_for_user(db, current_user, project_id)
    tenant = _tenant_for_user(db, current_user)
    if _active_job(db, project.id) is not None:
        _error(status.HTTP_409_CONFLICT, "project_job_already_running")
    try:
        with with_tenant_context(tenant.name, project.slug):
            import tasks as engine_tasks

            ticket = engine_tasks.set_status(project.slug, ticket_id, payload.status, payload.note)
    except KeyError:
        _error(status.HTTP_404_NOT_FOUND, "ticket_not_found")
    except GeoEngineError:
        _error(status.HTTP_400_BAD_REQUEST, "ticket_update_failed")
    return {"ticket": ticket}


@router.post("/{project_id}/verify", status_code=status.HTTP_202_ACCEPTED)
def verify_project(project_id: int, current_user: User = Depends(require_editor), db: Session = Depends(get_db)):
    """投递工单自动验收任务。"""
    project = _project_for_user(db, current_user, project_id)
    if _active_job(db, project.id) is not None:
        _error(status.HTTP_409_CONFLICT, "project_job_already_running")
    job = Job(project_id=project.id, action="verify", status="queued")
    db.add(job)
    project.status = "verifying"
    db.commit()
    db.refresh(job)
    tenant = _tenant_for_user(db, current_user)
    job.log_path = str(job_log_path(tenant.name, project.slug, job.id))
    db.commit()
    try:
        task_verify.delay(tenant.name, project.slug, job_id=job.id)
    except Exception as exc:  # noqa: BLE001
        job.status = "failed"
        job.error = f"{type(exc).__name__}: {exc}"
        job.finished_at = datetime.now(timezone.utc)
        project.status = "failed"
        db.commit()
        _error(status.HTTP_503_SERVICE_UNAVAILABLE, "worker_unavailable")
    return {"job_id": job.id, "project_id": project.id, "status": project.status}


@router.get("/{project_id}/verify/history")
def verify_history(project_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """返回 engine verify 生成的验收历史。"""
    project = _project_for_user(db, current_user, project_id)
    tenant = _tenant_for_user(db, current_user)
    with with_tenant_context(tenant.name, project.slug):
        import verify as engine_verify

        directory = geolib.project_dir(project.slug) / "verify"
        files = sorted(directory.glob("*.json"), key=engine_verify.report_key) if directory.exists() else []
        history = [geolib.read_json(path, {}) for path in files]
    return {"history": history}


@router.post("/{project_id}/deliver", status_code=status.HTTP_202_ACCEPTED)
def deliver_project(project_id: int, current_user: User = Depends(require_editor), db: Session = Depends(get_db)):
    """投递客户交付包生成任务。"""
    project = _project_for_user(db, current_user, project_id)
    if _active_job(db, project.id) is not None:
        _error(status.HTTP_409_CONFLICT, "project_job_already_running")
    job = Job(project_id=project.id, action="deliver", status="queued")
    db.add(job)
    project.status = "delivering"
    db.commit()
    db.refresh(job)
    tenant = _tenant_for_user(db, current_user)
    job.log_path = str(job_log_path(tenant.name, project.slug, job.id))
    db.commit()
    try:
        task_deliver.delay(tenant.name, project.slug, job_id=job.id)
    except Exception as exc:  # noqa: BLE001
        job.status = "failed"
        job.error = f"{type(exc).__name__}: {exc}"
        job.finished_at = datetime.now(timezone.utc)
        project.status = "failed"
        db.commit()
        _error(status.HTTP_503_SERVICE_UNAVAILABLE, "worker_unavailable")
    return {"job_id": job.id, "project_id": project.id, "status": project.status}


@router.get("/{project_id}/deliveries")
def deliveries(project_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """返回已生成的交付日期列表。"""
    project = _project_for_user(db, current_user, project_id)
    tenant = _tenant_for_user(db, current_user)
    with with_tenant_context(tenant.name, project.slug):
        directory = geolib.project_dir(project.slug) / "delivery"
        dates = sorted((item.name for item in directory.iterdir() if item.is_dir()), reverse=True) \
            if directory.exists() else []
    return {"deliveries": dates}


@router.get("/{project_id}/deliveries/{delivery_date}")
def download_delivery(
    project_id: int,
    delivery_date: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """把指定交付目录打成 zip 下载。"""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", delivery_date):
        _error(status.HTTP_400_BAD_REQUEST, "invalid_delivery_date")
    project = _project_for_user(db, current_user, project_id)
    tenant = _tenant_for_user(db, current_user)
    with with_tenant_context(tenant.name, project.slug):
        directory = geolib.project_dir(project.slug) / "delivery" / delivery_date
        if not directory.is_dir():
            _error(status.HTTP_404_NOT_FOUND, "delivery_not_found")
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for file_path in sorted(directory.rglob("*")):
                if file_path.is_file():
                    bundle.write(file_path, file_path.relative_to(directory).as_posix())
    archive.seek(0)
    return StreamingResponse(
        archive,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="delivery-{delivery_date}.zip"'},
    )
