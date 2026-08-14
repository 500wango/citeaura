"""Build page-role-aware, English audit views from immutable engine artifacts."""

import re
from collections import defaultdict
from urllib.parse import unquote, urlparse, urlunparse

from api.adapters.engine import geolib


ROLE_LABELS = {
    "home": "Home page",
    "product_service": "Product or service page",
    "pricing": "Pricing page",
    "comparison": "Comparison page",
    "article_news": "Article or news page",
    "docs_howto": "Documentation or guide",
    "faq_support": "FAQ or support page",
    "case_study": "Case study",
    "about": "About page",
    "contact": "Contact page",
    "legal": "Legal or policy page",
    "category_listing": "Category or listing page",
    "auth_utility": "Application or utility page",
    "generic": "General content page",
}

ROLE_PRIORITY = (
    "contact", "legal", "auth_utility", "pricing", "comparison", "faq_support",
    "docs_howto", "case_study", "article_news", "about", "category_listing",
    "product_service", "generic",
)

SCHEMA_ROLES = {
    "ContactPage": "contact",
    "AboutPage": "about",
    "FAQPage": "faq_support",
    "HowTo": "docs_howto",
    "TechArticle": "docs_howto",
    "Article": "article_news",
    "BlogPosting": "article_news",
    "NewsArticle": "article_news",
    "Report": "article_news",
    "CaseStudy": "case_study",
    "Product": "product_service",
    "SoftwareApplication": "product_service",
    "Service": "product_service",
    "CollectionPage": "category_listing",
    "ItemList": "category_listing",
    "ProfilePage": "about",
}

PATH_SIGNALS = {
    "contact": ("contact", "contact us", "get in touch", "sales inquiry", "request quote"),
    "legal": (
        "privacy", "privacy policy", "terms", "terms of service", "terms and conditions",
        "legal", "cookies", "cookie policy", "gdpr", "imprint", "disclaimer",
        "acceptable use", "refund policy", "shipping policy", "license agreement",
    ),
    "auth_utility": (
        "login", "log in", "signin", "sign in", "signup", "sign up", "register",
        "account", "auth", "password", "reset password", "dashboard", "admin", "app",
        "cart", "checkout", "search", "status", "404", "not found",
    ),
    "pricing": ("pricing", "price", "plans", "subscriptions", "tariffs"),
    "comparison": ("compare", "comparison", "versus", "vs", "alternatives", "competitors"),
    "faq_support": ("faq", "faqs", "support", "help center", "customer care"),
    "docs_howto": (
        "docs", "documentation", "guide", "guides", "tutorial", "tutorials", "how to",
        "howto", "quickstart", "getting started", "manual", "knowledge base", "kb",
        "api reference", "developer", "developers", "installation", "setup",
    ),
    "case_study": (
        "case study", "case studies", "customer story", "customer stories", "success story",
        "success stories", "portfolio",
    ),
    "article_news": (
        "blog", "blogs", "article", "articles", "news", "insights", "journal", "posts",
        "press release", "research",
    ),
    "about": ("about", "about us", "company", "our story", "team", "mission", "who we are"),
    "category_listing": ("category", "categories", "collection", "collections", "catalog", "shop", "store"),
    "product_service": (
        "product", "products", "service", "services", "solution", "solutions", "platform",
        "feature", "features", "offering", "offerings", "capabilities",
    ),
}

SURFACE_SIGNALS = {
    "contact": ("contact us", "get in touch", "contact our", "sales inquiry"),
    "legal": ("privacy policy", "terms of service", "terms and conditions", "cookie policy"),
    "pricing": ("pricing", "plans and pricing", "choose a plan"),
    "comparison": ("comparison", "compare", " versus ", " alternatives"),
    "faq_support": ("frequently asked questions", "help center", "support center"),
    "docs_howto": ("documentation", "quickstart", "getting started", "how to", "step by step"),
    "case_study": ("case study", "customer story", "success story"),
    "article_news": ("news", "press release", "research report"),
    "about": ("about us", "our story", "who we are", "our mission"),
    "category_listing": ("all products", "browse products", "product catalog", "collections"),
    "product_service": ("our services", "our solutions", "product features", "service overview"),
}

