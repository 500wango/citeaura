"""Convert audit findings into assignable, verifiable, trackable tickets.

``tasks.json`` is the execution-layer source of truth. Every ticket includes
its rationale, owner, acceptance criteria, and market.
"""

from __future__ import annotations

from datetime import datetime

import geolib as G

PACKAGES = ["Entity disambiguation", "Page technology", "Content matrix", "Heading system",
            "Knowledge base", "External evidence", "Measurement loop"]
OWNERS = ["Engineering", "Content", "Marketing", "GEO consultant", "Legal", "Design"]
EFFORT = {"S": "<=0.5 person-day", "M": "1-3 person-days", "L": ">=5 person-days"}
VALID_STATUSES = ("todo", "doing", "done", "blocked", "wontfix")


def _t(tid, priority, package, title, why, action, owner, effort, acceptance,
       market="both", affected=None, window="30_days", assets=None):
    return {
        "id": tid, "priority": priority, "package": package, "market": market,
        "title": title, "why": why, "action": action,
        "owner": owner, "effort": effort, "window": window,
        "affected": affected or [], "acceptance": acceptance,
        "status": "todo", "assets": assets or [], "evidence": [], "closed_at": None,
    }


# ---------------------------------------------------------------- Generation rules

def _has_issue(page: dict, code: str, text_fallback: str) -> bool:
    """Match structured issue codes, falling back to message text when needed."""
    codes = page.get("issue_codes")
    if codes is not None:
        return code in codes
    return any(text_fallback in i for i in page.get("issues", []))


