"""Redis 支持的 API 固定窗口限流。"""

import hashlib
import ipaddress
import time
from dataclasses import dataclass

import jwt
from fastapi import Request
from redis.exceptions import RedisError

from api import config
from api.adapters import locking
from api.auth.security import ACCESS_TOKEN_COOKIE, decode_token


RATE_LIMIT_PREFIX = "disvorai:rate-limit"
AUTH_PATHS = frozenset((
    "/api/v1/auth/register",
    "/api/v1/auth/login",
    "/api/v1/auth/refresh",
    "/api/v1/auth/password/forgot",
    "/api/v1/auth/password/reset",
))
EXEMPT_PATHS = frozenset(("/api/v1/health", "/api/v1/health/ready"))
INCREMENT_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return current
"""


class RateLimitUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    reset_at: int


def _source_ip(request):
    value = request.client.host if request.client else "unknown"
    if config.rate_limit_trust_proxy_headers():
        forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0]
        value = request.headers.get("x-real-ip") or forwarded or value
    try:
        return ipaddress.ip_address(value.strip()).compressed
    except ValueError:
        return "unknown"


def _access_token(request):
    authorization = request.headers.get("authorization", "")
    scheme, separator, value = authorization.partition(" ")
    if separator and scheme.lower() == "bearer":
        return value.strip()
    return request.cookies.get(ACCESS_TOKEN_COOKIE)


def _subject(request, auth_scope):
    if auth_scope:
        return f"ip:{_source_ip(request)}"
    token = _access_token(request)
    if token:
        try:
            claims = decode_token(token, expected_type="access")
            return f"tenant:{int(claims['tenant_id'])}:user:{int(claims['sub'])}"
        except (KeyError, TypeError, ValueError, RuntimeError, jwt.PyJWTError):
            pass
    return f"ip:{_source_ip(request)}"


def check_request(request, now=None):
    """返回当前请求的限流决策；非 API 和健康检查不计数。"""
    if not config.rate_limit_enabled() or not request.url.path.startswith("/api/v1/"):
        return None
    if request.url.path in EXEMPT_PATHS:
        return None
    auth_scope = request.url.path in AUTH_PATHS
    limit = config.rate_limit_auth_requests() if auth_scope else config.rate_limit_requests()
    window = config.rate_limit_window_seconds()
    current_time = time.time() if now is None else float(now)
    bucket = int(current_time // window)
    reset_at = (bucket + 1) * window
    subject = _subject(request, auth_scope)
    subject_hash = hashlib.sha256(subject.encode("utf-8")).hexdigest()[:24]
    scope = "auth" if auth_scope else "api"
    key = f"{RATE_LIMIT_PREFIX}:{scope}:{bucket}:{subject_hash}"
    try:
        count = int(locking.redis_client().eval(INCREMENT_SCRIPT, 1, key, max(1, reset_at - int(current_time) + 1)))
    except (RedisError, TypeError, ValueError) as exc:
        raise RateLimitUnavailable("rate_limit_unavailable") from exc
    return RateLimitDecision(
        allowed=count <= limit,
        limit=limit,
        remaining=max(0, limit - count),
        reset_at=reset_at,
    )
