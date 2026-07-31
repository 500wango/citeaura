from fastapi.testclient import TestClient

from api.main import app
from api import main
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
