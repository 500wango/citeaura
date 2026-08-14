"""引擎异步任务。"""

import json
import logging
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy.exc import DBAPIError, IntegrityError, SQLAlchemyError

from api.adapters import baseline, global_scope, measurement, sampling_control, site_signals, ticket_workflow
from api.adapters.delivery import ensure_delivery_contract, ensure_legacy_deliverables_contract
from api.adapters.engine import geolib, job_log_path, load_custom_providers, load_tenant_keys, with_tenant_context
from api.adapters.workspace import ensure_global_engine_scope, preserve_manual_tickets, resilient_crawl_evidence
from api.billing.limits import check_sample_run
from api.billing.platform_pool import meter_platform_calls, record_usage, resolve_funding
from api.db import SessionLocal
from api.models import IntegrationCredential, Job, Project, Tenant
from api.product_events import record_product_event
from api.settings.crypto import decrypt_key
from api.worker.celery_app import celery_app


logger = logging.getLogger(__name__)


PIPELINE_ACTIONS = {
    "crawl": {"label": "Crawl Website", "args": ["--max-pages"]},
    "audit": {"label": "Site Audit", "args": []},
    "sample": {"label": "AI Sampling", "args": ["--limit", "--repeat", "--platforms"]},
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

PLATFORM_FUNDED_ACTIONS = frozenset((
    "bootstrap", "sample", "cycle", "expand", "generate", "autopilot", "serve",
))

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
    "sample": {"limit": None, "repeat": 1, "platforms": None},
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
    "--repeat": (1, 10),
    "--draft-limit": (1, 100),
}
_FLAG_ARGS = {"--no-recrawl", "--draft", "--no-sample", "--skip-llm", "--no-llm"}
_CSV_ARGS = {"--platforms", "--asset"}


def _latest_metrics(project_slug):
    directory = geolib.project_dir(project_slug) / "metrics"
    files = sorted(directory.glob("*.json")) if directory.exists() else []
    return geolib.read_json(files[-1], {}) if files else {}


def _sampling_succeeded(result, project_slug):
    if isinstance(result, dict):
        sample_count = int(result.get("sample_count") or 0)
        if sample_count > 0:
            platforms = result.get("platforms") or {}
            return any(
                isinstance(item, dict) and int(item.get("samples") or 0) > 0
                for item in platforms.values()
            )
    metrics = _latest_metrics(project_slug)
    sample_summary = (metrics or {}).get("sample_summary") or {}
    successful = int(sample_summary.get("successful") or 0)
    if successful > 0:
        return True
    return any(
        isinstance(item, dict) and int(item.get("samples") or 0) > 0
        for item in ((metrics or {}).get("platforms") or {}).values()
    )


def _require_sampling_output(result, project_slug):
    if not _sampling_succeeded(result, project_slug):
        raise RuntimeError("sampling produced no measurable successful samples")
    return result


def _should_require_sampling_result(action, params):
    if action == "sample":
        return True
    if action not in ("autopilot", "serve"):
        return False
    params = params or {}
    if params.get("--no-sample", False):
        return False
    requested_platforms = params.get("--platforms")
    if requested_platforms:
        return True
    return False


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
        return db.query(Tenant).filter(Tenant.name == str(tenant_id)).first()


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


def _engine_keys(tenant_id):
    """读取租户 Key；直接调用任务且没有数据库时降级为空集合。"""
    db = SessionLocal()
    try:
        return load_tenant_keys(db, tenant_id)
    except SQLAlchemyError:
        db.rollback()
        return {}
    finally:
        db.close()


def _engine_funding(tenant_id, project_slug, allow_pool=True):
    """读取项目有效密钥及其中由平台池承担的引擎。"""
    db = SessionLocal()
    try:
        return resolve_funding(db, tenant_id, project_slug, allow_pool=allow_pool)
    except SQLAlchemyError:
        db.rollback()
        return {
            "keys": {}, "pool_codes": frozenset(), "rates": {},
            "tenant_id": None, "project_id": None,
        }
    finally:
        db.close()


def _engine_custom_providers(tenant_id):
    """读取租户自定义供应商；数据库不可用时降级为空。"""
    db = SessionLocal()
    try:
        return load_custom_providers(db, tenant_id)
    except SQLAlchemyError:
        db.rollback()
        return []
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
    if platforms != original:
        config["platforms"] = platforms
        geolib.save_config(project_slug, config)


