"""计费、套餐和用量 API。"""

import calendar
import hashlib
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel, field_validator
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api import config
from api.auth.deps import get_current_user, require_owner
from api.billing.limits import activation_funnel, usage
from api.billing.plans import PLANS, SUBSCRIBABLE_PLANS
from api.billing.platform_pool import PAID_PLANS, public_catalog, usage_summary
from api.billing import stripe as stripe_adapter
from api.adapters import transactional_email
from api.db import get_db
from api.country import normalize_country_code
from api.models import BillingEvent, Membership, PaymentTransaction, Subscription, Tenant, User
from api.product_events import record_product_event


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
    row.cancel_at_period_end = False
    row.provider = "stripe"
    row.provider_customer_id = _stripe_id(value.get("customer"))
    row.provider_subscription_id = provider_subscription_id
    row.provider_checkout_session_id = value.get("id")
    row.started_at = started_at
    row.expires_at = _add_billing_period(started_at, billing_interval)
    tenant.plan = plan_code
    record_product_event(
        db,
        "payment_succeeded",
        tenant_id=tenant.id,
        country_code=tenant.acquisition_country_code,
        properties={"plan": plan_code, "billing_interval": billing_interval, "source": "checkout"},
    )
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
    if active is not None:
        tenant.plan = active.plan
        return
    latest = (
        db.query(Subscription)
        .filter(Subscription.tenant_id == tenant_id)
        .order_by(Subscription.started_at.desc(), Subscription.id.desc())
        .first()
    )
    tenant.plan = "trial"
    if tenant.trial_ends_at is None:
        tenant.trial_ends_at = (
            latest.expires_at if latest is not None and latest.expires_at is not None
            else latest.started_at if latest is not None
            else datetime.now(timezone.utc)
        )


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
    if "cancel_at_period_end" in value:
        cancel_flag = value["cancel_at_period_end"]
        if isinstance(cancel_flag, str):
            cancel_flag = cancel_flag.strip().lower() in ("1", "true", "yes")
        row.cancel_at_period_end = bool(cancel_flag)
    row.provider = "stripe"
    row.provider_customer_id = _stripe_id(value.get("customer")) or row.provider_customer_id
    row.expires_at = _timestamp(value.get("current_period_end"), row.expires_at)
    metadata = _metadata(value.get("metadata"))
    if metadata:
        tenant_id, plan_code, billing_interval, plan = _validated_selection(value)
        if tenant_id != row.tenant_id:
            raise stripe_adapter.StripeError("stripe_tenant_invalid")
        row.plan = plan_code
        row.billing_interval = billing_interval
        row.amount_cny_fen = plan["prices"][billing_interval]["cny"] * 100
        row.amount_usd_cents = plan["prices"][billing_interval]["usd"] * 100
    db.flush()
    _sync_tenant_plan(db, row.tenant_id)
    return True


def _update_invoice_status(db, value, paid):
    provider_subscription_id = _stripe_id(value.get("subscription"))
    parent = value.get("parent") if isinstance(value.get("parent"), dict) else {}
    details = parent.get("subscription_details") if isinstance(parent.get("subscription_details"), dict) else {}
    if not provider_subscription_id:
        provider_subscription_id = _stripe_id(details.get("subscription"))
    row = _subscription_row(db, provider_subscription_id)
    if row is None:
        metadata = details.get("metadata") if isinstance(details.get("metadata"), dict) else value.get("metadata")
        try:
            tenant_id, plan_code, billing_interval, plan = _validated_selection({"metadata": metadata})
        except stripe_adapter.StripeError:
            return False
        if not provider_subscription_id or db.get(Tenant, tenant_id) is None:
            return False
        row = Subscription(
            tenant_id=tenant_id,
            plan=plan_code,
            billing_interval=billing_interval,
            amount_cny_fen=plan["prices"][billing_interval]["cny"] * 100,
            amount_usd_cents=plan["prices"][billing_interval]["usd"] * 100,
            status="active" if paid else "past_due",
            provider="stripe",
            provider_customer_id=_stripe_id(value.get("customer")),
            provider_subscription_id=provider_subscription_id,
            started_at=_timestamp(value.get("created")),
        )
        db.add(row)
        db.flush()
    if paid and row.status in ("canceled", "unpaid"):
        return False
    row.status = "active" if paid else "past_due"
    db.flush()
    _sync_tenant_plan(db, row.tenant_id)
    return row


