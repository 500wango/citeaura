"""租户级安全审计事件。"""

import json

from api.models import AuditEvent


def record_event(db, tenant_id, action, target, outcome="succeeded", user_id=None, ip_address=None, details=None):
    """追加一条审计事件；调用方负责提交事务。"""
    event = AuditEvent(
        tenant_id=tenant_id,
        user_id=user_id,
        action=action,
        target=target,
        outcome=outcome,
        ip_address=ip_address,
        details=json.dumps(details or {}, ensure_ascii=False, sort_keys=True),
    )
    db.add(event)
    return event


def event_payload(event):
    try:
        details = json.loads(event.details or "{}")
    except (TypeError, ValueError):
        details = {}
    return {
        "id": event.id,
        "tenant_id": event.tenant_id,
        "user_id": event.user_id,
        "action": event.action,
        "target": event.target,
        "outcome": event.outcome,
        "ip_address": event.ip_address,
        "details": details,
        "created_at": event.created_at,
    }