def from_audit(audit: dict, cfg: dict, seq) -> list[dict]:
    """Build site-technology and page-level tickets."""
    out = []
    site = audit.get("site", {})
    market = cfg.get("market", "cn")
    pages = audit.get("pages", [])
    scored_pages = [p for p in pages if p.get("scored", True) and p.get("score") is not None]

    # Site-level findings
    if site.get("ai_bots_blocked"):
        out.append(_t(next(seq), "P0", "Page technology",
                      "Unblock AI crawlers in robots.txt",
                      f"robots.txt blocks {', '.join(site['ai_bots_blocked'])}, preventing those crawlers from indexing the site",
                      "Remove the matching Disallow directives or restrict them to private application paths", "Engineering", "S",
                      {"type": "auto", "check": "site.no_ai_bot_block",
                       "desc": "Re-crawl confirms robots.txt no longer blocks AI crawlers sitewide"}))
    if not site.get("has_sitemap"):
        out.append(_t(next(seq), "P0", "Page technology", "Add and submit sitemap.xml",
                      "Missing sitemap.xml reduces discovery efficiency and coverage",
                      "Generate sitemap.xml, declare it in robots.txt, and submit it to the target search engines",
                      "Engineering", "S",
                      {"type": "auto", "check": "site.has_sitemap", "desc": "Re-crawl can fetch sitemap.xml"}))
    if not site.get("has_llms_txt"):
        out.append(_t(next(seq), "P1", "Knowledge base", "Deploy the official /llms.txt facts index",
                      "A curated official index gives AI systems a low-cost machine-readable facts source",
                      "Generate the asset with `geo.py generate --asset llms` and deploy it at the site root", "Engineering", "S",
                      {"type": "auto", "check": "site.has_llms_txt", "desc": "Re-crawl can fetch /llms.txt"}))

    # Language coverage for multi-market projects
    lc = audit.get("language_coverage") or {}
    if market in ("global", "both") and lc.get("en_pages", 0) == 0:
        out.append(_t(next(seq), "P0", "Content matrix", "Build a native English content section",
                      "The project has no native English pages and needs a measurable global-market baseline",
                      "Publish at least eight native English pages covering home, product, pricing, comparison, FAQ, and three case studies",
                      "Content", "L", {"type": "auto", "check": "site.en_pages_gte:8",
                                      "desc": "At least eight valid English content pages"}, market="global"))
    elif market == "both" and lc.get("en_pages", 0) and lc.get("zh_pages", 0):
        en, zh = lc["en_pages"], lc["zh_pages"]
        if abs(en - zh) > max(en, zh) * 0.7:
            thin = "English" if en < zh else "Chinese"
            out.append(_t(next(seq), "P1", "Content matrix", f"Balance {thin} content coverage",
                          f"Chinese {zh} pages / English {en} pages; {thin} coverage is materially weaker",
                          f"Bring {thin} page coverage within 30% of the other language", "Content", "L",
                          {"type": "auto", "check": "site.lang_balance:0.7",
                           "desc": "Chinese and English page-count difference is at most 70%"}))

    # Aggregate page findings by gap type instead of creating one ticket per page.
    spa = [p["url"] for p in pages if _has_issue(p, "SPA_SHELL", "Static HTML contains almost no body text")]
    if spa:
        t = _t(next(seq), "P0", "Page technology", "Fix client-rendered empty-shell pages with SSR or prerendering",
               "Static HTML has no meaningful body text, so non-rendering crawlers receive an empty page",
               "Enable SSR or prerendering for affected routes so raw HTML contains the complete body text",
               "Engineering", "M", {"type": "auto", "check": "pages.static_text",
                                    "desc": "Affected pages contain at least 120 words after re-crawl"},
               affected=spa)
        t["baseline_count"] = len(spa)
        t["verification_cohort"] = list(spa)
        out.append(t)

    no_schema = [p["url"] for p in scored_pages if not p.get("jsonld_types")]
    if no_schema:
        t = _t(next(seq), "P0", "Page technology", "Add sitewide JSON-LD structured data",
               "Missing structured data weakens machine-readable entity context",
               "Select Schema.org types supported by visible page content and verified facts; do not deploy placeholder or unsupported fields",
               "Engineering", "M", {"type": "auto", "check": "pages.has_jsonld",
                                    "desc": "Affected pages contain JSON-LD after re-crawl"},
               affected=no_schema)
        t["baseline_count"] = len(no_schema)
        t["verification_cohort"] = list(no_schema)
        out.append(t)

    # Reference associations prioritize extraction gaps but do not imply causal lift.
    association = {"numeric_facts": "stronger association", "definition": "stronger association",
                   "comparison": "positive association", "steps": "positive association",
                   "faq": "potential retrieval association requiring validation"}
    for g in audit.get("block_gap", []):
        if g["missing_pages"] >= max(3, g["total"] * 0.3):
            blk = g["block"]
            miss = [p["url"] for p in scored_pages if p.get("blocks", {}).get(blk) is False]
            t = _t(next(seq), "P1", "Content matrix", f"Add {blk} extraction blocks sitewide",
                   f"Missing on {g['missing_pages']}/{g['total']} pages; reference data shows a {association.get(blk, 'positive association')}, not causal lift",
                   f"Add {blk} blocks to core pages following content-patterns.md; keep definition text consistent with verified brand facts",
                   "Content", "M", {"type": "auto", "check": f"pages.block:{blk}",
                                    "desc": f"Pages missing {blk} blocks decrease by at least 50%"},
                   affected=miss[:30])
            # Affected examples are capped for display; verification uses the full cohort.
            t["baseline_count"] = len(miss)
            t["verification_cohort"] = list(miss)
            out.append(t)

    short = [p["url"] for p in scored_pages if p["word_count"] < 1000 and p["word_count"] >= 100]
    if len(short) >= 3:
        t = _t(next(seq), "P1", "Content matrix", "Expand core pages to 1,000+ words where justified",
               "Longer reference content is associated with visibility, but expansion must serve page intent and be validated through sampling",
               "Prioritize product, case-study, and comparison pages with definitions, sourced numeric tables, steps, and limitations",
               "Content", "L", {"type": "auto", "check": "pages.wordcount_gte:1000",
                                "desc": "Pages below 1,000 words decrease by at least 40%"},
               affected=short[:30])
        t["baseline_count"] = len(short)
        t["verification_cohort"] = list(short)
        out.append(t)

    thin_h2 = [p["url"] for p in scored_pages if len(p.get("dimensions", {})) and p["score"] < 70]
    if audit.get("avg_score") is not None and audit["avg_score"] < 70:
        out.append(_t(next(seq), "P1", "Page technology", f"Raise average site score from {audit.get('avg_score')} to 70",
                      "An average score below 70 indicates broad crawlability, structure, or evidence gaps",
                      "Improve the ten lowest-scoring pages according to their specific audit findings",
                      "Content", "L", {"type": "auto", "check": "site.avg_score_gte:70",
                                      "desc": "Re-audit average score is at least 70"},
                      affected=thin_h2[:10]))
    return out


