"""工单负责人、期限、备注和事件时间线适配。"""

from datetime import date

from api.adapters.engine import geolib
from api.analytics import experiments


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
        item["effect"] = experiments.normalize_experiment(item)
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
    import verify as engine_verify

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
            history = ticket.setdefault("activity", [])
            # 同一个 report 被重放（重试/重投）时不能重复写入时间线。
            replayed = any(
                isinstance(entry, dict)
                and entry.get("type") == "verification"
                and entry.get("at") == now
                and entry.get("verdict") == result.get("verdict")
                for entry in history
            )
            if replayed:
                continue
            history.append({
                "at": now,
                "actor": "system",
                "type": "verification",
                "verdict": result.get("verdict"),
                "evidence": result.get("note"),
                "status_from": result.get("was"),
                "status_to": result.get("now"),
                "next_action": result.get("next_action"),
            })
            ticket["activity"] = history[-100:]
            if result.get("verdict") == "pass":
                spec = experiments.normalize_experiment(ticket)
                if spec.get("state") == "draft":
                    try:
                        spec = experiments.transition(spec, "deployed", now=now)
                    except ValueError:
                        spec = None
                    if spec is not None:
                        if not spec.get("baseline_run_id"):
                            from api.adapters import measurement
                            spec["baseline_run_id"] = measurement.latest_run_id(project_slug)
                        ticket["effect"] = spec
                        ticket.setdefault("activity", []).append({
                            "at": now,
                            "actor": "system",
                            "type": "effect_deployed",
                            "baseline_run_id": spec.get("baseline_run_id"),
                            "observation_ends_at": spec.get("observation_ends_at"),
                        })
                        ticket["activity"] = ticket["activity"][-100:]
        engine_tasks.save(project_slug, data)
        verify_directory = geolib.project_dir(project_slug) / "verify"
        files = (
            sorted(verify_directory.glob("*.json"), key=engine_verify.report_key)
            if verify_directory.exists() else []
        )
        if files:
            geolib.write_json(files[-1], report)
    return report


def get_experiment(project_slug, ticket_id):
    import tasks as engine_tasks

    data = engine_tasks.load(project_slug)
    ticket = _find(data, ticket_id)
    if ticket is None:
        raise KeyError(ticket_id)
    return experiments.normalize_experiment(ticket)


def update_experiment(project_slug, ticket_id, changes, actor):
    """只允许在未部署时改题组；已部署后改题组会让前后 cohort 不可比。"""
    import tasks as engine_tasks

    changes = dict(changes or {})
    with geolib.project_lock(project_slug):
        data = engine_tasks.load(project_slug)
        ticket = _find(data, ticket_id)
        if ticket is None:
            raise KeyError(ticket_id)
        spec = experiments.normalize_experiment(ticket)
        if spec.get("state") not in ("draft", "inconclusive"):
            binding_fields = {"target_question_ids", "control_question_ids", "metric"}
            if binding_fields & set(changes):
                raise ValueError("experiment binding cannot change after deployment")
        for key in (
            "target_question_ids", "control_question_ids", "metric",
            "observation_days", "min_effect", "confidence",
        ):
            if key in changes and changes[key] is not None:
                spec[key] = changes[key]
        config = geolib.load_config(project_slug)
        experiments.validate_binding(spec, config.get("questions") or [])
        spec["ticket_id"] = ticket.get("id")
        ticket["effect"] = spec
        ticket.setdefault("activity", []).append({
            "at": geolib.now_iso(),
            "actor": actor,
            "type": "effect_updated",
            "target_question_ids": spec.get("target_question_ids"),
            "control_question_ids": spec.get("control_question_ids"),
        })
        ticket["activity"] = ticket["activity"][-100:]
        engine_tasks.save(project_slug, data)
        return spec


def record_effect_evaluations(project_slug, current_rows=None, run_id=None, now=None):
    """采样后评估到期的观察中实验；证据不足时保持/进入 inconclusive。"""
    import tasks as engine_tasks
    from api.adapters import measurement
    from api.adapters.experiment_cards import build_experiment_card

    current_run_id = run_id or measurement.latest_run_id(project_slug)
    if not current_run_id:
        return []
    if current_rows is None:
        current_rows = measurement.run_rows(project_slug, current_run_id)
    evaluated = []
    with geolib.project_lock(project_slug):
        data = engine_tasks.load(project_slug)
        for ticket in data.get("tasks", []):
            if not isinstance(ticket, dict) or not isinstance(ticket.get("effect"), dict):
                continue
            spec = experiments.normalize_experiment(ticket)
            if spec.get("state") not in ("deployed", "observing"):
                continue
            baseline_run_id = spec.get("baseline_run_id")
            if not baseline_run_id or str(baseline_run_id) == str(current_run_id):
                continue
            baseline_rows = measurement.run_rows(project_slug, baseline_run_id)
            if spec.get("state") == "deployed":
                try:
                    spec = experiments.transition(spec, "observing", now=now)
                except ValueError:
                    continue
            result = experiments.evaluate_experiment(spec, baseline_rows, current_rows, now=now)
            spec["latest_run_id"] = current_run_id
            if result.get("verdict"):
                target = result["state"]
                try:
                    spec = experiments.transition(spec, target, now=now)
                except ValueError:
                    pass
                spec["verdict"] = result["verdict"]
                spec["verdict_at"] = geolib.now_iso()
                spec["evidence"] = result.get("evidence") or {}
            spec["card"] = build_experiment_card(ticket, spec)
            ticket["effect"] = spec
            ticket.setdefault("activity", []).append({
                "at": geolib.now_iso(),
                "actor": "system",
                "type": "effect_evaluation",
                "state": spec.get("state"),
                "verdict": spec.get("verdict"),
                "run_id": current_run_id,
                "baseline_run_id": baseline_run_id,
                "status": (spec.get("evidence") or {}).get("status"),
            })
            ticket["activity"] = ticket["activity"][-100:]
            evaluated.append({"ticket_id": ticket.get("id"), "effect": spec})
        if evaluated:
            engine_tasks.save(project_slug, data)
    return evaluated
