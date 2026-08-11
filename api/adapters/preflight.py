"""上线前站点可达性和安全预检。"""

from urllib.parse import urlparse

import requests

from api.adapters.network import NetworkTargetError, assert_public_host


class PreflightError(ValueError):
    """预检输入或网络检查失败。"""


def normalize_url(value: str) -> str:
    value = str(value or "").strip()
    if "://" not in value:
        value = "https://" + value
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise PreflightError("url must be a valid http(s) URL")
    if parsed.username or parsed.password:
        raise PreflightError("url credentials are not allowed")
    if parsed.query or parsed.fragment:
        raise PreflightError("url query and fragment are not allowed")
    try:
        if parsed.port and not 1 <= parsed.port <= 65535:
            raise PreflightError("url port is invalid")
    except ValueError as exc:
        raise PreflightError("url port is invalid") from exc
    return value.rstrip("/")


def _resolve_public(hostname: str, port: int):
    try:
        assert_public_host(hostname, port)
    except NetworkTargetError as exc:
        message = "private_address_blocked" if str(exc) == "network_private_address_blocked" else "dns_unresolvable"
        raise PreflightError(message) from exc
    return True


def _check(name, ok, message, action=None, **extra):
    return {"name": name, "ok": bool(ok), "message": message, "action": None if ok else action, **extra}


def run(url: str, timeout: float = 8.0) -> dict:
    """执行不泄露响应内容的站点预检。"""
    normalized = normalize_url(url)
    parsed = urlparse(normalized)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    checks = []
    try:
        _resolve_public(parsed.hostname, port)
        checks.append(_check("dns", True, "DNS Resolvable"))
    except PreflightError as exc:
        action = "Configure public A/AAAA/CNAME records for domain and wait for DNS propagation"
        if str(exc) == "private_address_blocked":
            action = "Use a publicly accessible domain; internal, loopback, or metadata addresses are prohibited"
        checks.append(_check("dns", False, str(exc), action=action))
        checks.extend([
            _check("tls", False, "HTTPS check skipped", action="Re-run preflight once DNS propagation completes"),
            _check("homepage", False, "DNS unavailable", action="Verify homepage returns HTTP 2xx once DNS is resolved"),
            _check("robots", False, "DNS unavailable", action="Verify /robots.txt once DNS is resolved"),
        ])
        return {"url": normalized, "checks": checks, "ready": False}

    homepage = None
    try:
        homepage = requests.get(normalized, timeout=timeout, allow_redirects=False, stream=True)
        status = homepage.status_code
        reachable = 200 <= status < 300
        checks.append(_check(
            "tls", parsed.scheme == "https", "HTTPS handshake successful" if parsed.scheme == "https" else "Site does not enable HTTPS",
            action="Configure a valid TLS certificate and redirect HTTP permanently to HTTPS",
        ))
        checks.append(_check(
            "homepage", reachable, "Homepage accessible" if reachable else f"Homepage returned HTTP {status}",
            action="Inspect origin server, reverse proxy, and WAF to ensure homepage returns HTTP 2xx directly", status=status,
        ))
    except requests.exceptions.SSLError:
        checks.append(_check("tls", False, "TLS certificate verification failed", action="Update expired, mismatched, or incomplete certificate chain TLS certificate"))
        checks.append(_check("homepage", False, "TLS connection failed", action="Re-check homepage after resolving TLS issues"))
    except requests.RequestException as exc:
        checks.append(_check("tls", False, "Network connection failed", action="Ensure port 443, reverse proxy, and firewalls allow public internet access"))
        checks.append(_check("homepage", False, "Homepage connection failed", action="Check origin timeouts, WAF, and rate limits", error=type(exc).__name__))
    finally:
        if homepage is not None:
            homepage.close()

    robots_url = normalized + "/robots.txt"
    try:
        response = requests.get(robots_url, timeout=timeout, allow_redirects=False, stream=True)
        checks.append(_check(
            "robots", 200 <= response.status_code < 400 or response.status_code == 404,
            "robots.txt accessible" if response.status_code != 404 else "robots.txt not provided",
            action="Ensure /robots.txt is accessible and does not block AI crawlers sitewide", status=response.status_code,
        ))
        response.close()
    except requests.RequestException as exc:
        checks.append(_check(
            "robots", False, "robots.txt connection failed", action="Inspect /robots.txt route, WAF, and origin server availability",
            error=type(exc).__name__,
        ))

    return {"url": normalized, "checks": checks, "ready": all(item["ok"] for item in checks if item["name"] != "robots")}
