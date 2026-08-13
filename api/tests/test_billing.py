import hashlib
import hmac
import json
import time
import types
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.db import Base, get_db
from api.main import app
from api.models import BillingEvent, Job, PaymentTransaction, Project, Subscription, Tenant
from api.billing import stripe as stripe_adapter
from api.projects import router as project_router


@pytest.fixture()
def billing_client(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-that-is-long-enough-32")
    monkeypatch.setenv("BILLING_ENABLED", "true")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_citeaura")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_citeaura")
    monkeypatch.setenv("STRIPE_CURRENCY", "usd")
    monkeypatch.setattr("api.adapters.engine.WORK_ROOT", tmp_path / "work")
    engine = create_engine(f"sqlite:///{tmp_path / 'billing.sqlite'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client, session_factory
    app.dependency_overrides.clear()


def _register(client, email):
    assert client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "correct-horse-battery"},
    ).status_code == 201
    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "correct-horse-battery"},
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _stripe_event(event_id, event_type, value):
    return {
        "id": event_id,
        "type": event_type,
        "data": {"object": value},
    }


def _post_stripe_event(client, event, secret="whsec_citeaura"):
    payload = json.dumps(event, separators=(",", ":")).encode()
    timestamp = int(time.time())
    digest = hmac.new(
        secret.encode(),
        str(timestamp).encode() + b"." + payload,
        hashlib.sha256,
    ).hexdigest()
    return client.post(
        "/api/v1/billing/webhook",
        content=payload,
        headers={"Stripe-Signature": f"t={timestamp},v1={digest}", "Content-Type": "application/json"},
    )


def test_trial_project_limit_and_usage(billing_client, monkeypatch):
    client, session_factory = billing_client
    headers = _register(client, "owner@example.com")
    monkeypatch.setitem(__import__("sys").modules, "geo", types.SimpleNamespace(cmd_init=lambda args: None))
    monkeypatch.setattr(project_router.task_bootstrap, "delay", lambda *a, **kw: types.SimpleNamespace(id="boot"))

    for index in range(3):
        response = client.post(
            "/api/v1/projects",
            headers=headers,
            json={"url": f"example{index}.com"},
        )
        assert response.status_code == 202
    blocked = client.post(
        "/api/v1/projects",
        headers=headers,
        json={"url": "example3.com"},
    )
    assert blocked.status_code == 403
    assert blocked.json()["error"] == "trial_limit_exceeded"

    usage = client.get("/api/v1/billing/usage", headers=headers)
    assert usage.status_code == 200
    assert usage.json()["projects_active"] == 3
    assert usage.json()["projects_limit"] == 3


def test_paid_project_limits_are_enforced_and_reported(billing_client):
    client, session_factory = billing_client
    headers = _register(client, "pro-owner@example.com")
    with session_factory() as db:
        tenant = db.query(Tenant).filter(Tenant.name == "pro-owner").one()
        tenant.plan = "pro"
        db.add_all([
            Project(tenant_id=tenant.id, slug=f"pro-{index}", url=f"https://pro-{index}.example", market="both")
            for index in range(10)
        ])
        db.commit()

    usage = client.get("/api/v1/billing/usage", headers=headers)
    assert usage.status_code == 200
    assert usage.json()["projects_active"] == 10
    assert usage.json()["projects_limit"] == 10

    blocked = client.post(
        "/api/v1/projects",
        headers=headers,
        json={"url": "pro-over-limit.example"},
    )
    assert blocked.status_code == 403
    assert blocked.json() == {
        "error": "plan_limit_exceeded",
        "detail": "pro projects limit is 10",
    }

    with session_factory() as db:
        tenant = db.query(Tenant).filter(Tenant.name == "pro-owner").one()
        tenant.plan = "enterprise"
        db.commit()
    assert client.get("/api/v1/billing/usage", headers=headers).json()["projects_limit"] is None


