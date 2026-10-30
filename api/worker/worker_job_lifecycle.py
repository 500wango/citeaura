"""Worker Job claim, progress, and terminal-state lifecycle."""

import json
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone

from celery.exceptions import SoftTimeLimitExceeded
from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError

from api.adapters import locking, regression_alerts, sampling_control
from api.adapters.engine import job_log_path, tenant_slug
from api.adapters.log_translator import redact_secrets
from api.billing.access import sync_tenant_plan
from api.billing.limits import check_product_access
from api.models import Job, Project, Tenant
from api.pipeline_catalog import ENTITLEMENT_REQUIRED_ACTIONS
from api.product_events import record_product_event
from api.worker import job_cancel


# 稳定失败原因：工作区被平台禁用后，队列里的任务在认领阶段就被拒绝。
TENANT_DISABLED_REASON = "tenant_disabled"


def _task_facade():
    from api.worker import tasks as task_module

    return task_module


@contextmanager
def _job_status(tenant_id, project_slug, action, job_id=None, hold_project_lock=None):
    """把 Job 标为 running/done/failed，并提供粗粒度进度回调。

    隔离模式下项目锁仍由父进程持有；引擎子进程没有 Redis 凭据，
    通过 CITEAURA_SKIP_PROJECT_LOCK 跳过取锁，避免同一项目被并发执行。
    """
    if hold_project_lock is None:
        hold_project_lock = True
    tracked_job_id = None
    log_path = None

    def prepare(db):
        nonlocal tracked_job_id, log_path
        job = _task_facade()._find_job(db, tenant_id, project_slug, action, job_id)
        if job is None:
            return job_id is None
        redelivered_task_id = _task_facade()._redelivered_task_id()
        if job.status == "running" and redelivered_task_id and job.celery_task_id == redelivered_task_id:
            if job.budget_reservation_status == "reserved":
                # 前次平台池用量尚不可恢复，不能用同一个计费幂等键重复执行。
                # 仍存活的任务保持运行；失联任务由陈旧回收器转为 review。
                return False
            next_attempt = int(job.attempt or 1) + 1
            if next_attempt > _task_facade().MAX_JOB_ATTEMPTS:
                sampling_control.release_reservation(job)
                db.query(Job).filter(Job.id == job.id, Job.status == "running").update({
                    Job.status: "failed",
                    Job.stage: "failed",
                    Job.finished_at: datetime.now(timezone.utc),
                    Job.error: "worker_redelivered_attempt_limit",
                }, synchronize_session=False)
                project = db.get(Project, job.project_id)
                if project is not None and project.status not in ("archived",):
                    project.status = "failed"
                _task_facade().logger.error(
                    "Refusing redelivered job %s after %s attempts",
                    job.id, next_attempt,
                )
                return False
            reclaimed = db.query(Job).filter(
                Job.id == job.id,
                Job.status == "running",
                Job.celery_task_id == redelivered_task_id,
            ).update({
                Job.status: "queued",
                Job.stage: "requeued",
                Job.finished_at: None,
                Job.error: "worker_redelivered",
                Job.attempt: next_attempt,
            }, synchronize_session=False)
            if reclaimed != 1:
                return False
            db.flush()
            job.status = "queued"
            job.attempt = next_attempt
        if job.status != "queued":
            return False
        project = db.get(Project, job.project_id)
        tenant = db.get(Tenant, project.tenant_id) if project is not None else None
        if tenant is not None and tenant.status != "active":
            # 已禁用工作区不再认领任何新工作：in-flight 任务无法可靠中止，
            # 但认领入口拦截后队列里的任务不会真正开跑。
            sampling_control.release_reservation(job)
            job.status = "failed"
            job.stage = "failed"
            job.finished_at = datetime.now(timezone.utc)
            job.error = TENANT_DISABLED_REASON
            if project is not None and project.status != "archived":
                project.status = "ready"
            _task_facade().logger.info(
                "Refusing job %s: tenant %s is %s", job.id, tenant.id, tenant.status,
            )
            return False
        if tenant is not None and action in ENTITLEMENT_REQUIRED_ACTIONS:
            sync_tenant_plan(db, tenant.id)
            try:
                check_product_access(db, tenant)
            except HTTPException as exc:
                sampling_control.release_reservation(job)
                job.status = "failed"
                job.stage = "failed"
                job.finished_at = datetime.now(timezone.utc)
                job.error = (exc.detail or {}).get("error", "subscription_required")
                if project is not None and project.status != "archived":
                    project.status = "ready"
                return False
        if tenant is not None:
            log_path = _task_facade().job_log_path(tenant.directory_slug, project.slug, job.id)
            job.log_path = str(log_path)
        claimed = db.query(Job).filter(
            Job.id == job.id,
            Job.status == "queued",
        ).update({
            Job.status: "running",
            Job.stage: "preparing",
            Job.progress: max(int(job.progress or 0), 5),
            Job.started_at: datetime.now(timezone.utc),
            Job.heartbeat_at: datetime.now(timezone.utc),
            Job.error: None,
        }, synchronize_session=False)
        if claimed != 1:
            return False
        tracked_job_id = job.id
        return True

    claimed = _task_facade()._job_transaction(prepare)
    if not claimed:
        _task_facade().logger.info("Ignoring duplicate delivery for job %s", job_id)
        yield _task_facade()._JOB_NOT_CLAIMED
        return

    try:
        _task_facade()._append_job_event(log_path, f"{action} started")

        def mark_canceled(db):
            job = db.get(Job, tracked_job_id)
            if job is None or job.status in ("done", "canceled"):
                return
            project = db.get(Project, job.project_id)
            job.status = "canceled"
            job.stage = "canceled"
            job.finished_at = datetime.now(timezone.utc)
            job.error = "canceled_by_user"
            sampling_control.release_reservation(job)
            if project is not None:
                if project.status != "archived" and project.archived_at is None:
                    project.status = "ready"
                tenant = db.get(Tenant, project.tenant_id)
                record_product_event(
                    db,
                    "job_canceled",
                    tenant_id=project.tenant_id,
                    country_code=tenant.acquisition_country_code if tenant is not None else None,
                    properties={"project_id": project.id, "job_id": job.id, "action": job.action},
                )

        def update(stage, progress):
            if tracked_job_id is None:
                return
            job_cancel.raise_if_canceled()

            def persist(db):
                job = db.get(Job, tracked_job_id)
                if job is None:
                    return None
                job.stage = str(stage)[:64]
                job.progress = max(int(job.progress or 0), max(0, min(99, int(progress))))
                # 心跳：回收器据此区分"慢但活着"与"worker 已死"。
                job.heartbeat_at = datetime.now(timezone.utc)
                return job.stage, job.progress

            try:
                state = _task_facade()._job_transaction(persist)
            except SQLAlchemyError as exc:
                _task_facade().logger.warning(
                    "Unable to persist job progress; completion will retry with a fresh session: %s",
                    exc,
                )
                _task_facade()._append_job_event(log_path, f"progress {stage} delayed: database connection unavailable")
                return
            if state is not None:
                _task_facade()._append_job_event(log_path, f"progress {state[0]} {state[1]}")

        lock_context = (
            locking.project_lock(tenant_slug(str(tenant_id)), project_slug, allow_reentrant=True)
            if hold_project_lock else nullcontext()
        )
        with lock_context, job_cancel.bind(tracked_job_id):
            with _task_facade()._capture_task_output(log_path):
                yield update
    except BaseException as exc:
        if isinstance(exc, job_cancel.JobCanceled):
            # 取消已落库：异常本身不再冒泡，避免 Celery 把用户操作记成任务错误。
            _task_facade()._append_job_event(log_path, f"{action} canceled")
            if tracked_job_id is not None:
                try:
                    _task_facade()._job_transaction(mark_canceled)
                except SQLAlchemyError as status_error:
                    raise exc from status_error
            return
        if isinstance(exc, SoftTimeLimitExceeded):
            # 稳定机器码：前端与运维按此识别"未跑完超时"，而不是展示重复的类名。
            error_message = "task_timeout: worker soft time limit exceeded"
        else:
            error_message = redact_secrets(f"{type(exc).__name__}: {exc}")
        _task_facade()._append_job_event(log_path, f"{action} failed: {error_message}")
        if tracked_job_id is not None:
            def mark_failed(db):
                job = db.get(Job, tracked_job_id)
                if job is None:
                    return
                project = db.get(Project, job.project_id)
                job.status = "failed"
                job.stage = "failed"
                job.finished_at = datetime.now(timezone.utc)
                job.error = error_message
                if "platform_usage_accounting_pending" in error_message and job.budget_reservation_status == "reserved":
                    job.budget_reservation_status = "review"
                else:
                    sampling_control.release_reservation(job)
                if project is not None:
                    project.status = "failed"

            try:
                _task_facade()._job_transaction(mark_failed)
            except SQLAlchemyError as status_error:
                raise exc from status_error
        raise
    else:
        if tracked_job_id is not None:
            def mark_complete(db):
                job = db.get(Job, tracked_job_id)
                if job is None or job.status in ("done", "canceled"):
                    return
                if job.cancel_requested_at is not None:
                    # 取消请求在任务自然结束前落库：不能再写成 done。
                    mark_canceled(db)
                    _task_facade()._append_job_event(log_path, f"{action} canceled")
                    return "canceled"
                project = db.get(Project, job.project_id)
                job.status = "done"
                job.stage = "complete"
                job.progress = 100
                job.finished_at = datetime.now(timezone.utc)
                job.error = None
                if project is not None:
                    # 已归档项目可能仍有被 reclaim 后继续执行的任务；完成后
                    # 不能把归档状态改回 ready。
                    if project.status != "archived" and project.archived_at is None:
                        project.status = "ready"
                    tenant = db.get(Tenant, project.tenant_id)
                    event_name = "sample_completed" if job.action in ("sample", "autopilot", "serve", "cycle") else "job_completed"
                    record_product_event(
                        db,
                        event_name,
                        tenant_id=project.tenant_id,
                        country_code=tenant.acquisition_country_code if tenant is not None else None,
                        properties={"project_id": project.id, "job_id": job.id, "action": job.action},
                    )
                    if job.action == "verify":
                        record_product_event(
                            db,
                            "verify_completed",
                            tenant_id=project.tenant_id,
                            country_code=tenant.acquisition_country_code if tenant is not None else None,
                            properties={"project_id": project.id, "job_id": job.id},
                        )
                        record_product_event(
                            db,
                            "retest_completed",
                            tenant_id=project.tenant_id,
                            country_code=tenant.acquisition_country_code if tenant is not None else None,
                            properties={"project_id": project.id, "job_id": job.id},
                        )
                    elif job.action == "deliver":
                        record_product_event(
                            db,
                            "delivery_built",
                            tenant_id=project.tenant_id,
                            country_code=tenant.acquisition_country_code if tenant is not None else None,
                            properties={"project_id": project.id, "job_id": job.id},
                        )
                    if job.action in ("bootstrap", "autopilot", "serve", "cycle", "audit"):
                        try:
                            request_values = json.loads(job.request_json or "{}")
                        except (TypeError, ValueError):
                            request_values = {}
                        sampling_requested = job.action not in ("bootstrap",) and not bool(
                            request_values.get("no_sample") or request_values.get("--no-sample")
                        )
                        record_product_event(
                            db,
                            "diagnostic_ready",
                            tenant_id=project.tenant_id,
                            country_code=tenant.acquisition_country_code if tenant is not None else None,
                            properties={"project_id": project.id, "job_id": job.id, "sampling": sampling_requested},
                        )

            try:
                # Completion is the point at which a transient DB failure must not
                # leave the project occupied indefinitely. Retry more aggressively
                # than progress updates, then persist an explicit failed state.
                completion = _task_facade()._job_transaction(mark_complete, retries=4)
            except BaseException as completion_error:
                _task_facade()._append_job_event(
                    log_path,
                    f"{action} completion status failed: {type(completion_error).__name__}: {completion_error}",
                )

                def mark_failed_after_completion(db):
                    job = db.get(Job, tracked_job_id)
                    if job is None or job.status in ("done", "canceled"):
                        return
                    project = db.get(Project, job.project_id)
                    job.status = "failed"
                    job.stage = "failed"
                    job.finished_at = datetime.now(timezone.utc)
                    job.error = "completion_status_persist_failed"
                    sampling_control.release_reservation(job)
                    if project is not None:
                        project.status = "failed"

                try:
                    _task_facade()._job_transaction(mark_failed_after_completion, retries=4)
                except BaseException as fallback_error:
                    _task_facade().logger.exception("Unable to persist failed state for completed Job %s", tracked_job_id)
                    _task_facade()._append_job_event(
                        log_path,
                        f"completion failure state unavailable: {type(fallback_error).__name__}: {fallback_error}",
                    )
                raise
            if completion == "canceled":
                return
            if action in regression_alerts.SAMPLE_ACTIONS:
                alert = regression_alerts.notify_if_needed(tenant_id, project_slug, action)
                _task_facade()._append_job_event(log_path, f"regression alert {alert.get('status')}")
        _task_facade()._append_job_event(log_path, f"{action} done")

__all__ = tuple(name for name in globals() if not name.startswith("__"))