def _latest_metrics(project_slug):
    directory = geolib.project_dir(project_slug) / "metrics"
    files = sorted(directory.glob("*.json")) if directory.exists() else []
    return geolib.read_json(files[-1], {}) if files else {}


def _sampling_succeeded(result, project_slug):
    if isinstance(result, dict):
        sample_count = int(result.get("sample_count") or 0)
        if sample_count > 0:
            return any(
                isinstance(item, dict) and int(item.get("samples") or 0) > 0
                for item in (result.get("platforms") or {}).values()
            )
    metrics = _latest_metrics(project_slug)
    sample_summary = (metrics or {}).get("sample_summary") or {}
    if int(sample_summary.get("successful") or 0) > 0:
        return True
    return any(
        isinstance(item, dict) and int(item.get("samples") or 0) > 0
        for item in ((metrics or {}).get("platforms") or {}).values()
    )


def _require_sampling_output(result, project_slug):
    if not _sampling_succeeded(result, project_slug):
        raise RuntimeError("sampling produced no measurable successful samples")
    return result


@contextmanager
def _funded_engine_context(tenant_id, project_slug, action, job_id=None, allow_pool=True):
    """注入 BYOK/平台池密钥，并在退出时持久化平台代付逻辑调用。"""
    funding = _engine_funding(tenant_id, project_slug, allow_pool=allow_pool)
    custom_providers = _engine_custom_providers(tenant_id)
    context_options = {"keys": funding["keys"]}
    if custom_providers:
        context_options["custom_providers"] = custom_providers
    with with_tenant_context(str(tenant_id), project_slug, **context_options):
        ensure_global_engine_scope(project_slug)
        _sync_custom_provider_scope(project_slug, custom_providers)
        with meter_platform_calls(funding["pool_codes"]) as counts:
            pending_error = None
            try:
                yield
            except BaseException as exc:
                pending_error = exc
                raise
            finally:
                try:
                    record_usage(funding, counts, action, job_id=job_id)
                except Exception:
                    logger.exception("platform usage accounting failed", extra={"action": action, "job_id": job_id})
                    if pending_error is None:
                        raise


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
            return
        project = db.get(Project, job.project_id)
        tenant = db.get(Tenant, project.tenant_id) if project is not None else None
        if tenant is not None:
            log_path = job_log_path(tenant.name, project.slug, job.id)
            job.log_path = str(log_path)
        tracked_job_id = job.id
        job.status = "running"
        job.stage = "preparing"
        job.progress = max(int(job.progress or 0), 5)
        job.started_at = datetime.now(timezone.utc)
        job.error = None

    _job_transaction(prepare)

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

        with _capture_task_output(log_path):
            yield update
    except Exception as exc:
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
    with _job_status(tenant_id, project_slug, job_action, job_id) as update:
        update = update or (lambda *args: None)
        update("bootstrap", 15)
        with _funded_engine_context(tenant_id, project_slug, job_action, job_id=job_id):
            with global_scope.normalize_generated_outputs(project_slug):
                with preserve_manual_tickets(project_slug):
                    with resilient_crawl_evidence(project_slug):
                        with site_signals.semantic_site_signals(project_slug):
                            geo.cmd_autopilot(args)
            baseline.normalize_bootstrap_metadata(project_slug)
            update("finalizing", 90)
            ensure_delivery_contract(project_slug)
            ensure_legacy_deliverables_contract(project_slug)
            if not no_sample:
                funding = _engine_funding(tenant_id, project_slug)
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
                _require_sampling_output(_latest_metrics(project_slug), project_slug)
            return {"status": "done", "action": job_action, "project_slug": project_slug}