ROLE_POLICY = {
    "home": {"content": (120, 6), "h2": 2, "definition": True, "schema": True},
    "product_service": {"content": (120, 5), "h2": 2, "definition": True, "schema": True},
    "pricing": {"content": (80, 4), "h2": 2, "numeric_facts": True, "schema": True},
    "comparison": {
        "content": (250, 8), "h2": 3, "definition": True, "numeric_facts": True,
        "comparison": True, "external": True, "schema": True,
    },
    "article_news": {"content": (300, 8), "h2": 3, "date": True, "external": True, "schema": True},
    "docs_howto": {"content": (200, 6), "h2": 3, "schema": True},
    "faq_support": {"content": (100, 4), "h2": 2, "faq": True, "schema": True},
    "case_study": {"content": (200, 6), "h2": 3, "numeric_facts": True, "schema": True},
    "about": {"content": (100, 4), "h2": 1, "definition": True, "schema": True},
    "contact": {},
    "legal": {"content": (100, 5), "h2": 1, "date": True},
    "category_listing": {"content": (60, 3), "h2": 1, "schema": True},
    "generic": {},
}

CHECK_WEIGHTS = {
    "accessibility": 20,
    "indexability": 10,
    "canonical": 8,
    "rendered_content": 15,
    "h1": 10,
    "content_depth": 12,
    "section_structure": 8,
    "structured_data": 10,
    "definition": 8,
    "numeric_facts": 8,
    "comparison": 8,
    "steps": 8,
    "faq": 8,
    "date": 6,
    "external_evidence": 5,
}

KNOWN_ISSUE_CODES = frozenset((
    "BAD_H1", "FEW_EXTERNAL_LINKS", "FEW_H2", "LOW_CONTENT_PAGE",
    "LOW_LIST_DENSITY", "LOW_RELEVANCE", "NOINDEX", "NON_200_STATUS",
    "NO_CANONICAL", "NO_DATE", "NO_JSONLD", "PAGE_UNREACHABLE",
    "SHORT_CONTENT", "SPA_SHELL", "NO_DEFINITION", "NO_NUMBERS",
    "NO_COMPARISON", "NO_HOWTO", "NO_FAQ",
))

DIMENSION_NAMES = {
    "\u53ef\u6293\u53d6\u6027": "crawlability",
    "\u5185\u5bb9\u957f\u5ea6": "content_depth",
    "\u7ed3\u6784\u89c4\u8303": "structure",
    "\u53ef\u62bd\u53d6\u5757": "extractability",
    "\u6743\u5a01\u4fe1\u53f7": "authority",
    "\u5bf9\u9898\u6027": "query_alignment",
}

BLOCK_KEYS = {
    "definition": ("definition", "\u5b9a\u4e49"),
    "numeric_facts": ("numeric_facts", "\u6570\u5b57\u4e8b\u5b9e"),
    "comparison": ("comparison", "\u5bf9\u6bd4"),
    "steps": ("steps", "\u64cd\u4f5c\u6b65\u9aa4"),
    "faq": ("faq", "FAQ"),
}

BLOCK_LABELS = {
    "definition": "Definition",
    "numeric_facts": "Numeric facts",
    "comparison": "Comparison",
    "steps": "Step-by-step guidance",
    "faq": "FAQ",
}


def _surface(page):
    values = [page.get("title"), page.get("meta_description")]
    values.extend(page.get("h1") or [])
    values.extend(page.get("h2") or [])
    return " ".join(str(value or "") for value in values).lower()


def _normalized_words(value):
    return " " + re.sub(r"[^a-z0-9]+", " ", unquote(str(value or "")).lower()).strip() + " "


def _has_phrase(value, phrase):
    return f" {phrase} " in value


def _add_signal(scores, evidence, role, weight, signal):
    scores[role] += weight
    if signal not in evidence[role]:
        evidence[role].append(signal)


