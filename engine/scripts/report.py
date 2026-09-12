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
from urllib.parse import urlparse

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
:root {
  --bg: #f8fafc;
  --fg: #0f172a;
  --heading: #020617;
  --mut: #64748b;
  --mut-light: #94a3b8;
  --line: #e2e8f0;
  --line-subtle: #f1f5f9;
  --line-strong: #cbd5e1;
  --card: #ffffff;
  --card-hover: #f8fafc;
  --acc: #0f766e;
  --acc-hover: #0d9488;
  --acc-bg: rgba(15, 118, 110, 0.07);
  --acc-border: rgba(15, 118, 110, 0.22);
  --warn: #b45309;
  --warn-bg: #fef3c7;
  --danger: #b91c1c;
  --danger-bg: #fee2e2;
  --good: #047857;
  --good-bg: #d1fae5;
  --info: #0369a1;
  --info-bg: #e0f2fe;
  --sh-sm: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
  --sh-md: 0 4px 16px -2px rgba(15, 23, 42, 0.06), 0 2px 4px -2px rgba(15, 23, 42, 0.04);
  --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  --font-mono: "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #080d12;
    --fg: #cbd5e1;
    --heading: #f8fafc;
    --mut: #8499a5;
    --mut-light: #475569;
    --line: #1e293b;
    --line-subtle: #141f2c;
    --line-strong: #334155;
    --card: #0f1722;
    --card-hover: #141f2d;
    --acc: #9df22f;
    --acc-hover: #b5ff5b;
    --acc-bg: rgba(157, 242, 47, 0.08);
    --acc-border: rgba(157, 242, 47, 0.25);
    --warn: #f59e0b;
    --warn-bg: rgba(245, 158, 11, 0.14);
    --danger: #ef4444;
    --danger-bg: rgba(239, 68, 68, 0.14);
    --good: #10b981;
    --good-bg: rgba(16, 185, 129, 0.14);
    --info: #38bdf8;
    --info-bg: rgba(56, 189, 248, 0.14);
    --sh-sm: 0 1px 2px 0 rgba(0, 0, 0, 0.4);
    --sh-md: 0 6px 24px -4px rgba(0, 0, 0, 0.5);
  }
}
:root[data-theme="dark"] {
  --bg: #080d12;
  --fg: #cbd5e1;
  --heading: #f8fafc;
  --mut: #8499a5;
  --mut-light: #475569;
  --line: #1e293b;
  --line-subtle: #141f2c;
  --line-strong: #334155;
  --card: #0f1722;
  --card-hover: #141f2d;
  --acc: #9df22f;
  --acc-hover: #b5ff5b;
  --acc-bg: rgba(157, 242, 47, 0.08);
  --acc-border: rgba(157, 242, 47, 0.25);
  --warn: #f59e0b;
  --warn-bg: rgba(245, 158, 11, 0.14);
  --danger: #ef4444;
  --danger-bg: rgba(239, 68, 68, 0.14);
  --good: #10b981;
  --good-bg: rgba(16, 185, 129, 0.14);
  --info: #38bdf8;
  --info-bg: rgba(56, 189, 248, 0.14);
  --sh-sm: 0 1px 2px 0 rgba(0, 0, 0, 0.4);
  --sh-md: 0 6px 24px -4px rgba(0, 0, 0, 0.5);
}
:root[data-theme="light"] {
  --bg: #f8fafc;
  --fg: #0f172a;
  --heading: #020617;
  --mut: #64748b;
  --mut-light: #94a3b8;
  --line: #e2e8f0;
  --line-subtle: #f1f5f9;
  --line-strong: #cbd5e1;
  --card: #ffffff;
  --card-hover: #f8fafc;
  --acc: #0f766e;
  --acc-hover: #0d9488;
  --acc-bg: rgba(15, 118, 110, 0.07);
  --acc-border: rgba(15, 118, 110, 0.22);
  --warn: #b45309;
  --warn-bg: #fef3c7;
  --danger: #b91c1c;
  --danger-bg: #fee2e2;
  --good: #047857;
  --good-bg: #d1fae5;
  --info: #0369a1;
  --info-bg: #e0f2fe;
  --sh-sm: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
  --sh-md: 0 4px 16px -2px rgba(15, 23, 42, 0.06), 0 2px 4px -2px rgba(15, 23, 42, 0.04);
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.7 var(--font-sans);-webkit-font-smoothing:antialiased;-moz-osx-font-smoothing:grayscale}
.wrap{max-width:960px;margin:0 auto;padding:36px 24px 80px}
.report-topbar{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:24px;padding-bottom:14px;border-bottom:1px solid var(--line)}
.report-topbar-brand{display:inline-flex;align-items:center;gap:8px}
.report-topbar-badge{display:inline-flex;align-items:center;padding:2px 8px;border-radius:4px;background:var(--acc-bg);border:1px solid var(--acc-border);color:var(--acc);font-family:var(--font-mono);font-size:11px;font-weight:700;letter-spacing:.04em;text-transform:uppercase}
.report-topbar-title{font-size:12.5px;font-weight:600;color:var(--mut)}
.btn-print{display:inline-flex;align-items:center;gap:6px;padding:6px 12px;background:var(--card);color:var(--fg);border:1px solid var(--line-strong);border-radius:6px;font-family:var(--font-sans);font-size:12.5px;font-weight:600;cursor:pointer;transition:background-color .15s ease,border-color .15s ease,color .15s ease;box-shadow:var(--sh-sm)}
.btn-print:hover{background:var(--card-hover);border-color:var(--acc);color:var(--acc)}
.delivery-branding-header ~ .wrap .report-topbar-brand{display:none}
h1{font-size:27px;font-weight:800;color:var(--heading);letter-spacing:-.025em;line-height:1.25;margin:0 0 10px}
h2{font-size:18px;font-weight:750;color:var(--heading);letter-spacing:-.015em;margin:44px 0 16px;padding-bottom:8px;border-bottom:2px solid var(--line)}
h3{font-size:14.5px;font-weight:700;color:var(--heading);letter-spacing:-.01em;margin:26px 0 10px}
.sub{color:var(--mut);font-size:13.5px;margin-bottom:24px}
p,li{line-height:1.7}
a{color:var(--acc);text-decoration:none;font-weight:500}
a:hover{text-decoration:underline}
ul{padding-left:20px;margin:12px 0 18px}
li{margin-bottom:6px}
hr{border:0;border-top:1px solid var(--line);margin:36px 0}
code{font-family:var(--font-mono);font-size:12.5px;padding:2px 6px;border-radius:4px;background:var(--line-subtle);border:1px solid var(--line);color:var(--fg)}
pre{margin:16px 0;padding:14px 16px;border-radius:8px;background:var(--card);border:1px solid var(--line);overflow-x:auto}
pre code{background:transparent;border:none;padding:0}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:22px 0 32px}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:14px 16px;box-shadow:var(--sh-md);transition:transform .15s ease,border-color .15s ease}
.card:hover{border-color:var(--line-strong)}
.card .k{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--mut);margin-bottom:6px}
.card .v{font-size:26px;font-weight:800;font-family:var(--font-mono);font-variant-numeric:tabular-nums;line-height:1.15;color:var(--heading)}
blockquote{margin:18px 0;padding:12px 18px;background:var(--acc-bg);border-left:3px solid var(--acc);border-radius:0 8px 8px 0;color:var(--fg);font-size:13.5px;line-height:1.6}
blockquote p{margin:0}
blockquote + blockquote{margin-top:8px}
.scroll{overflow-x:auto;margin:18px 0 26px;border:1px solid var(--line);border-radius:8px;background:var(--card);box-shadow:var(--sh-sm)}
table{border-collapse:collapse;width:100%;font-size:13.5px;line-height:1.5;margin:0}
th{background:var(--line-subtle);color:var(--mut);font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;padding:10px 14px;border-bottom:1px solid var(--line);border-top:0;border-left:0;border-right:0;text-align:left;white-space:nowrap}
td{padding:9px 14px;border-bottom:1px solid var(--line-subtle);border-top:0;border-left:0;border-right:0;text-align:left;vertical-align:middle;color:var(--fg)}
tr:last-child td{border-bottom:0}
tr:hover td{background:var(--card-hover)}
td.n,th.n{text-align:right;font-family:var(--font-mono);font-variant-numeric:tabular-nums}
.badge{display:inline-flex;align-items:center;justify-content:center;padding:2px 7px;border-radius:4px;font-family:var(--font-mono);font-size:11px;font-weight:700;line-height:1.2}
.badge.p0{background:var(--danger-bg);color:var(--danger);border:1px solid rgba(239,68,68,.35)}
.badge.p1{background:var(--warn-bg);color:var(--warn);border:1px solid rgba(245,158,11,.35)}
.badge.p2{background:var(--info-bg);color:var(--info);border:1px solid rgba(59,130,246,.35)}
.badge.grade-a{background:var(--good-bg);color:var(--good);border:1px solid rgba(16,185,129,.35)}
.badge.grade-b{background:var(--info-bg);color:var(--info);border:1px solid rgba(59,130,246,.35)}
.badge.grade-c{background:var(--warn-bg);color:var(--warn);border:1px solid rgba(245,158,11,.35)}
.badge.grade-d{background:var(--danger-bg);color:var(--danger);border:1px solid rgba(239,68,68,.35)}
.status-pill{display:inline-flex;align-items:center;gap:6px;font-family:var(--font-mono);font-size:11.5px;font-weight:600}
.status-pill::before{content:"";width:6px;height:6px;border-radius:99px;background:currentColor}
.status-pill.done,.status-pill.passed{color:var(--good)}
.status-pill.doing,.status-pill.warn{color:var(--warn)}
.status-pill.blocked,.status-pill.unmet{color:var(--danger)}
.status-pill.todo{color:var(--mut)}
.p0{color:var(--danger);font-weight:700}
@media print{
  @page{size:A4 portrait;margin:16mm 14mm 16mm 14mm}
  :root{--bg:#fff !important;--fg:#111827 !important;--heading:#030712 !important;--mut:#4b5563 !important;--line:#d1d5db !important;--line-subtle:#e5e7eb !important;--card:#fafafa !important;--card-hover:#fafafa !important;--acc:#0f766e !important;--acc-bg:#f0fdfa !important;--sh-sm:none !important;--sh-md:none !important}
  body{background:#fff !important;color:#111827 !important;font-size:9.5pt !important;line-height:1.45 !important}
  .wrap{max-width:100% !important;padding:0 !important;margin:0 !important}
  .no-print{display:none !important}
  h1{font-size:18pt !important;margin-bottom:6pt !important;break-after:avoid !important;page-break-after:avoid !important}
  h2{font-size:13pt !important;margin-top:18pt !important;margin-bottom:8pt !important;border-bottom:1.5pt solid #d1d5db !important;break-after:avoid !important;page-break-after:avoid !important}
  h3{font-size:11pt !important;margin-top:12pt !important;margin-bottom:6pt !important;break-after:avoid !important;page-break-after:avoid !important}
  .cards{grid-template-columns:repeat(4,1fr) !important;gap:8px !important;margin:10pt 0 16pt !important;break-inside:avoid !important;page-break-inside:avoid !important}
  .card{border:1px solid #d1d5db !important;background:#f9fafb !important;box-shadow:none !important;padding:6pt 10pt !important;break-inside:avoid !important;page-break-inside:avoid !important}
  .card .k{font-size:7.5pt !important;color:#4b5563 !important}
  .card .v{font-size:15pt !important;color:#030712 !important}
  .scroll{overflow:visible !important;border:1px solid #d1d5db !important;box-shadow:none !important;margin:8pt 0 14pt !important}
  table{font-size:8.5pt !important;width:100% !important}
  thead{display:table-header-group !important}
  tr{break-inside:avoid !important;page-break-inside:avoid !important}
  th{background:#f3f4f6 !important;color:#1f2937 !important;border-bottom:1pt solid #9ca3af !important;padding:5pt 7pt !important;font-weight:700 !important}
  td{border-bottom:0.5pt solid #e5e7eb !important;padding:4.5pt 7pt !important}
  blockquote{border-left:2.5pt solid #0f766e !important;background:#f0fdfa !important;color:#134e4a !important;padding:6pt 10pt !important;margin:8pt 0 !important;break-inside:avoid !important;page-break-inside:avoid !important}
  code{background:#f1f5f9 !important;border:0.5pt solid #cbd5e1 !important;color:#0f172a !important;font-size:8pt !important}
  a{color:#111827 !important;text-decoration:none !important}
}
"""


def md_to_html(md: str) -> str:
    """Markdown subset renderer."""
    def inline(s):
        links = []

        def hold_link(match):
            label, href = match.group(1), match.group(2).strip()
            try:
                scheme = urlparse(href).scheme.lower()
            except ValueError:
                return label
            if scheme and scheme not in ("http", "https", "mailto"):
                return label
            token = f"\x00LINK{len(links)}\x00"
            links.append((token, label, href))
            return token

        s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", hold_link, s)
        s = html.escape(s)
        s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
        for token, label, href in links:
            s = s.replace(token, f'<a href="{html.escape(href, quote=True)}">{html.escape(label)}</a>')
        return s

    def style_cell(text, col_idx, head_label):
        val = text.strip()
        if val in ("P0", "P1", "P2"):
            return f'<span class="badge {val.lower()}">{val}</span>'
        if val in ("A", "B", "C", "D") and head_label.lower() in ("grade", "等级", "评级"):
            return f'<span class="badge grade-{val.lower()}">{val}</span>'
        if val in ("Done", "Passed", "完成", "通过"):
            return f'<span class="status-pill done">{inline(text)}</span>'
        if val in ("In Progress", "In verification", "进行中", "验证中"):
            return f'<span class="status-pill doing">{inline(text)}</span>'
        if val in ("Blocked", "Unmet", "阻塞", "未达标"):
            return f'<span class="status-pill blocked">{inline(text)}</span>'
        if val in ("Todo", "待办"):
            return f'<span class="status-pill todo">{inline(text)}</span>'
        return inline(text)

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
            tb = "".join("<tr>" + "".join(f'<td class="{c}">{style_cell(v, idx, head[idx] if idx < len(head) else "")}</td>' for idx, (v, c) in enumerate(zip(r, cls))) + "</tr>" for r in rows)
            out.append(f'<div class="scroll"><table><thead><tr>{th}</tr></thead><tbody>{tb}</tbody></table></div>')
            continue
        if ln.startswith("```"):
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                code_lines.append(html.escape(lines[i]))
                i += 1
            out.append(f"<pre><code>{chr(10).join(code_lines)}</code></pre>")
            i += 1
            continue
        if ln.startswith("> "):
            quotes = []
            while i < len(lines) and lines[i].startswith("> "):
                quotes.append(inline(lines[i][2:]))
                i += 1
            out.append(f"<blockquote><p>{' '.join(quotes)}</p></blockquote>")
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
    return "\n".join(out)


def build_html(title: str, md: str, cards: list[tuple[str, str]]) -> str:
    card_html = "".join(f'<div class="card"><div class="k">{html.escape(k)}</div><div class="v">{html.escape(v)}</div></div>' for k, v in cards)
    topbar_html = (
        '<div class="report-topbar no-print">'
        '<div class="report-topbar-brand">'
        '<span class="report-topbar-badge">CiteAura GEO</span>'
        '<span class="report-topbar-title">Executive Deliverable</span>'
        '</div>'
        '<div class="report-topbar-actions">'
        '<span class="btn-print" role="note" title="Use your browser print command to export this deliverable to PDF">'
        '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="6 9 6 2 18 2 18 9"></polyline><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"></path><rect x="6" y="14" width="12" height="8"></rect></svg>'
        '<span>Print / PDF</span>'
        '</span>'
        '</div>'
        '</div>'
    )
    return (
        f"<!doctype html><html lang=en><head><meta charset=utf-8>"
        f'<meta name=viewport content="width=device-width,initial-scale=1">'
        f"<title>{html.escape(title)}</title><style>{CSS}</style></head><body><div class=wrap>"
        f"{topbar_html}"
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
