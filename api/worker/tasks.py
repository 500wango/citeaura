"""引擎异步任务。"""

import json
import logging
import os
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from celery import current_task
from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from api import config
from api.adapters import baseline, brand_facts, global_scope, locking, measurement, regression_alerts, sampling_control, site_signals, ticket_workflow
from api.adapters.delivery import ensure_delivery_contract, ensure_legacy_deliverables_contract
from api.adapters.engine import (
    ENGINE_MAX_REPEAT,
    _environment_name,
    geolib,
    job_log_path,
    load_custom_providers,
    load_tenant_keys,
    tenant_slug,
    with_tenant_context,
)
from api.adapters.workspace import ensure_global_engine_scope, preserve_manual_tickets, resilient_crawl_evidence
from api.billing.limits import check_sample_run
from api.billing.platform_pool import (
    meter_platform_calls,
    persist_usage_outbox,
    record_usage,
    reconcile_usage_outbox,
    resolve_funding,
)
from api.db import SessionLocal
from api.models import IntegrationCredential, Job, Project, Tenant
from api.pipeline_catalog import ACTION_DEFAULTS, ACTION_METHODS, PIPELINE_ACTIONS
from api.product_events import record_product_event
from api.settings.crypto import decrypt_key
from api.worker.celery_app import celery_app
from api.worker import job_runtime as _job_runtime

_as_utc = _job_runtime.as_utc
_next_scheduled_run = _job_runtime.next_scheduled_run
_database_connection_lost = _job_runtime.database_connection_lost


logger = logging.getLogger(__name__)

MAX_JOB_ATTEMPTS = 3
REVIEW_RESERVATION_TTL = timedelta(hours=2)


PLATFORM_FUNDED_ACTIONS = frozenset(("sample", "autopilot", "serve", "cycle"))
_JOB_NOT_CLAIMED = object()

_INTEGER_LIMITS = {
    "--max-pages": (1, 1000),
    "--limit": (1, 1000),
    "--repeat": (1, ENGINE_MAX_REPEAT),
    "--draft-limit": (1, 100),
}
_FLAG_ARGS = {"--no-recrawl", "--draft", "--no-sample", "--skip-llm", "--no-llm"}
_CSV_ARGS = {"--platforms", "--asset", "--question-ids"}


def _latest_metrics_path(project_slug):
    directory = geolib.project_dir(project_slug) / "metrics"
    files = sorted(directory.glob("*.json")) if directory.exists() else []
    return files[-1] if files else None


def _latest_metrics(project_slug):
    path = _latest_metrics_path(project_slug)
    return geolib.read_json(path, {}) if path else {}


def _metrics_written_since(project_slug, started_at):
    if started_at is None:
        return True
    path = _latest_metrics_path(project_slug)
    if path is None:
        return False
    started = started_at if started_at.tzinfo else started_at.replace(tzinfo=timezone.utc)
    written = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return written >= started - timedelta(seconds=5)


def _sampling_succeeded(result, project_slug, job_id=None, started_at=None):
    if isinstance(result, dict):
        sample_count = int(result.get("sample_count") or 0)
        if sample_count > 0:
            platforms = result.get("platforms") or {}
            return any(
                isinstance(item, dict) and int(item.get("samples") or 0) > 0
                for item in platforms.values()
            )
    if started_at is not None and not _metrics_written_since(project_slug, started_at):
        return False
    metrics = result if isinstance(result, dict) and result.get("sample_summary") is not None else _latest_metrics(project_slug)
    if (
        job_id is not None
        and started_at is None
        and str(((metrics or {}).get("provenance") or {}).get("job_id")) != str(job_id)
    ):
        return False
    sample_summary = (metrics or {}).get("sample_summary") or {}
    successful = int(sample_summary.get("successful") or 0)
    if successful > 0:
        return True
    return any(
        isinstance(item, dict) and int(item.get("samples") or 0) > 0
        for item in ((metrics or {}).get("platforms") or {}).values()
    )


def _require_sampling_output(result, project_slug, job_id=None, started_at=None):
    if not _sampling_succeeded(result, project_slug, job_id=job_id, started_at=started_at):
        raise RuntimeError("sampling produced no measurable successful samples")
    return result


