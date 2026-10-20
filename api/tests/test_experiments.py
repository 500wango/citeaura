"""效果验证状态机与双重差分测试。"""

from datetime import datetime, timedelta, timezone

import pytest

from api.analytics import experiments as E


def _rows(prefix, count, mentions, total=5):
    rows = []
    for question in range(count):
        for index in range(total):
            rows.append({
                "ok": True,
                "question_id": f"{prefix}{question}",
                "platform": "openai",
                "sample_mode": "api",
                "round": index + 1,
                "analysis": {"brand_mentioned": index < mentions, "brand_rank": 1},
            })
    return rows


def _spec(targets, controls, ended=True):
    now = datetime.now(timezone.utc)
    return {
        "version": 2,
        "state": "observing",
        "metric": "mention_rate",
        "target_question_ids": targets,
        "control_question_ids": controls,
        "observation_days": 14,
        "min_effect": 0.05,
        "confidence": 0.95,
        "observation_ends_at": (
            (now - timedelta(days=1)).isoformat() if ended
            else (now + timedelta(days=1)).isoformat()
        ),
        "baseline_run_id": "baseline",
    }


def test_transitions_only_move_forward_and_allow_inconclusive_retry():
    assert E.can_transition("draft", "deployed") is True
    assert E.can_transition("draft", "effective") is False
    assert E.can_transition("deployed", "observing") is True
    assert E.can_transition("observing", "effective") is True
    assert E.can_transition("effective", "observing") is False
    assert E.can_transition("inconclusive", "observing") is True
    with pytest.raises(ValueError):
        E.transition({"state": "draft"}, "effective")


def test_transition_deployed_starts_observation_window():
    spec = E.transition(E.default_experiment(), "deployed", now="2026-10-01T00:00:00Z")
    assert spec["state"] == "deployed"
    assert spec["observation_started_at"].startswith("2026-10-01")
    assert spec["observation_ends_at"].startswith("2026-10-15")


def test_control_questions_exclude_targets():
    questions = [
        {"id": f"q{index:03d}", "group": "recommendation"} for index in range(20)
    ]
    controls = E.suggest_control_questions(["q000", "q001"], questions, limit=5)
    assert len(controls) == 5
    assert not {"q000", "q001"} & set(controls)


def test_binding_rejects_overlap_and_unknown_ids():
    questions = [{"id": "q001", "group": "recommendation"}]
    with pytest.raises(ValueError):
        E.validate_binding({"target_question_ids": ["q001"], "control_question_ids": ["q001"]}, questions)
    with pytest.raises(ValueError):
        E.validate_binding({"target_question_ids": ["q999"], "control_question_ids": []}, questions)
    E.validate_binding({"target_question_ids": ["q001"], "control_question_ids": []}, questions)


def test_positive_target_effect_is_effective():
    targets = [f"t{index}" for index in range(10)]
    controls = [f"c{index}" for index in range(10)]
    baseline = _rows("t", 10, 1) + _rows("c", 10, 1)
    current = _rows("t", 10, 5) + _rows("c", 10, 1)
    result = E.evaluate_experiment(_spec(targets, controls), baseline, current)
    assert result["verdict"] == "effective"
    assert result["evidence"]["estimate"] == 0.8


def test_common_trend_is_not_effective():
    targets = [f"t{index}" for index in range(10)]
    controls = [f"c{index}" for index in range(10)]
    baseline = _rows("t", 10, 1) + _rows("c", 10, 1)
    current = _rows("t", 10, 3) + _rows("c", 10, 3)
    result = E.evaluate_experiment(_spec(targets, controls), baseline, current)
    # 目标与对照同幅变化：处理后差异为零，不足以声称有效。
    assert result["verdict"] == "ineffective"
    assert result["evidence"]["estimate"] == 0.0


def test_open_observation_window_returns_observing():
    targets = [f"t{index}" for index in range(10)]
    controls = [f"c{index}" for index in range(10)]
    baseline = _rows("t", 10, 1) + _rows("c", 10, 1)
    current = _rows("t", 10, 5) + _rows("c", 10, 1)
    result = E.evaluate_experiment(_spec(targets, controls, ended=False), baseline, current)
    assert result["state"] == "observing"
    assert result["verdict"] is None
