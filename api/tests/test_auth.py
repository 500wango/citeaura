import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.adapters.engine import tenant_slug
from api.db import Base, get_db
from api.main import app
from api.models import Membership, Tenant, User


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
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie

    current = client.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
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
