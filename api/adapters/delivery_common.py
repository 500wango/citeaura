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

from api import config as app_config
from api.adapters.branding import apply_delivery_branding
from api.adapters.delivery_language import (
    _contains_disallowed_english,
    _contains_han,
    _json_language_violation,
    delivery_language_violations,
    validate_delivery_language,
)
from api.adapters.engine import geolib
from api.adapters.exceptions import GeoEngineError
from api.adapters.localization import localize_ticket, normalize_english_typography
from api.adapters import action_scope, audit_presentation, brand_facts, brand_identity, global_scope, measurement, product_insights, report_quality, sampling_modes


REQUIRED_DOCUMENTS = {
    "01": "Audit-Report",
    "02": "Execution-Plan",
    "03": "Ticket-Log",
    "04": "Acceptance-Checklist",
    "05": "Draft-Risks",
    "06": "Build-Map",
}

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


def validate_existing_delivery_contract(delivery_directory):
    """Validate an already published package without rewriting its snapshot."""
    directory = Path(delivery_directory)
    required = [
        *(f"{number}-{name}.md" for number, name in REQUIRED_DOCUMENTS.items()),
        *(f"{number}-{name}.html" for number, name in REQUIRED_DOCUMENTS.items()),
        "03-Ticket-Log.csv",
        "assets/index.json",
    ]
    missing = [name for name in required if not (directory / name).is_file()]
    if missing:
        raise GeoEngineError("delivery package is incomplete: " + ", ".join(missing))
    asset_index = geolib.read_json(directory / "assets" / "index.json", {}) or {}
    if (asset_index.get("quality_gate") or {}).get("status") != "passed":
        raise GeoEngineError("delivery package quality gate is not passed")
    validate_delivery_language(directory)
    return directory


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
    fallback = normalize_english_typography(str(fallback or "").strip())
    if value and not _contains_disallowed_english(value):
        return value
    if not fallback:
        return ""
    return fallback if not _contains_disallowed_english(fallback) else "Not recorded"


def _safe_join_display(values, fallback):
    """Join dynamic labels without allowing one invalid value into the package."""
    if isinstance(values, (str, bytes)) or not values:
        values = [values] if values else []
    rendered = []
    for value in values:
        text = _safe_display(value, fallback)
        if text and text not in rendered:
            rendered.append(text)
    return ", ".join(rendered) or fallback


def _safe_count(value, fallback="Not measured"):
    """Keep numeric counters numeric while replacing malformed localized values."""
    if isinstance(value, bool):
        return fallback
    if isinstance(value, (int, float)):
        return _format_number(value)
    text = normalize_english_typography(str(value or "").strip())
    return text if re.fullmatch(r"-?\d+(?:\.\d+)?", text) else fallback


def _markdown_cell(value):
    return str(value or "").replace("|", "\\|").replace("\r", " ").replace("\n", " ").strip()


def _format_number(value):
    if isinstance(value, float):
        return f"{value:.1f}".rstrip("0").rstrip(".")
    return str(value if value is not None else "Not measured")


def _format_rate(value):
    return "Not measured" if value is None else f"{float(value):.1%}"


def _score_result_label(score, partial_score=None):
    if score is not None:
        return _format_number(score)
    if partial_score is not None:
        return f"Not reported (partial result: {_format_number(partial_score)})"
    return "Not measured"


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
            "Publish the approved facts index at /llms.txt",
            "A curated facts index gives AI systems a stable official reference.",
            "After factual approval, generate the llms.txt asset and deploy it at the website root.",
            "The brand facts library is approved and /llms.txt is retrieved successfully on re-crawl.",
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
    prerequisites = []
    seen_prereqs = set()
    for item in ticket.get("prerequisites") or []:
        if not isinstance(item, dict):
            continue
        label = _require_english(item.get("label") or item.get("id") or "Required evidence", f"{ticket_id} prerequisite")
        status = "Met" if item.get("status") == "met" else "Pending"
        key = str(item.get("id") or label)
        if key in seen_prereqs:
            continue
        seen_prereqs.add(key)
        prerequisites.append({"id": key, "label": label, "status": status})
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
        "acceptance_check": check,
        "verification_mode": "Automated" if acceptance.get("type") == "auto" else "Manual",
        "status": STATUS_NAMES.get(ticket.get("status"), _require_english(ticket.get("status") or "todo", f"{ticket_id} status")),
        "affected": [
            _require_english(item, f"{ticket_id} affected page")
            for item in (ticket.get("affected") or [])
        ],
        "prerequisites": prerequisites,
        "execution_ready": all(item["status"] == "Met" for item in prerequisites),
    }


