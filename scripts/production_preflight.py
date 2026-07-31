#!/usr/bin/env python3
"""在启动生产 Compose 前验证环境和 TLS 证书。"""

import argparse
import base64
import json
import re
import ssl
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse


PLACEHOLDERS = ("replace-with", "example.com", "changeme")
PLATFORM_KEYS = (
    "ZHIPUAI_API_KEY", "ARK_API_KEY", "DEEPSEEK_API_KEY", "MOONSHOT_API_KEY",
    "MINIMAX_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
    "XAI_API_KEY", "PERPLEXITY_API_KEY",
)


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


def _placeholder(value):
    lowered = value.lower()
    return any(item in lowered for item in PLACEHOLDERS)


def validate_environment(values):
    errors = []
    warnings = []
    required = (
        "DOMAIN", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD", "DATABASE_URL",
        "PUBLIC_BASE_URL", "REDIS_URL", "JWT_SECRET", "AES_KEY", "SESSION_COOKIE_SECURE",
        "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "STRIPE_CURRENCY",
    )
    for key in required:
        if not values.get(key):
            errors.append(f"{key} is required")
    domain = values.get("DOMAIN", "")
    if domain and (not re.fullmatch(r"[A-Za-z0-9.-]+", domain) or "." not in domain or _placeholder(domain)):
        errors.append("DOMAIN must be a real hostname")
    public_url = values.get("PUBLIC_BASE_URL", "")
    parsed = urlparse(public_url)
    if public_url and (parsed.scheme != "https" or parsed.hostname != domain or parsed.path not in ("", "/")):
        errors.append("PUBLIC_BASE_URL must be the HTTPS URL for DOMAIN")
    database_url = values.get("DATABASE_URL", "")
    if database_url and (not database_url.startswith("postgresql+") or _placeholder(database_url)):
        errors.append("DATABASE_URL must use PostgreSQL and contain production credentials")
    if _placeholder(values.get("POSTGRES_PASSWORD", "")):
        errors.append("POSTGRES_PASSWORD still contains a placeholder")
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
    stripe_key = values.get("STRIPE_SECRET_KEY", "")
    if stripe_key and not stripe_key.startswith("sk_live_"):
        errors.append("STRIPE_SECRET_KEY must be a live-mode key")
    webhook_secret = values.get("STRIPE_WEBHOOK_SECRET", "")
    if webhook_secret and not webhook_secret.startswith("whsec_"):
        errors.append("STRIPE_WEBHOOK_SECRET has an invalid format")
    if values.get("STRIPE_CURRENCY", "").lower() not in ("cny", "usd"):
        errors.append("STRIPE_CURRENCY must be cny or usd")
    google_values = (values.get("GOOGLE_OAUTH_CLIENT_ID"), values.get("GOOGLE_OAUTH_CLIENT_SECRET"))
    if any(google_values) and not all(google_values):
        errors.append("GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET must be configured together")
    if not all(google_values):
        warnings.append("Search Console OAuth is disabled until Google credentials are configured")
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
    warnings.append("Semrush, SMTP, and OIDC credentials are tenant-managed and require in-app connection tests")
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
        decoded = ssl._ssl._test_decode_cert(str(certificate))  # noqa: SLF001 - 标准库无公开 PEM 解析入口
        ssl.match_hostname(decoded, domain)
    except (ValueError, ssl.CertificateError, ssl.SSLError):
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
    parser.add_argument("--skip-certificate", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        values = read_env(args.env_file)
    except (OSError, ValueError) as exc:
        result = {"ready": False, "errors": [str(exc)], "warnings": []}
    else:
        errors, warnings = validate_environment(values)
        if not args.skip_certificate:
            errors.extend(validate_certificate(args.cert_dir, values.get("DOMAIN", "")))
        result = {"ready": not errors, "errors": errors, "warnings": warnings}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for warning in result["warnings"]:
            print(f"WARN: {warning}")
        for error in result["errors"]:
            print(f"ERROR: {error}", file=sys.stderr)
        print("Production preflight passed." if result["ready"] else "Production preflight failed.")
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
