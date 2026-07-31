import base64

from scripts.production_preflight import read_env, validate_environment


def _valid_environment():
    return {
        "DOMAIN": "app.disvor.example",
        "POSTGRES_DB": "disvorai",
        "POSTGRES_USER": "disvorai",
        "POSTGRES_PASSWORD": "a-long-production-database-password",
        "DATABASE_URL": "postgresql+psycopg2://disvorai:secure@postgres:5432/disvorai",
        "PUBLIC_BASE_URL": "https://app.disvor.example",
        "REDIS_URL": "redis://redis:6379/0",
        "JWT_SECRET": "j" * 48,
        "AES_KEY": base64.urlsafe_b64encode(b"a" * 32).decode(),
        "SESSION_COOKIE_SECURE": "true",
        "STRIPE_SECRET_KEY": "sk_live_valid",
        "STRIPE_WEBHOOK_SECRET": "whsec_valid",
        "STRIPE_CURRENCY": "cny",
        "GOOGLE_OAUTH_CLIENT_ID": "google-client",
        "GOOGLE_OAUTH_CLIENT_SECRET": "google-secret",
        "OBJECT_STORAGE_BUCKET": "archives",
    }


def test_valid_production_environment_passes_with_optional_warnings():
    errors, warnings = validate_environment(_valid_environment())

    assert errors == []
    assert any("Platform-funded" in warning for warning in warnings)
    assert any("tenant-managed" in warning for warning in warnings)


def test_preflight_rejects_placeholders_insecure_url_and_test_payments():
    values = _valid_environment()
    values.update({
        "DOMAIN": "example.com",
        "PUBLIC_BASE_URL": "http://example.com",
        "JWT_SECRET": "short",
        "AES_KEY": "invalid",
        "SESSION_COOKIE_SECURE": "false",
        "STRIPE_SECRET_KEY": "sk_test_not_live",
    })

    errors, _warnings = validate_environment(values)

    assert "DOMAIN must be a real hostname" in errors
    assert "PUBLIC_BASE_URL must be the HTTPS URL for DOMAIN" in errors
    assert "JWT_SECRET must be a non-placeholder value of at least 32 characters" in errors
    assert "AES_KEY must be URL-safe base64 encoding of exactly 32 bytes" in errors
    assert "SESSION_COOKIE_SECURE must be true" in errors
    assert "STRIPE_SECRET_KEY must be a live-mode key" in errors


def test_env_reader_never_interprets_shell_syntax(tmp_path):
    path = tmp_path / "production.env"
    path.write_text("DOMAIN=app.example.test\nJWT_SECRET='literal value'\n", "utf-8")

    assert read_env(path) == {"DOMAIN": "app.example.test", "JWT_SECRET": "literal value"}
