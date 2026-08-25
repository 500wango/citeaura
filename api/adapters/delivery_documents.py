"""交付包客户文档渲染。"""

from api.adapters.delivery_common import *  # noqa: F401,F403

def _insights_markdown(insights, platform_labels=None):
    """把工作区洞察压缩成不夸大结论的英文交付摘要。"""
    insights = insights if isinstance(insights, dict) else {}
    prompt = insights.get("prompt_explorer") or {}
    heatmap = insights.get("competitor_heatmap") or {}
    alerts = insights.get("takeover_alerts") or []
    campaigns = insights.get("campaign_proposals") or {}
    lines = [
        "## Prompt and Competitive Insights",
        "",
        "These observations are derived from the same current samples used by the workspace. "
        "They prioritize follow-up work; they do not claim a ranking or forecast an outcome.",
        "",
        f"- Prompt Explorer: {_safe_count(prompt.get('measured_count', 0), '0')} of {_safe_count(prompt.get('total_count', 0), '0')} questions have valid samples; "
        f"minimum per-provider/mode sample target: {_safe_count(prompt.get('minimum_samples', 3), '3')}.",
        f"- Cohort evidence: {_safe_count(prompt.get('sufficient_count', 0), '0')} of {_safe_count(prompt.get('total_count', 0), '0')} questions meet the "
        f"minimum in every observed provider/mode cohort; missing cohort samples remain blocked.",
        f"- Competitive heatmap: {_safe_count(heatmap.get('sample_count', 0), '0')} valid samples across "
        f"{_safe_count(len(heatmap.get('cohorts') or []), '0')} separate sampling cohorts.",
        f"- Takeover candidates: {_safe_count(len(alerts), '0')}; an alert requires at least five competitor hits "
        "and separated Wilson 95% intervals in the same cohort.",
        f"- Campaign proposals: {_safe_count(campaigns.get('total_count', 0), '0')}; human approval is required and automatic publication is disabled.",
        "",
    ]
    readiness = insights.get("readiness") or {}
    question_readiness = readiness.get("question") or {}
    attribution = readiness.get("attribution") or {}
    if readiness:
        lines += [
            "### Evidence readiness",
            "",
            f"- Overall measurement: **{_markdown_cell(_safe_display((readiness.get('measurement') or {}).get('label'), 'No baseline'))}**.",
            f"- Per-question evidence: **{_markdown_cell(_safe_display(question_readiness.get('label'), 'Not measured'))}** "
            f"({_safe_count(question_readiness.get('sufficient', 0), '0')}/{_safe_count(question_readiness.get('total', 0), '0')} questions at the minimum evidence target).",
            f"- Attribution: **{_markdown_cell(_safe_display(attribution.get('label'), 'No comparable period'))}**. "
            "Comparable deltas require unchanged questions, providers, models, sampling modes, and measurement policy.",
            "",
        ]
    items = [item for item in prompt.get("items") or [] if isinstance(item, dict)]
    items = [item for item in items if item.get("priority") not in ("probe", "monitor")][:8]
    if items:
        lines += [
            "### Highest-priority prompts",
            "",
            "| Question | Priority | Samples | Mention rate | Wilson 95% interval | Reason |",
            "|---|---|---:|---:|---|---|",
        ]
        for item in items:
            question = _safe_display(item.get("text") or item.get("question"), "Configured question")
            reasons = "; ".join(
                _safe_display(reason, "Follow-up evidence is required")
                for reason in (item.get("reasons") or [])[:2]
            ) or "Follow-up evidence is required"
            mention = item.get("mention")
            lines.append(
                f"| {_markdown_cell(question)} | {_markdown_cell(_safe_display(item.get('priority'), 'Unclassified'))} "
                f"| {_safe_count(item.get('samples', 0), '0')} | {_format_rate(mention)} "
                f"| {_interval_label(item.get('mention_interval'))} | {_markdown_cell(reasons)} |"
            )
        lines.append("")
    cohorts = [item for item in heatmap.get("cohorts") or [] if isinstance(item, dict)]
    if cohorts:
        lines += [
            "### Measurement cohorts",
            "",
            "| Provider | Sampling mode | Samples |",
            "|---|---|---:|",
        ]
        for cohort in cohorts:
            code = str(cohort.get("engine_code") or "")
            label = (platform_labels or {}).get(code) or cohort.get("engine_name") or code
            lines.append(
                f"| {_markdown_cell(_safe_display(label, 'Configured provider'))} "
                f"| {_markdown_cell(_insight_mode_name(cohort.get('sampling_mode')))} | {_safe_count(cohort.get('samples', 0), '0')} |"
            )
        lines.append("")
    heatmap_questions = [
        item for item in heatmap.get("questions") or []
        if isinstance(item, dict) and int(item.get("samples") or 0) > 0
    ]
    entity_totals = {}
    for question in heatmap_questions:
        for competitor in question.get("competitors") or []:
            if not isinstance(competitor, dict):
                continue
            name = str(competitor.get("name") or "").strip()
            entity_totals[name] = entity_totals.get(name, 0) + int(competitor.get("hits") or 0)
    competitor_names = [name for name, _ in sorted(entity_totals.items(), key=lambda pair: (-pair[1], pair[0])) if name][:5]
    if heatmap_questions and competitor_names:
        lines += [
            "### Competitive heatmap",
            "",
            "Rates are shown per question aggregate; sampling cohorts remain separate above.",
            "",
            "| Question | Brand | " + " | ".join(_markdown_cell(_safe_display(name, "Competitor")) for name in competitor_names) + " |",
            "|---|---:|" + "---:|" * len(competitor_names),
        ]
        for question in heatmap_questions[:8]:
            cells = {str(item.get("name")): item for item in question.get("competitors") or [] if isinstance(item, dict)}
            brand = question.get("brand") or {}
            brand_value = _format_rate(brand.get("rate"))
            row = [
                _markdown_cell(_safe_display(question.get("text"), "Configured question")),
                f"{brand_value} ({_interval_label(brand.get('interval'))})",
            ]
            for name in competitor_names:
                cell = cells.get(name) or {}
                row.append(f"{_format_rate(cell.get('rate'))} ({_interval_label(cell.get('interval'))})")
            lines.append("| " + " | ".join(row) + " |")
        lines.append("")
    if alerts:
        lines += ["### Takeover candidates", ""]
        for alert in alerts[:8]:
            question = _safe_display(alert.get("question"), "Configured question")
            competitor = _safe_display(alert.get("competitor"), "Configured competitor")
            lines.append(
                f"- **{_markdown_cell(competitor)}** is a takeover candidate for **{_markdown_cell(question)}** "
                f"on {_markdown_cell(_safe_display(alert.get('engine_name'), 'configured provider'))} "
                f"({_markdown_cell(_insight_mode_name(alert.get('sampling_mode')))}); "
                "review the raw answer before planning a change."
            )
        lines.append("")
    counts = campaigns.get("counts") or {}
    lines += [
        "### Campaign proposal gate",
        "",
        f"- Blocked: {_safe_count(counts.get('blocked', 0), '0')}; review required: {_safe_count(counts.get('review_required', 0), '0')}; ready for approval: {_safe_count(counts.get('ready_for_approval', 0), '0')}.",
        "- Expected impact is a hypothesis only. Re-test with the same question set, provider, sampling mode, and measurement policy.",
        "- No proposal authorizes publication; factual review, asset review, and explicit human approval remain required.",
        "",
    ]
    proposal_items = [item for item in campaigns.get("items") or [] if isinstance(item, dict)][:6]
    if proposal_items:
        lines += [
            "### Campaign proposals",
            "",
            "| Status | Target question | Next step |",
            "|---|---|---|",
        ]
        for item in proposal_items:
            target = item.get("target_question") or {}
            next_step = item.get("next_step") or {}
            lines.append(
                f"| {_markdown_cell(_safe_display(item.get('status'), 'Unclassified'))} "
                f"| {_markdown_cell(_safe_display(target.get('text'), 'Configured question'))} "
                f"| {_markdown_cell(_safe_display(next_step.get('label'), 'Review evidence'))} |"
            )
        lines.append("")
    return lines


