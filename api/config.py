"""集中读取 DisvorAI 环境变量配置。"""

import math
import os
from decimal import Decimal, InvalidOperation
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


def database_url():
    return os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg2://disvorai:disvorai@localhost:5432/disvorai",
    )


def redis_url():
    return os.getenv("REDIS_URL", "redis://localhost:6379/0")


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


def celery_result_backend():
    return os.getenv("CELERY_RESULT_BACKEND", redis_url())


def jwt_secret():
    return os.getenv("JWT_SECRET")


def aes_key():
    return os.getenv("AES_KEY", "")


def session_cookie_secure():
    return os.getenv("SESSION_COOKIE_SECURE", "false").lower() in ("1", "true", "yes")


def public_base_url():
    return os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")


def google_oauth_client_id():
    return os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()


def google_oauth_client_secret():
    return os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()


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
        "prefix": os.getenv("OBJECT_STORAGE_PREFIX", "disvorai-archives").strip("/"),
        "force_path_style": _enabled("OBJECT_STORAGE_FORCE_PATH_STYLE"),
        "server_side_encryption": os.getenv("OBJECT_STORAGE_SSE", "").strip() or None,
        "retention_count": retention_count,
    }
