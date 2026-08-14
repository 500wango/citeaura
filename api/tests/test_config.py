from pathlib import Path
from decimal import Decimal

from api import config


def test_config_reads_runtime_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///test.sqlite")
    monkeypatch.setenv("REDIS_URL", "redis://example.test:6379/4")
    monkeypatch.setenv("PROJECT_LOCK_TTL_SECONDS", "90")
    monkeypatch.setenv("PROJECT_LOCK_WAIT_SECONDS", "2.5")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "yes")
    monkeypatch.setenv("RATE_LIMIT_REQUESTS", "240")
    monkeypatch.setenv("RATE_LIMIT_AUTH_REQUESTS", "12")
    monkeypatch.setenv("RATE_LIMIT_WINDOW_SECONDS", "90")
    monkeypatch.setenv("RATE_LIMIT_TRUST_PROXY_HEADERS", "true")
    monkeypatch.setenv("INTEGRATION_SYNC_COOLDOWN_SECONDS", "300")
    monkeypatch.setenv("CELERY_RESULT_BACKEND", "redis://example.test:6379/5")
    monkeypatch.setenv("JWT_SECRET", "runtime-secret")
    monkeypatch.setenv("AES_KEY", "runtime-aes-key")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "yes")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://app.example.test/")
    monkeypatch.setenv("WORK_ROOT", str(tmp_path / "tenant-work"))
    monkeypatch.setenv("BILLING_ENABLED", "true")
    monkeypatch.setenv("BILLING_ANNUAL_DISCOUNT_PERCENT", "20")
    monkeypatch.setenv("PASSWORD_RESET_EMAIL_ENABLED", "yes")
    monkeypatch.setenv("PASSWORD_RESET_TTL_MINUTES", "45")
    monkeypatch.setenv("AUTH_SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("AUTH_SMTP_PORT", "465")
    monkeypatch.setenv("AUTH_SMTP_SECURITY", "ssl")
    monkeypatch.setenv("AUTH_SMTP_USERNAME", "mailer")
    monkeypatch.setenv("AUTH_SMTP_PASSWORD", "secret")
    monkeypatch.setenv("AUTH_SMTP_FROM_EMAIL", "accounts@example.test")

    assert config.database_url() == "sqlite:///test.sqlite"
    assert config.redis_url() == "redis://example.test:6379/4"
    assert config.project_lock_ttl_seconds() == 90
    assert config.project_lock_wait_seconds() == 2.5
    assert config.rate_limit_enabled() is True
    assert config.rate_limit_requests() == 240
    assert config.rate_limit_auth_requests() == 12
    assert config.rate_limit_window_seconds() == 90
    assert config.rate_limit_trust_proxy_headers() is True
    assert config.integration_sync_cooldown_seconds() == 300
    assert config.celery_result_backend() == "redis://example.test:6379/5"
    assert config.jwt_secret() == "runtime-secret"
    assert config.aes_key() == "runtime-aes-key"
    assert config.session_cookie_secure() is True
    assert config.public_base_url() == "https://app.example.test"
    assert config.work_root(Path("unused")) == (tmp_path / "tenant-work").resolve()
    assert config.billing_enabled() is True
    assert config.billing_annual_discount_percent() == Decimal("20")
    assert config.password_reset_email_enabled() is True
    assert config.password_reset_ttl_minutes() == 45
    assert config.auth_smtp_configured() is True
    assert config.auth_smtp_settings()["security_mode"] == "ssl"


def test_project_lock_config_rejects_invalid_ranges(monkeypatch):
    monkeypatch.setenv("PROJECT_LOCK_TTL_SECONDS", "inf")
    monkeypatch.setenv("PROJECT_LOCK_WAIT_SECONDS", "-1")

    assert config.project_lock_ttl_seconds() == 60
    assert config.project_lock_wait_seconds() == 10


def test_rate_limit_config_rejects_invalid_ranges(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_REQUESTS", "0")
    monkeypatch.setenv("RATE_LIMIT_AUTH_REQUESTS", "invalid")
    monkeypatch.setenv("RATE_LIMIT_WINDOW_SECONDS", "3601")

    assert config.rate_limit_requests() == 120
    assert config.rate_limit_auth_requests() == 20
    assert config.rate_limit_window_seconds() == 60


def test_integration_sync_cooldown_rejects_invalid_ranges(monkeypatch):
    monkeypatch.setenv("INTEGRATION_SYNC_COOLDOWN_SECONDS", "-1")
    assert config.integration_sync_cooldown_seconds() == 900
    monkeypatch.setenv("INTEGRATION_SYNC_COOLDOWN_SECONDS", "0")
    assert config.integration_sync_cooldown_seconds() == 0


def test_annual_discount_config_rejects_invalid_ranges(monkeypatch):
    monkeypatch.setenv("BILLING_ANNUAL_DISCOUNT_PERCENT", "100")
    assert config.billing_annual_discount_percent() == Decimal("16.67")
    monkeypatch.setenv("BILLING_ANNUAL_DISCOUNT_PERCENT", "invalid")
    assert config.billing_annual_discount_percent() == Decimal("16.67")
    monkeypatch.setenv("BILLING_ANNUAL_DISCOUNT_PERCENT", "NaN")
    assert config.billing_annual_discount_percent() == Decimal("16.67")


def test_object_storage_config_is_runtime_and_bounds_retention(monkeypatch):
    monkeypatch.setenv("OBJECT_STORAGE_BUCKET", "snapshots")
    monkeypatch.setenv("OBJECT_STORAGE_ENDPOINT_URL", "https://objects.example.test")
    monkeypatch.setenv("OBJECT_STORAGE_FORCE_PATH_STYLE", "yes")
    monkeypatch.setenv("OBJECT_STORAGE_RETENTION_COUNT", "0")
    value = config.object_storage_settings()
    assert value["bucket"] == "snapshots"
    assert value["endpoint_url"] == "https://objects.example.test"
    assert value["force_path_style"] is True
    assert value["retention_count"] == 12
