"""Generate the current GEO report as Markdown and self-contained HTML.

Outputs:
  work/<slug>/reports/<date>/report.md
  work/<slug>/reports/<date>/report.html
  work/<slug>/reports/latest.md
"""

from __future__ import annotations

import html
import re
from pathlib import Path

import geolib as G

GRADE_NOTE = {"A": "Directly citeable", "B": "Usable baseline", "C": "Needs optimization", "D": "Non-extractable"}


def cell(s) -> str:
    """Table cell escaping."""
    return re.sub(r"\s+", " ", str(s)).replace("|", "/").strip()


def prev_metrics(pdir: Path, current: str):
    files = sorted((pdir / "metrics").glob("*.json"))
    files = [f for f in files if f.stem != current]
    return G.read_json(files[-1], None) if files else None


def prev_audit(pdir: Path):
    hist = sorted((pdir / "history").glob("audit-*.json"))
    return G.read_json(hist[-1], None) if hist else None


def delta(cur, prev, pct=False):
    if prev is None or cur is None:
        return ""
    d = cur - prev
    if abs(d) < 1e-9:
        return " (flat)"
    arrow = "↑" if d > 0 else "↓"
    return f" ({arrow}{abs(d)*100:.1f}pp)" if pct else f" ({arrow}{abs(d):.1f})"


def _weighted(rows, field):
    values = [(row.get(field), int(row.get("samples") or 0)) for row in rows
              if row.get(field) is not None and int(row.get("samples") or 0) > 0]
    total = sum(count for _value, count in values)
    return sum(value * count for value, count in values) / total if total else None


def pct(v):
    """None metric = unmeasured, do not fabricate numbers."""
    return f"{v:.0%}" if isinstance(v, (int, float)) else "Unmeasured"


def collect_todos(audit: dict, top: int = 20) -> list[dict]:
    """Aggregate page-level issues into prioritized action items."""
    buckets: dict[tuple[str, str], list[str]] = {}
    for issue in audit.get("site_issues", []):
        pri, _, body = issue.partition(" ")
        buckets.setdefault((pri, body), []).append("Sitewide")
    for p in audit.get("pages", []):
        for issue in p.get("issues", []):
            pri, _, body = issue.partition(" ")
            buckets.setdefault((pri, body), []).append(p["url"])
    todos = [
        {"priority": k[0], "action": k[1], "affected": len(v), "examples": v[:3]}
        for k, v in buckets.items()
    ]
    order = {"P0": 0, "P1": 1, "P2": 2}
    todos.sort(key=lambda t: (order.get(t["priority"], 9), -t["affected"]))
    return todos[:top]


def _bench_section(cn_domains: dict[str, int]) -> str:
    """Compare cited sources against national benchmark to identify high-leverage opportunities."""
    import benchmark

    b = benchmark.compare(cn_domains)
    L = ["#### Benchmark Comparison", "",
         f"Among the 15 high-authority cross-platform citation sources in the national benchmark, you cover **{len(b['cross_platform_covered'])}/15**"
         f" ({b['coverage_rate']:.0%}). These root domains influence all frontier AI models.", ""]

    if b["cross_platform_missing"]:
        L += ["**Missing Key Sources (Ranked by National Citation Volume)**:", "",
              "| Domain | Category | National Citations |", "|---|---|---:|"]
        for m in b["cross_platform_missing"][:10]:
            L.append(f"| `{m['domain']}` | {m['category']} | {m['national_citations']:,} |")
        L.append("")

    if b["ecosystem_gaps"]:
        L += ["**Ecosystem Gaps (Critical Platforms Gateways)**:", ""]
        for g in b["ecosystem_gaps"]:
            L.append(f"- `{g['domain']}` — {g['why']}")
        L.append("")

    if b["high_position_hits"]:
        L += ["**Covered Sources with High Placement (High Leverage)**:", ""]
        for h in b["high_position_hits"]:
            L.append(f"- `{h['domain']}` (Avg placement #{h['position']}, cited {h['your_citations']} times this cycle)")
        L.append("")

    L += ["> Note: **Brand official sites account for only 1.37% of total citation links across models**. The official site acts as the source of truth, not the primary citation link.",
          "> Shifting resources from 'micro-optimizing site HTML' to 'building external authoritative sources' typically delivers higher ROI. See `references/sources.md`.", ""]
    return "\n".join(L)


