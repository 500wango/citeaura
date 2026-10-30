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
GSC_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
GA4_SCOPE = "https://www.googleapis.com/auth/analytics.readonly"
# 兼容旧的单 flow 调用点与测试。
SCOPE = GSC_SCOPE
FLOW_GSC = "gsc"
FLOW_GA4 = "ga4"
FLOWS = {
    FLOW_GSC: {
        "scope": GSC_SCOPE,
        "state_type": "gsc_oauth_state",
        "redis_prefix": "citeaura:gsc",
    },
    FLOW_GA4: {
        "scope": GA4_SCOPE,
        "state_type": "ga4_oauth_state",
        "redis_prefix": "citeaura:ga4",
    },
}
STATE_TOKEN_TYPE = FLOWS[FLOW_GSC]["state_type"]
STATE_TTL = timedelta(minutes=10)
SESSION_TTL_SECONDS = 300
_REDIS_PREFIX = FLOWS[FLOW_GSC]["redis_prefix"]


class OAuthError(RuntimeError):
    """携带稳定错误码；消息不得包含 token 或授权码。"""


def redirect_uri():
    return f"{config.public_base_url()}/api/v1/searchdata/gsc/callback"


def _redis():
    return locking.redis_client()


def _flow_config(flow):
    value = FLOWS.get(str(flow or FLOW_GSC))
    if value is None:
        raise OAuthError(f"{flow}_state_invalid")
    return value


def _challenge(verifier):
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def peek_flow(state):
    """不验签读取 flow，只用于选择回调分支与前端落点；身份信息以 verify_state 为准。"""
    try:
        payload = jwt.decode(
            str(state or ""),
            options={
                "verify_signature": False,
                "verify_exp": False,
                "verify_aud": False,
                "verify_iss": False,
            },
        )
    except jwt.PyJWTError:
        return FLOW_GSC
    flow = str(payload.get("flow") or FLOW_GSC)
    return flow if flow in FLOWS else FLOW_GSC


def authorization_url(user_id, tenant_id, project_id, flow=FLOW_GSC):
    """签发绑定用户/租户/项目/flow 的 state，并把 PKCE verifier 暂存在 Redis。"""
    flow = str(flow or FLOW_GSC)
    flow_config = _flow_config(flow)
    if not config.google_oauth_configured():
        raise OAuthError(f"{flow}_not_configured")
    nonce = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(64)
    state = create_token(
        user_id, tenant_id, flow_config["state_type"], STATE_TTL,
        {"pid": int(project_id), "nonce": nonce, "flow": flow},
    )
    _redis().set(
        f"{flow_config['redis_prefix']}:pkce:{nonce}", verifier,
        ex=int(STATE_TTL.total_seconds()), nx=True,
    )
    query = urlencode({
        "client_id": config.google_oauth_client_id(),
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": flow_config["scope"],
        "state": state,
        "code_challenge": _challenge(verifier),
        "code_challenge_method": "S256",
        "prompt": "select_account",
    })
    return f"{GOOGLE_AUTH_ENDPOINT}?{query}"


def verify_state(state, flow=FLOW_GSC):
    """校验 state 签名与有效期，返回 (user_id, tenant_id, project_id, nonce)。"""
    flow = str(flow or FLOW_GSC)
    flow_config = _flow_config(flow)
    try:
        payload = decode_token(str(state or ""), expected_type=flow_config["state_type"])
        # 旧 GSC state 没有 flow claim，按 gsc 处理。
        if str(payload.get("flow") or FLOW_GSC) != flow:
            raise ValueError("flow mismatch")
        return int(payload["sub"]), int(payload["tenant_id"]), int(payload["pid"]), str(payload["nonce"])
    except (KeyError, TypeError, ValueError, RuntimeError, jwt.PyJWTError) as exc:
        raise OAuthError(f"{flow}_state_invalid") from exc


def _take_verifier(nonce, flow=FLOW_GSC):
    """一次性取出 verifier；重放同一个 state 会失败。"""
    key = f"{_flow_config(flow)['redis_prefix']}:pkce:{nonce}"
    client = _redis()
    verifier = client.get(key)
    client.delete(key)
    if isinstance(verifier, bytes):
        verifier = verifier.decode("ascii")
    if not verifier:
        raise OAuthError(f"{flow}_state_invalid")
    return verifier


def exchange_code(code, nonce, flow=FLOW_GSC):
    flow = str(flow or FLOW_GSC)
    flow_config = _flow_config(flow)
    verifier = _take_verifier(nonce, flow)
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
        raise OAuthError(f"{flow}_token_exchange_failed") from exc
    token = payload.get("access_token") if response.ok and isinstance(payload, dict) else None
    if not token:
        raise OAuthError(f"{flow}_token_exchange_failed")
    granted = set(str(payload.get("scope") or "").split())
    if flow_config["scope"] not in granted:
        revoke(token)
        raise OAuthError(f"{flow}_scope_not_granted")
    return token


def revoke(token):
    """撤销 access token；失败不影响主流程，token 一小时内自然过期。"""
    try:
        requests.post(GOOGLE_REVOKE_ENDPOINT, data={"token": token}, timeout=10)
    except requests.RequestException:
        pass


def _session_key(session_id, flow=FLOW_GSC):
    return f"{_flow_config(flow)['redis_prefix']}:session:{session_id}"


def open_session(token, user_id, tenant_id, project_id, sites=(), *, flow=FLOW_GSC, choices=None):
    """暂存 token 供用户在多个属性间选择；5 分钟过期且只能消费一次。"""
    flow = str(flow or FLOW_GSC)
    session_id = secrets.token_urlsafe(24)
    payload = {
        "token": token, "uid": int(user_id), "tid": int(tenant_id),
        "pid": int(project_id), "flow": flow,
    }
    if choices is not None:
        payload["choices"] = list(choices)
    else:
        payload["sites"] = list(sites)
    _redis().set(
        _session_key(session_id, flow),
        json.dumps(payload),
        ex=SESSION_TTL_SECONDS, nx=True,
    )
    return session_id


def read_session(session_id, user_id, tenant_id, project_id, flow=FLOW_GSC):
    flow = str(flow or FLOW_GSC)
    raw = _redis().get(_session_key(str(session_id or ""), flow))
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
        or str(data.get("flow") or FLOW_GSC) != flow
    ):
        raise OAuthError(f"{flow}_session_expired")
    return data


def close_session(session_id, flow=FLOW_GSC):
    key = _session_key(str(session_id or ""), flow)
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
