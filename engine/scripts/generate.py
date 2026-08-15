"""Generate deployable assets and reviewable content drafts.

Deterministic code produces structured assets under work/<slug>/assets/.
Configured LLM providers may draft prose from generated outlines.
"""

from __future__ import annotations

import html
import json
import re
from functools import lru_cache
from pathlib import Path

import geolib as G

PLACEHOLDER_RE = re.compile(
    r"pending_confirmation|<\u586b|\u5f85\u8865|\u5f85\u786e\u8ba4|<YYYY|<path>|\b(?:TODO|TBD)\b",
    re.I,
)
HAN_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
LOCALE_DIR = Path(__file__).resolve().parent.parent / "locales"

EN_LOCALE = {
    "llms": {
        "key_facts": "Key facts", "website": "Website", "aliases": "Also known as",
        "industry": "Industry", "target_users": "For", "important_pages": "Important pages",
        "scope": "Scope", "good_fit": "Good fit", "not_a_fit": "Not a fit",
        "disambiguation": "Disambiguation", "canonical_name": "Canonical name",
        "parent": "Parent", "default_disambiguation":
            "Not related to similarly-named products in other industries.",
        "source_reference": "{value} ({source})",
    },
    "definition": {
        "note": "Definition block: deploy only after factual review.",
        "heading_suffix": ": what it is",
        "discipline": "Keep this wording consistent with llms.txt, JSON-LD, and the About page.",
    },
    "faq": {
        "note": "FAQ answers must be fact-checked and visible in static HTML.",
        "heading": "FAQ",
    },
    "outline_templates": {
        "definition": [
            "What is {topic}?", "What does {topic} include?", "Key numbers with a source for every row",
            "How does {topic} compare with {alt}?", "Who is {topic} for and not for?",
            "How to get started with {topic}", "Frequently asked questions", "Sources",
        ],
        "comparison": [
            "Decision summary", "Comparison criteria and scope", "Core comparison table",
            "Limitations of each option", "Scenario-based decision guide", "Pricing and total cost",
            "Frequently asked questions", "Sources and verification date",
        ],
        "listicle": [
            "Methodology, sources, and disclosures", "Summary ranking table",
            "Individual reviews with positioning, strengths, limits, and fit", "How to choose",
            "Frequently asked questions", "Sources",
        ],
        "tutorial": [
            "Problem and outcome", "Prerequisites", "Numbered procedure with screenshot positions",
            "Common errors and troubleshooting", "Advanced guidance", "Related concepts",
            "Frequently asked questions", "Sources",
        ],
    },
    "alternative": "alternatives",
    "titles": {
        "dated": "{question} - a practical guide ({year})",
        "details": "{question}: comparison, evidence, and steps",
        "boundary": "{question}: the {brand} answer and its limits",
    },
    "outline_document": {
        "title": "Content Outline - {question}",
        "meta": "Target question ID: `{question_id}` | Market: {market} | Type: {type}",
        "title_candidates": "Title Candidates",
        "sections": "Section Outline",
        "requirements": "Requirements",
        "min_words": "Body >= {min_words} words; H2 sections >= {min_h2}",
        "blocks": "Required extraction blocks: {blocks}",
        "list_density": "List density {density}",
        "evidence": "Evidence: {evidence}",
        "facts": "Verified Facts Available",
        "block_separator": ", ",
    },
    "draft_review_comment": "Draft; verify every fact before publication",
}


@lru_cache(maxsize=2)
def _locale(lang: str) -> dict:
    if lang != "zh":
        return EN_LOCALE
    path = LOCALE_DIR / "zh-CN" / "generate.json"
    return json.loads(path.read_text("utf-8"))

# ---------------------------------------------------------------- Fact parsing

