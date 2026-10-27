"""隔离式引擎任务：父进程只调度、计量与写库，密钥只进入一次性子进程。"""

import threading
import time
from contextlib import contextmanager

from api import config
from api.adapters.engine import job_log_path, with_tenant_read_context
from api.adapters.workspace import ensure_global_engine_scope
from api.billing.platform_pool import persist_usage_outbox, record_usage
from api.worker import job_process, job_runner
from api.worker.worker_funding import _sync_custom_provider_scope, _sync_funded_engine_scope

# 必须明显小于 STALE_RUNNING_JOB_TIMEOUT_SECONDS（默认 4500s）。
HEARTBEAT_INTERVAL_SECONDS = 60


def _task_facade():
    from api.worker import tasks as task_module

    return task_module


@contextmanager
def _job_heartbeat(job_id):
    """子进程运行期间刷新 Job 心跳。

    父进程阻塞在 communicate() 上时不会走阶段 update()，回收器会把仍在
    采样的长任务误判成 worker_lost_or_timeout。
    """
    if job_id is None:
        yield
        return
    from datetime import datetime, timezone

    from sqlalchemy.exc import SQLAlchemyError

    from api.models import Job

    stop = threading.Event()
    logger = _task_facade().logger

    def touch():
        def operation(db):
            job = db.get(Job, job_id)
            if job is None or job.status != "running":
                return
            job.heartbeat_at = datetime.now(timezone.utc)

        try:
            _task_facade()._job_transaction(operation)
        except SQLAlchemyError as exc:
            # 心跳写不进去不能中断正在跑的采样。
            logger.warning("Unable to refresh heartbeat for job %s: %s", job_id, exc)

    def loop():
        while not stop.wait(HEARTBEAT_INTERVAL_SECONDS):
            touch()

    thread = threading.Thread(target=loop, name=f"job-heartbeat-{job_id}", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=10)


def resolve_job_funding(tenant_id, project_slug, allow_pool=True):
    """解析资金与自定义供应商，并同步项目作用域；不向父进程注入 Key。"""
    funding = _task_facade()._engine_funding(tenant_id, project_slug, allow_pool=allow_pool)
    if funding.get("tenant_id") is None:
        raise RuntimeError("worker_tenant_not_found")
    custom_providers = _task_facade()._engine_custom_providers(tenant_id)
    runtime_tenant = funding.get("tenant_directory_slug") or str(tenant_id)
    with with_tenant_read_context(runtime_tenant, project_slug):
        ensure_global_engine_scope(project_slug)
        _sync_funded_engine_scope(
            project_slug,
            set(funding.get("keys", {})) | set(funding.get("pool_codes", ())),
        )
        _sync_custom_provider_scope(project_slug, custom_providers)
    return funding, custom_providers


def _account_usage(funding, counts, action, job_id):
    """把子进程统计的平台调用写回账本；失败时写入补偿队列。"""
    if not counts:
        return
    for attempt in range(3):
        try:
            record_usage(funding, counts, action, job_id=job_id)
            return
        except Exception:  # noqa: BLE001 - 计量失败不能丢，转 outbox
            if attempt < 2:
                time.sleep(0.2 * (attempt + 1))
    persisted = persist_usage_outbox(
        funding, counts, action, job_id=job_id,
        error="isolated engine job usage accounting failed after retries",
    )
    billable = any(
        int(count) > 0 and code in funding.get("pool_codes", ())
        for code, count in counts.items()
    )
    if billable and not persisted:
        raise RuntimeError("platform_usage_accounting_pending")


def run_engine_job(tenant_id, project_slug, action, job_id=None, allow_pool=True,
                   timeout=None, funding=None, custom_providers=None, wrappers=None, **kwargs):
    """在隔离子进程中执行一次引擎动作，并返回动作结果。"""
    if funding is None:
        funding, custom_providers = resolve_job_funding(
            tenant_id, project_slug, allow_pool=allow_pool,
        )
    payload = {
        "tenant_directory": funding.get("tenant_directory_slug") or str(tenant_id),
        "project_slug": project_slug,
        "action": action,
        "keys": funding.get("keys") or {},
        "pool_codes": sorted(funding.get("pool_codes") or ()),
        "custom_providers": custom_providers or [],
        "kwargs": kwargs,
        "wrappers": list(wrappers or ()),
        "job_id": int(job_id) if job_id is not None else None,
    }
    if config.isolated_jobs_enabled():
        log_path = None
        if job_id is not None:
            log_path = job_log_path(payload["tenant_directory"], project_slug, job_id)
        try:
            with _job_heartbeat(job_id):
                result, usage, _stderr = job_process.run_job_process(
                    payload, timeout=timeout, log_path=log_path,
                )
        except BaseException as exc:
            _account_usage(funding, getattr(exc, "usage", {}), action, job_id)
            raise
    else:
        result, usage = job_runner.execute(payload)
    _account_usage(funding, usage, action, job_id)
    return result


__all__ = ("resolve_job_funding", "run_engine_job")
