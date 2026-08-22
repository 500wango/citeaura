"""把引擎样本聚合为面向产品的提示词和竞品洞察。"""

from collections import defaultdict
from pathlib import Path
import re

from api.adapters import brand_facts, measurement, sampling_modes
from api.adapters.engine import geolib


MIN_ALERT_SAMPLES = 5
MIN_QUESTION_SAMPLES = measurement.MIN_QUESTION_SAMPLES
MAX_CAMPAIGN_PROPOSALS = 12


def _usable_rows(rows):
    return [
        row for row in rows or []
        if isinstance(row, dict)
        and row.get("ok")
        and isinstance(row.get("analysis"), dict)
        and not row.get("brand_in_question")
    ]


def _sentiment_summary(rows):
    """Classify observed brand context into cautious, neutral, or enthusiastic bands."""
    labels = {"enthusiastic": 0, "neutral": 0, "cautious": 0, "negative": 0}
    positive_cues = re.compile(r"\b(best|excellent|great|leading|recommended|top|strong choice|reliable)\b", re.I)
    for row in _usable_rows(rows):
        analysis = row.get("analysis") or {}
        negative = list(analysis.get("negative_cues") or [])
        answer = str(row.get("answer") or "")
        if negative and analysis.get("brand_mentioned"):
            label = "negative"
        elif negative:
            label = "cautious"
        elif analysis.get("brand_mentioned") and positive_cues.search(answer):
            label = "enthusiastic"
        else:
            label = "neutral"
        labels[label] += 1
    total = sum(labels.values())
    return {
        "sample_count": total,
        "bands": [
            {"label": label, "count": count, "rate": round(count / total, 3) if total else None}
            for label, count in labels.items()
        ],
        "method": "heuristic answer context; inspect raw replay before making a claim",
    }


