"""交付包生成资产与 Schema.org 渲染。"""

from api.adapters.delivery_common import *  # noqa: F401,F403
from api.adapters.delivery_documents import (
    _content_form,
    _content_intent,
    _delivery_question,
    _is_financial_question,
)

def _replace_json_asset(value, field=None, parent_type=None, ordinal=None):
    if isinstance(value, dict):
        result = {}
        item_type = value.get("@type")
        for key, item in value.items():
            translated_key = JSON_ASSET_REPLACEMENTS.get(str(key), str(key))
            result[translated_key] = _replace_json_asset(
                item,
                field=translated_key,
                parent_type=item_type,
                ordinal=ordinal,
            )
        return result
    if isinstance(value, list):
        return [
            _replace_json_asset(item, field=field, parent_type=parent_type, ordinal=index + 1)
            for index, item in enumerate(value)
        ]
    if isinstance(value, str):
        value = JSON_ASSET_REPLACEMENTS.get(value, value)
        if field == "priceCurrency" and re.fullmatch(r"[A-Za-z]{3}", value.strip()):
            return value.strip().upper()
        if not _contains_han(value):
            return normalize_english_typography(value)
        if field == "name" and parent_type == "Question":
            return f"Configured Global target question {ordinal or 1}"
        if field == "headline":
            return "[Add an approved English headline containing the target query.]"
        if field in ("description", "about"):
            return "[Add the approved English brand description.]"
        if field == "text" and parent_type == "Answer":
            return "[Add a direct English answer followed by supporting evidence.]"
        if field == "priceCurrency":
            return "[Add an ISO 4217 currency code.]"
        return "[Add an approved English value.]"
    return value


def _generated_placeholder(value):
    value = str(value or "").strip()
    return (
        not value
        or value.startswith("[Add ")
        or value.startswith("Configured Global target question ")
    )


def _project_json_asset(value, config, facts=None):
    """Normalize engine JSON-LD and refill safe fields from the project fact contract."""
    value = _replace_json_asset(value)
    facts = facts if isinstance(facts, dict) else {}
    brand = config.get("brand") if isinstance(config.get("brand"), dict) else {}
    name = _safe_display(facts.get("name") or brand.get("name"), "")
    definition = _safe_display(facts.get("definition"), "")
    aliases = [
        _safe_display(alias, "") for alias in brand.get("aliases") or []
        if _safe_display(alias, "")
    ]
    questions = [
        str(question.get("text") or "").strip()
        for question in config.get("questions") or []
        if isinstance(question, dict)
        and question.get("market") in ("global", "both", None)
        and not _contains_han(question.get("text"))
        and str(question.get("text") or "").strip()
        and not _contains_disallowed_english(question.get("text"))
    ]
    pricing = [
        item for item in facts.get("pricing") or []
        if isinstance(item, dict)
    ]
    question_index = 0
    offer_index = 0

    def project(item):
        nonlocal question_index, offer_index
        if isinstance(item, list):
            return [project(child) for child in item]
        if not isinstance(item, dict):
            return item

        result = {key: project(child) for key, child in item.items()}
        item_types = set(_schema_type_names(result.get("@type")))
        if item_types & {"Organization", "SoftwareApplication", "Product", "Service"}:
            if name and "name" in result and _generated_placeholder(result.get("name")):
                result["name"] = name
            if definition and "description" in result and _generated_placeholder(result.get("description")):
                result["description"] = definition
        if definition and "about" in result and _generated_placeholder(result.get("about")):
            result["about"] = definition
        if "Organization" in item_types and "alternateName" in result:
            current_aliases = result.get("alternateName")
            current_aliases = current_aliases if isinstance(current_aliases, list) else [current_aliases]
            current_aliases = [
                str(alias).strip() for alias in current_aliases
                if str(alias or "").strip() and not _generated_placeholder(alias)
            ]
            result["alternateName"] = list(dict.fromkeys(current_aliases + aliases))
        if "Question" in item_types:
            if question_index < len(questions) and _generated_placeholder(result.get("name")):
                result["name"] = questions[question_index]
            question_index += 1
        if "Offer" in item_types:
            fact = pricing[offer_index] if offer_index < len(pricing) else {}
            for field in ("name", "description"):
                source = fact.get("desc") if field == "description" else fact.get(field)
                source = _safe_display(source, "")
                if source and field in result and _generated_placeholder(result.get(field)):
                    result[field] = source
            currency = _safe_display(fact.get("currency"), "").upper()
            if currency and re.fullmatch(r"[A-Z]{3}", currency) and _generated_placeholder(result.get("priceCurrency")):
                result["priceCurrency"] = currency
            offer_index += 1
        return result

    return project(value)