def classify_page(page):
    """Classify a page by function using URL, headings, and Schema.org evidence."""
    page = page if isinstance(page, dict) else {}
    parsed = urlparse(str(page.get("url") or page.get("final_url") or ""))
    path = parsed.path or "/"
    segments = [segment for segment in path.strip("/").split("/") if segment]
    if not segments or (len(segments) == 1 and re.fullmatch(r"[a-z]{2}(?:-[a-z]{2})?", segments[0], re.I)):
        return {
            "id": "home", "label": ROLE_LABELS["home"], "confidence": "high",
            "confidence_score": 0.99, "signals": ["root URL"],
        }

    scores = defaultdict(int)
    evidence = defaultdict(list)
    normalized_path = _normalized_words(path)
    final_segment = _normalized_words(segments[-1]).strip()

    listing_roots = {"products", "collections", "catalog", "shop", "blog", "articles", "news", "insights"}
    if final_segment in listing_roots:
        _add_signal(scores, evidence, "category_listing", 16, f"URL section: {final_segment}")

    for role, phrases in PATH_SIGNALS.items():
        for phrase in phrases:
            if _has_phrase(normalized_path, phrase):
                _add_signal(scores, evidence, role, 12, f"URL signal: {phrase}")

    schema_types = set(page.get("jsonld_types") or [])
    for item_type in schema_types:
        schema_name = str(item_type).rstrip("/").rsplit("/", 1)[-1].rsplit("#", 1)[-1]
        role = SCHEMA_ROLES.get(schema_name)
        if role:
            _add_signal(scores, evidence, role, 9, f"Schema.org type: {item_type}")

    normalized_surface = _normalized_words(_surface(page))
    for role, phrases in SURFACE_SIGNALS.items():
        for phrase in phrases:
            if _has_phrase(normalized_surface, phrase.strip()):
                _add_signal(scores, evidence, role, 3, f"page heading: {phrase.strip()}")

    if not scores:
        return {
            "id": "generic", "label": ROLE_LABELS["generic"], "confidence": "low",
            "confidence_score": 0.35, "signals": [],
        }

    order = {role: index for index, role in enumerate(ROLE_PRIORITY)}
    role = sorted(scores, key=lambda item: (-scores[item], order.get(item, 999), item))[0]
    value = scores[role]
    confidence = "high" if value >= 8 else "medium" if value >= 5 else "low"
    confidence_score = min(0.98, round(0.45 + value * 0.055, 2))
    return {
        "id": role,
        "label": ROLE_LABELS[role],
        "confidence": confidence,
        "confidence_score": confidence_score,
        "signals": evidence[role][:4],
    }


def _url_key(value, *, keep_query=True):
    try:
        parsed = urlparse(str(value or "").strip())
    except ValueError:
        return ""
    if not parsed.netloc:
        return str(value or "").strip().rstrip("/")
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    return urlunparse((
        parsed.scheme.lower(), parsed.netloc.lower(), path, "",
        parsed.query if keep_query else "", "",
    ))


def _evidence_lookup(pages):
    exact = {}
    without_query = {}
    for page in pages if isinstance(pages, list) else []:
        if not isinstance(page, dict):
            continue
        aliases = page.get("duplicate_urls") or []
        if not isinstance(aliases, list):
            aliases = [aliases]
        for value in (page.get("url"), page.get("final_url"), *aliases):
            key = _url_key(value)
            if key:
                exact[key] = page
            key = _url_key(value, keep_query=False)
            if key and key not in without_query:
                without_query[key] = page
    return exact, without_query


def _page_evidence(page, lookup):
    exact, without_query = lookup
    return exact.get(_url_key(page.get("url"))) or without_query.get(
        _url_key(page.get("url"), keep_query=False)
    ) or {}


