"""Client Delivery Package: All deliverables for the current cycle formatted for direct client handoff.

    work/<slug>/delivery/<date>/
      index.html            Client executive summary
      01-Diagnostic.html/.md Health check + AI visibility
      02-Strategy.md         30/60/90-day plan
      03-Tickets.html/.csv   Actionable items with owners and roles
      04-Verification.html   Automated validation of previous cycle items
      assets/               llms.txt / JSON-LD / HTML snippets / Outlines / Drafts
      README.md             Delivery instructions and next cycle overview

Oriented toward clients: No internal script references or debug logs, clear terminology,
conclusions based on evidence, and no commitments regarding specific platform citations.
"""

from __future__ import annotations

import csv
import html
import json
import shutil
from pathlib import Path

import geolib as G
import report as R
import tasks as T

STATUS_CN = {"todo": "Todo", "doing": "In Progress", "done": "Done",
             "blocked": "Blocked", "wontfix": "Won't Fix"}
PRI_NOTE = {"P0": "Critical blocker, foundational requirement", "P1": "Primary visibility gains", "P2": "Long-tail and scale"}


def _tasks_table_md(data: dict, market: str | None = None) -> str:
    rows = [t for t in data.get("tasks", []) if not market or t["market"] in (market, "both")]
    if not rows:
        return "_No action tickets for this market yet_\n"
    L = ["| ID | Priority | Package | Task | Owner | Effort | Window | Acceptance Criteria | Status |",
         "|---|---|---|---|---|---|---|---|---|"]
    for t in sorted(rows, key=lambda x: (x["priority"], x["package"])):
        L.append(f"| {t['id']} | {t['priority']} | {t['package']} | {R.cell(t['title'])} | "
                 f"{t['owner']} | {T.EFFORT.get(t['effort'], t['effort'])} | {t['window']} | "
                 f"{R.cell(t['acceptance'].get('desc',''))} | {STATUS_CN.get(t['status'], t['status'])} |")
    return "\n".join(L)


def _tasks_csv(data: dict, path: Path):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ID", "Priority", "Package", "Market", "Task", "Rationale", "Action",
                    "Owner", "Effort", "Window", "Acceptance Criteria", "Verification Mode", "Status", "Affected Pages"])
        for t in sorted(data.get("tasks", []), key=lambda x: (x["priority"], x["package"])):
            w.writerow([t["id"], t["priority"], t["package"], t["market"], t["title"], t["why"],
                        t["action"], t["owner"], T.EFFORT.get(t["effort"], t["effort"]), t["window"],
                        t["acceptance"].get("desc", ""),
                        "Auto" if t["acceptance"].get("type") == "auto" else "Manual",
                        STATUS_CN.get(t["status"], t["status"]), len(t.get("affected", []))])


