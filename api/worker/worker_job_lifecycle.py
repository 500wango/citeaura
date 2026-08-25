"""Worker Job claim, progress, and terminal-state lifecycle."""

import json
from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy.exc import SQLAlchemyError

from api.adapters import locking, regression_alerts, sampling_control
from api.adapters.engine import job_log_path, tenant_slug
from api.models import Job, Project, Tenant
from api.product_events import record_product_event


def _task_facade():
    from api.worker import tasks as task_module

    return task_module


@contextmanager
def _job_status(tenant_id, project_slug, action, job_id=None):
    """把 Job 标为 running/done/failed，并提供粗粒度进度回调。"""
    tracked_job_id = None
    log_path = None

    def prepare(db):
        nonlocal tracked_job_id, log_path
        job = _task_facade()._find_job(db, tenant_id, project_slug, action, job_id)
        if job is None:
            return job_id is None
        redelivered_task_id = _task_facade()._redelivered_task_id()
        if job.status == "running" and redelivered_task_id and job.celery_task_id == redelivered_task_id:
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

        def update(stage, progress):
            if tracked_job_id is None:
                return

            def persist(db):
                job = db.get(Job, tracked_job_id)
                if job is None:
                    return None
                job.stage = str(stage)[:64]
                job.progress = max(int(job.progress or 0), max(0, min(99, int(progress))))
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

        with locking.project_lock(tenant_slug(str(tenant_id)), project_slug, allow_reentrant=True):
            with _task_facade()._capture_task_output(log_path):
                yield update
    except BaseException as exc:
        error_message = f"{type(exc).__name__}: {exc}"
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
                if job is None or job.status == "done":
                    return
                project = db.get(Project, job.project_id)
                job.status = "done"
                job.stage = "complete"
                job.progress = 100
                job.finished_at = datetime.now(timezone.utc)
                job.error = None
                if project is not None:
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
                _task_facade()._job_transaction(mark_complete, retries=4)
            except BaseException as completion_error:
                _task_facade()._append_job_event(
                    log_path,
                    f"{action} completion status failed: {type(completion_error).__name__}: {completion_error}",
                )

                def mark_failed_after_completion(db):
                    job = db.get(Job, tracked_job_id)
                    if job is None or job.status == "done":
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
            if action in regression_alerts.SAMPLE_ACTIONS:
                alert = regression_alerts.notify_if_needed(tenant_id, project_slug, action)
                _task_facade()._append_job_event(log_path, f"regression alert {alert.get('status')}")
        _task_facade()._append_job_event(log_path, f"{action} done")

__all__ = tuple(name for name in globals() if not name.startswith("__"))
