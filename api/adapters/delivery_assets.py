"""交付资产清单与就绪状态编排。

资产文件的具体渲染仍由 :mod:`delivery` 负责；本模块只处理资产管线的
编排、状态归类和清单写入，避免交付文档编排继续承担资产状态聚合。
"""

import json
from pathlib import Path

from api import config as app_config
from api.adapters.engine import geolib
from api.adapters import measurement


class AssetOperations:
    """资产编排所需的具体文件操作，由交付 facade 显式注入。"""

    def __init__(
        self,
        facts_delivery_data,
        write_facts_asset,
        render_generated_assets,
        copy_drafts,
        copy_other_assets,
        asset_record,
        insight_mode_name,
        safe_display,
    ):
        self.facts_delivery_data = facts_delivery_data
        self.write_facts_asset = write_facts_asset
        self.render_generated_assets = render_generated_assets
        self.copy_drafts = copy_drafts
        self.copy_other_assets = copy_other_assets
        self.asset_record = asset_record
        self.insight_mode_name = insight_mode_name
        self.safe_display = safe_display


def classify_pack_readiness(audit, summary, sampling, facts_review):
    """根据审计、采样和资产状态拆分诊断就绪与实施就绪。"""
    audit = audit if isinstance(audit, dict) else {}
    summary = summary if isinstance(summary, dict) else {}
    sampling = sampling if isinstance(sampling, dict) else {}
    facts_review = facts_review if isinstance(facts_review, dict) else {}
    confidence = sampling.get("confidence") or {}
    page_count = int(audit.get("page_count") or 0)

    implementation_backlog = []
    needs_review = int(summary.get("needs_review") or 0)
    templates = int(summary.get("template") or 0)
    if needs_review:
        implementation_backlog.append(
            f"{needs_review} implementation asset(s) require factual or editorial review before publication"
        )
    if templates:
        implementation_backlog.append(
            f"{templates} template asset(s) are implementation outlines, not finished publishable pages"
        )
    if not confidence.get("sufficient"):
        label = str(confidence.get("label") or "unmeasured")
        implementation_backlog.append(
            f"AI visibility is {label.lower()}; representative 20/2 sampling is required "
            "only before publishing measured mention rates"
        )
    if audit.get("score_status") and audit.get("score_status") != "reported":
        implementation_backlog.append(
            "Site score is withheld until scoring coverage reaches the reporting threshold"
        )
    if facts_review.get("available") and not facts_review.get("approved"):
        implementation_backlog.append(
            "Brand facts are site-extracted and not yet approved for publication-derived assets"
        )

    diagnostic_blockers = []
    if page_count < 1:
        diagnostic_blockers.append("Audit has no crawled pages")

    implementation_ready = not implementation_backlog and int(summary.get("ready") or 0) > 0
    visibility_ready = bool(confidence.get("sufficient"))
    diagnostic_ready = not diagnostic_blockers
    if implementation_ready:
        pack_kind = "implementation"
    elif diagnostic_ready:
        pack_kind = "diagnostic"
    else:
        pack_kind = "review"
    return {
        "pack_kind": pack_kind,
        "readiness": "customer_ready" if diagnostic_ready else "review_required",
        "diagnostic_ready": diagnostic_ready,
        "visibility_ready": visibility_ready,
        "implementation_ready": implementation_ready,
        "readiness_issues": diagnostic_blockers,
        "implementation_backlog": implementation_backlog,
    }