def parse_facts(slug: str) -> dict:
    """Parse structured facts from content/facts.md."""
    p = G.project_dir(slug) / "content" / "facts.md"
    if not p.exists():
        return {}
    text = p.read_text("utf-8")
    out = {"definition": "", "numbers": [], "suitable": [], "unsuitable": [], "raw": text}

    m = re.search(r"##\s*Canonical Definition.*?\n(.*?)(?=\n##|\Z)", text, re.S | re.I)
    if m:
        body = m.group(1)
        quoted = [l.strip()[1:].strip() for l in body.split("\n") if l.strip().startswith(">")]
        if quoted:
            line = " ".join(quoted)
        else:
            line = next((l.strip() for l in body.split("\n")
                         if l.strip() and not l.strip().startswith(("#", "-", "|"))), "")
        line = re.sub(r"\*\*(.+?)\*\*", r"\1", line)
        line = re.sub(r"`(.+?)`", r"\1", line)
        line = re.sub(r"\s+", " ", line).strip()
        CJK = r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3000-\u303f\uff00-\uffef]"
        out["definition"] = re.sub(rf"(?<={CJK}) (?={CJK})", "", line)

    m = re.search(r"##\s*Key Numbers.*?\n(.*?)(?=\n##|\Z)", text, re.S | re.I)
    if m:
        for row in re.findall(r"^\|([^|\n]+)\|([^|\n]+)\|([^|\n]+)\|([^|\n]*)\|", m.group(1), re.M):
            a, b, c, evidence = (x.strip() for x in row)
            if a and a.casefold() not in ("fact", "field", "---") and not set(a) <= set("-: "):
                if not PLACEHOLDER_RE.search(" ".join((a, b, c))):
                    out["numbers"].append({"fact": a, "value": b, "source": c,
                                           "evidence": evidence})

    m = re.search(r"\*\*Good fit\*\*\s*:?(.*?)(?=\*\*Not a fit|##|\Z)", text, re.S | re.I)
    if m:
        out["suitable"] = [l.strip("- ").strip() for l in m.group(1).split("\n") if l.strip().startswith("-")]
    m = re.search(r"\*\*Not a fit\*\*\s*:?(.*?)(?=\n##|\Z)", text, re.S | re.I)
    if m:
        out["unsuitable"] = [l.strip("- ").strip() for l in m.group(1).split("\n") if l.strip().startswith("-")]
    return out


def _language_text(value, lang: str) -> str:
    text = str(value or "").strip()
    if not text or PLACEHOLDER_RE.search(text):
        return ""
    if lang == "en" and HAN_RE.search(text):
        return ""
    return text


def _definition(cfg: dict, facts: dict, lang: str) -> str:
    brand = cfg.get("brand") or {}
    if lang == "en":
        return _language_text(brand.get("definition_en"), "en") or _language_text(facts.get("definition"), "en")
    return _language_text(brand.get("definition_zh"), "zh") or _language_text(facts.get("definition"), "zh")


def _answer_for(question: dict, lang: str) -> str:
    value = question.get("answer_en") if lang == "en" else question.get("answer_zh")
    return _language_text(value or question.get("answer"), lang)


# ---------------------------------------------------------------- llms.txt

