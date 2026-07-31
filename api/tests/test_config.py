from pathlib import Path

from api import config


def test_config_reads_runtime_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///test.sqlite")
    monkeypatch.setenv("REDIS_URL", "redis://example.test:6379/4")
    monkeypatch.setenv("CELERY_RESULT_BACKEND", "redis://example.test:6379/5")
    monkeypatch.setenv("JWT_SECRET", "runtime-secret")
    monkeypatch.setenv("AES_KEY", "runtime-aes-key")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "yes")
    monkeypatch.setenv("WORK_ROOT", str(tmp_path / "tenant-work"))

    assert config.database_url() == "sqlite:///test.sqlite"
    assert config.redis_url() == "redis://example.test:6379/4"
    assert config.celery_result_backend() == "redis://example.test:6379/5"
    assert config.jwt_secret() == "runtime-secret"
    assert config.aes_key() == "runtime-aes-key"
    assert config.session_cookie_secure() is True
    assert config.work_root(Path("unused")) == (tmp_path / "tenant-work").resolve()
