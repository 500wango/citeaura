"""Product emails sent through the platform AUTH SMTP account."""

from api import config
from api.adapters import outreach


def send_product_email(recipient_email, subject, body, message_id):
    """Send one transactional email. Caller must check auth_smtp_configured()."""
    settings = config.auth_smtp_settings()
    credentials = {"username": settings.pop("username"), "password": settings.pop("password")}
    draft = {
        "id": str(message_id),
        "recipient_email": outreach._clean_email(recipient_email),
        "subject": str(subject or "").strip(),
        "body": str(body or "").strip(),
    }
    if not draft["subject"] or not draft["body"]:
        raise ValueError("email_content_invalid")
    return outreach.send_smtp(draft, settings, credentials)