def _load_sources(project_directory):
    audit = _read_required(project_directory / "audit.json", "audit.json")
    validated_site = geolib.read_json(project_directory / "evidence" / "site.json", None)
    if isinstance(validated_site, dict) and validated_site:
        audit_site = audit.get("site") if isinstance(audit.get("site"), dict) else {}
        audit = {**audit, "site": {**audit_site, **validated_site}}
    tasks = _read_required(project_directory / "tasks.json", "tasks.json")
    blueprint = _read_required(project_directory / "blueprint.json", "blueprint.json")
    if not isinstance(tasks.get("tasks"), list):
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


def _internal_provider_code(value):
    text = str(value or "").strip()
    return text == "custom" or text.startswith("custom_")


def _usable_provider_name(value):
    text = str(value or "").strip()
    if not text or _internal_provider_code(text):
        return ""
    return text


def _merged_provider_labels(project_directory, metrics=None, config=None):
    config = config if isinstance(config, dict) else geolib.read_json(Path(project_directory) / "geo.json", {}) or {}
    labels = {}
    for key, value in (config.get("provider_labels") or {}).items():
        name = _usable_provider_name(value)
        if name:
            labels[str(key)] = name
    samples_dir = Path(project_directory) / "samples"
    if samples_dir.is_dir():
        for path in sorted(samples_dir.glob("*.jsonl")):
            for row in geolib.read_jsonl(path):
                if not isinstance(row, dict):
                    continue
                name = _usable_provider_name(row.get("platform_name"))
                code = str(row.get("platform") or "")
                if code and name:
                    labels[code] = name
    for code, item in ((metrics or {}).get("platforms") or {}).items():
        if not isinstance(item, dict):
            continue
        name = _usable_provider_name(item.get("name") or item.get("label"))
        if name:
            labels[str(code)] = name
    return labels


def _merged_provider_model_ids(project_directory, metrics=None, config=None):
    """合并自定义供应商的非敏感 model_id 元数据。"""
    config = config if isinstance(config, dict) else geolib.read_json(Path(project_directory) / "geo.json", {}) or {}
    model_ids = {
        str(key): str(value).strip()
        for key, value in (config.get("provider_model_ids") or {}).items()
        if str(key).strip() and str(value).strip()
    }
    samples_dir = Path(project_directory) / "samples"
    if samples_dir.is_dir():
        for path in sorted(samples_dir.glob("*.jsonl")):
            for row in geolib.read_jsonl(path):
                if not isinstance(row, dict):
                    continue
                code = str(row.get("platform") or "")
                raw_model = str(row.get("raw_model") or "").strip()
                if code and raw_model and _internal_provider_code(code) and code not in model_ids:
                    model_ids[code] = raw_model
    observability = (metrics or {}).get("provider_observability") or {}
    for code, item in (observability.get("platforms") or {}).items():
        if str(code) in model_ids or not _internal_provider_code(code) or not isinstance(item, dict):
            continue
        models = [str(value).strip() for value in item.get("models") or [] if str(value).strip()]
        if len(models) == 1:
            model_ids[str(code)] = models[0]
    return model_ids


def _platform_display_name(code, item, config=None):
    item = item if isinstance(item, dict) else {}
    config = config if isinstance(config, dict) else {}
    labels = config.get("provider_labels") if isinstance(config.get("provider_labels"), dict) else {}
    model_ids = config.get("provider_model_ids") if isinstance(config.get("provider_model_ids"), dict) else {}
    model_id = str(model_ids.get(code) or "").strip()
    if _internal_provider_code(code):
        candidates = (labels.get(code), item.get("name"), item.get("label"))
        name = next(
            (
                usable
                for candidate in candidates
                for usable in (_usable_provider_name(candidate),)
                if usable and usable.casefold() not in {
                    "configured provider",
                    "configured openai-compatible provider",
                }
            ),
            "",
        )
        if model_id:
            base = name or "Configured OpenAI-compatible provider"
            return _safe_display(f"{base} · {model_id}", "Configured OpenAI-compatible provider")
        if name:
            return _safe_display(name, "Configured OpenAI-compatible provider")
    for candidate in (item.get("label"), item.get("name"), labels.get(code)):
        name = _usable_provider_name(candidate)
        if _internal_provider_code(code) and name.casefold() in {
            "configured provider",
            "configured openai-compatible provider",
        }:
            continue
        if name:
            return _safe_display(name, "Configured OpenAI-compatible provider")
    if _internal_provider_code(code) or _internal_provider_code(item.get("label")):
        named = [name for name in (_usable_provider_name(value) for value in labels.values()) if name]
        unique = list(dict.fromkeys(named))
        if model_id:
            base = unique[0] if len(unique) == 1 else "Configured OpenAI-compatible provider"
            return _safe_display(f"{base} · {model_id}", "Configured OpenAI-compatible provider")
        if len(unique) == 1:
            return _safe_display(unique[0], "Configured OpenAI-compatible provider")
        return "Configured OpenAI-compatible provider"
    return _safe_display(code, "Configured provider")