@celery_app.task(name="citeaura.sample")
def task_sample(
    tenant_id: str,
    project_slug: str,
    limit: int | None = None,
    platforms: list[str] | None = None,
    repeat: int = 1,
    job_id=None,
):
    """执行 API 采样和指标聚合。"""
    import sample

    with _job_status(tenant_id, project_slug, "sample", job_id) as update:
        update = update or (lambda *args: None)
        update("sampling", 15)
        with _funded_engine_context(tenant_id, project_slug, "sample", job_id=job_id):
            global_scope.normalize_project(project_slug)
            result = sample.run(project_slug, platforms=platforms, repeat=repeat, limit=limit)
            _require_sampling_output(result, project_slug)
            funding = _engine_funding(tenant_id, project_slug)
            measurement.record_sampling(
                project_slug,
                source="api",
                requested_platforms=platforms,
                limit=limit,
                repeat=repeat,
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
    with _job_status(tenant_id, project_slug, "cycle", job_id) as update:
        update = update or (lambda *args: None)
        update("crawl", 15)
        with _funded_engine_context(tenant_id, project_slug, "cycle", job_id=job_id):
            global_scope.normalize_project(project_slug)
            with site_signals.semantic_site_signals(project_slug):
                with global_scope.normalize_generated_outputs(project_slug):
                    geo.cmd_cycle(args)
            funding = _engine_funding(tenant_id, project_slug)
            measurement.record_sampling(
                project_slug,
                source="api",
                job_id=job_id,
                byok_codes=funding.get("keys", {}).keys(),
                pool_codes=funding.get("pool_codes", ()),
            )
            _require_sampling_output(_latest_metrics(project_slug), project_slug)
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
                    sampling_control.ensure_allowed(db, tenant, project)
            except (HTTPException, sampling_control.SamplingBudgetExceeded):
                result["quota_blocked"] += 1
                db.rollback()
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
            job.log_path = str(job_log_path(tenant.name, project.slug, job.id))
            db.commit()
            try:
                task_result = task_cycle.delay(tenant.name, project.slug, job_id=job.id)
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


@celery_app.task(name="citeaura.verify")
def task_verify(tenant_id: str, project_slug: str, job_id=None):
    """执行工单自动验收。"""
    import verify

    with _job_status(tenant_id, project_slug, "verify", job_id):
        with with_tenant_context(str(tenant_id), project_slug, keys=_engine_keys(tenant_id)):
            global_scope.normalize_project(project_slug)
            with site_signals.semantic_site_signals(project_slug):
                report = verify.run(project_slug)
            return ticket_workflow.record_verification(project_slug, report)


@celery_app.task(name="citeaura.deliver")
def task_deliver(tenant_id: str, project_slug: str, job_id=None):
    """生成客户交付包。"""
    import deliver

    with _job_status(tenant_id, project_slug, "deliver", job_id):
        with with_tenant_context(str(tenant_id), project_slug, keys=_engine_keys(tenant_id)):
            global_scope.normalize_project(project_slug)
            site_signals.validate_project_signals(project_slug)
            delivery_directory = deliver.run(project_slug)
            return str(ensure_delivery_contract(project_slug, delivery_directory))


@celery_app.task(name="citeaura.pipeline")
def task_pipeline(tenant_id: str, project_slug: str, action: str, params=None, job_id=None):
    """执行经过白名单校验的完整引擎动作。"""
    with _job_status(tenant_id, project_slug, action, job_id) as update:
        update = update or (lambda *args: None)
        update(action, 15)
        with _funded_engine_context(
            tenant_id,
            project_slug,
            action,
            job_id=job_id,
            allow_pool=action in PLATFORM_FUNDED_ACTIONS,
        ):
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
                funding = _engine_funding(tenant_id, project_slug)
                measurement.record_sampling(
                    project_slug,
                    source="api",
                    requested_platforms=(params or {}).get("--platforms"),
                    limit=(params or {}).get("--limit"),
                    repeat=(params or {}).get("--repeat", 1),
                    job_id=job_id,
                    byok_codes=funding.get("keys", {}).keys(),
                    pool_codes=funding.get("pool_codes", ()),
                )
                if _should_require_sampling_result(action, params):
                    _require_sampling_output(_latest_metrics(project_slug), project_slug)
                if action == "sample":
                    global_scope.normalize_project(project_slug)
            update("finalizing", 90)
            if action in ("deliver", "autopilot", "serve"):
                ensure_delivery_contract(project_slug)
            if action in ("deliverables", "autopilot"):
                ensure_legacy_deliverables_contract(project_slug)
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
        tenant_name = tenant.name
        tenant_db_id = tenant.id
    finally:
        db.close()

    with _job_status(tenant_name, project_slug, action, job_id):
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

    with _job_status(tenant_id, project_slug, "archive", job_id):
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

    with _job_status(tenant_id, project_slug, "archive_restore", job_id):
        result = archive.restore_archive(
            tenant_id,
            project_slug,
            archive_id,
            overwrite=overwrite,
        )
        return {"status": "done", "project_slug": project_slug, "restore": result}
