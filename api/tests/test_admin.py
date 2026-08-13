import base64
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.auth.security import hash_password
from api.db import Base, get_db
from api.main import app
from api.models import AdminAuditEvent, Job, Membership, PlatformAdmin, ProductEvent, Project, Subscription, Tenant, User


@pytest.fixture()
def admin_client(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-that-is-long-enough-32")
    monkeypatch.setenv("AES_KEY", base64.urlsafe_b64encode(b"a" * 32).decode())
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    engine = create_engine(f"sqlite:///{tmp_path / 'admin.sqlite'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with session_factory() as db:
        db.add(PlatformAdmin(
            email="admin@citeaura.com",
            password_hash=hash_password("correct-admin-password"),
            role="superadmin",
        ))
        db.commit()
    with TestClient(app) as client:
        client.session_factory = session_factory
        yield client
    app.dependency_overrides.clear()


def _login_admin(client):
    return client.post("/api/v1/admin/auth/login", json={
        "email": "admin@citeaura.com",
        "password": "correct-admin-password",
    })


def test_country_attribution_requires_trusted_cloudflare_proxy(admin_client, monkeypatch):
    client = admin_client
    payload = {"email": "first@example.com", "password": "correct-horse-battery", "tenant_name": "first"}
    untrusted = client.post("/api/v1/auth/register", headers={"CF-IPCountry": "US"}, json=payload)
    assert untrusted.status_code == 201
    with client.session_factory() as db:
        first = db.query(User).filter(User.email == payload["email"]).one()
        first_tenant = db.query(Tenant).filter(Tenant.name == "first").one()
        assert first.signup_country_code is None
        assert first_tenant.acquisition_country_code is None

    monkeypatch.setenv("TRUST_CLOUDFLARE_COUNTRY_HEADER", "true")
    trusted = client.post(
        "/api/v1/auth/register",
        headers={"CF-IPCountry": "de"},
        json={"email": "second@example.com", "password": "correct-horse-battery", "tenant_name": "second"},
    )
    assert trusted.status_code == 201
    with client.session_factory() as db:
        second = db.query(User).filter(User.email == "second@example.com").one()
        tenant = db.query(Tenant).filter(Tenant.name == "second").one()
        assert second.signup_country_code == "DE"
        assert tenant.acquisition_country_code == "DE"
        assert tenant.country_source == "cloudflare_signup"
        event = db.query(ProductEvent).filter(ProductEvent.tenant_id == tenant.id, ProductEvent.name == "signup_completed").one()
        assert event.country_code == "DE"


def test_admin_password_session_is_separate_from_tenant_session(admin_client):
    client = admin_client
    invalid = client.post("/api/v1/admin/auth/login", json={
        "email": "admin@citeaura.com",
        "password": "wrong-admin-password",
    })
    assert invalid.status_code == 401

    logged_in = _login_admin(client)
    assert logged_in.status_code == 200
    assert "citeaura_admin_session=" in logged_in.headers["set-cookie"]
    assert client.get("/api/v1/admin/me").status_code == 200
    assert client.get("/api/v1/me").status_code == 401

    client.cookies.delete("citeaura_admin_session")
    registered = client.post(
        "/api/v1/auth/register",
        json={"email": "owner@example.com", "password": "correct-horse-battery"},
    )
    assert registered.status_code == 201
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.com", "password": "correct-horse-battery"},
    )
    client.cookies.set("citeaura_access_token", login.cookies.get("citeaura_access_token"))
    assert client.get("/api/v1/admin/me").status_code == 401


def test_admin_can_change_password_and_existing_session_is_revoked(admin_client):
    client = admin_client
    assert _login_admin(client).status_code == 200
    current_cookie = client.cookies.get("citeaura_admin_session")

    wrong = client.post(
        "/api/v1/admin/auth/password",
        headers={"X-CiteAura-Admin": "console"},
        json={"current_password": "wrong-admin-password", "new_password": "replacement-admin-password"},
    )
    assert wrong.status_code == 400
    assert wrong.json()["error"] == "current_password_incorrect"
    assert client.get("/api/v1/admin/me").status_code == 200

    changed = client.post(
        "/api/v1/admin/auth/password",
        headers={"X-CiteAura-Admin": "console"},
        json={"current_password": "correct-admin-password", "new_password": "replacement-admin-password"},
    )
    assert changed.status_code == 200
    assert "citeaura_admin_session=\"\"" in changed.headers["set-cookie"]
    client.cookies.set("citeaura_admin_session", current_cookie)
    assert client.get("/api/v1/admin/me").status_code == 401
    client.cookies.clear()
    assert client.post("/api/v1/admin/auth/login", json={
        "email": "admin@citeaura.com", "password": "correct-admin-password",
    }).status_code == 401
    assert client.post("/api/v1/admin/auth/login", json={
        "email": "admin@citeaura.com", "password": "replacement-admin-password",
    }).status_code == 200
    with client.session_factory() as db:
        event = db.query(AdminAuditEvent).filter(AdminAuditEvent.action == "admin.password_changed").one()
        assert event.target == "admin:1"


def test_overview_country_funnel_and_usd_mrr(admin_client):
    client = admin_client
    now = datetime.now(timezone.utc)
    with client.session_factory() as db:
        owner = User(email="paid@example.com", password_hash="hash", signup_country_code="US")
        tenant = Tenant(
            name="paid-us",
            plan="pro",
            acquisition_country_code="US",
            country_source="cloudflare_signup",
            trial_ends_at=None,
            created_at=now - timedelta(days=20),
        )
        db.add_all([owner, tenant])
        db.flush()
        db.add(Membership(tenant_id=tenant.id, user_id=owner.id, role="owner"))
        project = Project(tenant_id=tenant.id, slug="example", url="https://example.com", status="ready")
        db.add(project)
        db.flush()
        db.add_all([
            Job(project_id=project.id, action="sample", status="done", started_at=now - timedelta(days=10), finished_at=now - timedelta(days=10)),
            ProductEvent(tenant_id=tenant.id, name="sample_completed", country_code="US"),
            ProductEvent(tenant_id=tenant.id, name="checkout_started", country_code="US"),
            Subscription(
                tenant_id=tenant.id,
                plan="pro",
                billing_interval="annual",
                amount_usd_cents=240000,
                status="active",
                started_at=now - timedelta(days=10),
                expires_at=now + timedelta(days=355),
            ),
        ])
        db.commit()
    assert _login_admin(client).status_code == 200
    overview = client.get("/api/v1/admin/overview?days=30&country=US")
    assert overview.status_code == 200
    data = overview.json()
    assert data["customers"]["registered"] == 1
    assert data["customers"]["activated"] == 1
    assert data["customers"]["paid_current"] == 1
    assert data["funnel"]["trial_to_paid_rate"] == 100.0
    assert data["revenue"]["currency"] == "USD"
    assert data["revenue"]["mrr_usd_cents"] == 20000
    assert data["revenue"]["refunds_usd_cents"] == 0
    assert data["revenue"]["net_payments_usd_cents"] == data["revenue"]["payments_usd_cents"]


def test_ops_status_change_revokes_user_session_and_is_audited(admin_client):
    client = admin_client
    registered = client.post(
        "/api/v1/auth/register",
        json={"email": "disable@example.com", "password": "correct-horse-battery"},
    ).json()
    user_id = registered["user"]["id"]
    tenant_id = registered["tenant"]["id"]
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "disable@example.com", "password": "correct-horse-battery"},
    )
    user_cookie = login.cookies.get("citeaura_access_token")
    client.cookies.clear()
    assert _login_admin(client).status_code == 200
    changed = client.patch(
        f"/api/v1/admin/users/{user_id}/status",
        headers={"X-CiteAura-Admin": "console"},
        json={"status": "disabled", "reason": "confirmed abuse report"},
    )
    assert changed.status_code == 200
    with client.session_factory() as db:
        user = db.get(User, user_id)
        assert user.status == "disabled"
        event = db.query(AdminAuditEvent).filter(AdminAuditEvent.action == "user.status_changed").one()
        assert "confirmed abuse report" in event.details
    client.cookies.clear()
    client.cookies.set("citeaura_access_token", user_cookie)
    assert client.get("/api/v1/me").status_code == 401
    with client.session_factory() as db:
        assert db.get(Tenant, tenant_id).status == "active"
