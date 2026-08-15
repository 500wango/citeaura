"""工单负责人、期限、备注和事件时间线适配。"""

from datetime import date

from api.adapters.engine import geolib


STATUSES = frozenset(("todo", "doing", "done", "blocked", "wontfix"))


def _due_date(value):
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError as exc:
        raise ValueError("due_date must be YYYY-MM-DD") from exc


def _owner(value):
    value = str(value or "").strip()
    if not value or len(value) > 128:
        raise ValueError("owner is required and must not exceed 128 characters")
    return value


def _note(value):
    value = str(value or "").strip()
    if len(value) > 2000:
        raise ValueError("note must not exceed 2000 characters")
    return value


def _find(data, ticket_id):
    return next((item for item in data.get("tasks", []) if item.get("id") == ticket_id), None)


def _apply(ticket, changes, actor, now):
    changed = {}
    if changes.get("status") is not None:
        status = str(changes["status"])
        if status not in STATUSES:
            raise ValueError("invalid ticket status")
        if ticket.get("status") != status:
            changed["status"] = {"from": ticket.get("status"), "to": status}
            ticket["status"] = status
            ticket["closed_at"] = now if status == "done" else None
    if changes.get("owner") is not None:
        owner = _owner(changes["owner"])
        if ticket.get("owner") != owner:
            changed["owner"] = {"from": ticket.get("owner"), "to": owner}
            ticket["owner"] = owner
    if "due_date" in changes:
        due = _due_date(changes.get("due_date"))
        if ticket.get("due_date") != due:
            changed["due_date"] = {"from": ticket.get("due_date"), "to": due}
            ticket["due_date"] = due
    note = _note(changes.get("note"))
    if note:
        note_item = {"at": now, "author": actor, "text": note}
        ticket.setdefault("notes", []).append(note_item)
        ticket["notes"] = ticket["notes"][-50:]
        ticket.setdefault("evidence", []).append({"at": now, "note": note, "author": actor})
        ticket["evidence"] = ticket["evidence"][-20:]
    if changed or note:
        ticket["workflow_customized"] = True
        ticket.setdefault("activity", []).append({
            "at": now,
            "actor": actor,
            "type": "updated",
            "changes": changed,
            "note": note or None,
        })
        ticket["activity"] = ticket["activity"][-100:]
    ticket.setdefault("due_date", None)
    ticket.setdefault("notes", [])
    ticket.setdefault("activity", [])
    return ticket


def update(project_slug, ticket_id, changes, actor):
    import tasks as engine_tasks

    with geolib.project_lock(project_slug):
        data = engine_tasks.load(project_slug)
        ticket = _find(data, ticket_id)
        if ticket is None:
            raise KeyError(ticket_id)
        _apply(ticket, changes, actor, geolib.now_iso())
        engine_tasks.save(project_slug, data)
        return ticket


def bulk_update(project_slug, ticket_ids, changes, actor):
    import tasks as engine_tasks

    unique_ids = list(dict.fromkeys(str(item) for item in ticket_ids))
    with geolib.project_lock(project_slug):
        data = engine_tasks.load(project_slug)
        missing = [ticket_id for ticket_id in unique_ids if _find(data, ticket_id) is None]
        if missing:
            raise KeyError(",".join(missing))
        now = geolib.now_iso()
        updated = [_apply(_find(data, ticket_id), changes, actor, now) for ticket_id in unique_ids]
        engine_tasks.save(project_slug, data)
        return updated


def enrich(tickets):
    items = []
    for raw in tickets or []:
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        item.setdefault("due_date", None)
        item.setdefault("notes", [])
        item.setdefault("activity", [])
        items.append(item)
    return items


def filter_tickets(tickets, *, status=None, owner=None, priority=None, query=None):
    items = enrich(tickets)
    if status:
        items = [item for item in items if item.get("status") == status]
    if owner:
        items = [item for item in items if item.get("owner") == owner]
    if priority:
        items = [item for item in items if item.get("priority") == priority]
    if query:
        needle = query.strip().lower()
        items = [item for item in items if needle in " ".join((
            str(item.get("id") or ""), str(item.get("title") or ""), str(item.get("action") or ""),
        )).lower()]
    return items


def record_verification(project_slug, report):
    """把验收结果写入工单时间线，并为未达标项补可执行下一步。"""
    import tasks as engine_tasks

    with geolib.project_lock(project_slug):
        data = engine_tasks.load(project_slug)
        now = report.get("verified_at") or geolib.now_iso()
        for result in report.get("results", []):
            ticket = _find(data, result.get("id"))
            if ticket is None:
                continue
            failed = result.get("verdict") == "fail"
            result["failure_evidence"] = result.get("note") if failed else None
            result["next_action"] = ticket.get("action") if failed else None
            result["acceptance"] = ticket.get("acceptance")
            ticket.setdefault("activity", []).append({
                "at": now,
                "actor": "system",
                "type": "verification",
                "verdict": result.get("verdict"),
                "evidence": result.get("note"),
                "status_from": result.get("was"),
                "status_to": result.get("now"),
                "next_action": result.get("next_action"),
            })
            ticket["activity"] = ticket["activity"][-100:]
        engine_tasks.save(project_slug, data)
        verify_directory = geolib.project_dir(project_slug) / "verify"
        files = sorted(verify_directory.glob("*.json")) if verify_directory.exists() else []
        if files:
            geolib.write_json(files[-1], report)
    return report
