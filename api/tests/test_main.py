from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from api.main import app
from api import config, main
from api.adapters import locking
from api.db import get_db
from api.rate_limit import AUTH_PATHS


client = TestClient(app)


def test_health_check():
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


def test_readiness_endpoint_uses_service_unavailable_until_ready(monkeypatch):
    app.dependency_overrides[get_db] = lambda: iter((object(),))
    monkeypatch.setattr(main, "readiness_checks", lambda db: {
        "status": "not_ready",
        "checks": {"database": True, "stripe": False},
    })
    try:
        response = client.get("/api/v1/health/ready")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {"database": True, "stripe": False},
    }


def test_api_rate_limit_returns_standard_headers_and_429(monkeypatch):
    monkeypatch.setattr(config, "rate_limit_requests", lambda: 2)

    first = client.get("/api/v1/billing/plans")
    second = client.get("/api/v1/billing/plans")
    blocked = client.get("/api/v1/billing/plans")

    assert first.status_code == 200
    assert first.headers["x-ratelimit-limit"] == "2"
    assert first.headers["x-ratelimit-remaining"] == "1"
    assert second.headers["x-ratelimit-remaining"] == "0"
    assert blocked.status_code == 429
    assert blocked.json() == {"error": "rate_limit_exceeded", "detail": "request limit exceeded"}
    assert int(blocked.headers["retry-after"]) >= 1


def test_sensitive_session_endpoints_use_auth_rate_limit():
    assert {
        "/api/v1/admin/auth/password",
        "/api/v1/team/invitations/accept",
    } <= AUTH_PATHS


def test_integrity_errors_map_to_stable_conflicts():
    """并发建 Job / 建项目撞唯一索引必须稳定返回 409，其它完整性错误仍是 500。"""
    import asyncio
    import json

    def response_for(detail):
        exc = IntegrityError("INSERT INTO jobs ...", {}, Exception(detail))
        response = asyncio.run(main.integrity_error_handler(None, exc))
        return response.status_code, json.loads(response.body)

    assert response_for("uq_jobs_project_active") == (
        409, {"error": "project_job_already_running"},
    )
    assert response_for("uq_projects_tenant_slug") == (
        409, {"error": "project_already_exists"},
    )
    # 其他唯一约束不是用户可见的冲突，不能被伪装成 409。
    assert response_for("uq_api_keys_tenant_engine") == (
        500, {"error": "database_integrity_error"},
    )


def test_health_is_exempt_and_redis_failure_only_closes_auth_endpoints(monkeypatch):
    monkeypatch.setattr(config, "rate_limit_requests", lambda: 1)
    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/api/v1/health").status_code == 200

    def unavailable():
        raise __import__("redis").exceptions.ConnectionError("offline")

    monkeypatch.setattr(locking, "redis_client", unavailable)
    assert client.get("/api/v1/billing/plans").status_code == 200
    response = client.post("/api/v1/auth/login", json={
        "email": "nobody@example.com",
        "password": "not-a-real-password",
    })
    assert response.status_code == 503
    assert response.json() == {"error": "rate_limit_unavailable"}
    assert response.headers["retry-after"] == "1"
