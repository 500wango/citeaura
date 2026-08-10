"""计费、套餐和用量 API。"""

import calendar
import hashlib
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api import config
from api.auth.deps import get_current_user, require_owner
from api.billing.limits import usage
from api.billing.plans import PLANS, SUBSCRIBABLE_PLANS
from api.billing.platform_pool import PAID_PLANS, public_catalog, usage_summary
from api.billing import stripe as stripe_adapter
from api.db import get_db
from api.models import BillingEvent, Subscription, Tenant, User


router = APIRouter(prefix="/api/v1/billing", tags=["billing"])


def _require_billing_enabled():
    if not config.billing_enabled():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "billing_disabled"},
        )


class SubscribePayload(BaseModel):
    plan: str
    billing_interval: str = "monthly"

    @field_validator("plan")
    @classmethod
    def validate_plan(cls, value: str):
        value = value.strip().lower()
        if value not in SUBSCRIBABLE_PLANS:
            raise ValueError("unsupported plan")
        return value

    @field_validator("billing_interval")
    @classmethod
    def validate_billing_interval(cls, value: str):
        value = value.strip().lower()
        if value not in ("monthly", "annual"):
            raise ValueError("unsupported billing interval")
        return value


def _annual_price(monthly_price, discount):
    if monthly_price is None:
        return None
    total = Decimal(monthly_price) * 12 * (Decimal("100") - discount) / Decimal("100")
    return int(total.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _catalog():
    discount = config.billing_annual_discount_percent()
    plans = []
    for code, details in PLANS.items():
        if code == "trial":
            continue
        monthly_cny = details["monthly_cny"]
        monthly_usd = details["monthly_usd"]
        annual_cny = _annual_price(monthly_cny, discount)
        annual_usd = _annual_price(monthly_usd, discount)
        plans.append({
            "code": code,
            "name": details["name"],
            "price_cny": monthly_cny,
            "price_usd": monthly_usd,
            "projects": details["projects"],
            "sample_runs": details["sample_runs"],
            "prices": {
                "monthly": {"cny": monthly_cny, "usd": monthly_usd, "months": 1},
                "annual": {"cny": annual_cny, "usd": annual_usd, "months": 12},
            },
            "annual_discount_percent": float(discount) if monthly_cny is not None else None,
            "annual_savings_cny": monthly_cny * 12 - annual_cny if monthly_cny is not None else None,
            "annual_savings_usd": monthly_usd * 12 - annual_usd if monthly_usd is not None else None,
        })
    return plans


def _add_billing_period(value, billing_interval):
    months = 12 if billing_interval == "annual" else 1
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def _plan(code):
    return next(item for item in _catalog() if item["code"] == code)


def _payment_amount(plan, billing_interval):
    price = plan["prices"][billing_interval]
    if config.stripe_currency() == "usd":
        return price["usd"] * 100
    return price["cny"] * 100


def _stripe_id(value):
    if isinstance(value, dict):
        return value.get("id")
    return value if isinstance(value, str) else None


def _timestamp(value, fallback=None):
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return fallback or datetime.now(timezone.utc)


def _subscription_row(db, provider_subscription_id=None, checkout_session_id=None):
    query = db.query(Subscription)
    if provider_subscription_id:
        row = query.filter(Subscription.provider_subscription_id == provider_subscription_id).first()
        if row is not None:
            return row
    if checkout_session_id:
        return query.filter(Subscription.provider_checkout_session_id == checkout_session_id).first()
    return None


def _metadata(value):
    return value if isinstance(value, dict) else {}


def _validated_selection(value):
    metadata = _metadata(value.get("metadata"))
    plan_code = str(metadata.get("plan") or "").lower()
    billing_interval = str(metadata.get("billing_interval") or "").lower()
    try:
        tenant_id = int(metadata["tenant_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise stripe_adapter.StripeError("stripe_metadata_invalid") from exc
    if plan_code not in SUBSCRIBABLE_PLANS or plan_code == "enterprise" or billing_interval not in ("monthly", "annual"):
        raise stripe_adapter.StripeError("stripe_metadata_invalid")
    return tenant_id, plan_code, billing_interval, _plan(plan_code)


def _activate_checkout(db, value):
    tenant_id, plan_code, billing_interval, plan = _validated_selection(value)
    if value.get("payment_status") not in ("paid", "no_payment_required"):
        return False
    expected_amount = _payment_amount(plan, billing_interval)
    try:
        amount_total = int(value.get("amount_total", -1))
    except (TypeError, ValueError):
        amount_total = -1
    if value.get("currency") != config.stripe_currency() or amount_total != expected_amount:
        raise stripe_adapter.StripeError("stripe_amount_mismatch")
    tenant = db.get(Tenant, tenant_id)
    if tenant is None or str(value.get("client_reference_id")) != str(tenant_id):
        raise stripe_adapter.StripeError("stripe_tenant_invalid")
    provider_subscription_id = _stripe_id(value.get("subscription"))
    if not provider_subscription_id:
        raise stripe_adapter.StripeError("stripe_subscription_missing")
    row = _subscription_row(db, provider_subscription_id, value.get("id"))
    started_at = _timestamp(value.get("created"))
    if row is None:
        row = Subscription(tenant_id=tenant.id)
        db.add(row)
    row.plan = plan_code
    row.billing_interval = billing_interval
    row.amount_cny_fen = plan["prices"][billing_interval]["cny"] * 100
    row.amount_usd_cents = plan["prices"][billing_interval]["usd"] * 100
    row.status = "active"
    row.provider = "stripe"
    row.provider_customer_id = _stripe_id(value.get("customer"))
    row.provider_subscription_id = provider_subscription_id
    row.provider_checkout_session_id = value.get("id")
    row.started_at = started_at
    row.expires_at = _add_billing_period(started_at, billing_interval)
    tenant.plan = plan_code
    return True


def _sync_tenant_plan(db, tenant_id):
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        return
    active = (
        db.query(Subscription)
        .filter(
            Subscription.tenant_id == tenant_id,
            Subscription.status.in_(("active", "trialing", "past_due")),
        )
        .order_by(Subscription.started_at.desc(), Subscription.id.desc())
        .first()
    )
    tenant.plan = active.plan if active is not None else "trial"


def _update_subscription(db, value, deleted=False):
    provider_subscription_id = value.get("id")
    row = _subscription_row(db, provider_subscription_id)
    if row is None:
        try:
            tenant_id, plan_code, billing_interval, plan = _validated_selection(value)
        except stripe_adapter.StripeError:
            return False
        if db.get(Tenant, tenant_id) is None:
            return False
        row = Subscription(
            tenant_id=tenant_id,
            plan=plan_code,
            billing_interval=billing_interval,
            amount_cny_fen=plan["prices"][billing_interval]["cny"] * 100,
            amount_usd_cents=plan["prices"][billing_interval]["usd"] * 100,
            provider="stripe",
            provider_subscription_id=provider_subscription_id,
            started_at=_timestamp(value.get("start_date")),
        )
        db.add(row)
    status_value = "canceled" if deleted else str(value.get("status") or "incomplete")
    if status_value == "incomplete_expired":
        status_value = "canceled"
    if status_value not in ("active", "trialing", "past_due", "canceled", "unpaid", "incomplete"):
        raise stripe_adapter.StripeError("stripe_subscription_status_invalid")
    row.status = status_value
    row.provider = "stripe"
    row.provider_customer_id = _stripe_id(value.get("customer")) or row.provider_customer_id
    row.expires_at = _timestamp(value.get("current_period_end"), row.expires_at)
    db.flush()
    _sync_tenant_plan(db, row.tenant_id)
    return True


def _update_invoice_status(db, value, paid):
    provider_subscription_id = _stripe_id(value.get("subscription"))
    if not provider_subscription_id:
        parent = value.get("parent") if isinstance(value.get("parent"), dict) else {}
        details = parent.get("subscription_details") if isinstance(parent.get("subscription_details"), dict) else {}
        provider_subscription_id = _stripe_id(details.get("subscription"))
    row = _subscription_row(db, provider_subscription_id)
    if row is None:
        return False
    if paid and row.status in ("canceled", "unpaid"):
        return False
    row.status = "active" if paid else "past_due"
    db.flush()
    _sync_tenant_plan(db, row.tenant_id)
    return True


def _process_stripe_event(db, event):
    event_type = event["type"]
    value = ((event.get("data") or {}).get("object") or {})
    if not isinstance(value, dict):
        raise stripe_adapter.StripeError("stripe_payload_invalid")
    if event_type in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
        return _activate_checkout(db, value)
    if event_type == "customer.subscription.updated":
        return _update_subscription(db, value)
    if event_type == "customer.subscription.deleted":
        return _update_subscription(db, value, deleted=True)
    if event_type == "invoice.payment_failed":
        return _update_invoice_status(db, value, paid=False)
    if event_type == "invoice.paid":
        return _update_invoice_status(db, value, paid=True)
    return False


@router.get("/usage")
def billing_usage(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """返回当前租户试用/订阅用量。"""
    tenant = db.get(Tenant, current_user.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": "no_tenant_membership"})
    result = usage(db, tenant)
    result["platform_pool"] = usage_summary(db, tenant)
    active = (
        db.query(Subscription)
        .filter(Subscription.tenant_id == tenant.id)
        .order_by(Subscription.started_at.desc(), Subscription.id.desc())
        .first()
    )
    result["subscription"] = None if active is None else {
        "id": active.id,
        "plan": active.plan,
        "billing_interval": active.billing_interval,
        "amount_cny_fen": active.amount_cny_fen,
        "amount_usd_cents": active.amount_usd_cents,
        "status": active.status,
        "provider": active.provider,
        "started_at": active.started_at,
        "expires_at": active.expires_at,
    }
    return result


@router.get("/plans")
def billing_plans():
    """返回可用套餐及其展示价格。"""
    return {
        "plans": _catalog(),
        "payment": {
            "provider": "stripe",
            "enabled": config.billing_enabled(),
            "configured": stripe_adapter.configured(),
            "currency": config.stripe_currency(),
        },
    }


@router.get("/platform-pool")
def platform_pool(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """返回平台代付可用引擎和每次逻辑调用单价，不返回服务端密钥。"""
    tenant = db.get(Tenant, current_user.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": "no_tenant_membership"})
    return {
        "eligible": tenant.plan in PAID_PLANS,
        "plan": tenant.plan,
        "engines": public_catalog(),
        "usage": usage_summary(db, tenant),
    }


@router.post("/subscribe")
def subscribe(
    payload: SubscribePayload,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """创建 Stripe Checkout，会话付款成功后由 Webhook 开通套餐。"""
    _require_billing_enabled()
    tenant = db.get(Tenant, current_user.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": "no_tenant_membership"})
    active = db.query(Subscription).filter(
        Subscription.tenant_id == tenant.id,
        Subscription.status.in_(("active", "trialing", "past_due")),
    ).first()
    if active is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "subscription_already_active", "detail": "cancel the current subscription before starting another one"},
        )
    if payload.plan == "enterprise":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "enterprise_contact_required"},
        )
    plan = _plan(payload.plan)
    try:
        session = stripe_adapter.create_checkout_session(
            tenant,
            current_user,
            plan,
            payload.billing_interval,
            _payment_amount(plan, payload.billing_interval),
        )
    except stripe_adapter.StripeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": str(exc)},
        ) from exc
    return {
        "plan": payload.plan,
        "billing_interval": payload.billing_interval,
        "payment": "stripe_checkout",
        "checkout_url": session["url"],
        "checkout_session_id": session["id"],
    }


@router.post("/cancel")
def cancel_subscription(current_user: User = Depends(require_owner), db: Session = Depends(get_db)):
    """取消当前订阅，等待 Stripe Webhook 将租户降回试用状态。"""
    _require_billing_enabled()
    tenant = db.get(Tenant, current_user.tenant_id)
    subscription = db.query(Subscription).filter(
        Subscription.tenant_id == tenant.id,
        Subscription.status.in_(("active", "trialing", "past_due")),
    ).order_by(Subscription.started_at.desc(), Subscription.id.desc()).first()
    if subscription is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"error": "subscription_not_found"})
    try:
        stripe_adapter.cancel_subscription(subscription.provider_subscription_id)
    except stripe_adapter.StripeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail={"error": str(exc)}) from exc
    return {"ok": True, "status": "cancel_requested", "subscription_id": subscription.id}


@router.post("/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """验证 Stripe 签名并幂等同步订阅状态。"""
    _require_billing_enabled()
    payload = await request.body()
    try:
        event = stripe_adapter.verify_event(payload, request.headers.get("Stripe-Signature"))
    except stripe_adapter.StripeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": str(exc)},
        ) from exc
    previous = db.query(BillingEvent).filter(
        BillingEvent.provider == "stripe",
        BillingEvent.event_id == event["id"],
    ).first()
    if previous is not None:
        return {"received": True, "duplicate": True, "processed": False}
    try:
        processed = _process_stripe_event(db, event)
    except stripe_adapter.StripeError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": str(exc)},
        ) from exc
    db.add(BillingEvent(
        provider="stripe",
        event_id=event["id"],
        event_type=event["type"],
        payload_sha256=hashlib.sha256(payload).hexdigest(),
    ))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        duplicate = db.query(BillingEvent).filter(
            BillingEvent.provider == "stripe",
            BillingEvent.event_id == event["id"],
        ).first()
        if duplicate is None:
            raise
        return {"received": True, "duplicate": True, "processed": False}
    return {"received": True, "duplicate": False, "processed": processed}
