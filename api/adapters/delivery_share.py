"""Time-limited client download links for Agency white-label packs."""

import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone

from api import config
from api.adapters import notify
from api.adapters.branding import load_branding
from api.models import DeliveryShare


WHITE_LABEL_PLANS = frozenset(("agency", "enterprise"))
SHARE_TTL_DAYS = 7
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def token_hash(token):
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def create_token():
    return secrets.token_urlsafe(32)


def public_url(token):
    return f"{config.public_base_url()}/api/v1/public/delivery-packs/{token}"


def clean_email(value):
    value = str(value or "").strip().lower()
    if not value:
        return None
    if not EMAIL_PATTERN.fullmatch(value):
        raise ValueError("invalid_recipient_email")
    return value


def active_share(db, project_id, delivery_date, now=None):
    now = now or datetime.now(timezone.utc)
    return (
        db.query(DeliveryShare)
        .filter(
            DeliveryShare.project_id == project_id,
            DeliveryShare.delivery_date == delivery_date,
            DeliveryShare.revoked_at.is_(None),
            DeliveryShare.expires_at > now,
        )
        .order_by(DeliveryShare.id.desc())
        .first()
    )


def create_share(db, project, user_id, delivery_date, recipient_email=None):
    token = create_token()
    row = DeliveryShare(
        project_id=project.id,
        delivery_date=delivery_date,
        token_hash=token_hash(token),
        created_by_user_id=user_id,
        recipient_email=recipient_email,
        expires_at=datetime.now(timezone.utc) + timedelta(days=SHARE_TTL_DAYS),
    )
    db.add(row)
    db.flush()
    return row, token


def resolve_share(db, token):
    if not token:
        return None
    now = datetime.now(timezone.utc)
    return (
        db.query(DeliveryShare)
        .filter(
            DeliveryShare.token_hash == token_hash(token),
            DeliveryShare.revoked_at.is_(None),
            DeliveryShare.expires_at > now,
        )
        .first()
    )


def sender_name():
    branding = load_branding()
    if branding.get("enabled") and branding.get("company_name"):
        return branding["company_name"]
    return "Your CiteAura workspace"


def send_share_email(recipient_email, project, delivery_date, url, expires_at):
    name = sender_name()
    subject = f"{name} sent a diagnostic pack for {project.url}"
    body = (
        f"{name} prepared a client-ready diagnostic pack for {project.url}.\n\n"
        f"Download the white-label ZIP (expires {expires_at.date().isoformat()}):\n{url}\n\n"
        "This link does not require a CiteAura account. Do not forward it beyond the intended client."
    )
    return notify.send_product_email(
        recipient_email,
        subject,
        body,
        f"delivery-share-{project.id}-{delivery_date}",
    )
