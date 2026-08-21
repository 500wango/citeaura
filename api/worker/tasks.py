"""引擎异步任务。"""

import json
import logging
import os
import time
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from celery import current_task
from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.exc import DBAPIError, IntegrityError, SQLAlchemyError

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
from api.product_events import record_product_event
from api.settings.crypto import decrypt_key
from api.worker.celery_app import celery_app


logger = logging.getLogger(__name__)

MAX_JOB_ATTEMPTS = 3
REVIEW_RESERVATION_TTL = timedelta(hours=2)


PIPELINE_ACTIONS = {
    "crawl": {"label": "Crawl Website", "args": ["--max-pages"]},
    "audit": {"label": "Site Audit", "args": []},
    "sample": {"label": "AI Sampling", "args": ["--limit", "--repeat", "--platforms", "--question-ids"]},
    "bootstrap": {"label": "Auto-bootstrap Baseline", "args": ["--skip-llm"]},
    "deliverables": {"label": "Generate Three Deliverables", "args": []},
    "plan": {"label": "Build Action Tickets", "args": []},
    "expand": {"label": "Query Expansion", "args": ["--no-llm"]},
    "blueprint": {"label": "Build Blueprint", "args": []},
    "generate": {"label": "Generate Assets", "args": ["--asset", "--draft", "--draft-limit"]},
    "lint": {"label": "Draft Risk Inspection", "args": []},
    "report": {"label": "Generate Diagnostic Report", "args": []},
    "verify": {"label": "Closed-Loop Verify", "args": ["--no-recrawl"]},
    "deliver": {"label": "Compile Delivery Pack", "args": []},
    "sample-sheet": {"label": "Export Manual Sample Sheet", "args": []},
    "autopilot": {"label": "Autopilot Bootstrap", "args": ["--no-sample", "--limit", "--skip-llm"]},
    "serve": {
        "label": "Run Full Optimization Cycle",
        "args": ["--max-pages", "--limit", "--no-sample", "--draft", "--draft-limit"],
    },
}

PLATFORM_FUNDED_ACTIONS = frozenset(("sample", "autopilot", "serve", "cycle"))
_JOB_NOT_CLAIMED = object()

_ACTION_METHODS = {
    "crawl": "cmd_crawl",
    "audit": "cmd_audit",
    "sample": "cmd_sample",
    "bootstrap": "cmd_bootstrap",
    "deliverables": "cmd_deliverables",
    "plan": "cmd_plan",
    "expand": "cmd_expand",
    "blueprint": "cmd_blueprint",
    "generate": "cmd_generate",
    "lint": "cmd_lint",
    "report": "cmd_report",
    "verify": "cmd_verify",
    "deliver": "cmd_deliver",
    "sample-sheet": "cmd_sheet",
    "autopilot": "cmd_autopilot",
    "serve": "cmd_serve",
}

_ACTION_DEFAULTS = {
    "crawl": {"max_pages": None},
    "audit": {},
    "sample": {"limit": None, "repeat": 1, "platforms": None, "question_ids": None},
    "bootstrap": {"skip_llm": False},
    "deliverables": {},
    "plan": {},
    "expand": {"no_llm": False},
    "blueprint": {},
    "generate": {"asset": None, "draft": False, "draft_limit": None},
    "lint": {},
    "report": {},
    "verify": {"no_recrawl": False},
    "deliver": {},
    "sample-sheet": {},
    "autopilot": {"no_sample": False, "limit": None, "skip_llm": False},
    "serve": {"max_pages": None, "limit": None, "no_sample": False, "draft": False, "draft_limit": None},
}

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
        brand_facts.sync_sample_factcheck(project_slug, verification)
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


def _should_require_sampling_result(action, params):
    if action == "sample":
        return True
    if action not in ("autopilot", "serve"):
        return False
    params = params or {}
    if params.get("--no-sample", False) or params.get("no_sample", False):
        return False
    return True