DIAGNOSIS_CATEGORY_ORDER = (
    "crawlability", "content", "extractability", "structure", "authority", "semantics", "coverage", "review",
)
DIAGNOSIS_CATEGORY_HEADINGS = {
    "crawlability": "AI cannot reliably access the site",
    "content": "Pages lack enough useful content",
    "extractability": "Pages do not state facts models can quote",
    "structure": "Pages are hard for models to parse",
    "authority": "Claims lack supporting evidence",
    "semantics": "Machine-readable brand facts are missing",
    "coverage": "Language or market coverage is incomplete",
    "review": "Findings that still need a human decision",
}
DIAGNOSIS_SEVERITY_RANK = {"P0": 0, "P1": 1, "P2": 2}


def _diagnosis_groups(audit):
    groups = {}
    for finding in audit.get("site_findings") or []:
        if isinstance(finding, dict):
            _record_diagnosis_finding(groups, finding, "Site-wide")
    for page in audit.get("pages") or []:
        if not isinstance(page, dict):
            continue
        url = _safe_display(page.get("url"), "")
        if not url:
            continue
        for finding in page.get("findings") or []:
            if isinstance(finding, dict):
                _record_diagnosis_finding(groups, finding, url, page=page)
    ordered = []
    for category in DIAGNOSIS_CATEGORY_ORDER:
        items = groups.get(category) or []
        if items:
            items.sort(key=lambda item: (
                DIAGNOSIS_SEVERITY_RANK.get(item["severity"], 9),
                -item["count"],
                item["title"],
            ))
            ordered.append((category, items))
    leftover = [finding for key, items in groups.items() if key not in DIAGNOSIS_CATEGORY_HEADINGS for finding in items]
    if leftover:
        existing = next((items for key, items in ordered if key == "review"), None)
        if existing is None:
            leftover.sort(key=lambda item: (DIAGNOSIS_SEVERITY_RANK.get(item["severity"], 9), item["title"]))
            ordered.append(("review", leftover))
        else:
            existing.extend(leftover)
    return ordered


def _record_diagnosis_finding(groups, finding, location, page=None):
    title = _safe_display(finding.get("title") or finding.get("code"), "Review required")
    if not title:
        return
    category = str(finding.get("category") or "content")
    bucket = groups.setdefault(category, [])
    match = next((item for item in bucket if item["title"] == title), None)
    if match is None:
        match = {
            "code": str(finding.get("code") or ""),
            "title": title,
            "severity": str(finding.get("severity") or "P1"),
            "why": _safe_display(finding.get("detail"), "This check failed on the current crawl."),
            "change": _safe_display(finding.get("recommendation"), "Fix the failed check on the affected pages."),
            "locations": [],
            "word_counts": [],
            "count": 0,
        }
        bucket.append(match)
    if location not in match["locations"]:
        match["locations"].append(location)
        match["count"] += 1
        if isinstance(page, dict) and page.get("word_count") is not None:
            try:
                match["word_counts"].append(int(page.get("word_count")))
            except (TypeError, ValueError):
                pass
        _refresh_diagnosis_why(match)


