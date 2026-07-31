from api import readiness


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
    monkeypatch.setattr(readiness, "_master_key", lambda: b"a" * 32)
    monkeypatch.setattr(readiness.stripe_adapter, "configured", lambda: True)
    monkeypatch.setattr(readiness.config, "jwt_secret", lambda: "j" * 32)
    monkeypatch.setattr(readiness.config, "session_cookie_secure", lambda: True)
    monkeypatch.setattr(readiness.config, "public_base_url", lambda: "https://app.example.test")

    result = readiness.readiness_checks(Database())

    assert result["status"] == "ready"
    assert all(result["checks"].values())


def test_readiness_reports_failed_dependency_without_secret_details(monkeypatch):
    monkeypatch.setattr(readiness, "redis_client", lambda: (_ for _ in ()).throw(OSError("secret-host")))
    monkeypatch.setattr(readiness, "_master_key", lambda: b"a" * 32)
    monkeypatch.setattr(readiness.stripe_adapter, "configured", lambda: True)
    monkeypatch.setattr(readiness.config, "jwt_secret", lambda: "j" * 32)
    monkeypatch.setattr(readiness.config, "session_cookie_secure", lambda: True)
    monkeypatch.setattr(readiness.config, "public_base_url", lambda: "https://app.example.test")

    result = readiness.readiness_checks(Database())

    assert result["status"] == "not_ready"
    assert result["checks"]["redis"] is False
    assert "secret-host" not in str(result)
