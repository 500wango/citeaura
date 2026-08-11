"""密码重置令牌和通知邮件。"""

import hashlib
import logging
import secrets
from urllib.parse import quote

from api import config
from api.adapters import outreach


logger = logging.getLogger(__name__)


def create_token():
    return secrets.token_urlsafe(32)


def token_hash(token):
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def send_password_reset_email(email, token):
    if not config.password_reset_email_enabled():
        raise RuntimeError("password_reset_email_disabled")
    settings = config.auth_smtp_settings()
    if not config.auth_smtp_configured():
        raise RuntimeError("auth_smtp_not_configured")
    reset_url = f"{config.public_base_url()}/app/#/reset-password?token={quote(token)}"
    draft = {
        "id": f"password-reset-{token_hash(token)[:12]}",
        "recipient_email": email,
        "subject": "Reset your CiteAura password",
        "body": (
            "We received a request to reset your CiteAura password.\n\n"
            f"Please click the link below within {config.password_reset_ttl_minutes()} minutes to set a new password:\n{reset_url}\n\n"
            "If you did not request this, you can safely ignore this email."
        ),
    }
    credentials = {"username": settings.pop("username"), "password": settings.pop("password")}
    return outreach.send_smtp(draft, settings, credentials)


def send_password_reset_email_safe(email, token):
    try:
        send_password_reset_email(email, token)
    except Exception:  # noqa: BLE001 - 找回接口不能因邮件服务暴露账号是否存在
        logger.exception("password reset email delivery failed")