WORD_COUNT_WHY_CODES = {"SPA_SHELL", "SHORT_CONTENT"}


MULTI_PAGE_WHY = {
    "NO_DEFINITION": "A clear, extractable definition was not detected on these pages.",
    "FEW_H2": "These pages do not have enough distinct section headings for their roles.",
    "BAD_H1": "The crawl did not find exactly one primary page heading on these pages.",
    "NO_JSONLD": "These pages have no machine-readable structured data describing their visible content.",
    "FEW_EXTERNAL_LINKS": "No external primary or independent source was detected on these pages.",
}


def _refresh_diagnosis_why(item):
    code = str(item.get("code") or "")
    if code in WORD_COUNT_WHY_CODES:
        counts = [value for value in item.get("word_counts") or [] if isinstance(value, int)]
        if len(counts) < 2:
            return
        low, high = min(counts), max(counts)
        if low == high:
            words = f"{low} words on each of {len(counts)} pages"
        else:
            words = f"{low}-{high} words across {len(counts)} pages"
        item["why"] = f"The crawl found {words}."
        return
    if item.get("count", 0) > 1 and code in MULTI_PAGE_WHY:
        item["why"] = MULTI_PAGE_WHY[code]


def _diagnosis_markdown(audit):
    groups = _diagnosis_groups(audit)
    lines = [
        "## What to change",
        "",
        "These are the website problems that currently hurt AI crawling, extraction, and mention. "
        "Each item says what to change. The tables below are the evidence.",
        "",
    ]
    if not groups:
        lines += ["No site or page problems were detected that currently block AI access or extraction.", ""]
        return lines
    for index, (category, items) in enumerate(groups, 1):
        heading = DIAGNOSIS_CATEGORY_HEADINGS.get(category, "Other findings")
        lines += [f"### {index}. {heading}", ""]
        for item in items:
            scope = "site-wide" if item["locations"] == ["Site-wide"] else f"{item['count']} page(s)"
            lines += [
                f"- **{item['title']}** ({item['severity']}, {scope})",
                f"  - Why it hurts AI: {item['why']}",
                f"  - Change this: {item['change']}",
            ]
            if item["locations"] != ["Site-wide"]:
                pages = ", ".join(f"`{url}`" for url in item["locations"])
                lines.append(f"  - Pages: {pages}")
            lines.append("")
    return lines


