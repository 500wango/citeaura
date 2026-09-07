"""订阅本地授权状态。"""

from datetime import datetime, timezone

from api.models import Subscription, Tenant


CURRENT_STATUSES = frozenset(("active", "trialing", "past_due"))
EXPIRED_PLAN = "expired"
TRIAL_PRESERVING_SUBSCRIPTION_STATUSES = frozenset(("pending", "incomplete"))


def as_utc(value):
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def subscription_is_current(subscription, now=None):
    """只有状态有效且未超过 Stripe 当前周期的订阅才授予套餐能力。"""
    if subscription is None or subscription.status not in CURRENT_STATUSES:
        return False
    expires_at = as_utc(subscription.expires_at)
    if expires_at is None:
        started_at = as_utc(subscription.started_at)
        if started_at is None:
            return False
        months = 12 if subscription.billing_interval == "annual" else 1
        month_index = started_at.month - 1 + months
        year = started_at.year + month_index // 12
        month = month_index % 12 + 1
        import calendar
        day = min(started_at.day, calendar.monthrange(year, month)[1])
        expires_at = started_at.replace(year=year, month=month, day=day)
    return expires_at is not None and expires_at > (now or datetime.now(timezone.utc))


def _tenant_subscriptions(db, tenant_id):
    return db.query(Subscription).filter(
        Subscription.tenant_id == tenant_id,
    ).order_by(Subscription.started_at.desc(), Subscription.id.desc()).all()


def _subscription_lifecycle_started(rows):
    """未完成的 Checkout 不消耗首次试用资格。"""
    return any(
        row.status not in TRIAL_PRESERVING_SUBSCRIPTION_STATUSES
        for row in rows
    )


def effective_tenant_plan(db, tenant_id, now=None):
    """计算当前授权套餐，不修改 SQLAlchemy 实体或提交事务。"""
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        return None
    rows = _tenant_subscriptions(db, tenant_id)
    active = next((row for row in rows if subscription_is_current(row, now)), None)
    if active is not None:
        return active.plan
    if _subscription_lifecycle_started(rows):
        return EXPIRED_PLAN
    return tenant.plan


def sync_tenant_plan(db, tenant_id, now=None):
    """按本地到期时间同步租户套餐，不依赖 webhook 是否按时抵达。"""
    now = now or datetime.now(timezone.utc)
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        return None
    rows = _tenant_subscriptions(db, tenant_id)
    active = next((row for row in rows if subscription_is_current(row, now)), None)
    if active is not None:
        tenant.plan = active.plan
        return active
    if _subscription_lifecycle_started(rows):
        tenant.plan = EXPIRED_PLAN
    return None
