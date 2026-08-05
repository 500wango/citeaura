import base64

from scripts.production_preflight import read_env, validate_environment


def _valid_environment():
    return {
        "DOMAIN": "app.disvor.example",
        "DATABASE_URL": "postgresql+psycopg2://neondb_owner:secure@ep-example-pooler.us-east-2.aws.neon.tech/neondb?sslmode=require",
        "PUBLIC_BASE_URL": "https://app.disvor.example",
        "REDIS_URL": "redis://redis:6379/0",
        "JWT_SECRET": "j" * 48,
        "AES_KEY": base64.urlsafe_b64encode(b"a" * 32).decode(),
        "SESSION_COOKIE_SECURE": "true",
        "RATE_LIMIT_ENABLED": "true",
        "RATE_LIMIT_REQUESTS": "120",
        "RATE_LIMIT_AUTH_REQUESTS": "20",
        "RATE_LIMIT_WINDOW_SECONDS": "60",
        "RATE_LIMIT_TRUST_PROXY_HEADERS": "true",
        "PASSWORD_RESET_TTL_MINUTES": "30",
        "AUTH_SMTP_HOST": "smtp.example.test",
        "AUTH_SMTP_PORT": "587",
        "AUTH_SMTP_SECURITY": "starttls",
        "AUTH_SMTP_USERNAME": "accounts",
        "AUTH_SMTP_PASSWORD": "smtp-secret",
        "AUTH_SMTP_FROM_EMAIL": "accounts@disvor.example",
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
        "DATABASE_URL": "postgresql+psycopg2://neondb_owner:secure@ep-example-pooler.us-east-2.aws.neon.tech/neondb",
        "JWT_SECRET": "short",
        "AES_KEY": "invalid",
        "SESSION_COOKIE_SECURE": "false",
        "RATE_LIMIT_ENABLED": "false",
        "AUTH_SMTP_HOST": "",
        "STRIPE_SECRET_KEY": "sk_test_not_live",
    })

    errors, _warnings = validate_environment(values)

    assert "DOMAIN must be a real hostname" in errors
    assert "PUBLIC_BASE_URL must be the HTTPS URL for DOMAIN" in errors
    assert "JWT_SECRET must be a non-placeholder value of at least 32 characters" in errors
    assert "AES_KEY must be URL-safe base64 encoding of exactly 32 bytes" in errors
    assert "SESSION_COOKIE_SECURE must be true" in errors
    assert "RATE_LIMIT_ENABLED must be true" in errors
    assert "AUTH_SMTP_HOST is required" in errors
    assert "STRIPE_SECRET_KEY must be a live-mode key" in errors


def test_env_reader_never_interprets_shell_syntax(tmp_path):
    path = tmp_path / "production.env"
    path.write_text("DOMAIN=app.example.test\nJWT_SECRET='literal value'\n", "utf-8")

    assert read_env(path) == {"DOMAIN": "app.example.test", "JWT_SECRET": "literal value"}