def _record_invoice_transaction(db, event, value, subscription, paid):
    currency = str(value.get("currency") or "").strip().lower()
    amount_field = "amount_paid" if paid else "amount_due"
    try:
        amount = max(0, int(value.get(amount_field) or 0))
    except (TypeError, ValueError):
        amount = 0
    address = value.get("customer_address") if isinstance(value.get("customer_address"), dict) else {}
    country_code = normalize_country_code(address.get("country"))
    transaction = PaymentTransaction(
        tenant_id=subscription.tenant_id,
        subscription_id=subscription.id,
        provider="stripe",
        provider_event_id=event["id"],
        provider_invoice_id=value.get("id"),
        status="succeeded" if paid else "failed",
        currency=currency[:3] if currency else "xxx",
        amount_usd_cents=amount if currency == "usd" else None,
        billing_country_code=country_code,
        occurred_at=_timestamp(value.get("status_transitions", {}).get("paid_at") if paid and isinstance(value.get("status_transitions"), dict) else value.get("created")),
    )
    db.add(transaction)
    tenant = db.get(Tenant, subscription.tenant_id)
    record_product_event(
        db,
        "payment_succeeded" if paid else "payment_failed",
        tenant_id=subscription.tenant_id,
        country_code=tenant.acquisition_country_code if tenant is not None else None,
        properties={"invoice_id": value.get("id"), "currency": currency, "amount": amount},
    )


def _record_refund_transaction(db, event, value):
    invoice_id = _stripe_id(value.get("invoice"))
    source = db.query(PaymentTransaction).filter(
        PaymentTransaction.provider == "stripe",
        PaymentTransaction.provider_invoice_id == invoice_id,
        PaymentTransaction.status == "succeeded",
    ).order_by(PaymentTransaction.id.desc()).first()
    if source is None:
        return False
    currency = str(value.get("currency") or source.currency or "").strip().lower()
    try:
        cumulative_amount = max(0, int(value.get("amount_refunded") or 0))
    except (TypeError, ValueError):
        cumulative_amount = 0
    previously_recorded = db.query(func.coalesce(func.sum(PaymentTransaction.amount_usd_cents), 0)).filter(
        PaymentTransaction.provider == "stripe",
        PaymentTransaction.provider_invoice_id == invoice_id,
        PaymentTransaction.status == "refunded",
    ).scalar() or 0
    amount = max(0, cumulative_amount - previously_recorded) if currency == "usd" else cumulative_amount
    billing_details = value.get("billing_details") if isinstance(value.get("billing_details"), dict) else {}
    address = billing_details.get("address") if isinstance(billing_details.get("address"), dict) else {}
    country_code = normalize_country_code(address.get("country")) or source.billing_country_code
    db.add(PaymentTransaction(
        tenant_id=source.tenant_id,
        subscription_id=source.subscription_id,
        provider="stripe",
        provider_event_id=event["id"],
        provider_invoice_id=invoice_id,
        status="refunded",
        currency=currency[:3] if currency else "xxx",
        amount_usd_cents=amount if currency == "usd" else None,
        billing_country_code=country_code,
        occurred_at=_timestamp(value.get("created")),
    ))
    tenant = db.get(Tenant, source.tenant_id)
    record_product_event(
        db,
        "payment_refunded",
        tenant_id=source.tenant_id,
        country_code=tenant.acquisition_country_code if tenant is not None else None,
        properties={"invoice_id": invoice_id, "currency": currency, "amount": amount},
    )
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
        row = _update_invoice_status(db, value, paid=False)
        if row:
            _record_invoice_transaction(db, event, value, row, paid=False)
        return bool(row)
    if event_type == "invoice.paid":
        row = _update_invoice_status(db, value, paid=True)
        if row:
            _record_invoice_transaction(db, event, value, row, paid=True)
        return bool(row)
    if event_type == "charge.refunded":
        return _record_refund_transaction(db, event, value)
    return False


