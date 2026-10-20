"""一次性引擎子进程：环境清洗、超时与进程组回收。"""

import os
import re
import signal
import subprocess
import sys
from pathlib import Path

from api import config
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


def run_job_process(payload, timeout=None, environ=None):
    """在子进程中执行一次引擎动作；返回 (result, usage, stderr)。"""
    timeout = int(timeout or config.engine_job_timeout_seconds())
    command = [sys.executable, "-m", "api.worker.job_runner"]
    process = subprocess.Popen(
        command,
        cwd=str(PROJECT_ROOT),
        env=sanitize_child_environment(environ),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(
            job_protocol.encode_job_request(payload),
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        terminate_process_group(process)
        stdout, stderr = process.communicate()
        raise EngineJobTimeout(f"engine job timed out after {timeout}s")
    result, usage, errors, _progress = job_protocol.parse_events(stdout)
    if errors:
        raise EngineJobError("; ".join(errors)[:2000])
    if process.returncode != 0:
        tail = (stderr or "").strip().splitlines()[-8:]
        raise EngineJobError(
            f"engine job exited with {process.returncode}: " + " | ".join(tail)[:1500]
        )
    if result is None:
        tail = (stderr or "").strip().splitlines()[-8:]
        raise EngineJobError("engine job returned no result: " + " | ".join(tail)[:1500])
    return result, usage, stderr
