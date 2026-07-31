from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.auth import password_reset
from api.adapters.engine import tenant_slug
from api.db import Base, get_db
from api.main import app
from api.models import Membership, PasswordResetToken, Tenant, User


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-that-is-long-enough-32")
    engine = create_engine(f"sqlite:///{tmp_path / 'auth.sqlite'}")
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
        test_client.session_factory = session_factory
        yield test_client
    app.dependency_overrides.clear()


def test_register_login_and_me(client):
    registered = client.post(
        "/api/v1/auth/register",
        json={"email": "owner@example.com", "password": "correct-horse-battery"},
    )
    assert registered.status_code == 201
    body = registered.json()
    assert body["user"]["email"] == "owner@example.com"
    assert body["tenant"]["plan"] == "trial"

    logged_in = client.post(
        "/api/v1/auth/login",
        json={"email": "OWNER@EXAMPLE.COM", "password": "correct-horse-battery"},
    )
    assert logged_in.status_code == 200
    tokens = logged_in.json()
    assert tokens["token_type"] == "bearer"
    assert tokens["access_token"]
    assert tokens["refresh_token"]
    cookie = logged_in.headers["set-cookie"]
    assert "disvorai_access_token=" in cookie
    assert "disvorai_refresh_token=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie
    assert logged_in.headers["cache-control"] == "no-store"

    client.cookies.delete("disvorai_access_token")
    cookie_refreshed = client.post("/api/v1/auth/refresh")
    assert cookie_refreshed.status_code == 200
    assert cookie_refreshed.json()["access_token"]

    refreshed = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert refreshed.status_code == 200
    refreshed_tokens = refreshed.json()
    assert refreshed_tokens["access_token"]
    assert refreshed_tokens["refresh_token"]
    assert refreshed.headers["cache-control"] == "no-store"

    current = client.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {refreshed_tokens['access_token']}"},
    )
    assert current.status_code == 200
    assert current.json()["user"]["email"] == "owner@example.com"
    assert current.json()["role"] == "owner"

    cookie_current = client.get("/api/v1/me")
    assert cookie_current.status_code == 200
    assert cookie_current.json()["user"]["email"] == "owner@example.com"


def test_auth_rejects_duplicate_and_invalid_credentials(client):
    payload = {"email": "owner@example.com", "password": "correct-horse-battery"}
    assert client.post("/api/v1/auth/register", json=payload).status_code == 201

    duplicate = client.post("/api/v1/auth/register", json=payload)
    assert duplicate.status_code == 409
    assert duplicate.json() == {"error": "email_already_registered"}

    invalid = client.post(
        "/api/v1/auth/login",
        json={"email": payload["email"], "password": "wrong-password"},
    )
    assert invalid.status_code == 401
    assert invalid.json() == {"error": "invalid_credentials"}


def test_me_requires_valid_access_token(client):
    response = client.get("/api/v1/me", headers={"Authorization": "Bearer invalid"})

    assert response.status_code == 401
    assert response.json() == {"error": "invalid_token"}


def test_refresh_rejects_missing_invalid_and_access_tokens(client):
    payload = {"email": "owner@example.com", "password": "correct-horse-battery"}
    assert client.post("/api/v1/auth/register", json=payload).status_code == 201
    tokens = client.post("/api/v1/auth/login", json=payload).json()

    client.cookies.clear()
    missing = client.post("/api/v1/auth/refresh")
    assert missing.status_code == 401
    assert missing.json() == {"error": "invalid_refresh_token"}
    invalid = client.post("/api/v1/auth/refresh", json={"refresh_token": "invalid"})
    assert invalid.status_code == 401
    access = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["access_token"]},
    )
    assert access.status_code == 401
    assert access.json() == {"error": "invalid_refresh_token"}


def test_logout_clears_both_session_cookies(client):
    payload = {"email": "logout@example.com", "password": "correct-horse-battery"}
    assert client.post("/api/v1/auth/register", json=payload).status_code == 201
    assert client.post("/api/v1/auth/login", json=payload).status_code == 200

    logged_out = client.post("/api/v1/auth/logout")

    assert logged_out.status_code == 200
    assert logged_out.json() == {"ok": True}
    cookies = logged_out.headers.get_list("set-cookie")
    assert any("disvorai_access_token=" in item and "Max-Age=0" in item for item in cookies)
    assert any("disvorai_refresh_token=" in item and "Max-Age=0" in item for item in cookies)
    assert client.post("/api/v1/auth/refresh").status_code == 401


def test_password_reset_is_non_enumerating_single_use_and_hashed(client, monkeypatch):
    payload = {"email": "reset@example.com", "password": "old-password-123"}
    assert client.post("/api/v1/auth/register", json=payload).status_code == 201
    sent = []
    monkeypatch.setattr(
        password_reset,
        "send_password_reset_email_safe",
        lambda email, token: sent.append((email, token)),
    )

    known = client.post("/api/v1/auth/password/forgot", json={"email": payload["email"]})
    unknown = client.post("/api/v1/auth/password/forgot", json={"email": "missing@example.com"})

    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json() == {"accepted": True}
    assert len(sent) == 1
    email, token = sent[0]
    assert email == payload["email"]
    with client.session_factory() as db:
        row = db.query(PasswordResetToken).one()
        assert row.token_hash == password_reset.token_hash(token)
        assert token not in row.token_hash

    reset = client.post(
        "/api/v1/auth/password/reset",
        json={"token": token, "password": "new-password-456"},
    )
    assert reset.status_code == 200
    assert reset.json() == {"ok": True}
    assert client.post("/api/v1/auth/login", json=payload).status_code == 401
    assert client.post(
        "/api/v1/auth/login",
        json={"email": payload["email"], "password": "new-password-456"},
    ).status_code == 200
    reused = client.post(
        "/api/v1/auth/password/reset",
        json={"token": token, "password": "third-password-789"},
    )
    assert reused.status_code == 400
    assert reused.json() == {"error": "password_reset_token_invalid"}


def test_expired_password_reset_token_is_rejected(client, monkeypatch):
    payload = {"email": "expired-reset@example.com", "password": "old-password-123"}
    assert client.post("/api/v1/auth/register", json=payload).status_code == 201
    sent = []
    monkeypatch.setattr(
        password_reset,
        "send_password_reset_email_safe",
        lambda email, token: sent.append(token),
    )
    client.post("/api/v1/auth/password/forgot", json={"email": payload["email"]})
    with client.session_factory() as db:
        row = db.query(PasswordResetToken).one()
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()

    response = client.post(
        "/api/v1/auth/password/reset",
        json={"token": sent[0], "password": "new-password-456"},
    )
    assert response.status_code == 400
    assert response.json() == {"error": "password_reset_token_invalid"}


def test_long_tenant_names_get_distinct_directory_slugs(client):
    shared_prefix = "Acme International Workspace " + "x" * 80
    first = client.post(
        "/api/v1/auth/register",
        json={
            "email": "first-long@example.com",
            "password": "correct-horse-battery",
            "tenant_name": shared_prefix + "-first",
        },
    )
    second = client.post(
        "/api/v1/auth/register",
        json={
            "email": "second-long@example.com",
            "password": "correct-horse-battery",
            "tenant_name": shared_prefix + "-second",
        },
    )

    assert first.status_code == 201
    assert second.status_code == 201
    first_name = first.json()["tenant"]["name"]
    second_name = second.json()["tenant"]["name"]
    assert first_name != second_name
    assert tenant_slug(first_name) == first_name
    assert tenant_slug(second_name) == second_name
    assert len(first_name) <= 48
    assert len(second_name) <= 48
