import hashlib
import hmac
import json
import time
from types import SimpleNamespace

import pytest

from api.billing import stripe


def test_checkout_sends_server_owned_price_and_metadata(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_secret")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_secret")
    monkeypatch.setenv("STRIPE_CURRENCY", "cny")
    captured = {}

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {"id": "cs_test_123", "url": "https://checkout.stripe.test/cs_test_123"}

    def post(url, **kwargs):
        captured.update({"url": url, **kwargs})
        return Response()

    monkeypatch.setattr(stripe.requests, "post", post)
    result = stripe.create_checkout_session(
        SimpleNamespace(id=17),
        SimpleNamespace(email="owner@example.com"),
        {"code": "pro", "name": "Pro"},
        "annual",
        199000,
    )

    assert result == {"id": "cs_test_123", "url": "https://checkout.stripe.test/cs_test_123"}
    assert captured["url"] == "https://api.stripe.com/v1/checkout/sessions"
    assert captured["auth"] == ("sk_test_secret", "")
    assert captured["timeout"] == 20
    assert captured["data"]["line_items[0][price_data][unit_amount]"] == "199000"
    assert captured["data"]["line_items[0][price_data][recurring][interval]"] == "year"
    assert captured["data"]["metadata[tenant_id]"] == "17"
    assert captured["data"]["subscription_data[metadata][plan]"] == "pro"


def test_webhook_signature_checks_age_and_payload(monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_secret")
    event = {"id": "evt_test", "type": "invoice.paid", "data": {"object": {}}}
    payload = json.dumps(event, separators=(",", ":")).encode()
    timestamp = int(time.time())
    signature = hmac.new(
        b"whsec_secret",
        str(timestamp).encode() + b"." + payload,
        hashlib.sha256,
    ).hexdigest()

    assert stripe.verify_event(payload, f"t={timestamp},v1={signature}") == event
    with pytest.raises(stripe.StripeError, match="stripe_signature_expired"):
        stripe.verify_event(payload, f"t={timestamp},v1={signature}", now=timestamp + 301)
    with pytest.raises(stripe.StripeError, match="stripe_payload_invalid"):
        invalid = b"not-json"
        invalid_signature = hmac.new(
            b"whsec_secret",
            str(timestamp).encode() + b"." + invalid,
            hashlib.sha256,
        ).hexdigest()
        stripe.verify_event(invalid, f"t={timestamp},v1={invalid_signature}", now=timestamp)