def _sync_claim_verification(project_slug):
    """用官网抓取证据对照事实库，并在有采样时回填 factcheck。"""
    try:
        facts_path = geolib.project_dir(project_slug) / "content" / "facts.md"
        if not facts_path.is_file():
            return None
        verification = brand_facts.verify_against_site(project_slug)
        # task lifecycle already owns the project lock; avoid reacquiring the
        # distributed lock while updating the derived factcheck ledger.
        brand_facts._sync_sample_factcheck_locked(project_slug, verification)
        return verification
    except Exception as exc:  # noqa: BLE001
        logger.warning("Claim verification deferred for %s: %s", project_slug, exc)
        return None


def _safe_delivery_contract(project_slug):
    """客户包门禁失败不推翻已完成的审计/工单基线。"""
    try:
        ensure_delivery_contract(project_slug)
        ensure_legacy_deliverables_contract(project_slug)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Delivery contract deferred for %s: %s", project_slug, exc)
        return f"{type(exc).__name__}: {exc}"

from api.worker.worker_funding import *  # noqa: F401,F403
from api.worker.worker_pipeline import *  # noqa: F401,F403
from api.worker.worker_job_lifecycle import _job_status

def _tenant_record(db, tenant_id):
    """按数据库 id 或租户名称查找租户。"""
    try:
        return db.get(Tenant, int(tenant_id))
    except (TypeError, ValueError):
        return db.query(Tenant).filter(or_(
            Tenant.name == str(tenant_id),
            Tenant.directory_slug == str(tenant_id),
        )).first()


def _find_job(db, tenant_id, project_slug, action, job_id):
    """定位 API 预创建的 Job，兼容 worker 直接调用。"""
    tenant = _tenant_record(db, tenant_id)
    if tenant is None:
        return None
    project = db.query(Project).filter(
        Project.tenant_id == tenant.id,
        Project.slug == project_slug,
    ).first()
    if project is None:
        return None
    if job_id is not None:
        try:
            job_id = int(job_id)
        except (TypeError, ValueError):
            return None
        return db.query(Job).filter(
            Job.id == job_id,
            Job.project_id == project.id,
            Job.action == action,
        ).first()
    return (
        db.query(Job)
        .filter(Job.project_id == project.id, Job.action == action, Job.status.in_(("queued", "running")))
        .order_by(Job.id.desc())
        .first()
    )


def _redelivered_task_id():
    """返回 Celery broker 重投任务的 ID；普通调用返回空值。"""
    request = getattr(current_task, "request", None)
    if request is None:
        return None
    delivery_info = getattr(request, "delivery_info", None) or {}
    redelivered = bool(
        getattr(request, "redelivered", False)
        or delivery_info.get("redelivered", False)
    )
    if not redelivered:
        return None
    value = getattr(request, "id", None)
    return str(value) if value else None

def _reclaim_stale_jobs(db, now):
    return _job_runtime.reclaim_stale_jobs(db, now)


def _capture_task_output(log_path):
    return _job_runtime.capture_task_output(log_path, logger)


def _append_job_event(log_path, message):
    return _job_runtime.append_job_event(log_path, message, logger)


def _job_transaction(operation, retries=2):
    return _job_runtime.job_transaction(operation, logger, retries=retries, session_factory=SessionLocal)

@celery_app.task(name="citeaura.bootstrap")
def task_bootstrap(
    tenant_id: str,
    project_slug: str,
    skip_llm: bool = False,
    no_sample: bool = False,
    job_action: str = "bootstrap",
    job_id=None,
):
    """执行新项目的完整自动引导。"""
    import geo

    args = SimpleNamespace(
        slug=project_slug, skip_llm=skip_llm, no_sample=no_sample, limit=None, no_delivery=True,
    )
    started_at = datetime.now(timezone.utc)
    with _job_status(tenant_id, project_slug, job_action, job_id) as update:
        if update is _JOB_NOT_CLAIMED:
            return {"status": "ignored", "reason": "job_not_queued"}
        update = update or (lambda *args: None)
        update("bootstrap", 15)
        with _funded_engine_context(
            tenant_id, project_slug, job_action, job_id=job_id,
            allow_pool=job_action in PLATFORM_FUNDED_ACTIONS,
        ) as worker_funding:
            with global_scope.normalize_generated_outputs(project_slug):
                with preserve_manual_tickets(project_slug):
                    with resilient_crawl_evidence(project_slug):
                        with site_signals.semantic_site_signals(project_slug):
                            geo.cmd_autopilot(args)
            baseline.normalize_bootstrap_metadata(project_slug)
            update("finalizing", 90)
            if not no_sample:
                _require_sampling_output(
                    _latest_metrics(project_slug), project_slug, job_id=job_id, started_at=started_at,
                )
                funding = _engine_funding(
                    tenant_id, project_slug, allow_pool=job_action in PLATFORM_FUNDED_ACTIONS,
                )
                latest_metrics = _latest_metrics(project_slug)
                measurement.record_sampling(
                    project_slug,
                    source="api",
                    requested_platforms=None,
                    limit=None,
                    repeat=1,
                    job_id=job_id,
                    byok_codes=funding.get("keys", {}).keys(),
                    pool_codes=funding.get("pool_codes", ()),
                    result=latest_metrics,
                    funding=worker_funding,
                )
            _sync_claim_verification(project_slug)
            delivery_error = _safe_delivery_contract(project_slug)
            return {
                "status": "done",
                "action": job_action,
                "project_slug": project_slug,
                "delivery_error": delivery_error,
            }