def _action_namespace(action, params=None):
    """按引擎动作白名单清洗参数，并转换为 geo.cmd_* 所需对象。"""
    if action not in PIPELINE_ACTIONS:
        raise ValueError(f"unsupported pipeline action: {action}")
    values = dict(_ACTION_DEFAULTS[action])
    allowed = set(PIPELINE_ACTIONS[action]["args"])
    for raw_name, value in (params or {}).items():
        flag = str(raw_name)
        if not flag.startswith("--"):
            flag = "--" + flag.replace("_", "-")
        if flag not in allowed:
            continue
        name = flag[2:].replace("-", "_")
        if flag in _FLAG_ARGS:
            values[name] = value is True
        elif value in (None, "", []):
            continue
        elif flag in _INTEGER_LIMITS:
            number = int(value)
            minimum, maximum = _INTEGER_LIMITS[flag]
            if not minimum <= number <= maximum:
                raise ValueError(f"{flag} must be between {minimum} and {maximum}")
            values[name] = number
        elif flag in _CSV_ARGS:
            values[name] = ",".join(str(item) for item in value) if isinstance(value, list) else str(value)
    return SimpleNamespace(**values)


def _run_pipeline_action(action, project_slug, params=None):
    import geo

    method = getattr(geo, _ACTION_METHODS[action])
    args = _action_namespace(action, params)
    args.slug = project_slug
    method(args)
    return {"status": "done", "action": action, "project_slug": project_slug}


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


