from types import SimpleNamespace

import pytest

from api import config
from api import rate_limit


def test_source_ip_uses_rightmost_untrusted_forwarded_hop(monkeypatch):
    monkeypatch.setattr(config, "rate_limit_trust_proxy_headers", lambda: True)
    monkeypatch.setattr(config, "forwarded_allow_ips", lambda: ("127.0.0.1",))
    request = SimpleNamespace(
        client=SimpleNamespace(host="127.0.0.1"),
        headers={"x-forwarded-for": "198.51.100.10, 127.0.0.1"},
    )

    assert rate_limit._source_ip(request) == "198.51.100.10"


def test_source_ip_skips_trusted_proxy_chain(monkeypatch):
    monkeypatch.setattr(config, "rate_limit_trust_proxy_headers", lambda: True)
    monkeypatch.setattr(config, "forwarded_allow_ips", lambda: ("127.0.0.1", "10.0.0.0/8"))
    request = SimpleNamespace(
        client=SimpleNamespace(host="127.0.0.1"),
        headers={"x-forwarded-for": "198.51.100.10, 10.2.3.4, 127.0.0.1"},
    )

    assert rate_limit._source_ip(request) == "198.51.100.10"


def test_source_ip_ignores_invalid_forwarded_values(monkeypatch):
    monkeypatch.setattr(config, "rate_limit_trust_proxy_headers", lambda: True)
    monkeypatch.setattr(config, "forwarded_allow_ips", lambda: ("127.0.0.1",))
    request = SimpleNamespace(
        client=SimpleNamespace(host="192.0.2.44"),
        headers={"x-forwarded-for": "attacker, not-an-ip"},
    )

    assert rate_limit._source_ip(request) == "192.0.2.44"


def test_account_rate_limit_is_normalized_and_fail_closed(monkeypatch):
    calls = []

    class Redis:
        def eval(self, script, count, key, expiry):
            calls.append((key, expiry))
            return len(calls)

    monkeypatch.setattr(rate_limit.locking, "redis_client", lambda: Redis())
    monkeypatch.setattr(config, "rate_limit_auth_requests", lambda: 1)
    first = rate_limit.check_account(" Owner@Example.com ", now=120)
    second = rate_limit.check_account("owner@example.com", now=120)
    assert first.allowed is True
    assert second.allowed is False
    assert calls[0][0] == calls[1][0]

    def unavailable():
        raise __import__("redis").exceptions.ConnectionError("offline")

    monkeypatch.setattr(rate_limit.locking, "redis_client", unavailable)
    with pytest.raises(rate_limit.RateLimitUnavailable):
        rate_limit.check_account("owner@example.com", now=120)
