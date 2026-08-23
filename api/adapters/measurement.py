"""采样口径、问题集版本和证据来源的文件系统适配。"""

import math
from collections import Counter
from datetime import datetime, timezone

from api import config
from api.adapters import brand_identity
from api.adapters.engine import geolib
from api.adapters.global_scope import is_global_sample
from api.adapters.sampling_modes import MODE_API, MODE_MANUAL, MODE_SEARCH, for_provider, for_row


SCHEMA_VERSION = "1.0"
MIN_COMPARABLE_SAMPLES = 20
MIN_REPRESENTATIVE_PLATFORMS = 2
MIN_QUESTION_SAMPLES = 3


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


def question_cohort_evidence(rows, config, minimum=MIN_QUESTION_SAMPLES, expected_cohorts=None):
    """按问题和 provider+sampling mode 计算可执行的证据缺口。"""
    config = config if isinstance(config, dict) else {}
    minimum = max(1, int(minimum or MIN_QUESTION_SAMPLES))
    questions = [
        item for item in (config.get("questions") or [])
        if isinstance(item, dict) and item.get("id")
    ]
    grouped = {}
    cohorts = {}
    for row in rows or ():
        if not isinstance(row, dict) or not row.get("ok") or row.get("brand_in_question"):
            continue
        question_id = str(row.get("question_id") or "").strip()
        platform = str(row.get("platform") or "").strip()
        if not question_id or not platform:
            continue
        mode = for_row(row)
        key = f"{mode}|{platform}"
        grouped.setdefault((question_id, key), 0)
        grouped[(question_id, key)] += 1
        cohorts.setdefault(key, {
            "key": key,
            "engine_code": platform,
            "engine_name": row.get("platform_name") or platform,
            "sampling_mode": mode,
        })

    for expected in expected_cohorts or ():
        if not isinstance(expected, dict):
            continue
        platform = str(expected.get("engine_code") or expected.get("platform") or "").strip()
        mode = _normalize_mode(expected.get("sampling_mode"))
        if not platform or not mode:
            continue
        key = f"{mode}|{platform}"
        cohorts.setdefault(key, {
            "key": key,
            "engine_code": platform,
            "engine_name": expected.get("engine_name") or expected.get("provider_name") or platform,
            "sampling_mode": mode,
            "funding_source": expected.get("funding_source") or expected.get("source"),
        })

    cohort_rows = [cohorts[key] for key in sorted(cohorts)]
    items = []
    gaps = []
    for question in questions:
        question_id = str(question["id"])
        cells = []
        missing = 0
        for cohort in cohort_rows:
            samples = int(grouped.get((question_id, cohort["key"]), 0))
            gap = max(0, minimum - samples)
            missing += gap
            cells.append({
                **cohort,
                "samples": samples,
                "required": minimum,
                "missing": gap,
                "sufficient": samples >= minimum,
            })
        total_samples = sum(cell["samples"] for cell in cells)
        sufficient = bool(cells) and all(cell["sufficient"] for cell in cells)
        item = {
            "id": question_id,
            "text": question.get("text") or "",
            "samples": total_samples,
            "required": minimum * len(cells) if cells else minimum,
            "missing_samples": missing if cells else minimum,
            "sufficient": sufficient,
            "cohorts": cells,
        }
        items.append(item)
        if not sufficient:
            gaps.append(item)

    return {
        "minimum_samples": minimum,
        "cohorts": cohort_rows,
        "items": items,
        "total": len(items),
        "measured": sum(1 for item in items if item["samples"] > 0),
        "sufficient": sum(1 for item in items if item["sufficient"]),
        "gaps": gaps,
    }


