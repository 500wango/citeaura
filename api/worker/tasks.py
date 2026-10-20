"""引擎异步任务。"""

import json
import logging
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from celery import current_task
from redis.exceptions import RedisError
from sqlalchemy import or_

from api import config
from api.adapters import baseline, brand_facts, global_scope, locking, measurement, regression_alerts, sampling_control, site_signals, ticket_workflow
from api.analytics.clustered_stats import DEFAULT_REPEAT
from api.adapters.delivery import ensure_delivery_contract, ensure_legacy_deliverables_contract
from api.adapters.engine import (
    ENGINE_MAX_REPEAT,
    _environment_name,
    geolib,
    load_custom_providers,
    load_tenant_keys,
    tenant_slug,
    with_tenant_context,
    with_tenant_read_context,
)
from api.adapters.workspace import ensure_global_engine_scope, preserve_manual_tickets, resilient_crawl_evidence
from api.billing.platform_pool import (
    meter_platform_calls,
    persist_usage_outbox,
    record_usage,
    resolve_funding,
)
from api.billing.limits import check_sample_run
from api.db import SessionLocal
from api.models import Job, Project, Tenant
from api.pipeline_catalog import ACTION_DEFAULTS, ACTION_METHODS, PIPELINE_ACTIONS
from api.product_events import record_product_event
from api.settings.crypto import decrypt_key
from api.worker.celery_app import celery_app
from api.worker.worker_sampling import (
    SamplingOutputError,
    _latest_metrics,
    _metrics_written_since,
    _require_sampling_output,
    _sampling_diagnostic,
    _sampling_rows,
    _sampling_succeeded,
)
from api.worker.worker_maintenance import task_dispatch_schedules, task_reconcile_platform_usage
from api.worker.worker_external import task_send_outreach, task_archive_project, task_restore_project
from api.worker import job_runtime as _job_runtime

_as_utc = _job_runtime.as_utc
_next_scheduled_run = _job_runtime.next_scheduled_run
_database_connection_lost = _job_runtime.database_connection_lost


logger = logging.getLogger(__name__)


def _evaluate_effects(project_slug):
    """采样后评估到期的效果实验；失败不影响采样主流程。"""
    if not config.effect_verification_enabled():
        return
    try:
        run_id = measurement.latest_run_id(project_slug)
        rows = measurement.run_rows(project_slug, run_id) if run_id else None
        ticket_workflow.record_effect_evaluations(
            project_slug, current_rows=rows, run_id=run_id,
        )
    except Exception as exc:  # noqa: BLE001 - 效果评估不能回滚已完成的采样
        logger.warning("effect evaluation failed for %s: %s", project_slug, exc)


def _sync_projections(tenant_id, project_slug):
    """把最新采样产物投影到数据库；失败只标记 dirty。"""
    from api.adapters.engine import tenant_project_dir
    from api.projections.service import mark_projection_dirty, sync_latest_run

    db = SessionLocal()
    try:
        project = db.query(Project).filter(
            Project.tenant_id == tenant_id, Project.slug == project_slug,
        ).first()
        if project is None:
            return
        try:
            with with_tenant_read_context(tenant_id, project_slug):
                sync_latest_run(db, tenant_id, project.id, tenant_project_dir(tenant_id, project_slug))
        except Exception as exc:  # noqa: BLE001 - 投影是派生索引，不能回滚采样
            db.rollback()
            mark_projection_dirty(db, tenant_id, project.id, error=exc)
            logger.warning("projection sync failed for %s: %s", project_slug, exc)
    finally:
        db.close()

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


def _ensure_delivery_with_measurement(tenant_id, project_slug, job_id=None, status_update=None):
    """按统一的问题证据门槛生成正式交付包。"""
    if status_update:
        status_update("evidence", 15)
    try:
        measurement_scope = _prepare_delivery_measurement(
            tenant_id,
            project_slug,
            job_id=job_id,
            status_update=status_update,
        )
    except TypeError:
        measurement_scope = _prepare_delivery_measurement(
            tenant_id,
            project_slug,
            job_id=job_id,
        )
    if status_update:
        status_update("compile", 70)
    if measurement_scope is None:
        target = ensure_delivery_contract(project_slug)
    else:
        target = ensure_delivery_contract(
            project_slug,
            measurement_scope=measurement_scope,
            require_question_evidence=bool(measurement_scope.get("active_cohorts")),
        )
    if status_update:
        status_update("package", 90)
    if job_id is not None:
        _append_job_event(
            job_log_path(tenant_id, project_slug, job_id),
            "[citeaura] Packaging deliverables into standalone ZIP archive...",
        )
    return target