def gen_llms_txt(slug: str, lang: str = "zh") -> str:
    cfg = G.load_config(slug)
    f = parse_facts(slug)
    b = cfg["brand"]
    audit = G.read_json(G.project_dir(slug) / "audit.json", {})
    pages = sorted(audit.get("pages", []), key=lambda p: -p["score"])[:12]

    strings = _locale(lang)["llms"]
    definition = _definition(cfg, f, lang)
    display_name = _language_text(b.get("name_en") or b["name"], lang)
    if not display_name:
        display_name = b["site"].split("//")[-1].split("/", 1)[0]
    L = [f"# {display_name}", ""]
    if definition:
        L.append(f"> {definition}")
    L += ["", f"## {strings['key_facts']}", ""]
    L.append(f"- {strings['website']}: {b['site']}")
    aliases = [_language_text(value, lang) for value in b.get("aliases", [])]
    aliases = [value for value in aliases if value]
    if aliases:
        L.append(f"- {strings['aliases']}: {strings.get('list_separator', ', ').join(aliases)}")
    industry = _language_text(b.get("industry_en") or b.get("industry"), lang)
    target_users = _language_text(b.get("target_users_en") or b.get("target_users"), lang)
    if industry:
        L.append(f"- {strings['industry']}: {industry}")
    if target_users:
        L.append(f"- {strings['target_users']}: {target_users}")
    for n in f.get("numbers", [])[:8]:
        fact = _language_text(n["fact"], lang)
        value = _language_text(n["value"], lang)
        if fact and value:
            rendered = strings["source_reference"].format(value=value, source=n["source"]) if n.get("source") else value
            L.append(f"- {fact}: {rendered}")

    L += ["", f"## {strings['important_pages']}", ""]
    for p in pages:
        title = _language_text((p.get("title") or "").split("|")[0].split("\uff5c")[0].strip()[:60], lang) or p["url"]
        L.append(f"- [{title}]({p['url']})")

    if f.get("suitable") or f.get("unsuitable"):
        L += ["", f"## {strings['scope']}", ""]
        for s in f.get("suitable", [])[:5]:
            value = _language_text(s, lang)
            if value:
                L.append(f"- {strings['good_fit']}: {value}")
        for s in f.get("unsuitable", [])[:5]:
            value = _language_text(s, lang)
            if value:
                L.append(f"- {strings['not_a_fit']}: {value}")

    L += ["", f"## {strings['disambiguation']}", "",
          f"- {strings['canonical_name']}: {display_name}"]
    if b.get("parent"):
        parent = _language_text(b["parent"], lang)
        if parent:
            L.append(f"- {strings['parent']}: {parent}"
                     + (f" ({b['parent_url']})" if b.get("parent_url") else ""))
    for line in (b.get("disambiguation") or []):
        value = _language_text(line, lang)
        if value:
            L.append(f"- {value}")
    if not b.get("disambiguation"):
        L.append(f"- {strings['default_disambiguation']}")
    L += ["", f"<!-- generated by geo skill · {G.today()} -->"]
    return "\n".join(L)


# ---------------------------------------------------------------- JSON-LD

def gen_jsonld(slug: str) -> dict[str, dict]:
    cfg = G.load_config(slug)
    f = parse_facts(slug)
    b = cfg["brand"]
    desc = _definition(cfg, f, "zh") or _definition(cfg, f, "en")
    site = b["site"].rstrip("/")

    org = {
        "@context": "https://schema.org", "@type": "Organization",
        "name": b["name"], "url": site,
    }
    if desc:
        org["description"] = desc
    if b.get("aliases"):
        org["alternateName"] = b["aliases"]
    same_as = [value for value in (b.get("same_as") or [])
               if isinstance(value, str) and value.startswith(("http://", "https://"))]
    if same_as:
        org["sameAs"] = same_as
    if b.get("parent"):
        org["parentOrganization"] = {"@type": "Organization", "name": b["parent"],
                                     **({"url": b["parent_url"]} if b.get("parent_url") else {})}
    if b.get("founding_date"):
        org["foundingDate"] = b["founding_date"]
    if b.get("knows_about"):
        org["knowsAbout"] = b["knows_about"]

    out = {"organization": org}
    if b.get("application_category"):
        app = {
            "@context": "https://schema.org", "@type": "SoftwareApplication",
            "name": b["name"], "url": site,
            "applicationCategory": b["application_category"],
            "operatingSystem": b.get("operating_system", "Web"),
            "publisher": {"@type": "Organization", "name": b.get("parent") or b["name"]},
        }
        if desc:
            app["description"] = desc
        offers = b.get("offers") or []
        out_offers = []
        for o in offers:
            price, currency = str(o.get("price") or "").strip(), str(o.get("currency") or "").strip()
            if not price or not currency or PLACEHOLDER_RE.search(price + currency):
                continue
            item = {"@type": "Offer", "name": o.get("name", ""), "price": price,
                    "priceCurrency": currency}
            if o.get("desc"):
                item["description"] = o["desc"]
            out_offers.append(item)
        if out_offers:
            app["offers"] = out_offers
        if b.get("audience"):
            app["audience"] = {"@type": "Audience", "audienceType": b["audience"]}
        out["software-application"] = app

    faq_entities = []
    for q in G.normalize_question_ids(cfg.get("questions", [])):
        qlang = "zh" if q.get("market") == "cn" else "en"
        answer = _answer_for(q, qlang)
        question = _language_text(q.get("text"), qlang)
        if answer and question:
            faq_entities.append({"@type": "Question", "name": question,
                                 "acceptedAnswer": {"@type": "Answer", "text": answer}})
    if faq_entities:
        out["faq-page"] = {"@context": "https://schema.org", "@type": "FAQPage",
                           "mainEntity": faq_entities[:8]}
    return out


