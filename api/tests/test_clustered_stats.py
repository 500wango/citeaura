"""题级聚类统计的回归测试。"""

from api.analytics import clustered_stats as S


def _row(question, ok=True, mention=False, platform="openai", mode="api", rank=0):
    return {
        "ok": ok,
        "question_id": question,
        "platform": platform,
        "sample_mode": mode,
        "round": 1,
        "analysis": {"brand_mentioned": mention, "brand_rank": rank},
    }


def _question_rows(question, mentions, total=5, **kwargs):
    return [_row(question, mention=index < mentions, **kwargs) for index in range(total)]


def test_clusters_weight_questions_not_rounds():
    rows = _question_rows("q1", 5) + _question_rows("q2", 0)
    rates = S.cluster_rates(rows)
    assert len(rates) == 2
    assert sum(item.samples for item in rates) == 10
    interval = S.cluster_bootstrap_interval(rows)
    assert interval.clusters == 2
    assert interval.status == "insufficient_clusters"
    assert interval.estimate == 0.5


def test_failed_rows_are_excluded_from_denominator():
    rows = _question_rows("q1", 3) + [_row("q1", ok=False, mention=True)]
    rates = S.cluster_rates(rows)
    assert rates[0].samples == 5
    assert rates[0].successes == 3


def test_same_input_produces_same_interval():
    rows = []
    for question in range(12):
        rows.extend(_question_rows(f"q{question}", question % 5))
    first = S.cluster_bootstrap_interval(rows, iterations=300)
    second = S.cluster_bootstrap_interval(rows, iterations=300)
    assert first == second
    assert first.status == "ok"
    assert first.low <= first.estimate <= first.high


def test_degenerate_all_success_interval_is_point():
    rows = []
    for question in range(10):
        rows.extend(_question_rows(f"q{question}", 5))
    interval = S.cluster_bootstrap_interval(rows)
    assert interval.status == "degenerate"
    assert interval.low == interval.high == 1.0


def test_paired_bootstrap_ignores_unmatched_questions():
    previous = []
    current = []
    for question in range(10):
        previous.extend(_question_rows(f"q{question}", 1))
        current.extend(_question_rows(f"q{question}", 2))
    # 新题只有当前期，不能抬高 delta 的簇数。
    current.extend(_question_rows("q-new", 5))
    result = S.paired_cluster_bootstrap(previous, current, iterations=400)
    assert result.matched_clusters == 10
    assert result.unmatched_current == 1
    assert result.status == "ok"
    assert result.delta == 0.2
    assert result.delta_low <= result.delta <= result.delta_high


def test_paired_bootstrap_requires_enough_clusters():
    previous = _question_rows("q1", 1)
    current = _question_rows("q1", 2)
    result = S.paired_cluster_bootstrap(previous, current)
    assert result.status == "insufficient_clusters"
    assert result.delta_low is None


def test_difference_in_differences_removes_common_trend():
    target_previous, target_current = [], []
    control_previous, control_current = [], []
    for question in range(10):
        target_previous.extend(_question_rows(f"t{question}", 1, platform="openai"))
        target_current.extend(_question_rows(f"t{question}", 4, platform="openai"))
        control_previous.extend(_question_rows(f"c{question}", 1, platform="openai"))
        control_current.extend(_question_rows(f"c{question}", 2, platform="openai"))
    result = S.difference_in_differences(
        target_previous, target_current, control_previous, control_current, iterations=400,
    )
    assert result.status == "ok"
    assert result.estimate == 0.4
    assert S.effect_verdict(result) == "effective"


def test_effect_verdict_returns_inconclusive_without_interval():
    assert S.effect_verdict(None) == "inconclusive"
    rows = _question_rows("q1", 1)
    result = S.paired_cluster_bootstrap(rows, rows)
    assert S.effect_verdict(result) == "inconclusive"
