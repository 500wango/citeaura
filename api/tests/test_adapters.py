import os
import threading

import pytest

from api.adapters import engine as engine_adapter
from api.adapters.engine import geolib, job_log_path, with_tenant_context
from api.adapters.exceptions import GeoEngineError


def test_tenant_context_patches_paths_and_die_then_restores():
    original_root = geolib.ROOT
    original_work = geolib.WORK
    original_die = geolib.die
    original_project_lock = geolib.project_lock

    with with_tenant_context("test-tenant", "example"):
        assert "test-tenant" in str(geolib.WORK)
        assert geolib.ROOT.name == "disvorai"
        with pytest.raises(GeoEngineError, match="test error"):
            geolib.die("test error")
        assert geolib.project_lock is not original_project_lock

    assert geolib.ROOT == original_root
    assert geolib.WORK == original_work
    assert geolib.die is original_die
    assert geolib.project_lock is original_project_lock


def test_key_injection_supports_engine_codes_and_restores_environment(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "old")
    monkeypatch.setenv("GEMINI_API_KEY", "global-fallback")
    os.environ.pop("DEEPSEEK_API_KEY", None)

    with with_tenant_context("tenant", "project", {"deepseek": "new", "OPENAI_API_KEY": "updated"}):
        assert os.environ["DEEPSEEK_API_KEY"] == "new"
        assert os.environ["OPENAI_API_KEY"] == "updated"
        assert "GEMINI_API_KEY" not in os.environ

    assert "DEEPSEEK_API_KEY" not in os.environ
    assert os.environ["OPENAI_API_KEY"] == "old"
    assert os.environ["GEMINI_API_KEY"] == "global-fallback"


def test_context_rejects_path_traversal():
    with pytest.raises(ValueError):
        with with_tenant_context("../other-tenant", "project"):
            pass


def test_job_log_path_is_tenant_scoped(tmp_path, monkeypatch):
    monkeypatch.setattr(engine_adapter, "WORK_ROOT", tmp_path / "work")

    path = job_log_path("Tenant Name", "example-com", 7)

    assert path == tmp_path / "work" / "tenant-name" / "example-com" / ".jobs" / "7.log"
    with pytest.raises(ValueError, match="invalid project slug"):
        job_log_path("tenant", "../example", 7)
    with pytest.raises(ValueError, match="invalid job id"):
        job_log_path("tenant", "example", 0)


def test_tenant_context_serializes_process_global_state(tmp_path, monkeypatch):
    monkeypatch.setattr(engine_adapter, "WORK_ROOT", tmp_path / "work")
    first_entered = threading.Event()
    release_first = threading.Event()
    second_attempted = threading.Event()
    second_entered = threading.Event()
    observed = []

    def first_call():
        with with_tenant_context("tenant-a", "project-a"):
            observed.append(("first-start", geolib.WORK))
            first_entered.set()
            release_first.wait(2)
            observed.append(("first-end", geolib.WORK))

    def second_call():
        first_entered.wait(2)
        second_attempted.set()
        with with_tenant_context("tenant-b", "project-b"):
            observed.append(("second", geolib.WORK))
            second_entered.set()

    first_thread = threading.Thread(target=first_call)
    second_thread = threading.Thread(target=second_call)
    first_thread.start()
    second_thread.start()
    assert first_entered.wait(2)
    assert second_attempted.wait(2)
    assert not second_entered.wait(0.05)
    release_first.set()
    first_thread.join(2)
    second_thread.join(2)

    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
    assert [label for label, _ in observed] == ["first-start", "first-end", "second"]
    assert all("tenant-a" in str(path) for _, path in observed[:2])
    assert "tenant-b" in str(observed[2][1])
