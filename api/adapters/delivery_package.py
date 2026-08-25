"""交付包组装、质量门禁和兼容合同。"""

import json
import shutil
import tempfile
from pathlib import Path

from api.adapters.delivery_common import *  # noqa: F401,F403
from api.adapters.delivery_documents import (
    _audit_markdown,
    _build_map_markdown,
    _execution_markdown,
    _risk_summary,
    _risk_markdown,
    _tickets_csv,
    _tickets_markdown,
    _verification_markdown,
)
from api.adapters.delivery_generated_assets import (
    _copy_drafts,
    _copy_other_assets,
    _facts_delivery_data,
    _schema_type_names,
    _write_facts_asset,
    render_english_generated_assets,
)

def _write_document(directory, number, markdown, cards):
    name = REQUIRED_DOCUMENTS[number]
    (directory / f"{number}-{name}.md").write_text(markdown, "utf-8")
    import report

    title = markdown.splitlines()[0].removeprefix("# ")
    document = report.build_html(title, markdown, cards)
    (directory / f"{number}-{name}.html").write_text(document, "utf-8")


def _json_nodes(value):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _json_nodes(item)
    elif isinstance(value, list):
        for item in value:
            yield from _json_nodes(item)


def _machine_price(value):
    if isinstance(value, bool) or value is None:
        return False
    if isinstance(value, (int, float)):
        return value >= 0
    return bool(re.fullmatch(r"\d+(?:\.\d+)?", str(value).strip()))


def _json_asset_issues(value):
    issues = []
    if not isinstance(value, dict):
        return ["JSON asset must contain an object"]
    if not value.get("@context") or not value.get("@type"):
        issues.append("Missing @context or @type")
    item_type = value.get("@type")
    if item_type == "FAQPage":
        entities = value.get("mainEntity")
        if not isinstance(entities, list) or not entities:
            issues.append("FAQPage has no questions and answers")
        else:
            for entity in entities:
                answer = entity.get("acceptedAnswer") if isinstance(entity, dict) else None
                if not entity.get("name") or not isinstance(answer, dict) or not answer.get("text"):
                    issues.append("FAQPage contains an incomplete question or answer")
                    break
    if item_type in ("Organization", "SoftwareApplication", "Product"):
        if not value.get("name"):
            issues.append(f"{item_type} is missing name")
        if not value.get("url"):
            issues.append(f"{item_type} is missing canonical URL")
    if item_type in ("SoftwareApplication", "Product") and not value.get("description"):
        issues.append(f"{item_type} is missing description")
    offers = [
        node for node in _json_nodes(value)
        if isinstance(node, dict) and "Offer" in _schema_type_names(node.get("@type"))
    ]
    for offer in offers:
        if offer.get("price") in (None, "") or not offer.get("priceCurrency"):
            issues.append("Offer is missing price or ISO currency")
            continue
        if not _machine_price(offer.get("price")):
            issues.append("Offer price must be a non-negative machine-readable number")
        if not re.fullmatch(r"[A-Z]{3}", str(offer.get("priceCurrency") or "")):
            issues.append("Offer priceCurrency must be an ISO 4217 code")
    return issues


def _asset_record(destination, delivery_path, *, facts_review_pending=False):
    relative = Path(delivery_path).relative_to("assets")
    path = destination / relative
    issues = []
    try:
        text = path.read_text("utf-8")
    except UnicodeDecodeError:
        text = ""
    if text and PLACEHOLDER_PATTERN.search(text):
        issues.append("Contains unresolved placeholders")
    if path.suffix.lower() == ".json" and relative.parts and relative.parts[0] == "jsonld":
        try:
            issues.extend(_json_asset_issues(json.loads(text)))
        except json.JSONDecodeError:
            issues.append("Invalid JSON")
    if relative.parts and relative.parts[0] == "outlines" and path.suffix.lower() in (".md", ".json"):
        issues.append("Editorial outline collection requires research and drafting")
    status = "template" if issues else ("needs_review" if relative.parts and relative.parts[0] == "drafts" else "ready")
    derived_fact_paths = (
        relative == Path("llms.txt")
        or relative == Path("llms.en.txt")
        or (relative.parts and relative.parts[0] == "jsonld")
        or relative == Path("snippets/definition.en.html")
    )
    if facts_review_pending and derived_fact_paths and status != "template":
        status = "needs_review"
        issues.append("Derived from an unreviewed brand facts library")
    if status == "needs_review" and relative.parts and relative.parts[0] == "drafts":
        issues.append("Draft requires factual and editorial review")
    if status == "template":
        template_relative = Path("llms.en.txt") if relative == Path("drafts/llms.en.txt") else relative
        target = destination / "templates" / template_relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(path, target)
        relative = target.relative_to(destination)
    record = {
        "path": relative.as_posix(),
        "status": status,
        "type": relative.suffix.lower().lstrip(".") or "file",
        "issues": list(dict.fromkeys(issues)),
    }
    if relative.name in {"llms.en.txt", "llms.txt"} or relative.as_posix().endswith("/llms.en.txt"):
        record["deploy_path"] = "/llms.txt"
    return record