def build_markdown(cfg, audit, metrics, prev_m, prev_a, todos) -> str:
    b = cfg["brand"]
    L = []
    A = L.append
    A(f"# {b['name']} · GEO Diagnostic Report · {G.today()}")
    A("")
    A(f"- Official Website: {b['site']}")
    A(f"- Target Market: { {'cn':'Domestic (CN)','global':'Global','both':'Global & Domestic'}.get(cfg.get('market','global'), cfg.get('market')) }")
    A(f"- Crawled Pages: {audit['page_count']} pages; Average Site Score **{audit['avg_score']}**"
      + (delta(audit["avg_score"], prev_a["avg_score"]) if prev_a else " (Baseline run)"))
    A("")

    A("## 1. Executive Summary")
    A("")
    p0 = [t for t in todos if t["priority"] == "P0"]
    if p0:
        A("Critical P0 Blockers to Resolve First:")
        for t in p0[:5]:
            A(f"- **{t['action']}** — affects {t['affected']} locations")
    else:
        A("- Zero P0 blockers. Focus on content extraction blocks and authoritative citation building.")
    A("")
    if metrics and metrics.get("platforms"):
        for mk, mk_name in (("cn", "Domestic (CN)"), ("global", "Global")):
            pool = [(p, m) for p, m in metrics["platforms"].items()
                    if m.get("market", "cn") == mk]
            if not pool:
                continue
            measured = [(p, m) for p, m in pool if m.get("mention_rate") is not None]
            rows = [(p, m) for p, m in measured if int(m.get("samples") or 0) >= 5]
            if not measured:
                A(f"- {mk_name}: Unmeasured")
                continue
            if not rows:
                A(f"- {mk_name}: Insufficient samples for platform comparisons")
                continue
            best = max(rows, key=lambda x: x[1]["mention_rate"])
            worst = min(rows, key=lambda x: x[1]["mention_rate"])
            if len(rows) < 2 or best[1]["mention_rate"] == worst[1]["mention_rate"]:
                A(f"- {mk_name}: Uniform mention rates across platforms or insufficient sample size.")
                continue
            A(f"- {mk_name} Top Performer: **{best[1].get('label', best[0])}** (Mention rate {best[1]['mention_rate']:.0%}); "
              f"Weakest: **{worst[1].get('label', worst[0])}** ({worst[1]['mention_rate']:.0%})")
    A("")

    A("## 2. Technical Infrastructure")
    A("")
    s = audit.get("site", {})
    A("| Check Item | Result |")
    A("|---|---|")
    A(f"| sitemap.xml | {'Present (' + str(s.get('sitemap_url_count', 0)) + ' URLs)' if s.get('has_sitemap') else '**Missing**'} |")
    A(f"| llms.txt | {'Present' if s.get('has_llms_txt') else '**Missing**'} |")
    A(f"| Robots Disallowed Bots | {', '.join(s.get('ai_bots_blocked') or []) or 'None'} |")
    A(f"| Page Accessibility Ratio | {s.get('pages_ok', 0)}/{s.get('pages_crawled', 0)} |")
    lc = audit.get("language_coverage") or {}
    if lc:
        lang_line = f"Chinese {lc.get('zh_pages', 0)} pages / English {lc.get('en_pages', 0)} pages"
        if lc.get("ja_pages", 0) > 0:
            lang_line += f" / Japanese {lc['ja_pages']} pages"
        A(f"| Language Coverage | {lang_line} |")
    A("")
    if audit.get("site_issues"):
        for i in audit["site_issues"]:
            A(f"- {i}")
        A("")

    A("## 3. Page GEO Audit")
    A("")
    gd = audit["grade_distribution"]
    A("| Grade | Pages | Meaning |")
    A("|---|---:|---|")
    for g in "ABCD":
        A(f"| {g} | {gd.get(g, 0)} | {GRADE_NOTE[g]} |")
    A("")
    A("Pages in Urgent Need of Optimization (Lowest Score First):")
    A("")
    A("| Score | Words | Missing Extraction Blocks | Page |")
    A("|---:|---:|---|---|")
    scored_pages = [page for page in audit["pages"] if page.get("score") is not None]
    for p in scored_pages[:12]:
        miss = ", ".join([k for k, v in p["blocks"].items() if v is False]) or "—"
        label = cell(p["title"] or p["url"])[:40]
        A(f"| {p['score']} | {p['word_count']} | {miss} | [{label}]({p['url']}) |")
    A("")
    A("Sitewide Extraction Block Gaps (Research Associations, Not Causal Lifts):")
    A("")
    A("| Extraction Block | Missing Pages | Evidence Note |")
    A("|---|---:|---|")
    gain = {key: "Associated with higher citation rates in the reference dataset; validate per project"
            for key in ("numeric_facts", "definition", "comparison", "steps", "faq")}
    for g in audit["block_gap"]:
        A(f"| {g['block']} | {g['missing_pages']}/{g['total']} | {gain.get(g['block'], '—')} |")
    A("")

    A("## 4. AI Search Visibility & Citations")
    A("")
    if not metrics or not metrics.get("platforms"):
        A("No sampling metrics available for this cycle. Configure API keys in Settings and run Sampling, or export a manual sampling sheet.")
        A("")
    else:
        stale = metrics.get("date") and metrics["date"] != G.today()
        A(f"Total Samples: {metrics['sample_count']} / Questions: {metrics['question_count']}"
          + (f", sampled on **{metrics['date']}**." if stale else "."))
        A("")
        A("> Domestic and Global markets are measured separately; metrics are never blended or averaged together.")
        A("")
        for mk, mk_name in (("cn", "Domestic (CN)"), ("global", "Global")):
            rows = {p: m for p, m in metrics["platforms"].items() if m.get("market", "cn") == mk}
            if not rows:
                continue
            A(f"### {mk_name} Market")
            A("")
            A("**Unprompted Visibility** (Brand name not in prompt; measures whether AI mentions brand organically):")
            A("")
            A("| Platform | Samples | Mention Rate | Top 1 | Top 3 | Avg Rank | Own Domain Cited |")
            A("|---|---:|---:|---:|---:|---:|---:|")
            for plat, m in rows.items():
                pm = (prev_m or {}).get("platforms", {}).get(plat, {})
                A(f"| {cell(m.get('label', plat))} | {m['samples']} "
                  f"| {pct(m.get('mention_rate'))}{delta(m.get('mention_rate'), pm.get('mention_rate'), True)} "
                  f"| {pct(m.get('top1_rate'))} | {pct(m.get('top3_rate'))} "
                  f"| {m['avg_rank'] or '—'} | {pct(m.get('own_domain_cite_rate'))} |")
            A("")
            probes = {p: m["probe"] for p, m in rows.items() if (m.get("probe") or {}).get("samples")}
            if probes:
                A("**Brand Knowledge Verification** (Direct brand query; measures factual accuracy and perception):")
                A("")
                A("| Platform | Samples | Recognized | Own Domain Cited |")
                A("|---|---:|---:|---:|")
                for plat, pr in probes.items():
                    A(f"| {cell(rows[plat].get('label', plat))} | {pr['samples']} "
                      f"| {pr['recognized_rate']:.0%} | {pr['own_domain_cite_rate']:.0%} |")
                A("")

            comp: dict[str, int] = {}
            doms: dict[str, int] = {}
            for m in rows.values():
                for k, v in m["competitor_mentions"].items():
                    comp[k] = comp.get(k, 0) + v
                for k, v in m["top_cited_domains"].items():
                    doms[k] = doms.get(k, 0) + v
            if comp:
                A(f"{mk_name} Competitor Mention Frequency: " + ", ".join(f"{k} ({v})" for k, v in sorted(comp.items(), key=lambda x: -x[1])[:10]))
                A("")
            if doms:
                A(f"{mk_name} Top Cited Source Domains by AI (Target destinations for content distribution):")
                A("")
                for k, v in sorted(doms.items(), key=lambda x: -x[1])[:15]:
                    A(f"- `{k}` × {v}")
                A("")
            if mk == "cn" and doms:
                A(_bench_section(doms))

    A("## 5. Action Tickets")
    A("")
    A("| Priority | Action | Impact Scope | Example |")
    A("|---|---|---:|---|")
    for t in todos:
        ex = t["examples"][0] if t["examples"] else ""
        ex = ex if ex == "Sitewide" else f"[Link]({ex})"
        A(f"| {t['priority']} | {cell(t['action'])} | {t['affected']} | {ex} |")
    A("")
    A("---")
    A("")
    A(f"Methodology specifications: `references/method.md`. Generated at {G.now_iso()}.")
    return "\n".join(L)