def _schema_type_names(value):
    values = value if isinstance(value, list) else [value]
    names = []
    for item in values:
        item = str(item or "").strip()
        if not item:
            continue
        name = item.rstrip("/").rsplit("/", 1)[-1].rsplit("#", 1)[-1]
        if name and name not in names:
            names.append(name)
    return names


def _root_schema_types(value):
    if not isinstance(value, dict):
        return []
    types = _schema_type_names(value.get("@type"))
    graph = value.get("@graph")
    if isinstance(graph, list):
        for item in graph:
            for item_type in _root_schema_types(item):
                if item_type not in types:
                    types.append(item_type)
    return types


def _all_schema_types(value):
    types = []
    if isinstance(value, dict):
        for item_type in _schema_type_names(value.get("@type")):
            if item_type not in types:
                types.append(item_type)
        for item in value.values():
            for item_type in _all_schema_types(item):
                if item_type not in types:
                    types.append(item_type)
    elif isinstance(value, list):
        for item in value:
            for item_type in _all_schema_types(item):
                if item_type not in types:
                    types.append(item_type)
    return types


def _page_schema_types(page):
    types = []
    for item_type in page.get("jsonld_types") or []:
        for name in _schema_type_names(item_type):
            if name not in types:
                types.append(name)
    for item_type in _all_schema_types(page.get("jsonld_raw") or []):
        if item_type not in types:
            types.append(item_type)
    return types


def _page_lookup(pages):
    lookup = {}
    for page in pages:
        aliases = page.get("duplicate_urls") or []
        if not isinstance(aliases, list):
            aliases = [aliases]
        urls = [page.get("url"), page.get("final_url"), *aliases]
        for value in urls:
            normalized = global_scope.normalize_evidence_url(value)
            if normalized:
                lookup[normalized] = page
    return lookup


def _claim_has_page_evidence(claim, pages):
    lookup = _page_lookup(pages)
    for evidence in claim.get("evidence") or []:
        if isinstance(evidence, str):
            url = evidence
            quote = ""
        elif isinstance(evidence, dict):
            url = evidence.get("url")
            quote = str(evidence.get("quote") or evidence.get("excerpt") or "").strip()
        else:
            continue
        page = lookup.get(global_scope.normalize_evidence_url(url))
        if not page:
            continue
        if quote:
            surface = " ".join(str(page.get("text") or "").split()).casefold()
            if " ".join(quote.split()).casefold() not in surface:
                continue
        return True
    return False


def _schema_claims(container, pages, source):
    if not isinstance(container, dict):
        return []
    raw_claims = container.get("schema_types") or []
    if isinstance(raw_claims, (str, dict)):
        raw_claims = [raw_claims]
    container_confirmed = container.get("schema_types_confirmed") is True or container.get("confirmed") is True
    claims = []
    for raw in raw_claims if isinstance(raw_claims, list) else []:
        if isinstance(raw, str):
            item_type = raw
            confirmed = container_confirmed
            inferred = False
        elif isinstance(raw, dict):
            item_type = raw.get("type") or raw.get("schema_type") or raw.get("@type")
            confirmed = raw.get("confirmed") is True or container_confirmed
            confidence = raw.get("confidence")
            inferred = confidence == "high" or (
                isinstance(confidence, (int, float)) and confidence >= 0.85
            )
            inferred = inferred and _claim_has_page_evidence(raw, pages)
        else:
            continue
        for name in _schema_type_names(item_type):
            if confirmed:
                claims.append({
                    "type": name,
                    "source": source,
                    "detail": "Confirmed in project configuration",
                    "requires_review": False,
                })
            elif inferred:
                claims.append({
                    "type": name,
                    "source": source,
                    "detail": "High-confidence claim with matching crawl evidence",
                    "requires_review": True,
                })
    return claims


