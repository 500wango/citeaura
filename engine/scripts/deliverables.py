"""三份正式交付物：诊断报告 / 优化方案 / 执行方案。

前面各模块产出的是数据（audit.json / metrics / blueprint.json / tasks.json），
这里把它们组织成客户看得懂、能签收的三份文档：

  诊断报告  现在什么样   —— 站点体检 + AI 可见性 + 与全国大盘对照
  优化方案  应该改成什么样 —— 结论、机会地图、建设地图、资源取舍
  执行方案  谁在什么时候做什么 —— 工单、排期、验收标准、资产清单

三份都出 Markdown + 自包含 HTML。
"""

from __future__ import annotations

from pathlib import Path

import blueprint as BP
import geolib as G
import report as R
import tasks as T

STATUS_CN = {"todo": "Todo", "doing": "In Progress", "done": "Done",
             "blocked": "Blocked", "wontfix": "Won't Fix"}


def _load(slug: str):
    pdir = G.project_dir(slug)
    cfg = G.load_config(slug)
    audit = G.read_json(pdir / "audit.json", {})
    mfiles = sorted((pdir / "metrics").glob("*.json")) if (pdir / "metrics").exists() else []
    metrics = G.read_json(mfiles[-1], None) if mfiles else None
    bp = G.read_json(pdir / "blueprint.json", None)
    td = T.load(slug)
    return cfg, audit, metrics, bp, td


# ---------------------------------------------------------------- 优化方案

