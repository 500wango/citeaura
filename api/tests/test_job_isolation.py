"""引擎子进程隔离：环境清洗、密钥传输与超时回收。"""

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from api.worker import job_process


def _payload(tenant, keys, **kwargs):
    return {
        "tenant_directory": tenant,
        "project_slug": "isolation",
        "action": "probe",
        "keys": keys,
        "pool_codes": [],
        "custom_providers": [],
        "kwargs": kwargs,
    }


def test_child_environment_drops_secrets(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "parent-secret")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@db/app")
    monkeypatch.setenv("CITEAURA_ISOLATED_JOBS", "on")
    monkeypatch.setenv("CITEAURA_WORK_ROOT", "/tmp/work")
    monkeypatch.setenv("PLATFORM_POOL_OPENAI", "pool-secret")
    clean = job_process.sanitize_child_environment()
    for name in ("OPENAI_API_KEY", "DATABASE_URL", "CITEAURA_ISOLATED_JOBS", "PLATFORM_POOL_OPENAI"):
        assert name not in clean
    assert clean["CITEAURA_WORK_ROOT"] == "/tmp/work"
    assert clean["CITEAURA_SKIP_PROJECT_LOCK"] == "1"
    assert "PATH" in clean


def test_parent_secrets_do_not_reach_child(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "parent-secret")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@db/app")
    result, _usage, _stderr = job_process.run_job_process(
        _payload("tenant-a", {"openai": "child-openai-key"}),
        timeout=30,
    )
    present = result["env_present"]
    assert present["OPENAI_API_KEY"] is True
    assert present["GEMINI_API_KEY"] is False
    assert present["DATABASE_URL"] is False
    assert present["CITEAURA_ISOLATED_JOBS"] is False
    assert result["project_lock"] == "ok"
    assert result["tenant"] == "tenant-a"


def test_child_runs_without_database_url_in_production(monkeypatch):
    """生产模式明确禁止默认 DATABASE_URL；子进程不触库，必须仍能导入。"""
    monkeypatch.setenv("PRODUCTION_PROXY_MODE", "true")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    result, _usage, _stderr = job_process.run_job_process(
        _payload("tenant-prod", {}),
        timeout=30,
    )
    assert result["env_present"]["DATABASE_URL"] is False
    assert result["tenant"] == "tenant-prod"


def test_concurrent_tenants_do_not_share_keys(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "parent-secret")
    monkeypatch.setenv("GEMINI_API_KEY", "parent-secret-2")
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            job_process.run_job_process,
            _payload("tenant-a", {"openai": "a-key"}), 60,
        )
        second = pool.submit(
            job_process.run_job_process,
            _payload("tenant-b", {"gemini": "b-key"}), 60,
        )
        result_a = first.result()[0]
        result_b = second.result()[0]
    assert result_a["tenant"] == "tenant-a"
    assert result_a["env_present"]["OPENAI_API_KEY"] is True
    assert result_a["env_present"]["GEMINI_API_KEY"] is False
    assert result_b["tenant"] == "tenant-b"
    assert result_b["env_present"]["GEMINI_API_KEY"] is True
    assert result_b["env_present"]["OPENAI_API_KEY"] is False


def test_timeout_kills_process_group():
    started = time.monotonic()
    with pytest.raises(job_process.EngineJobTimeout):
        job_process.run_job_process(
            _payload("tenant-timeout", {}, sleep=30),
            timeout=1,
        )
    assert time.monotonic() - started < 20


def test_pipeline_dispatch_injects_project_slug(monkeypatch):
    """子进程 pipeline 分支必须注入 slug，否则 geo.cmd_* 读 a.slug 直接抛 AttributeError。"""
    from api.worker import job_runner

    seen = {}

    def fake_cmd_sample(args):
        seen["slug"] = args.slug
        seen["limit"] = args.limit

    monkeypatch.setitem(sys.modules, "geo", SimpleNamespace(cmd_sample=fake_cmd_sample))

    result = job_runner._dispatch(
        "pipeline", "acme", {"pipeline_action": "sample", "params": {"--limit": 5}},
    )

    assert seen == {"slug": "acme", "limit": 5}
    assert result["project_slug"] == "acme"


