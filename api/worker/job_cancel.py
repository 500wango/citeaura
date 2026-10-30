"""运行中 Job 的协作式取消：DB 标记 → 检查点抛错。

取消不在 API 进程里直接杀任务：Celery 配了 ``acks_late`` 与
``task_reject_on_worker_lost``，杀掉执行进程会让消息重新入队；引擎子进程又是
独立进程组（``start_new_session=True``），父进程死了它照样调用付费 API。
因此统一走「标记 → worker 自己停」的路径：

1. API 写 ``Job.cancel_requested_at``；
2. worker 在检查点（进度回调、构建循环、发送前）调用 ``raise_if_canceled()``；
3. 引擎子进程的 watcher 线程用显式 job id 轮询，命中后终止整个进程组。

DB 轮询按 ``POLL_SECONDS`` 节流：检查点在循环里被高频调用，不能每次都查库。
"""

import logging
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar

from api.db import SessionLocal
from api.models import Job


logger = logging.getLogger(__name__)

POLL_SECONDS = 1.0

_JOB_ID = ContextVar("citeaura_job_cancel_id", default=None)
_LOCK = threading.Lock()
_LAST_CHECK = {}
_CANCELED = set()


class JobCanceled(Exception):
    """用户主动取消。必须是普通 Exception 子类：TypeError 会被调用方当成签名不兼容。"""


class EngineJobCanceled(JobCanceled):
    """引擎子进程被终止时抛出，携带已发生的平台用量。"""


def _read_flag(job_id):
    try:
        db = SessionLocal()
        try:
            return db.query(Job.cancel_requested_at).filter(Job.id == job_id).scalar() is not None
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001 - 轮询失败不打断任务，下次再试
        logger.warning("Unable to read cancel flag for job %s: %s", job_id, exc)
        return None


def cancel_requested(job_id=None):
    """是否已请求取消；无 job id（非 Job 上下文）时恒为 False。"""
    job_id = job_id if job_id is not None else _JOB_ID.get()
    if job_id is None:
        return False
    with _LOCK:
        if job_id in _CANCELED:
            return True
        now = time.monotonic()
        if now - _LAST_CHECK.get(job_id, 0.0) < POLL_SECONDS:
            return False
        _LAST_CHECK[job_id] = now
    if not _read_flag(job_id):
        return False
    with _LOCK:
        _CANCELED.add(job_id)
    return True


def raise_if_canceled():
    """检查点；不在 Job 上下文里调用时什么都不做。"""
    if cancel_requested():
        raise JobCanceled("canceled_by_user")


@contextmanager
def bind(job_id):
    """把当前任务绑定到 ContextVar，检查点据此找到要查询的 Job。"""
    if job_id is None:
        yield None
        return
    token = _JOB_ID.set(job_id)
    try:
        yield job_id
    finally:
        _JOB_ID.reset(token)
        with _LOCK:
            _LAST_CHECK.pop(job_id, None)
            _CANCELED.discard(job_id)


__all__ = (
    "EngineJobCanceled", "JobCanceled", "POLL_SECONDS",
    "bind", "cancel_requested", "raise_if_canceled",
)