def optimization_plan(slug: str) -> str:
    cfg, audit, metrics, bp, td = _load(slug)
    b = cfg["brand"]
    mk = {"cn": "Domestic (CN)", "global": "Global", "both": "Global & Domestic"}.get(cfg.get("market"))
    L = [f"# {b['name']} · GEO Strategy & Optimization Plan", "",
         f"Generated {G.today()} | Scope: **{mk}** AI Search Visibility | Official Website: {b['site']}", "",
         "This document addresses core strategic objectives: **what improvements are required and the underlying empirical rationale.**",
         "For operational execution, owners, and milestones, refer to the accompanying 《GEO Execution Plan》.", "",
         "---", "", "## 1. Current Baseline Position", ""]

    score = audit.get("avg_score")
    gd = audit.get("grade_distribution", {})
    ab = (gd.get("A", 0) + gd.get("B", 0))
    L += [f"- Average Site Score: **{score}** (out of 100; scores > 70 are considered directly usable)",
          f"- Crawled {audit.get('page_count')} pages, with **{ab}** directly citeable or usable baseline pages", ""]

    if metrics:
        for m_, name in (("cn", "Domestic (CN)"), ("global", "Global")):
            rows = [v for v in metrics["platforms"].values() if v.get("market", "cn") == m_]
            if not rows:
                continue
            mr_v = [v["mention_rate"] for v in rows if v.get("mention_rate") is not None]
            oc_v = [v["own_domain_cite_rate"] for v in rows if v.get("own_domain_cite_rate") is not None]
            mr = f"{sum(mr_v)/len(mr_v):.0%}" if mr_v else "Unmeasured"
            oc = f"{sum(oc_v)/len(oc_v):.0%}" if oc_v else "Unmeasured"
            L.append(f"- {name} Market: Across {len(rows)} model platforms, average **unprompted mention rate {mr}**, "
                     f"own domain citation rate {oc}")
        L.append("")
        L += ["> 'Unprompted Mention Rate' measures organic brand citations when the query does not contain the brand name.",
              "> Direct brand recognition queries are evaluated separately to avoid false positives.", ""]

    L += ["## 2. Strategic Optimization Layers", "",
          "GEO operates across a three-stage funnel with distinct bottlenecks at each level.", "",
          "| Layer | Current Status | Required Action |", "|---|---|---|"]

    site = audit.get("site", {})
    gate = []
    if site.get("ai_bots_blocked"):
        gate.append("Robots disallowing AI crawlers")
    if not site.get("has_sitemap"):
        gate.append("Missing sitemap")
    if not site.get("has_llms_txt"):
        gate.append("Missing llms.txt")
    spa = sum(1 for p in audit.get("pages", [])
              if "SPA_SHELL" in p.get("issue_codes", [])
              or (p.get("issue_codes") is None and p.get("word_count", 0) < 120))
    if spa:
        gate.append(f"{spa} pages with empty static HTML bodies")
    L.append(f"| ① Crawler Accessibility | {' / '.join(gate) if gate else 'Clean technical foundation'} "
             f"| {'Resolve foundational blockers before content investments' if gate else 'Maintain baseline'} |")

    own = None
    if metrics:
        vals = [v["own_domain_cite_rate"] for v in metrics["platforms"].values()
                if v.get("own_domain_cite_rate") is not None]
        own = sum(vals) / len(vals) if vals else None
    if own is None:
        L.append("| ② Citation Ingestion | Own domain cite rate unmeasured "
                 "| Run sampling cycle to establish baseline |")
    else:
        L.append(f"| ② Citation Ingestion | Own domain cite rate {own:.0%} "
                 f"| {'Expand high-authority external sources and index submissions' if own < 0.1 else 'Maintain and expand external citations'} |")

    gaps = audit.get("block_gap", [])
    top_gap = ", ".join(f"{g['block']}({g['missing_pages']}/{g['total']})" for g in gaps[:3])
    L.append(f"| ③ Answer Synthesis | Major gaps: {top_gap or '—'} "
             f"| Implement structured extraction blocks and expand core pages > 1000 words |")
    L.append("")

    L += ["## 3. High-Leverage Opportunities", "",
          "Opportunities ranked by empirical leverage based on multi-model benchmark citations.", ""]

    order = [
        ("Foundational Prerequisites", "P0", gate,
         "Robots, sitemaps, llms.txt, SPA prerendering, and schema markup. Without these, content investments fail to register."),
        ("Entity Disambiguation & Fact Grounding", "P0", b.get("disambiguation") or [],
         "Ensure factual consistency. Standardize definitions across Hero slogan, About page, JSON-LD, and llms.txt."),
        ("Information Extraction Blocks", "P1", [g["block"] for g in gaps if g["missing_pages"] >= max(3, g["total"] * .3)],
         "Empirical lift: Numeric facts +61.6%, Definitions +57.3%, Comparisons +55.3%, How-to steps +41.2%."),
        ("Authoritative External Sources", "P1", [],
         "**Official brand sites account for only 1.37% of citations across models**—the official site is a source of truth, not the primary citation link. External authority drives AI recommendations."),
        ("Content Architecture", "P1", [],
         "Each target query pattern requires tailored content structure matching AI retrieval heuristics."),
        ("Closed-Loop Measurement", "P2", [],
         "Automated periodic re-crawling and validation to prevent regression."),
    ]
    for name, pri, items, note in order:
        L += [f"### {pri} · {name}", "", note, ""]
        if items:
            L += [f"- {x}" for x in items[:6]] + [""]

    if bp:
        cov = bp["coverage"]
        L += ["## 4. Platform & Content Blueprint", "",
              f"Channel coverage **{cov['channel_covered']}/{cov['channel_total']}** "
              f"(P0/P1 critical channels {cov['p0p1_covered']}/{cov['p0p1_total']}); "
              f"Content fulfillment **{cov['content_done']}/{cov['content_total']}**.", "",
              "Key gaps requiring immediate focus:", ""]
        miss = [c for c in bp["channels"] if not c["covered"] and c["priority"] in ("P0", "P1")]
        miss.sort(key=lambda c: (-(c.get("national") or 0)))
        if miss:
            L += ["| Channel | Priority | Asset Form | Cadence | Evidence |", "|---|---|---|---|---|"]
            for c in miss[:8]:
                ev = []
                if c.get("national"):
                    ev.append(f"Citations: {c['national']:,}")
                if c.get("position"):
                    ev.append(f"Placement #{c['position']}")
                L.append(f"| {R.cell(c['name'])} | {c['priority']} | {R.cell(' / '.join(c['forms'][:2]))} "
                         f"| {R.cell(c['cadence'])} | {'; '.join(ev) or '—'} |")
            L.append("")

    L += ["## 5. Resource Allocation Recommendations", "",
          "- **Avoid over-indexing budget on full official site redesigns**. Ensure crawlers can parse definitions and structured data, then allocate resources toward external authoritative channels.",
          "- Prioritize depth over volume: High-visibility pages average 1,943 words; superficial pages under 200 words fail to be extracted.", "",
          "## 6. Objectives & Acceptance Criteria", ""]
    tg = cfg.get("targets", {})
    L += ["| Metric | Current | 90-Day Target |", "|---|---|---|",
          f"| Site Average Score | {score} | {tg.get('avg_page_score', 70)} |"]
    if metrics:
        for m_, name in (("cn", "Domestic (CN)"), ("global", "Global")):
            rows = [v for v in metrics["platforms"].values() if v.get("market", "cn") == m_]
            if rows:
                cur_v = [v["mention_rate"] for v in rows if v.get("mention_rate") is not None]
                cur = f"{sum(cur_v)/len(cur_v):.0%}" if cur_v else "Unmeasured"
                L.append(f"| {name} Unprompted Mention Rate | {cur} | {tg.get('mention_rate', .3):.0%} |")
    L += [f"| Own Domain Citation Rate | {f'{own:.0%}' if own is not None else 'Unmeasured'} | {tg.get('own_domain_cite_rate', .2):.0%} |", "",
          "## 7. Service Boundaries", "",
          "- GEO optimizes the **probability of AI citations**; no provider guarantees citation for any specific page",
          "- All brand claims, customer references, and specs must have verifiable source citations",
          "- AI answer sampling exhibits natural variance; multi-period trends should be evaluated in context",
          "- Sampling strictly follows platform terms of service without abusive scraping or unauthorized bypass", ""]
    return "\n".join(L)