def delivery_question_evidence(project_slug, funding=None, custom_providers=None):
    """按当前配置和实际 funding 返回交付前的问题级 cohort 状态。

    历史 sampling provenance 会保留当时请求过但未运行的平台。交付资格不能
    把这些 skipped 平台继续算入当前分母，因此这里仅把当前配置中有 funding
    的 provider 作为 active measurement cohort。
    """
    directory = geolib.project_dir(project_slug)
    config = geolib.load_config(project_slug) if (directory / "geo.json").is_file() else {}
    config = config if isinstance(config, dict) else {}
    import sample

    funding = funding if isinstance(funding, dict) else {}
    funded = {
        str(code).strip().lower()
        for code in (set(funding.get("keys") or {}) | set(funding.get("pool_codes") or ()))
        if str(code).strip()
    }
    custom_by_code = {
        str(item.get("code")): item
        for item in (custom_providers or ())
        if isinstance(item, dict) and item.get("code")
    }
    project_market = config.get("market") if config.get("market") in ("cn", "global", "both") else "both"

    def market_matches(provider_market):
        provider_market = provider_market or "both"
        return project_market == "both" or provider_market in ("both", project_market)
    configured = list(dict.fromkeys(
        str(code).strip().lower()
        for code in (config.get("platforms") or [])
        if str(code).strip()
    ))
    # The worker synchronizes newly funded providers into geo.json before this
    # helper runs. Do not infer activity from every tenant key: an unused key
    # must not silently become a cohort outside the project's market.
    active_codes = configured
    expected = []
    for code in active_codes:
        if code not in funded:
            continue
        provider = sample.PROVIDERS.get(code) or custom_by_code.get(code)
        if not isinstance(provider, dict):
            continue
        if not market_matches(provider.get("market")):
            continue
        expected.append({
            "engine_code": code,
            "engine_name": provider.get("name") or code,
            "model": provider.get("model_id") or provider.get("model"),
            "sampling_mode": _mode(provider),
            "source": "platform_pool" if code in set(funding.get("pool_codes") or ()) else "byok",
        })

    config_questions = {
        str(item.get("id")): item for item in (config.get("questions") or [])
        if isinstance(item, dict) and item.get("id")
    }
    sample_files = sorted((directory / "samples").glob("*.jsonl")) if (directory / "samples").exists() else []
    rows = []
    if sample_files:
        rows = [
            row for row in geolib.read_jsonl(sample_files[-1])
            if isinstance(row, dict)
            and row.get("ok")
            and is_global_sample(row, config)
            and brand_identity.is_current_sample(row, config)
        ]
    observed_modes = {}
    for row in rows:
        platform = str(row.get("platform") or "").strip()
        if platform:
            observed_modes.setdefault(platform, Counter())[for_row(row)] += 1
    for item in expected:
        modes = observed_modes.get(item["engine_code"])
        if modes:
            # Provider configuration advertises the preferred mode, while the
            # receipt must use the mode actually returned by this run.
            item["sampling_mode"] = modes.most_common(1)[0][0]
    evidence = question_cohort_evidence(
        rows,
        config,
        MIN_QUESTION_SAMPLES,
        expected_cohorts=expected,
    )
    metrics_files = sorted((directory / "metrics").glob("*.json")) if (directory / "metrics").exists() else []
    latest_metrics = geolib.read_json(metrics_files[-1], {}) if metrics_files else {}
    previous_platforms = {
        str(item.get("engine_code")): (
            _normalize_mode(item.get("sampling_mode")),
            item.get("model"),
        )
        for item in ((latest_metrics or {}).get("provenance") or {}).get("platforms") or []
        if isinstance(item, dict)
        and item.get("engine_code")
        and item.get("source") in ("byok", "platform_pool")
    }
    current_platforms = {
        str(item["engine_code"]): (_normalize_mode(item.get("sampling_mode")), item.get("model"))
        for item in expected
    }
    cohort_changed = bool(previous_platforms and previous_platforms != current_platforms)
    gaps = evidence.get("gaps") or []
    target_question_ids = list(config_questions)
    if not cohort_changed:
        target_question_ids = [str(item.get("id")) for item in gaps if item.get("id")]
    measured_platforms = sorted({
        str(cell.get("engine_code"))
        for item in evidence.get("items") or []
        for cell in item.get("cohorts") or []
        if int(cell.get("samples") or 0) > 0
    })
    configured_unfunded = sorted(set(configured) - funded)
    return {
        "question_set_version": question_set_version(config),
        "configured_platforms": configured,
        "funded_platforms": sorted(funded),
        "active_cohorts": expected,
        "measured_platforms": measured_platforms,
        "unfunded_platforms": configured_unfunded,
        "cohort_changed": cohort_changed,
        "needs_sampling": bool(expected and target_question_ids),
        "target_platforms": [item["engine_code"] for item in expected],
        "target_question_ids": target_question_ids,
        "ready": bool(expected) and not gaps and not cohort_changed,
        "evidence": evidence,
    }


def _mode(provider):
    return for_provider(provider)


