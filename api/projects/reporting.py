"""项目报告读取和报告契约规范化。"""

from pathlib import Path

from api.adapters import audit_presentation, brand_identity, global_scope, measurement, product_insights, report_quality, sampling_modes
from api.adapters.engine import ENGINE_KEY_ENV, geolib, load_custom_providers, load_tenant_keys, with_tenant_read_context
from api.projects.access import error
from api.projects.sampling import has_sampling_access


def latest_file(directory: Path, pattern: str):
    files = sorted(directory.glob(pattern)) if directory.exists() else []
    return files[-1] if files else None


def grade_for_score(score):
    if score is None:
        return None
    if score >= 90:
        return "A"
    if score >= 75:
        return "B"
    if score >= 60:
        return "C"
    return "D"


def engine_rows_by_mode(item, platform_rows):
    """Keep knowledge, retrieval, and product-surface cohorts on separate rows."""
    grouped = {}
    for row in platform_rows:
        grouped.setdefault(sampling_modes.for_row(row), []).append(row)
    if not grouped:
        return [{
            "engine_code": item.get("platform"),
            "engine_name": item.get("label") or item.get("platform"),
            "sampling_mode": sampling_modes.MODE_API,
            "sampling_mode_code": sampling_modes.CODE_PARAMETRIC,
            "mention_rate": item.get("mention"),
            "mention_interval": None,
            "median_rank": item.get("pos_median"),
            "sample_count": item.get("samples", 0),
            "citation_share": item.get("cite_share"),
            "citation_counts": item.get("cite_counts", [0, 0]),
            "top_sources": item.get("top_sources", []),
            "example": item.get("example"),
            "negative_sample_count": item.get("neg_n", 0),
        }]
    rows = []
    for mode, mode_rows in grouped.items():
        ok_rows = [row for row in mode_rows if row.get("ok")]
        mentioned = [row for row in ok_rows if (row.get("analysis") or {}).get("brand_mentioned")]
        ranks = [
            (row.get("analysis") or {}).get("brand_rank")
            for row in mentioned
            if (row.get("analysis") or {}).get("brand_rank")
        ]
        mention_rate = (len(mentioned) / len(ok_rows)) if ok_rows else None
        rows.append({
            "engine_code": item.get("platform"),
            "engine_name": item.get("label") or item.get("platform"),
            "sampling_mode": mode,
            "sampling_mode_code": sampling_modes.code_for_label(mode),
            "mention_rate": mention_rate,
            "mention_interval": measurement.wilson_interval(len(mentioned), len(ok_rows)),
            "median_rank": sorted(ranks)[len(ranks) // 2] if ranks else None,
            "sample_count": len(ok_rows),
            "citation_share": item.get("cite_share") if len(grouped) == 1 else None,
            "citation_counts": item.get("cite_counts", [0, 0]) if len(grouped) == 1 else [0, 0],
            "top_sources": item.get("top_sources", []) if len(grouped) == 1 else [],
            "example": item.get("example"),
            "negative_sample_count": sum(
                1 for row in ok_rows if (row.get("analysis") or {}).get("negative_cues")
            ),
        })
    mode_order = {
        sampling_modes.MODE_SEARCH: 0,
        sampling_modes.MODE_API: 1,
        sampling_modes.MODE_MANUAL: 2,
    }
    rows.sort(key=lambda item: mode_order.get(item["sampling_mode"], 9))
    return rows


def include_configured_engines(db, tenant, engines):
    """把已配置但尚未采到样本的引擎补成 Unmeasured 行。"""
    import sample

    rows = list(engines or [])
    seen = {str(item.get("engine_code") or "") for item in rows}
    configured = set(load_tenant_keys(db, tenant.id))
    custom = load_custom_providers(db, tenant.id)
    for code in list(ENGINE_KEY_ENV) + [provider["code"] for provider in custom]:
        if code in seen:
            continue
        if code not in configured and not any(provider["code"] == code for provider in custom):
            if code not in ENGINE_KEY_ENV:
                continue
        provider = sample.PROVIDERS.get(code) or next(
            (item for item in custom if item["code"] == code),
            {"name": code, "search": False},
        )
        rows.append({
            "engine_code": code,
            "engine_name": provider.get("name") or code,
            "sampling_mode": sampling_modes.for_provider(provider),
            "sampling_mode_code": sampling_modes.code_for_provider(provider),
            "mention_rate": None,
            "mention_interval": None,
            "median_rank": None,
            "sample_count": 0,
            "citation_share": None,
            "citation_counts": [0, 0],
            "top_sources": [],
            "example": None,
            "negative_sample_count": 0,
        })
        seen.add(code)
    return rows


def provider_identity(code, item, config):
    """Return one stable provider identity object for API/UI consumers."""
    import sample

    code = str(code or "")
    item = item if isinstance(item, dict) else {}
    config = config if isinstance(config, dict) else {}
    labels = config.get("provider_labels") if isinstance(config.get("provider_labels"), dict) else {}
    model_ids = config.get("provider_model_ids") if isinstance(config.get("provider_model_ids"), dict) else {}
    provider = sample.PROVIDERS.get(code) or {}
    provider_name = str(labels.get(code) or item.get("engine_name") or item.get("label") or provider.get("name") or code)
    model_id = str(model_ids.get(code) or item.get("model_id") or provider.get("model") or "")
    if (code == "custom" or code.startswith("custom_")) and not labels.get(code):
        provider_name = "Configured OpenAI-compatible provider"
    mode = item.get("sampling_mode") or sampling_modes.for_provider(provider)
    return {
        "engine_code": code,
        "provider_name": provider_name,
        "model_id": model_id or None,
        "sampling_mode": mode,
        "sampling_mode_code": item.get("sampling_mode_code") or sampling_modes.code_for_label(mode),
        "funding_source": item.get("source") or item.get("funding_source") or "unknown",
    }


def current_sample_rows(project_slug, config=None):
    """读取当前问题集样本，统一过滤历史身份和市场残留。"""
    config = config or geolib.load_config(project_slug)
    project_directory = geolib.project_dir(project_slug)
    sample_path = latest_file(project_directory / "samples", "*.jsonl")
    rows = [
        row for row in (geolib.read_jsonl(sample_path) if sample_path else [])
        if global_scope.is_global_sample(row, config) and brand_identity.is_current_sample(row, config)
    ]
    return sample_path, rows


def product_report(project_slug, metrics):
    """Normalize filesystem artifacts into the stable product report contract."""
    import analytics

    project_directory = geolib.project_dir(project_slug)
    config = geolib.load_config(project_slug)
    audit = audit_presentation.present_audit(project_slug)
    sample_path, rows = current_sample_rows(project_slug, config)
    engine_rows = analytics.engines(project_slug, rows, metrics)
    insights = product_insights.build(
        project_slug,
        rows,
        config,
        geolib.read_json(project_directory / "blueprint.json", None),
        expected_cohorts=((metrics or {}).get("provenance") or {}).get("platforms") or [],
    )

    engines = []
    citations = {}
    for item in engine_rows:
        platform_rows = [row for row in rows if row.get("platform") == item.get("platform")]
        engines.extend(engine_rows_by_mode(item, platform_rows))
        for row in platform_rows:
            if not row.get("ok"):
                continue
            for domain in (row.get("analysis") or {}).get("cited_domains") or []:
                evidence = citations.setdefault(domain, {"count": 0, "engines": set(), "questions": set()})
                evidence["count"] += 1
                engine_name = row.get("platform_name") or row.get("platform")
                if engine_name:
                    evidence["engines"].add(engine_name)
                if row.get("question"):
                    evidence["questions"].add(row["question"])

    measured = [item for item in engines if item["mention_rate"] is not None and item["sample_count"]]
    for item in engines:
        identity = provider_identity(item.get("engine_code"), item, config)
        item["provider_identity"] = identity
        item["provider_name"] = identity["provider_name"]
        item["model_id"] = identity["model_id"]
    measured_count = sum(item["sample_count"] for item in measured)
    mention_rate = (
        sum(item["mention_rate"] * item["sample_count"] for item in measured) / measured_count
        if measured_count else None
    )
    channels = [
        {
            "domain": domain,
            "count": evidence["count"],
            "engines": sorted(evidence["engines"]),
            "question_count": len(evidence["questions"]),
            "sample_questions": sorted(evidence["questions"])[:3],
        }
        for domain, evidence in sorted(citations.items(), key=lambda pair: (-pair[1]["count"], pair[0]))
    ]
    return {
        **(metrics or {}),
        "mention_rate": round(mention_rate, 4) if mention_rate is not None else None,
        "grade": audit.get("applicable_grade") or grade_for_score(audit.get("avg_score")),
        "engines": engines,
        "channels": channels,
        "audit": audit,
        "insights": insights,
        "measured": bool(measured),
        "sample_artifact": sample_path.stem if sample_path else None,
    }


def project_report_payload(db, tenant, project):
    """读取一个项目的稳定报告契约，供浏览器和只读集成 API 共用。"""
    with with_tenant_read_context(tenant, project.slug):
        global_scope.normalize_project(project.slug)
        path = latest_file(geolib.project_dir(project.slug) / "metrics", "*.json")
        if path is None:
            error(404, "report_not_found")
        metrics = geolib.read_json(path, None)
        product = product_report(project.slug, metrics)
        quality = report_quality.assess(project.slug, has_sampling_access(db, tenant, project))
        tasks_data = geolib.read_json(geolib.project_dir(project.slug) / "tasks.json", {}) or {}
    issues = quality.get("issues") if isinstance(quality.get("issues"), list) else []
    tickets = tasks_data.get("tasks") if isinstance(tasks_data.get("tasks"), list) else []
    primary_issue = next((item for item in issues if item.get("severity") in {"critical", "warning"}), None) or (issues[0] if issues else None)
    primary_ticket = next((item for item in tickets if item.get("status") not in {"done", "completed"}), None) or (tickets[0] if tickets else None)
    confidence = quality.get("confidence") if isinstance(quality.get("confidence"), dict) else {}
    measured = bool(product.get("measured"))
    user_summary = {
        "headline": (
            primary_issue.get("message") if primary_issue else
            ("AI visibility has been measured" if measured else "Your diagnostic is ready to review")
        ),
        "why_it_matters": (
            "Review the highest-priority finding before interpreting visibility results."
            if primary_issue else "Use the evidence and action plan to decide what to improve first."
        ),
        "recommended_action": (primary_issue or {}).get("action") or (primary_ticket or {}).get("action") or "Review the action plan",
        "next_route": (primary_issue or {}).get("route") or "plan",
        "evidence_scope": {
            "sample_count": product.get("sample_count") or 0,
            "measured": measured,
            "confidence": confidence.get("label") or confidence.get("level") or "unmeasured",
            "sampling_mode": (quality.get("measurement_quality") or {}).get("sampling_mode"),
        },
        "limitations": [
            issue.get("message") for issue in issues
            if issue.get("severity") in {"info", "warning"} and issue is not primary_issue
        ][:3],
        "primary_finding": {
            "code": (primary_issue or {}).get("code"),
            "ticket_id": (primary_ticket or {}).get("id"),
        },
    }
    return {
        "report": product,
        "date": metrics.get("date") if metrics else None,
        "sample_artifact": (metrics.get("run_id") or metrics.get("date")) if metrics else None,
        "report_quality": quality,
        "user_summary": user_summary,
    }
