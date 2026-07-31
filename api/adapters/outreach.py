"""外链联络草稿、人工确认状态机与 SMTP 发送。"""

import hashlib
import json
import re
import secrets
import smtplib
import ssl
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from urllib.parse import urlparse

from api.adapters.engine import geolib


EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class OutreachError(RuntimeError):
    pass


def _now():
    return datetime.now(timezone.utc).isoformat()


def _state_path(project_slug):
    return geolib.project_dir(project_slug) / "outreach" / "state.json"


def _load(project_slug):
    value = geolib.read_json(_state_path(project_slug), None)
    if not isinstance(value, dict):
        value = {"version": 1, "drafts": []}
    if not isinstance(value.get("drafts"), list):
        value["drafts"] = []
    return value


def _write(project_slug, state):
    geolib.write_json(_state_path(project_slug), state)


def _draft(state, draft_id):
    return next((item for item in state["drafts"] if item.get("id") == draft_id), None)


def _clean_email(value):
    value = str(value or "").strip().lower()
    if len(value) > 320 or not EMAIL_PATTERN.fullmatch(value):
        raise OutreachError("recipient_email_invalid")
    return value


def _clean_subject(value):
    value = str(value or "").strip()
    if not value or len(value) > 300 or "\n" in value or "\r" in value:
        raise OutreachError("outreach_subject_invalid")
    return value


def _clean_body(value):
    value = str(value or "").strip()
    if not value or len(value) > 20000:
        raise OutreachError("outreach_body_invalid")
    return value


