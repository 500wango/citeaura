"""计费、套餐和用量 API。"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from api.auth.deps import get_current_user, require_owner
from api.billing.limits import usage
from api.db import get_db
from api.models import Subscription, Tenant, User


router = APIRouter(prefix="/api/v1/billing", tags=["billing"])

PLANS = {
    "pro": {"name": "Pro", "price_cny": 199, "price_usd": 29, "projects": 10, "sample_runs": None},
    "agency": {"name": "Agency", "price_cny": 599, "price_usd": 79, "projects": 30, "sample_runs": None},
    "enterprise": {"name": "Enterprise", "price_cny": None, "price_usd": None, "projects": None, "sample_runs": None},
}


class SubscribePayload(BaseModel):
    plan: str

    @field_validator("plan")
    @classmethod
    def validate_plan(cls, value: str):
        value = value.strip().lower()
        if value not in PLANS:
            raise ValueError("unsupported plan")
        return value


@router.get("/usage")
def billing_usage(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """返回当前租户试用/订阅用量。"""
    tenant = db.get(Tenant, current_user.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": "no_tenant_membership"})
    return usage(db, tenant)


@router.get("/plans")
def billing_plans():
    """返回可用套餐及其展示价格。"""
    return {"plans": [{"code": code, **details} for code, details in PLANS.items()]}


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
    expires_at = None if payload.plan == "enterprise" else now + timedelta(days=30)
    subscription = Subscription(
        tenant_id=tenant.id,
        plan=payload.plan,
        started_at=now,
        expires_at=expires_at,
    )
    tenant.plan = payload.plan
    db.add(subscription)
    db.commit()
    db.refresh(subscription)
    return {
        "plan": tenant.plan,
        "subscription_id": subscription.id,
        "started_at": subscription.started_at,
        "expires_at": subscription.expires_at,
        "payment": "mock",
    }