def _schema_evidence(project_directory, config):
    pages = geolib.read_jsonl(project_directory / "evidence" / "pages.jsonl")
    evidence = {}

    def add(item_type, item):
        rows = evidence.setdefault(item_type, [])
        if item not in rows:
            rows.append(item)

    for page in pages:
        if not isinstance(page, dict):
            continue
        for item_type in _page_schema_types(page):
            add(item_type, {
                "source": "website_jsonld",
                "detail": str(page.get("url") or "Crawled website"),
                "requires_review": False,
            })

    brand = config.get("brand") if isinstance(config.get("brand"), dict) else {}
    profile_config = config.get("business_profile") if isinstance(config.get("business_profile"), dict) else {}
    for claim in (
        _schema_claims(config, pages, "project_config"),
        _schema_claims(brand, pages, "brand_config"),
        _schema_claims(profile_config, pages, "business_profile"),
    ):
        for item in claim:
            add(item["type"], {key: value for key, value in item.items() if key != "type"})

    for item_type, groups in EXPLICIT_SCHEMA_FIELD_GROUPS.items():
        if all(any(brand.get(field) not in (None, "", []) for field in group) for group in groups):
            add(item_type, {
                "source": "brand_config",
                "detail": "Required type-specific metadata is configured",
                "requires_review": False,
            })

    profile = global_scope.infer_business_profile(config, pages=pages)
    if profile.get("confidence") == "high" and profile.get("evidence_details"):
        for item_type in PROFILE_SCHEMA_TYPES.get(profile.get("id"), ()):
            add(item_type, {
                "source": "business_profile",
                "detail": f"{profile.get('label')} profile supported by crawled website evidence",
                "requires_review": not profile.get("confirmed", False),
            })
    return evidence


def _schema_asset_decision(relative, value, evidence):
    item_types = _root_schema_types(value)
    specialized = [item_type for item_type in item_types if item_type not in GENERIC_SCHEMA_TYPES]
    unsupported = [item_type for item_type in specialized if not evidence.get(item_type)]
    if unsupported:
        return {
            "path": relative,
            "status": "omitted",
            "types": item_types,
            "reason": "No project evidence supports specialized Schema.org type(s): " + ", ".join(unsupported),
            "evidence": [],
            "requires_review": False,
        }
    supporting = [item for item_type in specialized for item in evidence.get(item_type, [])]
    requires_review = any(
        all(item.get("requires_review") for item in evidence[item_type])
        for item_type in specialized
    )
    return {
        "path": relative,
        "status": "included",
        "types": item_types,
        "reason": "Generic type" if not specialized else "Specialized type supported by project evidence",
        "evidence": supporting,
        "requires_review": requires_review,
    }


