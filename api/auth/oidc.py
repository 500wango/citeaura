"""标准 OIDC 授权码流程、PKCE 和 ID Token 校验。"""

import base64
import hashlib
import secrets
from urllib.parse import urlencode, urlparse

import jwt
import requests

from api.settings.crypto import decrypt_key


class OidcError(RuntimeError):
    pass


def normalize_issuer_url(value):
    value = str(value or "").strip().rstrip("/")
    parsed = urlparse(value)
    local_http = parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1", "::1")
    if (parsed.scheme != "https" and not local_http) or not parsed.hostname:
        raise ValueError("issuer_url_must_use_https")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("invalid_issuer_url")
    return value


def discover(issuer_url):
    issuer_url = normalize_issuer_url(issuer_url)
    try:
        response = requests.get(f"{issuer_url}/.well-known/openid-configuration", timeout=10)
        response.raise_for_status()
        document = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise OidcError("oidc_discovery_failed") from exc
    required = ("issuer", "authorization_endpoint", "token_endpoint", "jwks_uri")
    if any(not document.get(key) for key in required) or document["issuer"].rstrip("/") != issuer_url:
        raise OidcError("oidc_discovery_invalid")
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
        response = requests.post(document["token_endpoint"], data=payload, timeout=10)
        response.raise_for_status()
        token_data = response.json()
        id_token = token_data["id_token"]
        signing_key = jwt.PyJWKClient(document["jwks_uri"]).get_signing_key_from_jwt(id_token).key
        supported = document.get("id_token_signing_alg_values_supported") or ["RS256"]
        algorithms = [value for value in supported if value in ("RS256", "RS384", "RS512", "ES256", "ES384")]
        if not algorithms:
            raise OidcError("oidc_algorithm_unsupported")
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
