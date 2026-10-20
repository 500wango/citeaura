from datetime import datetime, timedelta, timezone

import bcrypt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.auth import password_reset
from api.auth.security import PASSWORD_HASH_PREFIX, verify_password
from api.adapters.engine import tenant_slug
from api.db import Base, get_db
from api.main import app
from api.models import Membership, PasswordResetToken, Subscription, Tenant, User


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-that-is-long-enough-32")
    monkeypatch.setenv("PASSWORD_RESET_EMAIL_ENABLED", "true")
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
    assert registered.status_code == 202
    body = registered.json()
    # 注册响应故意只返回 accepted：状态码/响应体都不能泄露邮箱是否已注册。
    assert body == {"accepted": True, "audit": None}
    assert "user" not in body and "tenant" not in body and "role" not in body

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
    assert "citeaura_access_token=" in cookie
    assert "citeaura_refresh_token=" in cookie
    assert "HttpOnly" in cookie
    assert "Path=/" in cookie
    assert "SameSite=strict" in cookie
    assert logged_in.headers["cache-control"] == "no-store"

    # 响应体里的 refresh token 走 JSON 轮换路径，只有非 Cookie 客户端才会拿到新的 token 对。
    rotated = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert rotated.status_code == 200
    refreshed_tokens = rotated.json()
    assert refreshed_tokens["access_token"]
    assert refreshed_tokens["refresh_token"]
    assert rotated.headers["cache-control"] == "no-store"

    client.cookies.delete("citeaura_access_token")
    # Cookie 承载的刷新必须带自定义头，否则视为 CSRF。
    blocked_refresh = client.post("/api/v1/auth/refresh")
    assert blocked_refresh.status_code == 403
    assert blocked_refresh.json() == {"error": "csrf_validation_failed"}
    cookie_refreshed = client.post("/api/v1/auth/refresh", headers={"X-CiteAura-Session": "cookie"})
    assert cookie_refreshed.status_code == 200
    assert cookie_refreshed.json()["authenticated"] is True
    assert "access_token" not in cookie_refreshed.json()

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


