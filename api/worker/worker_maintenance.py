"""Worker 周期调度与平台用量对账任务。"""

import json
import shutil
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from api.adapters import sampling_control
from api.adapters.engine import job_log_path
from api.billing.limits import check_sample_run
from api import config
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
        _dispatch_trial_retests(db, facade, now, result)
        return result
    finally:
        db.close()


TRIAL_RETEST_DAYS = (7, 14)


def _retest_days(project):
    try:
        values = json.loads(project.trial_retests_json or "[]")
    except (TypeError, ValueError):
        return set()
    return {int(value) for value in values if str(value).isdigit()}


def _dispatch_trial_retests(db, facade, now, result):
    """试用项目在创建后第 7/14 天各自动复测一次；系统调度不受套餐 gating 限制。"""
    projects = (
        db.query(Project)
        .join(Tenant, Tenant.id == Project.tenant_id)
        .filter(
            Tenant.status == "active", Tenant.plan == "trial",
            Project.archived_at.is_(None), Project.status != "archived",
            Project.created_at.isnot(None),
        )
        .all()
    )
    for project in projects:
        done = _retest_days(project)
        due = [
            day for day in TRIAL_RETEST_DAYS
            if day not in done and facade._as_utc(project.created_at) + timedelta(days=day) <= now
        ]
        if not due:
            continue
        day = due[0]
        baseline_done = db.query(Job.id).filter(
            Job.project_id == project.id,
            Job.action.in_(("sample", "autopilot", "cycle", "serve")),
            Job.status == "done",
        ).first()
        if baseline_done is None:
            # 尚未完成首日基线时不复测；否则只会制造空采样。
            continue
        tenant = db.get(Tenant, project.tenant_id)
        if tenant is None or db.query(Job.id).filter(
            Job.project_id == project.id, Job.status.in_(("queued", "running")),
        ).first() is not None:
            result["busy"] += 1
            continue
        try:
            check_sample_run(db, tenant, project)
        except HTTPException:
            result["quota_blocked"] += 1
            continue
        job = Job(
            project_id=project.id, action="cycle", status="queued", stage="queued",
            request_json=json.dumps({"trial_retest_day": day}),
        )
        db.add(job)
        try:
            sampling_control.reserve(db, tenant, project, job, allow_pool=True)
        except (HTTPException, sampling_control.SamplingBudgetExceeded):
            db.rollback()
            result["quota_blocked"] += 1
            continue
        project.trial_retests_json = json.dumps(sorted(done | {day}))
        project.status = "processing"
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            result["busy"] += 1
            continue
        job.log_path = str(job_log_path(tenant.directory_slug, project.slug, job.id))
        db.commit()
        try:
            task_result = facade.task_cycle.delay(tenant.directory_slug, project.slug, job_id=job.id)
            job.celery_task_id = getattr(task_result, "id", None)
            db.commit()
        except Exception as exc:  # noqa: BLE001
            job.status = "failed"
            job.error = f"{type(exc).__name__}: {exc}"
            job.finished_at = now
            sampling_control.release_reservation(job)
            project.trial_retests_json = json.dumps(sorted(done))
            db.commit()
            result["failed"] += 1
            continue
        result["enqueued"] += 1


@celery_app.task(name="citeaura.reconcile_platform_usage")
def task_reconcile_platform_usage(limit=100):
    """补偿因数据库瞬时故障未完成的平台代付计量。"""
    return {"processed": reconcile_usage_outbox(limit=limit)}


@celery_app.task(name="citeaura.rebuild_projections")
def task_rebuild_projections(tenant=None, project=None, force=False, dry_run=False):
    """从文件系统重建测量投影；文件系统始终是唯一真源。"""
    from api.adapters.engine import geolib, tenant_slug, with_tenant_read_context
    from api.projections.rebuild import rebuild_index

    db = SessionLocal()
    try:
        query = db.query(Project, Tenant).join(Tenant, Tenant.id == Project.tenant_id)
        if tenant:
            query = query.filter(Tenant.directory_slug == tenant_slug(tenant))
        if project:
            query = query.filter(Project.slug == project)
        results = []
        for project_record, tenant_record in query.order_by(Project.id).all():
            try:
                with with_tenant_read_context(tenant_record.directory_slug, project_record.slug):
                    result = rebuild_index(
                        db,
                        tenant_record.id,
                        project_record.id,
                        geolib.project_dir(project_record.slug),
                        force=force,
                        dry_run=dry_run,
                    )
            except Exception as exc:  # noqa: BLE001 - 单个项目失败不影响其余项目
                db.rollback()
                results.append({
                    "tenant": tenant_record.directory_slug,
                    "project": project_record.slug,
                    "status": "error",
                    "error": str(exc)[:500],
                })
                continue
            results.append({"tenant": tenant_record.directory_slug, "project": project_record.slug, **result})
        return {"processed": len(results), "projects": results}
    finally:
        db.close()


@celery_app.task(name="citeaura.cleanup_expired_projects")
def task_cleanup_expired_projects(now_iso=None, dry_run=False):
    """归档超过保留期的项目目录；数据库记录保留为 purged 以便审计。"""
    from api.adapters.engine import tenant_project_dir

    now = datetime.fromisoformat(now_iso) if now_iso else datetime.now(timezone.utc)
    now = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    cutoff = now - timedelta(days=config.project_retention_days())
    result = {"scanned": 0, "purged": 0, "skipped": 0, "failed": 0}
    db = SessionLocal()
    try:
        projects = db.query(Project).join(Tenant, Tenant.id == Project.tenant_id).filter(
            Project.status != "purged",
            Project.archived_at.isnot(None),
            Project.archived_at < cutoff,
        ).all()
        result["scanned"] = len(projects)
        for project in projects:
            tenant = db.get(Tenant, project.tenant_id)
            if tenant is None:
                result["skipped"] += 1
                continue
            if db.query(Job.id).filter(
                Job.project_id == project.id, Job.status.in_(("queued", "running")),
            ).first() is not None:
                result["skipped"] += 1
                continue
            if dry_run:
                result["purged"] += 1
                continue
            try:
                directory = tenant_project_dir(tenant.directory_slug, project.slug)
                if directory.is_dir():
                    shutil.rmtree(directory)
                project.status = "purged"
                project.archived_at = project.archived_at or now
                db.commit()
                result["purged"] += 1
            except OSError:
                db.rollback()
                result["failed"] += 1
        return result
    finally:
        db.close()
