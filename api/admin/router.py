"""CiteAura 平台运营控制台 API。"""

import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from api import config
from api import segments
from api.admin.audit import record_admin_event
from api.admin.deps import require_admin_operate, require_admin_read
from api.admin.security import ADMIN_COOKIE, ADMIN_SESSION_MINUTES, create_admin_token
from api.auth.security import DUMMY_PASSWORD_HASH, hash_password, verify_password
from api.billing.access import subscription_is_current
from api.rate_limit import RateLimitUnavailable, check_account
from api.db import get_db
from api.models import (
    AdminAuditEvent,
    Job,
    Membership,
    PaymentTransaction,
    PlatformAdmin,
    ProductEvent,
    Project,
    Subscription,
    Tenant,
    User,
)
from api.billing.limits import activation_funnel
from api.billing.plans import TRIAL_DAYS
from api.billing.limits import activation_funnel_totals


router = APIRouter(prefix="/api/v1/admin", tags=["admin"])
ACTIVE_SUBSCRIPTION_STATUSES = ("active", "trialing", "past_due")
ACTIVATION_ACTIONS = ("sample", "autopilot", "serve", "cycle")


class AdminLogin(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value):
        return value.strip().lower()


class AdminPasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


class StatusChange(BaseModel):
    status: str
    reason: str = Field(min_length=3, max_length=500)

    @field_validator("status")
    @classmethod
    def validate_status(cls, value):
        value = value.strip().lower()
        if value not in ("active", "disabled"):
            raise ValueError("status must be active or disabled")
        return value


def _error(status_code, error):
    raise HTTPException(status_code=status_code, detail={"error": error})


def _utc(value):
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def _ratio(numerator, denominator):
    return round(numerator * 100 / denominator, 1) if denominator else None


def _range(days):
    end = datetime.now(timezone.utc)
    return end - timedelta(days=days), end


def _active_subscription(db, tenant_id):
    return db.query(Subscription).filter(
        Subscription.tenant_id == tenant_id,
        Subscription.status.in_(ACTIVE_SUBSCRIPTION_STATUSES),
    ).order_by(Subscription.started_at.desc(), Subscription.id.desc()).first()


def _active_subscription_map(db, tenant_ids):
    """一次读取租户当前订阅，避免管理概览按租户 N+1 查询。"""
    tenant_ids = [int(value) for value in tenant_ids if value is not None]
    if not tenant_ids:
        return {}
    rows = db.query(Subscription).filter(
        Subscription.tenant_id.in_(tenant_ids),
        Subscription.status.in_(ACTIVE_SUBSCRIPTION_STATUSES),
    ).order_by(Subscription.started_at.desc(), Subscription.id.desc()).all()
    result = {}
    for row in rows:
        result.setdefault(row.tenant_id, row)
    return result


def _activated_tenant_ids(db, tenant_ids):
    """批量计算完成过首个审计/采样动作的租户。"""
    tenant_ids = [int(value) for value in tenant_ids if value is not None]
    if not tenant_ids:
        return set()
    rows = db.query(Project.tenant_id).join(Job, Job.project_id == Project.id).filter(
        Project.tenant_id.in_(tenant_ids),
        Job.status == "done",
        Job.action.in_(("audit", "sample", "sample-import", "autopilot", "cycle", "serve", "bootstrap")),
    ).distinct().all()
    return {row[0] for row in rows}


def _converted_tenant_ids(db, tenants, end):
    """一次读取试用期内的订阅，再按租户截止日判断转化。"""
    tenant_ids = [tenant.id for tenant in tenants]
    if not tenant_ids:
        return set()
    rows = db.query(Subscription).filter(
        Subscription.tenant_id.in_(tenant_ids),
        Subscription.status.in_(ACTIVE_SUBSCRIPTION_STATUSES + ("canceled",)),
    ).all()
    result = set()
    deadlines = {
        tenant.id: _utc(tenant.created_at) + timedelta(days=TRIAL_DAYS)
        for tenant in tenants
        if _utc(tenant.created_at) <= end - timedelta(days=TRIAL_DAYS)
    }
    for row in rows:
        deadline = deadlines.get(row.tenant_id)
        if deadline is not None and _utc(row.started_at) <= deadline:
            result.add(row.tenant_id)
    return result


