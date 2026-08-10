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
        checks.append(_check("dns", True, "DNS 可解析"))
    except PreflightError as exc:
        action = "为域名配置公网 A/AAAA/CNAME 记录并等待 DNS 生效"
        if str(exc) == "private_address_blocked":
            action = "改用可从公网访问的域名，不能使用内网、回环或云元数据地址"
        checks.append(_check("dns", False, str(exc), action=action))
        checks.extend([
            _check("tls", False, "未执行 HTTPS 检查", action="DNS 生效后重新运行预检"),
            _check("homepage", False, "DNS 不可用", action="DNS 生效后检查首页是否返回 HTTP 2xx"),
            _check("robots", False, "DNS 不可用", action="DNS 生效后检查 /robots.txt"),
        ])
        return {"url": normalized, "checks": checks, "ready": False}

    homepage = None
    try:
        homepage = requests.get(normalized, timeout=timeout, allow_redirects=False, stream=True)
        status = homepage.status_code
        reachable = 200 <= status < 300
        checks.append(_check(
            "tls", parsed.scheme == "https", "HTTPS 握手成功" if parsed.scheme == "https" else "站点未启用 HTTPS",
            action="配置有效 TLS 证书，并将 HTTP 永久重定向到 HTTPS",
        ))
        checks.append(_check(
            "homepage", reachable, "首页可访问" if reachable else f"首页返回 HTTP {status}",
            action="检查源站、反向代理和 WAF，确保首页直接返回 HTTP 2xx", status=status,
        ))
    except requests.exceptions.SSLError:
        checks.append(_check("tls", False, "TLS 证书校验失败", action="更新过期、域名不匹配或证书链不完整的 TLS 证书"))
        checks.append(_check("homepage", False, "TLS 连接失败", action="修复 TLS 后重新检查首页"))
    except requests.RequestException as exc:
        checks.append(_check("tls", False, "网络连接失败", action="确认 443 端口、反向代理和防火墙允许公网访问"))
        checks.append(_check("homepage", False, "首页连接失败", action="检查源站超时、WAF 和访问频率限制", error=type(exc).__name__))
    finally:
        if homepage is not None:
            homepage.close()

    robots_url = normalized + "/robots.txt"
    try:
        response = requests.get(robots_url, timeout=timeout, allow_redirects=False, stream=True)
        checks.append(_check(
            "robots", 200 <= response.status_code < 400 or response.status_code == 404,
            "robots.txt 可访问" if response.status_code != 404 else "未提供 robots.txt",
            action="确保 /robots.txt 可访问，且没有整站禁止 AI 抓取器", status=response.status_code,
        ))
        response.close()
    except requests.RequestException as exc:
        checks.append(_check(
            "robots", False, "robots.txt 连接失败", action="检查 /robots.txt 路由、WAF 和源站可用性",
            error=type(exc).__name__,
        ))

    return {"url": normalized, "checks": checks, "ready": all(item["ok"] for item in checks if item["name"] != "robots")}