# ---------------------------------------------------------------- HTML snippets

def gen_definition_block(slug: str, lang: str = "zh") -> str:
    f = parse_facts(slug)
    cfg = G.load_config(slug)
    b = cfg["brand"]
    d = _definition(cfg, f, lang)
    if not d:
        return ""
    nums = [n for n in f.get("numbers", [])
            if _language_text(n.get("fact"), lang) and _language_text(n.get("value"), lang)][:4]
    strings = _locale(lang)["definition"]
    items = "".join(f'\n    <li><strong>{html.escape(n["value"])}</strong> — {html.escape(n["fact"])}</li>'
                    for n in nums)
    dis = [value for value in (_language_text(x, lang) for x in (b.get("disambiguation") or [])) if value]
    dis_html = ("\n  <p class=\"geo-disambiguation\"><small>"
                + " ".join(html.escape(x) for x in dis) + "</small></p>") if dis else ""
    display_name = _language_text(b.get("name_en") or b["name"], lang)
    if not display_name:
        return ""
    return f"""<!-- {strings['note']} -->
<section class="geo-definition">
  <h2>{html.escape(display_name)}{strings['heading_suffix']}</h2>
  <p>{html.escape(d)}</p>
  <ul>{items}
  </ul>{dis_html}
</section>
<!-- {strings['discipline']} -->"""


def gen_faq_block(slug: str, lang: str = "zh") -> str:
    cfg = G.load_config(slug)
    mk = "cn" if lang == "zh" else "global"
    qs = [(q, _language_text(q.get("text"), lang), _answer_for(q, lang))
          for q in G.normalize_question_ids(cfg.get("questions", []))
          if q.get("market") in (mk, "both")]
    qs = [(q, question, answer) for q, question, answer in qs if question and answer][:8]
    if not qs:
        return ""
    body = "\n".join(
        f"""  <details open>
    <summary><h3>{html.escape(question)}</h3></summary>
    <p>{html.escape(answer)}</p>
  </details>""" for q, question, answer in qs)
    strings = _locale(lang)["faq"]
    return f"""<!-- {strings['note']} -->
<section class="geo-faq">
  <h2>{strings['heading']}</h2>
{body}
</section>"""


# ---------------------------------------------------------------- Content outlines

GROUP2TYPE = {
    "recommendation": "listicle", "comparison": "comparison", "alternative": "comparison",
    "pricing": "definition", "risk": "definition", "brand_verification": "definition",
    "scenario": "tutorial",
}


def gen_outlines(slug: str) -> list[dict]:
    cfg = G.load_config(slug)
    f = parse_facts(slug)
    b = cfg["brand"]
    comps = [c["name"] for c in cfg.get("competitors", [])
             if c.get("confirmed") is not False]
    out = []
    for q in G.normalize_question_ids(cfg.get("questions", [])):
        typ = GROUP2TYPE.get(q.get("group", ""), "definition")
        mk = q.get("market", cfg.get("market", "cn"))
        lang = "zh" if mk == "cn" else "en"
        strings = _locale(lang)
        alt = comps[0] if comps else strings["alternative"]
        secs = [s.format(topic=b["name"], alt=alt) for s in strings["outline_templates"][typ]]
        out.append({
            "question_id": q.get("id"), "market": mk, "type": typ,
            "target_question": q["text"],
            "title_candidates": _titles(q["text"], b["name"], mk),
            "sections": secs,
            "requirements": {
                "min_words": 1200 if typ in ("comparison", "listicle") else 1000,
                "min_h2": 8, "list_density": ">=0.35",
                "must_have_blocks": ["definition", "numeric_facts", "comparison", "steps", "faq"],
                "evidence": "Every number requires a source and verification date; omit unsupported claims.",
            },
            "facts_to_use": [n["fact"] + ": " + n["value"] for n in f.get("numbers", [])[:5]],
        })
    return out


