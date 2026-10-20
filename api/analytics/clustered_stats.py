"""题级聚类统计：把轮次当重复测量，把题目当独立簇。

单条样本不是独立观测：同一道题的 5 轮回答高度相关。这里先用题内聚合，
再对题目做有放回重采样，避免把 5 轮当成 5 道题而低估区间。
纯标准库实现，固定种子保证同一输入得到同一区间。
"""

import hashlib
import json
import math
import random
from dataclasses import dataclass


DEFAULT_REPEAT = 5
MIN_CLUSTERS = 8
MIN_CLUSTER_SAMPLES = 5
BOOTSTRAP_ITERATIONS = 1000
MIN_EFFECT = 0.05
CONFIDENCE = 0.95


@dataclass(frozen=True)
class ClusterRate:
    key: tuple
    samples: int
    successes: int
    rate: float


@dataclass(frozen=True)
class IntervalResult:
    estimate: float | None
    low: float | None
    high: float | None
    confidence: float
    method: str
    status: str
    clusters: int
    samples: int
    seed: int
    iterations: int

    def as_dict(self):
        return {
            "estimate": self.estimate,
            "low": self.low,
            "high": self.high,
            "confidence": self.confidence,
            "method": self.method,
            "status": self.status,
            "clusters": self.clusters,
            "samples": self.samples,
            "seed": self.seed,
            "iterations": self.iterations,
        }


@dataclass(frozen=True)
class ComparisonResult:
    previous: IntervalResult
    current: IntervalResult
    delta: float | None
    delta_low: float | None
    delta_high: float | None
    status: str
    matched_clusters: int
    unmatched_previous: int
    unmatched_current: int
    confidence: float
    method: str
    seed: int

    def as_dict(self):
        return {
            "previous": self.previous.as_dict(),
            "current": self.current.as_dict(),
            "delta": self.delta,
            "delta_low": self.delta_low,
            "delta_high": self.delta_high,
            "status": self.status,
            "matched_clusters": self.matched_clusters,
            "unmatched_previous": self.unmatched_previous,
            "unmatched_current": self.unmatched_current,
            "confidence": self.confidence,
            "method": self.method,
            "seed": self.seed,
        }


@dataclass(frozen=True)
class DiDResult:
    estimate: float | None
    low: float | None
    high: float | None
    status: str
    confidence: float
    target_clusters: int
    control_clusters: int
    method: str
    seed: int

    def as_dict(self):
        return {
            "estimate": self.estimate,
            "low": self.low,
            "high": self.high,
            "status": self.status,
            "confidence": self.confidence,
            "target_clusters": self.target_clusters,
            "control_clusters": self.control_clusters,
            "method": self.method,
            "seed": self.seed,
        }


def stable_seed(*parts):
    payload = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return int.from_bytes(hashlib.sha256(payload.encode("utf-8")).digest()[:8], "big")


def _percentile(values, quantile):
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _round(value):
    return None if value is None else round(float(value), 4)


def success_value(row, success_key="mention"):
    """从一条样本提取成功布尔值；analysis 缺字段时按未提及处理。"""
    if callable(success_key):
        return bool(success_key(row))
    analysis = row.get("analysis") if isinstance(row.get("analysis"), dict) else {}
    key = str(success_key or "mention")
    if key in ("mention", "mention_rate", "brand_mentioned"):
        return bool(analysis.get("brand_mentioned"))
    if key in ("top1", "top3"):
        if not analysis.get("brand_mentioned"):
            return False
        rank = int(analysis.get("brand_rank") or 0)
        return rank == 1 if key == "top1" else 1 <= rank <= 3
    return bool(row.get(key))


def usable_rows(rows):
    """只保留成功样本；失败、超时和拒答单列，不能进分母。"""
    return [row for row in rows or () if isinstance(row, dict) and row.get("ok") is True]


def cluster_key(row, cluster_fields=("question_id",)):
    return tuple(str(row.get(field) or "") for field in cluster_fields)


def cluster_rates(rows, success_key="mention", cluster_fields=("question_id",)):
    """题内先聚合轮次与平台，题间等权。"""
    grouped = {}
    for row in usable_rows(rows):
        key = cluster_key(row, cluster_fields)
        if not any(key):
            continue
        samples, successes = grouped.get(key, (0, 0))
        grouped[key] = (samples + 1, successes + int(success_value(row, success_key)))
    return [
        ClusterRate(key=key, samples=samples, successes=successes, rate=successes / samples)
        for key, (samples, successes) in sorted(grouped.items())
        if samples
    ]