def _classify_pack_readiness(audit, summary, sampling, facts_review):
    """兼容入口：资产就绪分类由 delivery_assets 负责。"""
    from api.adapters.delivery_assets import classify_pack_readiness

    return classify_pack_readiness(audit, summary, sampling, facts_review)


def _write_assets(project_slug, project_directory, directory, config, audit, blueprint, measurement_scope=None):
    """兼容入口：资产清单编排由 delivery_assets 负责。"""
    from api.adapters.delivery_assets import AssetOperations, write_asset_index

    return write_asset_index(
        project_slug,
        project_directory,
        directory,
        config,
        audit,
        blueprint,
        measurement_scope=measurement_scope,
        operations=AssetOperations(
            facts_delivery_data=_facts_delivery_data,
            write_facts_asset=_write_facts_asset,
            render_generated_assets=render_english_generated_assets,
            copy_drafts=_copy_drafts,
            copy_other_assets=_copy_other_assets,
            asset_record=_asset_record,
            insight_mode_name=_insight_mode_name,
            safe_display=_safe_display,
        ),
    )


def validate_delivery_quality(directory, audit, tickets, asset_index):
    directory = Path(directory)
    issues = []
    measurement_scope = asset_index.get("measurement_scope") or {}
    if measurement_scope.get("active_cohorts") and not measurement_scope.get("question_ready"):
        issues.append("Measurement cohort evidence is incomplete for the active funded providers")
    required = [
        *(f"{number}-{name}.md" for number, name in REQUIRED_DOCUMENTS.items()),
        *(f"{number}-{name}.html" for number, name in REQUIRED_DOCUMENTS.items()),
        "03-Ticket-Log.csv",
    ]
    issues.extend(f"Missing required document: {name}" for name in required if not (directory / name).is_file())

    page_count = int(audit.get("page_count") or 0)
    pages = [page for page in audit.get("pages") or [] if isinstance(page, dict)]
    if page_count != len(pages):
        issues.append("Audit page count does not match the page evidence list")
    coverage = audit.get("score_coverage")
    minimum = float(audit.get("minimum_score_coverage") or audit_presentation.MIN_SITE_SCORE_COVERAGE)
    if audit.get("applicable_avg_score") is not None and (coverage is None or float(coverage) < minimum):
        issues.append("Audit reports a site score below the minimum scoring coverage")
    if audit.get("score_status") == "reported" and audit.get("applicable_avg_score") is None:
        issues.append("Audit score status is reported without a site score")

    records = [item for item in asset_index.get("assets") or [] if isinstance(item, dict)]
    summary = asset_index.get("summary") or {}
    for status in ("ready", "needs_review", "template"):
        if int(summary.get(status) or 0) != sum(item.get("status") == status for item in records):
            issues.append(f"Asset summary does not match {status} records")
    for record in records:
        path = directory / "assets" / str(record.get("path") or "")
        if not path.is_file():
            issues.append(f"Manifest asset is missing: {record.get('path')}")
        if record.get("status") == "ready" and record.get("issues"):
            issues.append(f"Ready asset still has unresolved issues: {record.get('path')}")

    risk_text = (directory / "05-Draft-Risks.md").read_text("utf-8") if (directory / "05-Draft-Risks.md").is_file() else ""
    for record in records:
        if record.get("status") == "needs_review" and f"assets/{record.get('path')}" not in risk_text:
            issues.append(f"Review-required asset is absent from the risk report: {record.get('path')}")

    facts_approved = bool((asset_index.get("facts_review") or {}).get("approved"))
    llms_tickets = [
        ticket for ticket in tickets
        if ticket.get("acceptance_check") == "site.has_llms_txt"
    ]
    if not facts_approved:
        for ticket in llms_tickets:
            pending = any(
                item.get("label") == "Brand facts library has passed factual review" and item.get("status") == "Pending"
                for item in ticket.get("prerequisites") or []
            )
            if not pending or "approved" not in ticket.get("acceptance", "").casefold():
                issues.append(f"{ticket.get('id')} does not block llms.txt deployment on factual approval")

    for ticket in tickets:
        ids = [item.get("id") or item.get("label") for item in ticket.get("prerequisites") or []]
        if len(ids) != len(set(ids)):
            issues.append(f"{ticket.get('id')} has duplicate prerequisites")

    checklist = directory / "04-Acceptance-Checklist.md"
    checklist_text = checklist.read_text("utf-8") if checklist.is_file() else ""
    for ticket in tickets:
        if ticket.get("acceptance_check") not in {"pages.applicable:rendered_content", "pages.static_text"}:
            continue
        if not ticket.get("affected"):
            continue
        line = next((row for row in checklist_text.splitlines() if f"| {ticket.get('id')} |" in row), "")
        if "Current value: 0" in line:
            issues.append(f"{ticket.get('id')} acceptance count ignores empty-shell failures")

    for path in directory.rglob("brand-facts.md"):
        text = path.read_text("utf-8")
        if brand_facts.normalize_price_rows(text) != text:
            issues.append(f"Brand facts contain a non-normalized price: {path.relative_to(directory).as_posix()}")

    if issues:
        raise GeoEngineError("delivery quality gate failed: " + "; ".join(issues))
    return {
        "status": "passed",
        "checks": [
            "document_contract", "audit_coverage", "asset_manifest", "risk_propagation",
            "fact_approval_dependency", "price_normalization", "ticket_acceptance_consistency",
        ],
    }