def _titles(question: str, brand: str, market: str) -> list[str]:
    """Keep the target question wording in every title candidate."""
    q = question.rstrip("\uff1f?").strip()
    strings = _locale("zh" if market == "cn" else "en")["titles"]
    return [q, strings["dated"].format(question=q, year=G.today()[:4]),
            strings["details"].format(question=q),
            strings["boundary"].format(question=q, brand=brand)]


# ---------------------------------------------------------------- LLM drafts

def draft(slug: str, outline: dict, provider: str | None = None) -> str:
    """Draft an article from an outline using the first configured LLM."""
    import sample as S

    plat = S.pick_llm(provider)
    if not plat:
        return ""
    cfg = G.load_config(slug)
    f = parse_facts(slug)
    b = cfg["brand"]
    language = "Simplified Chinese" if outline["market"] != "global" else "English"
    facts = "\n".join(f"- {x}" for x in outline["facts_to_use"]) or (
        "No structured facts are available. Write only general content and do not invent brand data."
    )
    secs = "\n".join(f"{i+1}. {s}" for i, s in enumerate(outline["sections"]))
    req = outline["requirements"]
    mk = outline["market"]
    comps = [c["name"] for c in cfg.get("competitors", [])
             if (c.get("market") in (mk, "both", None) or mk == "both")
             and c.get("confirmed") is not False]
    comp_rule = (
        "Mention only these verified competitors. Never invent another product name:\n"
        + "\n".join(f"- {c}" for c in comps)
        if comps else
        "No competitor list has been confirmed. Do not name any competitor; compare only with generic categories."
    )
    prompt = (
        f"""You are a generative-engine optimization content engineer. Write a publication-ready article in {language} from the outline below.

Current year: {G.today()[:4]}. Use this year whenever a current year is required.

Target question: {outline['target_question']}
Article type: {outline['type']}
Brand: {b['name']} ({b.get('industry', '')})

Verified facts. Preserve every value exactly and do not invent new data:
{facts}

Competitor constraints:
{comp_rule}

Section outline:
{secs}

Requirements:
- At least {req['min_words']} words and {req['min_h2']} H2 sections
- Include a quotable definition, supported numeric facts, a comparison table, numbered steps, and FAQ
- Prefer scannable ordered or unordered lists over long paragraphs
- State both good-fit and poor-fit boundaries
- Never invent customer names, prices, credentials, market data, or competitor attributes
- Omit unavailable claims instead of using fake values or placeholders
- Return only the Markdown article"""
    )
    res = S.ask(plat, prompt, timeout=300)
    return res.get("answer", "") if res.get("ok") else ""


# ---------------------------------------------------------------- Draft risk checks

FAKE_HINTS = [
    (r"\u5de5\u5177\s*[A-Z\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341]\b", "placeholder_product_name"),
    (r"\u67d0\u67d0|XX\u516c\u53f8|xxx\u516c\u53f8|\u793a\u4f8b\u516c\u53f8", "placeholder_company_name"),
    (r"(?i)\b(acme|foobar|example corp|competitor [a-z])\b", "placeholder_english_brand"),
]