def _engine_keys(tenant_id):
    """读取租户 Key。数据库不可用时失败，避免把空集合注入成无密钥运行。"""
    db = SessionLocal()
    try:
        return load_tenant_keys(db, tenant_id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise RuntimeError("engine_keys_unavailable") from exc
    finally:
        db.close()


def _engine_funding(tenant_id, project_slug, allow_pool=True):
    """读取项目有效密钥及其中由平台池承担的引擎。"""
    db = SessionLocal()
    try:
        return resolve_funding(db, tenant_id, project_slug, allow_pool=allow_pool)
    except SQLAlchemyError as exc:
        db.rollback()
        raise RuntimeError("engine_funding_unavailable") from exc
    finally:
        db.close()


class SamplingPlatformUnavailable(RuntimeError):
    """显式请求的平台没有被 Worker funding 提供。"""

    def __init__(self, missing, funding):
        self.missing = tuple(sorted(set(missing)))
        self.funding = funding
        super().__init__("sampling_platform_unavailable:" + ",".join(self.missing))


def _funding_diagnostic(tenant_id, project_slug, funding, custom_providers):
    """生成不含密钥值的 Worker funding 诊断快照。"""
    keys = funding.get("keys", {}) if isinstance(funding, dict) else {}
    engine_codes = sorted(str(code) for code in keys)
    env_names = []
    for code in engine_codes:
        try:
            env_names.append(_environment_name(code))
        except ValueError:
            continue
    tenant_directory = funding.get("tenant_directory_slug") if isinstance(funding, dict) else None
    return {
        "tenant_arg": str(tenant_id),
        "tenant_id": funding.get("tenant_id") if isinstance(funding, dict) else None,
        "tenant_directory_slug": tenant_directory,
        "runtime_tenant": tenant_directory or str(tenant_id),
        "project_slug": str(project_slug),
        "source_revision": config.source_revision(),
        "database_target_fingerprint": config.database_target_fingerprint(),
        "funded_engine_codes": engine_codes,
        "pool_engine_codes": sorted(str(code) for code in (funding.get("pool_codes", ()) if isinstance(funding, dict) else ())),
        "custom_engine_codes": sorted(str(item.get("code")) for item in (custom_providers or []) if item.get("code")),
        "injected_env_names": sorted(set(env_names)),
    }


def _validate_requested_platforms(platforms, funding):
    """显式平台必须在 Worker funding 中，否则阻断本次采样。"""
    if not platforms or not isinstance(funding, dict) or funding.get("tenant_id") is None:
        return
    if isinstance(platforms, str):
        platforms = platforms.split(",")
    requested = [str(code).strip().lower() for code in platforms if str(code).strip()]
    funded = set(funding.get("keys", {})) | set(funding.get("pool_codes", ()))
    missing = [code for code in requested if code not in funded]
    if missing:
        raise SamplingPlatformUnavailable(missing, funding)


def _engine_custom_providers(tenant_id):
    """读取租户自定义供应商。数据库不可用时失败，避免静默丢掉供应商。"""
    db = SessionLocal()
    try:
        return load_custom_providers(db, tenant_id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise RuntimeError("engine_providers_unavailable") from exc
    finally:
        db.close()


def _sync_custom_provider_scope(project_slug, providers):
    """把当前租户自定义供应商加入项目默认采样集合。"""
    config_path = geolib.project_dir(project_slug) / "geo.json"
    if not config_path.is_file():
        return
    config = geolib.load_config(project_slug)
    configured = {provider["code"] for provider in providers}
    original = list(config.get("platforms") or [])
    platforms = [code for code in original if not code.startswith("custom_") or code in configured]
    for provider in providers:
        if provider["code"] not in platforms:
            platforms.append(provider["code"])
    labels = {provider["code"]: provider["name"] for provider in providers if provider.get("name")}
    model_ids = {
        provider["code"]: provider["model_id"]
        for provider in providers
        if provider.get("code") and provider.get("model_id")
    }
    changed = (
        platforms != original
        or config.get("provider_labels") != labels
        or config.get("provider_model_ids") != model_ids
    )
    if changed:
        config["platforms"] = platforms
        if labels:
            config["provider_labels"] = labels
        else:
            config.pop("provider_labels", None)
        if model_ids:
            config["provider_model_ids"] = model_ids
        else:
            config.pop("provider_model_ids", None)
        geolib.save_config(project_slug, config)


def _sync_funded_engine_scope(project_slug, funded_codes):
    """把当前 funding 中可运行的全局 API 引擎加入默认采样集合。"""
    config_path = geolib.project_dir(project_slug) / "geo.json"
    if not config_path.is_file():
        return
    config = geolib.load_config(project_slug)
    funded = {
        str(code).strip().lower()
        for code in (funded_codes or ())
        if str(code).strip()
    }
    original = list(config.get("platforms") or [])
    platforms = list(original)
    for code in sampling_control.BUILTIN_GLOBAL_SAMPLE_PLATFORMS:
        if code in funded and code not in platforms:
            platforms.append(code)
    if platforms != original:
        config["platforms"] = platforms
        geolib.save_config(project_slug, config)


@contextmanager
def _funded_engine_context(tenant_id, project_slug, action, job_id=None, allow_pool=True):
    """注入 BYOK/平台池密钥，并在退出时持久化平台代付逻辑调用。"""
    funding = _engine_funding(tenant_id, project_slug, allow_pool=allow_pool)
    if funding.get("tenant_id") is None:
        raise RuntimeError("worker_tenant_not_found")
    custom_providers = _engine_custom_providers(tenant_id)
    runtime_tenant = funding.get("tenant_directory_slug") or str(tenant_id)
    diagnostic = _funding_diagnostic(tenant_id, project_slug, funding, custom_providers)
    logger.info(
        "Worker funding resolved tenant_arg=%s tenant_id=%s tenant_directory_slug=%s "
        "project_slug=%s source_revision=%s database_target_fingerprint=%s "
        "funded_engine_codes=%s pool_engine_codes=%s custom_engine_codes=%s injected_env_names=%s",
        diagnostic["tenant_arg"], diagnostic["tenant_id"], diagnostic["tenant_directory_slug"],
        diagnostic["project_slug"], diagnostic["source_revision"],
        diagnostic["database_target_fingerprint"], diagnostic["funded_engine_codes"],
        diagnostic["pool_engine_codes"], diagnostic["custom_engine_codes"],
        diagnostic["injected_env_names"],
    )
    context_options = {"keys": funding["keys"]}
    if custom_providers:
        context_options["custom_providers"] = custom_providers
    with with_tenant_context(runtime_tenant, project_slug, **context_options):
        diagnostic["runtime_env_present"] = {
            name: bool(os.environ.get(name)) for name in diagnostic["injected_env_names"]
        }
        logger.info(
            "Worker funding runtime environment present source_revision=%s "
            "database_target_fingerprint=%s runtime_env_present=%s",
            diagnostic["source_revision"], diagnostic["database_target_fingerprint"],
            diagnostic["runtime_env_present"],
        )
        if job_id is not None:
            _append_job_event(
                job_log_path(tenant_id, project_slug, job_id),
                "funding resolved " + json.dumps(diagnostic, sort_keys=True, ensure_ascii=True),
            )
        ensure_global_engine_scope(project_slug)
        _sync_funded_engine_scope(
            project_slug,
            set(funding.get("keys", {})) | set(funding.get("pool_codes", ())),
        )
        _sync_custom_provider_scope(project_slug, custom_providers)
        with meter_platform_calls(funding["pool_codes"]) as counts:
            try:
                yield funding
            except BaseException:
                raise
            finally:
                accounted = False
                for attempt in range(3):
                    try:
                        record_usage(funding, counts, action, job_id=job_id)
                        accounted = True
                        break
                    except Exception:
                        logger.warning(
                            "Platform usage accounting attempt %s failed",
                            attempt + 1,
                            exc_info=True,
                            extra={"action": action, "job_id": job_id},
                        )
                        if attempt < 2:
                            time.sleep(0.2 * (attempt + 1))
                if not accounted:
                    persist_usage_outbox(
                        funding,
                        counts,
                        action,
                        job_id=job_id,
                        error="platform usage accounting failed after retries",
                    )
                    logger.error(
                        "Platform usage accounting requires reconciliation",
                        extra={"action": action, "job_id": job_id, "calls": dict(counts)},
                    )


def _as_utc(value):
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _next_scheduled_run(scheduled_for, interval_days, now):
    """保持原有节奏，并跳过服务停机期间错过的周期。"""
    next_run = _as_utc(scheduled_for) + timedelta(days=interval_days)
    while next_run <= now:
        next_run += timedelta(days=interval_days)
    return next_run


def _reclaim_stale_jobs(db, now):
    """回收超过 Celery 最大执行窗口仍活跃的任务，避免项目永久占用。"""
    cutoff = now - timedelta(hours=2)
    stale_running = db.query(Job).filter(
        Job.status == "running",
        Job.started_at.isnot(None),
        Job.started_at < cutoff,
    ).all()
    stale_queued = db.query(Job).filter(
        Job.status == "queued",
        Job.created_at < cutoff,
    ).all()
    reclaimed = 0
    for job in stale_running + stale_queued:
        project = db.get(Project, job.project_id)
        job.status = "failed"
        job.stage = "failed"
        job.finished_at = now
        job.error = "worker_lost_or_timeout"
        if project is not None and project.status not in ("archived",):
            project.status = "failed"
        reclaimed += 1
    if reclaimed:
        db.commit()
    return reclaimed


@contextmanager
def _capture_task_output(log_path):
    """把引擎 print 输出写入当前 Job 日志。"""
    if log_path is None:
        yield
        return
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handle = log_path.open("a", encoding="utf-8", buffering=1)
    except OSError as exc:
        logger.error("Unable to capture job output in %s: %s", log_path, exc)
        yield
        return
    with handle:
        with redirect_stdout(handle), redirect_stderr(handle):
            yield


def _append_job_event(log_path, message):
    if log_path is None:
        return False
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"[citeaura] {message}\n")
    except OSError as exc:
        logger.error("Unable to append job event in %s: %s", log_path, exc)
        return False
    return True


def _database_connection_lost(exc):
    if exc.connection_invalidated:
        return True
    message = str(getattr(exc, "orig", exc)).lower()
    return any(marker in message for marker in (
        "connection has been closed",
        "connection is closed",
        "connection already closed",
        "closed the connection unexpectedly",
        "closed unexpectedly",
        "connection reset",
        "server closed the connection",
        "terminating connection",
    ))


def _job_transaction(operation):
    """用短会话更新 Job；断开的数据库连接可安全重放一次。"""
    for attempt in range(2):
        db = SessionLocal()
        try:
            result = operation(db)
            db.commit()
            return result
        except DBAPIError as exc:
            try:
                db.rollback()
            except SQLAlchemyError:
                pass
            if attempt == 0 and _database_connection_lost(exc):
                logger.warning("job status database connection lost; retrying with a fresh session")
                continue
            raise
        except SQLAlchemyError:
            db.rollback()
            raise
        finally:
            db.close()


@contextmanager
def _job_status(tenant_id, project_slug, action, job_id=None):
    """把 Job 标为 running/done/failed，并提供粗粒度进度回调。"""
    tracked_job_id = None
    log_path = None

    def prepare(db):
        nonlocal tracked_job_id, log_path
        job = _find_job(db, tenant_id, project_slug, action, job_id)
        if job is None:
            return job_id is None
        redelivered_task_id = _redelivered_task_id()
        if job.status == "running" and redelivered_task_id and job.celery_task_id == redelivered_task_id:
            next_attempt = int(job.attempt or 1) + 1
            if next_attempt > MAX_JOB_ATTEMPTS:
                db.query(Job).filter(Job.id == job.id, Job.status == "running").update({
                    Job.status: "failed",
                    Job.stage: "failed",
                    Job.finished_at: datetime.now(timezone.utc),
                    Job.error: "worker_redelivered_attempt_limit",
                }, synchronize_session=False)
                project = db.get(Project, job.project_id)
                if project is not None and project.status not in ("archived",):
                    project.status = "failed"
                logger.error(
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
            log_path = job_log_path(tenant.directory_slug, project.slug, job.id)
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

    claimed = _job_transaction(prepare)
    if not claimed:
        logger.info("Ignoring duplicate delivery for job %s", job_id)
        yield _JOB_NOT_CLAIMED
        return

    try:
        _append_job_event(log_path, f"{action} started")

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
                state = _job_transaction(persist)
            except SQLAlchemyError as exc:
                logger.warning(
                    "Unable to persist job progress; completion will retry with a fresh session: %s",
                    exc,
                )
                _append_job_event(log_path, f"progress {stage} delayed: database connection unavailable")
                return
            if state is not None:
                _append_job_event(log_path, f"progress {state[0]} {state[1]}")

        with locking.project_lock(tenant_slug(str(tenant_id)), project_slug, allow_reentrant=True):
            with _capture_task_output(log_path):
                yield update
    except BaseException as exc:
        error_message = f"{type(exc).__name__}: {exc}"
        _append_job_event(log_path, f"{action} failed: {error_message}")
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
                if project is not None:
                    project.status = "failed"

            try:
                _job_transaction(mark_failed)
            except SQLAlchemyError as status_error:
                raise exc from status_error
        raise
    else:
        if tracked_job_id is not None:
            def mark_complete(db):
                job = db.get(Job, tracked_job_id)
                if job is None:
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

            _job_transaction(mark_complete)
            if action in regression_alerts.SAMPLE_ACTIONS:
                alert = regression_alerts.notify_if_needed(tenant_id, project_slug, action)
                _append_job_event(log_path, f"regression alert {alert.get('status')}")
        _append_job_event(log_path, f"{action} done")


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

    args = SimpleNamespace(slug=project_slug, skip_llm=skip_llm, no_sample=no_sample, limit=None)
    started_at = datetime.now(timezone.utc)
    with _job_status(tenant_id, project_slug, job_action, job_id) as update:
        if update is _JOB_NOT_CLAIMED:
            return {"status": "ignored", "reason": "job_not_queued"}
        update = update or (lambda *args: None)
        update("bootstrap", 15)
        with _funded_engine_context(
            tenant_id, project_slug, job_action, job_id=job_id,
            allow_pool=job_action in PLATFORM_FUNDED_ACTIONS,
        ):
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
                measurement.record_sampling(
                    project_slug,
                    source="api",
                    requested_platforms=None,
                    limit=None,
                    repeat=1,
                    job_id=job_id,
                    byok_codes=funding.get("keys", {}).keys(),
                    pool_codes=funding.get("pool_codes", ()),
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
            _validate_requested_platforms(platforms, worker_funding)
            global_scope.normalize_project(project_slug)
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
        with _funded_engine_context(tenant_id, project_slug, "cycle", job_id=job_id, allow_pool=True):
            global_scope.normalize_project(project_slug)
            with site_signals.semantic_site_signals(project_slug):
                with global_scope.normalize_generated_outputs(project_slug):
                    geo.cmd_cycle(args)
            _require_sampling_output(
                _latest_metrics(project_slug), project_slug, job_id=job_id, started_at=started_at,
            )
            funding = _engine_funding(tenant_id, project_slug, allow_pool=True)
            measurement.record_sampling(
                project_slug,
                source="api",
                job_id=job_id,
                byok_codes=funding.get("keys", {}).keys(),
                pool_codes=funding.get("pool_codes", ()),
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
                    Project.schedule_interval_days.in_((7, 14, 30)),
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
                    Project.schedule_interval_days.in_((7, 14, 30)),
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
                if project.monthly_budget_cny_fen is not None or project.sample_call_limit is not None:
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
    import deliver

    with _job_status(tenant_id, project_slug, "deliver", job_id) as claim:
        if claim is _JOB_NOT_CLAIMED:
            return {"status": "ignored", "reason": "job_not_queued"}
        with with_tenant_context(str(tenant_id), project_slug, keys=_engine_keys(tenant_id)):
            global_scope.normalize_project(project_slug)
            site_signals.validate_project_signals(project_slug)
            delivery_directory = deliver.run(project_slug)
            return str(ensure_delivery_contract(project_slug, delivery_directory))


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
                _validate_requested_platforms(requested_platforms, worker_funding)
            global_scope.normalize_project(project_slug)
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
