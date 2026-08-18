"""Compare consecutive sample periods and email owners on noteworthy drops."""

import hashlib
import logging

from api import config
from api.adapters import measurement, notify
from api.adapters.engine import geolib, tenant_slug, with_tenant_read_context
from api.db import SessionLocal
from api.models import Membership, Project, Tenant, User


logger = logging.getLogger(__name__)
ALERT_FILENAME = ".regression-alert.json"
SAMPLE_ACTIONS = frozenset(("sample", "autopilot", "serve", "cycle"))


def _tenant_record(db, tenant_id):
    try:
        return db.get(Tenant, int(tenant_id))
    except (TypeError, ValueError):
        return db.query(Tenant).filter(
            (Tenant.name == str(tenant_id)) | (Tenant.directory_slug == str(tenant_id)),
        ).first()


def _fingerprint(events):
    parts = [
        f"{item.get('kind')}:{item.get('engine_code') or '-'}:{item.get('previous_date')}:"
        f"{item.get('current_date')}:{item.get('delta_pp')}"
        for item in events
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _already_sent(project_slug, fingerprint):
    path = geolib.project_dir(project_slug) / ALERT_FILENAME
    previous = geolib.read_json(path, {}) or {}
    return previous.get("fingerprint") == fingerprint


def _mark_sent(project_slug, fingerprint, events):
    geolib.write_json(geolib.project_dir(project_slug) / ALERT_FILENAME, {
        "fingerprint": fingerprint,
        "events": events,
    })


def _recipient_emails(db, tenant_id):
    rows = (
        db.query(User.email)
        .join(Membership, Membership.user_id == User.id)
        .filter(
            Membership.tenant_id == tenant_id,
            Membership.role.in_(("owner", "editor")),
            User.status == "active",
        )
        .order_by(User.email)
        .all()
    )
    return [row[0] for row in rows if row[0]]


def _format_rate(value):
    if value is None:
        return "unmeasured"
    return f"{round(float(value) * 100, 1)}%"


def _email_body(project, events):
    overall = next((item for item in events if item.get("kind") == "overall"), events[0])
    previous_date = overall.get("previous_date") or "previous period"
    current_date = overall.get("current_date") or "current period"
    lines = [
        f"CiteAura recorded a noteworthy mention-rate drop for {project.url}.",
        "",
        f"Compared periods: {previous_date} → {current_date}",
        f"Overall mention rate: {_format_rate(overall.get('previous_rate'))} → {_format_rate(overall.get('current_rate'))}"
        f" ({overall.get('delta_pp')} pp).",
        "",
    ]
    engine_rows = [item for item in events if item.get("kind") == "engine"]
    if engine_rows:
        lines.append("Engines with a drop of at least 10 pp:")
        for item in engine_rows:
            lines.append(
                f"- {item['engine_code']}: {_format_rate(item.get('previous_rate'))} → "
                f"{_format_rate(item.get('current_rate'))} ({item.get('delta_pp')} pp)"
            )
        lines.append("")
    lines.append("Open the visibility matrix to inspect prompts, answers, and citations.")
    lines.append(f"{config.public_base_url()}/app/#/engines")
    lines.append("")
    lines.append("This is not a ranking guarantee. Re-check the site and tickets before acting.")
    return "\n".join(lines)


def notify_if_needed(tenant_id, project_slug, action=None):
    """Send at most one email per distinct regression fingerprint. Never fail the job."""
    if action not in SAMPLE_ACTIONS:
        return {"status": "skipped", "reason": "action_not_sampled"}
    db = SessionLocal()
    try:
        tenant = _tenant_record(db, tenant_id)
        if tenant is None:
            return {"status": "skipped", "reason": "tenant_missing"}
        project = db.query(Project).filter(
            Project.tenant_id == tenant.id,
            Project.slug == project_slug,
        ).first()
        if project is None or not project.alert_on_regression:
            return {"status": "skipped", "reason": "alerts_disabled"}
        with with_tenant_read_context(tenant.directory_slug or tenant_slug(str(tenant.id)), project.slug):
            events = measurement.regression_events(project.slug)
            if not events:
                return {"status": "skipped", "reason": "no_regression"}
            fingerprint = _fingerprint(events)
            if _already_sent(project.slug, fingerprint):
                return {"status": "skipped", "reason": "already_sent"}
            if not config.auth_smtp_configured():
                _mark_sent(project.slug, fingerprint, events)
                return {"status": "recorded", "reason": "smtp_not_configured"}
            recipients = _recipient_emails(db, tenant.id)
            if not recipients:
                return {"status": "skipped", "reason": "no_recipients"}
            subject = f"CiteAura mention-rate drop on {project.url}"
            body = _email_body(project, events)
            sent = 0
            for email in recipients:
                try:
                    notify.send_product_email(
                        email,
                        subject,
                        body,
                        f"regression-{project.id}-{fingerprint[:12]}-{sent}",
                    )
                    sent += 1
                except Exception:  # noqa: BLE001 - 告警失败不能推翻采样任务
                    logger.exception("regression alert email failed for %s", email)
            if sent:
                _mark_sent(project.slug, fingerprint, events)
                return {"status": "sent", "recipients": sent, "events": len(events)}
            return {"status": "failed", "reason": "smtp_send_failed"}
    except Exception:  # noqa: BLE001
        logger.exception("regression alert evaluation failed")
        return {"status": "failed", "reason": "evaluation_failed"}
    finally:
        db.close()