def _overview_md(cfg, audit, metrics, data, verify_report, notes=None) -> str:
    b = cfg["brand"]
    s = data.get("summary", {})
    mk = {"cn": "Domestic (CN)", "global": "Global", "both": "Global & Domestic"}.get(cfg.get("market"), cfg.get("market"))
    L = [f"# {b['name']} · GEO Client Delivery Package · {G.today()}", "",
         f"- Service Scope: **{mk}** AI Search Visibility",
         f"- Official Website: {b['site']}",
         f"- Crawled Pages: {audit.get('page_count')} pages, Average Site Score **{audit.get('avg_score')}**",
         ""]
    if metrics:
        L.append(f"- AI Answer Sampling: {metrics.get('sample_count')} samples ({metrics.get('date')}), "
                 f"covering {len(metrics.get('platforms', {}))} frontier model platforms")
    L += ["", "## Package Deliverables", "",
          "| File | Content |", "|---|---|",
          "| `01-Diagnostic.html` | Technical baseline, page audit, AI visibility, benchmark comparison |",
          "| `02-Strategy.md` | 30/60/90-day roadmap, six work packages, resource tradeoffs |",
          "| `03-Tickets.html` / `.csv` | Direct actionable engineering tickets with owners and acceptance criteria |",
          "| `04-Verification.html` | Automated verification matrix from previous cycle tickets |",
          "| `05-Draft-Risks.html` | AI draft risk inspection log requiring human verification |",
          "| `06-Blueprint.html` | Platform distribution, target content assets, and coverage matrix |",
          "| `assets/` | Deployable assets: llms.txt, JSON-LD schemas, HTML snippets, and content outlines |",
          "", "## Ticket Overview", "",
          f"- Total: **{s.get('total', 0)}** tickets, including **{s.get('auto_verifiable', 0)}** auto-verifiable",
          f"- Priority: P0 {s.get('by_priority', {}).get('P0', 0)} ({PRI_NOTE['P0']}) / "
          f"P1 {s.get('by_priority', {}).get('P1', 0)} ({PRI_NOTE['P1']}) / "
          f"P2 {s.get('by_priority', {}).get('P2', 0)} ({PRI_NOTE['P2']})",
          f"- Progress: " + ", ".join(f"{STATUS_CN.get(k, k)} {v}" for k, v in s.get("by_status", {}).items() if v),
          ""]
    if s.get("by_package"):
        L += ["Distribution by Work Package:", ""]
        L += [f"- {k}: {v} tickets" for k, v in s["by_package"].items()]
        L.append("")
    if verify_report:
        p = sum(1 for r in verify_report["results"] if r["verdict"] == "通过" or r["verdict"] == "pass")
        f_ = sum(1 for r in verify_report["results"] if r["verdict"] == "未达标" or r["verdict"] == "fail")
        m_ = sum(1 for r in verify_report["results"] if r["verdict"] == "待人工" or r["verdict"] == "manual")
        L += ["## Previous Cycle Verification", "",
              f"Automated Verification: **Passed {p}** / Unmet {f_} / Manual Review {m_}", ""]
    if notes:
        L += ["## Data Methodology Notes", ""]
        L += [f"- {n}" for n in notes]
        L.append("")
    L += ["## How to Use This Package", "",
          "1. Review 'Executive Summary' and 'Action Tickets' in `01-Diagnostic.html`",
          "2. Import `03-Tickets.csv` into your issue tracker (Jira/Linear/GitHub) and assign to owners",
          "3. Deliver files in `assets/` directly to engineering for deployment (llms.txt, JSON-LD, snippets)",
          "4. Assign `assets/outlines/` to content teams; inspect `assets/drafts/` against `05-Draft-Risks.html` before publishing",
          "5. Next cycle will re-crawl and re-sample to verify resolved tickets automatically",
          "", "## Service Boundary", "",
          "- GEO maximizes the **probability of AI citations**; no provider guarantees citation for any specific page",
          "- All brand claims, customer references, and specs must have verifiable source citations",
          "- AI answer sampling exhibits natural variance; multi-period trends should be evaluated in context",
          "- Sampling strictly follows platform terms of service without abusive scraping or unauthorized bypass",
          ""]
    return "\n".join(L)


def _readme(cfg, data, notes=None) -> str:
    b = cfg["brand"]
    extra = ""
    if notes:
        extra = "\n## Data Methodology Notes\n\n" + "\n".join(f"- {n}" for n in notes) + "\n"
    return f"""# Delivery Notes

This directory contains the GEO (Generative Engine Optimization) delivery package for **{b['name']}** ({G.today()}).
{extra}
## Directory Structure

```
index.html            ← Executive overview (start here)
01-Diagnostic.html/.md GEO diagnostic report & AI visibility
02-Strategy.md         Strategy & execution plan
03-Tickets.html/.csv   Engineering & content action tickets
04-Verification.html   Closed-loop verification matrix
assets/
  llms.txt            Root ingestion index
  llms.en.txt         English edition for global models
  jsonld/             Schema.org structured data
  snippets/           Definition and FAQ HTML snippets
  outlines/           Content structure outlines
  drafts/             AI draft articles
```

## Recommended Deployment Sequence

1. **Resolve P0 tickets first**: Foundational requirements for AI crawler visibility
2. `assets/llms.txt` → Deploy to `{b['site'].rstrip('/')}/llms.txt`
3. `assets/jsonld/*.json` → Inject into corresponding page `<head>`
4. `assets/snippets/definition.*.html` → Place below hero slogan
5. `assets/snippets/faq.*.html` → Ensure answers are visible in raw static HTML

## Next Cycle

Re-running crawl and sampling will trigger automated ticket verification. Recommended cadence: **Page audit weekly, AI sampling bi-weekly**.

## Consistency Discipline

Standardize your one-sentence brand definition across four surfaces: Hero slogan, About page, JSON-LD `description`, and `llms.txt`.
"""