def test_auth_reads_effective_subscription_plan_without_persisting_sync(client):
    payload = {"email": "effective-plan@example.com", "password": "correct-horse-battery"}
    registered = client.post("/api/v1/auth/register", json=payload)
    assert registered.status_code == 202
    tokens = client.post("/api/v1/auth/login", json=payload).json()
    tenant_id = client.get(
        "/api/v1/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    ).json()["tenant"]["id"]

    with client.session_factory() as db:
        tenant = db.get(Tenant, tenant_id)
        tenant.plan = "trial"
        db.add(Subscription(
            tenant_id=tenant_id,
            plan="pro",
            billing_interval="monthly",
            status="active",
            provider="stripe",
            provider_subscription_id="sub-effective-plan",
            started_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        ))
        db.commit()

    response = client.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert response.status_code == 200
    assert response.json()["tenant"]["plan"] == "pro"
    with client.session_factory() as db:
        assert db.get(Tenant, tenant_id).plan == "trial"


def test_registration_schedules_welcome_email(client, monkeypatch):
    sent = []
    monkeypatch.setattr(
        "api.auth.router.transactional_email.send_welcome_email_safe",
        lambda *args: sent.append(args),
    )

    registered = client.post(
        "/api/v1/auth/register",
        json={"email": "welcome@example.com", "password": "correct-horse-battery"},
    )

    assert registered.status_code == 202
    assert sent == [("welcome@example.com", "welcome", 1)]


def test_refresh_token_rotation_detects_reuse(client):
    payload = {"email": "rotation@example.com", "password": "correct-horse-battery"}
    assert client.post("/api/v1/auth/register", json=payload).status_code == 202
    login = client.post("/api/v1/auth/login", json=payload)
    first = login.json()["refresh_token"]

    rotated = client.post("/api/v1/auth/refresh", json={"refresh_token": first})
    assert rotated.status_code == 200
    second = rotated.json()["refresh_token"]

    raced = client.post("/api/v1/auth/refresh", json={"refresh_token": first})
    assert raced.status_code == 401
    assert raced.json() == {"error": "refresh_token_reused"}
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": second}).status_code == 401


def test_auth_rejects_duplicate_and_invalid_credentials(client):
    payload = {"email": "owner@example.com", "password": "correct-horse-battery"}
    assert client.post("/api/v1/auth/register", json=payload).status_code == 202

    duplicate = client.post("/api/v1/auth/register", json=payload)
    assert duplicate.status_code == 202
    assert duplicate.json() == {"accepted": True, "audit": None}

    invalid = client.post(
        "/api/v1/auth/login",
        json={"email": payload["email"], "password": "wrong-password"},
    )
    assert invalid.status_code == 401
    assert invalid.json() == {"error": "invalid_credentials"}


def test_disabled_user_cannot_start_a_new_session(client):
    payload = {"email": "disabled@example.com", "password": "correct-horse-battery"}
    assert client.post("/api/v1/auth/register", json=payload).status_code == 202
    with client.session_factory() as db:
        from api.models import User

        user = db.query(User).filter(User.email == payload["email"]).one()
        user.status = "disabled"
        db.commit()

    response = client.post("/api/v1/auth/login", json=payload)

    assert response.status_code == 403
    assert response.json() == {"error": "account_disabled"}


def test_me_requires_valid_access_token(client):
    response = client.get("/api/v1/me", headers={"Authorization": "Bearer invalid"})

    assert response.status_code == 401
    assert response.json() == {"error": "invalid_token"}


def test_refresh_rejects_missing_invalid_and_access_tokens(client):
    payload = {"email": "owner@example.com", "password": "correct-horse-battery"}
    assert client.post("/api/v1/auth/register", json=payload).status_code == 202
    tokens = client.post("/api/v1/auth/login", json=payload).json()

    client.cookies.clear()
    # 没有 Json body 也没有会话头：Cookie 刷新路径直接按 CSRF 拒绝。
    blocked = client.post("/api/v1/auth/refresh")
    assert blocked.status_code == 403
    assert blocked.json() == {"error": "csrf_validation_failed"}
    missing = client.post("/api/v1/auth/refresh", headers={"X-CiteAura-Session": "cookie"})
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


def test_browser_session_responses_do_not_expose_jwt_tokens(client):
    registered = client.post(
        "/api/v1/auth/register",
        json={"email": "browser@example.com", "password": "correct-horse-battery", "tenant_name": "browser"},
    )
    assert registered.status_code == 202
    assert registered.json() == {"accepted": True, "audit": None}
    login = client.post(
        "/api/v1/auth/login",
        headers={"X-CiteAura-Session": "cookie"},
        json={"email": "browser@example.com", "password": "correct-horse-battery"},
    )
    assert login.status_code == 200
    assert login.json()["authenticated"] is True
    assert "access_token" not in login.json()
    refreshed = client.post("/api/v1/auth/refresh", headers={"X-CiteAura-Session": "cookie"})
    assert refreshed.status_code == 200
    assert refreshed.json()["authenticated"] is True
    assert "refresh_token" not in refreshed.json()

    # 注册响应不再返回 tenant，改从 /me 读取当前 Cookie 会话的租户。
    current = client.get("/api/v1/me")
    assert current.status_code == 200
    tenant_id = current.json()["tenant"]["id"]
    blocked = client.post("/api/v1/auth/switch-tenant", json={"tenant_id": tenant_id})
    assert blocked.status_code == 403
    assert blocked.json() == {"error": "csrf_validation_failed"}
    switched = client.post(
        "/api/v1/auth/switch-tenant",
        headers={"X-CiteAura-Session": "cookie"},
        json={"tenant_id": tenant_id},
    )
    assert switched.status_code == 200
    assert switched.json()["authenticated"] is True


def test_logout_clears_both_session_cookies(client):
    payload = {"email": "logout@example.com", "password": "correct-horse-battery"}
    assert client.post("/api/v1/auth/register", json=payload).status_code == 202
    login = client.post("/api/v1/auth/login", json=payload)
    assert login.status_code == 200
    stolen_refresh_token = login.json()["refresh_token"]

    blocked = client.post("/api/v1/auth/logout")
    assert blocked.status_code == 403
    assert blocked.json() == {"error": "csrf_validation_failed"}
    logged_out = client.post("/api/v1/auth/logout", headers={"X-CiteAura-Session": "cookie"})

    assert logged_out.status_code == 200
    assert logged_out.json() == {"ok": True}
    cookies = logged_out.headers.get_list("set-cookie")
    assert any("citeaura_access_token=" in item and "Max-Age=0" in item for item in cookies)
    assert any("citeaura_refresh_token=" in item and "Max-Age=0" in item for item in cookies)
    assert all("Path=/" in item for item in cookies)
    assert client.post("/api/v1/auth/refresh", headers={"X-CiteAura-Session": "cookie"}).status_code == 401
    rejected = client.post("/api/v1/auth/refresh", json={"refresh_token": stolen_refresh_token})
    assert rejected.status_code == 401
    with client.session_factory() as db:
        assert db.query(User).filter(User.email == payload["email"]).one().session_version == 1


def test_logout_ignores_stale_bearer_and_revokes_current_cookie_session(client):
    payload = {"email": "logout-stale@example.com", "password": "correct-horse-battery"}
    assert client.post("/api/v1/auth/register", json=payload).status_code == 202
    first = client.post("/api/v1/auth/login", json=payload).json()
    client.cookies.delete("citeaura_access_token")
    current = client.post("/api/v1/auth/login", json=payload).json()
    response = client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {first['access_token']}"},
    )
    assert response.status_code == 200
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": current["refresh_token"]}).status_code == 401


