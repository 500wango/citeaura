"""Build and enforce the English-only SaaS delivery contract."""

import csv
import html
import io
import json
import re
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from api.adapters.branding import apply_delivery_branding
from api.adapters.engine import geolib
from api.adapters.exceptions import GeoEngineError
from api.adapters.localization import localize_ticket, normalize_english_typography
from api.adapters import brand_identity, global_scope, measurement


REQUIRED_DOCUMENTS = {
    "01": "Audit-Report",
    "02": "Execution-Plan",
    "03": "Ticket-Log",
    "04": "Acceptance-Checklist",
    "05": "Draft-Risks",
    "06": "Build-Map",
}

HAN_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U0002fa1f]")
CJK_TYPOGRAPHY_PATTERN = re.compile(
    r"[\u3000-\u303f\ufe10-\ufe1f\ufe30-\ufe4f\uff01-\uff65\uffe0-\uffe6]"
)
UNICODE_ESCAPE_PATTERN = re.compile(r"\\u([0-9a-fA-F]{4})")
TEXT_SUFFIXES = frozenset((".md", ".html", ".csv", ".json", ".txt", ".xml", ".js", ".css"))
PLACEHOLDER_PATTERN = re.compile(
    r"(?i)(\[\s*add\b|<\s*add\b|<\s*(?:section|path|column|value|url)\s*>|\b(?:todo|tbd)\b|replace every bracketed placeholder|configured global target question)"
)

MARKET_NAMES = {
    "global": "Global",
    "both": "Global",
}
STATUS_NAMES = {
    "todo": "Todo",
    "doing": "In Progress",
    "done": "Done",
    "blocked": "Blocked",
    "wontfix": "Won't Fix",
}
EFFORT_NAMES = {
    "S": "Up to 0.5 person-day",
    "M": "1-3 person-days",
    "L": "At least 5 person-days",
}
BLOCK_NAMES = {
    "定义": "Definition",
    "数字事实": "Numeric facts",
    "对比": "Comparison",
    "操作步骤": "Step-by-step guidance",
    "FAQ": "FAQ",
    "definition": "Definition",
    "numeric_facts": "Numeric facts",
    "comparison": "Comparison",
    "steps": "Step-by-step guidance",
    "faq": "FAQ",
}
ISSUE_NAMES = {
    "NON_200_STATUS": "Non-200 response",
    "PAGE_UNREACHABLE": "Page unreachable",
    "NOINDEX": "Page excluded by noindex",
    "NO_CANONICAL": "Missing canonical URL",
    "LOW_CONTENT_PAGE": "Low-content functional page",
    "SPA_SHELL": "Client-rendered empty shell",
    "SHORT_CONTENT": "Insufficient content depth",
    "BAD_H1": "Invalid H1 structure",
    "FEW_H2": "Insufficient section structure",
    "LOW_LIST_DENSITY": "Low list density",
    "NO_DEFINITION": "Missing definition block",
    "NO_NUMBERS": "Missing numeric facts",
    "NO_COMPARISON": "Missing comparison block",
    "NO_HOWTO": "Missing step-by-step block",
    "NO_FAQ": "Missing FAQ block",
    "NO_DATE": "Missing publication or update date",
    "FEW_EXTERNAL_LINKS": "Weak external evidence chain",
    "NO_JSONLD": "Missing JSON-LD",
    "LOW_RELEVANCE": "Low target-query relevance",
}
CHANNEL_NAMES = {
    "official_en": "English Official Site",
    "wikipedia": "Wikipedia",
    "review": "G2, Capterra, and Product Hunt",
    "reddit": "Reddit and Hacker News",
    "youtube": "YouTube",
    "devsite": "GitHub, Documentation Sites, and dev.to",
    "media_en": "English Industry Media",
    "linkedin": "LinkedIn",
}
GROUP_NAMES = {
    "推荐": "Recommendation",
    "比较": "Comparison",
    "替代": "Alternatives",
    "价格": "Pricing",
    "风险": "Risk",
    "品牌验证": "Brand verification",
    "场景": "Use case",
    "recommendation": "Recommendation",
    "comparison": "Comparison",
    "alternative": "Alternatives",
    "pricing": "Pricing",
    "risk": "Risk",
    "brand_verification": "Brand verification",
    "scenario": "Use case",
}
VERDICT_NAMES = {
    "通过": "Passed",
    "pass": "Passed",
    "未达标": "Unmet",
    "fail": "Unmet",
    "待人工": "Manual Review",
    "manual": "Manual Review",
}
RISK_LEVELS = {
    "高": "High",
    "中": "Medium",
    "低": "Low",
    "high": "High",
    "medium": "Medium",
    "low": "Low",
}

MANUAL_TICKET_COPY = {
    "统一一句话定义，四处逐字一致": {
        "title": "Standardize the one-sentence definition across four surfaces",
        "rationale": "Inconsistent brand messaging causes model descriptions to drift.",
        "action": "Use one verbatim definition in the homepage hero, About page, JSON-LD description, and llms.txt.",
        "acceptance": "The definition is identical across all four surfaces after manual review.",
    },
    "建品牌事实卡并标注证据等级": {
        "title": "Build a brand facts library with evidence grades",
        "rationale": "All brand claims need a single, evidence-backed source of truth.",
        "action": "Document entities, aliases, products, key figures, scope, prohibited claims, and evidence grades in facts.md.",
        "acceptance": "facts.md exists and every claim has an evidence grade.",
    },
    "百科词条（实体消歧地基）": {
        "title": "Assess independent-source notability before any encyclopedia work",
        "rationale": "Encyclopedia publication is appropriate only when independent, reliable sources establish notability.",
        "action": "Document qualifying independent sources first. If the threshold is not met, strengthen the owned facts library and verified third-party profiles instead.",
        "acceptance": "The evidence review records at least three substantial independent reliable sources, or documents the safer non-encyclopedia alternative.",
    },
}