def _normalize_mode(value):
    value = str(value or "").strip()
    if value in (MODE_API, MODE_SEARCH, MODE_MANUAL):
        return value
    lowered = value.casefold()
    if "search" in lowered or "ground" in lowered or "联网" in value:
        return MODE_SEARCH
    if "manual" in lowered or "product interface" in lowered or "人工" in value:
        return MODE_MANUAL
    return MODE_API


def _sample_summary(project_slug):
    directory = geolib.project_dir(project_slug)
    sample_files = sorted((directory / "samples").glob("*.jsonl")) if (directory / "samples").exists() else []
    config = geolib.load_config(project_slug)
    rows = [
        row for row in geolib.read_jsonl(sample_files[-1])
        if is_global_sample(row, config) and brand_identity.is_current_sample(row, config)
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


def _run_rows(project_slug, run_id=None):
    directory = geolib.project_dir(project_slug)
    sample_directory = directory / "samples"
    if run_id:
        path = sample_directory / f"{run_id}.jsonl"
    else:
        files = sorted(sample_directory.glob("*.jsonl")) if sample_directory.exists() else []
        path = files[-1] if files else None
    rows = geolib.read_jsonl(path) if path and path.is_file() else []
    if run_id:
        rows = [row for row in rows if str(row.get("run_id") or "") == str(run_id)]
    return rows


def build_sampling_receipt(
    project_slug,
    *,
    result=None,
    requested_platforms=None,
    question_ids=None,
    limit=None,
    repeat=1,
    job_id=None,
    funding=None,
):
    """从本轮样本生成不含密钥的 Worker 执行回执。"""
    metrics = result if isinstance(result, dict) else {}
    run_id = metrics.get("run_id")
    rows = _run_rows(project_slug, run_id)
    if not rows and run_id is None:
        rows = _run_rows(project_slug)
    requested = requested_platforms
    if isinstance(requested, str):
        requested = [item.strip() for item in requested.split(",") if item.strip()]
    requested = list(dict.fromkeys(str(item).strip() for item in (requested or []) if str(item).strip()))
    requested_questions = question_ids
    if isinstance(requested_questions, str):
        requested_questions = [item.strip() for item in requested_questions.split(",") if item.strip()]
    requested_questions = list(dict.fromkeys(
        str(item).strip() for item in (requested_questions or []) if str(item).strip()
    ))
    funded = set()
    worker_diagnostic = {}
    if isinstance(funding, dict):
        funded.update(str(code) for code in (funding.get("keys") or {}))
        funded.update(str(code) for code in (funding.get("pool_codes") or ()))
        worker_diagnostic = funding.get("_worker_diagnostic") or {}
    per_platform = {}
    for row in rows:
        code = str(row.get("platform") or "unknown")
        item = per_platform.setdefault(code, {
            "requested": code in requested,
            "successful": 0,
            "failed": 0,
            "questions": {},
            "errors": Counter(),
            "model_ids": set(),
            "sampling_modes": set(),
            "engine_name": row.get("platform_name") or code,
        })
        question_id = str(row.get("question_id") or "")
        if question_id:
            cell = item["questions"].setdefault(question_id, {"successful": 0, "failed": 0})
            cell["successful" if row.get("ok") else "failed"] += 1
        if row.get("ok"):
            item["successful"] += 1
        else:
            item["failed"] += 1
            if row.get("error"):
                item["errors"][str(row["error"])[:200]] += 1
        if row.get("raw_model"):
            item["model_ids"].add(str(row["raw_model"]))
        item["sampling_modes"].add(for_row(row))
    for item in per_platform.values():
        item["status"] = "succeeded" if item["successful"] else "failed"
        item["errors"] = [
            {"message": message, "count": count}
            for message, count in item["errors"].most_common(5)
        ]
        item["model_ids"] = sorted(item["model_ids"])
        item["model_id"] = item["model_ids"][0] if len(item["model_ids"]) == 1 else None
        item["sampling_modes"] = sorted(item["sampling_modes"])
        item["sampling_mode"] = item["sampling_modes"][0] if len(item["sampling_modes"]) == 1 else None
    skipped = []
    for code in requested:
        if code in per_platform:
            continue
        skipped.append({
            "engine_code": code,
            "reason": "missing_worker_funding" if code not in funded else "no_successful_samples",
        })
        per_platform[code] = {
            "requested": True,
            "successful": 0,
            "failed": 0,
            "questions": {},
            "errors": [],
            "model_ids": [],
            "model_id": None,
            "sampling_modes": [],
            "sampling_mode": None,
            "engine_name": code,
            "status": "skipped",
        }
    successful = sum(int(item.get("successful") or 0) for item in per_platform.values())
    failed = sum(int(item.get("failed") or 0) for item in per_platform.values())
    receipt = {
        "schema_version": "1.0",
        "job_id": job_id,
        "run_id": run_id,
        "source_revision": config.source_revision(),
        "question_set_version": _question_version(metrics),
        "requested_platforms": requested,
        "requested_question_ids": requested_questions,
        "limit": limit,
        "repeat": int(repeat or 1),
        "funded_platforms": sorted(funded),
        "worker": worker_diagnostic,
        "successful_samples": successful,
        "failed_samples": failed,
        "skipped_platforms": skipped,
        "status": "succeeded" if successful else ("failed" if failed else "skipped"),
        "platforms": per_platform,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    return receipt


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


def _platform_comparisons(previous, current):
    """Return comparable platform deltas with intervals from the two metrics."""
    comparisons = []
    codes = sorted(set((previous.get("platforms") or {})) & set((current.get("platforms") or {})))
    for code in codes:
        previous_rate, previous_n = _platform_mention(previous, code)
        current_rate, current_n = _platform_mention(current, code)
        if previous_rate is None or current_rate is None:
            continue
        comparisons.append({
            "engine_code": code,
            "previous_rate": round(previous_rate, 4),
            "current_rate": round(current_rate, 4),
            "delta_pp": round((current_rate - previous_rate) * 100, 2),
            "previous_interval": wilson_interval(round(previous_rate * previous_n), previous_n),
            "current_interval": wilson_interval(round(current_rate * current_n), current_n),
            "previous_samples": previous_n,
            "current_samples": current_n,
        })
    return comparisons


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
            "attribution": {
                "status": "unavailable",
                "ready": False,
                "label": "No comparable period",
                "method": "fixed question set, platform, model, and sampling mode",
                "comparisons": [],
            },
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
            "attribution": {
                "status": "insufficient_periods",
                "ready": False,
                "label": "Single baseline",
                "method": "fixed question set, platform, model, and sampling mode",
                "comparisons": [],
            },
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
    platform_comparisons = _platform_comparisons(previous, current) if comparable else []
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
    attribution_ready = bool(
        comparable
        and min(current_n, previous_n) >= MIN_COMPARABLE_SAMPLES
        and min(confidence["platform_count"], previous_confidence["platform_count"]) >= MIN_REPRESENTATIVE_PLATFORMS
    )
    attribution = {
        "status": "ready" if attribution_ready else ("not_comparable" if not comparable else "insufficient_evidence"),
        "ready": attribution_ready,
        "label": "Comparable measurement" if attribution_ready else (
            "Methodology changed" if not comparable else "More comparable evidence required"
        ),
        "method": "fixed question set, platform, model, and sampling mode",
        "comparisons": platform_comparisons,
        "deployment_evidence_required": True,
        "note": "A comparable delta is not proof of causation without ticket deployment evidence.",
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
        "attribution": attribution,
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
    question_ids=None,
    limit=None,
    repeat=1,
    job_id=None,
    byok_codes=None,
    pool_codes=None,
    result=None,
    funding=None,
):
    """写入不含密钥的采样 manifest，并把摘要挂到最新 metrics。"""
    if not (geolib.project_dir(project_slug) / "geo.json").is_file():
        return None
    config = geolib.load_config(project_slug)
    import sample

    requested = requested_platforms or config.get("platforms") or sorted(set(sample.PROVIDERS) | set(sample.MANUAL_ONLY))
    if isinstance(requested, str):
        requested = [item.strip() for item in requested.split(",") if item.strip()]
    selected_questions = []
    for value in question_ids or ():
        value = str(value).strip()
        if value and value not in selected_questions:
            selected_questions.append(value)
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
        "requested_question_ids": selected_questions,
        "limit": limit,
        "repeat": repeat,
        "platforms": platforms,
    }
    receipt = build_sampling_receipt(
        project_slug,
        result=result,
        requested_platforms=requested,
        question_ids=selected_questions,
        limit=limit,
        repeat=repeat,
        job_id=job_id,
        funding=funding or {"keys": dict.fromkeys(byok), "pool_codes": pool},
    )
    manifest["sampling_receipt"] = receipt
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
        metrics["sampling_receipt"] = receipt
        geolib.write_json(metrics_files[-1], metrics)
    return manifest
