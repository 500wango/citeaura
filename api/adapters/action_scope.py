"""Align action tickets and verification with the role-aware audit contract."""

from copy import deepcopy


SCOPE_VERSION = 1

BLOCK_IDS = {
    "definition": "definition",
    "\u5b9a\u4e49": "definition",
    "numeric_facts": "numeric_facts",
    "\u6570\u5b57\u4e8b\u5b9e": "numeric_facts",
    "comparison": "comparison",
    "\u5bf9\u6bd4": "comparison",
    "steps": "steps",
    "\u64cd\u4f5c\u6b65\u9aa4": "steps",
    "faq": "faq",
}

CHECK_COPY = {
    "accessibility": (
        "Restore access to applicable public pages",
        "Restore a stable public HTTP response for each affected page.",
        "crawlability",
        "P0",
    ),
    "indexability": (
        "Make applicable public pages indexable",
        "Remove noindex only from pages intended for public discovery.",
        "crawlability",
        "P0",
    ),
    "canonical": (
        "Add canonical URLs to applicable public pages",
        "Add a correct self-referencing or preferred canonical URL to each affected page.",
        "crawlability",
        "P1",
    ),
    "rendered_content": (
        "Render meaningful HTML on applicable public pages",
        "Use server rendering, static generation, or prerendering for the affected public routes.",
        "crawlability",
        "P0",
    ),
    "h1": (
        "Use one clear H1 on applicable pages",
        "Give each affected page one descriptive primary heading that states its purpose.",
        "structure",
        "P1",
    ),
    "content_depth": (
        "Add role-appropriate content to thin public pages",
        "Add concise, decision-useful information that fulfills each affected page's role.",
        "content",
        "P1",
    ),
    "section_structure": (
        "Improve section structure on applicable pages",
        "Organize the affected pages under descriptive, intent-led section headings.",
        "structure",
        "P1",
    ),
    "structured_data": (
        "Add page-appropriate JSON-LD to applicable content pages",
        "Add only Schema.org types and properties supported by visible content and verified facts.",
        "semantics",
        "P1",
    ),
    "definition": (
        "Add clear definitions to applicable pages",
        "State plainly what the subject or offering is and who it serves on each affected page.",
        "content",
        "P1",
    ),
    "numeric_facts": (
        "Add verified numeric facts to applicable pages",
        "Add role-relevant prices, specifications, outcomes, or other verified figures.",
        "content",
        "P1",
    ),
    "comparison": (
        "Add the promised comparison to applicable pages",
        "Compare named options with consistent, evidence-backed criteria.",
        "content",
        "P1",
    ),
    "steps": (
        "Add extractable steps to procedural guides",
        "Present each verified procedure as ordered steps with prerequisites and explicit actions.",
        "content",
        "P1",
    ),
    "faq": (
        "Add answerable questions to applicable support pages",
        "Add concise answers to recurring questions on pages whose role requires an FAQ.",
        "content",
        "P1",
    ),
    "date": (
        "Add accurate dates to applicable pages",
        "Show an accurate publication or update date and keep structured data consistent with it.",
        "authority",
        "P2",
    ),
    "external_evidence": (
        "Add relevant evidence paths to applicable pages",
        "Cite relevant primary or independent sources for material claims on the affected pages.",
        "authority",
        "P2",
    ),
}

SITE_COPY = {
    "site.no_ai_bot_block": (
        "Unblock required AI crawlers in robots.txt",
        "Confirm the crawler policy and remove sitewide blocks for the engines required by the measurement strategy.",
        "P0",
    ),
    "site.has_sitemap": (
        "Add and submit sitemap.xml",
        "Publish a current sitemap, reference it from robots.txt, and submit it to relevant search engines.",
        "P1",
    ),
    "site.has_llms_txt": (
        "Publish the approved facts index at /llms.txt",
        "Publish a maintained facts index after its claims have passed factual review.",
        "P2",
    ),
}

SITE_FINDING_CHECKS = {
    "AI_BOTS_BLOCKED": "site.no_ai_bot_block",
    "NO_SITEMAP": "site.has_sitemap",
    "NO_LLMS_TXT": "site.has_llms_txt",
}


def _check(task):
    if task.get("scope_original_check"):
        return str(task["scope_original_check"])
    acceptance = task.get("acceptance") if isinstance(task.get("acceptance"), dict) else {}
    return str(acceptance.get("check") or "")


