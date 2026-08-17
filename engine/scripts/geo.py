#!/usr/bin/env python3
"""GEO automation pipeline CLI.

  python3 scripts/geo.py init --url https://example.com --name BrandName
  python3 scripts/geo.py crawl        --slug example
  python3 scripts/geo.py audit        --slug example
  python3 scripts/geo.py sample       --slug example
  python3 scripts/geo.py sample-sheet --slug example
  python3 scripts/geo.py sample-import --slug example --file work/example/samples/2026-07-26-manual.md
  python3 scripts/geo.py report       --slug example
  python3 scripts/geo.py cycle        --slug example
  python3 scripts/geo.py list
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import geolib as G  # noqa: E402
except ModuleNotFoundError as e:
    raise SystemExit(f"Missing dependency: {e.name}. Please run: pip3 install requests beautifulsoup4 lxml") from e

DEFAULT_PLATFORMS = {
    "cn": ["glm", "doubao", "deepseek", "kimi", "minimax", "nano_ai", "baidu"],
    "global": ["gemini", "openai", "claude", "grok", "perplexity", "deepseek", "chatgpt"],
    "both": ["glm", "doubao", "deepseek", "kimi", "minimax", "nano_ai", "baidu",
             "gemini", "openai", "claude", "grok", "perplexity", "chatgpt"],
}


def cmd_init(a):
    url = a.url.strip().rstrip("/")
    if "://" not in url:
        url = "https://" + url
    try:
        parsed = urlparse(url)
    except ValueError:
        G.die("Site URL must use http or https and include a valid hostname")
    host = G.normalize_host(url)
    if (parsed.scheme not in ("http", "https") or not host
            or parsed.username is not None or parsed.password is not None):
        G.die("Site URL must use http or https and include a valid hostname")
    if a.max_pages < 1:
        G.die("max_pages must be at least 1")
    if a.market not in ("cn", "global", "both"):
        G.die("market must be one of: cn, global, both")
    slug = a.slug or G.slugify(host.split(".")[0])

    # Existing projects require an explicit force reset.
    existing = G.project_dir(slug) / "geo.json"
    if existing.exists() and not getattr(a, "force", False):
        cur = G.read_json(existing, {})
        G.die(f"Project `{slug}` already exists ({len(cur.get('questions', []))} questions, "
              f"{len(cur.get('competitors', []))} competitors). Choose another --slug or use --force to reset it")
    if getattr(a, "force", False) and existing.parent.exists():
        archive = G.current_work() / ".archive"
        archive.mkdir(parents=True, exist_ok=True)
        destination = archive / f"{slug}-{G.new_run_id('reset')}"
        existing.parent.replace(destination)
        G.info(f"Previous project archived before force initialization: {destination}")

    name = a.name
    if not name:
        res = G.fetch(url)
        if res["html"]:
            soup = G.parse_html(res["html"])
            title = soup.title.get_text(" ", strip=True) if soup.title else ""
            name = (title.split("|")[0].split("-")[0].split("_")[0].strip() or host)[:40]
        else:
            name = host

    cfg = {
        "slug": slug,
        "created_at": G.now_iso(),
        "market": a.market,
        "brand": {
            "name": name,
            "aliases": [],
            "site": url,
            "products": [],
            "industry": "",
            "target_users": "",
            "business_goal": "",
        },
        "competitors": [],
        "platforms": DEFAULT_PLATFORMS[a.market],
        "pages": {"seed": [], "max": a.max_pages},
        "questions": [],
        "materials": [],
        "targets": {"mention_rate": 0.5, "top3_rate": 0.3, "avg_page_score": 75},
        "notes": "Populate questions, competitors, and aliases during bootstrap",
    }
    G.save_config(slug, cfg)
    for sub in ("evidence", "samples", "metrics", "reports", "history", "content"):
        (G.project_dir(slug) / sub).mkdir(parents=True, exist_ok=True)
    print(f"[geo] Project initialized: {G.project_dir(slug)/'geo.json'} (Brand: {name})")
    print("[geo] Next step: Populate brand/competitors/questions, then run crawl")
    return cfg


def cmd_bootstrap(a):
    import bootstrap

    bootstrap.run(a.slug, skip_llm=a.skip_llm)


def cmd_deliverables(a):
    import deliverables

    deliverables.run(a.slug)


def cmd_new(a):
    """Run the complete pipeline from a single site URL."""
    import audit as A
    import blueprint as BP
    import bootstrap
    import crawl as C
    import deliver
    import deliverables as DV
    import generate
    import report as Rp
    import sample as S
    import tasks
    import verify as V

    G.info("═══ 1/9 Initialize Project ═══")
    cfg = cmd_init(a)
    slug = cfg["slug"]
    G.info("═══ 2/9 Crawl Website ═══")
    C.run(slug, max_pages=a.max_pages)
    G.info("═══ 3/9 Site Audit ═══")
    A.run(slug)
    G.info("═══ 4/9 Bootstrap Baseline & Question Bank ═══")
    bootstrap.run(slug, skip_llm=a.skip_llm)
    G.info("═══ 5/9 Re-run Site Audit ═══")
    A.run(slug)
    G.info("═══ 6/9 AI Sampling ═══")
    if a.no_sample:
        G.info("Skipped: --no-sample")
    elif not G.load_config(slug).get("questions"):
        G.info("Skipped: questions library is empty")
    else:
        try:
            S.run(slug, limit=a.limit)
        except Exception as e:  # noqa: BLE001
            G.info(f"Sampling skipped: {type(e).__name__}: {e}")
    G.info("═══ 7/9 Action Tickets & Blueprint ═══")
    tasks.build(slug)
    BP.build(slug)
    G.info("═══ 8/9 Assets & Diagnostic Report ═══")
    generate.run(slug, with_draft=a.draft, draft_limit=a.draft_limit)
    Rp.run(slug)
    G.info("═══ 9/9 Deliverables & Delivery Package ═══")
    DV.run(slug)
    try:
        V.run(slug, recrawl=False)
    except Exception as e:  # noqa: BLE001
        G.info(f"Verification failed: {e}")
    deliver.run(slug)
    G.info("")
    G.info(f"Complete. Deliverables saved to work/{slug}/deliverables/:")
    G.info("")


def cmd_autopilot(a):
    """Run the complete onboarding pipeline for an existing project."""
    import audit as A
    import blueprint as BP
    import bootstrap
    import crawl as C
    import deliver
    import deliverables as DV
    import generate
    import report as Rp
    import sample as S
    import tasks
    import verify as V

    cfg = G.load_config(a.slug)
    G.info("═══ 1/8 Crawl Website ═══")
    C.run(a.slug)
    G.info("═══ 2/8 Site Audit ═══")
    A.run(a.slug)
    if not cfg.get("questions"):
        G.info("═══ 3/8 Bootstrap Baseline & Question Bank ═══")
        bootstrap.run(a.slug, skip_llm=a.skip_llm)
        A.run(a.slug)
    else:
        G.info("═══ 3/8 Existing questions found, skipping bootstrap ═══")
    G.info("═══ 4/8 AI Sampling ═══")
    if a.no_sample:
        G.info("Skipped: --no-sample")
    elif G.load_config(a.slug).get("questions"):
        try:
            S.run(a.slug, limit=a.limit)
        except Exception as e:  # noqa: BLE001
            G.info(f"Sampling skipped: {type(e).__name__}: {e}")
    G.info("═══ 5/8 Action Tickets & Blueprint ═══")
    tasks.build(a.slug)
    BP.build(a.slug)
    G.info("═══ 6/8 Assets & Diagnostic Report ═══")
    generate.run(a.slug)
    Rp.run(a.slug)
    G.info("═══ 7/8 Three Core Deliverables ═══")
    DV.run(a.slug)
    G.info("═══ 8/8 Verification & Delivery Package ═══")
    try:
        V.run(a.slug, recrawl=False)
    except Exception as e:  # noqa: BLE001
        G.info(f"Verification failed: {e}")
    deliver.run(a.slug)
    G.info("Complete. Three deliverables compiled in deliverables/.")


def cmd_crawl(a):
    import crawl

    crawl.run(a.slug, max_pages=a.max_pages)


def cmd_audit(a):
    import audit

    audit.run(a.slug)


def cmd_sample(a):
    import sample

    sample.run(a.slug, platforms=a.platforms.split(",") if a.platforms else None,
               repeat=a.repeat, limit=a.limit)


def cmd_sheet(a):
    import sample

    sample.sheet(a.slug)


def cmd_import(a):
    import sample

    sample.sample_import(a.slug, a.file)


def cmd_report(a):
    import report

    report.run(a.slug)


def cmd_cycle(a):
    import audit
    import crawl
    import report
    import sample

    G.info("=== 1/4 Crawl ===")
    crawl.run(a.slug, max_pages=a.max_pages)
    G.info("=== 2/4 Site Audit ===")
    audit.run(a.slug)
    G.info("=== 3/4 Sampling ===")
    # Sampling failure must not prevent the remaining cycle outputs.
    if not G.load_config(a.slug).get("questions"):
        G.info("Skipped sampling: question library is empty")
    else:
        try:
            sample.run(a.slug, limit=a.limit)
        except Exception as e:  # noqa: BLE001
            G.info(f"Sampling skipped: {type(e).__name__}: {e}")
    G.info("=== 4/4 Report ===")
    report.run(a.slug)


def cmd_expand(a):
    import expand
    expand.run(a.slug, use_llm=not a.no_llm)


def cmd_plan(a):
    import tasks

    tasks.build(a.slug)


def cmd_blueprint(a):
    import blueprint

    blueprint.build(a.slug)


def cmd_generate(a):
    import generate

    generate.run(a.slug, which=a.asset.split(",") if a.asset else None,
                 with_draft=a.draft, draft_limit=a.draft_limit)


def cmd_lint(a):
    import generate

    rep = generate.lint_all(a.slug)
    if not rep["files"]:
        print("No AI drafts found to check (generate with generate --draft)")
        return
    print(f"\nInspected {len(rep['files'])} drafts, {rep['total_issues']} issues found ({rep['high']} high risk)")
    for fn, issues in rep["files"].items():
        if not issues:
            print(f"\n  {fn}: No risk issues")
            continue
        print(f"\n  {fn}")
        for i in issues:
            print(f"    [{i['level']}] {i['type']}：{i['detail']}")
            print(f"          …{i['excerpt'][:76]}")
    print("\nHigh-risk items must be resolved before publishing.\n")


def cmd_verify(a):
    import verify

    verify.run(a.slug, recrawl=not a.no_recrawl)


def cmd_deliver(a):
    import deliver

    deliver.run(a.slug)


def cmd_publish(a):
    import publish

    r = publish.publish(a.slug, a.platform, a.path, a.title or "")
    if r.get("ok"):
        G.info(f"Published: {r.get('url') or r.get('note') or 'ok'}")
    else:
        G.die(f"Publish failed: {r.get('error')}")


def cmd_task(a):
    import tasks

    if a.status:
        try:
            tasks.set_status(a.slug, a.id, a.status, a.note or "")
        except KeyError as e:
            G.die(e.args[0] if e.args else str(e))
    else:
        data = tasks.load(a.slug)
        t = next((x for x in data["tasks"] if x["id"] == a.id), None)
        if not t:
            G.die(f"Ticket not found: {a.id}")
        print(json.dumps(t, ensure_ascii=False, indent=2))


def cmd_status(a):
    import tasks

    cfg = G.load_config(a.slug)
    audit = G.read_json(G.project_dir(a.slug) / "audit.json", {})
    data = tasks.load(a.slug)
    s = data.get("summary", {})
    print(f"\n{cfg['brand']['name']}  ({cfg.get('market')})  {cfg['brand']['site']}")
    print(f"  Site average score {audit.get('avg_score', '—')}  Pages {audit.get('page_count', '—')}"
          f"  Tickets {s.get('total', 0)} (auto-verifiable {s.get('auto_verifiable', 0)})")
    if not data.get("tasks"):
        print("  No tickets found. Run plan to generate.\n")
        return
    for pri in ("P0", "P1", "P2"):
        rows = [t for t in data["tasks"] if t["priority"] == pri]
        if not rows:
            continue
        done = sum(1 for t in rows if t["status"] == "done")
        print(f"\n  {pri}  {done}/{len(rows)} completed")
        for t in sorted(rows, key=lambda x: (x["status"] != "todo", x["package"])):
            mark = {"done": "✓", "doing": "◐", "blocked": "✗", "wontfix": "—"}.get(t["status"], "·")
            print(f"    {mark} {t['id']} [{t['package']}/{t['owner']}/{t['market']}] {t['title']}")
    print()


def cmd_serve(a):
    """Run the complete service cycle in one command."""
    import audit as A
    import crawl as C
    import deliver
    import generate
    import report as Rp
    import sample as S
    import tasks
    import verify as V

    G.info("═══ 1/7 Crawl ═══")
    C.run(a.slug, max_pages=a.max_pages)
    G.info("═══ 2/7 Site Audit ═══")
    A.run(a.slug)
    G.info("═══ 3/7 AI Sampling ═══")
    if not G.load_config(a.slug).get("questions"):
        G.info("Skipped: questions library is empty")
    elif a.no_sample:
        G.info("Skipped: --no-sample")
    else:
        try:
            S.run(a.slug, limit=a.limit)
        except Exception as e:  # noqa: BLE001
            G.info(f"Sampling skipped: {type(e).__name__}: {e}")
    try:
        import expand
        expand.run(a.slug)
    except Exception as e:  # noqa: BLE001
        G.info(f"Query expansion skipped: {type(e).__name__}: {e}")
    G.info("═══ 4/7 Action Tickets & Blueprint ═══")
    tasks.build(a.slug)
    import blueprint
    blueprint.build(a.slug)
    G.info("═══ 5/7 Generate Assets ═══")
    generate.run(a.slug, with_draft=a.draft, draft_limit=a.draft_limit)
    G.info("═══ 6/7 Report ═══")
    Rp.run(a.slug)
    G.info("═══ 7/7 Verify Previous Tickets ═══")
    V.run(a.slug, recrawl=False)
    G.info("═══ Compile Delivery Package ═══")
    deliver.run(a.slug)


def cmd_ui(a):
    import dashboard

    dashboard.run(port=a.port, open_browser=not a.no_open)


def cmd_list(a):
    if not G.current_work().exists():
        print("No projects found")
        return
    for d in sorted(G.current_work().iterdir()):
        cfg_path = d / "geo.json"
        if cfg_path.exists():
            cfg = G.read_json(cfg_path, {})
            reports = sorted((d / "reports").glob("2*")) if (d / "reports").exists() else []
            last = reports[-1].name if reports else "—"
            print(f"{d.name:20s} {cfg.get('brand', {}).get('name', ''):22s} Questions: {len(cfg.get('questions', [])):3d}  Latest report: {last}")


def main():
    G.load_env()
    p = argparse.ArgumentParser(prog="geo", description="GEO automation pipeline")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="Create a project")
    s.add_argument("--url", required=True)
    s.add_argument("--name")
    s.add_argument("--slug")
    s.add_argument("--market", choices=["cn", "global", "both"], default="cn")
    s.add_argument("--max-pages", type=int, default=25, dest="max_pages")
    s.add_argument("--force", action="store_true", help="Archive and rebuild an existing project")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("new", help="Run the complete pipeline from a site URL")
    s.add_argument("--url", required=True)
    s.add_argument("--name")
    s.add_argument("--slug")
    s.add_argument("--market", choices=["cn", "global", "both"], default="both")
    s.add_argument("--max-pages", type=int, default=25, dest="max_pages")
    s.add_argument("--limit", type=int, default=None, help="Sample only the first N questions")
    s.add_argument("--no-sample", action="store_true", dest="no_sample")
    s.add_argument("--skip-llm", action="store_true", dest="skip_llm", help="Skip LLM-assisted bootstrap")
    s.add_argument("--draft", action="store_true")
    s.add_argument("--draft-limit", type=int, default=3, dest="draft_limit")
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_new)

    s = sub.add_parser("autopilot", help="Run complete onboarding for an existing project")
    s.add_argument("--slug", required=True)
    s.add_argument("--limit", type=int, default=None)
    s.add_argument("--no-sample", action="store_true", dest="no_sample")
    s.add_argument("--skip-llm", action="store_true", dest="skip_llm")
    s.set_defaults(func=cmd_autopilot)

    s = sub.add_parser("bootstrap", help="Derive brand facts, competitors, and questions")
    s.add_argument("--slug", required=True)
    s.add_argument("--skip-llm", action="store_true", dest="skip_llm")
    s.set_defaults(func=cmd_bootstrap)

    s = sub.add_parser("deliverables", help="Compile diagnostic, optimization, and execution deliverables")
    s.add_argument("--slug", required=True)
    s.set_defaults(func=cmd_deliverables)

    s = sub.add_parser("crawl", help="Crawl the official site")
    s.add_argument("--slug", required=True)
    s.add_argument("--max-pages", type=int, default=None, dest="max_pages")
    s.set_defaults(func=cmd_crawl)

    s = sub.add_parser("audit", help="Run the page-level GEO audit")
    s.add_argument("--slug", required=True)
    s.set_defaults(func=cmd_audit)

    s = sub.add_parser("sample", help="Sample answers through configured APIs")
    s.add_argument("--slug", required=True)
    s.add_argument("--platforms", help="Comma-separated platform IDs")
    s.add_argument("--repeat", type=int, default=1, help="Samples per question")
    s.add_argument("--limit", type=int, default=None, help="Sample only the first N questions")
    s.set_defaults(func=cmd_sample)

    s = sub.add_parser("sample-sheet", help="Export a manual sampling sheet")
    s.add_argument("--slug", required=True)
    s.set_defaults(func=cmd_sheet)

    s = sub.add_parser("sample-import", help="Import a manual sampling sheet")
    s.add_argument("--slug", required=True)
    s.add_argument("--file", required=True)
    s.set_defaults(func=cmd_import)

    s = sub.add_parser("report", help="Generate the diagnostic report")
    s.add_argument("--slug", required=True)
    s.set_defaults(func=cmd_report)

    s = sub.add_parser("cycle", help="Run crawl, audit, sampling, and report")
    s.add_argument("--slug", required=True)
    s.add_argument("--max-pages", type=int, default=None, dest="max_pages")
    s.add_argument("--limit", type=int, default=None)
    s.set_defaults(func=cmd_cycle)

    s = sub.add_parser("expand", help="Expand candidate questions from search suggestions")
    s.add_argument("--slug", required=True)
    s.add_argument("--no-llm", action="store_true", dest="no_llm",
                   help="Use templates instead of LLM question rewriting")
    s.set_defaults(func=cmd_expand)

    s = sub.add_parser("plan", help="Convert findings into structured tickets")
    s.add_argument("--slug", required=True)
    s.set_defaults(func=cmd_plan)

    s = sub.add_parser("blueprint", help="Build the GEO channel and content blueprint")
    s.add_argument("--slug", required=True)
    s.set_defaults(func=cmd_blueprint)

    s = sub.add_parser("generate", help="Generate deployable GEO assets")
    s.add_argument("--slug", required=True)
    s.add_argument("--asset", help="Comma-separated: llms,jsonld,snippets,outlines")
    s.add_argument("--draft", action="store_true", help="Generate additional LLM article drafts")
    s.add_argument("--draft-limit", type=int, default=3, dest="draft_limit")
    s.set_defaults(func=cmd_generate)

    s = sub.add_parser("lint", help="Inspect AI drafts for unsupported claims")
    s.add_argument("--slug", required=True)
    s.set_defaults(func=cmd_lint)

    s = sub.add_parser("verify", help="Re-crawl and verify ticket acceptance criteria")
    s.add_argument("--slug", required=True)
    s.add_argument("--no-recrawl", action="store_true", dest="no_recrawl",
                   help="Use the current audit without re-crawling")
    s.set_defaults(func=cmd_verify)

    s = sub.add_parser("deliver", help="Compile the client delivery package")
    s.add_argument("--slug", required=True)
    s.set_defaults(func=cmd_deliver)

    s = sub.add_parser("publish", help="Publish approved content to a configured destination")
    s.add_argument("--slug", required=True)
    s.add_argument("--path", required=True, help="Relative path under content/ or assets/")
    s.add_argument("--platform", required=True, choices=["github", "wordpress", "wechat_draft", "webhook"])
    s.add_argument("--title")
    s.set_defaults(func=cmd_publish)

    s = sub.add_parser("task", help="View or update a ticket")
    s.add_argument("--slug", required=True)
    s.add_argument("--id", required=True)
    s.add_argument("--status", choices=["todo", "doing", "done", "blocked", "wontfix"])
    s.add_argument("--note")
    s.set_defaults(func=cmd_task)

    s = sub.add_parser("status", help="Show project progress")
    s.add_argument("--slug", required=True)
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("serve", help="Run the complete service cycle")
    s.add_argument("--slug", required=True)
    s.add_argument("--max-pages", type=int, default=None, dest="max_pages")
    s.add_argument("--limit", type=int, default=None, help="Sample only the first N questions")
    s.add_argument("--no-sample", action="store_true", dest="no_sample")
    s.add_argument("--draft", action="store_true", help="Generate additional article drafts")
    s.add_argument("--draft-limit", type=int, default=3, dest="draft_limit")
    s.set_defaults(func=cmd_serve)

    s = sub.add_parser("ui", help="Start the monitoring dashboard")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--no-open", action="store_true", dest="no_open")
    s.set_defaults(func=cmd_ui)

    s = sub.add_parser("list", help="List projects")
    s.set_defaults(func=cmd_list)

    a = p.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