# ---------------------------------------------------------------- 执行方案

def execution_plan(slug: str) -> str:
    cfg, audit, metrics, bp, td = _load(slug)
    b = cfg["brand"]
    rows = td.get("tasks", [])
    s = td.get("summary", {})
    L = [f"# {b['name']} · GEO Execution Plan", "",
         f"Generated {G.today()} | {s.get('total', 0)} total tickets "
         f"(including **{s.get('auto_verifiable', 0)} auto-verifiable tickets**)", "",
         "Defines: **assigned owners, implementation windows, actions, and acceptance criteria.**", "",
         "> Auto-verifiable tickets are evaluated deterministically upon site re-crawling.", "", "---", ""]

    L += ["## 1. Phased Milestones", ""]
    for win, label in (("30天", "Phase 1 · 0–30 Days · Foundation"),
                       ("60天", "Phase 2 · 30–60 Days · Primary Visibility Gains"),
                       ("90天", "Phase 3 · 60–90 Days · Scaling & Closed-Loop")):
        batch = [t for t in rows if t.get("window") == win or t.get("window") == f"{win[:2]} Days"]
        if not batch:
            batch = [t for t in rows if win[:2] in str(t.get("window", ""))]
        if not batch:
            continue
        done = sum(1 for t in batch if t["status"] == "done")
        L += [f"### {label} ({done}/{len(batch)} Completed)", "",
              "| ID | Task | Package | Owner | Effort | Acceptance Criteria | Status |",
              "|---|---|---|---|---|---|---|"]
        for t in sorted(batch, key=lambda x: x["priority"]):
            L.append(f"| {t['id']} | {R.cell(t['title'])} | {t['package']} | {t['owner']} "
                     f"| {T.EFFORT.get(t['effort'], t['effort'])} "
                     f"| {R.cell(t['acceptance'].get('desc',''))} "
                     f"| {STATUS_CN.get(t['status'], t['status'])} |")
        L.append("")

    L += ["## 2. Role-Based Assignments", "",
          "Direct actionable checklists organized by functional owner:", ""]
    by_owner: dict[str, list] = {}
    for t in rows:
        by_owner.setdefault(t["owner"], []).append(t)
    for owner, ts in sorted(by_owner.items(), key=lambda x: -len(x[1])):
        open_ = [t for t in ts if t["status"] != "done"]
        L += [f"### {owner} ({len(open_)} Open / {len(ts)} Total)", ""]
        for t in sorted(open_, key=lambda x: (x["priority"], x["window"])):
            L += [f"**{t['id']} · {t['title']}** | {t['priority']} | {t['window']} | "
                  f"{T.EFFORT.get(t['effort'], t['effort'])}", "",
                  f"- Rationale: {t['why']}", f"- Action: {t['action']}",
                  f"- Acceptance ({'Auto' if t['acceptance'].get('type') == 'auto' else 'Manual'}): "
                  f"{t['acceptance'].get('desc','')}"]
            if t.get("affected"):
                L.append(f"- Affects {len(t['affected'])} pages, e.g.: {t['affected'][0]}")
            L.append("")
        if not open_:
            L += ["(All tasks for this role are completed)", ""]

    adir = G.project_dir(slug) / "assets"
    if adir.exists():
        L += ["## 3. Deployable Ready-to-Use Assets", "",
              "Generated assets ready for engineering and content teams:", "",
              "| Asset | Purpose | Target Role |", "|---|---|---|"]
        m = [("llms.txt", "Root machine-readable index", "Engineering"),
             ("llms.en.txt", "English edition for frontier models", "Engineering"),
             ("jsonld/*.json", "Schema.org structured data for `<head>`", "Engineering"),
             ("snippets/definition.*.html", "Definition block below hero slogan", "Engineering"),
             ("snippets/faq.*.html", "FAQ block with static HTML visibility", "Engineering"),
             ("outlines/*.md", "Content outlines per target query", "Content"),
             ("drafts/*.md", "AI draft articles requiring human verification", "Content"),
             ("DEPLOY.md", "Deployment checklist with step verification", "Engineering")]
        for f, use, who in m:
            exists = any(adir.glob(f)) if "*" in f else (adir / f).exists()
            if exists:
                L.append(f"| `{f}` | {use} | {who} |")
        L.append("")

    L += ["## 4. Verification & Regression Policy", "",
          "1. Execute tickets according to specifications and deploy assets.",
          "2. Periodic re-crawling evaluates auto-verifiable tickets deterministically.",
          "3. Non-deterministic items are marked 'Manual Review' and confirmed by human owners.",
          "4. Detected regressions automatically revert resolved tickets to Todo status.", "",
          "Recommended Cadence: **Page audit weekly, AI sampling bi-weekly**.", ""]
    return "\n".join(L)


