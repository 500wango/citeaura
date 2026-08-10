"""密码重置令牌和通知邮件。"""

import hashlib
import logging
import secrets
from urllib.parse import urlencode

from api import config
from api.adapters import outreach


logger = logging.getLogger(__name__)


def create_token():
    return secrets.token_urlsafe(32)


def token_hash(token):
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def send_password_reset_email(email, token):
    settings = config.auth_smtp_settings()
    if not config.auth_smtp_configured():
        raise RuntimeError("auth_smtp_not_configured")
    query = urlencode({"reset_token": token})
    reset_url = f"{config.public_base_url()}/app?{query}"
    draft = {
        "id": f"password-reset-{token_hash(token)[:12]}",
        "recipient_email": email,
        "subject": "重置你的 CiteAura 密码",
        "body": (
            "我们收到了你的密码重置请求。\n\n"
            f"请在 {config.password_reset_ttl_minutes()} 分钟内打开以下链接：\n{reset_url}\n\n"
            "如果这不是你的操作，请忽略此邮件。"
        ),
    }
    credentials = {"username": settings.pop("username"), "password": settings.pop("password")}
    return outreach.send_smtp(draft, settings, credentials)


def send_password_reset_email_safe(email, token):
    try:
        send_password_reset_email(email, token)
    except Exception:  # noqa: BLE001 - 找回接口不能因邮件服务暴露账号是否存在
        logger.exception("password reset email delivery failed")
