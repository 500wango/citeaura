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
from api.adapters.localization import localize_ticket


REQUIRED_DOCUMENTS = {
    "01": "Audit-Report",
    "02": "Execution-Plan",
    "03": "Ticket-Log",
    "04": "Acceptance-Checklist",
    "05": "Draft-Risks",
    "06": "Build-Map",
}

HAN_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U0002fa1f]")
UNICODE_ESCAPE_PATTERN = re.compile(r"\\u([0-9a-fA-F]{4})")
TEXT_SUFFIXES = frozenset((".md", ".html", ".csv", ".json", ".txt", ".xml", ".js", ".css"))

MARKET_NAMES = {
    "cn": "Domestic",
    "global": "Global",
    "both": "Domestic and Global",
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
    "official": "Official Site",
    "official_en": "English Official Site",
    "baike": "Baidu Baike and Sogou Baike",
    "ranking": "Ranking and Directory Platforms",
    "wechat": "WeChat Official Accounts and Tencent News",
    "toutiao": "Toutiao and Douyin Articles",
    "zhihu": "Zhihu",
    "tech": "CSDN, CNBlogs, and Cloud Developer Communities",
    "quark": "Quark and Shenma Search Indexing",
    "baijia": "Baijiahao and Baidu Zhidao",
    "media": "Industry Media and Research Portals",
    "bilibili": "Bilibili and Video Channels",
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
        "title": "Create an encyclopedia entry for entity disambiguation",
        "rationale": "A third-party encyclopedia entry strengthens long-term entity resolution.",
        "action": "Prepare an encyclopedia entry supported by independent third-party sources.",
        "acceptance": "The entry passes editorial review and is publicly available.",
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


def _contains_han(value):
    text = str(value or "")
    for _ in range(3):
        decoded = html.unescape(text)
        if decoded == text:
            break
        text = decoded
    text = UNICODE_ESCAPE_PATTERN.sub(lambda match: chr(int(match.group(1), 16)), text)
    return bool(HAN_PATTERN.search(text))


def _json_han(value):
    if isinstance(value, dict):
        return any(_contains_han(key) or _json_han(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_json_han(item) for item in value)
    return isinstance(value, str) and _contains_han(value)


def delivery_language_violations(delivery_directory):
    """Return relative paths containing literal or encoded Han characters."""
    directory = Path(delivery_directory)
    violations = set()
    for path in sorted(directory.rglob("*")):
        relative = path.relative_to(directory)
        if any(_contains_han(part) for part in relative.parts):
            violations.add(relative.as_posix())
        if not path.is_file():
            continue
        try:
            text = path.read_text("utf-8")
        except UnicodeDecodeError:
            if path.suffix.lower() in TEXT_SUFFIXES:
                violations.add(relative.as_posix())
            continue
        if _contains_han(text):
            violations.add(relative.as_posix())
            continue
        if path.suffix.lower() == ".json":
            try:
                value = json.loads(text)
            except json.JSONDecodeError:
                violations.add(relative.as_posix())
                continue
            if _json_han(value):
                violations.add(relative.as_posix())
    return sorted(violations)


def validate_delivery_language(delivery_directory):
    """Reject a package if any path or decoded text contains Han characters."""
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
    value = str(value or "").strip()
    return value if value and not _contains_han(value) else fallback


def _markdown_cell(value):
    return str(value or "").replace("|", "\\|").replace("\r", " ").replace("\n", " ").strip()


def _format_number(value):
    if isinstance(value, float):
        return f"{value:.1f}".rstrip("0").rstrip(".")
    return str(value if value is not None else "Not measured")


def _format_rate(value):
    return "Not measured" if value is None else f"{float(value):.1%}"


def _window_name(value, priority):
    value = str(value or "").strip()
    if match := re.fullmatch(r"(\d+)\s*天", value):
        return f"{match.group(1)} days"
    if match := re.fullmatch(r"(\d+)d", value, re.IGNORECASE):
        return f"{match.group(1)} days"
    if value and not _contains_han(value):
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
    value = str(value or "").strip()
    if _contains_han(value):
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
        "market": MARKET_NAMES.get(ticket.get("market"), _require_english(ticket.get("market") or "both", f"{ticket_id} market")),
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
    rows = geolib.read_jsonl(project_directory / "samples" / f"{date}.jsonl") if date else []
    by_platform = {}
    for row in rows:
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


def _audit_markdown(project_directory, name, site, audit, metrics):
    site_data = audit.get("site") or {}
    coverage = audit.get("language_coverage") or {}
    grades = audit.get("grade_distribution") or {}
    audited_at = str(audit.get("audited_at") or geolib.today())[:10]
    lines = [
        f"# {name} GEO Audit Report",
        "",
        f"- Audit date: {audited_at}",
        f"- Official website: {site}",
        f"- Target market: {MARKET_NAMES.get(audit.get('market'), 'Domestic and Global')}",
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
        f"| English pages | {coverage.get('en_pages', 0)} |",
        f"| Domestic-language pages | {coverage.get('zh_pages', 0)} |",
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

    lines += ["", "## AI Visibility Sampling", ""]
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
                f"| {_markdown_cell(label)} | {MARKET_NAMES.get(item.get('market'), 'Domestic')} "
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
    if channel_id in CHANNEL_NAMES:
        return CHANNEL_NAMES[channel_id]
    return _require_english(channel.get("name") or channel_id or "Configured channel", "blueprint channel name")


def _delivery_question(content, content_id):
    """英文交付保留英文问题，其他市场用稳定引用，不改项目源问题。"""
    question = str(content.get("question") or "").strip()
    if question and not _contains_han(question):
        return question
    market = MARKET_NAMES.get(content.get("market"), "Domestic and Global")
    return f"Configured {market} target question {content_id}"


def _build_map_markdown(name, blueprint):
    coverage = blueprint.get("coverage") or {}
    channels = blueprint.get("channels") or []
    contents = blueprint.get("contents") or []
    lines = [
        f"# {name} GEO Build Map",
        "",
        "This map defines where authority should be built and which target-query content should be produced.",
        "",
        f"- Channel coverage: **{coverage.get('channel_covered', 0)}/{coverage.get('channel_total', 0)}**",
        f"- P0/P1 channel coverage: **{coverage.get('p0p1_covered', 0)}/{coverage.get('p0p1_total', 0)}**",
        f"- Content completed: **{coverage.get('content_done', 0)}/{coverage.get('content_total', 0)}**",
        "",
        "## Channel Map",
        "",
        "| Priority | Channel | Market | Coverage | Evidence |",
        "|---|---|---|---|---|",
    ]
    for channel in sorted(channels, key=lambda item: (item.get("priority", "P9"), str(item.get("id", "")))):
        evidence = []
        if channel.get("national") is not None:
            evidence.append(f"{channel['national']:,} observed citations")
        if channel.get("position") is not None:
            evidence.append(f"average placement #{channel['position']}")
        if channel.get("platforms") is not None:
            evidence.append(f"observed across {channel['platforms']} platforms")
        lines.append(
            f"| {_require_english(channel.get('priority') or 'P2', 'channel priority')} "
            f"| {_markdown_cell(_channel_name(channel))} | {MARKET_NAMES.get(channel.get('market'), 'Domestic and Global')} "
            f"| {'Covered' if channel.get('covered') else 'Gap'} | {_markdown_cell('; '.join(evidence) or 'No citation evidence yet')} |"
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
            f"| {MARKET_NAMES.get(content.get('market'), 'Domestic and Global')} "
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
            return value
        if field == "name" and parent_type == "Question":
            return f"Configured Domestic target question {ordinal or 1}"
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


def _write_jsonld_assets(source, destination, made):
    jsonld = source / "jsonld"
    if not jsonld.exists():
        return
    for path in sorted(jsonld.glob("*.json")):
        if _contains_han(path.name):
            raise GeoEngineError(f"delivery source cannot be represented in English: assets/jsonld/{path.name}")
        try:
            value = json.loads(path.read_text("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GeoEngineError(f"invalid delivery JSON asset: assets/jsonld/{path.name}") from exc
        value = _replace_json_asset(value)
        if _json_han(value):
            raise GeoEngineError(f"delivery source cannot be represented in English: assets/jsonld/{path.name}")
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
        markdown = "\n".join([
            f"# Content Outline - {question}",
            "",
            f"- Question ID: `{content_id}`",
            f"- Market: {MARKET_NAMES.get(content.get('market'), 'Domestic and Global')}",
            f"- Recommended format: {form}",
            "",
            "## Required Structure",
            "",
            "1. Direct answer and concise definition",
            "2. Evidence-backed key facts",
            "3. Comparison table with consistent criteria",
            "4. Step-by-step implementation guidance",
            "5. Limitations and decision boundaries",
            "6. Frequently asked questions",
            "7. Sources and verification date",
            "",
            "## Quality Requirements",
            "",
            "- Use at least 1,000 words when the topic requires a comprehensive guide.",
            "- Include a clear definition, numeric facts, comparison, steps, and FAQ.",
            "- Cite a source and verification date for every material claim.",
            "- Mark unsupported claims for review; never invent customer, pricing, or competitor data.",
            "",
        ])
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
        if relative.startswith("outlines/") and path.suffix.lower() == ".md" and path.stem in content_ids:
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


def _write_assets(project_slug, project_directory, directory, config, audit, blueprint):
    source = project_directory / "assets"
    destination = directory / "assets"
    destination.mkdir(parents=True, exist_ok=True)
    made = []
    _write_llms_asset(project_slug, source, destination, config, audit, made)
    _write_jsonld_assets(source, destination, made)
    _write_snippet_assets(source, destination, config, project_slug, made)
    _write_outline_assets(source, destination, blueprint, made)
    _copy_drafts(source, destination, blueprint, made)
    _copy_other_assets(source, destination, blueprint, made)
    index = {
        "generated_at": geolib.now_iso(),
        "language": "English",
        "assets": sorted(made),
    }
    (destination / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", "utf-8")
    return sorted(made)


def _write_index(directory, name, site, delivery_date, audit, tickets, blueprint, assets):
    coverage = blueprint.get("coverage") or {}
    documents = [f"{number}-{title}.html" for number, title in REQUIRED_DOCUMENTS.items()]
    lines = [
        f"# {name} GEO Delivery Pack",
        "",
        f"- Official website: {site}",
        f"- Delivery date: {delivery_date}",
        f"- Average site score: {_format_number(audit.get('avg_score'))}",
        f"- Action tickets: {len(tickets)}",
        f"- Channel coverage: {coverage.get('channel_covered', 0)}/{coverage.get('channel_total', 0)}",
        "",
        "## Documents",
        "",
    ]
    for number, title in REQUIRED_DOCUMENTS.items():
        lines.append(f"- [{number} - {title}]({number}-{title}.html)")
    lines += ["", "## Deployable Assets", ""]
    lines += [f"- `{path}`" for path in assets] or ["No deployable assets were generated for this cycle."]
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
                ("Assets", str(len(assets))),
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
        "- `assets/`: English-safe deployable assets and an asset index.",
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

    audit_markdown = _audit_markdown(project_directory, name, site, audit, metrics)
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
    _write_document(directory, "06", build_map_markdown, [
        ("Channel Coverage", f"{coverage.get('channel_covered', 0)}/{coverage.get('channel_total', 0)}"),
        ("Content Complete", f"{coverage.get('content_done', 0)}/{coverage.get('content_total', 0)}"),
    ])
    assets = _write_assets(project_slug, project_directory, directory, config, audit, blueprint)
    _write_index(directory, name, site, delivery_date, audit, tickets, blueprint, assets)
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


def ensure_delivery_contract(project_slug: str, delivery_directory: Path | None = None):
    """Rebuild a delivery package and fail closed unless every artifact is English-only."""
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