def _audit_markdown(project_slug, project_directory, name, site, audit, metrics, insights=None):
    site_data = audit.get("site") or {}
    coverage = audit.get("language_coverage") or {}
    grades = audit.get("applicable_grade_distribution") or audit.get("grade_distribution") or {}
    site_score = audit.get("applicable_avg_score")
    partial_score = audit.get("partial_applicable_avg_score")
    score_coverage = audit.get("score_coverage")
    evaluated_pages = _safe_count(audit.get("evaluated_page_count"), "0")
    eligible_pages = _safe_count(audit.get("score_eligible_page_count"), "0")
    score_label = _score_result_label(site_score, partial_score)
    audited_at = _safe_display(str(audit.get("audited_at") or geolib.today())[:10], "Not recorded")
    blocked_bots = _safe_join_display(site_data.get("ai_bots_blocked"), "Unlabeled crawler")
    lines = [
        f"# {name} GEO Diagnostic Report",
        "",
        f"- Official website: {site}",
        f"- Audit date: {audited_at}",
        f"- Pages reviewed: {_safe_count(audit.get('page_count', 0), '0')} "
        f"({evaluated_pages} scored, {_safe_count(audit.get('not_scored_page_count', 0), '0')} not scored, "
        f"{_safe_count(audit.get('excluded_page_count', 0), '0')} excluded)",
        "",
        "This report tells you which website content currently hurts AI access, extraction, and mention, and what to change.",
        "",
    ]
    lines += _diagnosis_markdown(audit)
    lines += [
        "## Technical Baseline",
        "",
        "| Check | Result |",
        "|---|---|",
        f"| sitemap.xml | {'Present' if site_data.get('has_sitemap') else 'Missing'} |",
        f"| llms.txt | {'Present' if site_data.get('has_llms_txt') else 'Missing'} |",
        f"| AI crawlers blocked | {blocked_bots if site_data.get('ai_bots_blocked') else 'None'} |",
        f"| Accessible pages | {_safe_count(site_data.get('pages_ok', 0), '0')}/{_safe_count(site_data.get('pages_crawled', 0), '0')} |",
        f"| English content pages (120+ words) | {_safe_count(coverage.get('en_pages', 0), 'Not measured')} |",
        "",
        f"- Applicable site score: **{score_label}**",
        f"- Scoring coverage: **{evaluated_pages}/{eligible_pages} eligible pages ({_format_rate(score_coverage)})**",
        f"- Not scored: **{_safe_count(audit.get('not_scored_page_count', 0), '0')}**; excluded: **{_safe_count(audit.get('excluded_page_count', 0), '0')}**",
        "- Scoring method: only evidence-backed checks applicable to each page role are counted.",
        "- Unmeasured AI visibility and withheld site scores are disclosed below; they do not make this report incomplete.",
        "",
        "## Grade Distribution",
        "",
        "| Grade | Pages |",
        "|---|---:|",
    ]
    lines.extend(f"| {grade} | {_safe_count(grades.get(grade, 0), '0')} |" for grade in "ABCD")
    lines.extend([
        f"| Not scored | {_safe_count(audit.get('not_scored_page_count', 0), '0')} |",
        f"| Excluded | {_safe_count(audit.get('excluded_page_count', 0), '0')} |",
    ])
    if audit.get("score_status") == "insufficient_coverage":
        lines += [
            "",
            "> Site score is withheld because scoring coverage is below the required "
            f"{float(audit.get('minimum_score_coverage') or 0.8):.0%} threshold.",
        ]
    lines += [
        "",
        "## Priority Pages",
        "",
        "| Score | Words | Grade | Role | Evaluation | Page | Primary Gaps or Reason |",
        "|---:|---:|---|---|---|---|---|",
    ]
    pages = sorted(
        audit.get("pages") or [],
        key=lambda page: (
            page.get("applicable_score") is None,
            page.get("applicable_score") if page.get("applicable_score") is not None else 101,
        ),
    )
    for page in pages:
        url = _require_english(page.get("url") or "Unknown URL", "audit page URL")
        findings = page.get("findings") or []
        issues = ", ".join(
            _require_english(item.get("title") or item.get("code") or "Review required", "audit finding")
            for item in findings[:5] if isinstance(item, dict)
        )
        if not issues and page.get("evaluation_status") != "evaluated":
            issues = _require_english(page.get("evaluation_note") or "Not scored", "audit evaluation note")
        issues = issues or "None"
        score = page.get("applicable_score")
        grade = _safe_display(page.get("applicable_grade"), "-")
        role = _require_english((page.get("role") or {}).get("label") or "Unclassified", "audit page role")
        evaluation = {
            "evaluated": "Evaluated",
            "excluded": "Excluded",
            "insufficient_evidence": "Insufficient evidence",
            "not_evaluated": "Not evaluated",
        }.get(page.get("evaluation_status"), "Not evaluated")
        lines.append(
            f"| {_format_number(score) if score is not None else 'Not scored'} | {_safe_count(page.get('word_count', 0), 'Not measured')} | {grade} "
            f"| {_markdown_cell(role)} | {evaluation} | [{_markdown_cell(url)}]({_markdown_cell(url)}) "
            f"| {_markdown_cell(issues)} |"
        )
    lines += [
        "",
        "## Extraction Coverage",
        "",
        "| Block | Missing Pages |",
        "|---|---:|",
    ]
    for gap in audit.get("block_gap") or []:
        block = BLOCK_NAMES.get(gap.get("block"), "Extraction block")
        lines.append(
            f"| {block} | {_safe_count(gap.get('missing_pages', 0), '0')}/{_safe_count(gap.get('total', 0), '0')} |"
        )

    quality = measurement.sampling_quality(project_slug)
    confidence = quality.get("confidence") or {}
    lines += [
        "", "## AI Visibility Sampling", "",
        f"**Confidence: {_safe_display(confidence.get('label'), 'No baseline')}**", "",
    ]
    for limitation in confidence.get("limitations") or []:
        lines.append(f"- Limitation: {_safe_display(limitation, 'Sampling limitation requires review')}")
    if not confidence.get("allows_global_conclusions"):
        lines.append("- Do not generalize these observations to global AI visibility or unsampled platforms.")
    lines.append("- Observed changes do not establish optimization attribution; use deployment evidence and repeated comparable periods.")
    lines.append("")
    platforms = (metrics or {}).get("platforms") or {}
    provider_config = geolib.read_json(project_directory / "geo.json", {}) or {}
    provider_config = {
        **provider_config,
        "provider_labels": _merged_provider_labels(project_directory, metrics, provider_config),
        "provider_model_ids": _merged_provider_model_ids(project_directory, metrics, provider_config),
    }
    display_names = _platform_display_names(platforms, provider_config)

    def receipt_label(code):
        return _receipt_platform_label(code, display_names, platforms, provider_config)
    if not platforms:
        lines += [
            "AI visibility is not measured for this cycle. That is a disclosed measurement gap, not a missing diagnosis.",
            "",
        ]
    else:
        modes = _sample_modes(project_directory, metrics)
        lines += [
            f"Sampling date: {_safe_display(metrics.get('date'), 'Not recorded')}",
            "",
            "| Platform | Market | Sampling Mode | Samples | Mention Rate | Top 3 Rate | Official Domain Cited |",
            "|---|---|---|---:|---:|---:|---:|",
        ]
        for code, item in platforms.items():
            code = str(code or "")
            label = display_names.get(code) or _platform_display_name(code, item, provider_config)
            lines.append(
                f"| {_markdown_cell(label)} | Global "
                f"| {_markdown_cell(_safe_display(modes.get(code), 'API - Parametric knowledge'))} | {_safe_count(item.get('samples', 0), '0')} "
                f"| {_format_rate(item.get('mention_rate'))} | {_format_rate(item.get('top3_rate'))} "
                f"| {_format_rate(item.get('own_domain_cite_rate'))} |"
            )
        lines.append("")
    receipt = (metrics or {}).get("sampling_receipt") or {}
    if receipt:
        lines += [
            "### Worker sampling receipt",
            "",
            "This receipt records the asynchronous worker execution without exposing credentials.",
            "",
            f"- Status: **{_markdown_cell(_safe_display(receipt.get('status'), 'Not recorded'))}**",
            f"- Successful samples: **{_safe_count(receipt.get('successful_samples', 0), '0')}**; failed: **{_safe_count(receipt.get('failed_samples', 0), '0')}**",
            f"- Requested platforms: **{_markdown_cell(_safe_join_display([receipt_label(item) for item in receipt.get('requested_platforms') or []], 'Configured provider'))}**",
            f"- Skipped platforms: **{_markdown_cell(_safe_join_display([receipt_label(item.get('engine_code')) for item in receipt.get('skipped_platforms') or [] if isinstance(item, dict)], 'None recorded'))}**",
        ]
        worker = receipt.get("worker") or {}
        if worker.get("runtime_env_present"):
            missing_env = [
                name for name, present in worker["runtime_env_present"].items() if not present
            ]
            missing = _safe_join_display(missing_env, "configured variable")
            lines.append(
                f"- Worker runtime environment: **{'all injected variables present' if not missing_env else 'missing ' + missing}**"
            )
        receipt_platforms = receipt.get("platforms") or {}
        if receipt_platforms:
            lines += [
                "",
                "| Worker platform | Model | Sampling mode | Status | Successful | Failed |",
                "|---|---|---|---|---:|---:|",
            ]
            for code, raw_item in sorted(receipt_platforms.items(), key=lambda pair: str(pair[0])):
                item = raw_item if isinstance(raw_item, dict) else {}
                modes = _safe_join_display(
                    [_insight_mode_name(value) for value in item.get("sampling_modes") or []],
                    "Not recorded",
                )
                model = _safe_display(
                    item.get("model_id") or _safe_join_display(item.get("model_ids"), ""),
                    "Not recorded",
                )
                platform_code = str(code or "")
                platform_label = receipt_label(platform_code)
                lines.append(
                    f"| {_markdown_cell(platform_label)} | {_markdown_cell(model)} | {_markdown_cell(modes)} "
                    f"| {_markdown_cell(_safe_display(item.get('status'), 'Not recorded'))} "
                    f"| {_safe_count(item.get('successful', 0), '0')} | {_safe_count(item.get('failed', 0), '0')} |"
                )
        lines.append("")
    lines += _insights_markdown(insights, display_names)
    return "\n".join(lines)