def from_metrics(metrics: dict, cfg: dict, seq) -> list[dict]:
    """Build AI-answer visibility tickets separately by market."""
    out = []
    if not metrics or not metrics.get("platforms"):
        return out
    measurement = metrics.get("measurement") or {}
    if measurement and not measurement.get("sufficient"):
        out.append(_t(
            next(seq), "P0", "Measurement loop", "Establish a representative AI visibility baseline",
            "Current sample volume or platform coverage supports observations only, not performance conclusions",
            f"Collect at least {measurement.get('minimum_samples', 20)} valid unprompted samples across at least "
            f"{measurement.get('minimum_platforms', 2)} platforms using a stable question set and sampling mode",
            "GEO consultant", "M", {"type": "auto", "check": "metrics.representative_baseline",
                                     "desc": "Sample volume and platform coverage meet the minimum conclusion threshold"}))
        return out
    for mk, mk_name in (("cn", "Domestic"), ("global", "Global")):
        rows = {p: m for p, m in metrics["platforms"].items() if m.get("market", "cn") == mk}
        if not rows:
            continue
        # Probe-only platforms have None rates and do not participate in averages.
        rates = [(m["mention_rate"], int(m.get("samples") or 0)) for m in rows.values()
                 if m.get("mention_rate") is not None and int(m.get("samples") or 0) > 0]
        target = cfg.get("targets", {}).get("mention_rate", 0.3)
        if rates:
            total = sum(count for _rate, count in rates)
            avg = sum(rate * count for rate, count in rates) / total
            if avg < target:
                out.append(_t(next(seq), "P1", "Measurement loop",
                              f"Raise {mk_name} unprompted mention rate from {avg:.0%} to {target:.0%}",
                              f"The sample-weighted unprompted mention rate across {len(rates)} measured {mk_name} platforms is {avg:.0%}",
                              "Treat this as a combined content-matrix and external-source outcome metric for quarterly verification",
                              "GEO consultant", "L",
                              {"type": "auto", "check": f"metrics.mention_rate_gte:{mk}:{target}",
                               "desc": f"{mk_name} average unprompted mention rate is at least {target:.0%}"}, market=mk))
        own = [(m["own_domain_cite_rate"], int(m.get("samples") or 0)) for m in rows.values()
               if m.get("own_domain_cite_rate") is not None and int(m.get("samples") or 0) > 0]
        own_total = sum(count for _rate, count in own)
        own_avg = sum(rate * count for rate, count in own) / own_total if own_total else None
        if own_avg is not None and own_avg < 0.1:
            out.append(_t(next(seq), "P1", "External evidence",
                          f"Improve official-site retrieval in {mk_name} AI search",
                          f"The {mk_name} sample-weighted official-domain citation rate is {own_avg:.0%}; correct content has no impact when it is not retrieved",
                          "Submit the site for indexing, publish sourced content on frequently cited domains, and link relevant products from verified related sites",
                          "Marketing", "M",
                          {"type": "auto", "check": f"metrics.own_cite_gte:{mk}:0.1",
                           "desc": f"{mk_name} official-domain citation rate is at least 10%"}, market=mk))
        for plat, m in rows.items():
            pr = m.get("probe") or {}
            if pr.get("samples") and (pr.get("own_domain_cite_rate") or 0) == 0:
                continue
    return out


