"""集中读取 DisvorAI 环境变量配置。"""

import math
import os
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


def work_root(default: Path):
    return Path(os.getenv("WORK_ROOT", str(default))).resolve()


def platform_pool_key(provider_key_env):
    return os.getenv(f"PLATFORM_POOL_{provider_key_env}", "").strip()


def platform_pool_prices():
    return os.getenv("PLATFORM_POOL_PRICES_CNY_FEN", "{}").strip()
