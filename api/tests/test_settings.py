import base64

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.db import Base, get_db
from api.main import app
from api.settings.crypto import decrypt_key, encrypt_key


@pytest.fixture()
def settings_client(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-that-is-long-enough-32")
    monkeypatch.setenv("AES_KEY", base64.urlsafe_b64encode(b"0" * 32).decode())
    engine = create_engine(f"sqlite:///{tmp_path / 'settings.sqlite'}")
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


def _headers(client, email):
    assert client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "correct-horse-battery"},
    ).status_code == 201
    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "correct-horse-battery"},
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_crypto_round_trip_and_api_key_lifecycle(settings_client):
    client = settings_client
    headers = _headers(client, "owner@example.com")
    encrypted = encrypt_key("sk-test-secret")
    assert encrypted != "sk-test-secret"
    assert decrypt_key(encrypted) == "sk-test-secret"

    saved = client.put(
        "/api/v1/settings/keys",
        headers=headers,
        json={"engine_code": "deepseek", "key_value": "sk-test-secret"},
    )
    assert saved.status_code == 200
    assert saved.json() == {"engine_code": "deepseek", "masked": "****cret"}

    listed = client.get("/api/v1/settings/keys", headers=headers)
    assert listed.status_code == 200
    assert listed.json() == {"keys": [{"engine_code": "deepseek", "masked": "****cret"}]}
    assert "sk-test-secret" not in listed.text

    deleted = client.delete("/api/v1/settings/keys/deepseek", headers=headers)
    assert deleted.status_code == 200
    assert client.get("/api/v1/settings/keys", headers=headers).json() == {"keys": []}


def test_keys_are_tenant_isolated(settings_client):
    client = settings_client
    first = _headers(client, "first@example.com")
    second = _headers(client, "second@example.com")
    assert client.put(
        "/api/v1/settings/keys",
        headers=first,
        json={"engine_code": "openai", "key_value": "sk-first"},
    ).status_code == 200
    assert client.get("/api/v1/settings/keys", headers=second).json() == {"keys": []}

