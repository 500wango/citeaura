"""试用额度检查和用量汇总。"""

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from api.models import Job, Project, Tenant


TRIAL_PROJECT_LIMIT = 3
TRIAL_SAMPLE_LIMIT_PER_PROJECT = 2
SAMPLE_JOB_ACTIONS = ("sample", "cycle", "autopilot", "serve")


def _trial_active(tenant: Tenant) -> bool:
    """判断租户是否受试用额度约束；过期试用直接拒绝。"""
    if tenant.plan != "trial":
        return False
    if tenant.trial_ends_at is None:
        return True
    ends_at = tenant.trial_ends_at
    if ends_at.tzinfo is None:
        ends_at = ends_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > ends_at:
        _raise_limit("trial has expired")
    return True


def _raise_limit(detail: str):
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"error": "trial_limit_exceeded", "detail": detail},
    )


def check_project_creation(db: Session, tenant: Tenant):
    """检查 trial 项目数量。"""
    if not _trial_active(tenant):
        return
    count = db.query(func.count(Project.id)).filter(Project.tenant_id == tenant.id).scalar() or 0
    if count >= TRIAL_PROJECT_LIMIT:
        _raise_limit(f"trial projects limit is {TRIAL_PROJECT_LIMIT}")


def check_sample_run(db: Session, tenant: Tenant, project: Project):
    """检查单项目 trial sample 次数。"""
    if not _trial_active(tenant):
        return
    count = (
        db.query(func.count(Job.id))
        .filter(Job.project_id == project.id, Job.action.in_(SAMPLE_JOB_ACTIONS))
        .scalar()
        or 0
    )
    if count >= TRIAL_SAMPLE_LIMIT_PER_PROJECT:
        _raise_limit(f"trial sample limit is {TRIAL_SAMPLE_LIMIT_PER_PROJECT} per project")


def usage(db: Session, tenant: Tenant) -> dict:
    """返回当前租户用量和额度。"""
    project_count = db.query(func.count(Project.id)).filter(Project.tenant_id == tenant.id).scalar() or 0
    projects = db.query(Project.id).filter(Project.tenant_id == tenant.id).all()
    project_ids = [row[0] for row in projects]
    sample_count = 0
    if project_ids:
        sample_count = (
            db.query(func.count(Job.id))
            .filter(Job.project_id.in_(project_ids), Job.action.in_(SAMPLE_JOB_ACTIONS))
            .scalar()
            or 0
        )
    per_project = {}
    for project_id in project_ids:
        per_project[str(project_id)] = (
            db.query(func.count(Job.id))
            .filter(Job.project_id == project_id, Job.action.in_(SAMPLE_JOB_ACTIONS))
            .scalar()
            or 0
        )
    trial = tenant.plan == "trial"
    return {
        "plan": tenant.plan,
        "trial_ends_at": tenant.trial_ends_at,
        "projects_active": project_count,
        "projects_limit": TRIAL_PROJECT_LIMIT if trial else None,
        "sample_runs": sample_count,
        "sample_runs_limit_per_project": TRIAL_SAMPLE_LIMIT_PER_PROJECT if trial else None,
        "sample_runs_by_project": per_project,
    }
