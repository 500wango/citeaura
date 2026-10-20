import base64
import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.db import Base, get_db
from api.main import app
from api.models import ApiKey, CustomProvider
from api.settings import router as settings_router
from api.settings.crypto import decrypt_key, encrypt_key, key_aad


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
    # 注册接口固定返回 202 + accepted（不再泄露邮箱是否已存在，也不返回 user/tenant）。
    registered = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "correct-horse-battery"},
    )
    assert registered.status_code == 202
    assert registered.json()["accepted"] is True
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

    # 末位掩码随写入落库，列表接口不再为打码而解密。
    with client.session_factory() as db:
        assert db.query(ApiKey).one().key_suffix == "cret"

    listed = client.get("/api/v1/settings/keys", headers=headers)
    assert listed.status_code == 200
    assert listed.json() == {"keys": [{"engine_code": "openai", "masked": "****cret"}]}
    assert "sk-test-secret" not in listed.text

    deleted = client.delete("/api/v1/settings/keys/openai", headers=headers)
    assert deleted.status_code == 200
    assert client.get("/api/v1/settings/keys", headers=headers).json() == {"keys": []}


def test_domestic_engine_keys_are_supported_and_isolated(settings_client):
    client = settings_client
    headers = _headers(client, "domestic-owner@example.com")
    domestic = ("glm", "doubao", "kimi", "minimax")
    for code in domestic:
        saved = client.put(
            "/api/v1/settings/keys",
            headers=headers,
            json={"engine_code": code, "key_value": f"{code}-test-secret"},
        )
        assert saved.status_code == 200
        assert saved.json()["engine_code"] == code
        assert f"{code}-test-secret" not in saved.text

    listed = client.get("/api/v1/settings/keys", headers=headers)
    assert listed.status_code == 200
    assert {item["engine_code"] for item in listed.json()["keys"]} == set(domestic)


def test_corrupted_ciphertext_uses_value_error_contract(monkeypatch):
    monkeypatch.setenv("AES_KEY", base64.urlsafe_b64encode(b"0" * 32).decode())
    encrypted = encrypt_key("sk-test-secret")
    corrupted = encrypted[:-2] + ("A" if encrypted[-2] != "A" else "B") + encrypted[-1]
    with pytest.raises(ValueError, match="invalid encrypted API key"):
        decrypt_key(corrupted)


def test_encrypted_keys_are_bound_to_their_tenant_and_engine(monkeypatch):
    monkeypatch.setenv("AES_KEY", base64.urlsafe_b64encode(b"0" * 32).decode())
    encrypted = encrypt_key("sk-test-secret", key_aad(1, "openai"))

    assert decrypt_key(encrypted, key_aad(1, "openai")) == "sk-test-secret"
    with pytest.raises(ValueError, match="invalid encrypted API key"):
        decrypt_key(encrypted, key_aad(2, "openai"))
    with pytest.raises(ValueError, match="invalid encrypted API key"):
        decrypt_key(encrypted, key_aad(1, "deepseek"))


def test_legacy_unbound_ciphertext_remains_readable_during_migration(monkeypatch, caplog):
    monkeypatch.setenv("AES_KEY", base64.urlsafe_b64encode(b"0" * 32).decode())
    encrypted = encrypt_key("sk-legacy-secret")

    with caplog.at_level(logging.WARNING, logger="api.settings.crypto"):
        assert decrypt_key(encrypted, key_aad(1, "openai")) == "sk-legacy-secret"

    # AAD 回退是一条需要被看见的退路：必须留下警告，方便运维安排重加密。
    assert "legacy ciphertext" in caplog.text


