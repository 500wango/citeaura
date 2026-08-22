"""试用额度检查和用量汇总。"""

import json
from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from api.models import Job, Membership, Project, Tenant, UsageCounter, User
from api.billing.plans import PLANS


TRIAL_PROJECT_LIMIT = 3
TRIAL_SAMPLE_LIMIT_PER_PROJECT = 2
SAMPLE_JOB_ACTIONS = ("sample", "sample-import", "cycle", "autopilot", "serve")
ACTIVATION_STEPS = (
    ("registration", "Registration"),
    ("project_creation", "First project"),
    ("first_audit", "First audit"),
    ("first_sample", "First sample"),
    ("first_delivery_pack", "First delivery pack"),
    ("first_resample", "First re-sample"),
)


def _iso(value):
    """把数据库时间转换为稳定的 API 字符串。"""
    return value.isoformat() if value is not None else None


def _job_payload(job):
    try:
        value = json.loads(job.request_json or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _job_sampled(job):
    """判断成功 Job 是否实际包含一次采样，而不是只看 action 名称。"""
    if job.action in ("sample", "sample-import", "cycle"):
        return True
    if job.action not in ("autopilot", "serve", "bootstrap"):
        return False
    payload = _job_payload(job)
    return not bool(payload.get("no_sample") or payload.get("--no-sample"))


def activation_funnel(db: Session, tenant: Tenant) -> dict:
    """按已完成的真实工作区事实返回首次价值漏斗。"""
    registration_at = (
        db.query(func.min(User.created_at))
        .join(Membership, Membership.user_id == User.id)
        .filter(Membership.tenant_id == tenant.id)
        .scalar()
        or tenant.created_at
    )
    projects = db.query(Project).filter(Project.tenant_id == tenant.id).all()
    project_ids = [project.id for project in projects]
    jobs = []
    if project_ids:
        jobs = (
            db.query(Job)
            .filter(Job.project_id.in_(project_ids), Job.status == "done")
            .order_by(Job.finished_at.asc(), Job.created_at.asc(), Job.id.asc())
            .all()
        )
    completed_jobs = [job for job in jobs if job.finished_at or job.created_at]
    audit_jobs = [
        job for job in completed_jobs
        if job.action in (
            "audit", "sample", "sample-import", "autopilot", "cycle", "serve", "bootstrap",
        )
    ]
    sampled_jobs = [job for job in completed_jobs if _job_sampled(job)]
    delivery_jobs = [job for job in completed_jobs if job.action == "deliver"]
    completed_at = {
        "registration": registration_at,
        "project_creation": min((project.created_at for project in projects if project.created_at), default=None),
        "first_audit": (audit_jobs[0].finished_at or audit_jobs[0].created_at) if audit_jobs else None,
        "first_sample": (sampled_jobs[0].finished_at or sampled_jobs[0].created_at) if sampled_jobs else None,
        "first_delivery_pack": (delivery_jobs[0].finished_at or delivery_jobs[0].created_at) if delivery_jobs else None,
        "first_resample": (sampled_jobs[1].finished_at or sampled_jobs[1].created_at) if len(sampled_jobs) >= 2 else None,
    }
    steps = []
    for key, label in ACTIVATION_STEPS:
        timestamp = completed_at[key]
        steps.append({
            "key": key,
            "label": label,
            "status": "complete" if timestamp else "pending",
            "completed": bool(timestamp),
            "completed_at": _iso(timestamp),
        })
    completed_count = sum(item["completed"] for item in steps)
    next_step = next((item for item in steps if not item["completed"]), None)
    return {
        "steps": steps,
        "completed_steps": completed_count,
        "total_steps": len(steps),
        "progress_percent": round(completed_count / len(steps) * 100, 1),
        "next_step": next_step["key"] if next_step else None,
        "next_step_label": next_step["label"] if next_step else None,
        "sample_runs_completed": len(sampled_jobs),
    }


def reconcile_usage_counter(db: Session, tenant: Tenant, now=None):
    """按当前项目快照和当月 Job 权威数据刷新用量计数器。"""
    now = now or datetime.now(timezone.utc)
    month = date(now.year, now.month, 1)
    month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    if now.month == 12:
        next_month = datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        next_month = datetime(now.year, now.month + 1, 1, tzinfo=timezone.utc)
    projects_active = db.query(func.count(Project.id)).filter(
        Project.tenant_id == tenant.id,
        Project.archived_at.is_(None),
        Project.status != "archived",
    ).scalar() or 0
    sample_runs = (
        db.query(func.count(Job.id))
        .join(Project, Project.id == Job.project_id)
        .filter(
            Project.tenant_id == tenant.id,
            Job.action.in_(SAMPLE_JOB_ACTIONS),
            Job.status != "failed",
            Job.created_at >= month_start,
            Job.created_at < next_month,
        )
        .scalar()
        or 0
    )
    values = {
        "tenant_id": tenant.id,
        "month": month,
        "sample_runs": sample_runs,
        "projects_active": projects_active,
        "platform_calls": 0,
        "platform_cost_cny_fen": 0,
    }
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        statement = postgres_insert(UsageCounter).values(**values).on_conflict_do_update(
            index_elements=["tenant_id", "month"],
            set_={"sample_runs": sample_runs, "projects_active": projects_active},
        )
        db.execute(statement)
    elif dialect == "sqlite":
        statement = sqlite_insert(UsageCounter).values(**values).on_conflict_do_update(
            index_elements=["tenant_id", "month"],
            set_={"sample_runs": sample_runs, "projects_active": projects_active},
        )
        db.execute(statement)
    else:
        counter = db.get(UsageCounter, {"tenant_id": tenant.id, "month": month})
        if counter is None:
            db.add(UsageCounter(**values))
        else:
            counter.sample_runs = sample_runs
            counter.projects_active = projects_active
    db.flush()
    return {"sample_runs": sample_runs, "projects_active": projects_active}


def _trial_active(tenant: Tenant) -> bool:
    """判断租户是否受试用额度约束；过期试用直接拒绝。"""
    if tenant.plan != "trial":
        return False
    ends_at = tenant.trial_ends_at
    if ends_at is None:
        created_at = tenant.created_at
        if created_at is None:
            _raise_limit("trial expiration is not configured")
        ends_at = created_at + timedelta(days=14)
    if ends_at.tzinfo is None:
        ends_at = ends_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > ends_at:
        _raise_limit("trial has expired")
    return True


def _raise_limit(detail: str, error="trial_limit_exceeded"):
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"error": error, "detail": detail},
    )