def from_benchmark(bench: dict, cfg: dict, seq) -> list[dict]:
    """Build external-evidence tickets from the reference ranking."""
    out = []
    if not bench:
        return out
    missing = bench.get("cross_platform_missing", [])
    rank = [m for m in missing if "ranking" in m["category"].lower()]
    if rank:
        out.append(_t(next(seq), "P1", "External evidence", "Establish presence on ranking and brand directories",
                      "Ranking domains represent a high-leverage citation category for recommendation queries",
                      "Publish verified brand listings on: " + ", ".join(f"`{m['domain']}`" for m in rank),
                      "Marketing", "M",
                      {"type": "auto", "check": "external.brand_any:" + ",".join(m["domain"] for m in rank),
                       "desc": "Sampling confirms a direct brand citation on at least one ranking domain"}, market="cn"))
    plat = [m for m in missing if m["category"].lower() == "content platform"]
    if plat:
        out.append(_t(next(seq), "P1", "External evidence", "Publish on authoritative content platforms",
                      "Content platforms represent a material share of reference citations across AI search engines",
                      "Establish and maintain verified content presence on: " + ", ".join(f"`{m['domain']}`" for m in plat),
                      "Content", "L",
                      {"type": "auto", "check": "external.brand_any:" + ",".join(m["domain"] for m in plat),
                       "desc": "Sampling confirms a direct brand citation on at least one content platform"}, market="cn"))
    for gap in bench.get("ecosystem_gaps", []):
        out.append(_t(next(seq), "P2", "External evidence", f"Overcome the {gap['domain']} ecosystem gateway",
                      f"{gap['why']}; the domain is a known gateway for platform retrieval",
                      f"Establish verified content presence on `{gap['domain']}`", "Marketing", "M",
                      {"type": "auto", "check": f"external.brand_any:{gap['domain']}",
                       "desc": f"Sampling confirms a direct brand citation from {gap['domain']}"}, market="cn"))
    return out


def entity_tasks(cfg: dict, seq) -> list[dict]:
    """Build the always-on entity and verified-facts foundation tickets."""
    b = cfg["brand"]
    return [
        _t(next(seq), "P0", "Entity disambiguation", "Standardize one-sentence brand definition across four surfaces",
           "Inconsistent messaging causes entity drift in AI-generated descriptions",
           f"Synchronize the definition for {b['name']} across homepage hero, about page, JSON-LD description, and /llms.txt",
           "Content", "S", {"type": "manual", "desc": "Definition text is verbatim identical across all four surfaces"}),
        _t(next(seq), "P0", "Knowledge base", "Build a sourced brand facts library",
           "All content production needs a single source of truth with evidence confidence",
           "Populate content/facts.md with entities, aliases, products, key metrics, applicability, exclusions, and prohibited claims; assign grades A-E",
           "GEO consultant", "M", {"type": "manual", "desc": "facts.md exists and every fact has an evidence grade"}),
        _t(next(seq), "P1", "Knowledge base", "Establish encyclopedia and knowledge-graph entries",
           "Independent entity references strengthen disambiguation and retrieval confidence",
           "Submit a verified encyclopedia entry and pursue Wikipedia for global markets when third-party sources support it",
           "Marketing", "M", {"type": "manual", "desc": "Entry is approved and publicly available"}),
    ]


# ---------------------------------------------------------------- Main flow