def _number(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _issue_code(value):
    code = re.sub(r"[^A-Za-z0-9]+", "_", str(value or "")).strip("_").upper()
    return code or "UNCLASSIFIED_ENGINE_CHECK"


def _dimension_name(value, index):
    if str(value) in DIMENSION_NAMES:
        return DIMENSION_NAMES[str(value)]
    name = re.sub(r"[^A-Za-z0-9]+", "_", str(value or "")).strip("_").lower()
    return name or f"dimension_{index}"


def _grade(score):
    if score is None:
        return None
    if score >= 90:
        return "A"
    if score >= 75:
        return "B"
    if score >= 60:
        return "C"
    return "D"


def _finding(code, title, detail, recommendation, severity="P1", category="content"):
    return {
        "code": code,
        "severity": severity,
        "category": category,
        "title": title,
        "detail": detail,
        "recommendation": recommendation,
    }


def _block_value(blocks, name):
    for key in BLOCK_KEYS[name]:
        if key in blocks:
            return bool(blocks[key])
    return None


def _guide_requires_steps(page):
    value = _normalized_words(
        " ".join([str(page.get("url") or ""), _surface(page)])
    )
    return any(_has_phrase(value, phrase) for phrase in (
        "how to", "tutorial", "guide", "quickstart", "getting started", "installation", "setup",
    ))


def _present_page(raw_page, evidence):
    raw_page = raw_page if isinstance(raw_page, dict) else {}
    evidence = evidence if isinstance(evidence, dict) else {}
    merged = {**raw_page, **evidence, "url": raw_page.get("url") or evidence.get("url")}
    role = classify_page(merged)
    role_id = role["id"]
    raw_codes = list(dict.fromkeys(
        _issue_code(code) for code in raw_page.get("issue_codes") or [] if code
    ))
    codes = set(raw_codes)
    word_count = _number(evidence.get("word_count", raw_page.get("word_count")), 0)
    para_count = _number(evidence.get("para_count"), 0)
    h1 = evidence.get("h1") if isinstance(evidence.get("h1"), list) else None
    h2 = evidence.get("h2") if isinstance(evidence.get("h2"), list) else None
    schema_types = list(dict.fromkeys(
        str(value) for value in (evidence.get("jsonld_types") or raw_page.get("jsonld_types") or []) if value
    ))
    blocks = raw_page.get("blocks") if isinstance(raw_page.get("blocks"), dict) else {}
    normalized_blocks = {name: _block_value(blocks, name) for name in BLOCK_KEYS}
    policy = ROLE_POLICY.get(role_id, {})

    base = {
        "url": raw_page.get("url") or evidence.get("url"),
        "title": raw_page.get("title") or evidence.get("title") or "",
        "word_count": word_count,
        "raw_score": raw_page.get("score"),
        "raw_grade": raw_page.get("grade"),
        "score": raw_page.get("score"),
        "grade": raw_page.get("grade"),
        "engine_dimensions": {
            _dimension_name(key, index): value
            for index, (key, value) in enumerate((raw_page.get("dimensions") or {}).items(), 1)
        },
        "blocks": normalized_blocks,
        "jsonld_types": schema_types,
        "issue_codes": raw_codes,
        "role": role,
    }

    if role_id == "auth_utility":
        return {
            **base,
            "applicable_score": None,
            "applicable_grade": None,
            "evaluation_status": "excluded",
            "evaluation_note": "Application and utility pages are excluded from public-content scoring.",
            "findings": [],
            "issues": [],
            "checks": [],
            "check_summary": {
                "evaluated": 0, "passed": 0, "failed": 0,
                "not_applicable": len(CHECK_WEIGHTS), "not_evaluated": 0,
            },
        }

    checks = {name: {"id": name, "status": "not_applicable", "weight": weight}
              for name, weight in CHECK_WEIGHTS.items()}
    findings = []

    def record(name, passed=None, finding=None, not_evaluated=False):
        if not_evaluated:
            checks[name]["status"] = "not_evaluated"
            return
        checks[name]["status"] = "passed" if passed else "failed"
        if finding:
            findings.append(finding)

    status = evidence.get("status")
    if status is None:
        if "PAGE_UNREACHABLE" in codes:
            status = 0
        elif "NON_200_STATUS" in codes:
            status = -1
        else:
            status = 200
    status = _number(status, 0)
    unreachable = status == 0 or status >= 400 or "PAGE_UNREACHABLE" in codes
    successful = status == 200 and not unreachable
    if unreachable:
        record("accessibility", False, _finding(
            "PAGE_UNREACHABLE", "Page is not crawlable",
            f"The crawl returned HTTP {status or 'no response'}; downstream content checks were not evaluated.",
            "Restore a successful public response before evaluating page content.", "P0", "crawlability",
        ))
    elif not successful:
        record("accessibility", False, _finding(
            "NON_200_STATUS", "Page does not return HTTP 200",
            f"The crawl recorded HTTP {status if status >= 0 else 'non-200'} for this URL.",
            "Return a stable HTTP 200 response at the canonical public URL.", "P1", "crawlability",
        ))
    else:
        record("accessibility", True)

    if unreachable:
        for name in CHECK_WEIGHTS:
            if name != "accessibility":
                record(name, not_evaluated=True)
    else:
        noindex = "noindex" in str(evidence.get("meta_robots") or "").lower() or "NOINDEX" in codes
        record("indexability", not noindex, None if not noindex else _finding(
            "NOINDEX", "Page is excluded by noindex",
            "Search and answer-engine crawlers are instructed not to index this public page.",
            "Remove noindex only when this page is intended for public discovery.", "P0", "crawlability",
        ))

        canonical_known = bool(evidence) or "NO_CANONICAL" in codes
        canonical_ok = bool(evidence.get("canonical")) if evidence else "NO_CANONICAL" not in codes
        if canonical_known:
            record("canonical", canonical_ok, None if canonical_ok else _finding(
                "NO_CANONICAL", "Missing canonical URL",
                "This public page does not declare its preferred canonical URL.",
                "Add a self-referencing or otherwise correct canonical URL.", "P2", "crawlability",
            ))
        else:
            record("canonical", not_evaluated=True)

        rendered_ok = (
            word_count >= 20 or para_count >= 2 or bool(h1) or
            (not evidence and "SPA_SHELL" not in codes and "LOW_CONTENT_PAGE" not in codes)
        )
        record("rendered_content", rendered_ok, None if rendered_ok else _finding(
            "SPA_SHELL", "No meaningful server-rendered content detected",
            f"The crawler found {word_count} words and no reliable body structure in the initial HTML.",
            "Render the page's essential public content in HTML through SSR, static generation, or prerendering.",
            "P0", "crawlability",
        ))

        schema_applicable = bool(policy.get("schema"))
        if schema_applicable:
            schema_ok = bool(schema_types) or (not evidence and "NO_JSONLD" not in codes)
            record("structured_data", schema_ok, None if schema_ok else _finding(
                "NO_JSONLD", "No JSON-LD detected for this content page",
                "The page has no machine-readable structured data describing its visible content.",
                "Add only Schema.org types and properties supported by visible content and verified facts.",
                "P2", "semantics",
            ))

        if not rendered_ok:
            for name in (
                "h1", "content_depth", "section_structure", "definition", "numeric_facts",
                "comparison", "steps", "faq", "date", "external_evidence",
            ):
                if name in ("h1",) or policy.get(name) or (name == "content_depth" and policy.get("content")) or (name == "section_structure" and policy.get("h2")):
                    record(name, not_evaluated=True)
        else:
            h1_ok = len(h1) == 1 if h1 is not None else "BAD_H1" not in codes
            record("h1", h1_ok, None if h1_ok else _finding(
                "BAD_H1", "Page needs one clear H1",
                "The crawl did not find exactly one primary page heading.",
                "Use one descriptive H1 that states the page's main purpose.", "P1", "structure",
            ))

            content_rule = policy.get("content")
            if content_rule:
                minimum_words, minimum_paragraphs = content_rule
                content_ok = word_count >= minimum_words or para_count >= minimum_paragraphs
                record("content_depth", content_ok, None if content_ok else _finding(
                    "SHORT_CONTENT", "Visible content is too thin for this page role",
                    f"The crawl found {word_count} words and {para_count} paragraphs on a {ROLE_LABELS[role_id].lower()}.",
                    "Add concise, decision-useful information that fulfills this page's purpose; do not pad to a universal word count.",
                    "P1", "content",
                ))

            h2_minimum = policy.get("h2")
            if h2_minimum:
                h2_count = len(h2) if h2 is not None else None
                h2_ok = h2_count >= h2_minimum if h2_count is not None else "FEW_H2" not in codes
                record("section_structure", h2_ok, None if h2_ok else _finding(
                    "FEW_H2", "Section structure is too shallow for this page role",
                    f"The page has {h2_count if h2_count is not None else 'too few'} H2 sections; this role needs at least {h2_minimum} distinct sections.",
                    "Organize existing information under descriptive, intent-led headings.", "P1", "structure",
                ))

            block_rules = (
                ("definition", "NO_DEFINITION", "Missing a clear definition", "State plainly what the subject or offering is and who it serves."),
                ("numeric_facts", "NO_NUMBERS", "Missing decision-useful numeric facts", "Add verified prices, specifications, outcomes, or other role-relevant figures."),
                ("comparison", "NO_COMPARISON", "Missing the promised comparison", "Compare the named options with consistent, evidence-backed criteria."),
                ("faq", "NO_FAQ", "Missing answerable support questions", "Add concise answers to the recurring questions this support page is meant to resolve."),
            )
            for name, code, title, recommendation in block_rules:
                if not policy.get(name):
                    continue
                value = normalized_blocks.get(name)
                passed = value if value is not None else code not in codes
                record(name, passed, None if passed else _finding(
                    code, title,
                    f"The expected {BLOCK_LABELS[name].lower()} block was not detected on this {ROLE_LABELS[role_id].lower()}.",
                    recommendation, "P1", "extractability",
                ))

            if role_id == "docs_howto" and _guide_requires_steps(merged):
                value = normalized_blocks.get("steps")
                passed = value if value is not None else "NO_HOWTO" not in codes
                record("steps", passed, None if passed else _finding(
                    "NO_HOWTO", "Guide lacks an extractable sequence of steps",
                    "The page promises procedural guidance but no clear ordered process was detected.",
                    "Present the verified procedure as ordered steps with explicit actions and prerequisites.",
                    "P1", "extractability",
                ))

            if policy.get("date"):
                passed = "NO_DATE" not in codes
                record("date", passed, None if passed else _finding(
                    "NO_DATE", "Missing publication or update date",
                    f"This {ROLE_LABELS[role_id].lower()} does not expose a verifiable publication or update date.",
                    "Show an accurate date and keep datePublished/dateModified structured data consistent with it.",
                    "P2", "authority",
                ))

            if policy.get("external"):
                links = evidence.get("external_links")
                passed = _number(links) >= 1 if links is not None else "FEW_EXTERNAL_LINKS" not in codes
                record("external_evidence", passed, None if passed else _finding(
                    "FEW_EXTERNAL_LINKS", "Claims lack an external evidence path",
                    "No external primary or independent source was detected for claims that benefit from verification.",
                    "Cite relevant primary or independent sources; do not add unrelated links to satisfy a count.",
                    "P2", "authority",
                ))

    for code in raw_codes:
        if code in KNOWN_ISSUE_CODES:
            continue
        title = code.replace("_", " ").strip().title() or "Unclassified audit finding"
        findings.append(_finding(
            code, title,
            "The engine reported a check that this presentation version does not yet classify.",
            "Review the crawl evidence before deciding whether action is required.",
            "P2", "review",
        ))

    evaluated = [item for item in checks.values() if item["status"] in ("passed", "failed")]
    earned = sum(item["weight"] for item in evaluated if item["status"] == "passed")
    possible = sum(item["weight"] for item in evaluated)
    applicable_score = round(earned / possible * 100, 1) if possible else None
    status_counts = {status: sum(item["status"] == status for item in checks.values()) for status in (
        "passed", "failed", "not_applicable", "not_evaluated",
    )}
    return {
        **base,
        "applicable_score": applicable_score,
        "applicable_grade": _grade(applicable_score),
        "evaluation_status": "evaluated" if possible else "not_evaluated",
        "evaluation_note": "Score uses only checks applicable to the inferred page role.",
        "findings": findings,
        "issues": [item["title"] for item in findings],
        "checks": list(checks.values()),
        "check_summary": {"evaluated": len(evaluated), **status_counts},
    }


def _site_findings(site, coverage, page_count):
    findings = []
    crawled = _number(site.get("pages_crawled"), page_count)
    accessible = _number(site.get("pages_ok"), crawled)
    if crawled and accessible < crawled:
        findings.append(_finding(
            "SITE_CRAWL_INCOMPLETE", "Some discovered pages were not accessible",
            f"The crawl could access {accessible} of {crawled} discovered pages.",
            "Review failed URLs and restore intentional public pages before drawing site-wide conclusions.",
            "P0", "crawlability",
        ))
    blocked = [str(value) for value in site.get("ai_bots_blocked") or [] if value]
    if blocked:
        findings.append(_finding(
            "AI_BOTS_BLOCKED", "robots.txt blocks AI crawlers",
            f"The current policy blocks: {', '.join(blocked)}.",
            "Confirm the policy is intentional; allow only the crawlers required by the measurement and publishing strategy.",
            "P0", "crawlability",
        ))
    if not site.get("has_sitemap"):
        findings.append(_finding(
            "NO_SITEMAP", "sitemap.xml was not detected",
            "The crawl did not find a sitemap describing the site's canonical public URLs.",
            "Publish a current sitemap and reference it from robots.txt.", "P1", "crawlability",
        ))
    if page_count and "en_pages" in coverage and _number(coverage.get("en_pages"), 0) == 0:
        findings.append(_finding(
            "NO_SUBSTANTIVE_ENGLISH_PAGES", "No substantive English page was detected",
            "The current global audit did not find an English page with enough extractable body content.",
            "Add useful English content only when English-speaking audiences are in scope.", "P1", "coverage",
        ))
    if not site.get("has_llms_txt"):
        findings.append(_finding(
            "NO_LLMS_TXT", "llms.txt was not detected",
            "No optional llms.txt facts index was found at the site root.",
            "Consider publishing a maintained facts index; do not treat it as a substitute for crawlable pages.",
            "P2", "semantics",
        ))
    return findings


def present_audit_data(audit, evidence_pages=None, site_data=None):
    """Return a non-mutating product view of raw audit and crawl evidence."""
    audit = audit if isinstance(audit, dict) else {}
    raw_pages = [page for page in audit.get("pages") or [] if isinstance(page, dict)]
    lookup = _evidence_lookup(evidence_pages or [])
    pages = [_present_page(page, _page_evidence(page, lookup)) for page in raw_pages]

    evaluated_checks = [
        check for page in pages for check in page.get("checks") or []
        if check.get("status") in ("passed", "failed")
    ]
    possible = sum(check["weight"] for check in evaluated_checks)
    earned = sum(check["weight"] for check in evaluated_checks if check["status"] == "passed")
    applicable_avg = round(earned / possible * 100, 1) if possible else None
    distribution = {grade: sum(page.get("applicable_grade") == grade for page in pages) for grade in "ABCD"}
    distribution["excluded"] = sum(page.get("evaluation_status") == "excluded" for page in pages)

    block_gap = []
    for name in ("definition", "numeric_facts", "comparison", "steps", "faq"):
        rows = [
            check for page in pages for check in page.get("checks") or []
            if check.get("id") == name and check.get("status") in ("passed", "failed")
        ]
        if rows:
            block_gap.append({
                "block": name,
                "label": BLOCK_LABELS[name],
                "missing_pages": sum(item["status"] == "failed" for item in rows),
                "total": len(rows),
            })

    site = {**(audit.get("site") if isinstance(audit.get("site"), dict) else {})}
    if isinstance(site_data, dict) and site_data:
        site.update(site_data)
    coverage = audit.get("language_coverage") if isinstance(audit.get("language_coverage"), dict) else {}
    site_findings = _site_findings(site, coverage, len(pages))
    return {
        "presentation_version": 1,
        "score_method": "Weighted coverage of evidence-backed checks applicable to each inferred page role.",
        "slug": audit.get("slug"),
        "audited_at": audit.get("audited_at"),
        "market": audit.get("market"),
        "site": site,
        "language_coverage": coverage,
        "site_findings": site_findings,
        "site_issues": [item["title"] for item in site_findings],
        "page_count": len(pages),
        "raw_avg_score": audit.get("avg_score"),
        "raw_grade_distribution": audit.get("grade_distribution") or {},
        "avg_score": audit.get("avg_score"),
        "grade_distribution": audit.get("grade_distribution") or {},
        "applicable_avg_score": applicable_avg,
        "applicable_grade": _grade(applicable_avg),
        "applicable_grade_distribution": distribution,
        "block_gap": block_gap,
        "pages": sorted(
            pages,
            key=lambda page: (
                page.get("applicable_score") is None,
                page.get("applicable_score") if page.get("applicable_score") is not None else 101,
                str(page.get("url") or ""),
            ),
        ),
        "check_summary": {
            "evaluated": len(evaluated_checks),
            "passed": sum(item["status"] == "passed" for item in evaluated_checks),
            "failed": sum(item["status"] == "failed" for item in evaluated_checks),
            "not_evaluated": sum(
                check.get("status") == "not_evaluated"
                for page in pages for check in page.get("checks") or []
            ),
            "not_applicable": sum(
                check.get("status") == "not_applicable"
                for page in pages for check in page.get("checks") or []
            ),
            "excluded_pages": distribution["excluded"],
        },
    }


def present_audit(project_slug):
    """Load project artifacts and return their role-aware presentation."""
    directory = geolib.project_dir(project_slug)
    audit = geolib.read_json(directory / "audit.json", {}) or {}
    pages = geolib.read_jsonl(directory / "evidence" / "pages.jsonl")
    site = geolib.read_json(directory / "evidence" / "site.json", {}) or {}
    return present_audit_data(audit, pages, site)