def test_trial_sample_limit_is_per_project(billing_client, monkeypatch):
    client, session_factory = billing_client
    headers = _register(client, "owner@example.com")

    def fake_init(args):
        from api.adapters.engine import geolib

        geolib.write_json(geolib.project_dir(args.slug) / "geo.json", {
            "brand": {"name": "Example", "site": args.url},
            "market": "both",
            "questions": [{"id": "q901", "text": "What is Example?", "market": "both"}],
        })

    monkeypatch.setitem(__import__("sys").modules, "geo", types.SimpleNamespace(cmd_init=fake_init))
    monkeypatch.setattr(project_router.task_bootstrap, "delay", lambda *a, **kw: types.SimpleNamespace(id="boot"))
    created = client.post("/api/v1/projects", headers=headers, json={"url": "example.com"})
    project_id = created.json()["project_id"]
    monkeypatch.setattr(project_router.task_sample, "delay", lambda *a, **kw: types.SimpleNamespace(id="sample"))

    with session_factory() as db:
        db.query(Job).filter(Job.project_id == project_id, Job.action == "bootstrap").one().status = "done"
        db.commit()

    for _ in range(2):
        response = client.post(f"/api/v1/projects/{project_id}/sample", headers=headers)
        assert response.status_code == 202
        with session_factory() as db:
            job = db.query(Job).filter(Job.project_id == project_id, Job.action == "sample").order_by(Job.id.desc()).first()
            job.status = "done"
            db.commit()
    blocked = client.post(f"/api/v1/projects/{project_id}/sample", headers=headers)
    assert blocked.status_code == 403
    assert blocked.json()["error"] == "trial_limit_exceeded"
    blocked_cycle = client.post(
        f"/api/v1/projects/{project_id}/actions/serve",
        headers=headers,
        json={"params": {}},
    )
    assert blocked_cycle.status_code == 403
    assert blocked_cycle.json()["error"] == "trial_limit_exceeded"


def test_subscribe_creates_checkout_without_opening_limits(billing_client, monkeypatch):
    client, session_factory = billing_client
    headers = _register(client, "owner@example.com")
    captured = {}
    monkeypatch.setattr(
        stripe_adapter,
        "create_checkout_session",
        lambda tenant, user, plan, billing_interval, amount: captured.update({
            "tenant_id": tenant.id,
            "email": user.email,
            "plan": plan["code"],
            "billing_interval": billing_interval,
            "amount": amount,
        }) or {"id": "cs_test_pro", "url": "https://checkout.stripe.test/session"},
    )
    plans = client.get("/api/v1/billing/plans")
    assert plans.status_code == 200
    assert {plan["code"] for plan in plans.json()["plans"]} == {"starter", "pro", "agency", "enterprise"}
    assert plans.json()["payment"] == {
        "provider": "stripe", "enabled": True, "configured": True, "currency": "usd",
    }

    subscribed = client.post("/api/v1/billing/subscribe", headers=headers, json={"plan": "pro"})
    assert subscribed.status_code == 200
    assert subscribed.json()["plan"] == "pro"
    assert subscribed.json()["payment"] == "stripe_checkout"
    assert subscribed.json()["checkout_url"] == "https://checkout.stripe.test/session"
    assert captured["amount"] == 19900
    usage = client.get("/api/v1/billing/usage", headers=headers)
    assert usage.json()["plan"] == "trial"
    with session_factory() as db:
        assert db.query(Subscription).count() == 0


def test_annual_plan_catalog_and_checkout_amount(billing_client, monkeypatch):
    client, _ = billing_client
    headers = _register(client, "annual-owner@example.com")
    monkeypatch.setenv("BILLING_ANNUAL_DISCOUNT_PERCENT", "16.67")
    captured = {}
    monkeypatch.setattr(
        stripe_adapter,
        "create_checkout_session",
        lambda tenant, user, plan, billing_interval, amount: captured.update({"amount": amount})
        or {"id": "cs_test_annual", "url": "https://checkout.stripe.test/annual"},
    )

    plans = client.get("/api/v1/billing/plans").json()["plans"]
    pro = next(plan for plan in plans if plan["code"] == "pro")
    assert pro["prices"]["monthly"] == {"cny": 1499, "usd": 199, "months": 1}
    assert pro["prices"]["annual"] == {"cny": 14989, "usd": 1990, "months": 12}
    assert pro["annual_savings_usd"] == 398
    assert pro["annual_discount_percent"] == 16.67

    subscribed = client.post(
        "/api/v1/billing/subscribe",
        headers=headers,
        json={"plan": "pro", "billing_interval": "annual"},
    )
    assert subscribed.status_code == 200
    result = subscribed.json()
    assert result["billing_interval"] == "annual"
    assert result["payment"] == "stripe_checkout"
    assert captured["amount"] == 199000