def _weighted_rate(clusters):
    samples = sum(item.samples for item in clusters)
    if not samples:
        return None
    return sum(item.successes for item in clusters) / samples


def _interval(clusters, seed, confidence=CONFIDENCE, iterations=BOOTSTRAP_ITERATIONS):
    clusters = list(clusters)
    samples = sum(item.samples for item in clusters)
    estimate = _weighted_rate(clusters)
    if not clusters:
        return IntervalResult(None, None, None, confidence, "cluster_bootstrap", "no_samples", 0, 0, seed, iterations)
    if len(clusters) < MIN_CLUSTERS:
        return IntervalResult(
            _round(estimate), None, None, confidence, "cluster_bootstrap",
            "insufficient_clusters", len(clusters), samples, seed, iterations,
        )
    if samples < MIN_CLUSTER_SAMPLES:
        return IntervalResult(
            _round(estimate), None, None, confidence, "cluster_bootstrap",
            "insufficient_samples", len(clusters), samples, seed, iterations,
        )
    if estimate in (0.0, 1.0):
        return IntervalResult(
            _round(estimate), _round(estimate), _round(estimate), confidence,
            "cluster_bootstrap", "degenerate", len(clusters), samples, seed, iterations,
        )
    rng = random.Random(seed)
    draws = []
    for _ in range(iterations):
        picked = [clusters[rng.randrange(len(clusters))] for _ in clusters]
        rate = _weighted_rate(picked)
        if rate is not None:
            draws.append(rate)
    if not draws:
        return IntervalResult(
            _round(estimate), None, None, confidence, "cluster_bootstrap",
            "insufficient_samples", len(clusters), samples, seed, iterations,
        )
    alpha = (1 - confidence) / 2
    return IntervalResult(
        _round(estimate),
        _round(_percentile(draws, alpha)),
        _round(_percentile(draws, 1 - alpha)),
        confidence,
        "cluster_bootstrap",
        "ok",
        len(clusters),
        samples,
        seed,
        iterations,
    )


def cluster_bootstrap_interval(
    rows, success_key="mention", cluster_fields=("question_id",),
    confidence=CONFIDENCE, iterations=BOOTSTRAP_ITERATIONS, seed=None,
):
    keyed = cluster_rates(rows, success_key, cluster_fields)
    key_seed = seed if seed is not None else stable_seed(
        "interval", success_key, cluster_fields,
        [(item.key, item.samples, item.successes) for item in keyed],
    )
    return _interval(keyed, key_seed, confidence, iterations)


def paired_cluster_bootstrap(
    previous_rows, current_rows, success_key="mention",
    cluster_fields=("question_id", "platform", "sample_mode"),
    confidence=CONFIDENCE, iterations=BOOTSTRAP_ITERATIONS, seed=None,
):
    """两期只比较都存在的簇；新增或缺失题目不会伪装成变化。"""
    previous = {item.key: item for item in cluster_rates(previous_rows, success_key, cluster_fields)}
    current = {item.key: item for item in cluster_rates(current_rows, success_key, cluster_fields)}
    shared = sorted(set(previous) & set(current))
    previous_interval = _interval(
        [previous[key] for key in shared], stable_seed("paired-prev", shared), confidence, iterations,
    )
    current_interval = _interval(
        [current[key] for key in shared], stable_seed("paired-curr", shared), confidence, iterations,
    )
    if not shared:
        return ComparisonResult(
            previous_interval, current_interval, None, None, None,
            "no_matched_clusters", 0, len(previous), len(current),
            confidence, "paired_cluster_bootstrap", 0,
        )
    unmatched_previous = len(set(previous) - set(shared))
    unmatched_current = len(set(current) - set(shared))

    keyed_seed = seed if seed is not None else stable_seed(
        "paired", success_key, cluster_fields, shared,
        [(key, previous[key].samples, previous[key].successes, current[key].samples, current[key].successes)
         for key in shared],
    )
    previous_rate = _weighted_rate([previous[key] for key in shared])
    current_rate = _weighted_rate([current[key] for key in shared])
    delta = current_rate - previous_rate
    if len(shared) < MIN_CLUSTERS:
        return ComparisonResult(
            previous_interval, current_interval, _round(delta), None, None,
            "insufficient_clusters", len(shared), unmatched_previous, unmatched_current,
            confidence, "paired_cluster_bootstrap", keyed_seed,
        )
    rng = random.Random(keyed_seed)
    draws = []
    for _ in range(iterations):
        picked = [shared[rng.randrange(len(shared))] for _ in shared]
        prev_samples = sum(previous[key].samples for key in picked)
        curr_samples = sum(current[key].samples for key in picked)
        if not prev_samples or not curr_samples:
            continue
        prev_rate = sum(previous[key].successes for key in picked) / prev_samples
        curr_rate = sum(current[key].successes for key in picked) / curr_samples
        draws.append(curr_rate - prev_rate)
    if not draws:
        return ComparisonResult(
            previous_interval, current_interval, _round(delta), None, None,
            "insufficient_samples", len(shared), unmatched_previous, unmatched_current,
            confidence, "paired_cluster_bootstrap", keyed_seed,
        )
    alpha = (1 - confidence) / 2
    return ComparisonResult(
        previous_interval,
        current_interval,
        _round(delta),
        _round(_percentile(draws, alpha)),
        _round(_percentile(draws, 1 - alpha)),
        "ok",
        len(shared),
        unmatched_previous,
        unmatched_current,
        confidence,
        "paired_cluster_bootstrap",
        keyed_seed,
    )


