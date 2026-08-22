import base64

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.db import Base, get_db
from api.main import app
from api.models import CustomProvider
from api.settings import router as settings_router
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
        test_client.session_factory = session_factory
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
        json={"engine_code": "openai", "key_value": "sk-test-secret"},
    )
    assert saved.status_code == 200
    assert saved.json() == {"engine_code": "openai", "masked": "****cret"}

    listed = client.get("/api/v1/settings/keys", headers=headers)
    assert listed.status_code == 200
    assert listed.json() == {"keys": [{"engine_code": "openai", "masked": "****cret"}]}
    assert "sk-test-secret" not in listed.text

    deleted = client.delete("/api/v1/settings/keys/openai", headers=headers)
    assert deleted.status_code == 200
    assert client.get("/api/v1/settings/keys", headers=headers).json() == {"keys": []}


def test_corrupted_ciphertext_uses_value_error_contract():
    encrypted = encrypt_key("sk-test-secret")
    corrupted = encrypted[:-2] + ("A" if encrypted[-2] != "A" else "B") + encrypted[-1]
    with pytest.raises(ValueError, match="invalid encrypted API key"):
        decrypt_key(corrupted)


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


def test_custom_provider_lifecycle_is_encrypted_and_tenant_isolated(settings_client, monkeypatch):
    client = settings_client
    first = _headers(client, "custom-first@example.com")
    second = _headers(client, "custom-second@example.com")
    monkeypatch.setattr(settings_router, "validate_outbound_url", lambda value, **kwargs: value)
    monkeypatch.setattr(
        settings_router,
        "_test_custom_provider",
        lambda provider: {"ok": True, "answer": "OK", "raw_model": provider["model_id"]},
    )
    payload = {
        "name": "Budget Gateway",
        "base_url": "https://gateway.example.com/v1/chat/completions",
        "api_key": "sk-custom-secret",
        "model_id": "vendor/budget-model",
        "market": "global",
    }

    saved = client.put("/api/v1/settings/keys/custom", headers=first, json=payload)

    assert saved.status_code == 200
    provider = saved.json()["provider"]
    assert provider["name"] == "Budget Gateway"
    assert provider["base_url"] == "https://gateway.example.com/v1"
    assert provider["model_id"] == "vendor/budget-model"
    assert provider["masked"] == "****cret"
    assert "sk-custom-secret" not in saved.text
    listed = client.get("/api/v1/settings/keys/custom", headers=first)
    assert listed.json() == {"providers": [provider]}
    assert client.get("/api/v1/settings/keys/custom", headers=second).json() == {"providers": []}

    with client.session_factory() as db:
        row = db.query(CustomProvider).one()
        assert row.encrypted_api_key != "sk-custom-secret"
        assert decrypt_key(row.encrypted_api_key) == "sk-custom-secret"

    updated = client.put(
        "/api/v1/settings/keys/custom",
        headers=first,
        json={
            **payload,
            "base_url": "https://other-gateway.example.com/api/v1",
            "api_key": "sk-replaced-secret",
            "model_id": "vendor/replacement-model",
            "market": "global",
        },
    )
    assert updated.status_code == 200
    provider = updated.json()["provider"]
    assert provider["base_url"] == "https://other-gateway.example.com/api/v1"
    assert provider["model_id"] == "vendor/replacement-model"
    assert provider["market"] == "global"
    with client.session_factory() as db:
        assert db.query(CustomProvider).count() == 1
        assert decrypt_key(db.query(CustomProvider).one().encrypted_api_key) == "sk-replaced-secret"

    deleted = client.delete(f"/api/v1/settings/keys/custom/{provider['code']}", headers=first)
    assert deleted.status_code == 200
    assert client.get("/api/v1/settings/keys/custom", headers=first).json() == {"providers": []}


def test_custom_provider_connection_uses_single_exact_request(monkeypatch):
    calls = []

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {
                "model": "vendor/model:exact",
                "choices": [{"message": {"content": "OK"}}],
            }

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    monkeypatch.setattr(settings_router.requests, "post", fake_post)
    result = settings_router._test_custom_provider({
        "code": "custom_abc123",
        "name": "Gateway",
        "base_url": "https://gateway.example.com/v1",
        "api_key": "sk-test",
        "model_id": "vendor/model:exact",
        "market": "global",
    })

    assert result == {"ok": True, "answer": "OK", "raw_model": "vendor/model:exact"}
    assert calls == [
        (
            "https://gateway.example.com/v1/chat/completions",
            {
                "headers": {"Authorization": "Bearer sk-test", "Content-Type": "application/json"},
                "json": {
                    "model": "vendor/model:exact",
                    "messages": [{"role": "user", "content": "Reply with exactly OK."}],
                    "temperature": 0.7,
                },
                "timeout": 15,
            },
        ),
    ]


def test_custom_provider_must_connect_before_save(settings_client, monkeypatch):
    client = settings_client
    headers = _headers(client, "custom-failure@example.com")
    monkeypatch.setattr(settings_router, "validate_outbound_url", lambda value, **kwargs: value)
    monkeypatch.setattr(
        settings_router,
        "_test_custom_provider",
        lambda provider: {"ok": False, "error": "HTTP 401: provider response is not returned"},
    )

    response = client.put(
        "/api/v1/settings/keys/custom",
        headers=headers,
        json={
            "name": "Unavailable Gateway",
            "base_url": "https://gateway.example.com/v1",
            "api_key": "sk-failed",
            "model_id": "vendor/model",
            "market": "global",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"] == "custom_provider_connection_failed"
    assert response.json()["detail"] == "provider_http_401"
    with client.session_factory() as db:
        assert db.query(CustomProvider).count() == 0