def _platform_display_names(platforms, config=None):
    """为重名的 API 与自定义供应商生成无歧义的报告标签。"""
    rows = [
        (str(code or ""), _platform_display_name(code, item, config))
        for code, item in (platforms or {}).items()
    ]
    counts = {}
    for _, label in rows:
        counts[label] = counts.get(label, 0) + 1
    labels = {}
    used = set()
    for code, label in rows:
        candidate = label
        if counts.get(label, 0) > 1:
            suffix = "configured provider" if _internal_provider_code(code) else "API provider"
            candidate = f"{label} ({suffix})"
            index = 2
            while candidate in used:
                candidate = f"{label} ({suffix} {index})"
                index += 1
        labels[code] = candidate
        used.add(candidate)
    return labels


BUILTIN_PROVIDER_LABELS = {
    "glm": "Zhipu GLM",
    "doubao": "Doubao (Ark API)",
    "deepseek": "DeepSeek",
    "kimi": "Kimi",
    "minimax": "MiniMax",
    "gemini": "Gemini",
    "openai": "OpenAI (ChatGPT)",
    "claude": "Claude",
    "grok": "Grok",
    "perplexity": "Perplexity",
    "chatgpt": "ChatGPT",
    "claude_web": "Claude (product interface)",
    "google_ai_overview": "Google AI Overviews",
}


def _receipt_platform_label(code, display_names, platforms, config):
    """Render receipt platform codes as customer-facing provider labels."""
    code = str(code or "")
    if code in display_names:
        return display_names[code]
    if code in BUILTIN_PROVIDER_LABELS:
        return BUILTIN_PROVIDER_LABELS[code]
    return _platform_display_name(code, (platforms or {}).get(code) or {}, config)


def _sample_modes(project_directory, metrics):
    date = str((metrics or {}).get("run_id") or (metrics or {}).get("date") or "")
    config = geolib.read_json(project_directory / "geo.json", {}) or {}
    rows = geolib.read_jsonl(project_directory / "samples" / f"{date}.jsonl") if date else []
    by_platform = {}
    for row in rows:
        if not global_scope.is_global_sample(row, config) or not brand_identity.is_current_sample(row, config):
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


def _current_sample_rows(project_directory, config):
    """读取最新合法样本，供客户报告复用与工作区相同的样本身份过滤。"""
    directory = Path(project_directory) / "samples"
    files = sorted(directory.glob("*.jsonl")) if directory.exists() else []
    if not files:
        return []
    return [
        row for row in geolib.read_jsonl(files[-1])
        if global_scope.is_global_sample(row, config) and brand_identity.is_current_sample(row, config)
    ]


INSIGHT_MODE_NAMES = {
    sampling_modes.MODE_API: "API - Parametric knowledge",
    sampling_modes.MODE_SEARCH: "API - Search grounded",
    sampling_modes.MODE_MANUAL: "Manual - Product interface",
}


def _insight_mode_name(value):
    value = str(value or "")
    if value in INSIGHT_MODE_NAMES:
        return INSIGHT_MODE_NAMES[value]
    if value.startswith("Mixed:"):
        return value.replace("API·参数化知识", "API - Parametric knowledge").replace(
            "API·联网检索", "API - Search grounded",
        ).replace("人工·产品端", "Manual - Product interface")
    return _safe_display(value, "Unlabeled sampling mode")


def _interval_label(interval):
    if not isinstance(interval, dict):
        return "Not measured"
    lower = interval.get("lower")
    upper = interval.get("upper")
    if lower is None or upper is None:
        return "Not measured"
    return f"{float(lower):.1%}–{float(upper):.1%}"

# Internal wildcard imports intentionally expose the facade's stable private helper contract.
__all__ = tuple(name for name in globals() if not name.startswith("__"))
