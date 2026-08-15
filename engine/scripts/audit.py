"""Score page-level GEO signals using the citation-lab reference findings.

The scoring model uses observational associations for prioritization, not as
universal causal claims. Output: ``work/<slug>/audit.json``.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

import geolib as G

# ------------------------------------------------------------ Extraction blocks

RE_DEFINITION = re.compile(
    r"(\u662f\u4e00[\u6b3e\u79cd\u4e2a\u5bb6\u7c7b]|\u662f\u6307|\u6307\u7684\u662f|\u5b9a\u4e49\u4e3a|\u5168\u79f0[\u4e3a\u662f]|\u53c8\u79f0|\u7b80\u79f0\u4e3a?|\u5c5e\u4e8e\u4e00[\u79cd\u7c7b]"
    r"|\bis an? \w+|\brefers to\b|\bis defined as\b|\bstands for\b)"
)
RE_NUMBER = re.compile(
    r"\d[\d,\.]*\s*(%|\uff05|\u4e07|\u4ebf|\u5343|\u500d|\u5143|\u7f8e\u5143|\u4eba|\u5bb6|\u4e2a|\u5929|\u5c0f\u65f6|\u5206\u949f|\u79d2|\u6b21|\u6761|\u6b3e|\u5e74|\u6708|"
    r"percent|x\b|hours?|days?|users?|customers?)"
)
RE_COMPARE = re.compile(
    r"(\u5bf9\u6bd4|\u76f8\u6bd4|\u533a\u522b|\u5dee\u5f02|\u4f18\u4e8e|\u4e0d\u5982|\u7ade\u54c1|\u66ff\u4ee3|\u9009\u578b|\u54ea\u4e2a\u597d|\bvs\.?\b|\bversus\b|\balternatives?\b)",
    re.I,
)
RE_HOWTO = re.compile(
    r"(\u7b2c[\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341\d]+\u6b65|\u6b65\u9aa4\s*[\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341\d]|\u64cd\u4f5c\u6d41\u7a0b|\bstep\s*\d|\bhow to\b)",
    re.I,
)
# Soft how-to terms count only when list structure is also present.
RE_HOWTO_SOFT = re.compile(r"(\u5982\u4f55|\u600e\u4e48)")
# Low-content utility pages are not treated as SPA shells.
FUNC_PAGE = re.compile(r"/(login|signin|signup|register|cart|checkout|account|auth)(/|$)", re.I)
CONTACT_PAGE = re.compile(r"/(contact|contact-us|get-in-touch)(/|$)", re.I)
LEGAL_PAGE = re.compile(r"/(privacy|terms|legal|cookies?|gdpr|imprint|disclaimer)(/|$)", re.I)
RE_FAQ = re.compile(
    r"(\u5e38\u89c1\u95ee\u9898|\u5e38\u89c1\u7591\u95ee|\u95ee\u7b54|\bFAQ\b|^\s*[\u95eeQ][:\uff1a]|\u7b54[:\uff1a])",
    re.I | re.M,
)
RE_DATE = re.compile(
    r"(20\d{2}[-/\u5e74]\s?\d{1,2}[-/\u6708]\s?\d{1,2}|\u66f4\u65b0[\u4e8e\u65f6\u95f4]*[:\uff1a]?\s*20\d{2}|\u6700\u540e\u66f4\u65b0|\u53d1\u5e03\u4e8e|\bupdated\b|\bpublished\b)",
    re.I,
)
RE_AUTHOR = re.compile(r"(\u4f5c\u8005|\u64b0\u6587|\u7f16\u8f91[:\uff1a]|\bauthor\b|\bby\s+[A-Z][a-z]+)", re.I)

AUTHORITY_SCHEMA = {
    "Organization", "Corporation", "Product", "SoftwareApplication", "Service",
    "FAQPage", "Article", "TechArticle", "NewsArticle", "BlogPosting",
    "HowTo", "BreadcrumbList", "WebSite", "Review", "AggregateRating", "Offer",
}


def band(value: float, stops: list[tuple[float, float]]) -> float:
    """Return the ratio for the first descending threshold that matches."""
    for threshold, ratio in stops:
        if value >= threshold:
            return ratio
    return 0.0


def jsonld_has_key(obj, keys: set[str]) -> bool:
    """Recursively inspect JSON-LD keys, including properties outside @type."""
    if isinstance(obj, dict):
        return any(k in keys or jsonld_has_key(v, keys) for k, v in obj.items())
    if isinstance(obj, list):
        return any(jsonld_has_key(x, keys) for x in obj)
    return False


def page_role(page: dict) -> str:
    path = urlparse(page.get("url") or "").path
    if FUNC_PAGE.search(path):
        return "utility"
    if CONTACT_PAGE.search(path):
        return "contact"
    if LEGAL_PAGE.search(path):
        return "legal"
    if path.rstrip("/") in ("",):
        return "home"
    if re.search(r"/(blog|news|articles?|insights?)(/|$)", path, re.I):
        return "editorial"
    if re.search(r"/(help|support|docs?|faq|guides?|tutorials?)(/|$)", path, re.I):
        return "support"
    return "content"


def _unscored_page(page: dict, role: str) -> dict:
    """Report utility-page evidence without normalizing sparse checks into a score."""
    status = page.get("status") or 0
    issues, codes = [], []
    if status != 200:
        codes.append("PAGE_UNREACHABLE" if not status or status >= 400 else "NON_200_STATUS")
        issues.append("P0 Page is not reliably accessible" if not status or status >= 400
                      else "P1 Page did not return HTTP 200")
    if "noindex" in (page.get("meta_robots") or "").lower():
        codes.append("NOINDEX")
        issues.append("P0 Page is excluded by noindex")
    if not page.get("canonical"):
        codes.append("NO_CANONICAL")
        issues.append("P2 Missing canonical URL")
    if page.get("word_count", 0) < 120:
        codes.append("LOW_CONTENT_PAGE")
        issues.append("Low-content utility page; excluded from public-content scoring")
    return {
        "url": page.get("url"), "title": page.get("title", "")[:120],
        "word_count": page.get("word_count", 0), "score": None, "grade": "N/A",
        "scored": False, "evaluation_status": "not_scored", "role": role,
        "evaluated_checks": 3, "minimum_evaluated_checks": 8,
        "dimensions": {},
        "blocks": {"definition": None, "numeric_facts": None, "comparison": None,
                   "steps": None, "faq": None},
        "jsonld_types": sorted(set(page.get("jsonld_types", []))),
        "issues": issues, "issue_codes": codes,
    }


def score_page(page: dict, keywords: list[str]) -> dict:
    role = page_role(page)
    if role in ("utility", "contact", "legal"):
        return _unscored_page(page, role)
    text = page.get("text", "") or ""
    wc = page.get("word_count", 0)
    h1, h2 = page.get("h1", []), page.get("h2", [])
    paras = page.get("para_count", 0)
    lis = page.get("li_count", 0)
    types = set(page.get("jsonld_types", []))

    issues: list[str] = []
    issue_codes: list[str] = []

    def issue(code: str, msg: str):
        issue_codes.append(code)
        issues.append(msg)

    d: dict[str, float] = {}

    # 1. Crawlability: 15 points
    s = 0.0
    status = page.get("status") or 0
    if status == 200:
        s += 7
    elif 200 < status < 400:
        s += 3
        issue("NON_200_STATUS", "P1 Page returned a non-200 status; some crawlers may stop processing it")
    else:
        issue("PAGE_UNREACHABLE", "P0 Page is inaccessible to AI crawlers")
    if "noindex" not in (page.get("meta_robots") or "").lower():
        s += 3
    else:
        issue("NOINDEX", "P0 Meta robots contains noindex, excluding the page from retrieval")
    if page.get("canonical"):
        s += 2
    else:
        issue("NO_CANONICAL", "P2 Missing canonical URL can dilute duplicate-content signals")
    if wc >= 120:
        s += 3
    elif FUNC_PAGE.search(urlparse(page.get("url") or "").path):
        issue("LOW_CONTENT_PAGE", "P2 Low-content utility page; add explanatory copy only when useful")
    else:
        issue("SPA_SHELL", "P0 Static HTML contains almost no body text; AI crawlers cannot read the content")
    d["crawlability"] = s

    # 2. Content depth: 15 points
    r = band(wc, [(1500, 1.0), (1000, 0.85), (600, 0.6), (300, 0.35), (120, 0.15)])
    d["content_depth"] = 15 * r
    if wc < 1000:
        issue("SHORT_CONTENT", "P1 Content depth is below the reference range; expand evidence to match page intent")

    # 3. Structure: 20 points
    s = 0.0
    if len(h1) == 1:
        s += 4
    else:
        issue("BAD_H1", "P1 Page must have exactly one H1 to provide a clear topic signal")
    s += 6 * band(len(h2), [(8, 1.0), (6, 0.85), (4, 0.6), (2, 0.3)])
    if len(h2) < 6:
        issue("FEW_H2", "P1 Section structure is shallow; organize clear sections around page intent")
    s += 5 * band(paras, [(40, 1.0), (25, 0.8), (15, 0.55), (8, 0.3)])
    density = lis / max(paras + lis, 1)
    s += 5 * band(density, [(0.35, 1.0), (0.2, 0.75), (0.1, 0.45), (0.03, 0.2)])
    if density < 0.1:
        issue("LOW_LIST_DENSITY", "P1 Low list density; use semantic lists for genuinely list-like information")
    d["structure"] = s

    # 4. Extractable blocks: 25 points
    has = {
        "definition": bool(RE_DEFINITION.search(text)),
        "numeric_facts": len(RE_NUMBER.findall(text)) >= 3,
        "comparison": bool(RE_COMPARE.search(text)) or page.get("table_count", 0) >= 1,
        "steps": bool(RE_HOWTO.search(text)) or (bool(RE_HOWTO_SOFT.search(text)) and lis >= 3),
        "faq": bool(RE_FAQ.search(text)) or "FAQPage" in types,
    }
    block_codes = {"definition": "NO_DEFINITION", "numeric_facts": "NO_NUMBERS",
                   "comparison": "NO_COMPARISON", "steps": "NO_HOWTO", "faq": "NO_FAQ"}
    weights = {"definition": 6, "numeric_facts": 6, "comparison": 5, "steps": 5, "faq": 3}
    d["extractability"] = sum(w for k, w in weights.items() if has[k])
    for k, ok in has.items():
        if not ok:
            issue(block_codes[k], f"P1 Missing {k} block; reference data shows an association that must be validated by page role")

    # 5. Authority signals: 15 points
    s = 0.0
    if RE_DATE.search(text) or jsonld_has_key(page.get("jsonld_raw"), {"dateModified", "datePublished"}):
        s += 4
    else:
        issue("NO_DATE", "P1 No visible publication or update date; freshness cannot be assessed")
    if RE_AUTHOR.search(text):
        s += 2
    ext = page.get("external_links", 0)
    s += 4 * band(ext, [(6, 1.0), (3, 0.7), (1, 0.4)])
    if ext < 3:
        issue("FEW_EXTERNAL_LINKS", "P2 Few external sources; the evidence chain is weak")
    hit_schema = types & AUTHORITY_SCHEMA
    s += 5 * band(len(hit_schema), [(3, 1.0), (2, 0.75), (1, 0.45)])
    if not hit_schema:
        issue("NO_JSONLD", "P0 Missing JSON-LD structured data for machine-readable entity context")
    d["authority"] = s

    # 6. Query alignment: 10 points
    surface = " ".join([page.get("title", "")] + h1 + h2).lower()
    hits = [k for k in keywords if k and k.lower() in surface]
    cover = len(hits) / max(len(keywords), 1) if keywords else 0
    d["query_alignment"] = 10 * band(cover, [(0.4, 1.0), (0.25, 0.8), (0.12, 0.55), (0.04, 0.3)])
    if cover < 0.12:
        issue("LOW_RELEVANCE", "P1 Headings have weak target-query alignment; the reference association is not a guaranteed lift")

    total = round(sum(d.values()), 1)
    return {
        "url": page.get("url"),
        "title": page.get("title", "")[:120],
        "word_count": wc,
        "score": total,
        "grade": "A" if total >= 80 else "B" if total >= 65 else "C" if total >= 45 else "D",
        "dimensions": {k: round(v, 1) for k, v in d.items()},
        "blocks": has,
        "jsonld_types": sorted(types),
        "issues": issues,
        "issue_codes": issue_codes,
        "scored": True,
        "evaluation_status": "scored",
        "role": role,
        "evaluated_checks": 19,
        "minimum_evaluated_checks": 8,
    }


def keywords_from_config(cfg: dict) -> list[str]:
    b = cfg.get("brand", {})
    # Brand terms do not count as evidence of target-query alignment.
    brand_terms = set()
    for k in [b.get("name")] + list(b.get("aliases", []) or []) + list(b.get("products", []) or []):
        if k:
            brand_terms.add(str(k).lower())
    kws: list[str] = []
    for q in cfg.get("questions", []):
        text = str(q.get("text") or "")
        for term in sorted(brand_terms, key=len, reverse=True):
            text = re.sub(re.escape(term), " ", text, flags=re.I)
        for token in G.relevance_tokens(text):
            if token.lower() not in brand_terms and token not in kws:
                kws.append(token)
    return kws[:40]


def run(slug: str) -> dict:
    cfg = G.load_config(slug)
    pdir = G.project_dir(slug)
    pages = G.read_jsonl(pdir / "evidence" / "pages.jsonl")
    if not pages:
        G.die("Missing crawl results. Run crawl first: python3 scripts/geo.py crawl --slug " + slug)
    site = G.read_json(pdir / "evidence" / "site.json", {})
    kws = keywords_from_config(cfg)

    results = [score_page(p, kws) for p in pages]
    # Average only successfully fetched, scored pages, including zero scores.
    ok = [r for r, p in zip(results, pages)
          if (p.get("status") or 0) == 200 and r.get("scored") and r.get("score") is not None]
    avg = round(sum(r["score"] for r in ok) / len(ok), 1) if ok else None

    # Language coverage is kept separate across markets.
    market = cfg.get("market", "cn")
    lang_dist: dict[str, int] = {}
    for p in pages:
        if p.get("word_count", 0) >= 120:
            # Recompute language from content because stored evidence may be stale.
            if p.get("text"):
                lang = G.page_language(p["text"], p.get("lang", ""))
            else:
                lang = p.get("language", "unknown")
            lang_dist[lang] = lang_dist.get(lang, 0) + 1
    # Mixed-language pages remain separate to avoid double counting.
    en_pages = lang_dist.get("en", 0)
    zh_pages = lang_dist.get("zh", 0)
    ja_pages = lang_dist.get("ja", 0)

    # Site-level issues
    site_issues = []
    if market in ("global", "both") and en_pages == 0:
        site_issues.append(
            "P0 No native English content pages were found; establish and measure a global-market baseline")
    if market in ("cn", "both") and zh_pages == 0:
        site_issues.append("P0 No Chinese content pages were found for the domestic market")
    if market == "both" and en_pages and zh_pages and abs(en_pages - zh_pages) > max(en_pages, zh_pages) * 0.7:
        thin = "English" if en_pages < zh_pages else "Chinese"
        site_issues.append(f"P1 Chinese and English content are imbalanced (Chinese {zh_pages} / English {en_pages}); {thin} coverage is weaker")
    if site.get("ai_bots_blocked"):
        site_issues.append("P0 robots.txt blocks these AI crawlers: " + ", ".join(site["ai_bots_blocked"]))
    if not site.get("has_sitemap"):
        site_issues.append("P0 Missing sitemap.xml reduces discovery efficiency and coverage")
    if not site.get("has_llms_txt"):
        site_issues.append("P2 Missing /llms.txt official facts index")
    grade_dist = {g: sum(1 for r in results if r["grade"] == g) for g in "ABCD"}
    grade_dist["not_scored"] = sum(not r.get("scored", True) for r in results)

    # Aggregate the most common sitewide extraction gaps.
    gap = {}
    for r in results:
        if not r.get("scored", True):
            continue
        for k, v in r["blocks"].items():
            gap.setdefault(k, 0)
            gap[k] += 0 if v else 1
    block_gap = sorted(gap.items(), key=lambda x: -x[1])

    out = {
        "slug": slug,
        "audited_at": G.now_iso(),
        "market": market,
        "site": site,
        "language_coverage": {"distribution": lang_dist, "zh_pages": zh_pages,
                              "en_pages": en_pages, "ja_pages": ja_pages},
        "site_issues": site_issues,
        "keywords_used": kws,
        "page_count": len(results),
        "avg_score": avg,
        "grade_distribution": grade_dist,
        "block_gap": [{"block": k, "missing_pages": v, "total": len(results)} for k, v in block_gap],
        "scored_page_count": len(ok),
        "pages": sorted(results, key=lambda r: (r.get("score") is None, r.get("score") or 0)),
    }
    G.write_json(pdir / "audit.json", out)
    G.info(f"Audit complete: {len(results)} pages, avg score {avg}, grade distribution {grade_dist} → {pdir/'audit.json'}")
    return out


if __name__ == "__main__":
    import sys

    run(sys.argv[1])
