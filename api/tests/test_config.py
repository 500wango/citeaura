from pathlib import Path

from api import config


def test_config_reads_runtime_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///test.sqlite")
    monkeypatch.setenv("REDIS_URL", "redis://example.test:6379/4")
    monkeypatch.setenv("PROJECT_LOCK_TTL_SECONDS", "90")
    monkeypatch.setenv("PROJECT_LOCK_WAIT_SECONDS", "2.5")
    monkeypatch.setenv("CELERY_RESULT_BACKEND", "redis://example.test:6379/5")
    monkeypatch.setenv("JWT_SECRET", "runtime-secret")
    monkeypatch.setenv("AES_KEY", "runtime-aes-key")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "yes")
    monkeypatch.setenv("WORK_ROOT", str(tmp_path / "tenant-work"))

    assert config.database_url() == "sqlite:///test.sqlite"
    assert config.redis_url() == "redis://example.test:6379/4"
    assert config.project_lock_ttl_seconds() == 90
    assert config.project_lock_wait_seconds() == 2.5
    assert config.celery_result_backend() == "redis://example.test:6379/5"
    assert config.jwt_secret() == "runtime-secret"
    assert config.aes_key() == "runtime-aes-key"
    assert config.session_cookie_secure() is True
    assert config.work_root(Path("unused")) == (tmp_path / "tenant-work").resolve()


def test_project_lock_config_rejects_invalid_ranges(monkeypatch):
    monkeypatch.setenv("PROJECT_LOCK_TTL_SECONDS", "inf")
    monkeypatch.setenv("PROJECT_LOCK_WAIT_SECONDS", "-1")

    assert config.project_lock_ttl_seconds() == 60
    assert config.project_lock_wait_seconds() == 10