def _write_jsonld_assets(source, destination, made, config, decisions, facts=None, strict=True):
    jsonld = source / "jsonld"
    if not jsonld.exists():
        return
    evidence = _schema_evidence(source.parent, config)
    for path in sorted(jsonld.glob("*.json")):
        if _contains_han(path.name):
            if strict:
                raise GeoEngineError(f"delivery source cannot be represented in English: assets/jsonld/{path.name}")
            decisions.append({
                "path": f"jsonld/{path.name}", "status": "omitted", "types": [],
                "reason": "Asset filename violates the English workspace contract",
                "evidence": [], "requires_review": False,
            })
            continue
        try:
            value = json.loads(path.read_text("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            if strict:
                raise GeoEngineError(f"invalid delivery JSON asset: assets/jsonld/{path.name}") from exc
            decisions.append({
                "path": f"jsonld/{path.name}", "status": "omitted", "types": [],
                "reason": "Invalid JSON asset",
                "evidence": [], "requires_review": False,
            })
            continue
        value = _project_json_asset(value, config, facts=facts)
        if _json_language_violation(value):
            if strict:
                raise GeoEngineError(f"delivery source cannot be represented in English: assets/jsonld/{path.name}")
            decisions.append({
                "path": f"jsonld/{path.name}", "status": "omitted", "types": [],
                "reason": "Asset content violates the English workspace contract",
                "evidence": [], "requires_review": False,
            })
            continue
        relative = f"jsonld/{path.name}"
        decision = _schema_asset_decision(relative, value, evidence)
        decisions.append(decision)
        if decision["status"] == "omitted":
            continue
        target = destination / "jsonld" / path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", "utf-8")
        made.append(target.relative_to(destination.parent).as_posix())


def _facts_delivery_data(project_slug, project_directory, config):
    path = project_directory / "content" / "facts.md"
    if not path.is_file():
        return {}, ""
    text = path.read_text("utf-8")
    if _contains_han(text):
        return {}, ""
    facts, text = brand_facts.load_facts(project_slug)
    return facts, text


def _write_facts_asset(destination, facts, facts_text, made):
    if not facts_text:
        return
    approved = bool(facts.get("approved") or facts.get("reviewed"))
    machine_only = approved and not facts.get("reviewed")
    relative = Path("facts/brand-facts.md") if approved else Path("drafts/brand-facts.md")
    target = destination / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    text = brand_facts.normalize_price_rows(brand_facts.display_text(facts_text))
    if approved:
        prefix = (
            "Machine-verified from official website evidence originally collected on "
            if machine_only else
            "Reviewed from official website evidence originally collected on "
        )
        text = text.replace("Generated from official website evidence on ", prefix).replace(
            " Every material claim requires human review.",
            " Publication-bound claims were matched to official-site crawl evidence." if machine_only else "",
        ).replace("## Officially stated facts requiring review", "## Verified facts")
    else:
        text = text.replace("## Verified facts", "## Officially stated facts requiring review")
    target.write_text(text, "utf-8")
    made.append(target.relative_to(destination.parent).as_posix())


def _write_llms_asset(project_slug, source, destination, config, audit, facts, made):
    path = source / "llms.en.txt"
    text = path.read_text("utf-8") if path.is_file() else ""
    text = text.replace(
        "（待补：一句话定义，必须与官网首屏和 JSON-LD description 逐字一致）",
        "[Add the one-sentence definition used verbatim in the homepage hero and JSON-LD description.]",
    )
    needs_rebuild = not text or _contains_disallowed_english(text) or bool(PLACEHOLDER_PATTERN.search(text))
    if not needs_rebuild:
        destination.mkdir(parents=True, exist_ok=True)
        relative = (
            Path("drafts/llms.en.txt")
            if "Draft generated from the Brand Fact Library; factual review is required before deployment." in text
            else Path("llms.en.txt")
        )
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, "utf-8")
        made.append(target.relative_to(destination.parent).as_posix())
        return

    brand = config.get("brand") if isinstance(config.get("brand"), dict) else {}
    name = _safe_display(facts.get("name") or brand.get("name"), project_slug)
    site = _safe_display(
        facts.get("site") or brand.get("site"),
        (audit.get("site") or {}).get("root") or "Website not configured",
    )
    definition = _safe_display(facts.get("definition"), "")
    industry = _safe_display(facts.get("industry") or brand.get("industry"), "")
    audience = _safe_display(facts.get("target_users") or brand.get("target_users"), "")
    products = [
        _safe_display(item, "") for item in (facts.get("products") or brand.get("products") or [])
        if _safe_display(item, "")
    ]
    aliases = [
        str(alias).strip() for alias in brand.get("aliases") or []
        if str(alias).strip() and not _contains_disallowed_english(alias)
    ]
    pages = []
    for page in audit.get("pages") or []:
        url = str(page.get("url") or "").strip()
        title = str(page.get("title") or "").strip()
        if url and not _contains_disallowed_english(url):
            pages.append((title if title and not _contains_disallowed_english(title) else "Official page", url))

    complete = bool(definition and industry and audience and products and not PLACEHOLDER_PATTERN.search(definition))
    lines = [f"# {name}", ""]
    if complete:
        lines += [f"> {definition}", "", "## Key facts", "", f"- Website: {site}"]
        if aliases:
            lines.append(f"- Also known as: {', '.join(dict.fromkeys(aliases))}")
        lines += [f"- Industry: {industry}", f"- Audience: {audience}", "", "## Products and services", ""]
        lines += [f"- {item}" for item in products]
    else:
        lines += [
            "> [Add the approved one-sentence English brand definition used verbatim on the website and in JSON-LD.]",
            "", "## Key facts", "", f"- Website: {site}",
            "- Industry: [Add the approved English industry category.]",
            "- Audience: [Add the approved English target-audience statement.]",
        ]
    lines += ["", "## Important pages", ""]
    lines += [f"- [{title}]({url})" for title, url in pages[:12]] or [f"- [Official website]({site})"]
    lines += ["", "## Scope", ""]
    if complete:
        lines += [f"- {item}" for item in products]
        lines += [f"- Good fit: {item}" for item in facts.get("suitable") or []]
        fact_label = "Verified fact" if facts.get("approved") or facts.get("reviewed") else "Officially stated fact requiring review"
        lines += [f"- {fact_label}: {item['fact']} - {item['value']}" for item in facts.get("numbers") or []]
        if not (facts.get("approved") or facts.get("reviewed")):
            lines += ["", "<!-- Draft generated from the Brand Fact Library; factual review is required before deployment. -->"]
    else:
        lines += [
            "- [Add verified English product, pricing, use-case, and limitation statements.]",
            "", "<!-- Review and replace every bracketed placeholder before deployment. -->",
        ]
    lines.append("")
    text = "\n".join(lines)
    relative = Path("llms.en.txt") if complete and (facts.get("approved") or facts.get("reviewed")) else Path("drafts/llms.en.txt")
    target = destination / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, "utf-8")
    made.append(target.relative_to(destination.parent).as_posix())