def check_project_creation(db: Session, tenant: Tenant):
    """按租户套餐检查项目数量。"""
    trial = _trial_active(tenant)
    plan = PLANS.get(tenant.plan)
    project_limit = plan.get("projects") if plan else None
    if project_limit is None:
        return
    count = db.query(func.count(Project.id)).filter(
        Project.tenant_id == tenant.id,
        Project.archived_at.is_(None),
        Project.status != "archived",
    ).scalar() or 0
    if count >= project_limit:
        error = "trial_limit_exceeded" if trial else "plan_limit_exceeded"
        _raise_limit(f"{tenant.plan} projects limit is {project_limit}", error=error)


def check_sample_run(db: Session, tenant: Tenant, project: Project):
    """检查单项目和整个试用生命周期的采样次数。"""
    if not _trial_active(tenant):
        return
    count = (
        db.query(func.count(Job.id))
        .filter(Job.project_id == project.id, Job.action.in_(SAMPLE_JOB_ACTIONS), Job.status != "failed")
        .scalar()
        or 0
    )
    if count >= TRIAL_SAMPLE_LIMIT_PER_PROJECT:
        _raise_limit(f"trial sample limit is {TRIAL_SAMPLE_LIMIT_PER_PROJECT} per project")
    tenant_count = (
        db.query(func.count(Job.id))
        .join(Project, Project.id == Job.project_id)
        .filter(
            Project.tenant_id == tenant.id,
            Job.action.in_(SAMPLE_JOB_ACTIONS),
            Job.status != "failed",
        )
        .scalar()
        or 0
    )
    lifetime_limit = TRIAL_PROJECT_LIMIT * TRIAL_SAMPLE_LIMIT_PER_PROJECT
    if tenant_count >= lifetime_limit:
        _raise_limit(f"trial sample lifetime limit is {lifetime_limit} per workspace")