def _write_index(directory, name, site, delivery_date, audit, tickets, blueprint, asset_index):
    coverage = blueprint.get("coverage") or {}
    assets = asset_index.get("assets") or []
    asset_summary = asset_index.get("summary") or {}
    schema_selection = asset_index.get("schema_selection") or {}
    documents = [f"{number}-{title}.html" for number, title in REQUIRED_DOCUMENTS.items()]
    site_score = audit.get("applicable_avg_score")
    site_score_label = _score_result_label(
        site_score, audit.get("partial_applicable_avg_score"),
    )
    source_revision = asset_index.get("source_revision") or app_config.source_revision()
    pack_kind = asset_index.get("pack_kind") or "diagnostic"
    diagnostic_ready = bool(asset_index.get("diagnostic_ready"))
    implementation_ready = bool(asset_index.get("implementation_ready"))
    visibility_ready = bool(asset_index.get("visibility_ready"))
    if implementation_ready:
        pack_status = "Implementation pack ready"
        pack_purpose = (
            "This package is the implementation final pack: diagnostic documents plus "
            "publishable assets that passed factual and editorial checks."
        )
    elif diagnostic_ready:
        pack_status = "Diagnostic pack ready"
        pack_purpose = (
            "This package is the diagnostic final pack. Send documents 01-06 to the client. "
            "Templates and review-only drafts are the implementation backlog, not missing diagnosis."
        )
    else:
        pack_status = "Review required"
        pack_purpose = (
            "This package could not be classified as a complete diagnostic pack. "
            "Resolve the readiness issues below before sending it to a client."
        )
    lines = [
        f"# {name} GEO Delivery Pack",
        "",
        f"- Pack type: {pack_kind}",
        f"- Pack status: {pack_status}",
        f"- Measurement baseline ready: {'yes' if visibility_ready else 'no'}",
        f"- Visibility claims: {'representative baseline available' if visibility_ready else 'limited or unmeasured; do not generalize'}",
        f"- Official website: {site}",
        f"- Delivery date: {delivery_date}",
        f"- Source revision: {source_revision}",
        f"- Applicable site score: {site_score_label}",
        f"- Scoring coverage: {audit.get('evaluated_page_count', 0)}/{audit.get('score_eligible_page_count', 0)} eligible pages ({_format_rate(audit.get('score_coverage'))})",
        f"- Action tickets: {len(tickets)}",
        f"- Channel coverage: {coverage.get('channel_covered', 0)}/{coverage.get('channel_total', 0)}",
    ]
    measurement_scope = asset_index.get("measurement_scope") or {}
    if measurement_scope:
        question_evidence = measurement_scope.get("question_evidence") or {}
        lines += [
            f"- Active funded provider cohorts: {len(measurement_scope.get('active_cohorts') or [])}",
            f"- Measured provider cohorts: {len(measurement_scope.get('measured_platforms') or [])}",
            f"- Question evidence: {question_evidence.get('sufficient', 0)}/{question_evidence.get('total', 0)} questions meet the {measurement_scope.get('minimum_question_samples', measurement.MIN_QUESTION_SAMPLES)}-sample cohort target",
        ]
        if measurement_scope.get("unfunded_platforms"):
            lines.append("- Configured providers without current funding are excluded from measured cohorts")
    if coverage.get("channel_manual"):
        lines.append(f"- Channels requiring manual confirmation: {coverage['channel_manual']}")
    lines += ["", pack_purpose, ""]
    backlog = [str(item) for item in (asset_index.get("implementation_backlog") or []) if item]
    if backlog and not implementation_ready:
        lines += ["## Implementation Backlog", ""]
        lines += [f"- {item}" for item in backlog]
        lines.append("")
    blockers = [str(item) for item in (asset_index.get("readiness_issues") or []) if item]
    if blockers:
        lines += ["## Diagnostic Blockers", ""]
        lines += [f"- {item}" for item in blockers]
        lines.append("")
    strategy = blueprint.get("channel_strategy") or {}
    if strategy:
        lines += [
            f"- Channel strategy: {strategy.get('label', 'Configured profile')} (confidence: {strategy.get('confidence', 'unknown')})",
            "- Channel recommendations are selected from the project business profile; confirm inferred profiles before execution.",
            "",
        ]
    lines += [
        "## Documents",
        "",
    ]
    for number, title in REQUIRED_DOCUMENTS.items():
        lines.append(f"- [{number} - {title}]({number}-{title}.html)")
    lines += [
        "", "## Asset Readiness", "",
        f"- Ready to deploy: {asset_summary.get('ready', 0)}",
        f"- Needs factual or editorial review: {asset_summary.get('needs_review', 0)}",
        f"- Implementation outlines (templates): {asset_summary.get('template', 0)}",
        f"- Specialized JSON-LD assets omitted for lack of supporting evidence: {len(schema_selection.get('omitted') or [])}",
        "",
    ]
    for status, heading in (
        ("ready", "Ready to Deploy"),
        ("needs_review", "Needs Review"),
        ("template", "Templates"),
    ):
        lines += [f"### {heading}", ""]
        matching = [item for item in assets if item.get("status") == status]
        lines += [
            f"- `assets/{item['path']}`"
            + (f" → publish as `{item['deploy_path']}`" if item.get("deploy_path") else "")
            + (f" - {'; '.join(item['issues'])}" if item.get("issues") else "")
            for item in matching
        ] or ["- None"]
        lines.append("")
    lines += [
        "",
        "## Use and Verification",
        "",
        "Send the diagnostic documents first. Execute tickets by priority, attach evidence, then re-run acceptance checks.",
        "Do not treat unmeasured visibility or unfinished outlines as a reason to withhold this pack.",
        "Sampling results must retain their stated mode: API - Parametric knowledge, API - Search grounded, or Manual - Product interface.",
        "",
    ]
    markdown = "\n".join(lines)
    (directory / "index.md").write_text(markdown, "utf-8")
    import report

    (directory / "index.html").write_text(
        report.build_html(
            f"{name} GEO Delivery Pack",
            markdown,
            [
                ("Pack Status", pack_status),
                ("Applicable Site Score", site_score_label),
                ("Scoring Coverage", _format_rate(audit.get("score_coverage"))),
                ("Tickets", str(len(tickets))),
                ("Documents", str(len(documents))),
                ("Ready Assets", str(asset_summary.get("ready", 0))),
            ],
        ),
        "utf-8",
    )
    readme = "\n".join([
        f"# {name} GEO Delivery Pack",
        "",
        f"Source revision: `{source_revision}`",
        f"Pack type: `{pack_kind}`",
        f"Pack status: {pack_status}",
        "",
        pack_purpose,
        "",
        "Start with `index.html` for the delivery overview. Documents 01-06 are the client-facing diagnostic final pack.",
        "",
        "## Package Contents",
        "",
        "- `01-Audit-Report`: what to change on the website so AI systems can crawl, extract, and mention the brand.",
        "- `02-Execution-Plan`: prioritized 30/60/90-day implementation sequence.",
        "- `03-Ticket-Log`: assigned work, rationale, actions, and acceptance criteria.",
        "- `04-Acceptance-Checklist`: current automated and manual verification state.",
        "- `05-Draft-Risks`: publication risks for implementation assets, not diagnostic defects.",
        "- `06-Build-Map`: channel and target-query content architecture.",
        "- `assets/`: classified as ready, needs review, or template in `assets/index.json`.",
        "- `assets/llms.en.txt`: English facts index to publish at `/llms.txt`.",
        "",
        "Templates and review-only drafts stay in the pack as the next implementation backlog. "
        "They do not block sending this diagnostic pack. Do not publish them until every claim is verified.",
        "",
    ])
    (directory / "README.md").write_text(readme, "utf-8")