JSON_ASSET_REPLACEMENTS = {
    "<填：百科页>": "<add encyclopedia URL>",
    "<填：公众号/社媒主页>": "<add social profile URL>",
    "<填：母品牌站>": "<add parent brand URL>",
    "<填：第一句就是结论，再展开>": "<add a direct answer followed by supporting detail>",
    "<填：含目标问题原词的标题>": "<add a headline containing the target query>",
    "<填 CNY/HKD/USD>": "<add an ISO 4217 currency code>",
    "<填>": "<add value>",
    "首页": "Home",
    "<栏目>": "<section>",
    "美元": "USD",
    "人民币": "CNY",
    "港币": "HKD",
}

GENERIC_SCHEMA_TYPES = frozenset((
    "Thing", "Organization", "WebSite", "WebPage", "AboutPage", "ContactPage",
    "CollectionPage", "ProfilePage", "Article", "BlogPosting", "NewsArticle",
    "FAQPage", "BreadcrumbList", "ItemList",
))
PROFILE_SCHEMA_TYPES = {
    "software": frozenset(("SoftwareApplication",)),
}
EXPLICIT_SCHEMA_FIELD_GROUPS = {
    "SoftwareApplication": (
        ("application_category",),
        ("operating_system", "software_version", "download_url"),
    ),
    "Product": (("sku", "mpn", "gtin", "gtin8", "gtin12", "gtin13", "gtin14"),),
    "Service": (("service_type",),),
}


def _decoded_text(value):
    text = str(value or "")
    for _ in range(3):
        decoded = html.unescape(text)
        if decoded == text:
            break
        text = decoded
    text = UNICODE_ESCAPE_PATTERN.sub(lambda match: chr(int(match.group(1), 16)), text)
    return text


def _contains_han(value):
    return bool(HAN_PATTERN.search(_decoded_text(value)))


def _contains_disallowed_english(value):
    text = _decoded_text(value)
    return bool(HAN_PATTERN.search(text) or CJK_TYPOGRAPHY_PATTERN.search(text))