def test_key_list_uses_persisted_suffix_and_backfills_legacy_rows(settings_client):
    client = settings_client
    headers = _headers(client, "suffix@example.com")
    for engine, key in (("openai", "sk-openai-store-1234"), ("deepseek", "sk-legacy-row-9876")):
        assert client.put(
            "/api/v1/settings/keys",
            headers=headers,
            json={"engine_code": engine, "key_value": key},
        ).status_code == 200

    with client.session_factory() as db:
        rows = {row.engine_code: row for row in db.query(ApiKey).all()}
        assert rows["openai"].key_suffix == "1234"
        # 模拟历史行：列没有值时列表接口回退解密一次并回填。
        rows["deepseek"].key_suffix = None
        db.commit()

    listed = client.get("/api/v1/settings/keys", headers=headers)
    assert listed.status_code == 200
    assert {item["engine_code"]: item["masked"] for item in listed.json()["keys"]} == {
        "openai": "****1234",
        "deepseek": "****9876",
    }

    with client.session_factory() as db:
        legacy = db.query(ApiKey).filter(ApiKey.engine_code == "deepseek").one()
        assert legacy.key_suffix == "9876"
        # 回填之后列表不再有解密面：密文不可解也不影响打码结果。
        legacy.encrypted_value = "not-a-ciphertext"
        db.commit()

    relisted = client.get("/api/v1/settings/keys", headers=headers)
    assert relisted.status_code == 200
    assert {item["engine_code"]: item["masked"] for item in relisted.json()["keys"]} == {
        "openai": "****1234",
        "deepseek": "****9876",
    }


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
        assert decrypt_key(row.encrypted_api_key, key_aad(row.tenant_id, row.code)) == "sk-custom-secret"

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
        row = db.query(CustomProvider).one()
        assert decrypt_key(row.encrypted_api_key, key_aad(row.tenant_id, row.code)) == "sk-replaced-secret"

    deleted = client.delete(f"/api/v1/settings/keys/custom/{provider['code']}", headers=first)
    assert deleted.status_code == 200
    assert client.get("/api/v1/settings/keys/custom", headers=first).json() == {"providers": []}


def test_custom_provider_connection_uses_single_exact_request(monkeypatch):
    """连接测试必须复用采样引擎，发出的请求与真实采样逐字节一致。"""
    import sample

    calls = []

    class Response:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {
                "model": "vendor/model:exact",
                "choices": [{"message": {"content": "OK"}}],
            }

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    monkeypatch.setattr(sample.requests, "post", fake_post)
    result = settings_router._test_custom_provider({
        "code": "custom_abc123",
        "name": "Gateway",
        "base_url": "https://gateway.example.com/v1",
        "api_key": "sk-test",
        "model_id": "vendor/model:exact",
        "market": "global",
        "protocol": "",
        "search": False,
        "extra_headers": None,
    })

    assert result["ok"] is True
    assert result["answer"] == "OK"
    assert calls == [
        (
            "https://gateway.example.com/v1/chat/completions",
            {
                "headers": {
                    "Authorization": "Bearer sk-test",
                    "Content-Type": "application/json",
                    "User-Agent": "CiteAura/1.0",
                },
                "json": {
                    "model": "vendor/model:exact",
                    "messages": [{"role": "user", "content": "Reply with exactly OK."}],
                    "temperature": 0.7,
                },
                "timeout": 20,
            },
        ),
    ]


def test_custom_provider_connection_surfaces_provider_http_code():
    """引擎返回的 HTTP 诊断码必须能被压缩成稳定的前端错误码。"""
    assert settings_router._safe_provider_error("HTTP 402: body") == "provider_http_402"
    assert settings_router._safe_provider_error("HTTP 503: body") == "provider_http_503"
    assert settings_router._safe_provider_error("ReadTimeout: x") == "provider_timeout"
    assert settings_router._safe_provider_error("boom") == "provider_request_failed"


def test_custom_provider_transport_round_trips_to_the_api(settings_client, monkeypatch):
    client = settings_client
    headers = _headers(client, "custom-transport@example.com")
    monkeypatch.setattr(settings_router, "validate_outbound_url", lambda value, **kwargs: value)
    monkeypatch.setattr(
        settings_router,
        "_test_custom_provider",
        lambda provider: {"ok": True, "answer": "OK"},
    )

    saved = client.put(
        "/api/v1/settings/keys/custom",
        headers=headers,
        json={
            "name": "OpenCode Go",
            "base_url": "https://opencode.ai/inference/go/v1/messages",
            "api_key": "sk-custom-secret",
            "model_id": "claude-haiku-5-5",
            "market": "global",
            "protocol": "anthropic",
            "search": True,
            "extra_headers": {"X-Opencode-Session": " citeaura "},
        },
    )

    assert saved.status_code == 200
    provider = saved.json()["provider"]
    assert provider["base_url"] == "https://opencode.ai/inference/go/v1"
    assert provider["protocol"] == "anthropic"
    assert provider["search"] is True
    assert provider["extra_headers"] == {"X-Opencode-Session": "citeaura"}
    assert provider["sampling_mode_code"] == "search"
    assert "sk-custom-secret" not in saved.text
    assert client.get("/api/v1/settings/keys/custom", headers=headers).json() == {"providers": [provider]}

    with client.session_factory() as db:
        row = db.query(CustomProvider).one()
        assert row.protocol == "anthropic"
        assert row.search is True
        assert row.extra_headers is not None