def _is_paid(subscription):
    return subscription_is_current(subscription)


def _mrr_cents(subscription):
    amount = subscription.amount_usd_cents
    if amount is None:
        return 0
    return round(amount / 12) if subscription.billing_interval == "annual" else amount


def _tenant_activated(db, tenant_id):
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        return False
    funnel = activation_funnel(db, tenant)
    return any(
        item.get("key") == "first_audit" and item.get("completed")
        for item in funnel.get("steps") or []
    )


def _tenant_payload_batch(db, tenants):
    """按分页批量预加载租户列表所需的关联数据。"""
    tenant_ids = [tenant.id for tenant in tenants]
    if not tenant_ids:
        return []
    member_counts = dict(db.query(Membership.tenant_id, func.count(Membership.user_id)).filter(
        Membership.tenant_id.in_(tenant_ids),
    ).group_by(Membership.tenant_id).all())
    project_counts = dict(db.query(Project.tenant_id, func.count(Project.id)).filter(
        Project.tenant_id.in_(tenant_ids),
    ).group_by(Project.tenant_id).all())
    owner_rows = db.query(Membership.tenant_id, User).join(User, User.id == Membership.user_id).filter(
        Membership.tenant_id.in_(tenant_ids),
        Membership.role == "owner",
    ).order_by(Membership.tenant_id.asc(), User.id.asc()).all()
    owners = {}
    for tenant_id, owner in owner_rows:
        owners.setdefault(tenant_id, owner)
    latest_job_ids = db.query(func.max(Job.id)).join(Project, Project.id == Job.project_id).filter(
        Project.tenant_id.in_(tenant_ids),
    ).group_by(Project.tenant_id).subquery()
    latest_jobs = db.query(Job, Project.tenant_id).join(Project, Project.id == Job.project_id).filter(
        Job.id.in_(latest_job_ids),
    ).all()
    latest_by_tenant = {tenant_id: job for job, tenant_id in latest_jobs}
    subscriptions = _active_subscription_map(db, tenant_ids)
    activated_ids = _activated_tenant_ids(db, tenant_ids)
    result = []
    for tenant in tenants:
        subscription = subscriptions.get(tenant.id)
        latest_job = latest_by_tenant.get(tenant.id)
        owner = owners.get(tenant.id)
        result.append({
            "id": tenant.id,
            "name": tenant.name,
            "status": tenant.status,
            "plan": tenant.plan,
            "country_code": tenant.acquisition_country_code,
            "country_source": tenant.country_source,
            "owner_email": owner.email if owner else None,
            "members": member_counts.get(tenant.id, 0),
            "projects": project_counts.get(tenant.id, 0),
            "activated": tenant.id in activated_ids,
            "mrr_usd_cents": _mrr_cents(subscription) if _is_paid(subscription) else 0,
            "subscription_status": subscription.status if subscription else None,
            "trial_ends_at": tenant.trial_ends_at,
            "latest_job_at": latest_job.finished_at or latest_job.started_at if latest_job else None,
            "created_at": tenant.created_at,
        })
    return result


def _tenant_payload(db, tenant):
    """兼容单租户调用，并复用分页批量实现。"""
    return _tenant_payload_batch(db, [tenant])[0]