def _delta_draws(previous_items, current_items, rng, iterations):
    shared = sorted(set(previous_items) & set(current_items))
    if len(shared) < MIN_CLUSTERS:
        return shared, [], None
    previous_rate = _weighted_rate([previous_items[key] for key in shared])
    current_rate = _weighted_rate([current_items[key] for key in shared])
    delta = current_rate - previous_rate
    draws = []
    for _ in range(iterations):
        picked = [shared[rng.randrange(len(shared))] for _ in shared]
        prev_samples = sum(previous_items[key].samples for key in picked)
        curr_samples = sum(current_items[key].samples for key in picked)
        if not prev_samples or not curr_samples:
            continue
        prev_rate = sum(previous_items[key].successes for key in picked) / prev_samples
        curr_rate = sum(current_items[key].successes for key in picked) / curr_samples
        draws.append(curr_rate - prev_rate)
    return shared, draws, delta


def difference_in_differences(
    target_previous_rows, target_current_rows, control_previous_rows, control_current_rows,
    success_key="mention", cluster_fields=("question_id", "platform", "sample_mode"),
    confidence=CONFIDENCE, iterations=BOOTSTRAP_ITERATIONS, seed=None,
):
    """目标组变化减去对照组变化，抵消同期共同波动。"""
    target_prev = {item.key: item for item in cluster_rates(target_previous_rows, success_key, cluster_fields)}
    target_curr = {item.key: item for item in cluster_rates(target_current_rows, success_key, cluster_fields)}
    control_prev = {item.key: item for item in cluster_rates(control_previous_rows, success_key, cluster_fields)}
    control_curr = {item.key: item for item in cluster_rates(control_current_rows, success_key, cluster_fields)}
    base_seed = seed if seed is not None else stable_seed(
        "did", success_key, cluster_fields,
        [(key, target_prev[key].samples, target_curr[key].samples) for key in sorted(set(target_prev) & set(target_curr))],
        [(key, control_prev[key].samples, control_curr[key].samples) for key in sorted(set(control_prev) & set(control_curr))],
    )
    rng = random.Random(base_seed)
    target_keys, target_draws, target_delta = _delta_draws(target_prev, target_curr, rng, iterations)
    control_keys, control_draws, control_delta = _delta_draws(control_prev, control_curr, rng, iterations)
    if len(target_keys) < MIN_CLUSTERS or len(control_keys) < MIN_CLUSTERS:
        return DiDResult(
            None, None, None, "insufficient_clusters", confidence,
            len(target_keys), len(control_keys), "difference_in_differences", base_seed,
        )
    if target_delta is None or control_delta is None or not target_draws or not control_draws:
        return DiDResult(
            None, None, None, "insufficient_samples", confidence,
            len(target_keys), len(control_keys), "difference_in_differences", base_seed,
        )
    estimate = target_delta - control_delta
    limit = min(len(target_draws), len(control_draws))
    draws = [target_draws[index] - control_draws[index] for index in range(limit)]
    alpha = (1 - confidence) / 2
    return DiDResult(
        _round(estimate),
        _round(_percentile(draws, alpha)),
        _round(_percentile(draws, 1 - alpha)),
        "ok",
        confidence,
        len(target_keys),
        len(control_keys),
        "difference_in_differences",
        base_seed,
    )


def effect_verdict(result, min_effect=MIN_EFFECT):
    """下界超过阈值才算有效；上界低于阈值才算无效；其余无法判断。"""
    if result is None or result.status != "ok" or result.low is None or result.high is None:
        return "inconclusive"
    if result.low >= min_effect:
        return "effective"
    if result.high < min_effect:
        return "ineffective"
    return "inconclusive"