def test_signed_webhook_activates_subscription_once(billing_client):
    client, session_factory = billing_client
    headers = _register(client, "paid-owner@example.com")
    with session_factory() as db:
        tenant_id = db.query(Tenant).filter(Tenant.name == "paid-owner").one().id
    event = _stripe_event("evt_checkout_paid", "checkout.session.completed", {
        "id": "cs_paid",
        "created": int(time.time()),
        "client_reference_id": str(tenant_id),
        "customer": "cus_paid",
        "subscription": "sub_paid",
        "payment_status": "paid",
        "currency": "usd",
        "amount_total": 19900,
        "metadata": {
            "tenant_id": str(tenant_id),
            "plan": "pro",
            "billing_interval": "monthly",
        },
    })

    completed = _post_stripe_event(client, event)
    assert completed.status_code == 200
    assert completed.json() == {"received": True, "duplicate": False, "processed": True}
    duplicate = _post_stripe_event(client, event)
    assert duplicate.json() == {"received": True, "duplicate": True, "processed": False}

    with session_factory() as db:
        tenant = db.get(Tenant, tenant_id)
        subscription = db.query(Subscription).one()
        assert tenant.plan == "pro"
        assert subscription.status == "active"
        assert subscription.provider == "stripe"
        assert subscription.provider_subscription_id == "sub_paid"
        assert subscription.provider_checkout_session_id == "cs_paid"
        assert db.query(BillingEvent).count() == 1
    usage = client.get("/api/v1/billing/usage", headers=headers).json()
    assert usage["plan"] == "pro"
    assert usage["subscription"]["provider"] == "stripe"
    assert usage["subscription"]["status"] == "active"


def test_invoice_payments_and_incremental_refunds_are_recorded_in_usd(billing_client):
    client, session_factory = billing_client
    _register(client, "refund-owner@example.com")
    with session_factory() as db:
        tenant = db.query(Tenant).filter(Tenant.name == "refund-owner").one()
        tenant.plan = "pro"
        db.add(Subscription(
            tenant_id=tenant.id,
            plan="pro",
            billing_interval="monthly",
            amount_usd_cents=19900,
            status="active",
            provider="stripe",
            provider_subscription_id="sub_refund",
        ))
        db.commit()

    paid = _post_stripe_event(client, _stripe_event("evt_invoice_paid", "invoice.paid", {
        "id": "in_refund",
        "subscription": "sub_refund",
        "currency": "usd",
        "amount_paid": 19900,
        "created": int(time.time()),
        "customer_address": {"country": "US"},
    }))
    first_refund = _post_stripe_event(client, _stripe_event("evt_refund_first", "charge.refunded", {
        "id": "ch_refund",
        "invoice": "in_refund",
        "currency": "usd",
        "amount_refunded": 5000,
        "created": int(time.time()),
        "billing_details": {"address": {"country": "US"}},
    }))
    second_refund = _post_stripe_event(client, _stripe_event("evt_refund_second", "charge.refunded", {
        "id": "ch_refund",
        "invoice": "in_refund",
        "currency": "usd",
        "amount_refunded": 7500,
        "created": int(time.time()),
    }))

    assert paid.json()["processed"] is True
    assert first_refund.json()["processed"] is True
    assert second_refund.json()["processed"] is True
    with session_factory() as db:
        payments = db.query(PaymentTransaction).order_by(PaymentTransaction.id).all()
        assert [(item.status, item.amount_usd_cents) for item in payments] == [
            ("succeeded", 19900),
            ("refunded", 5000),
            ("refunded", 2500),
        ]
        assert all(item.billing_country_code == "US" for item in payments)


def test_invoice_can_arrive_before_checkout_session_webhook(billing_client):
    client, session_factory = billing_client
    _register(client, "invoice-first@example.com")
    with session_factory() as db:
        tenant = db.query(Tenant).filter(Tenant.name == "invoice-first").one()
        tenant_id = tenant.id

    invoice = _post_stripe_event(client, _stripe_event("evt_invoice_first", "invoice.paid", {
        "id": "in_first",
        "subscription": "sub_invoice_first",
        "customer": "cus_invoice_first",
        "currency": "usd",
        "amount_paid": 19900,
        "created": int(time.time()),
        "parent": {"subscription_details": {"metadata": {
            "tenant_id": str(tenant_id),
            "plan": "pro",
            "billing_interval": "monthly",
        }}},
    }))

    assert invoice.status_code == 200
    assert invoice.json()["processed"] is True
    with session_factory() as db:
        subscription = db.query(Subscription).one()
        assert subscription.provider_subscription_id == "sub_invoice_first"
        assert subscription.status == "active"
        assert db.query(PaymentTransaction).one().amount_usd_cents == 19900