def test_password_reset_is_non_enumerating_single_use_and_hashed(client, monkeypatch):
    payload = {"email": "reset@example.com", "password": "old-password-123"}
    assert client.post("/api/v1/auth/register", json=payload).status_code == 202
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


def test_password_reset_email_uses_spa_hash_route(monkeypatch):
    sent = []
    monkeypatch.setattr(password_reset.config, "password_reset_email_enabled", lambda: True)
    monkeypatch.setattr(password_reset.config, "public_base_url", lambda: "https://citeaura.example")
    monkeypatch.setattr(password_reset.config, "password_reset_ttl_minutes", lambda: 30)
    monkeypatch.setattr(password_reset.config, "auth_smtp_configured", lambda: True)
    monkeypatch.setattr(
        password_reset.config,
        "auth_smtp_settings",
        lambda: {
            "host": "smtp.example.com",
            "port": 587,
            "security_mode": "starttls",
            "from_email": "noreply@example.com",
            "from_name": "CiteAura",
            "username": "smtp-user",
            "password": "smtp-password",
        },
    )
    monkeypatch.setattr(
        password_reset.outreach,
        "send_smtp",
        lambda draft, settings, credentials: sent.append((draft, settings, credentials)),
    )

    password_reset.send_password_reset_email("user@example.com", "token-value")

    assert "https://citeaura.example/app/#/reset-password?token=token-value" in sent[0][0]["body"]


def test_disabled_password_reset_email_does_not_create_token(client, monkeypatch):
    payload = {"email": "disabled-reset@example.com", "password": "old-password-123"}
    assert client.post("/api/v1/auth/register", json=payload).status_code == 202
    monkeypatch.setenv("PASSWORD_RESET_EMAIL_ENABLED", "false")

    response = client.post("/api/v1/auth/password/forgot", json={"email": payload["email"]})

    assert response.status_code == 503
    assert response.json() == {"error": "password_reset_email_disabled"}
    with client.session_factory() as db:
        assert db.query(PasswordResetToken).count() == 0


def test_expired_password_reset_token_is_rejected(client, monkeypatch):
    payload = {"email": "expired-reset@example.com", "password": "old-password-123"}
    assert client.post("/api/v1/auth/register", json=payload).status_code == 202
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

    assert first.status_code == 202
    assert second.status_code == 202

    def _tenant_name_for(email):
        # 注册响应不再返回 tenant，改从 /me 读取当前租户。
        login = client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "correct-horse-battery"},
        )
        assert login.status_code == 200
        current = client.get(
            "/api/v1/me",
            headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        )
        assert current.status_code == 200
        return current.json()["tenant"]["name"]

    first_name = _tenant_name_for("first-long@example.com")
    second_name = _tenant_name_for("second-long@example.com")
    assert first_name != second_name
    assert tenant_slug(first_name) == first_name
    assert tenant_slug(second_name) == second_name
    assert len(first_name) <= 48
    assert len(second_name) <= 48
    with client.session_factory() as db:
        directories = {
            row.directory_slug
            for row in db.query(Tenant).filter(Tenant.name.in_((first_name, second_name))).all()
        }
    assert directories == {first_name, second_name}


def test_login_upgrades_legacy_bcrypt_hash(client):
    legacy_hash = bcrypt.hashpw(b"legacy-password", bcrypt.gensalt()).decode("ascii")
    with client.session_factory() as db:
        tenant = Tenant(name="Legacy Workspace", plan="trial")
        db.add(tenant)
        db.flush()
        user = User(email="legacy@example.com", password_hash=legacy_hash)
        db.add(user)
        db.flush()
        db.add(Membership(tenant_id=tenant.id, user_id=user.id, role="owner"))
        db.commit()
        user_id = user.id

    logged_in = client.post(
        "/api/v1/auth/login",
        json={"email": "legacy@example.com", "password": "legacy-password"},
    )
    assert logged_in.status_code == 200

    with client.session_factory() as db:
        upgraded = db.get(User, user_id).password_hash
    assert upgraded != legacy_hash
    assert upgraded.startswith(PASSWORD_HASH_PREFIX)
    # 升级后的哈希仍必须能验证同一密码。
    assert verify_password("legacy-password", upgraded)
