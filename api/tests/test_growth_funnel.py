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


def test_public_crawler_check_returns_bot_statuses(growth_client):
    client, _ = growth_client
    response = client.post("/api/v1/public/crawler-check", json={"url": "https://crawler.example"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == "public_crawler_check"
    assert payload["sampling_mode"] == "No AI sampling · robots.txt inspection"
    assert payload["robots_present"] is True
    assert {item["name"] for item in payload["bots"]} >= {"GPTBot", "PerplexityBot"}


def test_public_free_tools_return_downloadable_drafts_and_schema_findings(growth_client, monkeypatch):
    client, _ = growth_client
    monkeypatch.setattr(public.geolib, "fetch_text", lambda url, timeout=6, allow_machine_file=False: "<html><title>Acme</title><meta name='description' content='Official Acme site'><script type='application/ld+json'>{\"@type\":\"Organization\"}</script></html>" if not url.endswith("/llms.txt") else "")
    llms = client.post("/api/v1/public/llms-txt-tool", json={"url": "https://acme.example"})
    assert llms.status_code == 200
    assert llms.json()["kind"] == "public_llms_txt_tool"
    assert "# Acme" in llms.json()["draft"]
    schema = client.post("/api/v1/public/schema-tool", json={"url": "https://acme.example"})
    assert schema.status_code == 200
    assert schema.json()["types"] == ["Organization"]


def test_public_tools_have_independent_rate_limit_buckets(growth_client, monkeypatch):
    client, _ = growth_client
    monkeypatch.setattr(public.geolib, "fetch_text", lambda url, timeout=6, allow_machine_file=False: "<html><title>Acme</title></html>")
    for _ in range(public._AUDIT_MAX_PER_WINDOW):
        assert client.post("/api/v1/public/crawler-check", json={"url": "https://acme.example"}).status_code == 200
    assert client.post("/api/v1/public/llms-txt-tool", json={"url": "https://acme.example"}).status_code == 200
    assert client.post("/api/v1/public/schema-tool", json={"url": "https://acme.example"}).status_code == 200


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


def test_public_audit_rejects_requests_when_redis_rate_limit_is_unavailable(growth_client, monkeypatch):
    client, _ = growth_client

    def unavailable(*args, **kwargs):
        raise public.RateLimitUnavailable("redis unavailable")

    monkeypatch.setattr(public, "check_scope", unavailable)
    response = client.post("/api/v1/public/audit", json={"url": "https://unavailable.example"})

    assert response.status_code == 503
    assert response.json()["error"] == "public_audit_rate_limit_unavailable"


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