@celery_app.task(name="citeaura.sample")
def task_sample(
    tenant_id: str,
    project_slug: str,
    limit: int | None = None,
    platforms: list[str] | None = None,
    repeat: int = 1,
    question_ids: list[str] | None = None,
    job_id=None,
):
    """执行 API 采样和指标聚合。"""
    import sample

    with _job_status(tenant_id, project_slug, "sample", job_id) as update:
        if update is _JOB_NOT_CLAIMED:
            return {"status": "ignored", "reason": "job_not_queued"}
        update = update or (lambda *args: None)
        update("sampling", 15)
        with _funded_engine_context(tenant_id, project_slug, "sample", job_id=job_id) as worker_funding:
            global_scope.normalize_project(project_slug)
            config_path = geolib.project_dir(project_slug) / "geo.json"
            project_config = geolib.read_json(config_path, {}) if config_path.is_file() else {}
            _validate_requested_platforms(
                platforms,
                worker_funding,
                project_market=project_config.get("market"),
            )
            sample_kwargs = {
                "platforms": platforms,
                "repeat": repeat,
                "limit": limit,
            }
            if question_ids:
                sample_kwargs["question_ids"] = question_ids
            result = sample.run(project_slug, **sample_kwargs)
            if job_id is None:
                _require_sampling_output(result, project_slug)
            else:
                _require_sampling_output(result, project_slug, job_id=job_id)
            funding = worker_funding or _engine_funding(tenant_id, project_slug)
            measurement.record_sampling(
                project_slug,
                source="api",
                requested_platforms=platforms,
                limit=limit,
                repeat=repeat,
                question_ids=question_ids,
                job_id=job_id,
                byok_codes=funding.get("keys", {}).keys(),
                pool_codes=funding.get("pool_codes", ()),
                result=result,
                funding=worker_funding or funding,
            )
            global_scope.normalize_project(project_slug)
            update("finalizing", 90)
            return result


@celery_app.task(name="citeaura.cycle")
def task_cycle(tenant_id: str, project_slug: str, job_id=None):
    """执行抓取、体检、采样和报告周期。"""
    import geo

    args = SimpleNamespace(slug=project_slug, max_pages=None, limit=None)
    started_at = datetime.now(timezone.utc)
    with _job_status(tenant_id, project_slug, "cycle", job_id) as update:
        if update is _JOB_NOT_CLAIMED:
            return {"status": "ignored", "reason": "job_not_queued"}
        update = update or (lambda *args: None)
        update("crawl", 15)
        with _funded_engine_context(
            tenant_id, project_slug, "cycle", job_id=job_id, allow_pool=True,
        ) as worker_funding:
            global_scope.normalize_project(project_slug)
            with site_signals.semantic_site_signals(project_slug):
                with global_scope.normalize_generated_outputs(project_slug):
                    geo.cmd_cycle(args)
            _require_sampling_output(
                _latest_metrics(project_slug), project_slug, job_id=job_id, started_at=started_at,
            )
            funding = _engine_funding(tenant_id, project_slug, allow_pool=True)
            latest_metrics = _latest_metrics(project_slug)
            measurement.record_sampling(
                project_slug,
                source="api",
                job_id=job_id,
                byok_codes=funding.get("keys", {}).keys(),
                pool_codes=funding.get("pool_codes", ()),
                result=latest_metrics,
                funding=worker_funding,
            )
            update("finalizing", 90)
            return {"status": "done", "project_slug": project_slug}


