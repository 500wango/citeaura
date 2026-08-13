"""平台管理员操作审计。"""

import json

from api.models import AdminAuditEvent


def record_admin_event(db, admin_id, action, target, outcome="succeeded", ip_address=None, details=None):
    event = AdminAuditEvent(
        admin_id=admin_id,
        action=action,
        target=target,
        outcome=outcome,
        ip_address=ip_address,
        details=json.dumps(details or {}, ensure_ascii=False, sort_keys=True),
    )
    db.add(event)
    return event