@router.post("/auth/login")
def admin_login(request: Request, payload: AdminLogin, response: Response, db: Session = Depends(get_db)):
    try:
        decision = check_account(payload.email)
    except RateLimitUnavailable:
        _error(status.HTTP_503_SERVICE_UNAVAILABLE, "rate_limit_unavailable")
    if not decision.allowed:
        _error(status.HTTP_429_TOO_MANY_REQUESTS, "rate_limit_exceeded")
    admin = db.query(PlatformAdmin).filter(PlatformAdmin.email == payload.email).first()
    password_hash = admin.password_hash if admin is not None else DUMMY_PASSWORD_HASH
    password_valid = verify_password(payload.password, password_hash)
    valid = admin is not None and admin.status == "active" and password_valid
    if not valid:
        if admin is not None:
            record_admin_event(
                db, admin.id, "admin.login", "admin_session", outcome="failed",
                ip_address=request.client.host if request.client else None,
            )
            db.commit()
        _error(status.HTTP_401_UNAUTHORIZED, "invalid_admin_credentials")
    admin.last_login_at = datetime.now(timezone.utc)
    record_admin_event(
        db, admin.id, "admin.login", "admin_session",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    response.set_cookie(
        ADMIN_COOKIE,
        create_admin_token(admin),
        max_age=ADMIN_SESSION_MINUTES * 60,
        httponly=True,
        secure=config.session_cookie_secure(),
        samesite="strict",
    )
    response.headers["Cache-Control"] = "no-store"
    return {"authenticated": True, "admin": {"email": admin.email, "role": admin.role}}


@router.post("/auth/logout")
def admin_logout(response: Response, admin: PlatformAdmin = Depends(require_admin_read)):
    response.delete_cookie(ADMIN_COOKIE, httponly=True, secure=config.session_cookie_secure(), samesite="strict")
    response.headers["Cache-Control"] = "no-store"
    return {"ok": True}


@router.post("/auth/password")
def change_admin_password(
    request: Request,
    payload: AdminPasswordChange,
    response: Response,
    admin: PlatformAdmin = Depends(require_admin_read),
    db: Session = Depends(get_db),
):
    if not verify_password(payload.current_password, admin.password_hash):
        _error(status.HTTP_400_BAD_REQUEST, "current_password_incorrect")
    if payload.new_password == payload.current_password:
        _error(status.HTTP_400_BAD_REQUEST, "password_unchanged")
    if payload.new_password == admin.email:
        _error(status.HTTP_400_BAD_REQUEST, "password_matches_email")
    admin.password_hash = hash_password(payload.new_password)
    admin.session_version += 1
    record_admin_event(
        db, admin.id, "admin.password_changed", f"admin:{admin.id}",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    response.delete_cookie(ADMIN_COOKIE, httponly=True, secure=config.session_cookie_secure(), samesite="strict")
    response.headers["Cache-Control"] = "no-store"
    return {"ok": True}


@router.get("/me")
def admin_me(admin: PlatformAdmin = Depends(require_admin_read)):
    return {"admin": {"id": admin.id, "email": admin.email, "role": admin.role, "last_login_at": admin.last_login_at}}


@router.get("/overview")
def overview(
    days: int = Query(default=30, ge=1, le=365),
    country: str | None = Query(default=None, min_length=2, max_length=2),
    admin: PlatformAdmin = Depends(require_admin_read),
    db: Session = Depends(get_db),
):
    start, end = _range(days)
    tenant_query = db.query(Tenant).filter(Tenant.created_at >= start, Tenant.created_at <= end)
    all_tenant_query = db.query(Tenant)
    if country:
        code = country.upper()
        tenant_query = tenant_query.filter(Tenant.acquisition_country_code == code)
        all_tenant_query = all_tenant_query.filter(Tenant.acquisition_country_code == code)
    period_tenants = tenant_query.all()
    all_tenants = all_tenant_query.all()
    subscription_map = _active_subscription_map(db, [tenant.id for tenant in all_tenants])
    current_subscriptions = list(subscription_map.values())
    paid_subscriptions = [item for item in current_subscriptions if _is_paid(item)]
    activated_ids = _activated_tenant_ids(db, [tenant.id for tenant in period_tenants])
    activated = len(activated_ids)
    matured = [tenant for tenant in period_tenants if _utc(tenant.created_at) <= end - timedelta(days=TRIAL_DAYS)]
    converted = len(_converted_tenant_ids(db, matured, end))
    checkout_query = db.query(ProductEvent.tenant_id).filter(
        ProductEvent.name == "checkout_started",
        ProductEvent.created_at >= start,
        ProductEvent.created_at <= end,
    )
    if country:
        checkout_query = checkout_query.join(Tenant, Tenant.id == ProductEvent.tenant_id).filter(
            Tenant.acquisition_country_code == country.upper(),
        )
    checkout_tenants = {row[0] for row in checkout_query.distinct().all() if row[0] is not None}
    paid_checkout = db.query(func.count(func.distinct(Subscription.tenant_id))).filter(
        Subscription.tenant_id.in_(checkout_tenants or {-1}),
        Subscription.started_at >= start,
        Subscription.started_at <= end,
    ).scalar() or 0
    job_query = db.query(Job).filter(Job.started_at >= start, Job.started_at <= end)
    current_job_query = db.query(Job)
    if country:
        job_query = job_query.join(Project, Project.id == Job.project_id).join(Tenant, Tenant.id == Project.tenant_id).filter(
            Tenant.acquisition_country_code == country.upper(),
        )
        current_job_query = current_job_query.join(Project, Project.id == Job.project_id).join(Tenant, Tenant.id == Project.tenant_id).filter(
            Tenant.acquisition_country_code == country.upper(),
        )
    jobs_total = job_query.count()
    failed_jobs = job_query.filter(Job.status == "failed").count()
    visitors_query = db.query(ProductEvent).filter(
        ProductEvent.name == "landing_view",
        ProductEvent.created_at >= start,
        ProductEvent.created_at <= end,
    )
    if country:
        visitors_query = visitors_query.filter(ProductEvent.country_code == country.upper())
    visitors = visitors_query.with_entities(ProductEvent.anonymous_id).distinct().count()
    self_service_signups = sum(1 for tenant in period_tenants)
    unknown = sum(1 for tenant in period_tenants if not tenant.acquisition_country_code)
    payment_query = db.query(func.coalesce(func.sum(PaymentTransaction.amount_usd_cents), 0)).filter(
        PaymentTransaction.status == "succeeded",
        PaymentTransaction.occurred_at >= start,
        PaymentTransaction.occurred_at <= end,
    )
    if country:
        payment_query = payment_query.join(Tenant, Tenant.id == PaymentTransaction.tenant_id).filter(
            Tenant.acquisition_country_code == country.upper(),
        )
    refund_query = db.query(func.coalesce(func.sum(PaymentTransaction.amount_usd_cents), 0)).filter(
        PaymentTransaction.status == "refunded",
        PaymentTransaction.occurred_at >= start,
        PaymentTransaction.occurred_at <= end,
    )
    if country:
        refund_query = refund_query.join(Tenant, Tenant.id == PaymentTransaction.tenant_id).filter(
            Tenant.acquisition_country_code == country.upper(),
        )
    payments_usd_cents = payment_query.scalar() or 0
    refunds_usd_cents = refund_query.scalar() or 0
    return {
        "range": {"days": days, "start": start, "end": end, "country": country.upper() if country else None},
        "segment_funnels": {
            segment: activation_funnel_totals(
                db,
                [tenant for tenant in period_tenants if segments.infer(tenant.plan, len(tenant.projects), tenant.segment) == segment],
            )
            for segment in segments.SEGMENTS
        },
        "customers": {
            "workspaces_total": len(all_tenants),
            "registered": len(period_tenants),
            "trialing": sum(1 for tenant in all_tenants if tenant.plan == "trial" and tenant.status == "active"),
            "activated": activated,
            "activation_rate": _ratio(activated, len(period_tenants)),
            "paid_current": len(paid_subscriptions),
            "unknown_country": unknown,
            "unknown_country_rate": _ratio(unknown, len(period_tenants)),
        },
        "revenue": {
            "currency": "USD",
            "mrr_usd_cents": sum(_mrr_cents(item) for item in paid_subscriptions),
            "arr_usd_cents": sum(_mrr_cents(item) for item in paid_subscriptions) * 12,
            "payments_usd_cents": payments_usd_cents,
            "refunds_usd_cents": refunds_usd_cents,
            "net_payments_usd_cents": payments_usd_cents - refunds_usd_cents,
            "past_due": sum(1 for item in current_subscriptions if item.status == "past_due"),
            "canceling": sum(1 for item in paid_subscriptions if item.cancel_at_period_end),
        },
        "funnel": {
            "visitors": visitors,
            "signups": self_service_signups,
            "visitor_to_signup_rate": _ratio(self_service_signups, visitors),
            "matured_trials": len(matured),
            "converted_trials": converted,
            "trial_to_paid_rate": _ratio(converted, len(matured)),
            "checkout_started": len(checkout_tenants),
            "checkout_paid": paid_checkout,
            "checkout_conversion_rate": _ratio(paid_checkout, len(checkout_tenants)),
        },
        "operations": {
            "jobs": jobs_total,
            "failed_jobs": failed_jobs,
            "job_failure_rate": _ratio(failed_jobs, jobs_total),
            "queued_jobs": current_job_query.filter(Job.status == "queued").count(),
            "running_jobs": current_job_query.filter(Job.status == "running").count(),
        },
    }


@router.get("/funnel")
def funnel(
    days: int = Query(default=30, ge=1, le=365),
    segment: str | None = Query(default=None, pattern="^(solo|agency|unknown)$"),
    country: str | None = Query(default=None, min_length=2, max_length=2),
    admin: PlatformAdmin = Depends(require_admin_read),
    db: Session = Depends(get_db),
):
    """返回按客群拆分的首次价值漏斗，不暴露单个租户数据。"""
    start, end = _range(days)
    query = db.query(Tenant).filter(Tenant.created_at >= start, Tenant.created_at <= end)
    if country:
        query = query.filter(Tenant.acquisition_country_code == country.upper())
    tenants = query.all()
    grouped = {key: [] for key in segments.SEGMENTS}
    for tenant in tenants:
        key = segments.infer(tenant.plan, len(tenant.projects), tenant.segment)
        grouped[key].append(tenant)
    if segment:
        grouped = {segment: grouped[segment]}
    return {
        "range": {"days": days, "start": start, "end": end, "country": country.upper() if country else None},
        "segments": {key: activation_funnel_totals(db, rows) for key, rows in grouped.items()},
    }


@router.get("/countries")
def countries(
    days: int = Query(default=30, ge=1, le=365),
    admin: PlatformAdmin = Depends(require_admin_read),
    db: Session = Depends(get_db),
):
    start, end = _range(days)
    rows = []
    grouped_tenants = {}
    grouped = db.query(Tenant.acquisition_country_code, func.count(Tenant.id)).filter(
        Tenant.created_at >= start,
        Tenant.created_at <= end,
    ).group_by(Tenant.acquisition_country_code).order_by(func.count(Tenant.id).desc()).all()
    period_tenants = db.query(Tenant).filter(Tenant.created_at >= start, Tenant.created_at <= end).all()
    period_tenant_ids = [tenant.id for tenant in period_tenants]
    subscription_map = _active_subscription_map(db, period_tenant_ids)
    activated_ids = _activated_tenant_ids(db, period_tenant_ids)
    matured = [tenant for tenant in period_tenants if _utc(tenant.created_at) <= end - timedelta(days=TRIAL_DAYS)]
    matured_ids = {tenant.id for tenant in matured}
    converted_ids = _converted_tenant_ids(db, matured, end)
    for tenant in period_tenants:
        grouped_tenants.setdefault(tenant.acquisition_country_code, []).append(tenant)
    for country_code, registered in grouped:
        tenants = grouped_tenants.get(country_code, [])
        paid = [subscription_map[tenant.id] for tenant in tenants if tenant.id in subscription_map]
        activated = sum(1 for tenant in tenants if tenant.id in activated_ids)
        country_matured = [tenant for tenant in tenants if tenant.id in matured_ids]
        converted = sum(1 for tenant in country_matured if tenant.id in converted_ids)
        rows.append({
            "country_code": country_code,
            "registered": registered,
            "activated": activated,
            "activation_rate": _ratio(activated, registered),
            "paid_current": sum(1 for item in paid if _is_paid(item)),
            "mrr_usd_cents": sum(_mrr_cents(item) for item in paid if _is_paid(item)),
            "matured_trials": len(country_matured),
            "converted_trials": converted,
            "trial_to_paid_rate": _ratio(converted, len(country_matured)),
        })
    return {"range": {"days": days, "start": start, "end": end}, "countries": rows}


@router.get("/users")
def users(
    q: str | None = Query(default=None, max_length=320),
    country: str | None = Query(default=None, min_length=2, max_length=2),
    user_status: str | None = Query(default=None, alias="status", max_length=32),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=100),
    admin: PlatformAdmin = Depends(require_admin_read),
    db: Session = Depends(get_db),
):
    query = db.query(User)
    if q:
        query = query.filter(User.email.ilike(f"%{q.strip()}%"))
    if country:
        query = query.filter(User.signup_country_code == country.upper())
    if user_status:
        query = query.filter(User.status == user_status)
    total = query.count()
    users_page = query.order_by(User.created_at.desc(), User.id.desc()).offset((page - 1) * per_page).limit(per_page).all()
    user_ids = [user.id for user in users_page]
    memberships_by_user = {}
    membership_rows = db.query(Membership, Tenant).join(Tenant, Tenant.id == Membership.tenant_id).filter(
        Membership.user_id.in_(user_ids or {-1}),
    ).all()
    tenant_ids = {tenant.id for _, tenant in membership_rows}
    subscription_map = _active_subscription_map(db, tenant_ids)
    for membership, tenant in membership_rows:
        memberships_by_user.setdefault(membership.user_id, []).append((membership, tenant))
    items = []
    for user in users_page:
        memberships = memberships_by_user.get(user.id, [])
        paid_workspaces = []
        for membership, tenant in memberships:
            subscription = subscription_map.get(tenant.id)
            if _is_paid(subscription):
                paid_workspaces.append({"id": tenant.id, "name": tenant.name, "plan": subscription.plan})
        items.append({
            "id": user.id,
            "email": user.email,
            "status": user.status,
            "registration_kind": user.registration_kind,
            "country_code": user.signup_country_code,
            "last_login_at": user.last_login_at,
            "created_at": user.created_at,
            "is_paid": bool(paid_workspaces),
            "paid_workspaces": paid_workspaces,
            "workspaces": [{"id": tenant.id, "name": tenant.name, "role": membership.role, "plan": tenant.plan} for membership, tenant in memberships],
        })
    return {"items": items, "pagination": {"page": page, "per_page": per_page, "total": total}}


@router.patch("/users/{user_id}/status")
def change_user_status(
    user_id: int,
    payload: StatusChange,
    request: Request,
    admin: PlatformAdmin = Depends(require_admin_operate),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if user is None:
        _error(status.HTTP_404_NOT_FOUND, "user_not_found")
    previous = user.status
    user.status = payload.status
    user.session_version += 1
    record_admin_event(
        db, admin.id, "user.status_changed", f"user:{user.id}",
        ip_address=request.client.host if request.client else None,
        details={"from": previous, "to": payload.status, "reason": payload.reason},
    )
    db.commit()
    return {"user": {"id": user.id, "status": user.status}}


@router.get("/tenants")
def tenants(
    q: str | None = Query(default=None, max_length=320),
    country: str | None = Query(default=None, min_length=2, max_length=2),
    plan: str | None = Query(default=None, max_length=32),
    tenant_status: str | None = Query(default=None, alias="status", max_length=32),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=100),
    admin: PlatformAdmin = Depends(require_admin_read),
    db: Session = Depends(get_db),
):
    query = db.query(Tenant)
    if q:
        owner_ids = db.query(Membership.tenant_id).join(User, User.id == Membership.user_id).filter(User.email.ilike(f"%{q.strip()}%"))
        query = query.filter(or_(Tenant.name.ilike(f"%{q.strip()}%"), Tenant.id.in_(owner_ids)))
    if country:
        query = query.filter(Tenant.acquisition_country_code == country.upper())
    if plan:
        query = query.filter(Tenant.plan == plan)
    if tenant_status:
        query = query.filter(Tenant.status == tenant_status)
    total = query.count()
    rows = query.order_by(Tenant.created_at.desc(), Tenant.id.desc()).offset((page - 1) * per_page).limit(per_page).all()
    return {"items": _tenant_payload_batch(db, rows), "pagination": {"page": page, "per_page": per_page, "total": total}}


@router.patch("/tenants/{tenant_id}/status")
def change_tenant_status(
    tenant_id: int,
    payload: StatusChange,
    request: Request,
    admin: PlatformAdmin = Depends(require_admin_operate),
    db: Session = Depends(get_db),
):
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        _error(status.HTTP_404_NOT_FOUND, "tenant_not_found")
    previous = tenant.status
    tenant.status = payload.status
    record_admin_event(
        db, admin.id, "tenant.status_changed", f"tenant:{tenant.id}",
        ip_address=request.client.host if request.client else None,
        details={"from": previous, "to": payload.status, "reason": payload.reason},
    )
    db.commit()
    return {"tenant": {"id": tenant.id, "status": tenant.status}}


@router.get("/subscriptions")
def subscriptions(
    subscription_status: str | None = Query(default=None, alias="status", max_length=32),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=100),
    admin: PlatformAdmin = Depends(require_admin_read),
    db: Session = Depends(get_db),
):
    query = db.query(Subscription)
    if subscription_status:
        query = query.filter(Subscription.status == subscription_status)
    total = query.count()
    rows = query.order_by(Subscription.updated_at.desc(), Subscription.id.desc()).offset((page - 1) * per_page).limit(per_page).all()
    tenant_map = {tenant.id: tenant for tenant in db.query(Tenant).filter(
        Tenant.id.in_({row.tenant_id for row in rows} or {-1}),
    ).all()}
    payments_by_subscription = {}
    payment_rows = db.query(PaymentTransaction).filter(
        PaymentTransaction.subscription_id.in_({row.id for row in rows} or {-1}),
    ).order_by(PaymentTransaction.occurred_at.desc(), PaymentTransaction.id.desc()).all()
    for payment in payment_rows:
        payments_by_subscription.setdefault(payment.subscription_id, payment)
    items = []
    for row in rows:
        tenant = tenant_map.get(row.tenant_id)
        latest_payment = payments_by_subscription.get(row.id)
        items.append({
            "id": row.id,
            "tenant_id": row.tenant_id,
            "tenant_name": tenant.name if tenant else None,
            "country_code": tenant.acquisition_country_code if tenant else None,
            "plan": row.plan,
            "billing_interval": row.billing_interval,
            "status": row.status,
            "mrr_usd_cents": _mrr_cents(row) if _is_paid(row) else 0,
            "amount_usd_cents": row.amount_usd_cents,
            "cancel_at_period_end": row.cancel_at_period_end,
            "billing_country_code": latest_payment.billing_country_code if latest_payment else None,
            "latest_payment_status": latest_payment.status if latest_payment else None,
            "started_at": row.started_at,
            "expires_at": row.expires_at,
        })
    return {"currency": "USD", "items": items, "pagination": {"page": page, "per_page": per_page, "total": total}}


