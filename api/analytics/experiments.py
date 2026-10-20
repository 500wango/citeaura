"""工单效果验证状态机与双重差分评估。

工单的 status 表示执行生命周期（todo/doing/done），effect.state 表示证据
生命周期（draft/deployed/observing/effective/ineffective/inconclusive）。
两者解耦：部署完成只证明改动上线，不证明 AI 可见性变化。
"""

import hashlib
from datetime import datetime, timedelta, timezone

from api.analytics import clustered_stats


EFFECT_STATES = ("draft", "deployed", "observing", "effective", "ineffective", "inconclusive")
METRICS = ("mention_rate", "top1_rate", "top3_rate")
OBSERVATION_DAYS = 14

# 只允许向前推进；inconclusive 可以重新进入观察，避免一次噪音永久关闭实验。
TRANSITIONS = {
    "draft": frozenset(("deployed",)),
    "deployed": frozenset(("observing",)),
    "observing": frozenset(("effective", "ineffective", "inconclusive")),
    "effective": frozenset(),
    "ineffective": frozenset(),
    "inconclusive": frozenset(("observing",)),
}


def _now(now=None):
    value = now or datetime.now(timezone.utc)
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _iso(value):
    return _now(value).isoformat().replace("+00:00", "Z")


def default_experiment(ticket=None):
    ticket = ticket or {}
    return {
        "version": 2,
        "state": "draft",
        "metric": "mention_rate",
        "target_question_ids": [],
        "control_question_ids": [],
        "observation_days": OBSERVATION_DAYS,
        "min_effect": clustered_stats.MIN_EFFECT,
        "confidence": clustered_stats.CONFIDENCE,
        "baseline_run_id": None,
        "latest_run_id": None,
        "deployed_at": None,
        "observation_started_at": None,
        "observation_ends_at": None,
        "verdict": None,
        "verdict_at": None,
        "evidence": {},
        "card": {},
        "ticket_id": ticket.get("id"),
    }


def normalize_experiment(ticket):
    ticket = ticket if isinstance(ticket, dict) else {}
    spec = dict(default_experiment(ticket))
    existing = ticket.get("effect")
    if isinstance(existing, dict):
        spec.update(existing)
    if spec.get("state") not in EFFECT_STATES:
        spec["state"] = "draft"
    if spec.get("metric") not in METRICS:
        spec["metric"] = "mention_rate"
    for key in ("target_question_ids", "control_question_ids"):
        values = spec.get(key)
        spec[key] = [str(item) for item in values] if isinstance(values, list) else []
    return spec


def can_transition(current, target, evidence=None):
    current = str(current or "draft")
    target = str(target or "")
    return target in TRANSITIONS.get(current, frozenset())


def transition(spec, target, evidence=None, now=None):
    spec = normalize_experiment({"effect": spec})
    if not can_transition(spec.get("state"), target, evidence):
        raise ValueError(f"invalid effect transition: {spec.get('state')} -> {target}")
    spec["state"] = target
    if target == "deployed":
        spec["deployed_at"] = _iso(now)
        spec["observation_started_at"] = _iso(now)
        spec["observation_ends_at"] = _iso(
            _now(now) + timedelta(days=int(spec.get("observation_days") or OBSERVATION_DAYS))
        )
    if target == "observing" and not spec.get("observation_started_at"):
        spec["observation_started_at"] = _iso(now)
        spec["observation_ends_at"] = _iso(
            _now(now) + timedelta(days=int(spec.get("observation_days") or OBSERVATION_DAYS))
        )
    return spec


def suggest_control_questions(target_ids, questions, limit=10):
    """从目标题组中稳定抽取对照题；对照题不能同时是目标题。"""
    targets = {str(item) for item in target_ids or ()}
    groups = {
        str(question.get("group") or "")
        for question in questions or ()
        if str(question.get("id") or "") in targets
    }
    candidates = [
        question for question in questions or ()
        if str(question.get("id") or "")
        and str(question.get("id")) not in targets
        and not question.get("brand_in_question")
        and (not groups or str(question.get("group") or "") in groups)
    ]
    candidates.sort(key=lambda question: hashlib.sha256(
        ("control:" + str(question.get("id"))).encode("utf-8")
    ).hexdigest())
    return [str(question.get("id")) for question in candidates[:max(0, int(limit))]]


def validate_binding(spec, questions):
    questions = {
        str(question.get("id")): question for question in questions or ()
        if isinstance(question, dict) and question.get("id")
    }
    targets = spec.get("target_question_ids") or []
    controls = spec.get("control_question_ids") or []
    if not targets:
        raise ValueError("target_question_ids is required")
    overlap = set(targets) & set(controls)
    if overlap:
        raise ValueError("target and control questions must not overlap: " + ", ".join(sorted(overlap)))
    missing = sorted((set(targets) | set(controls)) - set(questions))
    if missing:
        raise ValueError("unknown question ids: " + ", ".join(missing))
    probes = [qid for qid in targets + controls if questions[qid].get("brand_in_question")]
    if probes:
        raise ValueError("brand probe questions cannot be effect targets: " + ", ".join(probes))
    return spec


def _row_success(row, metric):
    return clustered_stats.success_value(row, metric)


def evaluate_experiment(spec, baseline_rows, current_rows, now=None):
    """返回评估结果；证据不足或观察期未结束时一律 inconclusive。"""
    spec = normalize_experiment({"effect": spec})
    now = _now(now)
    ends_at = spec.get("observation_ends_at")
    if ends_at:
        try:
            if now < _now(ends_at):
                return {
                    "state": "observing",
                    "verdict": None,
                    "reason": "observation_window_open",
                    "observation_ends_at": ends_at,
                    "evidence": {},
                }
        except ValueError:
            pass
    targets = set(spec.get("target_question_ids") or ())
    controls = set(spec.get("control_question_ids") or ())
    if not targets or not controls:
        return {"state": "inconclusive", "verdict": "inconclusive", "reason": "missing_question_binding", "evidence": {}}

    def subset(rows, ids):
        return [
            row for row in rows or ()
            if row.get("ok") is True and str(row.get("question_id") or "") in ids
        ]

    result = clustered_stats.difference_in_differences(
        subset(baseline_rows, targets),
        subset(current_rows, targets),
        subset(baseline_rows, controls),
        subset(current_rows, controls),
        success_key=spec.get("metric") or "mention_rate",
        confidence=float(spec.get("confidence") or clustered_stats.CONFIDENCE),
    )
    verdict = clustered_stats.effect_verdict(result, float(spec.get("min_effect") or 0))
    return {
        "state": verdict,
        "verdict": verdict,
        "reason": result.status,
        "evidence": result.as_dict(),
    }