def build(slug: str) -> dict:
    cfg = G.load_config(slug)
    pdir = G.project_dir(slug)
    audit = G.read_json(pdir / "audit.json")
    if not audit:
        G.die("Missing audit.json, run audit first")

    files = sorted((pdir / "metrics").glob("*.json")) if (pdir / "metrics").exists() else []
    metrics = G.read_json(files[-1], None) if files else None

    bench = None
    if metrics:
        import benchmark
        doms: dict[str, int] = {}
        for m in metrics["platforms"].values():
            if m.get("market", "cn") == "cn":
                for k, v in m.get("top_cited_domains", {}).items():
                    doms[k] = doms.get(k, 0) + v
        if doms:
            bench = benchmark.compare(doms)

    counter = iter(f"T-{i:03d}" for i in range(1, 999))
    tasks = (entity_tasks(cfg, counter) + from_audit(audit, cfg, counter)
             + from_metrics(metrics, cfg, counter) + from_benchmark(bench, cfg, counter))

    # P0, P1, and P2 tickets map to 30-, 60-, and 90-day windows.
    win = {"P0": "30_days", "P1": "60_days", "P2": "90_days"}
    for t in tasks:
        t["window"] = win.get(t["priority"], "90_days")

    with G.project_lock(slug):
        # Preserve the latest state while serializing against status updates.
        old = {t["id"]: t for t in (G.read_json(pdir / "tasks.json", {}) or {}).get("tasks", [])}
        old_by_title = {t["title"]: t for t in old.values()}
        for t in tasks:
            prev = old.get(t["id"]) if old.get(t["id"], {}).get("title") == t["title"] else old_by_title.get(t["title"])
            if prev:
                t.update({"status": prev.get("status", "todo"), "evidence": prev.get("evidence", []),
                          "assets": prev.get("assets", []), "closed_at": prev.get("closed_at")})

        data = {
            "slug": slug, "generated_at": G.now_iso(), "market": cfg.get("market", "cn"),
            "baseline": {"avg_score": audit.get("avg_score"), "pages": audit.get("page_count"),
                         "metrics_date": metrics.get("date") if metrics else None},
            "summary": summarize(tasks),
            "tasks": tasks,
        }
        G.write_json(pdir / "tasks.json", data)
    G.info(f"Generated {len(tasks)} ticket(s) → {pdir/'tasks.json'}")
    return data


def summarize(tasks: list[dict]) -> dict:
    def cnt(**kw):
        return sum(1 for t in tasks if all(t.get(k) == v for k, v in kw.items()))
    return {
        "total": len(tasks),
        "by_priority": {p: cnt(priority=p) for p in ("P0", "P1", "P2")},
        "by_status": {s: cnt(status=s) for s in ("todo", "doing", "done", "blocked", "wontfix")},
        "by_package": {p: sum(1 for t in tasks if t["package"] == p) for p in PACKAGES
                       if any(t["package"] == p for t in tasks)},
        "by_market": {m: sum(1 for t in tasks if t["market"] == m) for m in ("cn", "global", "both")},
        "auto_verifiable": sum(1 for t in tasks if t["acceptance"]["type"] == "auto"),
    }


def load(slug: str) -> dict:
    return G.read_json(G.project_dir(slug) / "tasks.json", {"tasks": []})


def save(slug: str, data: dict):
    """Back up the current task file before an atomic write, retaining ten copies."""
    data["summary"] = summarize(data.get("tasks", []))
    p = G.project_dir(slug) / "tasks.json"
    if p.exists():
        bak = p.parent / ".geo.bak"
        bak.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        (bak / f"tasks-{stamp}.json").write_text(p.read_text("utf-8"), "utf-8")
        old = sorted(bak.glob("tasks-*.json"))
        for f in old[:-10]:
            f.unlink()
    G.write_json(p, data)


def set_status(slug: str, task_id: str, status: str, note: str = "") -> dict:
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid task status: {status}")
    with G.project_lock(slug):
        data = load(slug)
        for t in data["tasks"]:
            if t["id"] == task_id:
                previous = t.get("status")
                t["status"] = status
                if note:
                    t.setdefault("evidence", []).append({"at": G.now_iso(), "note": note})
                if status == "done" and previous != "done":
                    t["closed_at"] = G.now_iso()
                elif status != "done":
                    t["closed_at"] = None
                save(slug, data)
                G.info(f"{task_id} → {status}")
                return t
    raise KeyError(f"Ticket {task_id} does not exist")
