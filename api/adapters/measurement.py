"""采样口径、问题集版本和证据来源的文件系统适配。"""

import math
from collections import Counter
from datetime import datetime, timezone

from api.adapters import brand_identity
from api.adapters.engine import geolib
from api.adapters.global_scope import is_global_sample
from api.adapters.sampling_modes import MODE_API, MODE_MANUAL, MODE_SEARCH, for_provider, for_row


SCHEMA_VERSION = "1.0"
MIN_COMPARABLE_SAMPLES = 20
MIN_REPRESENTATIVE_PLATFORMS = 2


def wilson_interval(successes, samples):
    """返回二项比例的 95% Wilson 置信区间；零样本不产生区间。"""
    successes = int(successes)
    samples = int(samples)
    if samples < 0 or successes < 0 or successes > samples:
        raise ValueError("successes must be between zero and samples")
    if not samples:
        return None
    z = 1.96
    rate = successes / samples
    denominator = 1 + z ** 2 / samples
    center = (rate + z ** 2 / (2 * samples)) / denominator
    margin = z * math.sqrt((rate * (1 - rate) + z ** 2 / (4 * samples)) / samples) / denominator
    return {
        "confidence_level": 0.95,
        "successes": successes,
        "samples": samples,
        "lower": round(max(0, center - margin), 4),
        "upper": round(min(1, center + margin), 4),
    }


def question_set_version(config):
    return brand_identity.question_set_version(config)


def _mode(provider):
    return for_provider(provider)


def _sample_summary(project_slug):
    directory = geolib.project_dir(project_slug)
    sample_files = sorted((directory / "samples").glob("*.jsonl")) if (directory / "samples").exists() else []
    config = geolib.load_config(project_slug)
    rows = [
        row for row in geolib.read_jsonl(sample_files[-1])
        if is_global_sample(row) and brand_identity.is_current_sample(row, config)
    ] if sample_files else []
    per_platform = {}
    success = 0
    for row in rows:
        platform = row.get("platform") or "unknown"
        entry = per_platform.setdefault(platform, {"total": 0, "successful": 0, "failed": 0})
        entry["total"] += 1
        if row.get("ok"):
            success += 1
            entry["successful"] += 1
        else:
            entry["failed"] += 1
    return {"total": len(rows), "successful": success, "failed": len(rows) - success, "per_platform": per_platform}


def _metrics_summary(metrics):
    summary = metrics.get("sample_summary") if isinstance(metrics, dict) else None
    if isinstance(summary, dict):
        total = int(summary.get("total") or 0)
        successful = int(summary.get("successful") or 0)
        failed = int(summary.get("failed") or max(0, total - successful))
        return {"total": total, "successful": successful, "failed": failed}
    total = int((metrics or {}).get("sample_count") or 0)
    return {"total": total, "successful": total, "failed": 0}


def _question_version(metrics):
    if not isinstance(metrics, dict):
        return None
    return metrics.get("question_set_version") or ((metrics.get("provenance") or {}).get("question_set") or {}).get("version")


def _cohort_signature(metrics):
    platforms = metrics.get("platforms") if isinstance(metrics, dict) else {}
    provenance = (metrics or {}).get("provenance") or {}
    modes = {
        item.get("engine_code"): (item.get("sampling_mode"), item.get("model"))
        for item in provenance.get("platforms", [])
        if isinstance(item, dict) and item.get("engine_code")
    }
    return sorted((code, modes.get(code)) for code in (platforms or {}))


def _weighted_mention(metrics):
    mentions = 0.0
    samples = 0
    for item in ((metrics or {}).get("platforms") or {}).values():
        rate = item.get("mention_rate")
        count = int(item.get("samples") or 0)
        if rate is None or count <= 0:
            continue
        mentions += float(rate) * count
        samples += count
    return (mentions / samples if samples else None), samples


