"""引擎子进程隔离：环境清洗、密钥传输与超时回收。"""

import os
import time
from concurrent.futures import ThreadPoolExecutor

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


def test_parent_environment_is_unchanged(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "parent-secret")
    before = dict(os.environ)
    job_process.run_job_process(_payload("tenant-env", {"gemini": "child-key"}), timeout=30)
    assert dict(os.environ) == before