def _build_delivery(
    project_slug,
    project_directory,
    directory,
    delivery_date,
    measurement_scope=None,
    require_question_evidence=False,
):
    config, audit, task_data, blueprint, metrics, verification, lint = _load_sources(project_directory)
    name, site = _identity(project_directory, project_slug, config, audit)
    display_audit = audit_presentation.present_audit_data(
        audit,
        geolib.read_jsonl(project_directory / "evidence" / "pages.jsonl"),
        audit.get("site") or {},
    )
    facts_path = project_directory / "content" / "facts.md"
    facts_text = facts_path.read_text("utf-8") if facts_path.is_file() else ""
    facts_approved = brand_facts.publication_approved(project_slug, facts_text)
    sampling_quality = measurement.sampling_quality(project_slug)
    task_data = action_scope.scope_task_data(
        task_data, display_audit, sampling_quality, facts_approved=facts_approved,
    )
    verification = action_scope.scope_verification(
        verification,
        task_data,
        display_audit,
        sampling_quality,
        facts_approved=facts_approved,
    )
    tickets = [_ticket_en(ticket) for ticket in task_data["tasks"] if isinstance(ticket, dict)]
    tickets.sort(key=lambda ticket: (ticket["priority"], ticket["id"]))

    sample_rows = _current_sample_rows(project_directory, config)
    insights = product_insights.build(
        project_slug,
        sample_rows,
        config,
        blueprint,
        expected_cohorts=((metrics or {}).get("provenance") or {}).get("platforms") or [],
    )
    insights["readiness"] = report_quality.assess(project_slug, has_sampling_access=True).get("readiness") or {}

    audit_markdown = _audit_markdown(
        project_slug, project_directory, name, site, display_audit, metrics, insights,
    )
    execution_markdown = _execution_markdown(name, tickets, task_data)
    tickets_markdown = _tickets_markdown(name, tickets)
    verification_markdown = _verification_markdown(name, display_audit, verification, tickets)
    asset_index = _write_assets(
        project_slug,
        project_directory,
        directory,
        config,
        display_audit,
        blueprint,
        measurement_scope=measurement_scope,
    )
    if require_question_evidence and isinstance(measurement_scope, dict):
        if measurement_scope.get("active_cohorts") and not measurement_scope.get("ready"):
            missing = sum(
                int(item.get("missing_samples") or 0)
                for item in (measurement_scope.get("evidence") or {}).get("gaps") or []
            )
            raise GeoEngineError(
                "delivery_evidence_incomplete: "
                f"{len((measurement_scope.get('evidence') or {}).get('gaps') or [])} question(s), "
                f"{missing} provider/mode sample(s) missing"
            )
    risk_summary = _risk_summary(lint, asset_index)
    risk_markdown = _risk_markdown(name, lint, asset_index)
    build_map_markdown = _build_map_markdown(name, blueprint)

    _write_document(directory, "01", audit_markdown, [
        ("Applicable Site Score", _score_result_label(
            display_audit.get("applicable_avg_score"),
            display_audit.get("partial_applicable_avg_score"),
        )),
        ("Scoring Coverage", _format_rate(display_audit.get("score_coverage"))),
        ("Crawled Pages", str(display_audit.get("page_count", 0))),
    ])
    _write_document(directory, "02", execution_markdown, [
        ("Total Tickets", str(len(tickets))),
        ("P0 Blockers", str(sum(1 for ticket in tickets if ticket["priority"] == "P0"))),
    ])
    _write_document(directory, "03", tickets_markdown, [
        ("Total Tickets", str(len(tickets))),
        ("Completed", str(sum(1 for ticket in tickets if ticket["status"] == "Done"))),
    ])
    (directory / "03-Ticket-Log.csv").write_text(_tickets_csv(tickets), "utf-8")
    _write_document(directory, "04", verification_markdown, [
        ("Status", "Verified" if verification else "Unverified"),
    ])
    _write_document(directory, "05", risk_markdown, [
        ("Items to Review", str(risk_summary["total"])),
        ("High Risk", str(risk_summary["high"])),
    ])
    coverage = blueprint.get("coverage") or {}
    channel_stats = [
        ("Channel Coverage", f"{coverage.get('channel_covered', 0)}/{coverage.get('channel_total', 0)}"),
        ("Content Complete", f"{coverage.get('content_done', 0)}/{coverage.get('content_total', 0)}"),
    ]
    if coverage.get("channel_manual"):
        channel_stats.append(("Manual Confirmation", str(coverage["channel_manual"])))
    _write_document(directory, "06", build_map_markdown, channel_stats)
    asset_index["quality_gate"] = validate_delivery_quality(directory, display_audit, tickets, asset_index)
    (directory / "assets" / "index.json").write_text(
        json.dumps(asset_index, ensure_ascii=False, indent=2) + "\n", "utf-8",
    )
    _write_index(directory, name, site, delivery_date, display_audit, tickets, blueprint, asset_index)
    apply_delivery_branding(directory)
    validate_delivery_language(directory)