def _platform_count(metrics):
    """Count platforms that contributed at least one successful visibility sample."""
    summary = (metrics or {}).get("sample_summary") or {}
    per_platform = summary.get("per_platform") if isinstance(summary, dict) else {}
    if isinstance(per_platform, dict) and per_platform:
        return sum(
            int(item.get("successful") or 0) > 0
            for item in per_platform.values()
            if isinstance(item, dict)
        )
    return sum(
        int(item.get("samples") or 0) > 0
        for item in ((metrics or {}).get("platforms") or {}).values()
        if isinstance(item, dict)
    )


def _confidence(metrics, effective_samples):
    platform_count = _platform_count(metrics)
    limitations = []
    if effective_samples < MIN_COMPARABLE_SAMPLES:
        limitations.append(
            f"Only {effective_samples} valid samples; at least {MIN_COMPARABLE_SAMPLES} are required per period"
        )
    if platform_count < MIN_REPRESENTATIVE_PLATFORMS:
        limitations.append(
            f"Only {platform_count} sampled platform(s); at least {MIN_REPRESENTATIVE_PLATFORMS} are required for cross-platform conclusions"
        )
    sufficient = not limitations
    return {
        "level": "representative_baseline" if sufficient else "limited_baseline",
        "label": "Representative baseline" if sufficient else "Limited baseline",
        "sufficient": sufficient,
        "platform_count": platform_count,
        "minimum_samples": MIN_COMPARABLE_SAMPLES,
        "minimum_platforms": MIN_REPRESENTATIVE_PLATFORMS,
        "limitations": limitations,
        "allows_global_conclusions": sufficient,
        "allows_trend_attribution": False,
    }


def sampling_quality(project_slug):
    """返回当前样本质量、跨期可比性和保守的趋势解释。"""
    directory = geolib.project_dir(project_slug) / "metrics"
    files = sorted(directory.glob("*.json")) if directory.exists() else []
    metrics = [geolib.read_json(path, {}) or {} for path in files[-2:]]
    if not metrics:
        return {
            "available": False,
            "current": {
                "total": 0, "successful": 0, "failed": 0, "failure_rate": None,
                "effective_visibility_samples": 0, "platform_count": 0,
            },
            "confidence": {
                "level": "unavailable", "label": "No baseline", "sufficient": False,
                "platform_count": 0, "minimum_samples": MIN_COMPARABLE_SAMPLES,
                "minimum_platforms": MIN_REPRESENTATIVE_PLATFORMS,
                "limitations": ["No sampling data available"],
                "allows_global_conclusions": False, "allows_trend_attribution": False,
            },
            "comparable": False,
            "comparison_reason": "No sampling data available yet",
            "trend": {"status": "unavailable", "label": "No trend data", "delta_pp": None},
        }

    current = metrics[-1]
    current_summary = _metrics_summary(current)
    current_total = current_summary["total"]
    current_summary["failure_rate"] = round(current_summary["failed"] / current_total, 4) if current_total else None
    current_summary["question_set_version"] = _question_version(current)
    current_summary["date"] = current.get("date")
    current_rate, current_n = _weighted_mention(current)
    current_summary["effective_visibility_samples"] = current_n
    current_summary["mention_rate"] = round(current_rate, 4) if current_rate is not None else None
    confidence = _confidence(current, current_n)
    current_summary["platform_count"] = confidence["platform_count"]

    if len(metrics) < 2:
        return {
            "available": True,
            "current": current_summary,
            "confidence": confidence,
            "comparable": False,
            "comparison_reason": "Single baseline run, at least two periods required to determine trends",
            "trend": {"status": "unavailable", "label": "Single baseline", "delta_pp": None},
        }

    previous = metrics[-2]
    previous_rate, previous_n = _weighted_mention(previous)
    previous_confidence = _confidence(previous, previous_n)
    comparable = True
    reason = "Question set, platforms, and sampling modes consistent"
    current_version = _question_version(current)
    previous_version = _question_version(previous)
    if not current_version or not previous_version:
        comparable, reason = False, "Historical data missing question set version, methodology consistency unconfirmed"
    elif current_version != previous_version:
        comparable, reason = False, "Question set version changed; periods cannot be directly compared"
    elif current.get("cohort_id") and previous.get("cohort_id") and current["cohort_id"] != previous["cohort_id"]:
        comparable, reason = False, "Sampling cohort changed; periods cannot be directly compared"
    elif _cohort_signature(current) != _cohort_signature(previous):
        comparable, reason = False, "Sampling platforms, modes, or models changed; periods cannot be directly compared"
    elif current_rate is None or previous_rate is None:
        comparable, reason = False, "Missing valid visibility samples"

    delta = (current_rate - previous_rate) if comparable else None
    if not comparable:
        trend = {"status": "not_comparable", "label": "Incomparable methodology", "delta_pp": None}
    elif min(current_n, previous_n) < MIN_COMPARABLE_SAMPLES:
        trend = {
            "status": "insufficient_samples",
            "label": "Insufficient samples",
            "delta_pp": round(delta * 100, 2),
            "detail": f"Valid sample counts are {previous_n} and {current_n}; at least {MIN_COMPARABLE_SAMPLES} required per period",
        }
    elif min(confidence["platform_count"], previous_confidence["platform_count"]) < MIN_REPRESENTATIVE_PLATFORMS:
        trend = {
            "status": "insufficient_platforms",
            "label": "Limited platform coverage",
            "delta_pp": round(delta * 100, 2),
            "detail": (
                f"Sampled platform counts are {previous_confidence['platform_count']} and "
                f"{confidence['platform_count']}; at least {MIN_REPRESENTATIVE_PLATFORMS} required per period"
            ),
        }
    else:
        variance = previous_rate * (1 - previous_rate) / previous_n + current_rate * (1 - current_rate) / current_n
        z_score = abs(delta) / math.sqrt(variance) if variance > 0 else (float("inf") if delta else 0.0)
        noteworthy = abs(delta) >= 0.05 and z_score >= 1.96
        trend = {
            "status": "noteworthy" if noteworthy else "normal_fluctuation",
            "label": "Worth monitoring" if noteworthy else "Normal variance",
            "direction": "up" if delta > 0 else ("down" if delta < 0 else "flat"),
            "delta_pp": round(delta * 100, 2),
            "z_score": round(z_score, 3) if math.isfinite(z_score) else None,
            "detail": "Statistical variance does not imply optimization attribution; evaluate with ticket deployment timelines and multi-period trends.",
        }
    return {
        "available": True,
        "current": current_summary,
        "confidence": confidence,
        "previous": {
            "date": previous.get("date"),
            "question_set_version": previous_version,
            "effective_visibility_samples": previous_n,
            "mention_rate": round(previous_rate, 4) if previous_rate is not None else None,
            "platform_count": previous_confidence["platform_count"],
        },
        "comparable": comparable,
        "comparison_reason": reason,
        "trend": trend,
    }