def _json_language_violation(value):
    if isinstance(value, dict):
        return any(
            _contains_disallowed_english(key) or _json_language_violation(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_json_language_violation(item) for item in value)
    return isinstance(value, str) and _contains_disallowed_english(value)


def delivery_language_violations(delivery_directory):
    """Return paths containing Han text or unnormalized CJK/fullwidth typography."""
    directory = Path(delivery_directory)
    violations = set()
    for path in sorted(directory.rglob("*")):
        relative = path.relative_to(directory)
        if any(_contains_disallowed_english(part) for part in relative.parts):
            violations.add(relative.as_posix())
        if not path.is_file():
            continue
        try:
            text = path.read_text("utf-8")
        except UnicodeDecodeError:
            if path.suffix.lower() in TEXT_SUFFIXES:
                violations.add(relative.as_posix())
            continue
        if _contains_disallowed_english(text):
            violations.add(relative.as_posix())
            continue
        if path.suffix.lower() == ".json":
            try:
                value = json.loads(text)
            except json.JSONDecodeError:
                violations.add(relative.as_posix())
                continue
            if _json_language_violation(value):
                violations.add(relative.as_posix())
    return sorted(violations)


def validate_delivery_language(delivery_directory):
    """Reject a package if any path or decoded text violates the English contract."""
    violations = delivery_language_violations(delivery_directory)
    if violations:
        raise GeoEngineError("delivery contains non-English content: " + ", ".join(violations))
    return Path(delivery_directory)


def _latest_delivery(project_directory):
    directory = project_directory / "delivery"
    deliveries = sorted(
        item for item in directory.iterdir()
        if item.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", item.name)
    ) if directory.exists() else []
    return deliveries[-1] if deliveries else None


def _read_required(path, label):
    value = geolib.read_json(path, None)
    if not isinstance(value, dict) or not value:
        raise GeoEngineError(f"delivery source is missing or invalid: {label}")
    return value


def _latest_json(directory):
    files = sorted(directory.glob("*.json")) if directory.exists() else []
    return geolib.read_json(files[-1], None) if files else None


def _latest_verification(directory):
    def key(path):
        match = re.match(r"(\d{4}-\d{2}-\d{2})(?:-(\d{6}))?", path.stem)
        return (match.group(1), match.group(2) or "000000") if match else ("", path.stem)

    files = sorted(directory.glob("*.json"), key=key) if directory.exists() else []
    return geolib.read_json(files[-1], None) if files else None


def _safe_display(value, fallback):
    value = normalize_english_typography(str(value or "").strip())
    return (
        value if value and not _contains_disallowed_english(value)
        else normalize_english_typography(str(fallback or ""))
    )


def _markdown_cell(value):
    return str(value or "").replace("|", "\\|").replace("\r", " ").replace("\n", " ").strip()


def _format_number(value):
    if isinstance(value, float):
        return f"{value:.1f}".rstrip("0").rstrip(".")
    return str(value if value is not None else "Not measured")


def _format_rate(value):
    return "Not measured" if value is None else f"{float(value):.1%}"


def _window_name(value, priority):
    value = normalize_english_typography(str(value or "").strip())
    if match := re.fullmatch(r"(\d+)\s*天", value):
        return f"{match.group(1)} days"
    if match := re.fullmatch(r"(\d+)d", value, re.IGNORECASE):
        return f"{match.group(1)} days"
    if value and not _contains_disallowed_english(value):
        return value
    return {"P0": "30 days", "P1": "60 days", "P2": "90 days"}.get(priority, "90 days")


def _check_copy(check):
    if check == "site.no_ai_bot_block":
        return (
            "Unblock AI crawlers in robots.txt",
            "Blocked crawlers cannot retrieve or index site content.",
            "Remove sitewide AI crawler blocks while retaining restrictions for private routes.",
            "No AI crawler is blocked sitewide on re-crawl.",
        )
    if check == "site.has_sitemap":
        return (
            "Add and submit sitemap.xml",
            "A missing sitemap reduces discovery speed and coverage.",
            "Generate sitemap.xml, reference it in robots.txt, and submit it to search engines.",
            "sitemap.xml is retrieved successfully on re-crawl.",
        )
    if check == "site.has_llms_txt":
        return (
            "Publish the official facts index at /llms.txt",
            "A curated facts index gives AI systems a stable official reference.",
            "Generate the llms.txt asset and deploy it at the website root.",
            "/llms.txt is retrieved successfully on re-crawl.",
        )
    if check.startswith("site.en_pages_gte:"):
        target = check.rsplit(":", 1)[-1]
        return (
            "Build native English content pages",
            "Native English pages are required for reliable global retrieval.",
            "Publish native English product, pricing, comparison, FAQ, and case-study pages.",
            f"At least {target} valid English pages are present.",
        )
    if check.startswith("site.lang_balance:"):
        return (
            "Balance domestic and English content coverage",
            "A large language coverage gap limits one target market.",
            "Expand the thinner language section until both markets have comparable page coverage.",
            "The language coverage gap is within the configured threshold.",
        )
    if check == "pages.static_text":
        return (
            "Fix client-rendered empty-shell pages",
            "AI crawlers cannot extract body copy from empty static HTML.",
            "Use server rendering or prerendering so initial HTML includes the full page body.",
            "Affected pages contain at least 120 words in the fetched HTML.",
        )
    if check == "pages.has_jsonld":
        return (
            "Add JSON-LD structured data sitewide",
            "Structured data helps crawlers identify entities and page purpose.",
            "Deploy page-appropriate Schema.org JSON-LD across affected routes.",
            "Affected pages contain valid JSON-LD on re-crawl.",
        )
    if check.startswith("pages.block:"):
        raw = check.split(":", 1)[1]
        block = BLOCK_NAMES.get(raw, "Extraction")
        return (
            f"Add {block.lower()} blocks sitewide",
            f"Missing {block.lower()} blocks reduces answer extractability.",
            f"Add clear, static {block.lower()} blocks to priority pages.",
            f"Pages missing {block.lower()} blocks decrease by at least 50%.",
        )
    if check.startswith("pages.wordcount_gte:"):
        target = check.rsplit(":", 1)[-1]
        return (
            f"Expand priority pages to at least {target} words",
            "Thin pages provide insufficient evidence and context for retrieval.",
            "Expand priority pages with definitions, evidence, comparisons, and implementation guidance.",
            f"Pages below {target} words decrease by at least 40%.",
        )
    if check.startswith("site.avg_score_gte:"):
        target = check.rsplit(":", 1)[-1]
        return (
            f"Raise the average site audit score to {target}",
            "The current audit score indicates broad technical and content gaps.",
            "Resolve the highest-priority page structure, extraction, authority, and freshness issues.",
            f"The next audit reaches an average score of at least {target}.",
        )
    if check.startswith("metrics.mention_rate_gte:"):
        _, market, target = check.split(":")
        return (
            f"Raise {MARKET_NAMES.get(market, market)} unprompted mention rate",
            "Measured brand visibility remains below the target threshold.",
            "Improve the content matrix and supporting third-party evidence, then re-sample.",
            f"Average unprompted mention rate reaches at least {float(target):.0%}.",
        )
    if check.startswith("metrics.own_cite_gte:"):
        _, market, target = check.split(":")
        return (
            f"Increase {MARKET_NAMES.get(market, market)} citations to the official site",
            "AI answers rarely cite the official domain in the measured market.",
            "Improve indexing and publish authoritative third-party content linking to the official site.",
            f"Official-domain citation rate reaches at least {float(target):.0%}.",
        )
    if check.startswith("external.any:"):
        domains = check.split(":", 1)[1]
        return (
            "Establish evidence on priority third-party domains",
            "The measured citation graph lacks evidence from priority external sources.",
            f"Create or update a verifiable presence on one of these domains: {domains}.",
            "A subsequent sample cites at least one target domain.",
        )
    return None


def _require_english(value, field):
    value = normalize_english_typography(str(value or "").strip())
    if _contains_disallowed_english(value):
        raise GeoEngineError(f"delivery source cannot be represented in English: {field}")
    return value


def _ticket_en(ticket):
    localized = localize_ticket(ticket)
    acceptance = localized.get("acceptance") if isinstance(localized.get("acceptance"), dict) else {}
    check = str(acceptance.get("check") or "")
    fallback = _check_copy(check)
    manual = MANUAL_TICKET_COPY.get(str(ticket.get("title") or ""))

    title = localized.get("title_en") or localized.get("title") or localized.get("name") or ticket.get("id")
    rationale = localized.get("why_en") or localized.get("desc_en") or ticket.get("why") or ticket.get("desc")
    action = localized.get("action_en") or ticket.get("action")
    acceptance_text = acceptance.get("desc_en") or acceptance.get("desc")
    if ticket.get("kind") == "offsite":
        url = _require_english(ticket.get("url") or "", f"{ticket.get('id')} offsite URL")
        host = urlparse(url).hostname or "external site"
        ask_text = _require_english(ticket.get("ask_text") or "", f"{ticket.get('id')} outreach request")
        question_count = len(ticket.get("influenced_questions") or [])
        title = f"Update the {host} page with verifiable brand facts"
        rationale = f"This external page influences {question_count} configured target question(s) and needs verifiable first-party evidence."
        action = f"Ask the page owner to make this update: {ask_text}"
        acceptance_text = "Manually verify the external page contains the requested facts and attach the URL or outreach record to the ticket."
    elif manual:
        title = manual["title"]
        rationale = manual["rationale"]
        action = manual["action"]
        acceptance_text = manual["acceptance"]
    elif fallback:
        values = (title, rationale, action, acceptance_text)
        title, rationale, action, acceptance_text = tuple(
            fallback[index] if not value or _contains_han(value) else value
            for index, value in enumerate(values)
        )

    ticket_id = _require_english(ticket.get("id") or "Unnumbered", "ticket id")
    package = localized.get("package_en") or localized.get("category_en") or ticket.get("package") or "General"
    owner = localized.get("owner_en") or localized.get("role_en") or ticket.get("owner") or "Unassigned"
    return {
        "id": ticket_id,
        "priority": _require_english(ticket.get("priority") or "P2", f"{ticket_id} priority"),
        "package": _require_english(package, f"{ticket_id} package"),
        "market": "Global",
        "title": _require_english(title, f"{ticket_id} title"),
        "rationale": _require_english(rationale or "No additional rationale supplied.", f"{ticket_id} rationale"),
        "action": _require_english(action or "Complete the ticket scope and attach evidence.", f"{ticket_id} action"),
        "owner": _require_english(owner, f"{ticket_id} owner"),
        "effort": EFFORT_NAMES.get(ticket.get("effort"), _require_english(ticket.get("effort") or "Not estimated", f"{ticket_id} effort")),
        "window": _window_name(ticket.get("window"), ticket.get("priority")),
        "acceptance": _require_english(acceptance_text or "Attach verifiable completion evidence.", f"{ticket_id} acceptance"),
        "verification_mode": "Automated" if acceptance.get("type") == "auto" else "Manual",
        "status": STATUS_NAMES.get(ticket.get("status"), _require_english(ticket.get("status") or "todo", f"{ticket_id} status")),
        "affected": [
            _require_english(item, f"{ticket_id} affected page")
            for item in (ticket.get("affected") or [])
        ],
    }


def _load_sources(project_directory):
    audit = _read_required(project_directory / "audit.json", "audit.json")
    validated_site = geolib.read_json(project_directory / "evidence" / "site.json", None)
    if isinstance(validated_site, dict) and validated_site:
        audit = {**audit, "site": validated_site}
    tasks = _read_required(project_directory / "tasks.json", "tasks.json")
    blueprint = _read_required(project_directory / "blueprint.json", "blueprint.json")
    if not isinstance(tasks.get("tasks"), list) or not tasks["tasks"]:
        raise GeoEngineError("delivery source is missing or invalid: tasks.json tasks")
    if not isinstance(blueprint.get("coverage"), dict) or not isinstance(blueprint.get("channels"), list):
        raise GeoEngineError("delivery source is missing or invalid: blueprint.json structure")
    config = geolib.read_json(project_directory / "geo.json", {}) or {}
    metrics = _latest_json(project_directory / "metrics")
    verification = _latest_verification(project_directory / "verify")
    lint = geolib.read_json(project_directory / "assets" / "drafts" / "_lint.json", None)
    return config, audit, tasks, blueprint, metrics, verification, lint


def _identity(project_directory, project_slug, config, audit):
    brand = config.get("brand") if isinstance(config.get("brand"), dict) else {}
    site = brand.get("site") or (audit.get("site") or {}).get("root") or ""
    host = urlparse(site).hostname or project_slug
    name = _safe_display(brand.get("name"), host)
    return name, _safe_display(site, host)


def _sample_modes(project_directory, metrics):
    date = str((metrics or {}).get("date") or "")
    config = geolib.read_json(project_directory / "geo.json", {}) or {}
    rows = geolib.read_jsonl(project_directory / "samples" / f"{date}.jsonl") if date else []
    by_platform = {}
    for row in rows:
        if not global_scope.is_global_sample(row) or not brand_identity.is_current_sample(row, config):
            continue
        platform = str(row.get("platform") or "")
        if not platform:
            continue
        if row.get("sample_mode") == "manual" or row.get("terminal") == "web":
            mode = "Manual - Product interface"
        elif row.get("search_enabled"):
            mode = "API - Search grounded"
        else:
            mode = "API - Parametric knowledge"
        by_platform.setdefault(platform, set()).add(mode)
    return {
        platform: "Mixed: " + ", ".join(sorted(modes)) if len(modes) > 1 else next(iter(modes))
        for platform, modes in by_platform.items()
    }


def _audit_markdown(project_slug, project_directory, name, site, audit, metrics):
    site_data = audit.get("site") or {}
    coverage = audit.get("language_coverage") or {}
    grades = audit.get("grade_distribution") or {}
    audited_at = str(audit.get("audited_at") or geolib.today())[:10]
    lines = [
        f"# {name} GEO Audit Report",
        "",
        f"- Audit date: {audited_at}",
        f"- Official website: {site}",
        "- Target market: Global",
        f"- Crawled pages: {audit.get('page_count', 0)}",
        f"- Average site score: **{_format_number(audit.get('avg_score'))}**",
        "",
        "## Technical Baseline",
        "",
        "| Check | Result |",
        "|---|---|",
        f"| sitemap.xml | {'Present' if site_data.get('has_sitemap') else 'Missing'} |",
        f"| llms.txt | {'Present' if site_data.get('has_llms_txt') else 'Missing'} |",
        f"| AI crawlers blocked | {', '.join(site_data.get('ai_bots_blocked') or []) or 'None'} |",
        f"| Accessible pages | {site_data.get('pages_ok', 0)}/{site_data.get('pages_crawled', 0)} |",
        f"| English content pages (120+ words) | {coverage.get('en_pages', 0)} |",
        "",
        "## Grade Distribution",
        "",
        "| Grade | Pages |",
        "|---|---:|",
    ]
    lines.extend(f"| {grade} | {grades.get(grade, 0)} |" for grade in "ABCD")
    lines += [
        "",
        "## Priority Pages",
        "",
        "| Score | Words | Grade | Page | Primary Gaps |",
        "|---:|---:|---|---|---|",
    ]
    pages = sorted(audit.get("pages") or [], key=lambda page: page.get("score", 0))[:20]
    for page in pages:
        url = _require_english(page.get("url") or "Unknown URL", "audit page URL")
        codes = page.get("issue_codes") or []
        issues = ", ".join(ISSUE_NAMES.get(str(code), str(code).replace("_", " ").title()) for code in codes[:5]) or "None"
        lines.append(
            f"| {_format_number(page.get('score'))} | {page.get('word_count', 0)} | {page.get('grade', '')} "
            f"| [{_markdown_cell(url)}]({_markdown_cell(url)}) | {_markdown_cell(issues)} |"
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
        lines.append(f"| {block} | {gap.get('missing_pages', 0)}/{gap.get('total', 0)} |")

    quality = measurement.sampling_quality(project_slug)
    confidence = quality.get("confidence") or {}
    lines += [
        "", "## AI Visibility Sampling", "",
        f"**Confidence: {confidence.get('label', 'No baseline')}**", "",
    ]
    for limitation in confidence.get("limitations") or []:
        lines.append(f"- Limitation: {_require_english(limitation, 'sampling limitation')}")
    if not confidence.get("allows_global_conclusions"):
        lines.append("- Do not generalize these observations to global AI visibility or unsampled platforms.")
    lines.append("- Observed changes do not establish optimization attribution; use deployment evidence and repeated comparable periods.")
    lines.append("")
    platforms = (metrics or {}).get("platforms") or {}
    if not platforms:
        lines += ["No AI visibility samples are available for this cycle.", ""]
    else:
        modes = _sample_modes(project_directory, metrics)
        lines += [
            f"Sampling date: {metrics.get('date', 'Not recorded')}",
            "",
            "| Platform | Market | Sampling Mode | Samples | Mention Rate | Top 3 Rate | Official Domain Cited |",
            "|---|---|---|---:|---:|---:|---:|",
        ]
        for code, item in platforms.items():
            code = _require_english(code, "sampling platform code")
            label = _safe_display(item.get("label"), code)
            lines.append(
                f"| {_markdown_cell(label)} | Global "
                f"| {modes.get(code, 'API - Parametric knowledge')} | {item.get('samples', 0)} "
                f"| {_format_rate(item.get('mention_rate'))} | {_format_rate(item.get('top3_rate'))} "
                f"| {_format_rate(item.get('own_domain_cite_rate'))} |"
            )
        lines.append("")
    return "\n".join(lines)


def _execution_markdown(name, tickets, tasks):
    baseline = tasks.get("baseline") or {}
    lines = [
        f"# {name} GEO Execution Plan",
        "",
        "This plan converts the current audit and visibility baseline into assigned, verifiable work.",
        "",
        f"- Baseline site score: {_format_number(baseline.get('avg_score'))}",
        f"- Baseline pages: {_format_number(baseline.get('pages'))}",
        f"- Total tickets: {len(tickets)}",
        "",
    ]
    for priority, heading in (("P0", "0-30 Days: Foundation"), ("P1", "30-60 Days: Visibility Gains"), ("P2", "60-90 Days: Scale")):
        rows = [ticket for ticket in tickets if ticket["priority"] == priority]
        lines += [f"## {heading}", ""]
        if not rows:
            lines += ["No tickets are currently assigned to this phase.", ""]
            continue
        for ticket in rows:
            lines += [
                f"### {ticket['id']} - {ticket['title']}",
                "",
                f"- Owner: {ticket['owner']}",
                f"- Package: {ticket['package']}",
                f"- Target window: {ticket['window']}",
                f"- Rationale: {ticket['rationale']}",
                f"- Action: {ticket['action']}",
                f"- Acceptance: {ticket['acceptance']}",
                "",
            ]
    lines += [
        "## Operating Cadence",
        "",
        "1. Complete P0 blockers before scaling content production.",
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
    lines += ["", "## Ticket Details", ""]
    for ticket in tickets:
        lines += [
            f"### {ticket['id']} - {ticket['title']}",
            "",
            f"- Rationale: {ticket['rationale']}",
            f"- Action: {ticket['action']}",
            f"- Acceptance: {ticket['acceptance']}",
        ]
        if ticket["affected"]:
            lines.append("- Affected pages: " + ", ".join(ticket["affected"][:10]))
        lines.append("")
    return "\n".join(lines)


def _tickets_csv(tickets):
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow([
        "ID", "Priority", "Package", "Market", "Task", "Rationale", "Action", "Owner",
        "Effort", "Window", "Acceptance Criteria", "Verification Mode", "Status", "Affected Pages",
    ])
    for ticket in tickets:
        writer.writerow([
            ticket["id"], ticket["priority"], ticket["package"], ticket["market"], ticket["title"],
            ticket["rationale"], ticket["action"], ticket["owner"], ticket["effort"], ticket["window"],
            ticket["acceptance"], ticket["verification_mode"], ticket["status"], len(ticket["affected"]),
        ])
    return output.getvalue()


def _verification_note(result, verdict):
    progress = result.get("progress") if isinstance(result.get("progress"), dict) else None
    if progress:
        current = _format_rate(progress.get("cur")) if progress.get("pct") else _format_number(progress.get("cur"))
        target = _format_rate(progress.get("target")) if progress.get("pct") else _format_number(progress.get("target"))
        relation = "at least" if progress.get("op") == "gte" else "at most"
        return f"Current value: {current}; target: {relation} {target}."
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

    lines += [
        f"- Verification date: {verify_date or 'Not recorded'}",
        f"- Re-audit average score: {_format_number(verification.get('audit_avg_score'))}",
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


def _risk_markdown(name, lint):
    lines = [f"# {name} AI Draft Risk Report", ""]
    if not isinstance(lint, dict):
        lines += ["No AI drafts were generated for this cycle; no draft risks require review.", ""]
        return "\n".join(lines)
    files = lint.get("files") if isinstance(lint.get("files"), dict) else {}
    lines += [
        f"- Draft files checked: {len(files)}",
        f"- Items requiring review: {lint.get('total_issues', 0)}",
        f"- High-risk items: {lint.get('high', 0)}",
        "",
    ]
    if lint.get("total_issues"):
        lines += [
            "**Do not publish affected drafts until manual verification is complete.**",
            "",
            "| File | Risk Level | Required Action |",
            "|---|---|---|",
        ]
        for filename, issues in files.items():
            filename = _require_english(filename, "draft risk filename")
            for issue in issues if isinstance(issues, list) else []:
                level = RISK_LEVELS.get(issue.get("level"), "Review")
                lines.append(f"| `{_markdown_cell(filename)}` | {level} | Verify claims and attach primary-source evidence before publication. |")
        lines.append("")
    else:
        lines += ["No draft issues were detected by the current lint rules.", ""]
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


def _build_map_markdown(name, blueprint):
    channels = [
        channel for channel in blueprint.get("channels") or []
        if isinstance(channel, dict) and channel.get("market") == "global"
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
        evidence.extend(f"observed citation on {domain}" for domain in channel.get("coverage_evidence") or [])
        if channel.get("national") is not None:
            evidence.append(f"{channel['national']:,} observed citations")
        if channel.get("position") is not None:
            evidence.append(f"average placement #{channel['position']}")
        if channel.get("platforms") is not None:
            evidence.append(f"observed across {channel['platforms']} platforms")
        status = {
            "covered": "Covered",
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
        intent = GROUP_NAMES.get(content.get("group"), _safe_display(content.get("group"), "General"))
        form = _require_english(content.get("form") or "Definition or guide page", f"{content_id} content form")
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


def _write_document(directory, number, markdown, cards):
    name = REQUIRED_DOCUMENTS[number]
    (directory / f"{number}-{name}.md").write_text(markdown, "utf-8")
    import report

    title = markdown.splitlines()[0].removeprefix("# ")
    document = report.build_html(title, markdown, cards)
    (directory / f"{number}-{name}.html").write_text(document, "utf-8")


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


def _write_jsonld_assets(source, destination, made, config, decisions):
    jsonld = source / "jsonld"
    if not jsonld.exists():
        return
    evidence = _schema_evidence(source.parent, config)
    for path in sorted(jsonld.glob("*.json")):
        if _contains_han(path.name):
            raise GeoEngineError(f"delivery source cannot be represented in English: assets/jsonld/{path.name}")
        try:
            value = json.loads(path.read_text("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GeoEngineError(f"invalid delivery JSON asset: assets/jsonld/{path.name}") from exc
        value = _replace_json_asset(value)
        if _json_language_violation(value):
            raise GeoEngineError(f"delivery source cannot be represented in English: assets/jsonld/{path.name}")
        relative = f"jsonld/{path.name}"
        decision = _schema_asset_decision(relative, value, evidence)
        decisions.append(decision)
        if decision["status"] == "omitted":
            continue
        target = destination / "jsonld" / path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", "utf-8")
        made.append(target.relative_to(destination.parent).as_posix())


def _write_llms_asset(project_slug, source, destination, config, audit, made):
    path = source / "llms.en.txt"
    if not path.is_file():
        return
    text = path.read_text("utf-8")
    text = text.replace(
        "（待补：一句话定义，必须与官网首屏和 JSON-LD description 逐字一致）",
        "[Add the one-sentence definition used verbatim in the homepage hero and JSON-LD description.]",
    )
    if _contains_han(text):
        brand = config.get("brand") if isinstance(config.get("brand"), dict) else {}
        name = _safe_display(brand.get("name"), project_slug)
        site = _safe_display(brand.get("site"), (audit.get("site") or {}).get("root") or "Website not configured")
        aliases = [
            str(alias).strip() for alias in brand.get("aliases") or []
            if str(alias).strip() and not _contains_han(alias)
        ]
        pages = []
        for page in audit.get("pages") or []:
            url = str(page.get("url") or "").strip()
            title = str(page.get("title") or "").strip()
            if url and not _contains_han(url):
                pages.append((title if title and not _contains_han(title) else "Official page", url))
        lines = [
            f"# {name}",
            "",
            "> [Add the approved one-sentence English brand definition used verbatim on the website and in JSON-LD.]",
            "",
            "## Key facts",
            "",
            f"- Website: {site}",
        ]
        if aliases:
            lines.append(f"- Also known as: {', '.join(dict.fromkeys(aliases))}")
        lines += [
            "- Industry: [Add the approved English industry category.]",
            "- Audience: [Add the approved English target-audience statement.]",
            "",
            "## Important pages",
            "",
        ]
        lines += [f"- [{title}]({url})" for title, url in pages[:12]] or [f"- [Official website]({site})"]
        lines += [
            "",
            "## Scope",
            "",
            "- [Add verified English product, pricing, use-case, and limitation statements.]",
            "",
            "<!-- Review and replace every bracketed placeholder before deployment. -->",
            "",
        ]
        text = "\n".join(lines)
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / "llms.en.txt"
    target.write_text(text, "utf-8")
    made.append(target.relative_to(destination.parent).as_posix())


def _write_snippet_assets(source, destination, config, project_slug, made):
    snippets = source / "snippets"
    if not snippets.exists():
        return
    brand = config.get("brand") if isinstance(config.get("brand"), dict) else {}
    name = _safe_display(brand.get("name"), project_slug)
    target_dir = destination / "snippets"
    if (snippets / "definition.en.html").is_file():
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / "definition.en.html"
        target.write_text(
            '<!-- Place this static definition block below the primary page heading. -->\n'
            '<section class="geo-definition">\n'
            f"  <h2>{html.escape(name)}: what it is</h2>\n"
            "  <p>[Add the approved one-sentence definition.]</p>\n"
            "</section>\n",
            "utf-8",
        )
        made.append(target.relative_to(destination.parent).as_posix())
    if (snippets / "faq.en.html").is_file():
        questions = []
        for question in config.get("questions") or []:
            text = str(question.get("text") or "").strip()
            if text and not _contains_han(text) and question.get("market") in ("global", "both", None):
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
        form = _require_english(content.get("form") or "Definition or guide page", f"{content_id} content form")
        target_dir.mkdir(parents=True, exist_ok=True)
        group = GROUP_NAMES.get(content.get("group"), _safe_display(content.get("group"), "Recommendation"))
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
                ["One-sentence entity definition", "Official identity and aliases", "Products and audience", "Verified facts table", "What the brand does not claim", "Official sources and last verification"],
                "A fact-evidence-source table with confidence grades",
                "Approved facts library, official pages, legal identity, and independent reliable sources where available",
            ),
        }
        sections, decision_aid, evidence = structures.get(group, structures["Recommendation"])
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
        text = re.sub(
            r"\A<!--\s*初稿，需人工核实所有事实后再发布\s*[·・]\s*\d{4}-\d{2}-\d{2}\s*-->\s*",
            "<!-- Draft: verify every factual claim before publication. -->\n\n",
            text,
        )
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
        "index.json",
        "llms.txt",
        "llms.en.txt",
        "outlines/_index.json",
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
    offers = value.get("offers")
    if offers:
        offers = offers if isinstance(offers, list) else [offers]
        if any(
            not isinstance(offer, dict)
            or offer.get("price") in (None, "")
            or not offer.get("priceCurrency")
            for offer in offers
        ):
            issues.append("Offer is missing price or ISO currency")
    return issues


def _asset_record(destination, delivery_path):
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
    if status == "needs_review":
        issues.append("Draft requires factual and editorial review")
    if status == "template":
        target = destination / "templates" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(path, target)
        relative = target.relative_to(destination)
    return {
        "path": relative.as_posix(),
        "status": status,
        "type": relative.suffix.lower().lstrip(".") or "file",
        "issues": list(dict.fromkeys(issues)),
    }


def _write_assets(project_slug, project_directory, directory, config, audit, blueprint):
    source = project_directory / "assets"
    destination = directory / "assets"
    destination.mkdir(parents=True, exist_ok=True)
    made = []
    schema_decisions = []
    _write_llms_asset(project_slug, source, destination, config, audit, made)
    _write_jsonld_assets(source, destination, made, config, schema_decisions)
    _write_snippet_assets(source, destination, config, project_slug, made)
    _write_outline_assets(source, destination, blueprint, made)
    _copy_drafts(source, destination, blueprint, made)
    _copy_other_assets(source, destination, blueprint, made)
    records = [_asset_record(destination, path) for path in sorted(set(made))]
    decisions_by_path = {item["path"]: item for item in schema_decisions}
    for record in records:
        decision_path = record["path"].removeprefix("templates/")
        decision = decisions_by_path.get(decision_path)
        if not decision or not decision.get("requires_review"):
            continue
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
    readiness_issues = []
    if summary["needs_review"]:
        readiness_issues.append(f"{summary['needs_review']} asset(s) require factual or editorial review")
    if summary["template"]:
        readiness_issues.append(f"{summary['template']} template asset(s) contain incomplete material")
    if not confidence.get("sufficient"):
        readiness_issues.append(f"Sampling confidence is {confidence.get('label', 'unavailable')}")
    index = {
        "generated_at": geolib.now_iso(),
        "language": "English",
        "readiness": "customer_ready" if records and not readiness_issues else "review_required",
        "readiness_issues": readiness_issues,
        "report_confidence": confidence,
        "schema_selection": {
            "policy": "Specialized Schema.org types require project evidence",
            "included": [item for item in schema_decisions if item["status"] == "included"],
            "omitted": [item for item in schema_decisions if item["status"] == "omitted"],
        },
        "summary": summary,
        "assets": records,
    }
    (destination / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", "utf-8")
    return index


def _write_index(directory, name, site, delivery_date, audit, tickets, blueprint, asset_index):
    coverage = blueprint.get("coverage") or {}
    assets = asset_index.get("assets") or []
    asset_summary = asset_index.get("summary") or {}
    schema_selection = asset_index.get("schema_selection") or {}
    documents = [f"{number}-{title}.html" for number, title in REQUIRED_DOCUMENTS.items()]
    lines = [
        f"# {name} GEO Delivery Pack",
        "",
        f"- Official website: {site}",
        f"- Delivery date: {delivery_date}",
        f"- Average site score: {_format_number(audit.get('avg_score'))}",
        f"- Action tickets: {len(tickets)}",
        f"- Channel coverage: {coverage.get('channel_covered', 0)}/{coverage.get('channel_total', 0)}",
    ]
    if coverage.get("channel_manual"):
        lines.append(f"- Channels requiring manual confirmation: {coverage['channel_manual']}")
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
        f"- Templates requiring completion: {asset_summary.get('template', 0)}",
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
            f"- `assets/{item['path']}`" + (f" - {'; '.join(item['issues'])}" if item.get("issues") else "")
            for item in matching
        ] or ["- None"]
        lines.append("")
    lines += [
        "",
        "## Use and Verification",
        "",
        "Review the audit first, execute tickets by priority, attach evidence, then re-run acceptance checks and visibility sampling.",
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
                ("Site Score", _format_number(audit.get("avg_score"))),
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
        "Start with `index.html` for the delivery overview.",
        "",
        "## Package Contents",
        "",
        "- `01-Audit-Report`: current technical, content, and AI visibility baseline.",
        "- `02-Execution-Plan`: prioritized 30/60/90-day implementation sequence.",
        "- `03-Ticket-Log`: assigned work, rationale, actions, and acceptance criteria.",
        "- `04-Acceptance-Checklist`: current automated and manual verification state.",
        "- `05-Draft-Risks`: publication risks requiring human review.",
        "- `06-Build-Map`: channel and target-query content architecture.",
        "- `assets/`: assets grouped as ready, needs review, or template in `assets/index.json`.",
        "",
        "Do not publish drafts or deploy placeholders until the responsible owner has verified every claim and value.",
        "",
    ])
    (directory / "README.md").write_text(readme, "utf-8")


def _build_delivery(project_slug, project_directory, directory, delivery_date):
    config, audit, task_data, blueprint, metrics, verification, lint = _load_sources(project_directory)
    name, site = _identity(project_directory, project_slug, config, audit)
    tickets = [_ticket_en(ticket) for ticket in task_data["tasks"] if isinstance(ticket, dict)]
    if not tickets:
        raise GeoEngineError("delivery source is missing or invalid: no usable tickets")
    tickets.sort(key=lambda ticket: (ticket["priority"], ticket["id"]))

    audit_markdown = _audit_markdown(project_slug, project_directory, name, site, audit, metrics)
    execution_markdown = _execution_markdown(name, tickets, task_data)
    tickets_markdown = _tickets_markdown(name, tickets)
    verification_markdown = _verification_markdown(name, audit, verification, tickets)
    risk_markdown = _risk_markdown(name, lint)
    build_map_markdown = _build_map_markdown(name, blueprint)

    _write_document(directory, "01", audit_markdown, [
        ("Site Score", _format_number(audit.get("avg_score"))),
        ("Crawled Pages", str(audit.get("page_count", 0))),
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
        ("Items to Review", str((lint or {}).get("total_issues", 0))),
        ("High Risk", str((lint or {}).get("high", 0))),
    ])
    coverage = blueprint.get("coverage") or {}
    channel_stats = [
        ("Channel Coverage", f"{coverage.get('channel_covered', 0)}/{coverage.get('channel_total', 0)}"),
        ("Content Complete", f"{coverage.get('content_done', 0)}/{coverage.get('content_total', 0)}"),
    ]
    if coverage.get("channel_manual"):
        channel_stats.append(("Manual Confirmation", str(coverage["channel_manual"])))
    _write_document(directory, "06", build_map_markdown, channel_stats)
    asset_index = _write_assets(project_slug, project_directory, directory, config, audit, blueprint)
    _write_index(directory, name, site, delivery_date, audit, tickets, blueprint, asset_index)
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
        if isinstance(channel, dict) and channel.get("market") == "global"
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


def ensure_delivery_contract(project_slug: str, delivery_directory: Path | None = None):
    """Rebuild a delivery package and fail closed unless every artifact is English-only."""
    global_scope.normalize_project(project_slug)
    project_directory = geolib.project_dir(project_slug)
    delivery_directory = Path(delivery_directory) if delivery_directory else _latest_delivery(project_directory)
    if delivery_directory is None or not delivery_directory.is_dir():
        raise GeoEngineError("delivery directory was not generated")
    target = _delivery_target(project_directory, delivery_directory)
    target.parent.mkdir(parents=True, exist_ok=True)
    with geolib.project_lock(project_slug):
        staging = Path(tempfile.mkdtemp(prefix=".delivery-english-", dir=target.parent))
        try:
            _build_delivery(project_slug, project_directory, staging, target.name)
            if target.exists():
                shutil.rmtree(target)
            staging.rename(target)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            raise
    return target