_STREAMING_CHILD = (
    "import json, sys, time\n"
    "sys.stderr.write('[geo] 1/8 Crawl Website\\n')\n"
    "sys.stderr.flush()\n"
    "time.sleep(1.5)\n"
    "sys.stdout.write(json.dumps({'type': 'result', 'result': {'status': 'done'}, 'usage': {}}) + '\\n')\n"
    "sys.stdout.flush()\n"
)


def test_job_log_receives_child_output_while_running(tmp_path):
    """子进程 stderr 必须在运行期间落盘。

    父进程的 capture_task_output 只重定向自己的 stdout/stderr；隔离子进程
    若把 stderr 写进 PIPE，任务跑多久前端就多久看不到任何进度。
    """
    log_path = tmp_path / "jobs" / "7.log"
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            job_process.run_job_process,
            _payload("tenant-stream", {}),
            60,
            None,
            log_path,
            [sys.executable, "-u", "-c", _STREAMING_CHILD],
        )
        deadline = time.monotonic() + 15
        streamed = ""
        while time.monotonic() < deadline:
            if log_path.exists():
                streamed = log_path.read_text(encoding="utf-8")
                if "1/8 Crawl Website" in streamed:
                    break
            if future.done():
                break
            time.sleep(0.05)
        result, _usage, stderr = future.result()
    assert "1/8 Crawl Website" in streamed
    assert result == {"status": "done"}
    assert "1/8 Crawl Website" in stderr


def test_isolation_passes_job_log_path(monkeypatch):
    """隔离分支必须把 Job 日志路径交给子进程，否则流式输出没有去处。"""
    from api.worker import worker_isolation

    seen = {}

    def fake_run(payload, timeout=None, **kwargs):
        seen["log_path"] = kwargs.get("log_path")
        return {"status": "done"}, {}, ""

    monkeypatch.setattr(worker_isolation.config, "isolated_jobs_enabled", lambda: True)
    monkeypatch.setattr(worker_isolation.job_process, "run_job_process", fake_run)

    worker_isolation.run_engine_job(
        "uszx",
        "lancco-com",
        "autopilot",
        job_id=7,
        funding={
            "tenant_id": 2,
            "tenant_directory_slug": "uszx",
            "keys": {},
            "pool_codes": [],
        },
    )

    log_path = seen["log_path"]
    assert log_path is not None
    assert log_path.name == "7.log"
    assert log_path.parent.name == ".jobs"
    assert "lancco-com" in log_path.parts


def test_isolation_refreshes_heartbeat_while_child_runs(monkeypatch):
    """子进程长跑期间父进程必须刷新心跳。

    否则回收器只看到 claim 时的心跳，采到一半就会被当成
    worker_lost_or_timeout 写死。
    """
    from api.worker import worker_isolation

    beats = []
    fake_tasks = SimpleNamespace(
        logger=SimpleNamespace(warning=lambda *args, **kwargs: None),
        _job_transaction=lambda operation, retries=2: beats.append(1),
    )

    def fake_run(payload, timeout=None, **kwargs):
        time.sleep(0.4)
        return {"status": "done"}, {}, ""

    monkeypatch.setattr(worker_isolation, "_task_facade", lambda: fake_tasks)
    monkeypatch.setattr(worker_isolation, "HEARTBEAT_INTERVAL_SECONDS", 0.05)
    monkeypatch.setattr(worker_isolation.config, "isolated_jobs_enabled", lambda: True)
    monkeypatch.setattr(worker_isolation.job_process, "run_job_process", fake_run)

    worker_isolation.run_engine_job(
        "uszx",
        "lancco-com",
        "autopilot",
        job_id=7,
        funding={
            "tenant_id": 2,
            "tenant_directory_slug": "uszx",
            "keys": {},
            "pool_codes": [],
        },
    )

    assert len(beats) >= 2
    settled = len(beats)
    time.sleep(0.2)
    assert len(beats) == settled


