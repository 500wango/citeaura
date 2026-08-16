"""集中读取 CiteAura 环境变量配置。"""

import math
import os
import subprocess
from decimal import Decimal, InvalidOperation
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


def database_url():
    return os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg2://citeaura:citeaura@localhost:5432/citeaura",
    )


def redis_url():
    return os.getenv("REDIS_URL", "redis://localhost:6379/0")


def redis_socket_timeout_seconds():
    return _seconds("REDIS_SOCKET_TIMEOUT_SECONDS", 0.5, 0.1)


def _seconds(name, default, minimum):
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        return float(default)
    return value if math.isfinite(value) and value >= minimum else float(default)


def project_lock_ttl_seconds():
    return _seconds("PROJECT_LOCK_TTL_SECONDS", 60, 5)


def project_lock_wait_seconds():
    return _seconds("PROJECT_LOCK_WAIT_SECONDS", 10, 0)


def _integer(name, default, minimum=1, maximum=1_000_000):
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if minimum <= value <= maximum else default


def rate_limit_enabled():
    return _enabled("RATE_LIMIT_ENABLED", "true")


def rate_limit_requests():
    return _integer("RATE_LIMIT_REQUESTS", 120)


def rate_limit_auth_requests():
    return _integer("RATE_LIMIT_AUTH_REQUESTS", 20)


def rate_limit_window_seconds():
    return _integer("RATE_LIMIT_WINDOW_SECONDS", 60, maximum=3600)


def rate_limit_trust_proxy_headers():
    return _enabled("RATE_LIMIT_TRUST_PROXY_HEADERS")


def production_proxy_mode():
    """是否由可信生产反向代理承接公网流量。"""
    return _enabled("PRODUCTION_PROXY_MODE")


def trust_cloudflare_country_header():
    """仅在源站限制为可信 Cloudflare 流量后启用国家头。"""
    return _enabled("TRUST_CLOUDFLARE_COUNTRY_HEADER")


def celery_result_backend():
    return os.getenv("CELERY_RESULT_BACKEND", redis_url())


def jwt_secret():
    return os.getenv("JWT_SECRET")


def jwt_secret_valid(secret=None):
    """Reject missing, short, or documented placeholder JWT secrets."""
    value = (jwt_secret() if secret is None else secret) or ""
    lowered = value.lower()
    return len(value) >= 32 and not any(marker in lowered for marker in (
        "replace-with", "changeme", "example-secret",
    ))


def aes_key():
    return os.getenv("AES_KEY", "")


def session_cookie_secure():
    return os.getenv("SESSION_COOKIE_SECURE", "false").lower() in ("1", "true", "yes")


def oidc_allow_insecure_localhost():
    """仅在本地开发显式允许 OIDC 回环地址。"""
    return _enabled("OIDC_ALLOW_INSECURE_LOCALHOST")


def public_base_url():
    return os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")


def source_revision():
    """返回部署源码版本，本地运行时回退读取 Git。"""
    configured = os.getenv("CITEAURA_SOURCE_REVISION", "").strip()
    if configured and configured.lower() != "unknown":
        return configured
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            capture_output=True,
            check=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return configured or "unknown"
    revision = result.stdout.strip()
    return revision or configured or "unknown"


def work_root(default: Path):
    return Path(os.getenv("WORK_ROOT", str(default))).resolve()


def platform_pool_key(provider_key_env):
    return os.getenv(f"PLATFORM_POOL_{provider_key_env}", "").strip()


def platform_pool_prices():
    return os.getenv("PLATFORM_POOL_PRICES_CNY_FEN", "{}").strip()


def billing_annual_discount_percent():
    """返回年付折扣百分比，非法配置回退到付 10 个月。"""
    try:
        value = Decimal(os.getenv("BILLING_ANNUAL_DISCOUNT_PERCENT", "16.67"))
    except InvalidOperation:
        return Decimal("16.67")
    return value if value.is_finite() and Decimal("0") <= value < Decimal("100") else Decimal("16.67")


def billing_enabled():
    return _enabled("BILLING_ENABLED")


def stripe_secret_key():
    return os.getenv("STRIPE_SECRET_KEY", "").strip()


def stripe_webhook_secret():
    return os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()


def stripe_currency():
    value = os.getenv("STRIPE_CURRENCY", "usd").strip().lower()
    return value if value in ("cny", "usd") else "usd"


def password_reset_ttl_minutes():
    return _integer("PASSWORD_RESET_TTL_MINUTES", 30, minimum=5, maximum=1440)


def password_reset_email_enabled():
    return _enabled("PASSWORD_RESET_EMAIL_ENABLED")


def auth_smtp_settings():
    security = os.getenv("AUTH_SMTP_SECURITY", "starttls").strip().lower()
    if security not in ("starttls", "ssl"):
        security = "starttls"
    return {
        "host": os.getenv("AUTH_SMTP_HOST", "").strip(),
        "port": _integer("AUTH_SMTP_PORT", 587, maximum=65535),
        "security_mode": security,
        "username": os.getenv("AUTH_SMTP_USERNAME", "").strip(),
        "password": os.getenv("AUTH_SMTP_PASSWORD", ""),
        "from_email": os.getenv("AUTH_SMTP_FROM_EMAIL", "").strip().lower(),
        "from_name": os.getenv("AUTH_SMTP_FROM_NAME", "CiteAura").strip() or "CiteAura",
    }


def auth_smtp_configured():
    settings = auth_smtp_settings()
    credentials_valid = not settings["username"] or bool(settings["password"])
    return bool(settings["host"] and settings["from_email"] and credentials_valid)


def _enabled(name, default="false"):
    return os.getenv(name, default).lower() in ("1", "true", "yes")


def object_storage_settings():
    """返回 S3 兼容对象存储配置。"""
    try:
        retention_count = int(os.getenv("OBJECT_STORAGE_RETENTION_COUNT", "12"))
    except ValueError:
        retention_count = 12
    if not 1 <= retention_count <= 1000:
        retention_count = 12
    return {
        "bucket": os.getenv("OBJECT_STORAGE_BUCKET", "").strip(),
        "endpoint_url": os.getenv("OBJECT_STORAGE_ENDPOINT_URL", "").strip() or None,
        "region": os.getenv("OBJECT_STORAGE_REGION", "us-east-1").strip() or "us-east-1",
        "access_key_id": os.getenv("OBJECT_STORAGE_ACCESS_KEY_ID", "").strip() or None,
        "secret_access_key": os.getenv("OBJECT_STORAGE_SECRET_ACCESS_KEY", "").strip() or None,
        "prefix": os.getenv("OBJECT_STORAGE_PREFIX", "citeaura-archives").strip("/"),
        "force_path_style": _enabled("OBJECT_STORAGE_FORCE_PATH_STYLE"),
        "server_side_encryption": os.getenv("OBJECT_STORAGE_SSE", "").strip() or None,
        "retention_count": retention_count,
    }