def usage(db: Session, tenant: Tenant) -> dict:
    """返回当前租户用量和额度。读取路径不写 usage_counters。"""
    now = datetime.now(timezone.utc)
    month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    if now.month == 12:
        next_month = datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        next_month = datetime(now.year, now.month + 1, 1, tzinfo=timezone.utc)
    project_count = db.query(func.count(Project.id)).filter(
        Project.tenant_id == tenant.id,
        Project.archived_at.is_(None),
        Project.status != "archived",
    ).scalar() or 0
    projects = db.query(Project.id).filter(
        Project.tenant_id == tenant.id,
        Project.archived_at.is_(None),
        Project.status != "archived",
    ).all()
    project_ids = [row[0] for row in projects]
    sample_count = (
        db.query(func.count(Job.id))
        .join(Project, Project.id == Job.project_id)
        .filter(
            Project.tenant_id == tenant.id,
            Job.action.in_(SAMPLE_JOB_ACTIONS),
            Job.status != "failed",
            Job.created_at >= month_start,
            Job.created_at < next_month,
        )
        .scalar()
        or 0
    )
    per_project = {}
    for project_id in project_ids:
        per_project[str(project_id)] = (
            db.query(func.count(Job.id))
            .filter(Job.project_id == project_id, Job.action.in_(SAMPLE_JOB_ACTIONS), Job.status != "failed")
            .scalar()
            or 0
        )
    trial = tenant.plan == "trial"
    plan = PLANS.get(tenant.plan) or {}
    trial_ends_at = tenant.trial_ends_at
    if trial and trial_ends_at is None and tenant.created_at is not None:
        trial_ends_at = tenant.created_at + timedelta(days=14)
    trial_expired = False
    if trial and trial_ends_at is not None:
        ends_at = trial_ends_at
        if ends_at.tzinfo is None:
            ends_at = ends_at.replace(tzinfo=timezone.utc)
        trial_expired = datetime.now(timezone.utc) > ends_at
    lifetime_sample_runs = (
        db.query(func.count(Job.id))
        .join(Project, Project.id == Job.project_id)
        .filter(
            Project.tenant_id == tenant.id,
            Job.action.in_(SAMPLE_JOB_ACTIONS),
            Job.status != "failed",
        )
        .scalar()
        or 0
    )
    lifetime_limit = TRIAL_PROJECT_LIMIT * TRIAL_SAMPLE_LIMIT_PER_PROJECT if trial else None
    projects_limit = plan.get("projects")
    platform_sample_remaining = (
        max(0, lifetime_limit - lifetime_sample_runs)
        if lifetime_limit is not None else None
    )
    return {
        "plan": tenant.plan,
        "trial_ends_at": tenant.trial_ends_at,
        "trial_expired": trial_expired,
        # 试用未结束也可随时付费升级；不要求等 14 天。
        "can_upgrade": trial,
        "projects_active": project_count,
        "projects_limit": projects_limit,
        "projects_remaining": max(0, projects_limit - project_count) if projects_limit is not None else None,
        "sample_runs": sample_count,
        "sample_runs_limit_per_project": TRIAL_SAMPLE_LIMIT_PER_PROJECT if trial else None,
        "sample_runs_by_project": per_project,
        "sample_runs_lifetime": lifetime_sample_runs,
        "sample_runs_lifetime_limit": lifetime_limit,
        "sample_runs_remaining": platform_sample_remaining,
        "sample_runs_remaining_by_project": {
            project_id: max(0, TRIAL_SAMPLE_LIMIT_PER_PROJECT - count)
            for project_id, count in per_project.items()
        } if trial else {},
    }