def market_avg_cards(metrics) -> list[tuple[str, str]]:
    """Domestic/Global average mention rates split into two cards."""
    cards = []
    if not metrics or not metrics.get("platforms"):
        return cards
    for mk, mk_name in (("cn", "Domestic (CN)"), ("global", "Global")):
        pool = [m for m in metrics["platforms"].values() if m.get("market", "cn") == mk]
        if not pool:
            continue
        rate = _weighted(pool, "mention_rate")
        cards.append((f"{mk_name} Avg Mention",
                      f"{rate:.0%}" if rate is not None else "Unmeasured"))
    return cards


CSS = """
:root{--bg:#fdfcfa;--fg:#1f2328;--mut:#6b7280;--line:#e5e1d8;--acc:#1f4e79;--warn:#b4451f;--card:#fff}
@media(prefers-color-scheme:dark){:root{--bg:#14161a;--fg:#e6e6e6;--mut:#9aa0a6;--line:#2c3037;--acc:#7fb3e0;--warn:#e08b5f;--card:#1b1e23}}
:root[data-theme=dark]{--bg:#14161a;--fg:#e6e6e6;--mut:#9aa0a6;--line:#2c3037;--acc:#7fb3e0;--warn:#e08b5f;--card:#1b1e23}
:root[data-theme=light]{--bg:#fdfcfa;--fg:#1f2328;--mut:#6b7280;--line:#e5e1d8;--acc:#1f4e79;--warn:#b4451f;--card:#fff}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.75 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:920px;margin:0 auto;padding:40px 24px 96px}
h1{font-size:28px;margin:0 0 4px;letter-spacing:-.01em}
h2{font-size:20px;margin:44px 0 14px;padding-bottom:8px;border-bottom:2px solid var(--line);color:var(--acc)}
h3{font-size:16px;margin:26px 0 10px}
.sub{color:var(--mut);font-size:14px;margin-bottom:28px}
table{border-collapse:collapse;width:100%;margin:14px 0;font-size:14px}
th,td{border:1px solid var(--line);padding:8px 10px;text-align:left;vertical-align:top}
th{background:color-mix(in srgb,var(--acc) 8%,transparent);font-weight:600}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
.scroll{overflow-x:auto}
code{background:color-mix(in srgb,var(--fg) 8%,transparent);padding:1px 5px;border-radius:4px;font-size:13px}
a{color:var(--acc)}
ul{padding-left:22px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:20px 0}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.card .k{font-size:12px;color:var(--mut)}
.card .v{font-size:26px;font-weight:650;font-variant-numeric:tabular-nums;line-height:1.3}
.p0{color:var(--warn);font-weight:700}
hr{border:0;border-top:1px solid var(--line);margin:36px 0}
"""


