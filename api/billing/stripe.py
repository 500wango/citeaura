"""Stripe Checkout 和 Webhook 签名适配。"""

import hashlib
import hmac
import json
import time
import uuid

import requests

from api import config


API_BASE = "https://api.stripe.com/v1"
SIGNATURE_TOLERANCE_SECONDS = 300


class StripeError(RuntimeError):
    pass


def configured():
    return bool(config.billing_enabled() and config.stripe_secret_key() and config.stripe_webhook_secret())


def create_checkout_session(tenant, user, plan, billing_interval, amount):
    if not config.billing_enabled():
        raise StripeError("billing_disabled")
    secret = config.stripe_secret_key()
    if not secret or not config.stripe_webhook_secret():
        raise StripeError("stripe_not_configured")
    currency = config.stripe_currency()
    base_url = config.public_base_url()
    interval = "year" if billing_interval == "annual" else "month"
    metadata = {
        "tenant_id": str(tenant.id),
        "plan": plan["code"],
        "billing_interval": billing_interval,
    }
    data = {
        "mode": "subscription",
        "client_reference_id": str(tenant.id),
        "customer_email": user.email,
        "success_url": f"{base_url}/app?billing=success",
        "cancel_url": f"{base_url}/app?billing=canceled",
        "line_items[0][quantity]": "1",
        "line_items[0][price_data][currency]": currency,
        "line_items[0][price_data][unit_amount]": str(amount),
        "line_items[0][price_data][recurring][interval]": interval,
        "line_items[0][price_data][product_data][name]": f"CiteAura {plan['name']}",
        "allow_promotion_codes": "true",
        "billing_address_collection": "auto",
    }
    for key, value in metadata.items():
        data[f"metadata[{key}]"] = value
        data[f"subscription_data[metadata][{key}]"] = value
    try:
        response = requests.post(
            f"{API_BASE}/checkout/sessions",
            data=data,
            auth=(secret, ""),
            headers={"Idempotency-Key": uuid.uuid4().hex},
            timeout=20,
        )
    except requests.RequestException as exc:
        raise StripeError("stripe_unavailable") from exc
    try:
        result = response.json()
    except ValueError as exc:
        raise StripeError("stripe_invalid_response") from exc
    if response.status_code >= 400:
        code = ((result.get("error") or {}).get("code") or "stripe_request_failed")
        raise StripeError(str(code))
    if not result.get("id") or not result.get("url"):
        raise StripeError("stripe_invalid_response")
    return {"id": result["id"], "url": result["url"]}


def cancel_subscription(provider_subscription_id):
    """设置 Stripe 在当前计费周期结束时取消订阅。"""
    if not config.billing_enabled():
        raise StripeError("billing_disabled")
    secret = config.stripe_secret_key()
    if not secret or not provider_subscription_id:
        raise StripeError("stripe_not_configured")
    try:
        response = requests.post(
            f"{API_BASE}/subscriptions/{provider_subscription_id}",
            data={"cancel_at_period_end": "true"},
            auth=(secret, ""),
            timeout=20,
        )
    except requests.RequestException as exc:
        raise StripeError("stripe_unavailable") from exc
    try:
        result = response.json()
    except ValueError as exc:
        raise StripeError("stripe_invalid_response") from exc
    if response.status_code >= 400:
        code = ((result.get("error") or {}).get("code") or "stripe_request_failed")
        raise StripeError(str(code))
    return result