def lint_draft(slug: str, path: Path) -> list[dict]:
    """Flag likely fabrication and unsupported numeric claims before delivery."""
    import re as _re

    cfg = G.load_config(slug)
    f = parse_facts(slug)
    text = path.read_text("utf-8")
    known = {cfg["brand"]["name"], *cfg["brand"].get("aliases", [])}
    known |= {c["name"] for c in cfg.get("competitors", [])}
    for c in cfg.get("competitors", []):
        known |= set(c.get("aliases", []) or [])

    issues = []
    for pat, desc in FAKE_HINTS:
        for m in _re.finditer(pat, text):
            issues.append({"level": "high", "type": "suspected_fabrication", "detail": desc,
                           "excerpt": text[max(0, m.start() - 30):m.end() + 30].replace("\n", " ")})

    # Chinese units remain part of multilingual NLP matching.
    known_values = {n["value"] for n in f.get("numbers", [])}
    units = r"%|\uff05|\u4e07|\u4ebf|\u500d|\u5143|\u7f8e\u5143|\u6e2f\u5e01|HK\$|\$|\u4eba|\u5bb6|\u5929|\u5c0f\u65f6|\u5206\u949f"
    for m in _re.finditer(rf"[^\n|]*?(\d[\d,\.]*\s*(?:{units}))[^\n|]*", text):
        seg, val = m.group(0), m.group(1)
        if any(val in v or v in val for v in known_values):
            continue
        if "pending_confirmation" in seg or "\u5f85\u786e\u8ba4" in seg or "\u5f85\u8865" in seg:
            continue
        issues.append({"level": "medium", "type": "unverified_number",
                       "detail": f"`{val}` is absent from the verified fact card",
                       "excerpt": seg.strip()[:90]})

    year = G.today()[:4]
    for m in _re.finditer(r"20\d{2}\s*\u5e74", text):
        if m.group(0).strip() != f"{year}\u5e74":
            issues.append({"level": "low", "type": "questionable_year",
                           "detail": f"Found {m.group(0)} while the current year is {year}",
                           "excerpt": text[max(0, m.start() - 25):m.end() + 25].replace("\n", " ")})
    # Collapse repeated findings.
    seen, out = set(), []
    for i in issues:
        k = (i["type"], i["detail"])
        if k in seen:
            continue
        seen.add(k)
        out.append(i)
    return out


def lint_all(slug: str) -> dict:
    d = G.project_dir(slug) / "assets" / "drafts"
    files = sorted(d.glob("*.md")) if d.exists() else []
    report = {"slug": slug, "checked_at": G.now_iso(), "files": {}}
    total = 0
    for p in files:
        iss = lint_draft(slug, p)
        report["files"][p.name] = iss
        total += len(iss)
    report["total_issues"] = total
    report["high"] = sum(1 for v in report["files"].values() for i in v if i["level"] == "high")
    G.write_json(d / "_lint.json", report) if files else None
    return report


# ---------------------------------------------------------------- Main flow

ASSETS = ["llms", "jsonld", "snippets", "outlines"]


def _asset_issues(text: str, lang: str | None = None) -> list[str]:
    issues = []
    if PLACEHOLDER_RE.search(text or ""):
        issues.append("contains_placeholder")
    if lang == "en" and HAN_RE.search(text or ""):
        issues.append("contains_untranslated_text")
    return issues