def _page_check(check):
    if check == "pages.static_text":
        return "rendered_content"
    if check == "pages.has_jsonld":
        return "structured_data"
    if check.startswith("pages.block:"):
        return BLOCK_IDS.get(check.split(":", 1)[1].casefold())
    if check.startswith("pages.wordcount_gte:"):
        return "content_depth"
    if check.startswith("pages.applicable:"):
        value = check.split(":", 1)[1]
        return value if value in CHECK_COPY else None
    return None


def _page_rows(audit, check_id):
    rows = []
    allowed = {"evaluated"}
    if check_id == "rendered_content":
        allowed.add("insufficient_evidence")
    for page in audit.get("pages") or []:
        if not isinstance(page, dict) or page.get("evaluation_status") not in allowed:
            continue
        check = next((item for item in page.get("checks") or [] if item.get("id") == check_id), None)
        if check and check.get("status") in ("passed", "failed"):
            rows.append((page, check))
    return rows


def _failed_pages(audit, check_id):
    rows = _page_rows(audit, check_id)
    return [str(page.get("url") or "") for page, check in rows if check.get("status") == "failed"], len(rows)


def _customer_facing_priority(task):
    """站点访问/内容问题优先；事实库和采样基线不占 P0。"""
    blob = " ".join(str(task.get(key) or "") for key in ("id", "title", "title_en", "action", "action_en")).casefold()
    check = _check(task)
    if "facts.md" in blob or "brand facts library" in blob:
        return "P2"
    if "four surfaces" in blob:
        return "P1"
    if check == "metrics.representative_baseline" or "representative ai visibility" in blob:
        return "P1"
    return None


def _dedupe_prerequisites(items):
    unique = {}
    leftover = []
    for item in items or []:
        if isinstance(item, dict) and item.get("id"):
            unique[item["id"]] = item
        elif item:
            leftover.append(item)
    return leftover + list(unique.values())


def _task_summary(tasks):
    packages = list(dict.fromkeys(task.get("package") for task in tasks if task.get("package")))
    return {
        "total": len(tasks),
        "by_priority": {priority: sum(task.get("priority") == priority for task in tasks) for priority in ("P0", "P1", "P2")},
        "by_status": {
            status: sum(task.get("status") == status for task in tasks)
            for status in ("todo", "doing", "done", "blocked", "wontfix")
        },
        "by_package": {package: sum(task.get("package") == package for task in tasks) for package in packages},
        "by_market": {
            market: sum(task.get("market") == market for task in tasks)
            for market in ("cn", "global", "both")
        },
        "auto_verifiable": sum(
            isinstance(task.get("acceptance"), dict) and task["acceptance"].get("type") == "auto"
            for task in tasks
        ),
    }