@celery_app.task(name="citeaura.dispatch_schedules")
def task_dispatch_schedules(now_iso=None):
    """扫描到期项目并投递周期复跑任务。"""
    now = datetime.fromisoformat(now_iso) if now_iso else datetime.now(timezone.utc)
    now = _as_utc(now)
    result = {"scanned": 0, "enqueued": 0, "busy": 0, "quota_blocked": 0, "failed": 0}
    db = SessionLocal()
    try:
        _reclaim_stale_jobs(db, now)
        candidate_ids = [
            row[0]
            for row in (
                db.query(Project.id)
                .join(Tenant, Tenant.id == Project.tenant_id)
                .filter(
                    Tenant.status == "active",
                    Project.schedule_interval_days.in_((1, 7, 14, 30)),
                    Project.schedule_next_run_at.isnot(None),
                    Project.schedule_next_run_at <= now,
                )
                .order_by(Project.schedule_next_run_at, Project.id)
                .all()
            )
        ]
        result["scanned"] = len(candidate_ids)
        db.rollback()
        for project_id in candidate_ids:
            project = (
                db.query(Project)
                .filter(
                    Project.id == project_id,
                    Project.schedule_interval_days.in_((1, 7, 14, 30)),
                    Project.schedule_next_run_at.isnot(None),
                    Project.schedule_next_run_at <= now,
                )
                .with_for_update(skip_locked=True, of=Project)
                .first()
            )
            if project is None:
                db.rollback()
                continue
            tenant = db.get(Tenant, project.tenant_id)
            if tenant is None or tenant.status != "active":
                project.schedule_interval_days = None
                project.schedule_next_run_at = None
                db.commit()
                continue
            active = db.query(Job.id).filter(
                Job.project_id == project.id,
                Job.status.in_(("queued", "running")),
            ).first()
            if active is not None:
                result["busy"] += 1
                db.rollback()
                continue
            try:
                check_sample_run(db, tenant, project)
                sampling_control.ensure_allowed(db, tenant, project, allow_pool=True)
            except (HTTPException, sampling_control.SamplingBudgetExceeded):
                result["quota_blocked"] += 1
                scheduled_for = project.schedule_next_run_at
                project.schedule_next_run_at = _next_scheduled_run(
                    scheduled_for,
                    project.schedule_interval_days,
                    now,
                )
                db.commit()
                continue

            scheduled_for = project.schedule_next_run_at
            previous_status = project.status
            previous_last_enqueued = project.schedule_last_enqueued_at
            job = Job(project_id=project.id, action="cycle", status="queued", stage="queued", request_json="{}")
            db.add(job)
            try:
                sampling_control.reserve(db, tenant, project, job, allow_pool=True)
            except (HTTPException, sampling_control.SamplingBudgetExceeded):
                db.rollback()
                blocked_project = db.get(Project, project_id)
                if blocked_project is not None:
                    blocked_project.schedule_next_run_at = _next_scheduled_run(
                        scheduled_for,
                        blocked_project.schedule_interval_days,
                        now,
                    )
                    db.commit()
                result["quota_blocked"] += 1
                continue
            project.status = "processing"
            project.schedule_last_enqueued_at = now
            project.schedule_next_run_at = _next_scheduled_run(
                scheduled_for,
                project.schedule_interval_days,
                now,
            )
            try:
                db.flush()
            except IntegrityError:
                db.rollback()
                result["busy"] += 1
                continue
            job.log_path = str(job_log_path(tenant.directory_slug, project.slug, job.id))
            db.commit()
            try:
                task_result = task_cycle.delay(tenant.directory_slug, project.slug, job_id=job.id)
                job.celery_task_id = getattr(task_result, "id", None)
                db.commit()
            except Exception as exc:  # noqa: BLE001
                job.status = "failed"
                job.error = f"{type(exc).__name__}: {exc}"
                job.finished_at = now
                sampling_control.release_reservation(job)
                project.status = previous_status
                project.schedule_next_run_at = scheduled_for
                project.schedule_last_enqueued_at = previous_last_enqueued
                db.commit()
                result["failed"] += 1
                continue
            result["enqueued"] += 1
        return result
    finally:
        db.close()


@celery_app.task(name="citeaura.reconcile_platform_usage")
def task_reconcile_platform_usage(limit=100):
    """补偿因数据库瞬时故障未完成的平台代付计量。"""
    return {"processed": reconcile_usage_outbox(limit=limit)}