def md_to_html(md: str) -> str:
    """Markdown subset renderer."""
    def inline(s):
        s = html.escape(s)
        s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', s)
        s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
        return s

    out, lines, i = [], md.split("\n"), 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s:|-]+\|$", lines[i + 1]):
            aligns = [c.strip() for c in lines[i + 1].strip("|").split("|")]
            head = [c.strip() for c in ln.strip("|").split("|")]
            cls = ["n" if a.endswith(":") else "" for a in aligns]
            rows = []
            i += 2
            while i < len(lines) and lines[i].startswith("|"):
                rows.append([c.strip() for c in lines[i].strip("|").split("|")])
                i += 1
            th = "".join(f'<th class="{c}">{inline(h)}</th>' for h, c in zip(head, cls))
            tb = "".join("<tr>" + "".join(f'<td class="{c}">{inline(v)}</td>' for v, c in zip(r, cls)) + "</tr>" for r in rows)
            out.append(f'<div class="scroll"><table><thead><tr>{th}</tr></thead><tbody>{tb}</tbody></table></div>')
            continue
        if m := re.match(r"^(#{1,4})\s+(.*)", ln):
            lvl = len(m.group(1))
            out.append(f"<h{lvl}>{inline(m.group(2))}</h{lvl}>")
        elif ln.startswith("- "):
            items = []
            while i < len(lines) and lines[i].startswith("- "):
                items.append(f"<li>{inline(lines[i][2:])}</li>")
                i += 1
            out.append("<ul>" + "".join(items) + "</ul>")
            continue
        elif ln.strip() == "---":
            out.append("<hr>")
        elif ln.strip():
            out.append(f"<p>{inline(ln)}</p>")
        i += 1
    body = "\n".join(out)
    body = body.replace("P0 ", '<span class="p0">P0</span> ')
    return body