def test_custom_provider_transport_defaults_stay_empty(settings_client, monkeypatch):
    client = settings_client
    headers = _headers(client, "custom-defaults@example.com")
    monkeypatch.setattr(settings_router, "validate_outbound_url", lambda value, **kwargs: value)
    monkeypatch.setattr(
        settings_router,
        "_test_custom_provider",
        lambda provider: {"ok": True, "answer": "OK"},
    )

    saved = client.put(
        "/api/v1/settings/keys/custom",
        headers=headers,
        json={
            "name": "Plain Gateway",
            "base_url": "https://gateway.example.com/v1",
            "api_key": "sk-plain",
            "model_id": "vendor/model",
            "market": "global",
        },
    )

    assert saved.status_code == 200
    provider = saved.json()["provider"]
    assert provider["protocol"] == ""
    assert provider["search"] is False
    assert provider["extra_headers"] == {}
    assert provider["sampling_mode_code"] == "parametric"
    with client.session_factory() as db:
        row = db.query(CustomProvider).one()
        assert row.protocol is None
        assert row.extra_headers is None


def test_custom_provider_headers_reject_credentials_and_bad_shapes(settings_client, monkeypatch):
    client = settings_client
    headers = _headers(client, "custom-headers@example.com")
    monkeypatch.setattr(settings_router, "validate_outbound_url", lambda value, **kwargs: value)
    monkeypatch.setattr(
        settings_router,
        "_test_custom_provider",
        lambda provider: {"ok": True, "answer": "OK"},
    )
    base = {
        "name": "Header Gateway",
        "base_url": "https://gateway.example.com/v1",
        "api_key": "sk-header",
        "model_id": "vendor/model",
        "market": "global",
    }

    for name in (
        "Authorization", "authorization", "X-Api-Key",
        "Proxy-Authorization", "api-key", "apikey", "Cookie",
        "X-Auth-Token", "X-Goog-Api-Key", "X-Amz-Security-Token",
    ):
        response = client.put(
            "/api/v1/settings/keys/custom",
            headers=headers,
            json={**base, "extra_headers": {name: "Bearer sneaky"}},
        )
        assert response.status_code == 422, name

    for extra_headers in (
        {"Bad Header": "value"},
        {"X-Ok": "line1\nline2"},
        {"X-Ok": "nul\x00byte"},
        {f"X-Header-{index}": "v" for index in range(17)},
        {"X-Ok": "v" * 4200},
    ):
        response = client.put(
            "/api/v1/settings/keys/custom",
            headers=headers,
            json={**base, "extra_headers": extra_headers},
        )
        assert response.status_code == 422, extra_headers

    assert client.get("/api/v1/settings/keys/custom", headers=headers).json() == {"providers": []}


def test_custom_provider_rejects_unknown_protocol(settings_client, monkeypatch):
    client = settings_client
    headers = _headers(client, "custom-protocol@example.com")
    monkeypatch.setattr(settings_router, "validate_outbound_url", lambda value, **kwargs: value)

    response = client.put(
        "/api/v1/settings/keys/custom",
        headers=headers,
        json={
            "name": "Bad Protocol",
            "base_url": "https://gateway.example.com/v1",
            "api_key": "sk-bad",
            "model_id": "vendor/model",
            "market": "global",
            "protocol": "ark",
        },
    )

    assert response.status_code == 422


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

def test_keys_reject_nul_byte(settings_client):
    headers = _headers(settings_client, "nultest@example.com")
    response = settings_client.put(
        "/api/v1/settings/keys",
        json={"engine_code": "openai", "key_value": "test\x00key"},
        headers=headers,
    )
    assert response.status_code == 422

    response = settings_client.post(
        "/api/v1/settings/keys/custom/test",
        json={
            "name": "Test\x00",
            "base_url": "https://example.com",
            "api_key": "test_key",
            "model_id": "test_model",
            "market": "both",
        },
        headers=headers,
    )
    assert response.status_code == 422