def _write_snippet_assets(source, destination, config, project_slug, made, facts=None):
    snippets = source / "snippets"
    if not snippets.exists():
        return
    facts = facts if isinstance(facts, dict) else {}
    brand = config.get("brand") if isinstance(config.get("brand"), dict) else {}
    name = _safe_display(facts.get("name") or brand.get("name"), project_slug)
    definition = _safe_display(facts.get("definition"), "")
    definition = definition or "[Add the approved one-sentence definition.]"
    verified_facts = [
        (_safe_display(item.get("fact"), ""), _safe_display(item.get("value"), ""))
        for item in facts.get("numbers") or []
        if isinstance(item, dict)
    ]
    verified_facts = [(fact, value) for fact, value in verified_facts if fact and value]
    target_dir = destination / "snippets"
    if (snippets / "definition.en.html").is_file():
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / "definition.en.html"
        fact_items = "".join(
            f"\n    <li><strong>{html.escape(value)}</strong> - {html.escape(fact)}</li>"
            for fact, value in verified_facts[:4]
        )
        fact_list = f"\n  <ul>{fact_items}\n  </ul>" if fact_items else ""
        target.write_text(
            '<!-- Place this static definition block below the primary page heading. -->\n'
            '<section class="geo-definition">\n'
            f"  <h2>{html.escape(name)}: what it is</h2>\n"
            f"  <p>{html.escape(definition)}</p>"
            + fact_list
            + "\n"
            "</section>\n",
            "utf-8",
        )
        made.append(target.relative_to(destination.parent).as_posix())
    if (snippets / "faq.en.html").is_file():
        questions = []
        for question in config.get("questions") or []:
            text = str(question.get("text") or "").strip()
            if text and not _contains_disallowed_english(text) and question.get("market") in ("global", "both", None):
                questions.append(text)
        body = "\n".join(
            "  <details open>\n"
            f"    <summary><h3>{html.escape(question)}</h3></summary>\n"
            "    <p>[Add a direct answer followed by supporting evidence.]</p>\n"
            "  </details>"
            for question in questions[:8]
        )
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / "faq.en.html"
        target.write_text(
            '<!-- Keep FAQ answers visible in static HTML for crawler access. -->\n'
            '<section class="geo-faq">\n  <h2>Frequently Asked Questions</h2>\n'
            + body
            + "\n</section>\n",
            "utf-8",
        )
        made.append(target.relative_to(destination.parent).as_posix())


