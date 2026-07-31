import base64
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.auth import oidc
from api.auth.security import create_sso_state
from api.auth.sso import SSO_CONTEXT_COOKIE
from api.db import Base, get_db
from api.main import app
from api.models import AuditEvent, Membership, SsoConfiguration, Tenant, User
from api.settings.crypto import encrypt_key


@pytest.fixture()
def sso_client(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-that-is-long-enough-32")
    monkeypatch.setenv("AES_KEY", base64.urlsafe_b64encode(b"s" * 32).decode())
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://app.example.test")
    monkeypatch.delenv("SESSION_COOKIE_SECURE", raising=False)
    engine = create_engine(f"sqlite:///{tmp_path / 'sso.sqlite'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client, session_factory
    app.dependency_overrides.clear()


def _register_login(client, email="owner@example.com", tenant_name="enterprise-team"):
    registered = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "correct-horse-battery", "tenant_name": tenant_name},
    )
    assert registered.status_code == 201
    logged_in = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "correct-horse-battery"},
    )
    assert logged_in.status_code == 200
    return registered.json(), {"Authorization": f"Bearer {logged_in.json()['access_token']}"}


def _config_payload(**updates):
    payload = {
        "provider_name": "Example Identity",
        "issuer_url": "https://identity.example.test",
        "client_id": "disvorai-client",
        "client_secret": "top-secret-client-value",
        "allowed_domains": ["example.com"],
        "default_role": "viewer",
        "enabled": True,
    }
    payload.update(updates)
    return payload


def test_enterprise_owner_configures_sso_without_exposing_secret(sso_client, monkeypatch):
    client, session_factory = sso_client
    registered, headers = _register_login(client)
    tenant_id = registered["tenant"]["id"]

    blocked = client.put("/api/v1/sso/config", headers=headers, json=_config_payload())
    assert blocked.status_code == 403
    assert blocked.json() == {"error": "enterprise_plan_required"}
    with session_factory() as db:
        db.get(Tenant, tenant_id).plan = "enterprise"
        db.commit()

    saved = client.put("/api/v1/sso/config", headers=headers, json=_config_payload())
    assert saved.status_code == 200
    assert saved.json()["client_secret_configured"] is True
    assert saved.json()["login_url"] == f"/api/v1/sso/login/{tenant_id}"
    assert "client_secret" not in saved.json()
    with session_factory() as db:
        stored = db.get(SsoConfiguration, tenant_id)
        assert stored.encrypted_client_secret != "top-secret-client-value"
        assert "top-secret-client-value" not in stored.encrypted_client_secret
        assert json.loads(stored.allowed_domains) == ["example.com"]

    monkeypatch.setattr(
        oidc,
        "authorization_request",
        lambda configuration, redirect_uri, state: (
            f"https://identity.example.test/authorize?state={state}",
            {"state": state, "verifier": "verifier", "nonce": "nonce"},
        ),
    )
    started = client.get(f"/api/v1/sso/login/{tenant_id}", follow_redirects=False)
    assert started.status_code == 303
    assert started.headers["location"].startswith("https://identity.example.test/authorize?")
    assert SSO_CONTEXT_COOKIE in started.cookies

    audit = client.get("/api/v1/sso/audit-events", headers=headers)
    assert audit.status_code == 200
    assert audit.json()["soc2_status"] == "controls_ready_not_certified"
    assert any(
        event["action"] == "api.put" and event["target"] == "/api/v1/sso/config"
        for event in audit.json()["events"]
    )


def test_sso_callback_provisions_member_and_rejects_unapproved_domain(sso_client, monkeypatch):
    client, session_factory = sso_client
    registered, owner_headers = _register_login(client)
    tenant_id = registered["tenant"]["id"]
    with session_factory() as db:
        tenant = db.get(Tenant, tenant_id)
        tenant.plan = "enterprise"
        db.add(SsoConfiguration(
            tenant_id=tenant_id,
            provider_name="Example Identity",
            issuer_url="https://identity.example.test",
            client_id="disvorai-client",
            encrypted_client_secret=encrypt_key("secret"),
            allowed_domains='["example.com"]',
            default_role="viewer",
            enabled=True,
        ))
        db.commit()

    state = create_sso_state(tenant_id)
    context = {"state": state, "verifier": "verifier", "nonce": "nonce"}
    client.cookies.set(SSO_CONTEXT_COOKIE, encrypt_key(json.dumps(context)))
    monkeypatch.setattr(
        oidc,
        "complete_login",
        lambda configuration, redirect_uri, code, current: {
            "email": "new.member@example.com", "subject": "idp-subject-1", "claims": {},
        },
    )
    completed = client.get(
        "/api/v1/sso/callback",
        params={"code": "authorization-code", "state": state},
        follow_redirects=False,
    )
    assert completed.status_code == 303
    assert completed.headers["location"] == "/#overview"
    assert "disvorai_access_token=" in completed.headers["set-cookie"]
    with session_factory() as db:
        user = db.query(User).filter(User.email == "new.member@example.com").one()
        assert db.get(Membership, {"tenant_id": tenant_id, "user_id": user.id}).role == "viewer"
        event = db.query(AuditEvent).filter(AuditEvent.action == "sso.login").one()
        assert event.outcome == "succeeded"
        assert "idp-subject-1" in event.details

    rejected_state = create_sso_state(tenant_id)
    rejected_context = {"state": rejected_state, "verifier": "verifier", "nonce": "nonce"}
    client.cookies.set(SSO_CONTEXT_COOKIE, encrypt_key(json.dumps(rejected_context)))
    monkeypatch.setattr(
        oidc,
        "complete_login",
        lambda configuration, redirect_uri, code, current: {
            "email": "outsider@other.test", "subject": "idp-subject-2", "claims": {},
        },
    )
    rejected = client.get(
        "/api/v1/sso/callback",
        params={"code": "authorization-code", "state": rejected_state},
        follow_redirects=False,
    )
    assert rejected.status_code == 403
    assert rejected.json() == {"error": "sso_domain_not_allowed"}
    assert client.get("/api/v1/sso/audit-events", headers=owner_headers).status_code == 200


def test_sso_config_and_audit_are_tenant_isolated(sso_client):
    client, session_factory = sso_client
    first, first_headers = _register_login(client, "first@example.com", "first-enterprise")
    second, second_headers = _register_login(client, "second@example.net", "second-enterprise")
    with session_factory() as db:
        db.get(Tenant, first["tenant"]["id"]).plan = "enterprise"
        db.get(Tenant, second["tenant"]["id"]).plan = "enterprise"
        db.commit()
    assert client.put("/api/v1/sso/config", headers=first_headers, json=_config_payload()).status_code == 200
    first_audit = client.get("/api/v1/sso/audit-events", headers=first_headers).json()["events"]
    second_audit = client.get("/api/v1/sso/audit-events", headers=second_headers).json()["events"]
    assert first_audit
    assert second_audit == []
    assert client.get("/api/v1/sso/config", headers=second_headers).json()["configured"] is False


def test_oidc_issuer_requires_https_except_loopback():
    assert oidc.normalize_issuer_url("https://identity.example.test/") == "https://identity.example.test"
    assert oidc.normalize_issuer_url("http://127.0.0.1:9000/") == "http://127.0.0.1:9000"
    with pytest.raises(ValueError, match="issuer_url_must_use_https"):
        oidc.normalize_issuer_url("http://identity.example.test")
