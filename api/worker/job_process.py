"""一次性引擎子进程：环境清洗、超时与进程组回收。"""

import os
import re
import signal
import subprocess
import sys
import threading
from pathlib import Path

from celery import current_task

from api import config
from api.adapters import locking
from api.worker import job_protocol

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SECRET_NAME = re.compile(
    r"(API_KEY|_KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|PRIVATE)$|^(DATABASE_URL|REDIS_URL|STRIPE_|AUTH_SMTP_|OBJECT_STORAGE_|PLATFORM_POOL_|CITEAURA_)",
    re.IGNORECASE,
)
_ALLOWED_CITEAURA = {"CITEAURA_WORK_ROOT", "CITEAURA_SKIP_DOTENV"}
_KEEP_NAMES = {"PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "TZ", "PYTHONPATH", "PYTHONUNBUFFERED", "PYTHONDONTWRITEBYTECODE", "VIRTUAL_ENV"}


class EngineJobError(RuntimeError):
    """引擎子进程失败或超时。"""


class EngineJobTimeout(EngineJobError):
    pass


def sanitize_child_environment(environ=None):
    """子进程不继承任何密钥、数据库凭据或平台池配置。"""
    source = os.environ if environ is None else environ
    clean = {}
    for name, value in source.items():
        if name in _KEEP_NAMES:
            clean[name] = value
            continue
        if name in _ALLOWED_CITEAURA:
            clean[name] = value
            continue
        if _SECRET_NAME.search(name):
            continue
        clean[name] = value
    clean["PYTHONPATH"] = str(PROJECT_ROOT) + (
        os.pathsep + clean["PYTHONPATH"] if clean.get("PYTHONPATH") else ""
    )
    clean.setdefault("PYTHONUNBUFFERED", "1")
    clean["CITEAURA_SKIP_DOTENV"] = "1"
    clean["CITEAURA_SKIP_PROJECT_LOCK"] = "1"
    return clean


def terminate_process_group(process, grace_seconds=10):
    """先 SIGTERM 整个进程组，超时再 SIGKILL，避免孤儿引擎进程。"""
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=grace_seconds)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        pass


def _file_tail(path, lines=8):
    """从日志文件尾部取最后几行，用于子进程失败时的诊断。"""
    if path is None:
        return []
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - 4000))
            text = handle.read().decode("utf-8", "replace")
    except OSError:
        return []
    return text.strip().splitlines()[-lines:]


def _task_soft_time_limit():
    """返回当前 Celery 任务的软超时；非任务上下文返回 None。"""
    request = getattr(current_task, "request", None)
    if request is None or getattr(request, "called_directly", True):
        return None
    value = getattr(current_task, "soft_time_limit", None) or getattr(
        request, "soft_time_limit", None,
    )
    if not value:
        # 短任务没有 per-task 配置，交给全局软超时兜底。
        from celery import current_app
        value = current_app.conf.task_soft_time_limit
    try:
        return float(value) if value else None
    except (TypeError, ValueError):
        return None


def run_job_process(payload, timeout=None, environ=None, log_path=None, command=None):
    """在子进程中执行一次引擎动作；返回 (result, usage, stderr)。

    log_path 不为空时，子进程 stderr 直接追写该 Job 日志：引擎的逐步输出
    必须在任务运行期间就能被前端轮询到，而不是结束后才一次性拿到。
    """
    timeout = int(timeout or config.engine_job_timeout_seconds(_task_soft_time_limit()))
    command = command or [sys.executable, "-m", "api.worker.job_runner"]
    log_handle = None
    if log_path is not None:
        try:
            Path(log_path).parent.mkdir(parents=True, exist_ok=True)
            log_handle = open(log_path, "a", encoding="utf-8", buffering=1)
        except OSError:
            log_handle = None
    try:
        process = subprocess.Popen(
            command,
            cwd=str(PROJECT_ROOT),
            env=sanitize_child_environment(environ),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=log_handle if log_handle is not None else subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        loss = locking.current_lock_loss()
        stopped = threading.Event()
        def stop_on_lock_loss():
            while not stopped.wait(0.1):
                if loss is not None and loss.is_set():
                    terminate_process_group(process, grace_seconds=0.1)
                    return
        watcher = threading.Thread(target=stop_on_lock_loss, daemon=True)
        watcher.start()
        try:
            stdout, stderr = process.communicate(
                job_protocol.encode_job_request(payload),
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            terminate_process_group(process)
            stdout, stderr = process.communicate()
            exc = EngineJobTimeout(f"engine job timed out after {timeout}s")
            exc.usage = job_protocol.parse_events(stdout)[1]
            raise exc
        except BaseException as exc:
            # 父进程被 Celery 软超时等中断时，子进程在独立会话里不会自动退出：
            # 不回收进程组就会在 Job 已失败后继续调用付费 API 并写入产物。
            terminate_process_group(process)
            stdout, _ = process.communicate()
            exc.usage = job_protocol.parse_events(stdout)[1]
            raise
        finally:
            stopped.set()
            watcher.join(timeout=1)
    finally:
        if log_handle is not None:
            log_handle.close()
    if log_handle is not None:
        stderr = "\n".join(_file_tail(log_path))
    result, usage, errors, _progress = job_protocol.parse_events(stdout)
    if loss is not None and loss.is_set():
        exc = EngineJobError("project_lock_lost")
        exc.usage = usage
        raise exc
    if errors:
        exc = EngineJobError("; ".join(errors)[:2000])
        exc.usage = usage
        raise exc
    if process.returncode != 0:
        tail = (stderr or "").strip().splitlines()[-8:]
        exc = EngineJobError(
            f"engine job exited with {process.returncode}: " + " | ".join(tail)[:1500]
        )
        exc.usage = usage
        raise exc
    if result is None:
        tail = (stderr or "").strip().splitlines()[-8:]
        exc = EngineJobError("engine job returned no result: " + " | ".join(tail)[:1500])
        exc.usage = usage
        raise exc
    return result, usage, stderr