def _write_outline_assets(source, destination, blueprint, made):
    if not (source / "outlines").exists():
        return
    rows = []
    target_dir = destination / "outlines"
    content_by_id = {
        str(content.get("id")): content
        for content in blueprint.get("contents") or []
        if content.get("id")
    }
    for content_id, content in sorted(content_by_id.items()):
        question = _delivery_question(content, content_id)
        group = _content_intent(content, question)
        form = _content_form(group, question)
        target_dir.mkdir(parents=True, exist_ok=True)
        structures = {
            "Recommendation": (
                ["Direct recommendation by user profile", "Who this is and is not for", "Evaluation criteria and weights", "Evidence-backed shortlist table", "Trade-offs and final selection guidance"],
                "A scored decision matrix with consistent criteria",
                "Independent category evidence, current product capabilities, pricing, and explicit exclusions",
            ),
            "Comparison": (
                ["Decision summary", "Like-for-like scope and assumptions", "Criterion-by-criterion comparison", "Trade-off table", "Migration and switching considerations", "Verdict by user profile"],
                "A side-by-side table using identical definitions and measurement dates",
                "Primary documentation and dated evidence for every compared product",
            ),
            "Alternatives": (
                ["Why buyers seek an alternative", "Non-negotiable requirements", "Alternative shortlist", "Capability and cost comparison", "Switching risks", "Best fit by scenario"],
                "A shortlist table that states exclusion criteria",
                "Verified limitations of the incumbent and primary evidence for each alternative",
            ),
            "Pricing": (
                ["Current pricing summary", "Plan and entitlement table", "Usage assumptions", "Worked cost scenarios", "Overages and contract caveats", "Buyer checklist"],
                "A dated pricing table plus low, expected, and high usage scenarios",
                "Official pricing and contract sources with currency, tax, billing period, and verification date",
            ),
            "Risk": (
                ["Risk statement and affected users", "Threat or failure scenarios", "Controls and evidence", "Residual risk", "Deployment checklist", "Incident and escalation boundaries"],
                "A risk-control-evidence matrix",
                "Security documentation, certifications, architecture evidence, and clearly marked unknowns",
            ),
            "Use case": (
                ["Outcome and prerequisites", "Starting state", "Step-by-step workflow", "Expected outputs", "Troubleshooting", "Verification checklist", "Next-step variations"],
                "A reproducible procedure with inputs, outputs, and acceptance checks",
                "Product documentation, tested steps, version information, and observable results",
            ),
            "Brand verification": (
                ["One-sentence entity definition", "Legal identity and aliases", "Products and audience", "Claim-evidence-source table", "Unknown or unsupported claims", "Official and independent sources with last verification"],
                "A fact-evidence-source table with confidence grades",
                "Approved facts library, official pages, legal identity, and independent reliable sources where available",
            ),
        }
        sections, decision_aid, evidence = structures.get(group, structures["Recommendation"])
        if group == "Risk" and _is_financial_question(question):
            sections = [
                "Direct safety answer with jurisdiction and scope",
                "Legal entity and service-provider responsibilities",
                "Regulatory authorization and register evidence",
                "Safeguarding, insurance, and insolvency distinctions",
                "Operational risks, complaints, and user protections",
                "Unknowns and verification checklist",
            ]
            decision_aid = "A claim-regulator-provider-evidence matrix"
            evidence = "Official regulator registers, legal terms, safeguarding disclosures, provider records, and independent operational evidence"
        elif group == "Pricing" and _is_financial_question(question):
            sections = [
                "Direct fee summary with currency and verification date",
                "Transfer, exchange-rate, card, ATM, and withdrawal fee components",
                "Limits, tiers, eligibility, and geographic availability",
                "Worked low, expected, and high-cost scenarios",
                "Third-party charges and exchange-rate assumptions",
                "Unknowns, exclusions, and buyer checklist",
            ]
            decision_aid = "A dated fee-and-limit table plus worked transaction scenarios"
            evidence = "Official fee schedules and terms with currency, jurisdiction, billing period, limits, and verification date"
        markdown_lines = [
            f"# Content Outline - {question}",
            "",
            f"- Question ID: `{content_id}`",
            "- Market: Global",
            f"- Intent: {group}",
            f"- Recommended format: {form}",
            f"- Editorial angle: Answer '{question}' for a reader making a {group.lower()} decision.",
            "",
            "## Required Structure",
            "",
        ]
        markdown_lines += [f"{index}. {section}" for index, section in enumerate(sections, 1)]
        markdown_lines += [
            "",
            "## Required Evidence",
            "",
            f"- {evidence}.",
            "- Cite a source and verification date for every material claim.",
            f"- Include {decision_aid.lower()}.",
            "- Identify missing brand facts in the approved facts library before drafting.",
            "",
            "## Publication Guardrails",
            "",
            "- Never invent customer, pricing, security, performance, or competitor claims.",
            "- Label assumptions and unknowns; do not convert them into factual statements.",
            "- Use only the length and heading depth needed to answer this question completely.",
            "- Add limitations, decision boundaries, source links, and a verification date.",
            "",
        ]
        markdown = "\n".join(markdown_lines)
        target = target_dir / f"{content_id}.md"
        target.write_text(markdown, "utf-8")
        made.append(target.relative_to(destination.parent).as_posix())
        rows.append({
            "question_id": content_id,
            "market": content.get("market"),
            "target_question": question,
            "form": form,
        })
    if rows:
        target = target_dir / "index.json"
        target.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", "utf-8")
        made.append(target.relative_to(destination.parent).as_posix())


