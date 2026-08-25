import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.db import Base, get_db
from api.main import app
from api.models import ProductEvent, PublicAudit
from api.projects import public


@pytest.fixture()
def growth_client(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'growth.sqlite'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def override_get_db():
        db = sessions()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr(public.preflight, "run", lambda url, timeout=6.0: {
        "url": url,
        "ready": True,
        "checks": [{"name": "dns", "ok": True}, {"name": "homepage", "ok": True}],
    })
    monkeypatch.setattr(
        public.geolib,
        "fetch_text",
        lambda url, timeout=5, allow_machine_file=False: "User-agent: *\nAllow: /\nSitemap: https://example.com/sitemap.xml",
    )
    public._AUDIT_CACHE.clear()
    public._AUDIT_REQUESTS.clear()
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client, sessions
    app.dependency_overrides.clear()


def test_public_sample_report_is_available_without_auth(growth_client):
    client, _ = growth_client
    response = client.get("/sample-report")
    assert response.status_code == 200
    assert "Example diagnostic pack" in response.text
    assert "Create free workspace" in response.text


def test_public_audit_returns_cached_technical_summary_and_event(growth_client):
    client, sessions = growth_client
    first = client.post("/api/v1/public/audit", json={"url": "https://example.com"})
    assert first.status_code == 200
    payload = first.json()
    assert payload["kind"] == "public_diagnostic_summary"
    assert payload["sampling_mode"] == "No AI sampling · public technical preflight"
    assert payload["cached"] is False
    assert payload["signals"]["sitemap"] is True

    second = client.post("/api/v1/public/audit", json={"url": "https://example.com"})
    assert second.status_code == 200
    assert second.json()["cached"] is True
    with sessions() as db:
        assert db.query(ProductEvent).filter(ProductEvent.name == "public_audit_completed").count() == 2


def test_public_audit_rate_limit_is_per_anonymous_source(growth_client):
    client, _ = growth_client
    for _ in range(public._AUDIT_MAX_PER_WINDOW):
        assert client.post("/api/v1/public/audit", json={"url": f"https://example-{_}.com"}).status_code == 200
    blocked = client.post("/api/v1/public/audit", json={"url": "https://example-blocked.com"})
    assert blocked.status_code == 429
    assert blocked.json()["error"] == "public_audit_rate_limited"


def test_public_audit_returns_handoff_id_and_persists_result(growth_client):
    client, sessions = growth_client
    response = client.post("/api/v1/public/audit", json={"url": "https://handoff.example"})
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["audit_id"]) == 32
    with sessions() as db:
        row = db.query(PublicAudit).filter(PublicAudit.audit_id == payload["audit_id"]).one()
        assert "public_diagnostic_summary" in row.result_json


def test_public_audit_handoff_is_accepted_during_registration(growth_client):
    client, sessions = growth_client
    audit = client.post("/api/v1/public/audit", json={"url": "https://register-handoff.example"}).json()
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "handoff-owner@example.com",
            "password": "correct-horse-battery",
            "audit_id": audit["audit_id"],
            "acquisition_source": "landing",
            "acquisition_medium": "organic",
            "acquisition_campaign": "seo-guide",
        },
    )
    assert response.status_code == 201
    assert response.json()["audit"]["audit_id"] == audit["audit_id"]
    with sessions() as db:
        event = db.query(ProductEvent).filter(ProductEvent.name == "signup_attribution").one()
        properties = json.loads(event.properties)
        assert properties == {
            "audit_id": audit["audit_id"],
            "campaign": "seo-guide",
            "medium": "organic",
            "source": "landing",
        }