def _content_hash(draft):
    payload = json.dumps(
        {
            "recipient_email": draft["recipient_email"],
            "subject": draft["subject"],
            "body": draft["body"],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def list_drafts(project_slug):
    return sorted(_load(project_slug)["drafts"], key=lambda item: item.get("created_at", ""), reverse=True)


def create_draft(project_slug, ticket, recipient_email):
    if ticket.get("kind") != "offsite":
        raise OutreachError("outreach_requires_offsite_ticket")
    config = geolib.load_config(project_slug)
    brand = (config.get("brand") or {}).get("name") or project_slug
    target_url = str(ticket.get("url") or "").strip()
    target_host = urlparse(target_url).hostname or "目标页面"
    ask_text = str(ticket.get("ask_text") or ticket.get("action") or "补充可核验的品牌信息").strip()
    subject = f"关于更新 {target_host} 上的 {brand} 信息"
    body = (
        "您好，\n\n"
        f"我们注意到页面 {target_url} 与 {brand} 相关，想请您协助完成以下更新：\n\n"
        f"{ask_text}\n\n"
        "如需事实来源或补充材料，请直接回复此邮件。\n\n谢谢。"
    )
    now = _now()
    draft = {
        "id": f"outreach-{secrets.token_hex(6)}",
        "ticket_id": ticket.get("id"),
        "target_url": target_url,
        "recipient_email": _clean_email(recipient_email),
        "subject": _clean_subject(subject),
        "body": _clean_body(body),
        "status": "draft",
        "revision": 1,
        "created_at": now,
        "updated_at": now,
        "queued_at": None,
        "sent_at": None,
        "error": None,
        "confirmed_by_user_id": None,
        "confirmed_at": None,
        "confirmed_revision": None,
        "confirmed_content_hash": None,
    }
    with geolib.project_lock(project_slug):
        state = _load(project_slug)
        state["drafts"].append(draft)
        _write(project_slug, state)
    return draft


def update_draft(project_slug, draft_id, revision, recipient_email, subject, body):
    with geolib.project_lock(project_slug):
        state = _load(project_slug)
        draft = _draft(state, draft_id)
        if draft is None:
            raise OutreachError("outreach_draft_not_found")
        if draft.get("status") not in ("draft", "failed"):
            raise OutreachError("outreach_draft_not_editable")
        if int(draft.get("revision") or 0) != int(revision):
            raise OutreachError("outreach_revision_conflict")
        draft.update({
            "recipient_email": _clean_email(recipient_email),
            "subject": _clean_subject(subject),
            "body": _clean_body(body),
            "status": "draft",
            "revision": int(revision) + 1,
            "updated_at": _now(),
            "error": None,
            "confirmed_by_user_id": None,
            "confirmed_at": None,
            "confirmed_revision": None,
            "confirmed_content_hash": None,
        })
        _write(project_slug, state)
        return draft


def confirm_and_queue(project_slug, draft_id, revision, user_id, confirmation_text):
    with geolib.project_lock(project_slug):
        state = _load(project_slug)
        draft = _draft(state, draft_id)
        if draft is None:
            raise OutreachError("outreach_draft_not_found")
        if draft.get("status") not in ("draft", "failed"):
            raise OutreachError("outreach_draft_not_sendable")
        if int(draft.get("revision") or 0) != int(revision):
            raise OutreachError("outreach_revision_conflict")
        if confirmation_text != f"SEND {draft_id}":
            raise OutreachError("outreach_confirmation_required")
        now = _now()
        draft.update({
            "status": "queued",
            "queued_at": now,
            "updated_at": now,
            "error": None,
            "confirmed_by_user_id": int(user_id),
            "confirmed_at": now,
            "confirmed_revision": int(revision),
            "confirmed_content_hash": _content_hash(draft),
        })
        _write(project_slug, state)
        return draft


def restore_after_queue_failure(project_slug, draft_id, revision, error):
    with geolib.project_lock(project_slug):
        state = _load(project_slug)
        draft = _draft(state, draft_id)
        if draft and draft.get("status") == "queued" and draft.get("confirmed_revision") == int(revision):
            draft.update({"status": "failed", "error": str(error), "updated_at": _now()})
            _write(project_slug, state)
        return draft


def mark_queued_failed(project_slug, draft_id, error):
    with geolib.project_lock(project_slug):
        state = _load(project_slug)
        draft = _draft(state, draft_id)
        if draft is not None and draft.get("status") == "queued":
            draft.update({"status": "failed", "error": str(error)[:2000], "updated_at": _now()})
            _write(project_slug, state)
        return draft


def claim_for_sending(project_slug, draft_id):
    with geolib.project_lock(project_slug):
        state = _load(project_slug)
        draft = _draft(state, draft_id)
        if draft is None:
            raise OutreachError("outreach_draft_not_found")
        if draft.get("status") != "queued":
            raise OutreachError("outreach_draft_not_queued")
        if (
            draft.get("confirmed_revision") != draft.get("revision")
            or draft.get("confirmed_content_hash") != _content_hash(draft)
        ):
            raise OutreachError("outreach_confirmation_stale")
        draft.update({"status": "sending", "updated_at": _now()})
        _write(project_slug, state)
        return dict(draft)


def mark_sent(project_slug, draft_id):
    with geolib.project_lock(project_slug):
        state = _load(project_slug)
        draft = _draft(state, draft_id)
        if draft is None or draft.get("status") != "sending":
            raise OutreachError("outreach_draft_not_sending")
        now = _now()
        draft.update({"status": "sent", "sent_at": now, "updated_at": now, "error": None})
        _write(project_slug, state)
        return draft


def mark_failed(project_slug, draft_id, error):
    with geolib.project_lock(project_slug):
        state = _load(project_slug)
        draft = _draft(state, draft_id)
        if draft is not None and draft.get("status") == "sending":
            draft.update({"status": "failed", "error": str(error)[:2000], "updated_at": _now()})
            _write(project_slug, state)
        return draft


def send_smtp(draft, settings, credentials):
    host = str(settings.get("host") or "").strip()
    port = int(settings.get("port") or 0)
    security_mode = settings.get("security_mode")
    from_email = _clean_email(settings.get("from_email"))
    if not host or port not in (25, 465, 587, 2525) or security_mode not in ("starttls", "ssl"):
        raise OutreachError("outreach_smtp_config_invalid")
    message = EmailMessage()
    message["From"] = formataddr((str(settings.get("from_name") or "").strip(), from_email))
    message["To"] = draft["recipient_email"]
    message["Subject"] = draft["subject"]
    message["Message-ID"] = make_msgid(idstring=draft["id"], domain=from_email.rsplit("@", 1)[-1])
    message.set_content(draft["body"])
    context = ssl.create_default_context()
    smtp_class = smtplib.SMTP_SSL if security_mode == "ssl" else smtplib.SMTP
    try:
        client_connection = (
            smtp_class(host, port, timeout=20, context=context)
            if security_mode == "ssl"
            else smtp_class(host, port, timeout=20)
        )
        with client_connection as client:
            client.ehlo()
            if security_mode == "starttls":
                client.starttls(context=context)
                client.ehlo()
            username = str(credentials.get("username") or "").strip()
            password = str(credentials.get("password") or "")
            if username:
                client.login(username, password)
            client.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise OutreachError("outreach_smtp_send_failed") from exc
    return {"message_id": message["Message-ID"], "recipient_email": draft["recipient_email"]}