def render_english_generated_assets(
    project_slug,
    project_directory,
    source,
    destination,
    config,
    audit,
    blueprint,
    *,
    strict=True,
    only_existing=False,
):
    """Render the engine-managed asset families through one English project contract."""
    source = Path(source)
    destination = Path(destination)
    made = []
    decisions = []
    facts, _facts_text = _facts_delivery_data(project_slug, Path(project_directory), config)
    asset_config = {
        **config,
        "brand": {
            **(config.get("brand") if isinstance(config.get("brand"), dict) else {}),
        },
    }
    for field in ("name", "site", "industry", "target_users", "business_goal", "products"):
        if facts.get(field):
            asset_config["brand"][field] = facts[field]
    if not only_existing or (source / "llms.en.txt").is_file() or (source / "llms.txt").is_file():
        _write_llms_asset(project_slug, source, destination, asset_config, audit, facts, made)
    _write_jsonld_assets(
        source, destination, made, asset_config, decisions, facts=facts, strict=strict,
    )
    _write_snippet_assets(source, destination, asset_config, project_slug, made, facts=facts)
    _write_outline_assets(source, destination, blueprint, made)
    return {"paths": made, "schema_decisions": decisions, "facts": facts}


def normalize_generated_draft_text(text):
    return re.sub(
        r"\A<!--\s*初稿，需人工核实所有事实后再发布\s*[·・]\s*\d{4}-\d{2}-\d{2}\s*-->\s*",
        "<!-- Draft: verify every factual claim before publication. -->\n\n",
        str(text or ""),
    )


def _copy_drafts(source, destination, blueprint, made):
    drafts = source / "drafts"
    if not drafts.exists():
        return
    markets = {
        str(content.get("id")): content.get("market")
        for content in blueprint.get("contents") or []
        if content.get("id")
    }
    for path in sorted(drafts.glob("*.md")):
        if markets.get(path.stem) == "cn":
            continue
        text = path.read_text("utf-8")
        text = normalize_generated_draft_text(text)
        if _contains_han(path.name) or _contains_han(text):
            raise GeoEngineError(f"delivery source cannot be represented in English: assets/drafts/{path.name}")
        target = destination / "drafts" / path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, "utf-8")
        made.append(target.relative_to(destination.parent).as_posix())


def _copy_other_assets(source, destination, blueprint, made):
    content_ids = {
        str(content.get("id"))
        for content in blueprint.get("contents") or []
        if content.get("id")
    }
    handled = {
        ".citeaura-manual-edits.json",
        "index.json",
        "llms.txt",
        "llms.en.txt",
        "outlines/_index.json",
        "outlines/index.json",
        "drafts/_lint.json",
        "snippets/definition.en.html",
        "snippets/definition.zh.html",
        "snippets/faq.en.html",
        "snippets/faq.zh.html",
    }
    for path in sorted(source.rglob("*")) if source.exists() else []:
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(source).as_posix()
        if relative in handled:
            continue
        if relative.startswith("jsonld/") and path.suffix.lower() == ".json":
            continue
        if relative.startswith("drafts/") and path.suffix.lower() == ".md":
            continue
        if relative.startswith("outlines/") and path.suffix.lower() == ".md":
            continue
        if _contains_han(relative):
            raise GeoEngineError(f"delivery source cannot be represented in English: assets/{relative}")
        try:
            text = path.read_text("utf-8")
        except UnicodeDecodeError:
            text = None
        if text is not None and _contains_han(text):
            raise GeoEngineError(f"delivery source cannot be represented in English: assets/{relative}")
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        made.append(target.relative_to(destination.parent).as_posix())

__all__ = tuple(name for name in globals() if not name.startswith("__"))