def update_subscription(provider_subscription_id, tenant, plan, billing_interval, amount):
    """创建服务端定价并原地切换订阅，差额立即开票。"""
    if not config.billing_enabled():
        raise StripeError("billing_disabled")
    secret = config.stripe_secret_key()
    if not secret or not provider_subscription_id:
        raise StripeError("stripe_not_configured")
    auth = (secret, "")
    timeout = 20
    try:
        current_response = requests.get(
            f"{API_BASE}/subscriptions/{provider_subscription_id}",
            auth=auth,
            timeout=timeout,
        )
        current = current_response.json()
    except requests.RequestException as exc:
        raise StripeError("stripe_unavailable") from exc
    except ValueError as exc:
        raise StripeError("stripe_invalid_response") from exc
    if current_response.status_code >= 400:
        raise StripeError(str(((current.get("error") or {}).get("code") or "stripe_request_failed")))
    items = ((current.get("items") or {}).get("data") or [])
    item = items[0] if items and isinstance(items[0], dict) else {}
    item_id = item.get("id")
    product_id = ((item.get("price") or {}).get("product") if isinstance(item.get("price"), dict) else None)
    if isinstance(product_id, dict):
        product_id = product_id.get("id")
    if not item_id or not product_id:
        raise StripeError("stripe_subscription_item_missing")

    interval = "year" if billing_interval == "annual" else "month"
    metadata = {
        "tenant_id": str(tenant.id),
        "plan": plan["code"],
        "billing_interval": billing_interval,
    }
    try:
        price_response = requests.post(
            f"{API_BASE}/prices",
            data={
                "currency": config.stripe_currency(),
                "unit_amount": str(amount),
                "recurring[interval]": interval,
                "product": product_id,
                "metadata[tenant_id]": str(tenant.id),
                "metadata[plan]": plan["code"],
            },
            auth=auth,
            headers={"Idempotency-Key": uuid.uuid4().hex},
            timeout=timeout,
        )
        price = price_response.json()
    except requests.RequestException as exc:
        raise StripeError("stripe_unavailable") from exc
    except ValueError as exc:
        raise StripeError("stripe_invalid_response") from exc
    if price_response.status_code >= 400:
        raise StripeError(str(((price.get("error") or {}).get("code") or "stripe_request_failed")))
    if not price.get("id"):
        raise StripeError("stripe_invalid_response")

    data = {
        "items[0][id]": item_id,
        "items[0][price]": price["id"],
        "proration_behavior": "always_invoice",
        "payment_behavior": "error_if_incomplete",
        "cancel_at_period_end": "false",
    }
    for key, value in metadata.items():
        data[f"metadata[{key}]"] = value
    try:
        response = requests.post(
            f"{API_BASE}/subscriptions/{provider_subscription_id}",
            data=data,
            auth=auth,
            headers={"Idempotency-Key": uuid.uuid4().hex},
            timeout=timeout,
        )
        result = response.json()
    except requests.RequestException as exc:
        raise StripeError("stripe_unavailable") from exc
    except ValueError as exc:
        raise StripeError("stripe_invalid_response") from exc
    if response.status_code >= 400:
        raise StripeError(str(((result.get("error") or {}).get("code") or "stripe_request_failed")))
    if result.get("id") != provider_subscription_id:
        raise StripeError("stripe_invalid_response")
    return result


def verify_event(payload, signature_header, now=None):
    if not config.billing_enabled():
        raise StripeError("billing_disabled")
    secret = config.stripe_webhook_secret()
    if not secret:
        raise StripeError("stripe_not_configured")
    values = {}
    for item in (signature_header or "").split(","):
        key, separator, value = item.partition("=")
        if separator:
            values.setdefault(key, []).append(value)
    try:
        timestamp = int(values["t"][0])
    except (KeyError, ValueError, IndexError) as exc:
        raise StripeError("stripe_signature_invalid") from exc
    current = int(time.time() if now is None else now)
    if abs(current - timestamp) > SIGNATURE_TOLERANCE_SECONDS:
        raise StripeError("stripe_signature_expired")
    signed = str(timestamp).encode("ascii") + b"." + payload
    expected = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, value) for value in values.get("v1", ())):
        raise StripeError("stripe_signature_invalid")
    try:
        event = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StripeError("stripe_payload_invalid") from exc
    if not isinstance(event, dict) or not event.get("id") or not event.get("type"):
        raise StripeError("stripe_payload_invalid")
    return event