def build_html(title: str, md: str, cards: list[tuple[str, str]]) -> str:
    card_html = "".join(f'<div class="card"><div class="k">{html.escape(k)}</div><div class="v">{html.escape(v)}</div></div>' for k, v in cards)
    return (
        f"<!doctype html><html lang=en><head><meta charset=utf-8>"
        f'<meta name=viewport content="width=device-width,initial-scale=1">'
        f"<title>{html.escape(title)}</title><style>{CSS}</style></head><body><div class=wrap>"
        f'<div class="cards">{card_html}</div>{md_to_html(md)}</div></body></html>'
    )


def run(slug: str) -> Path:
    cfg = G.load_config(slug)
    pdir = G.project_dir(slug)
    audit = G.read_json(pdir / "audit.json")
    if not audit:
        G.die("Missing audit.json, run audit first")
    metrics = G.read_json(pdir / "metrics" / f"{G.today()}.json", None)
    if metrics is None:
        files = sorted((pdir / "metrics").glob("*.json")) if (pdir / "metrics").exists() else []
        metrics = G.read_json(files[-1], None) if files else None
    pm = prev_metrics(pdir, (metrics.get("run_id") or metrics.get("date")) if metrics else G.today())
    pa = prev_audit(pdir)

    todos = collect_todos(audit)
    md = build_markdown(cfg, audit, metrics, pm, pa, todos)

    cards = [
        ("Site Score", str(audit["avg_score"])),
        ("Crawled Pages", str(audit["page_count"])),
        ("Pages to Fix (C/D)", str(audit["grade_distribution"].get("C", 0) + audit["grade_distribution"].get("D", 0))),
        ("P0 Blockers", str(sum(1 for t in todos if t["priority"] == "P0"))),
    ]
    cards += market_avg_cards(metrics)

    outdir = pdir / "reports" / G.today()
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "report.md").write_text(md, "utf-8")
    (outdir / "report.html").write_text(build_html(f"{cfg['brand']['name']} GEO Report {G.today()}", md, cards), "utf-8")
    (pdir / "reports" / "latest.md").write_text(md, "utf-8")
    G.write_json(pdir / "todos.json", todos)

    # Archive current audit for delta calculation in next run
    G.write_json(pdir / "history" / f"audit-{G.today()}.json",
                 {"avg_score": audit["avg_score"], "grade_distribution": audit["grade_distribution"],
                  "page_count": audit["page_count"], "date": G.today()})

    G.info(f"Report generated → {outdir/'report.html'}")
    return outdir / "report.html"