def _safe_delivery_contract(tenant_id, project_slug, job_id=None, prepare_measurement=True, status_update=None):
    """客户包门禁失败不推翻已完成的审计/工单基线。"""
    try:
        if prepare_measurement:
            _ensure_delivery_with_measurement(tenant_id, project_slug, job_id=job_id, status_update=status_update)
        else:
            ensure_delivery_contract(project_slug)
        ensure_legacy_deliverables_contract(project_slug)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Delivery contract deferred for %s: %s", project_slug, exc)
        return f"{type(exc).__name__}: {exc}"

from api.worker.worker_funding import *  # noqa: F401,F403
from api.worker.worker_pipeline import *  # noqa: F401,F403
from api.worker.worker_isolation import *  # noqa: F401,F403
from api.worker.worker_job_lifecycle import _job_status

def _tenant_record(db, tenant_id):
    """按目录名或租户名称查找租户，不按主键猜测。"""
    tenant_id_str = str(tenant_id)
    result = db.query(Tenant).filter(or_(
        Tenant.directory_slug == tenant_id_str,
        Tenant.name == tenant_id_str,
    )).first()
    return result


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


TASK_DELIVERY_KEY_PREFIX = "citeaura:task-delivery"
TASK_DELIVERY_TTL_SECONDS = 7200


def _redelivered_task_id():
    """返回 Celery broker 重投任务的 ID；普通首次投递返回空值。

    Redis broker 不填 request.redelivered / delivery_info["redelivered"]，只用这两个
    标志会让重投恢复与 MAX_JOB_ATTEMPTS 完全不生效。这里额外用 SETNX 记录首次
    投递：同一个 task id 第二次进入即视为重投。
    """
    request = getattr(current_task, "request", None)
    if request is None:
        return None
    value = getattr(request, "id", None)
    if not value:
        return None
    delivery_info = getattr(request, "delivery_info", None) or {}
    if getattr(request, "redelivered", False) or delivery_info.get("redelivered", False):
        return str(value)
    try:
        first_delivery = locking.redis_client().set(
            f"{TASK_DELIVERY_KEY_PREFIX}:{value}",
            1,
            nx=True,
            ex=TASK_DELIVERY_TTL_SECONDS,
        )
    except (RedisError, AttributeError):
        # Redis 不可用（或测试替身不提供 SET）时退回 broker 标志语义，避免误判重投。
        return None
    return None if first_delivery else str(value)

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
    platforms=None,
    repeat=None,
):
    """执行新项目的完整自动引导。"""
    started_at = datetime.now(timezone.utc)
    with _job_status(tenant_id, project_slug, job_action, job_id) as update:
        if update is _JOB_NOT_CLAIMED:
            return {"status": "ignored", "reason": "job_not_queued"}
        update = update or (lambda *args: None)
        update("bootstrap", 15)
        allow_pool = job_action in PLATFORM_FUNDED_ACTIONS
        funding, custom_providers = resolve_job_funding(
            tenant_id, project_slug, allow_pool=allow_pool,
        )
        runtime_tenant = funding.get("tenant_directory_slug") or str(tenant_id)
        with with_tenant_read_context(runtime_tenant, project_slug):
            run_engine_job(
                tenant_id, project_slug, "autopilot", job_id=job_id, allow_pool=allow_pool,
                funding=funding, custom_providers=custom_providers,
                wrappers=(
                    "normalize_generated_outputs", "preserve_manual_tickets",
                    "resilient_crawl_evidence", "semantic_site_signals",
                ),
                skip_llm=skip_llm, no_sample=no_sample, limit=None, no_delivery=True,
                platforms=platforms, repeat=repeat or DEFAULT_REPEAT,
            )
            baseline.normalize_bootstrap_metadata(project_slug)
            update("finalizing", 90)
            if not no_sample:
                _require_sampling_output(
                    _latest_metrics(project_slug), project_slug, job_id=job_id, started_at=started_at,
                    funding=funding,
                )
                latest_metrics = _latest_metrics(project_slug)
                measurement.record_sampling(
                    project_slug,
                    source="api",
                    requested_platforms=None,
                    limit=None,
                    repeat=repeat or DEFAULT_REPEAT,
                    job_id=job_id,
                    byok_codes=funding.get("keys", {}).keys(),
                    pool_codes=funding.get("pool_codes", ()),
                    result=latest_metrics,
                    funding=funding,
                )
                _sync_projections(tenant_id, project_slug)
            _sync_claim_verification(project_slug)
            delivery_error = _safe_delivery_contract(
                tenant_id,
                project_slug,
                job_id=job_id,
                prepare_measurement=not no_sample,
                status_update=update,
            )
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
    repeat: int = DEFAULT_REPEAT,
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
        funding, custom_providers = resolve_job_funding(tenant_id, project_slug, allow_pool=False)
        runtime_tenant = funding.get("tenant_directory_slug") or str(tenant_id)
        with with_tenant_read_context(runtime_tenant, project_slug):
            config_path = geolib.project_dir(project_slug) / "geo.json"
            project_config = geolib.read_json(config_path, {}) if config_path.is_file() else {}
            _validate_requested_platforms(
                platforms,
                funding,
                project_market=project_config.get("market"),
            )
            sample_kwargs = {
                "platforms": platforms,
                "repeat": repeat,
                "limit": limit,
            }
            if question_ids:
                sample_kwargs["question_ids"] = question_ids
            result = run_engine_job(
                tenant_id, project_slug, "sample", job_id=job_id, allow_pool=False,
                funding=funding, custom_providers=custom_providers,
                wrappers=("normalize_project",), **sample_kwargs,
            )
            if job_id is None:
                _require_sampling_output(result, project_slug, funding=funding)
            else:
                _require_sampling_output(result, project_slug, job_id=job_id, funding=funding)
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
                funding=funding,
            )
            _sync_projections(tenant_id, project_slug)
            global_scope.normalize_project(project_slug)
            _evaluate_effects(project_slug)
            update("finalizing", 90)
            return result