ENGINE_DROP_ALERT_PP = 10.0


def _platform_mention(metrics, code):
    item = ((metrics or {}).get("platforms") or {}).get(code) or {}
    rate = item.get("mention_rate")
    count = int(item.get("samples") or 0)
    if rate is None or count <= 0:
        return None, 0
    return float(rate), count


def regression_events(project_slug):
    """Return statistically noteworthy mention-rate drops between the last two periods."""
    quality = sampling_quality(project_slug)
    if not quality.get("comparable"):
        return []
    trend = quality.get("trend") or {}
    if trend.get("status") != "noteworthy" or trend.get("direction") != "down":
        return []
    directory = geolib.project_dir(project_slug) / "metrics"
    files = sorted(directory.glob("*.json")) if directory.exists() else []
    metrics = [geolib.read_json(path, {}) or {} for path in files[-2:]]
    if len(metrics) < 2:
        return []
    previous, current = metrics[0], metrics[1]
    events = [{
        "kind": "overall",
        "engine_code": None,
        "previous_rate": (quality.get("previous") or {}).get("mention_rate"),
        "current_rate": (quality.get("current") or {}).get("mention_rate"),
        "delta_pp": trend.get("delta_pp"),
        "previous_date": (quality.get("previous") or {}).get("date"),
        "current_date": (quality.get("current") or {}).get("date"),
    }]
    codes = sorted(set((previous.get("platforms") or {})) & set((current.get("platforms") or {})))
    for code in codes:
        previous_rate, previous_n = _platform_mention(previous, code)
        current_rate, current_n = _platform_mention(current, code)
        if previous_rate is None or current_rate is None:
            continue
        if min(previous_n, current_n) < MIN_COMPARABLE_SAMPLES:
            continue
        delta_pp = round((current_rate - previous_rate) * 100, 2)
        if delta_pp <= -ENGINE_DROP_ALERT_PP:
            events.append({
                "kind": "engine",
                "engine_code": code,
                "previous_rate": round(previous_rate, 4),
                "current_rate": round(current_rate, 4),
                "delta_pp": delta_pp,
                "previous_date": previous.get("date"),
                "current_date": current.get("date"),
            })
    return events


