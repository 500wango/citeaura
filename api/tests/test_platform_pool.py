import base64
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.billing import platform_pool
from api.db import Base, get_db
from api.main import app
from api.models import ApiKey, Job, Membership, PlatformUsage, Project, Tenant, UsageCounter
from api.settings.crypto import encrypt_key


@pytest.fixture()
def pool_client(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-that-is-long-enough-32")
    monkeypatch.setenv("AES_KEY", base64.urlsafe_b64encode(b"0" * 32).decode())
    monkeypatch.setenv("PLATFORM_POOL_PRICES_CNY_FEN", json.dumps({"openai": 3, "gemini": 2}))
    monkeypatch.setenv("PLATFORM_POOL_OPENAI_API_KEY", "platform-openai-secret")
    monkeypatch.setenv("PLATFORM_POOL_GEMINI_API_KEY", "platform-gemini-secret")
    engine = create_engine(f"sqlite:///{tmp_path / 'pool.sqlite'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client, session_factory
    app.dependency_overrides.clear()


def _register(client, email, tenant_name):
    registered = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "correct-horse-battery", "tenant_name": tenant_name},
    )
    assert registered.status_code == 201
    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "correct-horse-battery"},
    )
    return registered.json(), {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_platform_pool_api_is_explicit_byok_first_and_tenant_isolated(pool_client, monkeypatch):
    client, session_factory = pool_client
    first, first_headers = _register(client, "owner@example.com", "first")
    second, second_headers = _register(client, "other@example.com", "second")
    with session_factory() as db:
        first_tenant = db.get(Tenant, first["tenant"]["id"])
        first_tenant.plan = "pro"
        first_project = Project(
            tenant_id=first_tenant.id,
            slug="first-project",
            url="https://first.example",
            market="both",
        )
        second_project = Project(
            tenant_id=second["tenant"]["id"],
            slug="second-project",
            url="https://second.example",
            market="both",
        )
        db.add_all([first_project, second_project])
        db.add(Membership(
            tenant_id=first_tenant.id,
            user_id=second["user"]["id"],
            role="viewer",
        ))
        db.commit()
        first_project_id = first_project.id
        second_project_id = second_project.id

    byok = client.put(
        "/api/v1/settings/keys",
        headers=first_headers,
        json={"engine_code": "openai", "key_value": "tenant-openai-secret"},
    )
    assert byok.status_code == 200
    initial = client.get(
        f"/api/v1/projects/{first_project_id}/sampling-funding",
        headers=first_headers,
    )
    assert initial.status_code == 200
    assert initial.json()["platform_pool_enabled"] is False
    assert initial.json()["byok_engines"] == ["openai"]
    assert {item["engine_code"] for item in initial.json()["pool_engines"]} == {"gemini", "openai"}

    enabled = client.put(
        f"/api/v1/projects/{first_project_id}/sampling-funding",
        headers=first_headers,
        json={"platform_pool_enabled": True},
    )
    assert enabled.status_code == 200
    sources = {item["engine_code"]: item["source"] for item in enabled.json()["effective_engines"]}
    assert sources["openai"] == "byok"
    assert sources["gemini"] == "platform_pool"
    assert enabled.json()["usage"]["calls"] == 0
    assert "platform-gemini-secret" not in enabled.text
    assert "platform-openai-secret" not in enabled.text
    assert "tenant-openai-secret" not in enabled.text

    pool_status = client.get("/api/v1/billing/platform-pool", headers=first_headers)
    assert pool_status.status_code == 200
    assert pool_status.json()["eligible"] is True
    assert pool_status.json()["engines"][1]["unit_price_cny_fen"] == 3
    assert pool_status.json()["engines"][0]["engine_name"]
    assert pool_status.json()["engines"][0]["sampling_mode"] == "API - Parametric knowledge"
    billing = client.get("/api/v1/billing/usage", headers=first_headers)
    assert billing.json()["platform_pool"]["cost_cny"] == "0.00"

    trial_blocked = client.put(
        f"/api/v1/projects/{second_project_id}/sampling-funding",
        headers=second_headers,
        json={"platform_pool_enabled": True},
    )
    assert trial_blocked.status_code == 403
    assert trial_blocked.json()["error"] == "platform_pool_paid_plan_required"
    assert client.get(
        f"/api/v1/projects/{first_project_id}/sampling-funding",
        headers=second_headers,
    ).status_code == 404

    viewer_login = client.post(
        "/api/v1/auth/login",
        json={
            "email": "other@example.com",
            "password": "correct-horse-battery",
            "tenant_id": first["tenant"]["id"],
        },
    )
    viewer_headers = {"Authorization": f"Bearer {viewer_login.json()['access_token']}"}
    viewer_state = client.get(
        f"/api/v1/projects/{first_project_id}/sampling-funding",
        headers=viewer_headers,
    )
    assert viewer_state.status_code == 200
    assert viewer_state.json()["can_edit"] is False
    assert client.put(
        f"/api/v1/projects/{first_project_id}/sampling-funding",
        headers=viewer_headers,
        json={"platform_pool_enabled": False},
    ).status_code == 403

    monkeypatch.delenv("PLATFORM_POOL_OPENAI_API_KEY")
    monkeypatch.delenv("PLATFORM_POOL_GEMINI_API_KEY")
    assert client.put(
        f"/api/v1/projects/{first_project_id}/sampling-funding",
        headers=first_headers,
        json={"platform_pool_enabled": False},
    ).status_code == 200
    unavailable = client.put(
        f"/api/v1/projects/{first_project_id}/sampling-funding",
        headers=first_headers,
        json={"platform_pool_enabled": True},
    )
    assert unavailable.status_code == 409
    assert unavailable.json()["error"] == "platform_pool_unavailable"


def test_pool_meter_records_only_fallback_calls_once_per_job(tmp_path, monkeypatch):
    monkeypatch.setenv("AES_KEY", base64.urlsafe_b64encode(b"1" * 32).decode())
    monkeypatch.setenv("PLATFORM_POOL_PRICES_CNY_FEN", json.dumps({"gemini": 2, "openai": 3}))
    monkeypatch.setenv("PLATFORM_POOL_GEMINI_API_KEY", "platform-gemini")
    monkeypatch.setenv("PLATFORM_POOL_OPENAI_API_KEY", "platform-openai")
    engine = create_engine(f"sqlite:///{tmp_path / 'meter.sqlite'}")
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(engine)
    with session_factory() as db:
        tenant = Tenant(name="meter", plan="pro")
        db.add(tenant)
        db.flush()
        project = Project(
            tenant_id=tenant.id,
            slug="meter-project",
            url="https://meter.example",
            market="both",
            platform_pool_enabled=True,
        )
        db.add(project)
        db.flush()
        job = Job(project_id=project.id, action="sample", status="running")
        db.add(job)
        db.add(ApiKey(
            tenant_id=tenant.id,
            engine_code="openai",
            encrypted_value=encrypt_key("tenant-openai"),
        ))
        db.commit()
        tenant_id, project_id, job_id = tenant.id, project.id, job.id

    monkeypatch.setattr(platform_pool, "SessionLocal", session_factory)
    with session_factory() as db:
        funding = platform_pool.resolve_funding(db, tenant_id, "meter-project")
    assert funding["keys"]["openai"] == "tenant-openai"
    assert funding["keys"]["gemini"] == "platform-gemini"
    assert funding["pool_codes"] == frozenset(("gemini",))

    import sample

    calls = []
    monkeypatch.setattr(sample, "ask", lambda engine_code, prompt: calls.append(engine_code) or {"ok": True})
    with platform_pool.meter_platform_calls(funding["pool_codes"]) as counts:
        sample.ask("gemini", "one")
        sample.ask("openai", "two")
        sample.ask("gemini", "three")
    assert calls == ["gemini", "openai", "gemini"]
    assert counts == {"gemini": 2}

    assert len(platform_pool.record_usage(funding, counts, "sample", job_id=job_id)) == 1
    assert platform_pool.record_usage(funding, counts, "sample", job_id=job_id) == []
    with session_factory() as db:
        usage = db.query(PlatformUsage).one()
        assert usage.tenant_id == tenant_id
        assert usage.project_id == project_id
        assert usage.engine_code == "gemini"
        assert usage.calls == 2
        assert usage.unit_price_cny_fen == 2
        assert usage.amount_cny_fen == 4
        counter = db.query(UsageCounter).one()
        assert counter.platform_calls == 2
        assert counter.platform_cost_cny_fen == 4
        summary = platform_pool.usage_summary(db, db.get(Tenant, tenant_id))
        assert summary["calls"] == 2
        assert summary["cost_cny"] == "0.04"
        assert summary["by_engine"] == [{"engine_code": "gemini", "calls": 2, "cost_cny_fen": 4}]

        month = platform_pool._month_start()
        next_year = month.year + (1 if month.month == 12 else 0)
        next_month = 1 if month.month == 12 else month.month + 1
        db.add(PlatformUsage(
            tenant_id=tenant_id,
            project_id=project_id,
            action="sample",
            engine_code="deepseek",
            calls=4,
            unit_price_cny_fen=1,
            amount_cny_fen=4,
            created_at=datetime(next_year, next_month, 1, tzinfo=timezone.utc),
        ))
        db.commit()
        summary = platform_pool.usage_summary(db, db.get(Tenant, tenant_id))
        assert summary["by_engine"] == [{"engine_code": "gemini", "calls": 2, "cost_cny_fen": 4}]


def test_pool_meter_propagates_isolated_context_to_sampling_threads(monkeypatch):
    import sample

    monkeypatch.setattr(sample, "ask", lambda engine_code, prompt: {"ok": True})

    def measure(engine_code):
        with platform_pool.meter_platform_calls((engine_code,)) as counts:
            with sample.ThreadPoolExecutor(max_workers=4) as executor:
                futures = [executor.submit(sample.ask, engine_code, str(index)) for index in range(100)]
                for future in futures:
                    assert future.result() == {"ok": True}
        return counts

    with ThreadPoolExecutor(max_workers=2) as executor:
        openai = executor.submit(measure, "openai")
        gemini = executor.submit(measure, "gemini")

    assert openai.result() == {"openai": 100}
    assert gemini.result() == {"gemini": 100}