def _is_supporting_ticket(ticket):
    blob = " ".join(str(ticket.get(key) or "") for key in (
        "id", "title", "action", "acceptance", "acceptance_check", "package", "rationale",
    )).casefold()
    check = str(ticket.get("acceptance_check") or "")
    if "facts.md" in blob or "brand facts library" in blob:
        return True
    if check == "metrics.representative_baseline" or "visibility baseline" in blob:
        return True
    if "encyclopedia" in blob or "wikipedia" in blob or "knowledge-graph" in blob:
        return True
    if check == "site.has_llms_txt" or "/llms.txt" in blob:
        return True
    return False


def _ticket_window_bucket(ticket):
    window = re.sub(r"[_-]+", " ", str(ticket.get("window") or "").casefold())
    if re.search(r"\b30\s*days?\b", window):
        return "30 days"
    if re.search(r"\b30\s*d\b", window):
        return "30 days"
    if re.search(r"\b60\s*days?\b", window):
        return "60 days"
    if re.search(r"\b60\s*d\b", window):
        return "60 days"
    if re.search(r"\b90\s*days?\b", window):
        return "90 days"
    if re.search(r"\b90\s*d\b", window):
        return "90 days"
    return {"P0": "30 days", "P1": "60 days", "P2": "90 days"}.get(ticket.get("priority"), "90 days")


def _append_execution_tickets(lines, tickets):
    if not tickets:
        lines += ["No tickets are currently assigned to this section.", ""]
        return
    for window, heading in (
        ("30 days", "0-30 Days: Foundation"),
        ("60 days", "30-60 Days: Visibility Gains"),
        ("90 days", "60-90 Days: Scale"),
    ):
        rows = [ticket for ticket in tickets if _ticket_window_bucket(ticket) == window]
        if not rows:
            continue
        lines += [f"### {heading}", ""]
        for ticket in rows:
            lines += [
                f"#### {ticket['id']} - {ticket['title']}",
                "",
                f"- Owner: {ticket['owner']}",
                f"- Package: {ticket['package']}",
                f"- Target window: {ticket['window']}",
                f"- Rationale: {ticket['rationale']}",
                f"- Action: {ticket['action']}",
                f"- Acceptance: {ticket['acceptance']}",
            ]
            if ticket["prerequisites"]:
                lines.append("- Prerequisites: " + "; ".join(
                    f"{item['label']} ({item['status']})" for item in ticket["prerequisites"]
                ))
                if not ticket["execution_ready"]:
                    lines.append("- Execution state: Blocked until all prerequisites are met")
            lines.append("")


def _execution_markdown(name, tickets, tasks):
    baseline = tasks.get("baseline") or {}
    baseline_score = baseline.get("applicable_avg_score")
    baseline_score_label = _score_result_label(
        baseline_score, baseline.get("partial_applicable_avg_score"),
    )
    website = [ticket for ticket in tickets if not _is_supporting_ticket(ticket)]
    supporting = [ticket for ticket in tickets if _is_supporting_ticket(ticket)]
    lines = [
        f"# {name} GEO Execution Plan",
        "",
        "This plan converts the current audit into assigned work. Website changes come first. "
        "Measurement and CiteAura files are a later stage and do not block this diagnostic pack.",
        "",
        f"- Baseline site score: {baseline_score_label}",
        f"- Baseline scoring coverage: {_format_rate(baseline.get('score_coverage'))}",
        f"- Baseline pages: {_format_number(baseline.get('pages'))}",
        f"- Total tickets: {len(tickets)}",
        f"- Website-change tickets: {_format_number(len(website))}",
        f"- Measurement and delivery-asset tickets: {_format_number(len(supporting))}",
        "",
        "## Website changes",
        "",
        "Do these on the official website. They are the diagnostic actions from the audit.",
        "",
    ]
    _append_execution_tickets(lines, website)
    lines += [
        "## Measurement and delivery assets",
        "",
        "These items improve sampling or CiteAura-generated files. They do not block sending this diagnostic pack.",
        "",
    ]
    _append_execution_tickets(lines, supporting)
    lines += [
        "## Operating Cadence",
        "",
        "1. Complete website P0 blockers before scaling content production.",
        "2. Attach implementation evidence to each ticket.",
        "3. Re-crawl the site and run automated acceptance checks.",
        "4. Re-sample AI platforms using the same question set and sampling modes.",
        "5. Compare multi-period results before attributing changes to completed work.",
        "",
    ]
    return "\n".join(lines)