def record_sampling(
    project_slug,
    *,
    source="api",
    requested_platforms=None,
    limit=None,
    repeat=1,
    job_id=None,
    byok_codes=None,
    pool_codes=None,
):
    """写入不含密钥的采样 manifest，并把摘要挂到最新 metrics。"""
    if not (geolib.project_dir(project_slug) / "geo.json").is_file():
        return None
    config = geolib.load_config(project_slug)
    import sample

    requested = requested_platforms or config.get("platforms") or sorted(set(sample.PROVIDERS) | set(sample.MANUAL_ONLY))
    if isinstance(requested, str):
        requested = [item.strip() for item in requested.split(",") if item.strip()]
    byok = set(byok_codes or ())
    pool = set(pool_codes or ())
    sample_files = sorted((geolib.project_dir(project_slug) / "samples").glob("*.jsonl"))
    actual_mode_counts = {}
    if sample_files:
        for row in geolib.read_jsonl(sample_files[-1]):
            code = row.get("platform")
            if code and row.get("ok"):
                actual_mode_counts.setdefault(code, Counter())[for_row(row)] += 1
    platforms = []
    for code in requested:
        if code in sample.PROVIDERS:
            provider = sample.PROVIDERS[code]
            provider_source = "byok" if code in byok else ("platform_pool" if code in pool else "unavailable")
            actual_modes = actual_mode_counts.get(code)
            platforms.append({
                "engine_code": code,
                "engine_name": provider.get("name", code),
                "sampling_mode": actual_modes.most_common(1)[0][0] if actual_modes else _mode(provider),
                "sampling_mode_source": "sample_evidence" if actual_modes else "provider_configuration",
                "model": sample.model_for(code),
                "source": provider_source,
            })
        elif code in sample.MANUAL_ONLY:
            name, _market = sample.MANUAL_ONLY[code]
            platforms.append({
                "engine_code": code,
                "engine_name": name,
                "sampling_mode": MODE_MANUAL,
                "sampling_mode_source": "provider_configuration",
                "model": None,
                "source": "manual",
            })
    qset = question_set_version(config)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "job_id": job_id,
        "source": source,
        "question_set": qset,
        "requested_platforms": list(requested),
        "limit": limit,
        "repeat": repeat,
        "platforms": platforms,
    }
    directory = geolib.project_dir(project_slug) / "sampling-manifests"
    directory.mkdir(parents=True, exist_ok=True)
    suffix = str(job_id or datetime.now(timezone.utc).strftime("%H%M%S%f"))
    manifest_path = directory / f"{datetime.now(timezone.utc).date().isoformat()}-{suffix}.json"
    geolib.write_json(manifest_path, manifest)

    metrics_files = sorted((geolib.project_dir(project_slug) / "metrics").glob("*.json"))
    if metrics_files:
        metrics = geolib.read_json(metrics_files[-1], {}) or {}
        manifest["run_id"] = metrics.get("run_id")
        manifest["cohort_id"] = metrics.get("cohort_id")
        manifest["engine_question_set_id"] = metrics.get("question_set_id")
        geolib.write_json(manifest_path, manifest)
        metrics["provenance"] = manifest
        metrics["question_set_version"] = qset["version"]
        metrics["sample_summary"] = _sample_summary(project_slug)
        geolib.write_json(metrics_files[-1], metrics)
    return manifest
