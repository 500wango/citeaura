"""计费、套餐和用量 API。"""

import calendar
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from api import config
from api.auth.deps import get_current_user, require_owner
from api.billing.limits import usage
from api.billing.platform_pool import PAID_PLANS, public_catalog, usage_summary
from api.db import get_db
from api.models import Subscription, Tenant, User


router = APIRouter(prefix="/api/v1/billing", tags=["billing"])

PLANS = {
    "pro": {"name": "Pro", "monthly_cny": 199, "monthly_usd": 29, "projects": 10, "sample_runs": None},
    "agency": {"name": "Agency", "monthly_cny": 599, "monthly_usd": 79, "projects": 30, "sample_runs": None},
    "enterprise": {"name": "Enterprise", "monthly_cny": None, "monthly_usd": None, "projects": None, "sample_runs": None},
}


class SubscribePayload(BaseModel):
    plan: str
    billing_interval: str = "monthly"

    @field_validator("plan")
    @classmethod
    def validate_plan(cls, value: str):
        value = value.strip().lower()
        if value not in PLANS:
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
        "started_at": active.started_at,
        "expires_at": active.expires_at,
    }
    return result


@router.get("/plans")
def billing_plans():
    """返回可用套餐及其展示价格。"""
    return {"plans": _catalog()}


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
    """升级租户套餐；支付提供 mock 协议，后续可接 Stripe/支付宝。"""
    tenant = db.get(Tenant, current_user.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": "no_tenant_membership"})
    now = datetime.now(timezone.utc)
    expires_at = None if payload.plan == "enterprise" else _add_billing_period(now, payload.billing_interval)
    plan = next(item for item in _catalog() if item["code"] == payload.plan)
    price = plan["prices"][payload.billing_interval]
    subscription = Subscription(
        tenant_id=tenant.id,
        plan=payload.plan,
        billing_interval=payload.billing_interval,
        amount_cny_fen=price["cny"] * 100 if price["cny"] is not None else None,
        amount_usd_cents=price["usd"] * 100 if price["usd"] is not None else None,
        started_at=now,
        expires_at=expires_at,
    )
    tenant.plan = payload.plan
    db.add(subscription)
    db.commit()
    db.refresh(subscription)
    return {
        "plan": tenant.plan,
        "billing_interval": subscription.billing_interval,
        "amount_cny_fen": subscription.amount_cny_fen,
        "amount_usd_cents": subscription.amount_usd_cents,
        "subscription_id": subscription.id,
        "started_at": subscription.started_at,
        "expires_at": subscription.expires_at,
        "payment": "mock",
    }