def run(slug: str, which: list[str] | None = None, with_draft: bool = False,
        draft_limit: int = 3) -> dict:
    cfg = G.load_config(slug)
    market = cfg.get("market", "cn")
    adir = G.project_dir(slug) / "assets"
    which = which or ASSETS
    made: list[str] = []
    records: list[dict] = []
    facts_need_review = bool((cfg.get("bootstrap") or {}).get("needs_review")) and not cfg.get("facts_reviewed")

    def add(relative: str, text: str, *, lang: str | None = None,
            status: str = "deployable", issues: list[str] | None = None):
        path = adir / relative
        found = list(issues or []) + _asset_issues(text, lang)
        if not text:
            if path.exists():
                path.unlink()
            records.append({"path": f"assets/{relative}", "status": "omitted",
                            "issues": found or ["missing_verified_content"]})
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, "utf-8")
        resolved_status = "review_required" if found and status == "deployable" else status
        item = {"path": f"assets/{relative}", "status": resolved_status,
                "issues": sorted(set(found))}
        records.append(item)
        made.append(item["path"])

    if "llms" in which:
        adir.mkdir(parents=True, exist_ok=True)
        facts = parse_facts(slug)
        if market in ("cn", "both"):
            issues = ["facts_require_review"] if facts_need_review else []
            if not _definition(cfg, facts, "zh"):
                issues.append("missing_verified_definition")
            add("llms.txt", gen_llms_txt(slug, "zh"), lang="zh", issues=issues)
        if market in ("global", "both"):
            issues = ["facts_require_review"] if facts_need_review else []
            if not _definition(cfg, facts, "en"):
                issues.append("missing_verified_english_definition")
            add("llms.en.txt", gen_llms_txt(slug, "en"), lang="en", issues=issues)

    if "jsonld" in which:
        d = adir / "jsonld"
        d.mkdir(parents=True, exist_ok=True)
        schemas = gen_jsonld(slug)
        for stale in d.glob("*.json"):
            if stale.stem not in schemas:
                stale.unlink()
        for name, obj in schemas.items():
            issues = ["facts_require_review"] if facts_need_review else []
            add(f"jsonld/{name}.json", json.dumps(obj, ensure_ascii=False, indent=2), issues=issues)

    if "snippets" in which:
        for lang in (["zh"] if market == "cn" else ["en"] if market == "global" else ["zh", "en"]):
            issues = ["facts_require_review"] if facts_need_review else []
            add(f"snippets/definition.{lang}.html", gen_definition_block(slug, lang),
                lang=lang, issues=issues)
            add(f"snippets/faq.{lang}.html", gen_faq_block(slug, lang), lang=lang)

    outlines = []
    if "outlines" in which:
        d = adir / "outlines"
        d.mkdir(parents=True, exist_ok=True)
        outlines = gen_outlines(slug)
        for o in outlines:
            strings = _locale("zh" if o["market"] == "cn" else "en")["outline_document"]
            body = [f"# {strings['title'].format(question=o['target_question'])}", "",
                    f"- {strings['meta'].format(question_id=o['question_id'], market=o['market'], type=o['type'])}",
                    "", f"## {strings['title_candidates']}", ""]
            body += [f"{i+1}. {t}" for i, t in enumerate(o["title_candidates"])]
            body += ["", f"## {strings['sections']}", ""]
            body += [f"{i+1}. {s}" for i, s in enumerate(o["sections"])]
            requirements = o["requirements"]
            body += ["", f"## {strings['requirements']}", "",
                     f"- {strings['min_words'].format(min_words=requirements['min_words'], min_h2=requirements['min_h2'])}",
                     f"- {strings['blocks'].format(blocks=strings['block_separator'].join(requirements['must_have_blocks']))}",
                     f"- {strings['list_density'].format(density=requirements['list_density'])}",
                     f"- {strings['evidence'].format(evidence=requirements['evidence'])}", ""]
            if o["facts_to_use"]:
                body += [f"## {strings['facts']}", ""] + [f"- {x}" for x in o["facts_to_use"]] + [""]
            path = G.safe_child(d, o["question_id"], ".md")
            path.write_text("\n".join(body), "utf-8")
            item = {"path": f"assets/outlines/{path.name}", "status": "draft", "issues": []}
            records.append(item)
            made.append(item["path"])
        G.write_json(adir / "outlines" / "_index.json", outlines)

    if with_draft and outlines:
        d = adir / "drafts"
        d.mkdir(parents=True, exist_ok=True)
        for o in outlines[:draft_limit]:
            G.info(f"Drafting {o['question_id']} · {o['target_question'][:30]}…")
            text = draft(slug, o)
            if text:
                path = G.safe_child(d, o["question_id"], ".md")
                lang = "zh" if o["market"] == "cn" else "en"
                note = _locale(lang)["draft_review_comment"]
                path.write_text(f"<!-- {note} - {G.today()} -->\n\n" + text, "utf-8")
                item = {"path": f"assets/drafts/{path.name}", "status": "draft",
                        "issues": ["requires_factual_review"]}
                records.append(item)
                made.append(item["path"])
            else:
                G.info("  No available LLM API Key, skipping draft generation")
                break
        rep = lint_all(slug)
        if rep.get("total_issues"):
            G.info(f"Draft risk inspection: {rep['total_issues']} items (High risk: {rep['high']} items)"
                   " -> assets/drafts/_lint.json. Manual review required before publication.")

    index = {
        "slug": slug, "generated_at": G.now_iso(), "market": market,
        "assets": [item["path"] for item in records if item["status"] == "deployable"],
        "generated_assets": made,
        "asset_records": records,
        "review_required": [item["path"] for item in records if item["status"] == "review_required"],
        "drafts": [item["path"] for item in records if item["status"] == "draft"],
    }
    G.write_json(adir / "index.json", index)
    G.info(f"Generated {len(made)} asset(s) → {adir}")
    return index
