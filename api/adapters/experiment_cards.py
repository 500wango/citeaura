"""效果实验卡片：把状态、证据和限制条件转成可交付的展示对象。"""

from api.analytics import experiments

CAVEAT = (
    "Observational comparison, not a randomized controlled trial. "
    "Target and control question groups may differ in ways this design cannot "
    "observe; treat the verdict as evidence, not proof of causation."
)


def build_experiment_card(ticket, spec=None):
    ticket = ticket if isinstance(ticket, dict) else {}
    spec = experiments.normalize_experiment({**ticket, "effect": spec or ticket.get("effect")})
    evidence = spec.get("evidence") if isinstance(spec.get("evidence"), dict) else {}
    verdict = spec.get("verdict") or ("pending" if spec.get("state") in ("draft", "deployed", "observing") else None)
    return {
        "ticket_id": ticket.get("id") or spec.get("ticket_id"),
        "title": ticket.get("title"),
        "state": spec.get("state"),
        "verdict": verdict,
        "metric": spec.get("metric"),
        "target_question_ids": spec.get("target_question_ids") or [],
        "control_question_ids": spec.get("control_question_ids") or [],
        "observation_days": spec.get("observation_days"),
        "observation_started_at": spec.get("observation_started_at"),
        "observation_ends_at": spec.get("observation_ends_at"),
        "did_estimate": evidence.get("estimate"),
        "did_interval": [evidence.get("low"), evidence.get("high")],
        "status": evidence.get("status"),
        "target_clusters": evidence.get("target_clusters"),
        "control_clusters": evidence.get("control_clusters"),
        "caveat": CAVEAT,
        "needs_human_review": spec.get("state") == "inconclusive",
    }


def experiment_cards(tickets):
    cards = []
    for ticket in tickets or ():
        if not isinstance(ticket, dict):
            continue
        effect = ticket.get("effect")
        if not isinstance(effect, dict):
            continue
        cards.append(build_experiment_card(ticket, effect))
    return cards
