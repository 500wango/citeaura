"""试用额度检查和用量汇总。"""

import json
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from api.models import Job, Membership, Project, Tenant, User
from api.billing.plans import PLANS, TRIAL_DAYS


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


def _row_sampled(action, request_json):
    """判断轻量查询行是否包含实际采样。"""
    if action == "sample":
        return True
    if action == "sample-import":
        try:
            payload = json.loads(request_json or "{}")
        except (TypeError, ValueError):
            payload = {}
        # 旧导入 Job 没有 sample_count，按历史行为视为一次有效导入。
        value = payload.get("sample_count", 1)
        try:
            return int(value or 0) > 0
        except (TypeError, ValueError):
            return True
    if action not in ("cycle", "autopilot", "serve", "bootstrap"):
        return False
    try:
        payload = json.loads(request_json or "{}")
    except (TypeError, ValueError):
        payload = {}
    return not bool(payload.get("no_sample") or payload.get("--no-sample"))


def _count_sampled_jobs(db, *, project_id=None, tenant_id=None, created_from=None, created_to=None):
    """按动作参数统计已执行或仍待执行的采样 Job，忽略 no_sample 管线。"""
    query = db.query(Job).filter(
        Job.action.in_(SAMPLE_JOB_ACTIONS),
        or_(Job.status != "failed", Job.started_at.isnot(None)),
    )
    if tenant_id is not None:
        query = query.join(Project, Project.id == Job.project_id).filter(Project.tenant_id == tenant_id)
    if project_id is not None:
        query = query.filter(Job.project_id == project_id)
    if created_from is not None:
        query = query.filter(Job.created_at >= created_from)
    if created_to is not None:
        query = query.filter(Job.created_at < created_to)
    rows = query.with_entities(Job.action, Job.request_json).all()
    return sum(1 for action, request_json in rows if _row_sampled(action, request_json))


def activation_funnel(db: Session, tenant: Tenant) -> dict:
    """按已完成的真实工作区事实返回首次价值漏斗。"""
    registration_at = (
        db.query(func.min(User.created_at))
        .join(Membership, Membership.user_id == User.id)
        .filter(Membership.tenant_id == tenant.id)
        .scalar()
        or tenant.created_at
    )
    project_ids = [row[0] for row in db.query(Project.id).filter(Project.tenant_id == tenant.id).all()]
    project_created_at = db.query(func.min(Project.created_at)).filter(Project.tenant_id == tenant.id).scalar()
    jobs = []
    if project_ids:
        jobs = (
            db.query(Job.action, Job.request_json, Job.finished_at, Job.created_at)
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
    sampled_jobs = [job for job in completed_jobs if _row_sampled(job.action, job.request_json)]
    delivery_jobs = [job for job in completed_jobs if job.action == "deliver"]
    job_time = lambda job: job.finished_at or job.created_at
    completed_at = {
        "registration": registration_at,
        "project_creation": project_created_at,
        "first_audit": job_time(audit_jobs[0]) if audit_jobs else None,
        "first_sample": job_time(sampled_jobs[0]) if sampled_jobs else None,
        "first_delivery_pack": job_time(delivery_jobs[0]) if delivery_jobs else None,
        "first_resample": job_time(sampled_jobs[1]) if len(sampled_jobs) >= 2 else None,
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


AUDIT_JOB_ACTIONS = ("audit", "sample", "sample-import", "autopilot", "cycle", "serve", "bootstrap")


def activation_funnel_totals(db: Session, tenants) -> dict:
    """把 activation_funnel 的六段聚合到一组租户上，只用两次批量查询。

    单租户版本按时间线返回明细；这里只关心每段有多少租户到达，
    用于运营面板的转化率，因此不读取时间戳。
    """
    tenant_ids = [tenant.id for tenant in tenants]
    reached = {key: set() for key, _ in ACTIVATION_STEPS}
    reached["registration"] = set(tenant_ids)
    if not tenant_ids:
        return _funnel_payload(reached, 0)
    project_rows = db.query(Project.id, Project.tenant_id).filter(Project.tenant_id.in_(tenant_ids)).all()
    reached["project_creation"] = {row.tenant_id for row in project_rows}
    project_owner = {row.id: row.tenant_id for row in project_rows}
    if project_owner:
        job_rows = db.query(Job.project_id, Job.action, Job.request_json).filter(
            Job.project_id.in_(list(project_owner)),
            Job.status == "done",
        ).all()
        sample_counts = {}
        for row in job_rows:
            owner = project_owner.get(row.project_id)
            if owner is None:
                continue
            if row.action in AUDIT_JOB_ACTIONS:
                reached["first_audit"].add(owner)
            if row.action == "deliver":
                reached["first_delivery_pack"].add(owner)
            if _row_sampled(row.action, row.request_json):
                reached["first_sample"].add(owner)
                sample_counts[owner] = sample_counts.get(owner, 0) + 1
        reached["first_resample"] = {owner for owner, count in sample_counts.items() if count >= 2}
    return _funnel_payload(reached, len(tenant_ids))


def _funnel_payload(reached, registered):
    """把每段到达人数转成带转化率的阶段列表。"""
    steps = []
    previous = None
    for key, label in ACTIVATION_STEPS:
        count = len(reached[key])
        steps.append({
            "key": key,
            "label": label,
            "tenants": count,
            "rate_from_registration": round(count * 100 / registered, 1) if registered else None,
            "rate_from_previous": round(count * 100 / previous, 1) if previous else None,
        })
        previous = count
    return {"registered": registered, "steps": steps}


def _trial_active(tenant: Tenant) -> bool:
    """判断租户是否受试用额度约束；过期试用直接拒绝。"""
    if tenant.plan != "trial":
        return False
    ends_at = tenant.trial_ends_at
    if ends_at is None:
        created_at = tenant.created_at
        if created_at is None:
            _raise_limit("trial expiration is not configured")
        ends_at = created_at + timedelta(days=TRIAL_DAYS)
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
    count = _count_sampled_jobs(db, project_id=project.id)
    if count >= TRIAL_SAMPLE_LIMIT_PER_PROJECT:
        _raise_limit(f"trial sample limit is {TRIAL_SAMPLE_LIMIT_PER_PROJECT} per project")
    tenant_count = _count_sampled_jobs(db, tenant_id=tenant.id)
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
    sample_count = _count_sampled_jobs(
        db,
        tenant_id=tenant.id,
        created_from=month_start,
        created_to=next_month,
    )
    per_project = {
        str(project_id): _count_sampled_jobs(db, project_id=project_id)
        for project_id in project_ids
    }
    trial = tenant.plan == "trial"
    plan = PLANS.get(tenant.plan) or {}
    trial_ends_at = tenant.trial_ends_at
    if trial and trial_ends_at is None and tenant.created_at is not None:
        trial_ends_at = tenant.created_at + timedelta(days=TRIAL_DAYS)
    trial_expired = False
    if trial and trial_ends_at is not None:
        ends_at = trial_ends_at
        if ends_at.tzinfo is None:
            ends_at = ends_at.replace(tzinfo=timezone.utc)
        trial_expired = datetime.now(timezone.utc) > ends_at
    lifetime_sample_runs = _count_sampled_jobs(db, tenant_id=tenant.id)
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
        # 试用未结束也可随时付费升级；不要求等 7 天。
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