def _delivery_target(project_directory, delivery_directory):
    root = (project_directory / "delivery").resolve()
    target = Path(delivery_directory).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise GeoEngineError("delivery directory is outside the project delivery root") from exc
    if target.parent != root or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", target.name):
        raise GeoEngineError("delivery directory must identify a dated package")
    return target


def _legacy_deliverables_target(project_directory, deliverables_directory):
    root = (project_directory / "deliverables").resolve()
    target = Path(deliverables_directory).resolve()
    if target != root:
        raise GeoEngineError("legacy deliverables directory is outside the project deliverables root")
    return target


def _legacy_blueprint_section(name, blueprint):
    lines = _build_map_markdown(name, blueprint).splitlines()[2:]
    nested = ["#" + line if line.startswith(("## ", "### ")) else line for line in lines]
    return "\n".join(["## 4. Platform & Content Blueprint", "", *nested]).rstrip()


def _legacy_optimization_markdown(name, blueprint, original):
    start_heading = "## 4. Platform & Content Blueprint"
    end_heading = "## 5. Resource Allocation Recommendations"
    start = original.find(start_heading)
    end = original.find(end_heading, start + len(start_heading)) if start >= 0 else -1
    section = _legacy_blueprint_section(name, blueprint)
    if start < 0 or end < 0:
        return f"# {name} GEO Strategy & Optimization Plan\n\n{section}\n"
    return f"{original[:start].rstrip()}\n\n{section}\n\n{original[end:].lstrip()}"