def write_asset_index(
    project_slug,
    project_directory,
    directory,
    config,
    audit,
    blueprint,
    measurement_scope=None,
    *,
    operations,
):
    """生成交付包的资产目录、状态摘要和测量范围快照。"""
    project_directory = Path(project_directory)
    directory = Path(directory)
    source = project_directory / "assets"
    destination = directory / "assets"
    destination.mkdir(parents=True, exist_ok=True)
    made = []
    facts, facts_text = operations.facts_delivery_data(project_slug, project_directory, config)
    operations.write_facts_asset(destination, facts, facts_text, made)
    generated = operations.render_generated_assets(
        project_slug,
        project_directory,
        source,
        destination,
        config,
        audit,
        blueprint,
    )
    made.extend(generated["paths"])
    schema_decisions = generated["schema_decisions"]
    operations.copy_drafts(source, destination, blueprint, made)
    operations.copy_other_assets(source, destination, blueprint, made)
    facts_review_pending = bool(facts_text) and not bool(facts.get("approved") or facts.get("reviewed"))
    records = [
        operations.asset_record(destination, path, facts_review_pending=facts_review_pending)
        for path in sorted(set(made))
    ]
    decisions_by_path = {item["path"]: item for item in schema_decisions}
    for record in records:
        decision_path = record["path"].removeprefix("templates/")
        decision = decisions_by_path.get(decision_path)
        if not decision:
            continue
        decision["path"] = record["path"]
        if decision.get("requires_review"):
            record["issues"].append("Schema applicability is inferred and requires confirmation")
            if record["status"] == "ready":
                record["status"] = "needs_review"
    records.sort(key=lambda item: (item["status"], item["path"]))
    summary = {
        status: sum(item["status"] == status for item in records)
        for status in ("ready", "needs_review", "template")
    }
    sampling = measurement.sampling_quality(project_slug)
    confidence = sampling.get("confidence") or {}
    facts_review = {
        "available": bool(facts_text),
        "approved": bool(facts.get("approved") or facts.get("reviewed")),
        "machine_verified": bool((facts.get("verification") or {}).get("publication_ready"))
        and not bool(facts.get("reviewed")),
    }
    classification = classify_pack_readiness(audit, summary, sampling, facts_review)
    index = {
        "generated_at": geolib.now_iso(),
        "source_revision": app_config.source_revision(),
        "language": "English",
        "pack_kind": classification["pack_kind"],
        "readiness": classification["readiness"],
        "diagnostic_ready": classification["diagnostic_ready"],
        "visibility_ready": classification["visibility_ready"],
        "implementation_ready": classification["implementation_ready"],
        "readiness_issues": classification["readiness_issues"],
        "implementation_backlog": classification["implementation_backlog"],
        "report_confidence": confidence,
        "audit_confidence": {
            "status": audit.get("score_status"),
            "score_coverage": audit.get("score_coverage"),
            "minimum_score_coverage": audit.get("minimum_score_coverage"),
            "evaluated_pages": audit.get("evaluated_page_count"),
            "eligible_pages": audit.get("score_eligible_page_count"),
        },
        "facts_review": facts_review,
        "schema_selection": {
            "policy": "Specialized Schema.org types require project evidence",
            "included": [item for item in schema_decisions if item["status"] == "included"],
            "omitted": [item for item in schema_decisions if item["status"] == "omitted"],
        },
        "summary": summary,
        "assets": records,
    }
    if isinstance(measurement_scope, dict):
        index["measurement_scope"] = {
            "question_set_version": measurement_scope.get("question_set_version"),
            "configured_platforms": list(measurement_scope.get("configured_platforms") or []),
            "funded_platforms": list(measurement_scope.get("funded_platforms") or []),
            "active_cohorts": [
                {
                    key: (
                        operations.insight_mode_name(item.get(key))
                        if key == "sampling_mode"
                        else operations.safe_display(item.get(key), "Configured provider")
                    )
                    for key in ("engine_code", "engine_name", "model", "sampling_mode", "source")
                    if item.get(key) is not None
                }
                for item in (measurement_scope.get("active_cohorts") or [])
                if isinstance(item, dict)
            ],
            "measured_platforms": list(measurement_scope.get("measured_platforms") or []),
            "unfunded_platforms": list(measurement_scope.get("unfunded_platforms") or []),
            "cohort_changed": bool(measurement_scope.get("cohort_changed")),
            "question_ready": bool(measurement_scope.get("ready")),
            "minimum_question_samples": measurement.MIN_QUESTION_SAMPLES,
            "question_evidence": {
                "total": int((measurement_scope.get("evidence") or {}).get("total") or 0),
                "measured": int((measurement_scope.get("evidence") or {}).get("measured") or 0),
                "sufficient": int((measurement_scope.get("evidence") or {}).get("sufficient") or 0),
                "gaps": [
                    {
                        "question_id": operations.safe_display(item.get("id"), "Configured question"),
                        "samples": int(item.get("samples") or 0),
                        "required": int(item.get("required") or 0),
                        "missing_samples": int(item.get("missing_samples") or 0),
                    }
                    for item in (measurement_scope.get("evidence") or {}).get("gaps") or []
                    if isinstance(item, dict) and item.get("id")
                ],
            },
        }
    (destination / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n",
        "utf-8",
    )
    return index
