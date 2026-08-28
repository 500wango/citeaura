"""Worker 周期调度与平台用量对账任务。"""

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from api.adapters import sampling_control
from api.adapters.engine import job_log_path
from api.billing.limits import check_sample_run
from api.billing.platform_pool import reconcile_usage_outbox
from api.db import SessionLocal
from api.models import Job, Project, Tenant
from api.worker.celery_app import celery_app


def _task_facade():
    from api.worker import tasks
    return tasks


@celery_app.task(name="citeaura.dispatch_schedules")
def task_dispatch_schedules(now_iso=None):
    """扫描到期项目并投递周期复跑任务。"""
    facade = _task_facade()
    now = datetime.fromisoformat(now_iso) if now_iso else datetime.now(timezone.utc)
    now = facade._as_utc(now)
    result = {"scanned": 0, "enqueued": 0, "busy": 0, "quota_blocked": 0, "failed": 0}
    db = facade.SessionLocal()
    try:
        facade._reclaim_stale_jobs(db, now)
        candidate_ids = [row[0] for row in db.query(Project.id).join(Tenant, Tenant.id == Project.tenant_id).filter(
            Tenant.status == "active", Project.schedule_interval_days.in_((1, 7, 14, 30)),
            Project.schedule_next_run_at.isnot(None), Project.schedule_next_run_at <= now,
        ).order_by(Project.schedule_next_run_at, Project.id).all()]
        result["scanned"] = len(candidate_ids)
        db.rollback()
        for project_id in candidate_ids:
            project = db.query(Project).filter(
                Project.id == project_id, Project.schedule_interval_days.in_((1, 7, 14, 30)),
                Project.schedule_next_run_at.isnot(None), Project.schedule_next_run_at <= now,
            ).with_for_update(skip_locked=True, of=Project).first()
            if project is None:
                db.rollback(); continue
            tenant = db.get(Tenant, project.tenant_id)
            if tenant is None or tenant.status != "active":
                project.schedule_interval_days = None; project.schedule_next_run_at = None; db.commit(); continue
            if db.query(Job.id).filter(Job.project_id == project.id, Job.status.in_(("queued", "running"))).first() is not None:
                result["busy"] += 1; db.rollback(); continue
            try:
                check_sample_run(db, tenant, project)
                sampling_control.ensure_allowed(db, tenant, project, allow_pool=True)
            except (HTTPException, sampling_control.SamplingBudgetExceeded):
                result["quota_blocked"] += 1
                project.schedule_next_run_at = facade._next_scheduled_run(project.schedule_next_run_at, project.schedule_interval_days, now)
                db.commit(); continue
            scheduled_for = project.schedule_next_run_at
            previous_status = project.status
            previous_last_enqueued = project.schedule_last_enqueued_at
            job = Job(project_id=project.id, action="cycle", status="queued", stage="queued", request_json="{}")
            db.add(job)
            try:
                sampling_control.reserve(db, tenant, project, job, allow_pool=True)
            except (HTTPException, sampling_control.SamplingBudgetExceeded):
                db.rollback()
                blocked = db.get(Project, project_id)
                if blocked is not None:
                    blocked.schedule_next_run_at = facade._next_scheduled_run(scheduled_for, blocked.schedule_interval_days, now)
                    db.commit()
                result["quota_blocked"] += 1; continue
            project.status = "processing"
            project.schedule_last_enqueued_at = now
            project.schedule_next_run_at = facade._next_scheduled_run(scheduled_for, project.schedule_interval_days, now)
            try:
                db.flush()
            except IntegrityError:
                db.rollback(); result["busy"] += 1; continue
            job.log_path = str(job_log_path(tenant.directory_slug, project.slug, job.id))
            db.commit()
            try:
                task_result = facade.task_cycle.delay(tenant.directory_slug, project.slug, job_id=job.id)
                job.celery_task_id = getattr(task_result, "id", None)
                db.commit()
            except Exception as exc:  # noqa: BLE001
                job.status = "failed"; job.error = f"{type(exc).__name__}: {exc}"; job.finished_at = now
                sampling_control.release_reservation(job)
                project.status = previous_status; project.schedule_next_run_at = scheduled_for
                project.schedule_last_enqueued_at = previous_last_enqueued
                db.commit(); result["failed"] += 1; continue
            result["enqueued"] += 1
        return result
    finally:
        db.close()


@celery_app.task(name="citeaura.reconcile_platform_usage")
def task_reconcile_platform_usage(limit=100):
    """补偿因数据库瞬时故障未完成的平台代付计量。"""
    return {"processed": reconcile_usage_outbox(limit=limit)}
