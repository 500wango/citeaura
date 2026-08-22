from types import SimpleNamespace

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