@router.get("/jobs")
def jobs(
    job_status: str | None = Query(default=None, alias="status", max_length=32),
    q: str | None = Query(default=None, max_length=128),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=100),
    admin: PlatformAdmin = Depends(require_admin_read),
    db: Session = Depends(get_db),
):
    query = db.query(Job, Project, Tenant).join(Project, Project.id == Job.project_id).join(Tenant, Tenant.id == Project.tenant_id)
    if job_status:
        query = query.filter(Job.status == job_status)
    if q:
        value = f"%{q.strip()}%"
        query = query.filter(or_(Tenant.name.ilike(value), Project.slug.ilike(value), Job.action.ilike(value)))
    total = query.count()
    items = []
    for job, project, tenant in query.order_by(Job.id.desc()).offset((page - 1) * per_page).limit(per_page).all():
        duration = None
        if job.started_at and job.finished_at:
            duration = max(0, round((_utc(job.finished_at) - _utc(job.started_at)).total_seconds()))
        items.append({
            "id": job.id,
            "tenant_id": tenant.id,
            "tenant_name": tenant.name,
            "project_id": project.id,
            "project_slug": project.slug,
            "action": job.action,
            "status": job.status,
            "stage": job.stage,
            "progress": job.progress,
            "attempt": job.attempt,
            "duration_seconds": duration,
            "error": job.error,
            "started_at": job.started_at,
            "finished_at": job.finished_at,
        })
    return {"items": items, "pagination": {"page": page, "per_page": per_page, "total": total}}


@router.get("/audit")
def audit_events(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=100),
    admin: PlatformAdmin = Depends(require_admin_read),
    db: Session = Depends(get_db),
):
    total = db.query(AdminAuditEvent).count()
    rows = db.query(AdminAuditEvent, PlatformAdmin).outerjoin(
        PlatformAdmin, PlatformAdmin.id == AdminAuditEvent.admin_id,
    ).order_by(AdminAuditEvent.id.desc()).offset((page - 1) * per_page).limit(per_page).all()
    items = []
    for event, actor in rows:
        try:
            details = json.loads(event.details or "{}")
        except (TypeError, ValueError):
            details = {}
        items.append({
            "id": event.id,
            "admin_email": actor.email if actor else None,
            "action": event.action,
            "target": event.target,
            "outcome": event.outcome,
            "ip_address": event.ip_address,
            "details": details,
            "created_at": event.created_at,
        })
    return {"items": items, "pagination": {"page": page, "per_page": per_page, "total": total}}