@celery_app.task(name="citeaura.cycle")
def task_cycle(tenant_id: str, project_slug: str, job_id=None):
    """执行抓取、体检、采样和报告周期。"""
    started_at = datetime.now(timezone.utc)
    with _job_status(tenant_id, project_slug, "cycle", job_id) as update:
        if update is _JOB_NOT_CLAIMED:
            return {"status": "ignored", "reason": "job_not_queued"}
        update = update or (lambda *args: None)
        update("crawl", 15)
        funding, custom_providers = resolve_job_funding(tenant_id, project_slug, allow_pool=True)
        runtime_tenant = funding.get("tenant_directory_slug") or str(tenant_id)
        with with_tenant_read_context(runtime_tenant, project_slug):
            run_engine_job(
                tenant_id, project_slug, "cycle", job_id=job_id, allow_pool=True,
                funding=funding, custom_providers=custom_providers,
                wrappers=("normalize_project", "semantic_site_signals", "normalize_generated_outputs"),
                max_pages=None, limit=None,
            )
            _require_sampling_output(
                _latest_metrics(project_slug), project_slug, job_id=job_id, started_at=started_at,
                funding=funding,
            )
            latest_metrics = _latest_metrics(project_slug)
            measurement.record_sampling(
                project_slug,
                source="api",
                job_id=job_id,
                byok_codes=funding.get("keys", {}).keys(),
                pool_codes=funding.get("pool_codes", ()),
                result=latest_metrics,
                funding=funding,
            )
            _sync_projections(tenant_id, project_slug)
            _evaluate_effects(project_slug)
            update("finalizing", 90)
            return {"status": "done", "project_slug": project_slug}


@celery_app.task(name="citeaura.verify")
def task_verify(tenant_id: str, project_slug: str, job_id=None):
    """执行工单自动验收。"""
    with _job_status(tenant_id, project_slug, "verify", job_id) as claim:
        if claim is _JOB_NOT_CLAIMED:
            return {"status": "ignored", "reason": "job_not_queued"}
        funding, custom_providers = resolve_job_funding(tenant_id, project_slug, allow_pool=False)
        report = run_engine_job(
            tenant_id, project_slug, "verify", job_id=job_id, allow_pool=False,
            funding=funding, custom_providers=custom_providers,
            wrappers=("normalize_project", "semantic_site_signals"),
        )
        runtime_tenant = funding.get("tenant_directory_slug") or str(tenant_id)
        with with_tenant_read_context(runtime_tenant, project_slug):
            return ticket_workflow.record_verification(project_slug, report)


