"""生产依赖就绪检查。"""

from sqlalchemy import text

from api import config
from api.adapters.locking import redis_client
from api.billing import stripe as stripe_adapter
from api.settings.crypto import _master_key
from api.worker.celery_app import celery_app


EXPECTED_DB_REVISION = "0027_daily_monitoring"


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
        checks["migrations"] = revision == EXPECTED_DB_REVISION
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
    return {"status": "ready" if all(checks.values()) else "not_ready", "checks": checks}