def _entity_names(config):
    brand = config.get("brand") or {}
    brand_name = str(brand.get("name") or "Brand")
    entities = [("brand", brand_name)]
    seen = {brand_name}
    for item in config.get("competitors") or []:
        if not isinstance(item, dict):
            continue
        if item.get("confirmed") is False or item.get("benchmark_eligible") is False:
            continue
        name = str(item.get("name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        entities.append((f"competitor:{name}", name))
    return entities


def _cohort_key(row):
    return sampling_modes.for_row(row), str(row.get("platform") or "unknown")


def _cohort_rows(rows):
    grouped = defaultdict(list)
    for row in _usable_rows(rows):
        grouped[_cohort_key(row)].append(row)
    return grouped


def _entity_hit(row, key):
    analysis = row.get("analysis") or {}
    if key == "brand":
        return bool(analysis.get("brand_mentioned"))
    return key.split(":", 1)[1] in (analysis.get("competitors_mentioned") or [])


def _cell(rows, key):
    samples = len(rows)
    hits = sum(1 for row in rows if _entity_hit(row, key))
    interval = measurement.wilson_interval(hits, samples)
    return {
        "hits": hits,
        "samples": samples,
        "rate": round(hits / samples, 4) if samples else None,
        "interval": interval,
    }


def _question_rows(rows):
    by_question = defaultdict(list)
    for row in _usable_rows(rows):
        question_id = str(row.get("question_id") or "")
        if question_id:
            by_question[question_id].append(row)
    return by_question


def _prompt_explorer(project_slug, rows, blueprint, config, expected_cohorts=None):
    import analytics
    import geolib

    questions = analytics.questions(project_slug, rows, blueprint)
    expansion = geolib.read_json(geolib.project_dir(project_slug) / "expand.json", {}) or {}
    demand = expansion.get("q_demand") or {}
    question_rows = _question_rows(rows)
    evidence = measurement.question_cohort_evidence(
        rows, config, MIN_QUESTION_SAMPLES, expected_cohorts=expected_cohorts,
    )
    evidence_by_id = {item["id"]: item for item in evidence["items"]}
    items = []
    for item in questions:
        qid = item.get("id")
        cohort_evidence = evidence_by_id.get(str(qid)) or {
            "samples": int(item.get("samples") or 0),
            "required": MIN_QUESTION_SAMPLES,
            "missing_samples": MIN_QUESTION_SAMPLES,
            "sufficient": False,
            "cohorts": [],
        }
        samples = int(cohort_evidence.get("samples") or 0)
        mention = item.get("mention")
        diagnosis = item.get("diagnosis") or {}
        signal = demand.get(qid) if isinstance(demand, dict) else None
        signal = signal if isinstance(signal, dict) else {}
        question_sample_rows = question_rows.get(qid, [])
        mention_cell = _cell(question_sample_rows, "brand")
        rival_counts = defaultdict(int)
        for row in question_sample_rows:
            for name in (row.get("analysis") or {}).get("competitors_mentioned") or []:
                rival_counts[name] += 1
        rival_rate = max(rival_counts.values(), default=0) / len(question_sample_rows) if question_sample_rows else 0
        reasons = []
        if item.get("brand_probe"):
            reasons.append("Brand-named probe; keep separate from unprompted opportunity scoring")
        elif not cohort_evidence.get("sufficient"):
            reasons.append(
                f"Evidence is incomplete across provider and sampling cohorts; "
                f"collect {int(cohort_evidence.get('missing_samples') or MIN_QUESTION_SAMPLES)} more sample(s)"
            )
        elif mention == 0:
            reasons.append("Brand absent in the latest unprompted answers")
        elif mention is not None and mention < 0.5:
            reasons.append("Brand visibility is inconsistent across the latest answers")
        if diagnosis.get("type") == "competitor_dominant":
            reasons.append(diagnosis.get("detail") or "A configured competitor dominates this prompt")
        if item.get("content") != "ready":
            reasons.append("No ready content asset is mapped to this prompt")
        if signal.get("new"):
            reasons.append("Search expansion found a new demand signal")

        score = None
        if not item.get("brand_probe") and cohort_evidence.get("sufficient"):
            competitor_rate = rival_rate
            gap = 1 - float(mention or 0)
            content_gap = 1 if item.get("content") != "ready" else 0
            score = round(100 * (0.55 * gap + 0.25 * competitor_rate + 0.20 * content_gap))
        if item.get("brand_probe"):
            priority = "probe"
        elif not cohort_evidence.get("sufficient"):
            priority = "needs_sampling"
        elif score >= 60:
            priority = "high"
        elif score >= 30:
            priority = "medium"
        else:
            priority = "monitor"
        items.append({
            **item,
            "opportunity_score": score,
            "priority": priority,
            "cohort_evidence": cohort_evidence,
            "demand": {
                "terms": signal.get("terms") or [],
                "roots": signal.get("roots") or [],
                "new": bool(signal.get("new")),
                "count": int(signal.get("n") or 0),
            },
            "mention_interval": mention_cell.get("interval"),
            "reasons": reasons[:4],
        })
    items.sort(key=lambda item: (
        item.get("priority") == "probe",
        item.get("priority") == "monitor",
        -(item.get("opportunity_score") if item.get("opportunity_score") is not None else -1),
        item.get("id") or "",
    ))
    return {
        "items": items,
        "measured_count": sum(1 for item in items if item.get("samples")),
        "total_count": len(items),
        "minimum_samples": MIN_QUESTION_SAMPLES,
        "cohorts": evidence.get("cohorts") or [],
        "sufficient_count": evidence.get("sufficient", 0),
    }


def _competitor_heatmap(config, rows):
    entities = _entity_names(config)
    grouped = _cohort_rows(rows)
    cohorts = []
    for (mode, platform), cohort_rows in sorted(grouped.items(), key=lambda pair: pair[0]):
        cohorts.append({
            "key": f"{mode}|{platform}",
            "engine_code": platform,
            "engine_name": cohort_rows[0].get("platform_name") or platform,
            "sampling_mode": mode,
            "samples": len(cohort_rows),
        })

    by_question = _question_rows(rows)
    questions = []
    alerts = []
    for question in config.get("questions") or []:
        if not isinstance(question, dict):
            continue
        qid = str(question.get("id") or "")
        qrows = by_question.get(qid, [])
        aggregate = {key: _cell(qrows, key) for key, _ in entities}
        cohort_cells = []
        for cohort in cohorts:
            mode, platform = cohort["sampling_mode"], cohort["engine_code"]
            cohort_rows = grouped[(mode, platform)]
            selected = [row for row in cohort_rows if str(row.get("question_id") or "") == qid]
            cells = {key: _cell(selected, key) for key, _ in entities}
            cohort_cells.append({"cohort": cohort["key"], "cells": cells})
            brand = cells.get("brand") or {}
            if brand.get("samples", 0) < MIN_ALERT_SAMPLES or brand.get("hits", 0):
                continue
            for key, name in entities[1:]:
                rival = cells.get(key) or {}
                rival_interval = rival.get("interval")
                brand_interval = brand.get("interval")
                if (
                    rival.get("hits", 0) >= MIN_ALERT_SAMPLES
                    and rival_interval
                    and brand_interval
                    and rival_interval["lower"] > brand_interval["upper"]
                ):
                    alerts.append({
                        "question_id": qid,
                        "question": question.get("text") or "",
                        "competitor": name,
                        "cohort": cohort["key"],
                        "engine_name": cohort["engine_name"],
                        "sampling_mode": cohort["sampling_mode"],
                        "brand": brand,
                        "competitor_cell": rival,
                        "status": "takeover_candidate",
                        "reason": "Wilson 95% intervals are separated in a comparable cohort",
                    })
        questions.append({
            "id": qid,
            "text": question.get("text") or "",
            "samples": len(qrows),
            "brand": aggregate.get("brand"),
            "competitors": [
                {"name": name, **aggregate.get(key, {})}
                for key, name in entities[1:]
            ],
            "cohorts": cohort_cells,
        })
    return {
        "entities": [{"key": key, "name": name} for key, name in entities],
        "cohorts": cohorts,
        "questions": questions,
        "sample_count": len(_usable_rows(rows)),
    }, alerts[:50]


def _facts_gate(project_directory):
    facts_path = project_directory / "content" / "facts.md"
    if not facts_path.is_file():
        return {"status": "missing", "approved": False}
    text = facts_path.read_text("utf-8", errors="replace")
    if not text.strip():
        return {"status": "missing", "approved": False}
    if brand_facts.REVIEWED_MARKER in text:
        return {"status": "approved", "approved": True}
    verification = geolib.read_json(project_directory / "content" / "facts.verification.json", {}) or {}
    if verification.get("publication_ready"):
        return {"status": "machine_verified", "approved": True}
    return {"status": "review_required", "approved": False}


def _asset_records(project_directory):
    index = geolib.read_json(project_directory / "assets" / "index.json", {}) or {}
    records = [
        dict(item) for item in index.get("asset_records") or []
        if isinstance(item, dict) and item.get("path")
    ]
    if records:
        return records
    assets = project_directory / "assets"
    if not assets.is_dir():
        return []
    inferred = []
    for path in sorted(assets.rglob("*")):
        if not path.is_file() or path.name == "index.json" or path.suffix.lower() not in (".txt", ".json", ".html", ".md"):
            continue
        relative = path.relative_to(assets).as_posix()
        status = "draft" if relative.startswith(("drafts/", "outlines/")) else "review_required"
        inferred.append({"path": relative, "status": status, "issues": ["asset_index_missing"]})
    return inferred


def _question_assets(records, question_id):
    related = []
    for record in records:
        path = str(record.get("path") or "")
        if Path(path).stem != question_id:
            continue
        related.append({
            "path": path,
            "status": record.get("status") or "review_required",
            "issues": record.get("issues") or [],
        })
    related.sort(key=lambda item: (item["status"] != "review_required", item["path"]))
    return related


def _task_question_ids(task):
    values = []
    for key in ("question_id", "qid"):
        if task.get(key):
            values.append(task[key])
    for key in ("question_ids", "influenced_questions", "impacted_questions"):
        value = task.get(key) or []
        values.extend(value if isinstance(value, list) else [value])
    for asset in task.get("assets") or []:
        path = asset.get("path") if isinstance(asset, dict) else asset
        if path:
            values.append(Path(str(path)).stem)
    return {str(value) for value in values if str(value).strip()}


def _question_tasks(tasks, question_id):
    related = []
    for task in tasks:
        if not isinstance(task, dict) or question_id not in _task_question_ids(task):
            continue
        related.append({
            "id": task.get("id"),
            "title": task.get("title") or task.get("action") or "Linked implementation ticket",
            "status": task.get("status") or "todo",
            "priority": task.get("priority"),
        })
    related.sort(key=lambda item: (item["status"] in ("done", "wontfix"), item.get("id") or ""))
    return related[:5]


def _cohort_baselines(heatmap, question_id):
    cohorts = {item.get("key"): item for item in heatmap.get("cohorts") or []}
    question = next(
        (item for item in heatmap.get("questions") or [] if item.get("id") == question_id),
        {},
    )
    baselines = []
    for row in question.get("cohorts") or []:
        cell = (row.get("cells") or {}).get("brand") or {}
        if not cell.get("samples"):
            continue
        cohort = cohorts.get(row.get("cohort"), {})
        baselines.append({
            "cohort": row.get("cohort"),
            "engine_name": cohort.get("engine_name") or cohort.get("engine_code"),
            "sampling_mode": cohort.get("sampling_mode"),
            "samples": cell.get("samples"),
            "rate": cell.get("rate"),
            "interval": cell.get("interval"),
        })
    return baselines


def _campaign_proposals(project_slug, prompt, heatmap, alerts, blueprint):
    project_directory = geolib.project_dir(project_slug)
    tasks_data = geolib.read_json(project_directory / "tasks.json", {}) or {}
    tasks = [item for item in tasks_data.get("tasks") or [] if isinstance(item, dict)]
    assets = _asset_records(project_directory)
    facts = _facts_gate(project_directory)
    content_by_question = {
        str(item.get("id")): item
        for item in (blueprint.get("contents") if isinstance(blueprint, dict) else []) or []
        if isinstance(item, dict) and item.get("id")
    }
    alerts_by_question = defaultdict(list)
    for alert in alerts:
        alerts_by_question[str(alert.get("question_id") or "")].append(alert)

    ranked = [
        item for item in prompt.get("items") or []
        if item.get("priority") in ("high", "medium", "needs_sampling")
    ]
    ranked.sort(key=lambda item: (
        item.get("priority") == "needs_sampling",
        -(item.get("opportunity_score") if item.get("opportunity_score") is not None else -1),
        item.get("id") or "",
    ))
    proposals = []
    for item in ranked[:MAX_CAMPAIGN_PROPOSALS]:
        question_id = str(item.get("id") or "")
        question = str(item.get("text") or item.get("question") or question_id)
        question_alerts = alerts_by_question.get(question_id, [])
        related_assets = _question_assets(assets, question_id)
        related_tickets = _question_tasks(tasks, question_id)
        content_plan = content_by_question.get(question_id) or {}
        cohort_evidence = item.get("cohort_evidence") or {}
        insufficient = not bool(cohort_evidence.get("sufficient"))
        asset_review = any(asset.get("status") == "review_required" for asset in related_assets)
        if insufficient or facts["status"] == "missing":
            status = "blocked"
        elif not facts["approved"] or asset_review:
            status = "review_required"
        else:
            status = "ready_for_approval"

        kind = "competitive_takeover" if question_alerts else (
            "measurement_gap" if insufficient else "prompt_opportunity"
        )
        if kind == "competitive_takeover":
            title = f"Review competitive gap: {question}"
            competitors = sorted({str(alert.get("competitor")) for alert in question_alerts if alert.get("competitor")})
            objective = (
                f"Create or improve fact-grounded evidence for this prompt before comparing again with "
                f"{', '.join(competitors)}."
            )
        elif kind == "measurement_gap":
            title = f"Measure before planning: {question}"
            objective = "Collect enough comparable samples to decide whether a content intervention is justified."
        else:
            title = f"Build evidence for: {question}"
            objective = "Create or improve a fact-grounded asset that directly answers this measured prompt gap."

        if insufficient:
            next_step = {
                "label": "Collect comparable samples",
                "route": "#/engines",
                "action": "fill_question_gap",
                "question_ids": [question_id],
            }
        elif facts["status"] == "missing":
            next_step = {"label": "Create the brand fact library", "route": "#/facts"}
        elif not facts["approved"]:
            next_step = {"label": "Review supporting facts", "route": "#/facts"}
        elif asset_review:
            next_step = {
                "label": "Resolve asset review gates",
                "route": f"#/assets?question={question_id}",
            }
        elif related_assets:
            next_step = {"label": "Replay evidence and review asset", "route": f"#/workbench?qid={question_id}"}
        else:
            next_step = {"label": "Generate a linked asset", "route": "#/assets"}

        evidence = [{
            "type": "prompt_opportunity",
            "opportunity_score": item.get("opportunity_score"),
            "priority": item.get("priority"),
            "samples": item.get("samples") or 0,
            "mention_rate": item.get("mention"),
            "mention_interval": item.get("mention_interval"),
            "cohort_evidence": cohort_evidence,
            "reasons": item.get("reasons") or [],
            "scope": "question_aggregate_for_prioritization_only",
        }]
        evidence.extend({
            "type": "takeover_candidate",
            "competitor": alert.get("competitor"),
            "engine_name": alert.get("engine_name"),
            "sampling_mode": alert.get("sampling_mode"),
            "cohort": alert.get("cohort"),
            "brand": alert.get("brand"),
            "competitor_cell": alert.get("competitor_cell"),
            "reason": alert.get("reason"),
        } for alert in question_alerts)
        proposals.append({
            "id": f"campaign-{question_id}",
            "kind": kind,
            "status": status,
            "priority": item.get("priority"),
            "title": title,
            "objective": objective,
            "target_question": {"id": question_id, "text": question},
            "evidence": evidence,
            "expected_impact": {
                "claim": "hypothesis",
                "metric": "brand_mention_rate",
                "statement": (
                    "Test for improvement within each unchanged sampling cohort after the asset is deployed; "
                    "no effect size is forecast."
                ),
                "cohort_baselines": _cohort_baselines(heatmap, question_id),
                "validation": "Re-run the same question set, engine, sampling mode, and measurement policy after deployment.",
            },
            "content_plan": {
                "status": content_plan.get("status") or "not_planned",
                "form": content_plan.get("form"),
                "group": content_plan.get("group"),
            },
            "related_tickets": related_tickets,
            "related_assets": related_assets,
            "gates": {
                "minimum_samples": {
                    "required": MIN_QUESTION_SAMPLES,
                    "actual": int(item.get("samples") or 0),
                    "met": not insufficient,
                },
                "cohort_evidence": cohort_evidence,
                "brand_facts": facts,
                "asset_review_required": asset_review,
                "human_approval_required": True,
                "automatic_publication": False,
            },
            "next_step": next_step,
            "workflow": {
                "evidence": {
                    "status": "insufficient" if insufficient else "available",
                    "samples": int(item.get("samples") or 0),
                    "minimum": MIN_QUESTION_SAMPLES,
                    "interval": item.get("mention_interval"),
                    "cohort_evidence": cohort_evidence,
                },
                "ticket": {
                    "status": "linked" if related_tickets else "missing",
                    "count": len(related_tickets),
                    "route": "#/plan",
                },
                "asset": {
                    "status": "linked" if related_assets else "missing",
                    "count": len(related_assets),
                    "route": f"#/assets?question={question_id}",
                },
                "review": {
                    "status": "required" if (not facts["approved"] or asset_review) else "ready",
                    "route": "#/facts" if not facts["approved"] else f"#/assets?question={question_id}",
                },
                "verification": {
                    "status": "pending",
                    "route": "#/verify",
                    "condition": "Re-run the same question set, provider, model, sampling mode, and policy after deployment.",
                },
            },
        })

    counts = {name: sum(item["status"] == name for item in proposals) for name in (
        "blocked", "review_required", "ready_for_approval",
    )}
    return {
        "items": proposals,
        "counts": counts,
        "total_count": len(proposals),
        "source_summary": {
            "prompt_candidates": len(ranked),
            "takeover_candidates": len(alerts),
            "tickets": len(tasks),
            "assets": len(assets),
            "brand_facts": facts["status"],
        },
        "policy": {
            "human_approval_required": True,
            "automatic_publication": False,
            "impact_claims": "hypothesis_only",
        },
    }


def build(project_slug, rows, config, blueprint=None, expected_cohorts=None):
    """返回不改变管线产物的产品洞察；没有样本时保留可渲染的空结构。"""
    prompt = _prompt_explorer(
        project_slug, rows, blueprint, config, expected_cohorts=expected_cohorts,
    )
    heatmap, alerts = _competitor_heatmap(config, rows)
    return {
        "prompt_explorer": prompt,
        "competitor_heatmap": heatmap,
        "takeover_alerts": alerts,
        "sentiment": _sentiment_summary(rows),
        "campaign_proposals": _campaign_proposals(
            project_slug, prompt, heatmap, alerts, blueprint,
        ),
    }
