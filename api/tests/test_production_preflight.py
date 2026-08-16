import base64

from scripts.production_preflight import read_env, validate_environment


def _valid_environment():
    return {
        "DOMAIN": "app.citeaura.example",
        "DATABASE_URL": "postgresql+psycopg2://neondb_owner:secure@ep-example-pooler.us-east-2.aws.neon.tech/neondb?sslmode=require",
        "PUBLIC_BASE_URL": "https://app.citeaura.example",
        "REDIS_URL": "redis://:" + "r" * 32 + "@redis:6379/0",
        "REDIS_PASSWORD": "r" * 32,
        "JWT_SECRET": "j" * 48,
        "AES_KEY": base64.urlsafe_b64encode(b"a" * 32).decode(),
        "SESSION_COOKIE_SECURE": "true",
        "RATE_LIMIT_ENABLED": "true",
        "RATE_LIMIT_REQUESTS": "120",
        "RATE_LIMIT_AUTH_REQUESTS": "20",
        "RATE_LIMIT_WINDOW_SECONDS": "60",
        "RATE_LIMIT_TRUST_PROXY_HEADERS": "true",
        "PRODUCTION_PROXY_MODE": "true",
        "TRUST_CLOUDFLARE_COUNTRY_HEADER": "true",
        "BILLING_ENABLED": "true",
        "PASSWORD_RESET_TTL_MINUTES": "30",
        "PASSWORD_RESET_EMAIL_ENABLED": "true",
        "AUTH_SMTP_HOST": "smtp.example.test",
        "AUTH_SMTP_PORT": "587",
        "AUTH_SMTP_SECURITY": "starttls",
        "AUTH_SMTP_USERNAME": "accounts",
        "AUTH_SMTP_PASSWORD": "smtp-secret",
        "AUTH_SMTP_FROM_EMAIL": "accounts@citeaura.example",
        "STRIPE_SECRET_KEY": "sk_live_valid",
        "STRIPE_WEBHOOK_SECRET": "whsec_valid",
        "STRIPE_CURRENCY": "usd",
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


def test_preflight_allows_disabled_billing_and_password_reset_email():
    values = _valid_environment()
    values.update({
        "BILLING_ENABLED": "false",
        "STRIPE_SECRET_KEY": "",
        "STRIPE_WEBHOOK_SECRET": "",
        "STRIPE_CURRENCY": "",
        "PASSWORD_RESET_EMAIL_ENABLED": "false",
        "PASSWORD_RESET_TTL_MINUTES": "",
        "AUTH_SMTP_HOST": "",
        "AUTH_SMTP_PORT": "",
        "AUTH_SMTP_SECURITY": "",
        "AUTH_SMTP_USERNAME": "",
        "AUTH_SMTP_PASSWORD": "",
        "AUTH_SMTP_FROM_EMAIL": "",
    })

    errors, warnings = validate_environment(values)

    assert errors == []
    assert "Billing is disabled by BILLING_ENABLED=false" in warnings
    assert "Password reset email is disabled by PASSWORD_RESET_EMAIL_ENABLED=false" in warnings


def test_preflight_warns_about_removed_seo_integration_settings():
    values = _valid_environment()
    values["GOOGLE_OAUTH_CLIENT_ID"] = "unused-client"
    values["GOOGLE_OAUTH_CLIENT_SECRET"] = "unused-secret"
    values["INTEGRATION_SYNC_COOLDOWN_SECONDS"] = "900"

    errors, warnings = validate_environment(values)

    assert errors == []
    assert "GOOGLE_OAUTH_CLIENT_ID is no longer used and should be removed" in warnings
    assert "GOOGLE_OAUTH_CLIENT_SECRET is no longer used and should be removed" in warnings
    assert "INTEGRATION_SYNC_COOLDOWN_SECONDS is no longer used and should be removed" in warnings


def test_preflight_requires_explicit_valid_feature_flags():
    values = _valid_environment()
    values["BILLING_ENABLED"] = "sometimes"
    values.pop("PASSWORD_RESET_EMAIL_ENABLED")

    errors, _warnings = validate_environment(values)

    assert "BILLING_ENABLED must be true or false" in errors
    assert "PASSWORD_RESET_EMAIL_ENABLED is required" in errors


def test_env_reader_never_interprets_shell_syntax(tmp_path):
    path = tmp_path / "production.env"
    path.write_text("DOMAIN=app.example.test\nJWT_SECRET='literal value'\n", "utf-8")

    assert read_env(path) == {"DOMAIN": "app.example.test", "JWT_SECRET": "literal value"}