def test_subscription_deleted_webhook_revokes_paid_plan(billing_client):
    client, session_factory = billing_client
    _register(client, "cancel-owner@example.com")
    with session_factory() as db:
        tenant = db.query(Tenant).filter(Tenant.name == "cancel-owner").one()
        tenant.plan = "pro"
        db.add(Subscription(
            tenant_id=tenant.id,
            plan="pro",
            billing_interval="monthly",
            status="active",
            provider="stripe",
            provider_subscription_id="sub_cancel",
        ))
        db.commit()
        tenant_id = tenant.id
    deleted = _post_stripe_event(client, _stripe_event(
        "evt_subscription_deleted",
        "customer.subscription.deleted",
        {"id": "sub_cancel", "status": "canceled", "customer": "cus_cancel"},
    ))
    assert deleted.status_code == 200
    stale_invoice = _post_stripe_event(client, _stripe_event(
        "evt_stale_invoice_paid",
        "invoice.paid",
        {"id": "in_stale", "subscription": "sub_cancel"},
    ))
    assert stale_invoice.status_code == 200
    assert stale_invoice.json()["processed"] is False
    with session_factory() as db:
        assert db.get(Tenant, tenant_id).plan == "trial"
        assert db.query(Subscription).one().status == "canceled"


def test_cancel_subscription_requests_period_end_and_persists_flag(billing_client, monkeypatch):
    client, session_factory = billing_client
    headers = _register(client, "cancel-period@example.com")
    with session_factory() as db:
        tenant = db.query(Tenant).filter(Tenant.name == "cancel-period").one()
        tenant.plan = "pro"
        db.add(Subscription(
            tenant_id=tenant.id,
            plan="pro",
            billing_interval="monthly",
            status="active",
            provider="stripe",
            provider_subscription_id="sub_period",
        ))
        db.commit()
    calls = []
    monkeypatch.setattr(
        stripe_adapter,
        "cancel_subscription",
        lambda subscription_id: calls.append(subscription_id) or {"id": subscription_id, "cancel_at_period_end": True},
    )
    response = client.post("/api/v1/billing/cancel", headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "cancel_at_period_end"
    assert calls == ["sub_period"]
    with session_factory() as db:
        subscription = db.query(Subscription).one()
        assert subscription.cancel_at_period_end is True


def test_webhook_rejects_invalid_signature_and_amount(billing_client):
    client, session_factory = billing_client
    _register(client, "invalid-payment@example.com")
    with session_factory() as db:
        tenant_id = db.query(Tenant).filter(Tenant.name == "invalid-payment").one().id
    event = _stripe_event("evt_bad_amount", "checkout.session.completed", {
        "id": "cs_bad",
        "client_reference_id": str(tenant_id),
        "subscription": "sub_bad",
        "payment_status": "paid",
        "currency": "usd",
        "amount_total": 1,
        "metadata": {"tenant_id": str(tenant_id), "plan": "pro", "billing_interval": "monthly"},
    })
    invalid_signature = _post_stripe_event(client, event, secret="wrong-secret")
    assert invalid_signature.status_code == 400
    assert invalid_signature.json() == {"error": "stripe_signature_invalid"}
    invalid_amount = _post_stripe_event(client, event)
    assert invalid_amount.status_code == 400
    assert invalid_amount.json() == {"error": "stripe_amount_mismatch"}
    with session_factory() as db:
        assert db.get(Tenant, tenant_id).plan == "trial"
        assert db.query(BillingEvent).count() == 0
        assert db.query(Subscription).count() == 0


def test_subscribe_rejects_invalid_billing_interval(billing_client):
    client, _ = billing_client
    headers = _register(client, "invalid-interval@example.com")
    response = client.post(
        "/api/v1/billing/subscribe",
        headers=headers,
        json={"plan": "pro", "billing_interval": "weekly"},
    )
    assert response.status_code == 422


def test_checkout_requires_stripe_configuration_and_rejects_enterprise(billing_client, monkeypatch):
    client, _ = billing_client
    headers = _register(client, "unconfigured-owner@example.com")
    monkeypatch.delenv("STRIPE_SECRET_KEY")

    plans = client.get("/api/v1/billing/plans").json()
    assert plans["payment"]["configured"] is False
    unavailable = client.post(
        "/api/v1/billing/subscribe",
        headers=headers,
        json={"plan": "pro"},
    )
    assert unavailable.status_code == 503
    assert unavailable.json() == {"error": "stripe_not_configured"}
    enterprise = client.post(
        "/api/v1/billing/subscribe",
        headers=headers,
        json={"plan": "enterprise"},
    )
    assert enterprise.status_code == 409
    assert enterprise.json() == {"error": "enterprise_contact_required"}


def test_disabled_billing_rejects_checkout_and_webhooks(billing_client, monkeypatch):
    client, _ = billing_client
    headers = _register(client, "disabled-billing-owner@example.com")
    monkeypatch.setenv("BILLING_ENABLED", "false")

    plans = client.get("/api/v1/billing/plans").json()
    assert plans["payment"]["enabled"] is False
    assert plans["payment"]["configured"] is False
    checkout = client.post(
        "/api/v1/billing/subscribe",
        headers=headers,
        json={"plan": "pro"},
    )
    webhook = client.post("/api/v1/billing/webhook", content=b"{}")

    assert checkout.status_code == 503
    assert checkout.json() == {"error": "billing_disabled"}
    assert webhook.status_code == 503
    assert webhook.json() == {"error": "billing_disabled"}


def test_expired_trial_cannot_create_projects(billing_client):
    client, session_factory = billing_client
    headers = _register(client, "expired@example.com")
    with session_factory() as db:
        tenant = db.query(Tenant).filter(Tenant.name == "expired").one()
        tenant.trial_ends_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()

    blocked = client.post(
        "/api/v1/projects",
        headers=headers,
        json={"url": "expired.example"},
    )
    assert blocked.status_code == 403
    assert blocked.json() == {"error": "trial_limit_exceeded", "detail": "trial has expired"}


def test_active_and_expired_trial_can_upgrade_to_pro_without_waiting(billing_client, monkeypatch):
    """试用中与试用过期均可立刻升级 Pro，不要求等满 14 天。"""
    client, session_factory = billing_client
    captured = []
    monkeypatch.setattr(
        stripe_adapter,
        "create_checkout_session",
        lambda tenant, user, plan, billing_interval, amount: (
            captured.append({"tenant_id": tenant.id, "plan": plan["code"], "amount": amount})
            or {"id": f"cs_{plan['code']}_{len(captured)}", "url": f"https://checkout.stripe.test/{plan['code']}"}
        ),
    )

    active_headers = _register(client, "active-trial@example.com")
    usage = client.get("/api/v1/billing/usage", headers=active_headers).json()
    assert usage["plan"] == "trial"
    assert usage["can_upgrade"] is True
    assert usage["trial_expired"] is False
    active = client.post("/api/v1/billing/subscribe", headers=active_headers, json={"plan": "pro"})
    assert active.status_code == 200
    assert active.json()["plan"] == "pro"
    assert active.json()["from_plan"] == "trial"
    assert active.json()["checkout_url"] == "https://checkout.stripe.test/pro"

    expired_headers = _register(client, "expired-trial@example.com")
    with session_factory() as db:
        tenant = db.query(Tenant).filter(Tenant.name == "expired-trial").one()
        tenant.trial_ends_at = datetime.now(timezone.utc) - timedelta(days=1)
        tenant_id = tenant.id
        db.commit()
    expired_usage = client.get("/api/v1/billing/usage", headers=expired_headers).json()
    assert expired_usage["plan"] == "trial"
    assert expired_usage["trial_expired"] is True
    assert expired_usage["can_upgrade"] is True
    expired = client.post("/api/v1/billing/subscribe", headers=expired_headers, json={"plan": "agency"})
    assert expired.status_code == 200
    assert expired.json()["plan"] == "agency"
    assert expired.json()["from_plan"] == "trial"

    # Webhook 开通后立即离开试用，限额按付费套餐生效。
    paid = _post_stripe_event(client, _stripe_event("evt_trial_upgrade", "checkout.session.completed", {
        "id": "cs_trial_upgrade",
        "created": int(time.time()),
        "client_reference_id": str(tenant_id),
        "customer": "cus_trial_upgrade",
        "subscription": "sub_trial_upgrade",
        "payment_status": "paid",
        "currency": "usd",
        "amount_total": 49900,
        "metadata": {
            "tenant_id": str(tenant_id),
            "plan": "agency",
            "billing_interval": "monthly",
        },
    }))
    assert paid.status_code == 200
    assert paid.json()["processed"] is True
    with session_factory() as db:
        tenant = db.get(Tenant, tenant_id)
        assert tenant.plan == "agency"
        assert tenant.trial_ends_at is None
    after = client.get("/api/v1/billing/usage", headers=expired_headers).json()
    assert after["plan"] == "agency"
    assert after["can_upgrade"] is False
    assert after["projects_limit"] == 30
    assert [item["plan"] for item in captured] == ["pro", "agency"]