@celery_app.task(name="citeaura.verify")
def task_verify(tenant_id: str, project_slug: str, job_id=None):
    """执行工单自动验收。"""
    import verify

    with _job_status(tenant_id, project_slug, "verify", job_id) as claim:
        if claim is _JOB_NOT_CLAIMED:
            return {"status": "ignored", "reason": "job_not_queued"}
        with with_tenant_context(str(tenant_id), project_slug, keys=_engine_keys(tenant_id)):
            global_scope.normalize_project(project_slug)
            with site_signals.semantic_site_signals(project_slug):
                report = verify.run(project_slug)
            return ticket_workflow.record_verification(project_slug, report)


@celery_app.task(name="citeaura.deliver")
def task_deliver(tenant_id: str, project_slug: str, job_id=None):
    """生成客户交付包。"""
    with _job_status(tenant_id, project_slug, "deliver", job_id) as claim:
        if claim is _JOB_NOT_CLAIMED:
            return {"status": "ignored", "reason": "job_not_queued"}
        with with_tenant_context(str(tenant_id), project_slug, keys=_engine_keys(tenant_id)):
            global_scope.normalize_project(project_slug)
            site_signals.validate_project_signals(project_slug)
            measurement_scope = _prepare_delivery_measurement(
                tenant_id,
                project_slug,
                job_id=job_id,
            )
            # The SaaS adapter is the sole owner of the formal delivery path.
            # Keep the engine CLI renderer independent for standalone users.
            if measurement_scope is None:
                return str(ensure_delivery_contract(project_slug))
            return str(ensure_delivery_contract(
                project_slug,
                measurement_scope=measurement_scope,
                require_question_evidence=bool(measurement_scope.get("active_cohorts")),
            ))


@celery_app.task(name="citeaura.pipeline")
def task_pipeline(tenant_id: str, project_slug: str, action: str, params=None, job_id=None):
    """执行经过白名单校验的完整引擎动作。"""
    started_at = datetime.now(timezone.utc)
    with _job_status(tenant_id, project_slug, action, job_id) as update:
        if update is _JOB_NOT_CLAIMED:
            return {"status": "ignored", "reason": "job_not_queued"}
        update = update or (lambda *args: None)
        update(action, 15)
        with _funded_engine_context(
            tenant_id,
            project_slug,
            action,
            job_id=job_id,
            allow_pool=action in PLATFORM_FUNDED_ACTIONS,
        ) as worker_funding:
            if action == "sample":
                requested_platforms = (params or {}).get("--platforms", (params or {}).get("platforms"))
            global_scope.normalize_project(project_slug)
            if action == "sample":
                config_path = geolib.project_dir(project_slug) / "geo.json"
                project_config = geolib.read_json(config_path, {}) if config_path.is_file() else {}
                _validate_requested_platforms(
                    requested_platforms,
                    worker_funding,
                    project_market=project_config.get("market"),
                )
            if action in ("audit", "deliverables", "plan", "report", "deliver"):
                site_signals.validate_project_signals(project_slug)
            with global_scope.normalize_generated_outputs(project_slug):
                if action in ("plan", "autopilot", "serve"):
                    with preserve_manual_tickets(project_slug):
                        if action == "autopilot":
                            with resilient_crawl_evidence(project_slug):
                                with site_signals.semantic_site_signals(project_slug):
                                    result = _run_pipeline_action(action, project_slug, params)
                        else:
                            if action in ("serve",):
                                with site_signals.semantic_site_signals(project_slug):
                                    result = _run_pipeline_action(action, project_slug, params)
                            else:
                                result = _run_pipeline_action(action, project_slug, params)
                else:
                    if action in ("crawl", "verify"):
                        with site_signals.semantic_site_signals(project_slug):
                            result = _run_pipeline_action(action, project_slug, params)
                    else:
                        result = _run_pipeline_action(action, project_slug, params)
            if action in ("bootstrap", "autopilot"):
                baseline.normalize_bootstrap_metadata(project_slug)
            if action in ("sample", "autopilot", "serve") and not (params or {}).get("--no-sample", False):
                if _should_require_sampling_result(action, params):
                    _require_sampling_output(
                        result if action == "sample" else _latest_metrics(project_slug),
                        project_slug,
                        job_id=job_id,
                        started_at=started_at,
                    )
                funding = _engine_funding(
                    tenant_id, project_slug, allow_pool=action in PLATFORM_FUNDED_ACTIONS,
                )
                measurement.record_sampling(
                    project_slug,
                    source="api",
                    requested_platforms=(params or {}).get("--platforms"),
                    question_ids=(params or {}).get("--question-ids"),
                    limit=(params or {}).get("--limit"),
                    repeat=(params or {}).get("--repeat", 1),
                    job_id=job_id,
                    byok_codes=funding.get("keys", {}).keys(),
                    pool_codes=funding.get("pool_codes", ()),
                    result=result if isinstance(result, dict) else _latest_metrics(project_slug),
                    funding=worker_funding,
                )
                if action == "sample":
                    global_scope.normalize_project(project_slug)
            update("finalizing", 90)
            if action in ("bootstrap", "autopilot", "serve", "generate", "sample", "deliver"):
                _sync_claim_verification(project_slug)
            delivery_error = None
            if action in ("deliver",):
                ensure_delivery_contract(project_slug)
            elif action in ("autopilot", "serve"):
                delivery_error = _safe_delivery_contract(project_slug)
            if action in ("deliverables",) and delivery_error is None:
                try:
                    ensure_legacy_deliverables_contract(project_slug)
                except Exception as exc:  # noqa: BLE001
                    delivery_error = f"{type(exc).__name__}: {exc}"
            if delivery_error:
                if isinstance(result, dict):
                    result = {**result, "delivery_error": delivery_error}
                else:
                    result = {"result": result, "delivery_error": delivery_error}
            return result


