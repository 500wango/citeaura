"""生产依赖就绪检查。"""

from functools import lru_cache
from pathlib import Path

from sqlalchemy import text

from api import config
from api.adapters.locking import redis_client
from api.billing import stripe as stripe_adapter
from api.settings.crypto import _master_key
from api.worker.celery_app import celery_app


REQUIRED_CHECKS = (
    "database",
    "migrations",
    "redis",
    "encryption",
    "jwt",
    "https",
    "rate_limit_proxy_headers",
    "stripe",
    "password_reset_email",
)


@lru_cache(maxsize=1)
def expected_db_revision():
    """从迁移目录读取 head，避免新增迁移后忘记同步硬编码版本号。"""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    root = Path(__file__).resolve().parents[1]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "api" / "migrations"))
    return ScriptDirectory.from_config(cfg).get_current_head()


def _worker_available():
    """确认至少一个 Celery Worker 能响应任务控制请求。"""
    replies = celery_app.control.inspect(timeout=0.5).ping()
    return bool(replies and any(reply.get("ok") == "pong" for reply in replies.values()))


def readiness_checks(db):
    """检查请求处理、任务锁、迁移和支付所需依赖。"""
    checks = {}
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception:  # noqa: BLE001 - 就绪端点需要汇总依赖状态
        checks["database"] = False
    try:
        revision = db.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        checks["migrations"] = revision == expected_db_revision()
    except Exception:  # noqa: BLE001 - 未迁移数据库应返回未就绪
        checks["migrations"] = False
    try:
        checks["redis"] = bool(redis_client().ping())
    except Exception:  # noqa: BLE001 - Redis 不可用应返回未就绪
        checks["redis"] = False
    try:
        checks["worker"] = _worker_available()
    except Exception:  # noqa: BLE001 - Worker 或 broker 不可用应返回未就绪
        checks["worker"] = False
    try:
        checks["encryption"] = len(_master_key()) == 32
    except (RuntimeError, ValueError):
        checks["encryption"] = False
    checks["jwt"] = config.jwt_secret_valid()
    checks["https"] = config.session_cookie_secure() and config.public_base_url().startswith("https://")
    checks["rate_limit_proxy_headers"] = (
        not config.production_proxy_mode()
        or not config.rate_limit_enabled()
        or config.rate_limit_trust_proxy_headers()
    )
    checks["stripe"] = not config.billing_enabled() or stripe_adapter.configured()
    checks["password_reset_email"] = not config.password_reset_email_enabled() or config.auth_smtp_configured()
    # worker 状态只作为观测项：API 的容器健康不应与某个 worker 副本绑定，
    # 否则一次 worker 重启就会让 API 被判 unhealthy 并阻断部署。
    ready = all(checks.get(name) for name in REQUIRED_CHECKS)
    return {"status": "ready" if ready else "not_ready", "checks": checks}
