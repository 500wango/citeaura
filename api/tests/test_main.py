from fastapi.testclient import TestClient

from api.main import app
from api import config, main
from api.adapters import locking
from api.db import get_db


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


def test_health_is_exempt_and_redis_failure_is_retryable(monkeypatch):
    monkeypatch.setattr(config, "rate_limit_requests", lambda: 1)
    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/api/v1/health").status_code == 200

    def unavailable():
        raise __import__("redis").exceptions.ConnectionError("offline")

    monkeypatch.setattr(locking, "redis_client", unavailable)
    response = client.get("/api/v1/billing/plans")
    assert response.status_code == 503
    assert response.json() == {"error": "rate_limit_unavailable"}
    assert response.headers["retry-after"] == "1"