@celery_app.task(name="citeaura.deliver")
def task_deliver(tenant_id: str, project_slug: str, job_id=None):
    """生成客户交付包。"""
    with _job_status(tenant_id, project_slug, "deliver", job_id) as claim:
        if claim is _JOB_NOT_CLAIMED:
            return {"status": "ignored", "reason": "job_not_queued"}
        update = claim or (lambda *args: None)
        funding, _custom_providers = resolve_job_funding(tenant_id, project_slug, allow_pool=True)
        runtime_tenant = funding.get("tenant_directory_slug") or str(tenant_id)
        with with_tenant_read_context(runtime_tenant, project_slug):
            global_scope.normalize_project(project_slug)
            site_signals.validate_project_signals(project_slug)
            # The SaaS adapter is the sole owner of the formal delivery path.
            # Keep the engine CLI renderer independent for standalone users.
            return str(_ensure_delivery_with_measurement(
                tenant_id,
                project_slug,
                job_id=job_id,
                status_update=update,
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
        allow_pool = action in PLATFORM_FUNDED_ACTIONS
        funding, custom_providers = resolve_job_funding(
            tenant_id, project_slug, allow_pool=allow_pool,
        )
        runtime_tenant = funding.get("tenant_directory_slug") or str(tenant_id)
        if action == "sample":
            requested_platforms = (params or {}).get("--platforms", (params or {}).get("platforms"))
        with with_tenant_read_context(runtime_tenant, project_slug):
            if action == "sample":
                config_path = geolib.project_dir(project_slug) / "geo.json"
                project_config = geolib.read_json(config_path, {}) if config_path.is_file() else {}
                _validate_requested_platforms(
                    requested_platforms,
                    funding,
                    project_market=project_config.get("market"),
                )
            if action in ("audit", "deliverables", "plan", "report", "deliver"):
                site_signals.validate_project_signals(project_slug)
        wrappers = ["normalize_project", "normalize_generated_outputs"]
        if action in ("plan", "autopilot", "serve"):
            wrappers.append("preserve_manual_tickets")
        if action == "autopilot":
            wrappers.append("resilient_crawl_evidence")
        if action in ("autopilot", "serve", "crawl", "verify"):
            wrappers.append("semantic_site_signals")
        result = run_engine_job(
            tenant_id, project_slug, "pipeline", job_id=job_id, allow_pool=allow_pool,
            funding=funding, custom_providers=custom_providers,
            wrappers=tuple(wrappers), pipeline_action=action, params=params,
        )
        with with_tenant_read_context(runtime_tenant, project_slug):
            if action in ("bootstrap", "autopilot"):
                baseline.normalize_bootstrap_metadata(project_slug)
            if action == "sample" or (action in ("autopilot", "serve") and not (params or {}).get("--no-sample", False)):
                if _should_require_sampling_result(action, params):
                    # 统一读取落盘的 metrics：_run_pipeline_action 只返回状态字典，
                    # 把它当作采样结果会让成功的采样被判失败。
                    _require_sampling_output(
                        _latest_metrics(project_slug),
                        project_slug,
                        job_id=job_id,
                        started_at=started_at,
                        funding=funding,
                    )
                measurement.record_sampling(
                    project_slug,
                    source="api",
                    requested_platforms=(params or {}).get("--platforms"),
                    question_ids=(params or {}).get("--question-ids"),
                    limit=(params or {}).get("--limit"),
                    repeat=(params or {}).get("--repeat", DEFAULT_REPEAT),
                    job_id=job_id,
                    byok_codes=funding.get("keys", {}).keys(),
                    pool_codes=funding.get("pool_codes", ()),
                    result=result if isinstance(result, dict) else _latest_metrics(project_slug),
                    funding=funding,
                )
                _sync_projections(tenant_id, project_slug)
                if action == "sample":
                    global_scope.normalize_project(project_slug)
            update("finalizing", 90)
            if action in ("bootstrap", "autopilot", "serve", "generate", "sample", "deliver"):
                _sync_claim_verification(project_slug)
            delivery_error = None
            if action in ("deliver",):
                _ensure_delivery_with_measurement(
                    tenant_id,
                    project_slug,
                    job_id=job_id,
                    status_update=update,
                )
            elif action in ("autopilot", "serve"):
                no_sample = (
                    (params or {}).get("--no-sample")
                    or (params or {}).get("no_sample")
                )
                delivery_error = _safe_delivery_contract(
                    tenant_id,
                    project_slug,
                    job_id=job_id,
                    prepare_measurement=not bool(no_sample),
                    status_update=update,
                )
            if action in ("deliverables",) and delivery_error is None:
                try:
                    ensure_legacy_deliverables_contract(project_slug)
                except Exception as exc:  # noqa: BLE001
                    delivery_error = f"{type(exc).__name__}: {exc}"
            if delivery_error:
                if action in ("deliver", "deliverables"):
                    # 返回值和 task_ignore_result=True 一起会把这个错误丢掉，
                    # 客户端会看到"成功"但交付包不存在。
                    raise RuntimeError(f"delivery_contract_failed: {delivery_error}")
                _append_job_event(
                    job_log_path(tenant_id, project_slug, job_id) if job_id is not None else None,
                    f"[citeaura] Delivery contract deferred: {delivery_error}",
                )
                if isinstance(result, dict):
                    result = {**result, "delivery_error": delivery_error}
                else:
                    result = {"result": result, "delivery_error": delivery_error}
            return result


__all__ = tuple(name for name in globals() if not name.startswith("__"))
