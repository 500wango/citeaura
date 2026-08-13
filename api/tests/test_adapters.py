import os
import threading

import pytest
import requests

from api.adapters import engine as engine_adapter
from api.adapters import network
from api.adapters.engine import geolib, job_log_path, with_tenant_context
from api.adapters.exceptions import GeoEngineError


def test_tenant_context_patches_paths_and_die_then_restores():
    original_root = geolib.ROOT
    original_work = geolib.WORK
    original_die = geolib.die
    original_project_lock = geolib.project_lock

    with with_tenant_context("test-tenant", "example"):
        assert "test-tenant" in str(geolib.WORK)
        assert geolib.ROOT.name in ("disvorai", "citeaura")
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


def test_custom_provider_is_registered_only_inside_tenant_context():
    import sample

    provider = {
        "code": "custom_abc123",
        "name": "Budget Gateway",
        "base_url": "https://gateway.example.com/v1",
        "model_id": "vendor/budget-model",
        "market": "global",
        "api_key": "sk-custom",
    }
    original_preferences = sample.LLM_PREFS
    assert provider["code"] not in sample.PROVIDERS

    with with_tenant_context(
        "tenant", "project", {provider["code"]: provider["api_key"]}, custom_providers=[provider],
    ):
        registered = sample.PROVIDERS[provider["code"]]
        assert registered["base"] == provider["base_url"]
        assert registered["model"] == provider["model_id"]
        assert sample.model_for(provider["code"]) == provider["model_id"]
        assert sample.available(provider["code"]) is True
        assert sample.LLM_PREFS[-1] == provider["code"]

    assert provider["code"] not in sample.PROVIDERS
    assert sample.LLM_PREFS == original_preferences


def test_custom_provider_uses_exact_endpoint_key_and_model(monkeypatch):
    import sample

    provider = {
        "code": "custom_abc123",
        "name": "Budget Gateway",
        "base_url": "https://gateway.example.com/v1",
        "model_id": "vendor/budget-model:exact",
        "market": "global",
        "api_key": "sk-custom",
    }
    calls = []

    class Response:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {
                "model": provider["model_id"],
                "choices": [{"message": {"content": "OK"}}],
            }

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    monkeypatch.setattr(sample.requests, "post", fake_post)
    with with_tenant_context(
        "tenant", "project", {provider["code"]: provider["api_key"]}, custom_providers=[provider],
    ):
        result = sample.ask(provider["code"], "connection check", timeout=20)

    assert result["ok"] is True
    assert calls == [
        (
            "https://gateway.example.com/v1/chat/completions",
            {
                "headers": {
                    "Authorization": "Bearer sk-custom",
                    "Content-Type": "application/json",
                },
                "json": {
                    "model": "vendor/budget-model:exact",
                    "messages": [{"role": "user", "content": "connection check"}],
                    "temperature": 0.7,
                },
                "timeout": 20,
            },
        ),
    ]


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


def test_tenant_context_guards_all_http_methods_and_disables_redirects(monkeypatch):
    calls = []

    def resolve_public(host, port, type=None):
        return [(2, 1, 6, "", ("93.184.216.34", port))]

    def fake_request(session, method, url, **kwargs):
        calls.append((method, url, kwargs))
        return object()

    monkeypatch.setattr(network.socket, "getaddrinfo", resolve_public)
    monkeypatch.setattr(requests.sessions.Session, "request", fake_request)
    with with_tenant_context("tenant", "project"):
        requests.post("https://example.com/hook", allow_redirects=True)

    assert calls == [("post", "https://example.com/hook", {"data": None, "json": None, "allow_redirects": False})]


def test_tenant_context_blocks_private_and_mixed_dns_results(monkeypatch):
    def resolve_mixed(host, port, type=None):
        return [
            (2, 1, 6, "", ("93.184.216.34", port)),
            (2, 1, 6, "", ("169.254.169.254", port)),
        ]

    monkeypatch.setattr(network.socket, "getaddrinfo", resolve_mixed)
    with with_tenant_context("tenant", "project"):
        with pytest.raises(GeoEngineError, match="network_private_address_blocked"):
            requests.put("https://example.com/resource")

    monkeypatch.setattr(
        network.socket,
        "getaddrinfo",
        lambda host, port, type=None: [(2, 1, 6, "", ("224.0.0.1", port))],
    )
    with with_tenant_context("tenant", "project"):
        with pytest.raises(GeoEngineError, match="network_private_address_blocked"):
            requests.get("https://example.com/resource")
