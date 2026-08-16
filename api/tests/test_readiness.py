from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from api import readiness


ROOT = Path(__file__).resolve().parents[2]


class Result:
    def __init__(self, value=None):
        self.value = value

    def scalar_one(self):
        return self.value


class Database:
    def execute(self, statement):
        if "alembic_version" in str(statement):
            return Result(readiness.EXPECTED_DB_REVISION)
        return Result(1)


class Redis:
    @staticmethod
    def ping():
        return True


def test_readiness_requires_all_production_dependencies(monkeypatch):
    monkeypatch.setattr(readiness, "redis_client", lambda: Redis())
    monkeypatch.setattr(readiness, "_worker_available", lambda: True)
    monkeypatch.setattr(readiness, "_master_key", lambda: b"a" * 32)
    monkeypatch.setattr(readiness.config, "billing_enabled", lambda: True)
    monkeypatch.setattr(readiness.stripe_adapter, "configured", lambda: True)
    monkeypatch.setattr(readiness.config, "jwt_secret", lambda: "j" * 32)
    monkeypatch.setattr(readiness.config, "session_cookie_secure", lambda: True)
    monkeypatch.setattr(readiness.config, "public_base_url", lambda: "https://app.example.test")
    monkeypatch.setattr(readiness.config, "password_reset_email_enabled", lambda: True)
    monkeypatch.setattr(readiness.config, "auth_smtp_configured", lambda: True)

    result = readiness.readiness_checks(Database())

    assert result["status"] == "ready"
    assert all(result["checks"].values())


def test_readiness_requires_latest_migration():
    migrations = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    assert readiness.EXPECTED_DB_REVISION == migrations.get_current_head()


def test_readiness_reports_failed_dependency_without_secret_details(monkeypatch):
    monkeypatch.setattr(readiness, "redis_client", lambda: (_ for _ in ()).throw(OSError("secret-host")))
    monkeypatch.setattr(readiness, "_worker_available", lambda: True)
    monkeypatch.setattr(readiness, "_master_key", lambda: b"a" * 32)
    monkeypatch.setattr(readiness.config, "billing_enabled", lambda: True)
    monkeypatch.setattr(readiness.stripe_adapter, "configured", lambda: True)
    monkeypatch.setattr(readiness.config, "jwt_secret", lambda: "j" * 32)
    monkeypatch.setattr(readiness.config, "session_cookie_secure", lambda: True)
    monkeypatch.setattr(readiness.config, "public_base_url", lambda: "https://app.example.test")
    monkeypatch.setattr(readiness.config, "password_reset_email_enabled", lambda: True)
    monkeypatch.setattr(readiness.config, "auth_smtp_configured", lambda: True)

    result = readiness.readiness_checks(Database())

    assert result["status"] == "not_ready"
    assert result["checks"]["redis"] is False
    assert "secret-host" not in str(result)


def test_readiness_allows_disabled_optional_features(monkeypatch):
    monkeypatch.setattr(readiness, "redis_client", lambda: Redis())
    monkeypatch.setattr(readiness, "_worker_available", lambda: True)
    monkeypatch.setattr(readiness, "_master_key", lambda: b"a" * 32)
    monkeypatch.setattr(readiness.config, "billing_enabled", lambda: False)
    monkeypatch.setattr(readiness.stripe_adapter, "configured", lambda: False)
    monkeypatch.setattr(readiness.config, "jwt_secret", lambda: "j" * 32)
    monkeypatch.setattr(readiness.config, "session_cookie_secure", lambda: True)
    monkeypatch.setattr(readiness.config, "public_base_url", lambda: "https://app.example.test")
    monkeypatch.setattr(readiness.config, "password_reset_email_enabled", lambda: False)
    monkeypatch.setattr(readiness.config, "auth_smtp_configured", lambda: False)

    result = readiness.readiness_checks(Database())

    assert result["status"] == "ready"
    assert result["checks"]["stripe"] is True
    assert result["checks"]["password_reset_email"] is True


def test_readiness_requires_an_active_worker(monkeypatch):
    monkeypatch.setattr(readiness, "redis_client", lambda: Redis())
    monkeypatch.setattr(readiness, "_worker_available", lambda: False)
    monkeypatch.setattr(readiness, "_master_key", lambda: b"a" * 32)
    monkeypatch.setattr(readiness.config, "billing_enabled", lambda: False)
    monkeypatch.setattr(readiness.config, "jwt_secret", lambda: "j" * 32)
    monkeypatch.setattr(readiness.config, "session_cookie_secure", lambda: True)
    monkeypatch.setattr(readiness.config, "public_base_url", lambda: "https://app.example.test")
    monkeypatch.setattr(readiness.config, "password_reset_email_enabled", lambda: False)

    result = readiness.readiness_checks(Database())

    assert result["status"] == "not_ready"
    assert result["checks"]["worker"] is False


def test_readiness_rejects_untrusted_proxy_headers_in_production_mode(monkeypatch):
    monkeypatch.setattr(readiness, "redis_client", lambda: Redis())
    monkeypatch.setattr(readiness, "_worker_available", lambda: True)
    monkeypatch.setattr(readiness, "_master_key", lambda: b"a" * 32)
    monkeypatch.setattr(readiness.config, "billing_enabled", lambda: False)
    monkeypatch.setattr(readiness.config, "jwt_secret", lambda: "j" * 32)
    monkeypatch.setattr(readiness.config, "session_cookie_secure", lambda: True)
    monkeypatch.setattr(readiness.config, "public_base_url", lambda: "https://app.example.test")
    monkeypatch.setattr(readiness.config, "password_reset_email_enabled", lambda: False)
    monkeypatch.setattr(readiness.config, "production_proxy_mode", lambda: True)
    monkeypatch.setattr(readiness.config, "rate_limit_enabled", lambda: True)
    monkeypatch.setattr(readiness.config, "rate_limit_trust_proxy_headers", lambda: False)

    result = readiness.readiness_checks(Database())

    assert result["status"] == "not_ready"
    assert result["checks"]["rate_limit_proxy_headers"] is False