@celery_app.task(name="citeaura.send_outreach")
def task_send_outreach(tenant_id: str, project_slug: str, draft_id: str, job_id=None):
    """领取已人工确认的草稿并通过租户 SMTP 发送。"""
    from api.adapters import outreach

    action = "outreach_send"
    db = SessionLocal()
    try:
        tenant = _tenant_record(db, tenant_id)
        if tenant is None:
            raise ValueError("tenant_not_found")
        tenant_name = tenant.directory_slug
        tenant_db_id = tenant.id
    finally:
        db.close()

    with _job_status(tenant_name, project_slug, action, job_id) as claim:
        if claim is _JOB_NOT_CLAIMED:
            return {"status": "ignored", "reason": "job_not_queued"}
        try:
            credential_db = SessionLocal()
            try:
                row = credential_db.query(IntegrationCredential).filter(
                    IntegrationCredential.tenant_id == tenant_db_id,
                    IntegrationCredential.provider == "outreach_smtp",
                ).first()
                if row is None:
                    raise outreach.OutreachError("smtp_not_configured")
                credentials = json.loads(decrypt_key(row.encrypted_value))
                settings = json.loads(row.config_json or "{}")
            finally:
                credential_db.close()
        except Exception as exc:
            with with_tenant_context(tenant_name, project_slug):
                outreach.mark_queued_failed(project_slug, draft_id, exc)
            raise
        with with_tenant_context(tenant_name, project_slug):
            try:
                draft = outreach.claim_for_sending(project_slug, draft_id)
                result = outreach.send_smtp(draft, settings, credentials)
            except Exception as exc:
                outreach.mark_failed(project_slug, draft_id, exc)
                outreach.mark_queued_failed(project_slug, draft_id, exc)
                raise
            outreach.mark_sent(project_slug, draft_id)
            return {"status": "done", "draft_id": draft_id, **result}


@celery_app.task(name="citeaura.archive_project")
def task_archive_project(tenant_id: str, project_slug: str, job_id=None):
    """将本地活动项目写成经校验的对象存储快照。"""
    from api.adapters import archive

    with _job_status(tenant_id, project_slug, "archive", job_id) as claim:
        if claim is _JOB_NOT_CLAIMED:
            return {"status": "ignored", "reason": "job_not_queued"}
        result = archive.create_archive(tenant_id, project_slug)
        return {"status": "done", "project_slug": project_slug, "archive": result}


@celery_app.task(name="citeaura.restore_project")
def task_restore_project(
    tenant_id: str,
    project_slug: str,
    archive_id: str,
    overwrite: bool = False,
    job_id=None,
):
    """校验对象快照并恢复到本地活动项目。"""
    from api.adapters import archive

    with _job_status(tenant_id, project_slug, "archive_restore", job_id) as claim:
        if claim is _JOB_NOT_CLAIMED:
            return {"status": "ignored", "reason": "job_not_queued"}
        result = archive.restore_archive(
            tenant_id,
            project_slug,
            archive_id,
            overwrite=overwrite,
        )
        return {"status": "done", "project_slug": project_slug, "restore": result}

__all__ = tuple(name for name in globals() if not name.startswith("__"))
