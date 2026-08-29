"""Turn a public audit handoff into one deterministic first-value ticket."""

import hashlib

from api.adapters.engine import geolib


def _ticket_id(audit_id):
    return "F-" + hashlib.sha256(str(audit_id).encode("utf-8")).hexdigest()[:12].upper()


def ensure_ticket(project_slug, audit):
    """Idempotently add the observed first repair to tasks.json.

    The public audit remains the evidence source of truth. This function only
    creates a small actionable projection after a project has been initialized.
    """
    if not isinstance(audit, dict):
        return None, False
    repair = audit.get("first_repair") if isinstance(audit.get("first_repair"), dict) else None
    if not repair or repair.get("status") != "observed_gap":
        return None, False
    audit_id = audit.get("audit_id") or audit.get("url") or project_slug
    ticket_id = _ticket_id(audit_id)
    ticket = {
        "id": ticket_id,
        "kind": "public_audit_repair",
        "source": "public_audit",
        "public_audit_id": audit.get("audit_id"),
        "priority": "P0",
        "status": "todo",
        "package": "Technical foundations",
        "market": "both",
        "owner": "Engineering",
        "effort": "S",
        "title": f"Fix first public audit finding: {repair.get('finding', 'technical gap')}",
        "why": repair.get("why_it_matters", "Resolve the observed technical gap before measuring AI visibility."),
        "action": repair.get("recommended_action", "Review and fix the observed technical finding."),
        "acceptance": {
            "type": "manual",
            "desc": repair.get("acceptance_criteria", "Re-run the public technical audit and confirm the finding reports OK."),
        },
        "evidence": repair.get("evidence") or [],
        "workflow_customized": False,
    }
    with geolib.project_lock(project_slug):
        import tasks as engine_tasks
        data = engine_tasks.load(project_slug) or {}
        tasks = data.get("tasks") if isinstance(data.get("tasks"), list) else []
        existing = next((item for item in tasks if item.get("id") == ticket_id), None)
        if existing:
            return existing, True
        tasks.insert(0, ticket)
        data["tasks"] = tasks
        engine_tasks.save(project_slug, data)
    return ticket, False