def _owner_email(db, tenant_id):
    """返回租户第一个 owner 的邮箱。"""
    row = (
        db.query(User.email)
        .join(Membership, Membership.user_id == User.id)
        .filter(Membership.tenant_id == tenant_id, Membership.role == "owner")
        .order_by(User.id)
        .first()
    )
    return row[0] if row else None


def _payment_email_payload(db, event, processed):
    """仅为新处理的成功付款事件构造通知参数。"""
    if not processed or event["type"] not in (
        "checkout.session.completed",
        "checkout.session.async_payment_succeeded",
        "invoice.paid",
    ):
        return None
    value = ((event.get("data") or {}).get("object") or {})
    if event["type"].startswith("checkout.session"):
        tenant_id, _, billing_interval, plan = _validated_selection(value)
        amount_minor = value.get("amount_total")
        currency = value.get("currency")
    else:
        provider_subscription_id = _stripe_id(value.get("subscription"))
        parent = value.get("parent") if isinstance(value.get("parent"), dict) else {}
        details = parent.get("subscription_details") if isinstance(parent.get("subscription_details"), dict) else {}
        if not provider_subscription_id:
            provider_subscription_id = _stripe_id(details.get("subscription"))
        subscription = _subscription_row(db, provider_subscription_id)
        if subscription is None:
            return None
        tenant_id = subscription.tenant_id
        plan_code = subscription.plan
        billing_interval = subscription.billing_interval
        plan = _plan(plan_code)
        amount_minor = value.get("amount_paid")
        currency = value.get("currency")
    email = _owner_email(db, tenant_id)
    if not email:
        return None
    return {
        "email": email,
        "plan_name": plan["name"],
        "billing_interval": billing_interval,
        "amount_minor": amount_minor,
        "currency": currency,
        "payment_reference": event["id"],
    }


def _payment_notification_key(event):
    """返回可跨 Checkout 和 invoice 事件复用的通知键。"""
    event_type = event.get("type")
    value = ((event.get("data") or {}).get("object") or {})
    if event_type in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
        invoice_id = _stripe_id(value.get("invoice"))
        if invoice_id:
            return f"stripe-payment:{invoice_id}"
    if event_type == "invoice.paid" and value.get("id"):
        return f"stripe-payment:{value['id']}"
    return None