def run(slug: str) -> Path:
    cfg = G.load_config(slug)
    pdir = G.project_dir(slug)
    audit = G.read_json(pdir / "audit.json", {})
    if not audit:
        G.die("Missing audit.json, run cycle first")
    data = T.load(slug)
    if not data.get("tasks"):
        G.die("No action tickets found. Run plan first: python3 scripts/geo.py plan --slug " + slug)

    files = sorted((pdir / "metrics").glob("*.json")) if (pdir / "metrics").exists() else []
    metrics = G.read_json(files[-1], None) if files else None
    import verify as V
    vfiles = sorted((pdir / "verify").glob("*.json"), key=V.report_key) \
        if (pdir / "verify").exists() else []
    vrep = G.read_json(vfiles[-1], None) if vfiles else None

    # 本期体检日期：报告与验收的日期口径都以它为准
    audit_date = str(audit.get("audited_at", ""))[:10]
    notes = []  # 交付包口径说明：日期不一致必须显式标注，不能静默混入

    # 验收日期早于本期体检日期（或没有验收记录）视为「本期未验收」
    vrep_date = str(vrep.get("verified_at", ""))[:10] if vrep else ""
    unverified = not vrep or bool(audit_date and vrep_date < audit_date)
    if unverified:
        notes.append("Unverified for this cycle: " + ("No verification records found yet" if not vrep else
                     f"Latest verification date {vrep_date} is older than current audit date {audit_date}"))

    out = pdir / "delivery" / G.today()
    # 当日目录整体重建：04/05/06 是条件生成的，只增量写会让上次生成的旧文件残留
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True, exist_ok=True)

    # 01 诊断报告：报告目录日期必须与本期体检日期一致。
    # 今天有体检但报告是旧的，先补跑一次报告；仍不一致则在 README/总览里标注。
    reports = sorted((pdir / "reports").glob("2*")) if (pdir / "reports").exists() else []
    if audit_date and audit_date == G.today() and (not reports or reports[-1].name != audit_date):
        try:
            R.run(slug)
            reports = sorted((pdir / "reports").glob("2*"))
        except Exception as e:  # noqa: BLE001
            G.info(f"Failed to re-run diagnostic report: {e}")
    if reports:
        latest = reports[-1]
        if audit_date and latest.name != audit_date:
            notes.append(f"Diagnostic report date {latest.name}, current audit date {audit_date}; "
                         f"report content is based on data from {latest.name}")
        for src, dst in ((latest / "report.html", "01-Diagnostic.html"),
                         (latest / "report.md", "01-Diagnostic.md")):
            if src.exists():
                shutil.copy2(src, out / dst)

    # 02 执行方案
    plan = pdir / "plan.md"
    if plan.exists():
        shutil.copy2(plan, out / "02-Strategy.md")

    # 03 工单表
    mk = cfg.get("market", "global")
    md = [f"# {cfg['brand']['name']} · GEO Action Tickets · {G.today()}", "",
          "Each ticket has an assigned owner and acceptance criteria. Auto-verifiable tickets are evaluated deterministically.", ""]
    if mk == "both":
        md += ["## Domestic Market (CN) & General", "", _tasks_table_md(data, "cn"), "",
               "## Global Market", "", _tasks_table_md(data, "global"), ""]
    else:
        md += [_tasks_table_md(data), ""]
    md += ["## Ticket Breakdown", ""]
    for t in sorted(data["tasks"], key=lambda x: (x["priority"], x["package"])):
        md += [f"### {t['id']} · {t['title']}", "",
               f"- Priority **{t['priority']}** | Package {t['package']} | Market {t['market']} | "
               f"Owner {t['owner']} | Effort {T.EFFORT.get(t['effort'], t['effort'])} | Window {t['window']}",
               f"- **Rationale**: {t['why']}",
               f"- **Action**: {t['action']}",
               f"- **Acceptance** ({'Auto' if t['acceptance'].get('type')=='auto' else 'Manual'}): {t['acceptance'].get('desc','')}",
               f"- Current Status: {STATUS_CN.get(t['status'], t['status'])}"]
        if t.get("affected"):
            md.append(f"- Affects {len(t['affected'])} pages, first 3: "
                      + ", ".join(t["affected"][:3]))
        md.append("")
    tasks_md = "\n".join(md)
    (out / "03-Tickets.md").write_text(tasks_md, "utf-8")
    (out / "03-Tickets.html").write_text(
        R.build_html(f"{cfg['brand']['name']} GEO Action Tickets", tasks_md,
                     [("Total Tickets", str(data["summary"]["total"])),
                      ("P0 Blockers", str(data["summary"]["by_priority"]["P0"])),
                      ("Auto Verifiable", str(data["summary"]["auto_verifiable"])),
                      ("Completed", str(data["summary"]["by_status"].get("done", 0)))]), "utf-8")
    _tasks_csv(data, out / "03-Tickets.csv")

    # 04 验收表
    if vrep and not unverified:
        vm = [f"# Action Ticket Verification Matrix · {vrep['verified_at'][:10]}", "",
              f"Re-crawl site average score **{vrep.get('audit_avg_score')}**; status updated for {vrep.get('changed')} tickets.", "",
              "| ID | Task | Priority | Verdict | Rationale |", "|---|---|---|---|---|"]
        for r in vrep["results"]:
            vm.append(f"| {r['id']} | {R.cell(r['title'])} | {r['priority']} | "
                      f"{r['verdict']} | {R.cell(r['note'])} |")
        vm += ["", "> 'Manual Review' indicates items that cannot be evaluated purely by crawler scripts and require human confirmation.", ""]
        vmd = "\n".join(vm)
        (out / "04-Verification.md").write_text(vmd, "utf-8")
        (out / "04-Verification.html").write_text(
            R.build_html(f"{cfg['brand']['name']} Verification Matrix", vmd,
                         [("Passed", str(sum(1 for r in vrep["results"] if r["verdict"] in ("通过", "pass")))),
                          ("Unmet", str(sum(1 for r in vrep["results"] if r["verdict"] in ("未达标", "fail")))),
                          ("Manual Review", str(sum(1 for r in vrep["results"] if r["verdict"] in ("待人工", "manual"))))]), "utf-8")
    else:
        reason = "No verification records found yet" if not vrep else \
            f"Latest verification date {vrep_date} is older than current audit date {audit_date or 'unknown'}"
        vmd = "\n".join([
            f"# Action Ticket Verification Matrix · {G.today()}", "",
            f"**Unverified for this cycle**: {reason}.", "",
            "Verification requires re-crawling after current audit; previous results omitted to prevent data confusion.", ""])
        (out / "04-Verification.md").write_text(vmd, "utf-8")
        (out / "04-Verification.html").write_text(
            R.build_html(f"{cfg['brand']['name']} Verification Matrix", vmd,
                         [("Status", "Unverified for this cycle")]), "utf-8")

    # 05 初稿风险清单
    lint = G.read_json(pdir / "assets" / "drafts" / "_lint.json", None)
    if lint and lint.get("total_issues"):
        lm = [f"# AI Draft Risk Inspection · {G.today()}", "",
              f"Generated {len(lint['files'])} AI draft articles, identified **{lint['total_issues']} items** requiring human verification, "
              f"including **{lint['high']} high-risk items**.", "",
              "> **These drafts must not be published before verification is complete.**", "",
              "| File | Risk Level | Type | Description | Original Excerpt |", "|---|---|---|---|---|"]
        for fn, issues in lint["files"].items():
            for i in issues:
                lm.append(f"| `{fn}` | {i['level']} | {i['type']} | {R.cell(i['detail'])} | {R.cell(i['excerpt'][:60])} |")
        lm += ["", "## Action Guidelines", "",
               "- **High Risk**: Remove placeholders and verify authentic competitor facts",
               "- **Medium Risk (Unverified figures)**: Attach factual citations or mark as pending verification",
               "- **Low Risk (Year stamps)**: Update to current year", ""]
        lmd = "\n".join(lm)
        (out / "05-Draft-Risks.md").write_text(lmd, "utf-8")
        (out / "05-Draft-Risks.html").write_text(
            R.build_html(f"{cfg['brand']['name']} AI Draft Risk Inspection", lmd,
                         [("Drafts", str(len(lint["files"]))),
                          ("Items to Verify", str(lint["total_issues"])),
                          ("High Risk", str(lint["high"]))]), "utf-8")

    # 06 建设地图
    bp = G.read_json(pdir / "blueprint.json", None)
    if bp:
        cov = bp["coverage"]
        bm = [f"# GEO Architecture Blueprint · {G.today()}", "",
              "Answers two core questions: **which platforms to build on**, and **what content to deploy**.", "",
              f"- Channel Coverage: **{cov['channel_covered']}/{cov['channel_total']}** "
              f"(P0/P1 Critical Channels {cov['p0p1_covered']}/{cov['p0p1_total']})",
              f"- Content Fulfillment: **{cov['content_done']}/{cov['content_total']}** target questions with completed drafts", "",
              "## 1. Platform Distribution", ""]
        for pri in ("P0", "P1", "P2"):
            rows = [c for c in bp["channels"] if c["priority"] == pri]
            if not rows:
                continue
            note = {"P0": "Foundational, core requirement", "P1": "Primary visibility gains", "P2": "Scale"}[pri]
            bm += [f"### {pri} · {note} (Covered {sum(1 for c in rows if c['covered'])}/{len(rows)})", "",
                   "| Channel | Status | Asset Form | Volume | Cadence | Owner | Evidence |",
                   "|---|---|---|---|---|---|---|"]
            for c in rows:
                ev = []
                if c.get("national"):
                    ev.append(f"Citations: {c['national']:,}")
                if c.get("position"):
                    ev.append(f"Placement #{c['position']}")
                if c.get("platforms"):
                    ev.append(f"{c['platforms']} platforms")
                bm.append(f"| {R.cell(c['name'])} | {'✓ Cited' if c['covered'] else 'Gap'} "
                          f"| {R.cell(' / '.join(c['forms']))} | {R.cell(c['volume'])} "
                          f"| {R.cell(c['cadence'])} | {c['owner']} | {'; '.join(ev) or '—'} |")
            bm.append("")
        bm += ["## 2. Content Architecture", ""]
        by_form: dict[str, list] = {}
        for c in bp["contents"]:
            by_form.setdefault(c["form"], []).append(c)
        for form, lst in by_form.items():
            done = sum(1 for x in lst if x["status"] in ("已成稿", "done", "ready"))
            bm += [f"### {form} · {len(lst)} questions (Drafts completed: {done})", "",
                   f"_{lst[0]['note']}_", "",
                   "| Target Question | Group | Market | Status |", "|---|---|---|---|"]
            for c in lst:
                mk = {"cn": "Domestic", "global": "Global"}.get(c["market"], "General")
                bm.append(f"| {R.cell(c['question'])} | {c['group']} | {mk} | {c['status']} |")
            bm.append("")
        bm += ["## 3. Phased Roadmap", ""]
        for r in bp["roadmap"]:
            bm += [f"**{r['window']} · {r['focus']}**", ""] + [f"- {i}" for i in r["items"]] + [""]
        bm += ["---", "",
               "**Golden Rule**: Official brand sites account for only **1.37%** of citations across generative models.",
               "The official site is the **source of truth**, not the primary citation link. External authority drives AI recommendations.", ""]
        bmd = "\n".join(bm)
        (out / "06-建设地图.md").write_text(bmd, "utf-8")
        (out / "06-建设地图.html").write_text(
            R.build_html(f"{cfg['brand']['name']} GEO Blueprint", bmd,
                         [("Channel Coverage", f"{cov['channel_covered']}/{cov['channel_total']}"),
                          ("Critical Channels", f"{cov['p0p1_covered']}/{cov['p0p1_total']}"),
                          ("Content Fulfillment", f"{cov['content_done']}/{cov['content_total']}"),
                          ("Content Gaps", str(cov["content_gap"] + sum(
                              1 for c in bp["contents"] if c["status"] in ("仅大纲", "outline_only"))))]), "utf-8")

    # assets
    adir = pdir / "assets"
    if adir.exists():
        dst = out / "assets"
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(adir, dst)

    # index + README
    ov = _overview_md(cfg, audit, metrics, data, None if unverified else vrep, notes)
    (out / "index.md").write_text(ov, "utf-8")
    cards = [("Site Score", str(audit.get("avg_score"))),
             ("Crawled Pages", str(audit.get("page_count"))),
             ("Total Tickets", str(data["summary"]["total"])),
             ("P0 Blockers", str(sum(1 for t in data["tasks"]
                                 if t["priority"] == "P0" and t["status"] != "done")))]
    if metrics:
        rates = [m["mention_rate"] for m in metrics["platforms"].values()
                 if m.get("mention_rate") is not None]
        if rates:
            cards.append(("平均提及率", f"{sum(rates)/len(rates):.0%}"))
    (out / "index.html").write_text(
        R.build_html(f"{cfg['brand']['name']} · GEO 服务交付 {G.today()}", ov, cards), "utf-8")
    (out / "README.md").write_text(_readme(cfg, data, notes), "utf-8")

    G.info(f"Delivery package compiled → {out}")
    return out
