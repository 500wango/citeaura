"""生产依赖就绪检查。"""

from sqlalchemy import text

from api import config
from api.adapters.locking import redis_client
from api.billing import stripe as stripe_adapter
from api.settings.crypto import _master_key


EXPECTED_DB_REVISION = "0016_backfill_trial_expiration"


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
        checks["encryption"] = len(_master_key()) == 32
    except (RuntimeError, ValueError):
        checks["encryption"] = False
    checks["jwt"] = len(config.jwt_secret() or "") >= 32
    checks["https"] = config.session_cookie_secure() and config.public_base_url().startswith("https://")
    checks["stripe"] = not config.billing_enabled() or stripe_adapter.configured()
    checks["password_reset_email"] = not config.password_reset_email_enabled() or config.auth_smtp_configured()
    return {"status": "ready" if all(checks.values()) else "not_ready", "checks": checks}