def test_parent_environment_is_unchanged(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "parent-secret")
    before = dict(os.environ)
    job_process.run_job_process(_payload("tenant-env", {"gemini": "child-key"}), timeout=30)
    assert dict(os.environ) == before


def test_engine_timeout_stays_below_task_soft_limit(monkeypatch):
    """子进程超时必须早于 Celery 软超时，父进程才有机会回收进程组。"""
    monkeypatch.delenv("CITEAURA_ENGINE_JOB_TIMEOUT", raising=False)
    assert job_process.config.engine_job_timeout_seconds(3540) == 3480
    monkeypatch.setenv("CITEAURA_ENGINE_JOB_TIMEOUT", "7140")
    assert job_process.config.engine_job_timeout_seconds(7200) == 7140
    assert job_process.config.engine_job_timeout_seconds(3540) == 3480


def test_soft_time_limit_terminates_child_group(monkeypatch):
    """父进程被软超时打断时必须终止子进程组。

    否则引擎子进程会在 Job 已失败后继续调用付费 API 并写入产物。
    """
    from celery.exceptions import SoftTimeLimitExceeded

    terminated = []

    class Child:
        pid = 4242
        returncode = None

        def communicate(self, *args, **kwargs):
            raise SoftTimeLimitExceeded()

    monkeypatch.setattr(job_process.subprocess, "Popen", lambda *args, **kwargs: Child())
    monkeypatch.setattr(
        job_process,
        "terminate_process_group",
        lambda process, **kwargs: terminated.append(process),
    )

    with pytest.raises(SoftTimeLimitExceeded):
        job_process.run_job_process(_payload("tenant-soft", {}), timeout=30)

    assert [process.pid for process in terminated] == [4242]


def test_timed_out_child_retains_observed_usage():
    command = [sys.executable, "-u", "-c", (
        "import json,time; "
        "print(json.dumps({'type':'usage','usage':{'openai':2}}), flush=True); "
        "time.sleep(30)"
    )]
    with pytest.raises(job_process.EngineJobTimeout) as caught:
        job_process.run_job_process(_payload('tenant-a', {}), timeout=1, command=command)
    assert caught.value.usage == {"openai": 2}


def test_lock_loss_stops_running_isolated_child(monkeypatch):
    import threading
    from api.adapters import locking

    loss = threading.Event()
    monkeypatch.setattr(locking, "current_lock_loss", lambda: loss)
    timer = threading.Timer(0.3, loss.set)
    timer.start()
    started = time.monotonic()
    try:
        with pytest.raises(job_process.EngineJobError, match="project_lock_lost"):
            job_process.run_job_process(
                _payload('tenant-a', {}), timeout=20,
                command=[sys.executable, '-u', '-c', 'import time; time.sleep(20)'],
            )
    finally:
        timer.cancel()
    assert time.monotonic() - started < 5


def test_failed_isolated_job_accounts_observed_usage(monkeypatch):
    from api.worker import worker_isolation

    monkeypatch.setenv('CITEAURA_ISOLATED_JOBS', 'true')
    failure = job_process.EngineJobTimeout('timed out')
    failure.usage = {'openai': 2}
    monkeypatch.setattr(job_process, 'run_job_process', lambda *a, **kw: (_ for _ in ()).throw(failure))
    calls = []
    monkeypatch.setattr(worker_isolation, '_account_usage', lambda *a, **kw: calls.append((a, kw)))
    funding = {'tenant_id': 1, 'tenant_directory_slug': 'tenant-a', 'pool_codes': {'openai'}}
    with pytest.raises(job_process.EngineJobTimeout):
        worker_isolation.run_engine_job('tenant-a', 'isolation', 'sample', funding=funding)
    assert calls[0][0][1] == {'openai': 2}