def _tickets_markdown(name, tickets):
    lines = [
        f"# {name} GEO Ticket Log",
        "",
        "| ID | Priority | Package | Task | Owner | Effort | Window | Verification | Status |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for ticket in tickets:
        lines.append(
            f"| {ticket['id']} | {ticket['priority']} | {_markdown_cell(ticket['package'])} "
            f"| {_markdown_cell(ticket['title'])} | {_markdown_cell(ticket['owner'])} "
            f"| {ticket['effort']} | {ticket['window']} | {ticket['verification_mode']} | {ticket['status']} |"
        )
    if not tickets:
        lines.append("| - | - | - | No unresolved action tickets for the current evidence | - | - | - | - | Complete |")
    lines += ["", "## Ticket Details", ""]
    for ticket in tickets:
        lines += [
            f"### {ticket['id']} - {ticket['title']}",
            "",
            f"- Rationale: {ticket['rationale']}",
            f"- Action: {ticket['action']}",
            f"- Acceptance: {ticket['acceptance']}",
        ]
        if ticket["prerequisites"]:
            lines.append("- Prerequisites: " + "; ".join(
                f"{item['label']} ({item['status']})" for item in ticket["prerequisites"]
            ))
        if ticket["affected"]:
            lines.append("- Affected pages: " + ", ".join(ticket["affected"][:10]))
        lines.append("")
    return "\n".join(lines)


def _affected_pages_cell(affected, limit=8):
    pages = [str(item) for item in (affected or []) if item]
    if not pages:
        return ""
    if len(pages) <= limit:
        return ", ".join(pages)
    return ", ".join(pages[:limit]) + f" (+{len(pages) - limit} more)"


def _tickets_csv(tickets):
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow([
        "ID", "Priority", "Package", "Market", "Task", "Rationale", "Action", "Owner",
        "Effort", "Window", "Prerequisites", "Acceptance Criteria", "Verification Mode", "Status", "Affected Pages",
    ])
    for ticket in tickets:
        writer.writerow([
            ticket["id"], ticket["priority"], ticket["package"], ticket["market"], ticket["title"],
            ticket["rationale"], ticket["action"], ticket["owner"], ticket["effort"], ticket["window"],
            "; ".join(f"{item['label']} ({item['status']})" for item in ticket["prerequisites"]),
            ticket["acceptance"], ticket["verification_mode"], ticket["status"],
            _affected_pages_cell(ticket["affected"]),
        ])
    return output.getvalue()


def _verification_note(result, verdict):
    progress = result.get("progress") if isinstance(result.get("progress"), dict) else None
    if progress:
        current = _format_rate(progress.get("cur")) if progress.get("pct") else _format_number(progress.get("cur"))
        target = _format_rate(progress.get("target")) if progress.get("pct") else _format_number(progress.get("target"))
        relation = "at least" if progress.get("op") == "gte" else "at most"
        return f"Current value: {current}; target: {relation} {target}."
    note = _safe_display(result.get("note_en") or result.get("note"), "")
    if note:
        return note
    return {
        "Passed": "The configured acceptance check passed.",
        "Unmet": "The configured acceptance check has not passed yet.",
        "Manual Review": "This item requires human confirmation and attached evidence.",
    }.get(verdict, "No deterministic verification detail is available.")


def _verification_markdown(name, audit, verification, tickets):
    audit_date = str(audit.get("audited_at") or "")[:10]
    verify_date = str((verification or {}).get("verified_at") or "")[:10]
    ticket_by_id = {ticket["id"]: ticket for ticket in tickets}
    current = bool(verification and (not audit_date or not verify_date or verify_date >= audit_date))
    lines = [f"# {name} GEO Acceptance Checklist", ""]
    if not current:
        reason = "No verification record is available" if not verification else "The latest verification predates the current audit"
        lines += [
            f"**Unverified for this cycle:** {reason}.",
            "",
            "Re-crawl the site after implementation before using acceptance results for this cycle.",
            "",
        ]
        return "\n".join(lines)

    verification_score = verification.get("audit_avg_score")
    verification_score_label = _score_result_label(
        verification_score, verification.get("partial_applicable_avg_score"),
    )
    lines += [
        f"- Verification date: {verify_date or 'Not recorded'}",
        f"- Re-audit applicable score: {verification_score_label}",
        f"- Re-audit scoring coverage: {_format_rate(verification.get('score_coverage'))}",
        f"- Ticket status changes: {verification.get('changed', 0)}",
        "",
        "| ID | Task | Priority | Verdict | Evidence Summary |",
        "|---|---|---|---|---|",
    ]
    for result in verification.get("results") or []:
        ticket_id = _require_english(result.get("id") or "Unnumbered", "verification ticket id")
        ticket = ticket_by_id.get(ticket_id)
        title = ticket["title"] if ticket else ticket_id
        priority = ticket["priority"] if ticket else _require_english(result.get("priority") or "", f"{ticket_id} verification priority")
        verdict = VERDICT_NAMES.get(result.get("verdict"), _safe_display(result.get("verdict"), "Manual Review"))
        lines.append(
            f"| {ticket_id} | {_markdown_cell(title)} | {priority} | {verdict} "
            f"| {_markdown_cell(_verification_note(result, verdict))} |"
        )
    lines += [
        "",
        "> Manual Review means the crawler cannot determine completion without human evidence.",
        "",
    ]
    return "\n".join(lines)


def _risk_summary(lint, asset_index=None):
    items = []
    files = lint.get("files") if isinstance(lint, dict) and isinstance(lint.get("files"), dict) else {}
    for filename, issues in files.items():
        for issue in issues if isinstance(issues, list) else []:
            items.append({
                "path": str(filename),
                "level": RISK_LEVELS.get(issue.get("level"), "Review"),
                "reason": _safe_display(issue.get("message_en") or issue.get("message"), "AI draft claim requires review"),
            })
    assets = (asset_index or {}).get("assets") if isinstance(asset_index, dict) else []
    for record in assets or []:
        if not isinstance(record, dict) or record.get("status") != "needs_review":
            continue
        reasons = record.get("issues") or ["Asset requires factual or editorial review"]
        for reason in reasons:
            reason = _safe_display(reason, "Asset requires review")
            level = "High" if any(
                token in reason.casefold() for token in ("factual", "unreviewed", "brand facts")
            ) else "Medium"
            items.append({"path": f"assets/{record.get('path')}", "level": level, "reason": reason})
    deduplicated = []
    seen = set()
    for item in items:
        key = (item["path"], item["reason"])
        if key not in seen:
            seen.add(key)
            deduplicated.append(item)
    return {
        "items": deduplicated,
        "total": len(deduplicated),
        "high": sum(item["level"] == "High" for item in deduplicated),
        "files": len({item["path"] for item in deduplicated}),
        "templates": int(((asset_index or {}).get("summary") or {}).get("template") or 0),
    }


def _risk_markdown(name, lint, asset_index=None):
    summary = _risk_summary(lint, asset_index)
    lines = [f"# {name} AI Draft Risk Report", ""]
    if not summary["items"] and not summary["templates"]:
        lines += ["No generated draft or asset risks require review for this cycle.", ""]
        return "\n".join(lines)
    lines += [
        "These items are implementation publication risks. They do not block the diagnostic pack.",
        "",
        f"- Files requiring review: {summary['files']}",
        f"- Review findings: {summary['total']}",
        f"- High-risk findings: {summary['high']}",
        f"- Incomplete templates: {summary['templates']}",
        "",
    ]
    if summary["items"]:
        lines += [
            "**Do not publish affected drafts until manual verification is complete.**",
            "",
            "| File | Risk Level | Reason | Required Action |",
            "|---|---|---|---|",
        ]
        for item in summary["items"]:
            filename = _require_english(item["path"], "draft risk filename")
            reason = _require_english(item["reason"], "draft risk reason")
            lines.append(
                f"| `{_markdown_cell(filename)}` | {item['level']} | {_markdown_cell(reason)} "
                "| Verify claims and attach attributable evidence before publication. |"
            )
        lines.append("")
    else:
        lines += ["No reviewable claims were detected; incomplete templates remain non-publishable.", ""]
    return "\n".join(lines)


def _channel_name(channel):
    channel_id = str(channel.get("id") or "")
    if channel.get("strategy_profile") and channel.get("name"):
        return _require_english(channel["name"], "blueprint channel name")
    if channel_id in CHANNEL_NAMES:
        return CHANNEL_NAMES[channel_id]
    return _require_english(channel.get("name") or channel_id or "Configured channel", "blueprint channel name")


def _delivery_question(content, content_id):
    """英文交付保留英文问题，其他市场用稳定引用，不改项目源问题。"""
    question = str(content.get("question") or "").strip()
    if question and not _contains_han(question):
        return question
    market = MARKET_NAMES.get(content.get("market"), "Global")
    return f"Configured {market} target question {content_id}"


def _is_financial_question(question):
    value = str(question or "").casefold()
    return any(token in value for token in (
        "money", "payment", "transfer", "currency", "exchange rate", "atm", "cash",
        "card", "bank", "finance", "financial", "remittance", "withdraw", "funds",
    ))


def _content_intent(content, question):
    value = str(question or "").casefold()
    if re.search(r"\b(?:what|which)\s+app\s+should\s+i\s+use\b", value) or "best app" in value:
        return "Recommendation"
    if any(token in value for token in (
        "how much", "price", "pricing", "cost", "fee", "fees", "exchange rate",
        "withdrawal limit", "withdrawal limits", "hidden charge", "hidden charges",
    )):
        return "Pricing"
    if any(token in value for token in (
        "legitimate", "safe", "safety", "secure", "security", "regulated", "regulator",
        "licence", "license", "safeguard", "fund protection",
    )):
        return "Risk"
    if any(token in value for token in ("alternative to", "alternatives to", "instead of")):
        return "Alternatives"
    if "comparison" in value or "better to use" in value or re.search(r"\b(?:compare|versus|vs)\.?\b", value):
        return "Comparison"
    return GROUP_NAMES.get(content.get("group"), _safe_display(content.get("group"), "Recommendation"))


def _content_form(intent, question):
    if intent == "Pricing":
        return "Transparent Pricing and Fees Page" if _is_financial_question(question) else "Transparent Pricing Page"
    if intent == "Risk":
        return "Trust, Regulation, and Safeguarding Page" if _is_financial_question(question) else "Security and Reliability Page"
    return {
        "Recommendation": "Evidence-Based Recommendation Page",
        "Comparison": "Comparison Matrix Page",
        "Alternatives": "Alternative Guide Page",
        "Use case": "How-To Tutorial Page",
        "Brand verification": "Entity Verification and Evidence Page",
    }.get(intent, "Definition or Guide Page")


def _build_map_markdown(name, blueprint):
    channels = [
        channel for channel in blueprint.get("channels") or []
        if isinstance(channel, dict) and channel.get("market") in ("global", "both", None)
    ]
    contents = [
        content for content in blueprint.get("contents") or []
        if isinstance(content, dict)
        and content.get("market") in ("global", "both", None)
        and not _contains_han(content.get("question"))
    ]
    coverage = {
        **global_scope.summarize_channel_coverage(channels),
        "content_total": len(contents),
        "content_done": sum(content.get("status") == "ready" for content in contents),
    }
    lines = [
        f"# {name} GEO Build Map",
        "",
        "This map defines where authority should be built and which target-query content should be produced.",
        "",
        f"- Channel coverage: **{coverage.get('channel_covered', 0)}/{coverage.get('channel_total', 0)}**",
        f"- P0/P1 channel coverage: **{coverage.get('p0p1_covered', 0)}/{coverage.get('p0p1_total', 0)}**",
        f"- Content completed: **{coverage.get('content_done', 0)}/{coverage.get('content_total', 0)}**",
    ]
    if coverage.get("channel_manual"):
        lines.append(f"- Channels requiring manual confirmation: **{coverage['channel_manual']}**")
    lines.append("")
    strategy = blueprint.get("channel_strategy") or {}
    if strategy:
        lines += [
            f"- Strategy profile: **{strategy.get('label', 'Configured profile')}**",
            f"- Profile confidence: **{strategy.get('confidence', 'unknown').title()}**",
        ]
        evidence = strategy.get("evidence") or []
        if evidence:
            lines.append(f"- Profile evidence: {', '.join(str(item) for item in evidence)}")
        if strategy.get("review_required"):
            if strategy.get("id") == "generic":
                lines.append("- Review required: project metadata was insufficient, so neutral cross-industry channels were used.")
            else:
                lines.append("- Review required: confirm or correct the inferred business profile before executing profile-specific channels.")
        lines.append("")
    lines += [
        "## Channel Map",
        "",
        "| Priority | Channel | Market | Coverage | Evidence |",
        "|---|---|---|---|---|",
    ]
    for channel in sorted(channels, key=lambda item: (item.get("priority", "P9"), str(item.get("id", "")))):
        coverage_status = global_scope.channel_coverage_status(channel)
        evidence = []
        evidence.extend(f"brand-linked citation on {domain}" for domain in channel.get("coverage_evidence") or [])
        evidence.extend(
            f"source observed on {domain}" for domain in channel.get("observed_source_evidence") or []
        )
        if channel.get("national") is not None:
            evidence.append(f"{channel['national']:,} observed citations")
        if channel.get("position") is not None:
            evidence.append(f"average placement #{channel['position']}")
        if channel.get("platforms") is not None:
            evidence.append(f"observed across {channel['platforms']} platforms")
        status = {
            "brand_cited": "Brand cited",
            "covered": "Covered (legacy)",
            "observed_source": "Observed source",
            "gap": "Gap",
            "manual": "Manual review",
        }[coverage_status]
        if coverage_status == "manual" and not evidence:
            evidence.append("Requires confirmation against project-specific channels")
        lines.append(
            f"| {_require_english(channel.get('priority') or 'P2', 'channel priority')} "
            f"| {_markdown_cell(_channel_name(channel))} | Global "
            f"| {status} | {_markdown_cell('; '.join(evidence) or 'No citation evidence yet')} |"
        )

    lines += [
        "",
        "## Content Map",
        "",
        "| ID | Target | Intent | Market | Form | Status |",
        "|---|---|---|---|---|---|",
    ]
    for content in contents:
        content_id = _require_english(content.get("id") or "Unnumbered", "content id")
        question = _delivery_question(content, content_id)
        intent = _content_intent(content, question)
        form = _content_form(intent, question)
        status_name = {
            "ready": "Ready",
            "draft": "Draft",
            "outline_only": "Outline Only",
            "gap": "Gap",
            "已成稿": "Ready",
            "仅大纲": "Outline Only",
        }.get(content.get("status"), _safe_display(content.get("status"), "Gap"))
        lines.append(
            f"| {content_id} | {_markdown_cell(question)} | {_markdown_cell(intent)} "
            f"| Global "
            f"| {_markdown_cell(form)} | {status_name} |"
        )

    lines += ["", "## 30/60/90-Day Roadmap", ""]
    for priority, window, focus in (
        ("P0", "0-30 Days", "Foundational baseline"),
        ("P1", "30-60 Days", "High-leverage authority and content"),
        ("P2", "60-90 Days", "Scale and closed-loop verification"),
    ):
        names = [_channel_name(channel) for channel in channels if channel.get("priority") == priority]
        lines += [f"### {window}: {focus}", ""]
        lines += [f"- {channel_name}" for channel_name in names] or ["- No channels are currently assigned to this phase."]
        lines.append("")
    return "\n".join(lines)

__all__ = tuple(name for name in globals() if not name.startswith("__"))