def _source_tasks(data):
    sources = []
    seen = set()
    groups = [
        data.get("tasks") or [],
        data.get("scope_excluded_tasks") or [],
        data.get("scope_deferred_tasks") or [],
    ]
    for group in groups:
        for raw in group:
            if not isinstance(raw, dict) or (raw.get("scope_generated") and not raw.get("workflow_customized")):
                continue
            task = deepcopy(raw)
            task.pop("scope_exclusion_reason", None)
            key = str(task.get("id") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            sources.append(task)
    return sources


def _scope_page_task(task, audit, check_id):
    affected, total = _failed_pages(audit, check_id)
    # A current crawl is authoritative when it has applicable failures. Historical
    # cohorts remain useful only for manually retained workflow items.
    cohort = list(affected or task.get("verification_cohort") or task.get("affected") or [])
    title, action, package, priority = CHECK_COPY[check_id]
    acceptance = task.get("acceptance") if isinstance(task.get("acceptance"), dict) else {}
    scoped = {
        **task,
        "title": title,
        "title_en": title,
        "why": f"{len(affected)} of {total} applicable page(s) currently fail this role-aware check.",
        "why_en": f"{len(affected)} of {total} applicable page(s) currently fail this role-aware check.",
        "action": action,
        "action_en": action,
        "package": "Page technology" if package in ("crawlability", "semantics") else "Content matrix",
        "package_en": "Page technology" if package in ("crawlability", "semantics") else "Content matrix",
        "priority": priority,
        "market": task.get("market") if task.get("market") in ("cn", "global", "both") else "both",
        "affected": affected,
        "verification_cohort": cohort,
        "scope_original_check": _check(task),
        "scope_page_check": check_id,
        "acceptance": {
            **acceptance,
            "type": "auto",
            "check": f"pages.applicable:{check_id}",
            "desc": "Every currently affected applicable page passes this role-aware check on re-crawl.",
            "desc_en": "Every currently affected applicable page passes this role-aware check on re-crawl.",
        },
        "progress": {
            "label": "Applicable pages still failing",
            "cur": len(affected),
            "target": 0,
            "op": "lte",
        },
    }
    scoped.pop("progress_first", None)
    return scoped, affected


def _synthetic_page_task(check_id, audit):
    title, action, package, priority = CHECK_COPY[check_id]
    task = {
        "id": f"T-AUDIT-{check_id.replace('_', '-').upper()}",
        "priority": priority,
        "package": "Page technology" if package in ("crawlability", "semantics") else "Content matrix",
        "market": "both",
        "title": title,
        "why": "The role-aware audit found an applicable page-level gap that was absent from the raw engine task set.",
        "action": action,
        "owner": "Engineering" if package in ("crawlability", "semantics", "structure") else "Content",
        "effort": "S" if check_id in ("canonical", "date", "h1") else "M",
        "window": "30 days" if priority == "P0" else "60 days",
        "acceptance": {
            "type": "auto",
            "check": f"pages.applicable:{check_id}",
            "desc": "Every currently affected applicable page passes this role-aware check on re-crawl.",
            "desc_en": "Every currently affected applicable page passes this role-aware check on re-crawl.",
        },
        "status": "todo",
        "scope_generated": True,
        "scope_page_check": check_id,
    }
    return _scope_page_task(task, audit, check_id)[0]


def _facts_prerequisite(facts_approved):
    return {
        "id": "facts_approved",
        "label": "Brand facts library has passed factual review",
        "status": "met" if facts_approved else "pending",
    }


def _scope_site_task(task, check, facts_approved=None):
    if check != "site.has_llms_txt" or facts_approved is None:
        return task
    title, action, _priority = SITE_COPY[check]
    acceptance = task.get("acceptance") if isinstance(task.get("acceptance"), dict) else {}
    return {
        **task,
        "title": title,
        "title_en": title,
        "action": action,
        "action_en": action,
        "prerequisites": [_facts_prerequisite(facts_approved)],
        "acceptance": {
            **acceptance,
            "type": "auto",
            "check": check,
            "desc": "The brand facts library is approved and /llms.txt is retrieved successfully on re-crawl.",
            "desc_en": "The brand facts library is approved and /llms.txt is retrieved successfully on re-crawl.",
        },
    }


def _synthetic_site_task(check, facts_approved=None):
    title, action, priority = SITE_COPY[check]
    task = {
        "id": "T-AUDIT-" + check.rsplit(".", 1)[-1].replace("_", "-").upper(),
        "priority": priority,
        "package": "Page technology" if check != "site.has_llms_txt" else "Knowledge base",
        "market": "both",
        "title": title,
        "why": "The role-aware site audit found this unresolved site-level gap.",
        "action": action,
        "owner": "Engineering",
        "effort": "S",
        "window": "30 days" if priority == "P0" else "60 days",
        "affected": [],
        "acceptance": {"type": "auto", "check": check, "desc": "The site-level check passes on re-crawl."},
        "status": "todo",
        "scope_generated": True,
    }
    return _scope_site_task(task, check, facts_approved)


def _sampling_sufficient(quality):
    return bool(((quality or {}).get("confidence") or {}).get("sufficient"))


def _sampling_task(quality):
    confidence = (quality or {}).get("confidence") or {}
    minimum_samples = int(confidence.get("minimum_samples") or 20)
    minimum_platforms = int(confidence.get("minimum_platforms") or 2)
    return {
        "id": "T-MEASUREMENT-BASELINE",
        "priority": "P0",
        "package": "Measurement loop",
        "market": "both",
        "title": "Establish a representative AI visibility baseline",
        "why": "Current sampling is insufficient for global performance conclusions or target-based optimization tickets.",
        "action": (
            f"Collect at least {minimum_samples} valid unprompted samples across at least "
            f"{minimum_platforms} answer engines using the current question set and recorded sampling modes."
        ),
        "owner": "GEO strategist",
        "effort": "M",
        "window": "30 days",
        "affected": [],
        "acceptance": {
            "type": "auto",
            "check": "metrics.representative_baseline",
            "desc": f"At least {minimum_samples} valid samples and {minimum_platforms} sampled platforms are recorded.",
        },
        "status": "todo",
        "scope_generated": True,
    }


def scope_task_data(data, audit, sampling_quality=None, facts_approved=None):
    """Rebuild the active action set from applicable failures and sample confidence."""
    current = deepcopy(data) if isinstance(data, dict) else {}
    audit = audit if isinstance(audit, dict) else {}
    active = []
    excluded = []
    deferred = []
    covered_page_checks = set()
    covered_site_checks = set()
    metric_tasks = []

    for task in _source_tasks(current):
        check = _check(task)
        page_check = _page_check(check)
        if page_check:
            scoped, affected = _scope_page_task(task, audit, page_check)
            retained = task.get("status") in ("doing", "blocked", "done", "wontfix")
            if affected or retained or task.get("workflow_customized"):
                active.append(scoped)
                covered_page_checks.add(page_check)
            else:
                task["scope_exclusion_reason"] = "no_applicable_failure"
                excluded.append(task)
            continue
        if check.startswith("site.avg_score_gte:"):
            try:
                target = float(check.rsplit(":", 1)[-1])
            except ValueError:
                active.append(task)
                continue
            score = audit.get("applicable_avg_score")
            if score is not None and float(score) >= target and task.get("status") not in ("done", "wontfix"):
                task["scope_exclusion_reason"] = "applicable_score_already_meets_target"
                excluded.append(task)
                continue
            title = f"Raise the applicable site audit score to {target:g}"
            existing_prerequisites = task.get("prerequisites")
            prerequisites = [
                item for item in (existing_prerequisites if isinstance(existing_prerequisites, list) else [])
                if not isinstance(item, dict) or item.get("id") not in {"score_coverage", "rendered_content"}
            ]
            if score is None:
                minimum_coverage = float(audit.get("minimum_score_coverage") or 0.8)
                coverage = audit.get("score_coverage")
                coverage_label = "not measurable" if coverage is None else f"{float(coverage):.0%}"
                empty_shells, _total = _failed_pages(audit, "rendered_content")
                why = (
                    f"The applicable site score is withheld because scoring coverage is {coverage_label}; "
                    f"at least {minimum_coverage:.0%} is required before comparing it with the {target:g} target."
                )
                action = (
                    "First server-render empty-shell public pages so they can be scored. Then resolve the "
                    "failed role-aware checks; do not apply content, schema, or extraction requirements to "
                    "excluded utility pages or roles where they are not applicable."
                )
                progress = None
                prerequisites.append({
                    "id": "score_coverage",
                    "label": f"Role-aware scoring coverage reaches at least {minimum_coverage:.0%}",
                    "status": "pending",
                })
                if empty_shells:
                    prerequisites.append({
                        "id": "rendered_content",
                        "label": "Server-render empty-shell public pages so they can be scored",
                        "status": "pending",
                    })
            else:
                why = f"The role-aware applicable score is {score}; the target is {target:g}."
                action = (
                    "Resolve the failed role-aware checks on applicable public pages. Do not apply content, "
                    "schema, or extraction requirements to excluded utility pages or roles where they are not applicable."
                )
                progress = {
                    "label": "Applicable site score",
                    "cur": score,
                    "target": target,
                    "op": "gte",
                }
            affected = [
                str(page.get("url") or "")
                for page in audit.get("pages") or []
                if isinstance(page, dict)
                and page.get("evaluation_status") == "evaluated"
                and any(item.get("status") == "failed" for item in page.get("checks") or [])
            ]
            scoped = {
                **task,
                "title": title,
                "title_en": title,
                "why": why,
                "why_en": why,
                "action": action,
                "action_en": action,
                "affected": affected,
                "prerequisites": _dedupe_prerequisites(prerequisites),
                "acceptance": {
                    **(task.get("acceptance") if isinstance(task.get("acceptance"), dict) else {}),
                    "type": "auto",
                    "check": check,
                    "desc": f"The role-aware applicable site score reaches at least {target:g}.",
                    "desc_en": f"The role-aware applicable site score reaches at least {target:g}.",
                },
                "progress": progress,
                "scope_original_check": check,
            }
            scoped.pop("progress_first", None)
            active.append(scoped)
            continue
        if check.startswith("metrics.mention_rate_gte:") or check.startswith("metrics.own_cite_gte:"):
            metric_tasks.append(task)
            continue
        if check == "metrics.representative_baseline":
            if _sampling_sufficient(sampling_quality):
                task["scope_exclusion_reason"] = "representative_baseline_established"
                excluded.append(task)
            else:
                active.append(task)
            continue
        if check in SITE_COPY:
            task = _scope_site_task(task, check, facts_approved)
            covered_site_checks.add(check)
            passed = _site_result(audit.get("site") or {}, check, facts_approved)
            if passed and task.get("status") not in ("done", "wontfix") and not task.get("workflow_customized"):
                task["scope_exclusion_reason"] = "site_check_already_passes"
                excluded.append(task)
                continue
        active.append(task)

    if _sampling_sufficient(sampling_quality):
        active.extend(metric_tasks)
    else:
        deferred.extend(metric_tasks)
        if not any(_check(task) == "metrics.representative_baseline" for task in active):
            active.append(_sampling_task(sampling_quality))

    for check_id in CHECK_COPY:
        affected, _total = _failed_pages(audit, check_id)
        if affected and check_id not in covered_page_checks:
            active.append(_synthetic_page_task(check_id, audit))

    for finding in audit.get("site_findings") or []:
        check = SITE_FINDING_CHECKS.get(finding.get("code")) if isinstance(finding, dict) else None
        if check and check not in covered_site_checks:
            active.append(_synthetic_site_task(check, facts_approved))
            covered_site_checks.add(check)

    baseline = deepcopy(current.get("baseline") if isinstance(current.get("baseline"), dict) else {})
    if audit.get("applicable_avg_score") is not None:
        baseline["raw_avg_score"] = baseline.get("raw_avg_score", baseline.get("avg_score"))
        baseline["avg_score"] = audit["applicable_avg_score"]
        baseline["applicable_avg_score"] = audit["applicable_avg_score"]
        baseline["score_method"] = "applicable_page_role_v1"
    baseline["pages"] = audit.get("page_count", baseline.get("pages"))
    baseline["applicable_pages"] = sum(
        page.get("evaluation_status") == "evaluated" for page in audit.get("pages") or [] if isinstance(page, dict)
    )
    baseline["score_eligible_pages"] = audit.get("score_eligible_page_count")
    baseline["score_coverage"] = audit.get("score_coverage")
    baseline["score_status"] = audit.get("score_status")
    baseline["partial_applicable_avg_score"] = audit.get("partial_applicable_avg_score")

    deduplicated = []
    seen_ids = set()
    for task in active:
        task_id = str(task.get("id") or "")
        if task_id and task_id not in seen_ids:
            seen_ids.add(task_id)
            if task.get("prerequisites"):
                task["prerequisites"] = _dedupe_prerequisites(task.get("prerequisites"))
            override = _customer_facing_priority(task)
            if override:
                task["priority"] = override
            deduplicated.append(task)
    return {
        **current,
        "baseline": baseline,
        "tasks": deduplicated,
        "summary": _task_summary(deduplicated),
        "scope_version": SCOPE_VERSION,
        "scope_excluded_tasks": excluded,
        "scope_deferred_tasks": deferred,
    }


def _site_result(site, check, facts_approved=None):
    if check == "site.no_ai_bot_block":
        if "ai_bots_blocked" not in site:
            return None
        return not bool(site.get("ai_bots_blocked"))
    if check == "site.has_sitemap":
        return bool(site.get("has_sitemap"))
    if check == "site.has_llms_txt":
        deployed = bool(site.get("has_llms_txt"))
        return deployed if facts_approved is None else deployed and bool(facts_approved)
    return None


def scope_verification(verification, task_data, audit, sampling_quality=None, facts_approved=None):
    """Recompute deterministic acceptance values using the same scoped evidence as the report."""
    source = deepcopy(verification) if isinstance(verification, dict) else {}
    source_results = {
        str(result.get("id")): result
        for result in source.get("results") or [] if isinstance(result, dict) and result.get("id")
    }
    results = []
    for task in task_data.get("tasks") or []:
        task_id = str(task.get("id") or "")
        check = _check(task)
        page_check = _page_check(check)
        result = deepcopy(source_results.get(task_id) or {})
        result.update({"id": task_id, "priority": task.get("priority")})
        if page_check:
            cohort = list(task.get("verification_cohort") or task.get("affected") or [])
            pages = {str(page.get("url") or ""): page for page in audit.get("pages") or []
                     if isinstance(page, dict)}
            missing = []
            failed = []
            for url in cohort:
                page = pages.get(url)
                if not page:
                    missing.append(url)
                    continue
                check_row = next((item for item in page.get("checks") or [] if item.get("id") == page_check), None)
                if check_row and check_row.get("status") == "failed":
                    failed.append(url)
                elif check_row and check_row.get("status") == "passed":
                    continue
                else:
                    missing.append(url)
            missing = list(dict.fromkeys(missing))
            verdict = "manual" if missing else "fail" if failed else "pass"
            note = (f"{len(missing)} baseline URL(s) were not evaluated in the current crawl; pass is withheld."
                    if missing else
                    f"{len(failed)} baseline page(s) still fail the role-aware {page_check} check.")
            result.update({
                "verdict": verdict,
                "progress": {"label": "Baseline pages still failing", "cur": len(failed),
                             "target": 0, "op": "lte", "missing": len(missing), "base": len(cohort)},
                "note_en": note,
            })
        elif check in SITE_COPY:
            passed = _site_result(audit.get("site") or {}, check, facts_approved)
            if check == "site.has_llms_txt" and facts_approved is not None:
                note = (
                    "The approved brand facts library and deployed /llms.txt both pass the current checks."
                    if passed else
                    "Completion requires both an approved brand facts library and a retrievable /llms.txt."
                )
            else:
                note = "The current role-aware site evidence passes this check." if passed else "The current role-aware site evidence still fails this check."
            result.update({
                "verdict": "pass" if passed else "fail",
                "progress": None,
                "note_en": note,
            })
        elif check.startswith("site.avg_score_gte:"):
            try:
                target = float(check.rsplit(":", 1)[-1])
            except ValueError:
                target = 0
            score = audit.get("applicable_avg_score")
            if score is None:
                coverage = audit.get("score_coverage")
                minimum_coverage = float(audit.get("minimum_score_coverage") or 0.8)
                coverage_label = "not measurable" if coverage is None else f"{float(coverage):.0%}"
                result.update({
                    "verdict": "fail",
                    "progress": None,
                    "note_en": (
                        f"The site score is withheld because role-aware scoring coverage is {coverage_label}; "
                        f"at least {minimum_coverage:.0%} is required before the {target:g} target can be assessed."
                    ),
                })
                results.append(result)
                continue
            result.update({
                "verdict": "pass" if float(score) >= target else "fail",
                "progress": {"label": "Applicable site score", "cur": score, "target": target, "op": "gte"},
                "note_en": "The applicable page-role score is used for this acceptance check.",
            })
        elif check == "metrics.representative_baseline":
            confidence = (sampling_quality or {}).get("confidence") or {}
            current = (sampling_quality or {}).get("current") or {}
            sufficient = bool(confidence.get("sufficient"))
            result.update({
                "verdict": "pass" if sufficient else "fail",
                "progress": None,
                "note_en": (
                    f"Current baseline: {int(current.get('effective_visibility_samples') or 0)} valid sample(s) "
                    f"across {int(current.get('platform_count') or confidence.get('platform_count') or 0)} platform(s); "
                    f"minimum: {int(confidence.get('minimum_samples') or 20)} samples across "
                    f"{int(confidence.get('minimum_platforms') or 2)} platforms."
                ),
            })
        elif result:
            result.setdefault("verdict", "manual")
        else:
            result.update({"verdict": "manual", "progress": None, "note_en": "This item requires human confirmation and attached evidence."})
        results.append(result)

    return {
        **source,
        "verified_at": source.get("verified_at") or audit.get("audited_at"),
        "audit_avg_score": audit.get("applicable_avg_score"),
        "partial_applicable_avg_score": audit.get("partial_applicable_avg_score"),
        "score_coverage": audit.get("score_coverage"),
        "score_status": audit.get("score_status"),
        "score_method": "applicable_page_role_v1",
        "results": results,
    }
