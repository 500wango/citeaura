"""对服务端主动连接的目标地址做统一校验。"""

import ipaddress
import socket
from urllib.parse import urlparse


class NetworkTargetError(ValueError):
    """目标地址不是可访问的公网地址。"""


def resolve_public_addresses(host, port):
    """解析主机并返回稳定排序的地址集合。"""
    host = str(host or "").strip().rstrip(".")
    if not host:
        raise NetworkTargetError("network_target_invalid")
    try:
        results = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, ValueError, OSError) as exc:
        raise NetworkTargetError("network_target_unresolvable") from exc
    addresses = set()
    for result in results:
        address = result[4][0].split("%", 1)[0]
        try:
            addresses.add(ipaddress.ip_address(address))
        except ValueError as exc:
            raise NetworkTargetError("network_target_invalid") from exc
    if not addresses:
        raise NetworkTargetError("network_target_unresolvable")
    return tuple(sorted(addresses, key=lambda address: (address.version, int(address))))


def _resolved_addresses(host, port):
    """兼容内部调用的 DNS 解析入口。"""
    return set(resolve_public_addresses(host, port))


def _is_loopback(host, port):
    host = str(host or "").strip().rstrip(".").lower()
    if host == "localhost":
        return all(address.is_loopback for address in _resolved_addresses(host, port))
    try:
        address = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return False
    return address.is_loopback


def assert_public_host(host, port):
    """拒绝私网、回环、链路本地、保留和云元数据地址。"""
    addresses = resolve_public_addresses(host, port)
    for address in addresses:
        if not address.is_global or address.is_multicast:
            raise NetworkTargetError("network_private_address_blocked")
    return str(host).strip()


def validate_outbound_url(
    value,
    *,
    require_https=True,
    allow_loopback=False,
    resolve=True,
    return_addresses=False,
):
    """校验服务端请求 URL，并在需要时解析 DNS 验证所有结果。"""
    value = str(value or "").strip()
    parsed = urlparse(value)
    if any(ord(char) < 32 for char in value):
        raise NetworkTargetError("network_target_invalid")
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise NetworkTargetError("network_target_invalid")
    if parsed.username or parsed.password:
        raise NetworkTargetError("network_target_invalid")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise NetworkTargetError("network_target_invalid") from exc
    loopback = _is_loopback(parsed.hostname, port) if allow_loopback else False
    if require_https and parsed.scheme != "https" and not loopback:
        raise NetworkTargetError("network_https_required")
    if loopback:
        if not allow_loopback:
            raise NetworkTargetError("network_private_address_blocked")
        return value
    if not resolve:
        try:
            literal = ipaddress.ip_address(parsed.hostname.split("%", 1)[0])
        except ValueError:
            literal = None
        if literal is not None and not literal.is_global:
            raise NetworkTargetError("network_private_address_blocked")
        if parsed.hostname.lower() in {"localhost", "localhost.localdomain"}:
            raise NetworkTargetError("network_private_address_blocked")
        return value
    addresses = resolve_public_addresses(parsed.hostname, port)
    for address in addresses:
        if not address.is_global or address.is_multicast:
            raise NetworkTargetError("network_private_address_blocked")
    return (value, addresses) if return_addresses else value


def assert_public_url(value, *, require_https=True):
    """校验并解析公网 URL。"""
    return validate_outbound_url(value, require_https=require_https, resolve=True)