@router.get("/usage")
def billing_usage(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """返回当前租户试用/订阅用量。"""
    tenant = db.get(Tenant, current_user.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": "no_tenant_membership"})
    result = usage(db, tenant)
    result["platform_pool"] = usage_summary(db, tenant)
    result["platform_pool_calls"] = result["platform_pool"].get("calls", 0)
    result["platform_pool_cost_cny_fen"] = result["platform_pool"].get("cost_cny_fen", 0)
    result["activation_funnel"] = activation_funnel(db, tenant)
    latest = (
        db.query(Subscription)
        .filter(Subscription.tenant_id == tenant.id)
        .order_by(Subscription.started_at.desc(), Subscription.id.desc())
        .first()
    )
    active_paid = (
        latest is not None
        and latest.status in ("active", "trialing", "past_due")
    )
    can_change_plan = bool(
        active_paid
        and latest.provider == "stripe"
        and latest.provider_subscription_id
    )
    result["can_upgrade"] = not active_paid or can_change_plan
    result["can_change_plan"] = can_change_plan
    result["subscription"] = None if latest is None else {
        "id": latest.id,
        "plan": latest.plan,
        "billing_interval": latest.billing_interval,
        "amount_cny_fen": latest.amount_cny_fen,
        "amount_usd_cents": latest.amount_usd_cents,
        "status": latest.status,
        "cancel_at_period_end": latest.cancel_at_period_end,
        "provider": latest.provider,
        "started_at": latest.started_at,
        "expires_at": latest.expires_at,
    }
    db.commit()
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
    """创建 Stripe Checkout；试用中/试用过期均可立即升级，不要求等 trial 结束。"""
    _require_billing_enabled()
    tenant = db.get(Tenant, current_user.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": "no_tenant_membership"})
    if payload.plan == "enterprise":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "enterprise_contact_required"},
        )
    plan = _plan(payload.plan)
    active = db.query(Subscription).filter(
        Subscription.tenant_id == tenant.id,
        Subscription.status.in_(("active", "trialing", "past_due")),
    ).first()
    if active is not None:
        previous_plan = active.plan
        if active.plan == payload.plan and active.billing_interval == payload.billing_interval and not active.cancel_at_period_end:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"error": "subscription_already_active"},
            )
        if active.provider != "stripe" or not active.provider_subscription_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"error": "subscription_change_unavailable"},
            )
        try:
            updated = stripe_adapter.update_subscription(
                active.provider_subscription_id,
                tenant,
                plan,
                payload.billing_interval,
                _payment_amount(plan, payload.billing_interval),
            )
        except stripe_adapter.StripeError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"error": str(exc)},
            ) from exc
        active.plan = payload.plan
        active.billing_interval = payload.billing_interval
        active.amount_cny_fen = plan["prices"][payload.billing_interval]["cny"] * 100
        active.amount_usd_cents = plan["prices"][payload.billing_interval]["usd"] * 100
        active.cancel_at_period_end = False
        updated_status = str(updated.get("status") or active.status)
        if updated_status in ("active", "trialing", "past_due", "canceled", "unpaid", "incomplete"):
            active.status = updated_status
        active.expires_at = _timestamp(updated.get("current_period_end"), active.expires_at)
        tenant.plan = payload.plan
        record_product_event(
            db,
            "subscription_changed",
            tenant_id=tenant.id,
            user_id=current_user.id,
            country_code=tenant.acquisition_country_code,
            properties={"from_plan": previous_plan, "plan": payload.plan, "billing_interval": payload.billing_interval},
        )
        db.commit()
        return {
            "plan": payload.plan,
            "billing_interval": payload.billing_interval,
            "payment": "stripe_subscription_update",
            "subscription_id": active.id,
            "proration": "always_invoice",
            "from_plan": previous_plan,
        }
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
    record_product_event(
        db,
        "checkout_started",
        tenant_id=tenant.id,
        user_id=current_user.id,
        country_code=tenant.acquisition_country_code,
        properties={"plan": payload.plan, "billing_interval": payload.billing_interval, "session_id": session["id"]},
    )
    db.commit()
    return {
        "plan": payload.plan,
        "billing_interval": payload.billing_interval,
        "payment": "stripe_checkout",
        "checkout_url": session["url"],
        "checkout_session_id": session["id"],
        "from_plan": tenant.plan,
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
    subscription.cancel_at_period_end = True
    db.commit()
    return {"ok": True, "status": "cancel_at_period_end", "subscription_id": subscription.id}


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
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
    payment_email = _payment_email_payload(db, event, processed)
    notification_key = _payment_notification_key(event) if payment_email is not None else None
    if notification_key and db.query(BillingEvent.id).filter(
        BillingEvent.provider == "stripe",
        BillingEvent.notification_key == notification_key,
    ).first() is not None:
        payment_email = None
        notification_key = None
    db.add(BillingEvent(
        provider="stripe",
        event_id=event["id"],
        event_type=event["type"],
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        notification_key=notification_key,
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
    if payment_email is not None:
        background_tasks.add_task(
            transactional_email.send_payment_success_email_safe,
            **payment_email,
        )
    return {"received": True, "duplicate": False, "processed": processed}