def _write_legacy_document(directory, stem, title, markdown, cards):
    (directory / f"{stem}.md").write_text(markdown, "utf-8")
    import report

    (directory / f"{stem}.html").write_text(
        report.build_html(title, markdown, cards),
        "utf-8",
    )


def ensure_legacy_deliverables_contract(project_slug: str, deliverables_directory: Path | None = None):
    """用覆盖状态感知的 SaaS 渲染器替换旧优化报告的蓝图章节。"""
    global_scope.normalize_project(project_slug)
    project_directory = geolib.project_dir(project_slug)
    deliverables_directory = Path(deliverables_directory) if deliverables_directory else project_directory / "deliverables"
    target = _legacy_deliverables_target(project_directory, deliverables_directory)
    if not target.is_dir():
        raise GeoEngineError("legacy deliverables directory was not generated")

    blueprint = geolib.read_json(project_directory / "blueprint.json", {}) or {}
    if not isinstance(blueprint, dict) or not isinstance(blueprint.get("channels"), list):
        return target
    markdown_path = target / "2-GEO优化方案.md"
    if not markdown_path.is_file():
        return target
    config = geolib.read_json(project_directory / "geo.json", {}) or {}
    audit = geolib.read_json(project_directory / "audit.json", {}) or {}
    if not isinstance(config, dict):
        config = {}
    if not isinstance(audit, dict):
        audit = {}
    name, _site = _identity(project_directory, project_slug, config, audit)
    optimization_markdown = _legacy_optimization_markdown(
        name,
        blueprint,
        markdown_path.read_text("utf-8"),
    )
    channels = [
        channel for channel in blueprint.get("channels") or []
        if isinstance(channel, dict) and channel.get("market") in ("global", "both", None)
    ]
    coverage = global_scope.summarize_channel_coverage(channels)

    with geolib.project_lock(project_slug):
        staging = Path(tempfile.mkdtemp(prefix=".legacy-deliverables-", dir=target.parent))
        try:
            _write_legacy_document(
                staging,
                "2-GEO优化方案",
                f"{name} GEO Strategy & Optimization Plan",
                optimization_markdown,
                [
                    ("Measurable Channels", f"{coverage['channel_covered']}/{coverage['channel_total']}"),
                    ("Manual Confirmation", str(coverage["channel_manual"])),
                    (
                        "Content Complete",
                        f"{blueprint.get('coverage', {}).get('content_done', 0)}/{blueprint.get('coverage', {}).get('content_total', 0)}",
                    ),
                ],
            )
            for suffix in ("md", "html"):
                (staging / f"2-GEO优化方案.{suffix}").replace(target / f"2-GEO优化方案.{suffix}")
        finally:
            shutil.rmtree(staging, ignore_errors=True)
    return target


