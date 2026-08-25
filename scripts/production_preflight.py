#!/usr/bin/env python3
"""在启动生产 Compose 前验证环境和 TLS 证书。"""

import argparse
import base64
import ipaddress
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse


PLACEHOLDERS = ("replace-with", "example.com", "changeme")
TRUE_VALUES = ("1", "true", "yes")
FALSE_VALUES = ("0", "false", "no")
PLATFORM_KEYS = (
    "ZHIPUAI_API_KEY", "ARK_API_KEY", "DEEPSEEK_API_KEY", "MOONSHOT_API_KEY",
    "MINIMAX_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
    "XAI_API_KEY", "PERPLEXITY_API_KEY",
)
LEGACY_ENV_DEFAULTS = {"FORWARDED_ALLOW_IPS": "127.0.0.1"}
LOCAL_POSTGRES_HOSTS = {"postgres"}


def read_env(path):
    values = {}
    for number, raw_line in enumerate(path.read_text("utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"line {number} is not KEY=VALUE")
        key, value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise ValueError(f"line {number} has an invalid key")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        values[key] = value
    return values


def ensure_legacy_environment_defaults(path):
    """Add non-secret defaults required by newer production deployments."""
    text = path.read_text("utf-8")
    values = read_env(path)
    missing = [key for key in LEGACY_ENV_DEFAULTS if key not in values]
    if not missing:
        return []
    suffix = "" if text.endswith("\n") else "\n"
    suffix += "\n# Added by CiteAura deployment migration.\n"
    suffix += "".join(f"{key}={LEGACY_ENV_DEFAULTS[key]}\n" for key in missing)
    path.write_text(text + suffix, encoding="utf-8")
    return missing


def _placeholder(value):
    lowered = value.lower()
    return any(item in lowered for item in PLACEHOLDERS)


def _feature_flag(values, key, errors):
    value = values.get(key, "").strip().lower()
    if not value:
        errors.append(f"{key} is required")
        return False
    if value not in TRUE_VALUES + FALSE_VALUES:
        errors.append(f"{key} must be true or false")
        return False
    return value in TRUE_VALUES


def _database_target(database_url):
    parsed = urlparse(database_url)
    return parsed, (parsed.hostname or "").lower()


def validate_environment(values):
    errors = []
    warnings = []
    required = (
        "DOMAIN", "DATABASE_URL",
        "PUBLIC_BASE_URL", "REDIS_URL", "REDIS_PASSWORD", "JWT_SECRET", "AES_KEY", "SESSION_COOKIE_SECURE",
        "RATE_LIMIT_ENABLED", "RATE_LIMIT_REQUESTS", "RATE_LIMIT_AUTH_REQUESTS",
        "RATE_LIMIT_WINDOW_SECONDS", "RATE_LIMIT_TRUST_PROXY_HEADERS",
        "PRODUCTION_PROXY_MODE", "TRUST_CLOUDFLARE_COUNTRY_HEADER", "FORWARDED_ALLOW_IPS",
    )
    for key in required:
        if not values.get(key):
            errors.append(f"{key} is required")
    billing_enabled = _feature_flag(values, "BILLING_ENABLED", errors)
    password_reset_email_enabled = _feature_flag(values, "PASSWORD_RESET_EMAIL_ENABLED", errors)
    production_proxy_mode = _feature_flag(values, "PRODUCTION_PROXY_MODE", errors)
    _feature_flag(values, "TRUST_CLOUDFLARE_COUNTRY_HEADER", errors)
    domain = values.get("DOMAIN", "")
    if domain and (not re.fullmatch(r"[A-Za-z0-9.-]+", domain) or "." not in domain or _placeholder(domain)):
        errors.append("DOMAIN must be a real hostname")
    public_url = values.get("PUBLIC_BASE_URL", "")
    parsed = urlparse(public_url)
    if public_url and (parsed.scheme != "https" or parsed.hostname != domain or parsed.path not in ("", "/")):
        errors.append("PUBLIC_BASE_URL must be the HTTPS URL for DOMAIN")
    database_url = values.get("DATABASE_URL", "")
    if database_url and (not database_url.startswith("postgresql+psycopg2://") or _placeholder(database_url)):
        errors.append("DATABASE_URL must use postgresql+psycopg2 and contain production credentials")
    if database_url:
        parsed_database, database_host = _database_target(database_url)
        if not parsed_database.hostname:
            errors.append("DATABASE_URL must include a database hostname")
        query = {key.lower(): value.lower() for key, value in (item.split("=", 1) for item in parsed_database.query.split("&") if "=" in item)}
        sslmode = query.get("sslmode", "")
        if database_host in LOCAL_POSTGRES_HOSTS:
            postgres_db = values.get("POSTGRES_DB", "citeaura")
            postgres_user = values.get("POSTGRES_USER", "citeaura")
            postgres_password = values.get("POSTGRES_PASSWORD", "")
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", postgres_db):
                errors.append("POSTGRES_DB must be a valid PostgreSQL identifier")
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", postgres_user):
                errors.append("POSTGRES_USER must be a valid PostgreSQL identifier")
            if not postgres_password or len(postgres_password) < 24 or _placeholder(postgres_password):
                errors.append("POSTGRES_PASSWORD must be a non-placeholder value of at least 24 characters")
            if unquote(parsed_database.username or "") != postgres_user:
                errors.append("DATABASE_URL user must match POSTGRES_USER for local PostgreSQL")
            if unquote(parsed_database.path.lstrip("/") or "") != postgres_db:
                errors.append("DATABASE_URL database must match POSTGRES_DB for local PostgreSQL")
            if unquote(parsed_database.password or "") != postgres_password:
                errors.append("DATABASE_URL password must match POSTGRES_PASSWORD for local PostgreSQL")
            if sslmode and sslmode not in ("disable", "prefer"):
                errors.append("DATABASE_URL sslmode must be disable or prefer for local PostgreSQL")
        elif sslmode not in ("require", "verify-ca", "verify-full"):
            errors.append("DATABASE_URL must require TLS for an external PostgreSQL server")
    redis_url = urlparse(values.get("REDIS_URL", ""))
    redis_password = values.get("REDIS_PASSWORD", "")
    if not redis_password or len(redis_password) < 24 or _placeholder(redis_password):
        errors.append("REDIS_PASSWORD must be a non-placeholder value of at least 24 characters")
    if values.get("REDIS_URL") and (redis_url.scheme not in ("redis", "rediss") or unquote(redis_url.password or "") != redis_password):
        errors.append("REDIS_URL must include REDIS_PASSWORD")
    jwt_secret = values.get("JWT_SECRET", "")
    if jwt_secret and (len(jwt_secret) < 32 or _placeholder(jwt_secret)):
        errors.append("JWT_SECRET must be a non-placeholder value of at least 32 characters")
    aes_key = values.get("AES_KEY", "")
    if aes_key:
        try:
            decoded = base64.urlsafe_b64decode(aes_key.encode("ascii"))
        except (ValueError, UnicodeError):
            decoded = b""
        if len(decoded) != 32 or _placeholder(aes_key):
            errors.append("AES_KEY must be URL-safe base64 encoding of exactly 32 bytes")
    if values.get("SESSION_COOKIE_SECURE", "").lower() not in ("1", "true", "yes"):
        errors.append("SESSION_COOKIE_SECURE must be true")
    if values.get("RATE_LIMIT_ENABLED", "").lower() not in ("1", "true", "yes"):
        errors.append("RATE_LIMIT_ENABLED must be true")
    if values.get("RATE_LIMIT_TRUST_PROXY_HEADERS", "").lower() not in ("1", "true", "yes"):
        errors.append("RATE_LIMIT_TRUST_PROXY_HEADERS must be true behind the production proxy")
    forwarded_allow_ips = values.get("FORWARDED_ALLOW_IPS", "").strip()
    if not forwarded_allow_ips or forwarded_allow_ips == "*" or "*" in forwarded_allow_ips:
        errors.append("FORWARDED_ALLOW_IPS must list explicit trusted proxy IPs or CIDRs")
    else:
        for entry in forwarded_allow_ips.split(","):
            try:
                ipaddress.ip_network(entry.strip(), strict=False)
            except ValueError:
                errors.append("FORWARDED_ALLOW_IPS must contain only valid IPs or CIDRs")
                break
    if not production_proxy_mode:
        errors.append("PRODUCTION_PROXY_MODE must be true for the production proxy deployment")
    for key, maximum in (("RATE_LIMIT_REQUESTS", 1_000_000), ("RATE_LIMIT_AUTH_REQUESTS", 1_000_000), ("RATE_LIMIT_WINDOW_SECONDS", 3600)):
        try:
            number = int(values.get(key, ""))
        except ValueError:
            number = 0
        if not 1 <= number <= maximum:
            errors.append(f"{key} must be an integer between 1 and {maximum}")
    if password_reset_email_enabled:
        required_email = (
            "PASSWORD_RESET_TTL_MINUTES", "AUTH_SMTP_HOST", "AUTH_SMTP_PORT",
            "AUTH_SMTP_SECURITY", "AUTH_SMTP_FROM_EMAIL",
        )
        for key in required_email:
            if not values.get(key):
                errors.append(f"{key} is required")
        try:
            reset_ttl = int(values.get("PASSWORD_RESET_TTL_MINUTES", ""))
        except ValueError:
            reset_ttl = 0
        if not 5 <= reset_ttl <= 1440:
            errors.append("PASSWORD_RESET_TTL_MINUTES must be an integer between 5 and 1440")
    else:
        warnings.append("Password reset email is disabled by PASSWORD_RESET_EMAIL_ENABLED=false")
    smtp_configured = any(
        values.get(key, "")
        for key in ("AUTH_SMTP_HOST", "AUTH_SMTP_USERNAME", "AUTH_SMTP_PASSWORD", "AUTH_SMTP_FROM_EMAIL")
    )
    if password_reset_email_enabled or smtp_configured:
        if values.get("AUTH_SMTP_SECURITY", "").lower() not in ("starttls", "ssl"):
            errors.append("AUTH_SMTP_SECURITY must be starttls or ssl")
        try:
            smtp_port = int(values.get("AUTH_SMTP_PORT", ""))
        except ValueError:
            smtp_port = 0
        if not 1 <= smtp_port <= 65535:
            errors.append("AUTH_SMTP_PORT must be an integer between 1 and 65535")
        elif smtp_port == 465 and values.get("AUTH_SMTP_SECURITY", "").lower() != "ssl":
            errors.append("AUTH_SMTP_PORT=465 requires AUTH_SMTP_SECURITY=ssl")
        elif smtp_port != 465 and values.get("AUTH_SMTP_SECURITY", "").lower() == "ssl":
            errors.append("AUTH_SMTP_SECURITY=ssl requires AUTH_SMTP_PORT=465")
        smtp_username = values.get("AUTH_SMTP_USERNAME", "")
        smtp_password = values.get("AUTH_SMTP_PASSWORD", "")
        if bool(smtp_username) != bool(smtp_password):
            errors.append("AUTH_SMTP_USERNAME and AUTH_SMTP_PASSWORD must be configured together")
        from_email = values.get("AUTH_SMTP_FROM_EMAIL", "")
        if from_email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", from_email):
            errors.append("AUTH_SMTP_FROM_EMAIL must be a valid email address")
    if billing_enabled:
        for key in ("STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "STRIPE_CURRENCY"):
            if not values.get(key):
                errors.append(f"{key} is required")
        stripe_key = values.get("STRIPE_SECRET_KEY", "")
        if stripe_key and not stripe_key.startswith("sk_live_"):
            errors.append("STRIPE_SECRET_KEY must be a live-mode key")
        webhook_secret = values.get("STRIPE_WEBHOOK_SECRET", "")
        if webhook_secret and not webhook_secret.startswith("whsec_"):
            errors.append("STRIPE_WEBHOOK_SECRET has an invalid format")
        if values.get("STRIPE_CURRENCY", "").lower() != "usd":
            errors.append("STRIPE_CURRENCY must be usd")
    else:
        warnings.append("Billing is disabled by BILLING_ENABLED=false")
    bucket = values.get("OBJECT_STORAGE_BUCKET", "")
    endpoint = values.get("OBJECT_STORAGE_ENDPOINT_URL", "")
    if endpoint and not bucket:
        errors.append("OBJECT_STORAGE_BUCKET is required when OBJECT_STORAGE_ENDPOINT_URL is set")
    if endpoint and not (values.get("OBJECT_STORAGE_ACCESS_KEY_ID") and values.get("OBJECT_STORAGE_SECRET_ACCESS_KEY")):
        errors.append("S3-compatible storage endpoint requires access credentials")
    if not bucket:
        warnings.append("Object storage archive is disabled until a bucket is configured")
    if not any(values.get(f"PLATFORM_POOL_{key}") for key in PLATFORM_KEYS):
        warnings.append("Platform-funded sampling is disabled until at least one platform key is configured")
    for key in ("GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET", "INTEGRATION_SYNC_COOLDOWN_SECONDS"):
        if values.get(key):
            warnings.append(f"{key} is no longer used and should be removed")
    warnings.append("Outreach SMTP and OIDC credentials are tenant-managed and require in-app connection tests")
    return errors, warnings


def validate_certificate(cert_dir, domain):
    errors = []
    certificate = cert_dir / "fullchain.pem"
    private_key = cert_dir / "privkey.pem"
    if not certificate.is_file() or not private_key.is_file():
        return ["deploy/certs/fullchain.pem and privkey.pem are required"]
    try:
        subprocess.run(
            ["openssl", "x509", "-checkend", "604800", "-noout", "-in", str(certificate)],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        errors.append("TLS certificate is invalid or expires within 7 days")
    try:
        subprocess.run(
            ["openssl", "x509", "-checkhost", domain, "-noout", "-in", str(certificate)],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        errors.append("TLS certificate does not cover DOMAIN")
    try:
        cert_public = subprocess.run(
            ["openssl", "x509", "-pubkey", "-noout", "-in", str(certificate)],
            check=True,
            capture_output=True,
        ).stdout
        key_public = subprocess.run(
            ["openssl", "pkey", "-pubout", "-in", str(private_key)],
            check=True,
            capture_output=True,
        ).stdout
        if cert_public != key_public:
            errors.append("TLS certificate and private key do not match")
    except (OSError, subprocess.CalledProcessError):
        errors.append("TLS private key is invalid")
    return errors


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, default=Path(".env.production"))
    parser.add_argument("--cert-dir", type=Path, default=Path("deploy/certs"))
    parser.add_argument("--tls-mode", choices=("local", "external"), default="local")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--migrate-legacy",
        action="store_true",
        help="Add safe non-secret defaults missing from older production env files",
    )
    args = parser.parse_args(argv)
    migrated = []
    try:
        if args.migrate_legacy:
            migrated = ensure_legacy_environment_defaults(args.env_file)
        values = read_env(args.env_file)
    except (OSError, ValueError) as exc:
        result = {"ready": False, "errors": [str(exc)], "warnings": [], "migrated": migrated}
    else:
        errors, warnings = validate_environment(values)
        if args.tls_mode == "local":
            errors.extend(validate_certificate(args.cert_dir, values.get("DOMAIN", "")))
        else:
            warnings.append("TLS certificate validation is delegated to the external Caddy or CDN endpoint")
        result = {"ready": not errors, "errors": errors, "warnings": warnings, "migrated": migrated}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for key in result["migrated"]:
            print(f"INFO: added legacy production default {key}")
        for warning in result["warnings"]:
            print(f"WARN: {warning}")
        for error in result["errors"]:
            print(f"ERROR: {error}", file=sys.stderr)
        print("Production preflight passed." if result["ready"] else "Production preflight failed.")
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