# ---------------------------------------------------------------- 主流程

def run(slug: str) -> Path:
    cfg = G.load_config(slug)
    pdir = G.project_dir(slug)
    out = pdir / "deliverables"
    out.mkdir(parents=True, exist_ok=True)
    name = cfg["brand"]["name"]

    reports = sorted((pdir / "reports").glob("2*")) if (pdir / "reports").exists() else []
    if reports:
        import shutil
        for src, dst in ((reports[-1] / "report.md", "1-GEO诊断报告.md"),
                         (reports[-1] / "report.html", "1-GEO诊断报告.html")):
            if src.exists():
                shutil.copy2(src, out / dst)

    audit = G.read_json(pdir / "audit.json", {})
    td = T.load(slug)

    opt = optimization_plan(slug)
    (out / "2-GEO优化方案.md").write_text(opt, "utf-8")
    (out / "2-GEO优化方案.html").write_text(
        R.build_html(f"{name} · GEO Strategy & Optimization Plan", opt,
                     [("Site Score", str(audit.get("avg_score", "—"))),
                      ("Crawled Pages", str(audit.get("page_count", "—"))),
                      ("Total Tickets", str(td.get("summary", {}).get("total", 0)))]), "utf-8")

    exe = execution_plan(slug)
    (out / "3-GEO执行方案.md").write_text(exe, "utf-8")
    s = td.get("summary", {})
    (out / "3-GEO执行方案.html").write_text(
        R.build_html(f"{name} · GEO Execution Plan", exe,
                     [("Total Tickets", str(s.get("total", 0))),
                      ("P0 Blockers", str(s.get("by_priority", {}).get("P0", 0))),
                      ("Auto Verifiable", str(s.get("auto_verifiable", 0))),
                      ("Completed", str(s.get("by_status", {}).get("done", 0)))]), "utf-8")

    G.info(f"Three core deliverables compiled → {out}")
    return out
