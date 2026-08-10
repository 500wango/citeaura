"""标准 OIDC 授权码流程、PKCE 和 ID Token 校验。"""

import base64
import hashlib
import secrets
from urllib.parse import urlencode, urlparse

import jwt
import requests

from api import config
from api.adapters.network import NetworkTargetError, validate_outbound_url
from api.settings.crypto import decrypt_key


class OidcError(RuntimeError):
    pass


def normalize_issuer_url(value):
    value = str(value or "").strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("invalid_issuer_url")
    try:
        validate_outbound_url(
            value,
            require_https=True,
            allow_loopback=config.oidc_allow_insecure_localhost(),
            resolve=False,
        )
    except NetworkTargetError as exc:
        raise ValueError("issuer_url_must_use_https" if str(exc) == "network_https_required" else "invalid_issuer_url") from exc
    return value


def _validate_endpoint(value):
    try:
        return validate_outbound_url(
            value,
            require_https=True,
            allow_loopback=config.oidc_allow_insecure_localhost(),
        )
    except NetworkTargetError as exc:
        raise OidcError("oidc_endpoint_blocked") from exc


def _request_json(method, url, **kwargs):
    kwargs["allow_redirects"] = False
    response = method(url, **kwargs)
    if 300 <= response.status_code < 400:
        raise OidcError("oidc_redirect_blocked")
    response.raise_for_status()
    document = response.json()
    if not isinstance(document, dict):
        raise OidcError("oidc_response_invalid")
    return document


def discover(issuer_url):
    issuer_url = normalize_issuer_url(issuer_url)
    _validate_endpoint(issuer_url)
    try:
        document = _request_json(
            requests.get,
            f"{issuer_url}/.well-known/openid-configuration",
            timeout=10,
        )
    except OidcError:
        raise
    except (requests.RequestException, ValueError) as exc:
        raise OidcError("oidc_discovery_failed") from exc
    required = ("issuer", "authorization_endpoint", "token_endpoint", "jwks_uri")
    if (
        not isinstance(document.get("issuer"), str)
        or any(not document.get(key) for key in required)
        or document["issuer"].rstrip("/") != issuer_url
    ):
        raise OidcError("oidc_discovery_invalid")
    for key in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        _validate_endpoint(document[key])
    return document


def _pkce_pair():
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def authorization_request(configuration, redirect_uri, state):
    document = discover(configuration.issuer_url)
    verifier, challenge = _pkce_pair()
    nonce = secrets.token_urlsafe(32)
    query = urlencode({
        "client_id": configuration.client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    return f"{document['authorization_endpoint']}?{query}", {"verifier": verifier, "nonce": nonce, "state": state}


def complete_login(configuration, redirect_uri, code, context):
    document = discover(configuration.issuer_url)
    payload = {
        "grant_type": "authorization_code",
        "client_id": configuration.client_id,
        "redirect_uri": redirect_uri,
        "code": code,
        "code_verifier": context["verifier"],
    }
    if configuration.encrypted_client_secret:
        payload["client_secret"] = decrypt_key(configuration.encrypted_client_secret)
    try:
        token_data = _request_json(
            requests.post,
            document["token_endpoint"],
            data=payload,
            timeout=10,
        )
        id_token = token_data["id_token"]
        supported = document.get("id_token_signing_alg_values_supported") or ["RS256"]
        algorithms = [value for value in supported if value in ("RS256", "RS384", "RS512", "ES256", "ES384")]
        if not algorithms:
            raise OidcError("oidc_algorithm_unsupported")
        header = jwt.get_unverified_header(id_token)
        if header.get("alg") not in algorithms:
            raise OidcError("oidc_algorithm_unsupported")
        jwks = _request_json(requests.get, document["jwks_uri"], timeout=10)
        keys = jwks.get("keys") if isinstance(jwks.get("keys"), list) else []
        candidates = [key for key in keys if isinstance(key, dict) and (not header.get("kid") or key.get("kid") == header["kid"])]
        if len(candidates) != 1:
            raise OidcError("oidc_signing_key_not_found")
        signing_key = jwt.PyJWK.from_dict(candidates[0], algorithm=header["alg"]).key
        claims = jwt.decode(
            id_token,
            signing_key,
            algorithms=algorithms,
            audience=configuration.client_id,
            issuer=document["issuer"],
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except OidcError:
        raise
    except (KeyError, requests.RequestException, ValueError, jwt.PyJWTError) as exc:
        raise OidcError("oidc_token_invalid") from exc
    if claims.get("nonce") != context.get("nonce"):
        raise OidcError("oidc_nonce_invalid")
    email = str(claims.get("email") or "").strip().lower()
    if not email or "@" not in email or claims.get("email_verified") is False:
        raise OidcError("oidc_email_unverified")
    return {"email": email, "subject": str(claims["sub"]), "claims": claims}