def ensure_delivery_contract(
    project_slug: str,
    delivery_directory: Path | None = None,
    *,
    measurement_scope=None,
    require_question_evidence=False,
):
    """Rebuild a delivery package and fail closed unless every artifact is English-only."""
    config = global_scope.normalize_project(project_slug)
    from api.adapters import generated_assets

    generated_assets.normalize_project_assets(project_slug, config=config)
    project_directory = geolib.project_dir(project_slug)
    delivery_directory = Path(delivery_directory) if delivery_directory else _latest_delivery(project_directory)
    if delivery_directory is None:
        # The SaaS adapter owns the formal delivery path. The standalone
        # engine CLI may still emit its own package, but SaaS jobs must be able
        # to create a formal package without first writing legacy output here.
        delivery_directory = project_directory / "delivery" / geolib.today()
    target = _delivery_target(project_directory, delivery_directory)
    target.parent.mkdir(parents=True, exist_ok=True)
    with geolib.project_lock(project_slug):
        staging = Path(tempfile.mkdtemp(prefix=".delivery-english-", dir=target.parent))
        backup = target.with_name(f".{target.name}.backup")
        try:
            if backup.exists() and not target.exists():
                backup.rename(target)
            _build_delivery(
                project_slug,
                project_directory,
                staging,
                target.name,
                measurement_scope=measurement_scope,
                require_question_evidence=require_question_evidence,
            )
            shutil.rmtree(backup, ignore_errors=True)
            if target.exists():
                target.rename(backup)
            try:
                staging.rename(target)
            except Exception:
                if backup.exists() and not target.exists():
                    backup.rename(target)
                raise
            shutil.rmtree(backup, ignore_errors=True)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            if backup.exists() and not target.exists():
                backup.rename(target)
            raise
    return target

__all__ = tuple(name for name in globals() if not name.startswith("__"))
