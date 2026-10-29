"""Google OAuth 授权码 + PKCE；access token 只在短期会话内使用，不落库。"""

import base64
import hashlib
import json
import secrets
from datetime import timedelta
from urllib.parse import urlencode

import jwt
import requests

from api import config
from api.adapters import locking
from api.auth.security import create_token, decode_token


GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"
SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
STATE_TOKEN_TYPE = "gsc_oauth_state"
STATE_TTL = timedelta(minutes=10)
SESSION_TTL_SECONDS = 300
_REDIS_PREFIX = "citeaura:gsc"


class OAuthError(RuntimeError):
    """携带稳定错误码；消息不得包含 token 或授权码。"""


def redirect_uri():
    return f"{config.public_base_url()}/api/v1/searchdata/gsc/callback"


def _redis():
    return locking.redis_client()


def _challenge(verifier):
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def authorization_url(user_id, tenant_id, project_id):
    """签发绑定用户/租户/项目的 state，并把 PKCE verifier 暂存在 Redis。"""
    if not config.google_oauth_configured():
        raise OAuthError("gsc_not_configured")
    nonce = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(64)
    state = create_token(
        user_id, tenant_id, STATE_TOKEN_TYPE, STATE_TTL,
        {"pid": int(project_id), "nonce": nonce},
    )
    _redis().set(
        f"{_REDIS_PREFIX}:pkce:{nonce}", verifier,
        ex=int(STATE_TTL.total_seconds()), nx=True,
    )
    query = urlencode({
        "client_id": config.google_oauth_client_id(),
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": SCOPE,
        "state": state,
        "code_challenge": _challenge(verifier),
        "code_challenge_method": "S256",
        "prompt": "select_account",
    })
    return f"{GOOGLE_AUTH_ENDPOINT}?{query}"


def verify_state(state):
    """校验 state 签名与有效期，返回 (user_id, tenant_id, project_id, nonce)。"""
    try:
        payload = decode_token(str(state or ""), expected_type=STATE_TOKEN_TYPE)
        return int(payload["sub"]), int(payload["tenant_id"]), int(payload["pid"]), str(payload["nonce"])
    except (KeyError, TypeError, ValueError, RuntimeError, jwt.PyJWTError) as exc:
        raise OAuthError("gsc_state_invalid") from exc


def _take_verifier(nonce):
    """一次性取出 verifier；重放同一个 state 会失败。"""
    key = f"{_REDIS_PREFIX}:pkce:{nonce}"
    client = _redis()
    verifier = client.get(key)
    client.delete(key)
    if isinstance(verifier, bytes):
        verifier = verifier.decode("ascii")
    if not verifier:
        raise OAuthError("gsc_state_invalid")
    return verifier


def exchange_code(code, nonce):
    verifier = _take_verifier(nonce)
    try:
        response = requests.post(
            GOOGLE_TOKEN_ENDPOINT,
            data={
                "client_id": config.google_oauth_client_id(),
                "client_secret": config.google_oauth_client_secret(),
                "code": code,
                "code_verifier": verifier,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri(),
            },
            timeout=15,
        )
        payload = response.json() if response.content else {}
    except (requests.RequestException, ValueError) as exc:
        raise OAuthError("gsc_token_exchange_failed") from exc
    token = payload.get("access_token") if response.ok and isinstance(payload, dict) else None
    if not token:
        raise OAuthError("gsc_token_exchange_failed")
    granted = set(str(payload.get("scope") or "").split())
    if SCOPE not in granted:
        revoke(token)
        raise OAuthError("gsc_scope_not_granted")
    return token


def revoke(token):
    """撤销 access token；失败不影响主流程，token 一小时内自然过期。"""
    try:
        requests.post(GOOGLE_REVOKE_ENDPOINT, data={"token": token}, timeout=10)
    except requests.RequestException:
        pass


def _session_key(session_id):
    return f"{_REDIS_PREFIX}:session:{session_id}"


def open_session(token, user_id, tenant_id, project_id, sites):
    """暂存 token 供用户在多个属性间选择；5 分钟过期且只能消费一次。"""
    session_id = secrets.token_urlsafe(24)
    _redis().set(
        _session_key(session_id),
        json.dumps({
            "token": token, "uid": int(user_id), "tid": int(tenant_id),
            "pid": int(project_id), "sites": list(sites),
        }),
        ex=SESSION_TTL_SECONDS, nx=True,
    )
    return session_id


def read_session(session_id, user_id, tenant_id, project_id):
    raw = _redis().get(_session_key(str(session_id or "")))
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        data = json.loads(raw) if raw else None
    except ValueError:
        data = None
    if (
        not isinstance(data, dict)
        or data.get("uid") != int(user_id)
        or data.get("tid") != int(tenant_id)
        or data.get("pid") != int(project_id)
    ):
        raise OAuthError("gsc_session_expired")
    return data


def close_session(session_id):
    key = _session_key(str(session_id or ""))
    client = _redis()
    raw = client.get(key)
    client.delete(key)
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        token = (json.loads(raw) or {}).get("token") if raw else None
    except ValueError:
        token = None
    if token:
        revoke(token)
