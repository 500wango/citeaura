"""试用额度检查和用量汇总。"""

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from api.models import Job, Project, Tenant
from api.billing.plans import PLANS


TRIAL_PROJECT_LIMIT = 3
TRIAL_SAMPLE_LIMIT_PER_PROJECT = 2
SAMPLE_JOB_ACTIONS = ("sample", "sample-import", "cycle", "autopilot", "serve")


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
    """检查单项目 trial sample 次数。"""
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


def usage(db: Session, tenant: Tenant) -> dict:
    """返回当前租户用量和额度。"""
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
    sample_count = 0
    if project_ids:
        sample_count = (
            db.query(func.count(Job.id))
            .filter(Job.project_id.in_(project_ids), Job.action.in_(SAMPLE_JOB_ACTIONS), Job.status != "failed")
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
    return {
        "plan": tenant.plan,
        "trial_ends_at": tenant.trial_ends_at,
        "trial_expired": trial_expired,
        # 试用未结束也可随时付费升级；不要求等 14 天。
        "can_upgrade": trial,
        "projects_active": project_count,
        "projects_limit": plan.get("projects"),
        "sample_runs": sample_count,
        "sample_runs_limit_per_project": TRIAL_SAMPLE_LIMIT_PER_PROJECT if trial else None,
        "sample_runs_by_project": per_project,
    }
