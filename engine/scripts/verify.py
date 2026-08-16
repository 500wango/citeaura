"""Re-crawl projects and verify ticket acceptance criteria.

Supported checker expressions include site assets, page extraction blocks,
content depth, market visibility metrics, and external citation evidence.
Relative checks use ``baseline_count`` and the full verification cohort.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import geolib as G
import tasks as T


def report_key(f: Path) -> tuple[str, str]:
    """Sort legacy date-only and timestamped verification reports chronologically."""
    m = re.match(r"(\d{4}-\d{2}-\d{2})(?:-(\d{6}))?", f.stem)
    return (m.group(1), m.group(2) or "000000") if m else ("", f.stem)


def _pages_by_url(audit: dict) -> dict:
    return {p["url"]: p for p in audit.get("pages", [])
            if isinstance(p, dict) and p.get("url")}


def _cited_domains(metrics: dict, market: str | None = None, *, brand_only: bool = False) -> dict[str, int]:
    out: dict[str, int] = {}
    for m in (metrics or {}).get("platforms", {}).values():
        if market and m.get("market", "cn") != market:
            continue
        field = "top_brand_cited_domains" if brand_only else "top_cited_domains"
        for k, v in m.get(field, {}).items():
            domain = G.normalize_host(k)
            if domain and isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
                out[domain] = out.get(domain, 0) + v
    return out


def _market_avg(metrics: dict, market: str, field: str):
    # Probe-only platforms are unmeasured and do not participate in averages.
    vals = [(m[field], int(m.get("samples") or 0))
            for m in (metrics or {}).get("platforms", {}).values()
            if m.get("market", "cn") == market and m.get(field) is not None
            and int(m.get("samples") or 0) > 0]
    total = sum(count for _value, count in vals)
    return (sum(value * count for value, count in vals) / total) if total else None


def _measurement_sufficient(metrics: dict) -> bool:
    measurement = (metrics or {}).get("measurement") or {}
    if measurement:
        return bool(measurement.get("sufficient"))
    rows = [item for item in (metrics or {}).get("platforms", {}).values()
            if item.get("mention_rate") is not None and int(item.get("samples") or 0) > 0]
    return sum(int(item.get("samples") or 0) for item in rows) >= 20 and len(rows) >= 2


def _evidence_history(task: dict) -> list:
    """Normalize legacy verification evidence before appending a new entry."""
    value = task.get("evidence")
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    return [{"note": str(value)}]


def check(task: dict, audit: dict, metrics: dict) -> tuple[bool | None, str, dict | None]:
    """Return ``(passed, note, progress)``; ``None`` means manual review.

    Quantitative checks return a structured progress snapshot. Qualitative
    checks such as sitemap presence return no intermediate progress.
    """
    acc = task.get("acceptance", {})
    if acc.get("type") != "auto":
        return None, "Manual review required", None
    expr = acc.get("check", "")
    site = audit.get("site", {})
    pages = _pages_by_url(audit)
    aff = task.get("affected", [])
    cohort = task.get("verification_cohort") or aff
    base = len(aff)

    try:
        if expr == "site.no_ai_bot_block":
            blocked = site.get("ai_bots_blocked") or []
            return (not blocked), ("robots.txt does not block any AI crawler" if not blocked
                                   else f"Still blocked: {', '.join(blocked)}"), None
        if expr == "site.has_sitemap":
            ok = bool(site.get("has_sitemap"))
            return ok, (f"sitemap.xml is available with {site.get('sitemap_url_count', 0)} URLs"
                        if ok else "sitemap.xml is still missing"), None
        if expr == "site.has_llms_txt":
            ok = bool(site.get("has_llms_txt"))
            return ok, ("llms.txt is available" if ok else "llms.txt is still missing"), None
        if expr.startswith("site.avg_score_gte:"):
            tgt = float(expr.split(":")[1])
            cur = audit.get("avg_score", 0)
            return cur >= tgt, f"Current average score {cur} / target {tgt}", \
                {"label": "Average site audit score", "cur": cur, "target": tgt, "op": "gte"}
        if expr.startswith("site.en_pages_gte:"):
            tgt = int(expr.split(":")[1])
            cur = (audit.get("language_coverage") or {}).get("en_pages", 0)
            return cur >= tgt, f"Valid English content pages {cur} / target {tgt}", \
                {"label": "Valid English content pages", "cur": cur, "target": tgt, "op": "gte"}
        if expr.startswith("site.lang_balance:"):
            r = float(expr.split(":")[1])
            lc = audit.get("language_coverage") or {}
            en, zh = lc.get("en_pages", 0), lc.get("zh_pages", 0)
            if not (en and zh):
                return False, f"Chinese pages {zh} / English pages {en}; one side is still empty", None
            ok = abs(en - zh) <= max(en, zh) * r
            return ok, f"Chinese pages {zh} / English pages {en}", \
                {"label": "Chinese-English page-count difference ratio", "cur": round(abs(en - zh) / max(en, zh), 2),
                 "target": r, "op": "lte"}

        if expr == "pages.static_text":
            missing = [u for u in cohort if u not in pages]
            if missing:
                return None, f"{len(missing)} verification-cohort URLs were not crawled; result is indeterminate", None
            bad = [u for u in cohort if pages[u].get("word_count", 0) < 120]
            base = len(cohort)
            return (not bad), f"{base - len(bad)}/{base} pages expose body text", \
                {"label": "Pages without crawlable body text", "cur": len(bad), "target": 0, "op": "lte", "base": base}
        if expr == "pages.has_jsonld":
            missing = [u for u in cohort if u not in pages]
            if missing:
                return None, f"{len(missing)} verification-cohort URLs were not crawled; result is indeterminate", None
            bad = [u for u in cohort if not pages[u].get("jsonld_types")]
            base = len(cohort)
            return (not bad), f"{base - len(bad)}/{base} pages contain JSON-LD", \
                {"label": "Pages without JSON-LD", "cur": len(bad), "target": 0, "op": "lte", "base": base}
        if expr.startswith("pages.block:"):
            blk = expr.split(":", 1)[1]
            missing = [u for u in cohort if u not in pages]
            if missing:
                return None, f"{len(missing)} verification-cohort URLs were not crawled; gap reduction is indeterminate", None
            # Use the full generation-time gap count as the relative baseline.
            base = task.get("baseline_count", len(aff))
            cur = sum(1 for u in cohort if pages[u].get("blocks", {}).get(blk) is False)
            return cur <= base * 0.5, f"Pages missing {blk}: {cur} (baseline {base}, target <={int(base*0.5)})", \
                {"label": f"Pages missing {blk} blocks", "cur": cur, "target": int(base * 0.5),
                 "op": "lte", "base": base}
        if expr.startswith("pages.applicable:"):
            check_id = expr.split(":", 1)[1].strip()
            missing = []
            failed = []
            for url in cohort:
                page = pages.get(url)
                if not page or page.get("evaluation_status") != "evaluated":
                    missing.append(url)
                    continue
                check_row = next(
                    (item for item in page.get("checks") or [] if isinstance(item, dict) and item.get("id") == check_id),
                    None,
                )
                if not check_row or check_row.get("status") == "not_evaluated":
                    missing.append(url)
                elif check_row.get("status") == "failed":
                    failed.append(url)
            base = len(cohort)
            progress = {
                "label": "Applicable pages still failing",
                "cur": len(failed),
                "target": 0,
                "op": "lte",
                "missing": len(missing),
                "base": base,
            }
            if missing:
                return None, (
                    f"{len(missing)} baseline URL(s) were not evaluated in the current crawl; pass is withheld"
                ), progress
            ok = not failed
            return ok, (
                f"{base - len(failed)}/{base} applicable pages pass {check_id}"
                if ok else
                f"{len(failed)} baseline page(s) still fail the role-aware {check_id} check"
            ), progress
        if expr.startswith("pages.wordcount_gte:"):
            n = int(expr.split(":")[1])
            missing = [u for u in cohort if u not in pages]
            if missing:
                return None, f"{len(missing)} verification-cohort URLs were not crawled; content improvement is indeterminate", None
            base = task.get("baseline_count", len(aff))
            cur = sum(1 for u in cohort if 100 <= pages[u].get("word_count", 0) < n)
            return cur <= base * 0.6, f"Pages below {n} words: {cur} (baseline {base}, target <={int(base*0.6)})", \
                {"label": f"Pages below {n} words", "cur": cur, "target": int(base * 0.6),
                 "op": "lte", "base": base}

        if expr.startswith("metrics.mention_rate_gte:"):
            if not _measurement_sufficient(metrics):
                return None, "Sample volume or platform coverage is insufficient to verify the mention-rate target", None
            _, mk, tgt = expr.split(":")
            cur = _market_avg(metrics, mk, "mention_rate")
            if cur is None:
                return None, f"No measured sampling data for the {mk} market in this cycle", None
            return cur >= float(tgt), f"{mk} average mention rate {cur:.1%} / target {float(tgt):.0%}", \
                {"label": f"{mk} average mention rate", "cur": round(cur, 3), "target": float(tgt),
                 "op": "gte", "pct": True}
        if expr.startswith("metrics.own_cite_gte:"):
            if not _measurement_sufficient(metrics):
                return None, "Sample volume or platform coverage is insufficient to verify the citation-rate target", None
            _, mk, tgt = expr.split(":")
            cur = _market_avg(metrics, mk, "own_domain_cite_rate")
            if cur is None:
                return None, f"No measured sampling data for the {mk} market in this cycle", None
            return cur >= float(tgt), f"{mk} official-domain citation rate {cur:.1%} / target {float(tgt):.0%}", \
                {"label": f"{mk} official-domain citation rate", "cur": round(cur, 3), "target": float(tgt),
                 "op": "gte", "pct": True}

        if expr == "metrics.representative_baseline":
            ok = _measurement_sufficient(metrics)
            measurement = (metrics or {}).get("measurement") or {}
            return ok, ("Sampling baseline meets the conclusion threshold" if ok
                        else "Sampling baseline is still insufficient"), {
                "label": "Valid unprompted samples", "cur": measurement.get("effective_samples", 0),
                "target": measurement.get("minimum_samples", 20), "op": "gte",
            }

        if expr.startswith("external.any:"):
            return None, "Legacy checker proves only domain presence, not brand-related evidence; regenerate tickets", None
        if expr.startswith("external.brand_any:"):
            targets = [G.normalize_host(d) for d in expr.split(":", 1)[1].split(",")]
            targets = [d for d in targets if d]
            doms = _cited_domains(metrics, brand_only=True)
            hit = [t for t in targets if any(d == t or d.endswith("." + t) for d in doms)]
            return bool(hit), (f"Cited domains: {', '.join(hit)}" if hit
                               else f"No target domain appeared in sampled citations ({len(targets)} checked)"), \
                {"label": "Cited target domains", "cur": len(hit), "target": 1, "op": "gte",
                 "base": len(targets)}
    except Exception as e:  # noqa: BLE001
        return None, f"Checker error: {type(e).__name__}: {e}", None
    return None, f"Unknown checker `{expr}`", None


def run(slug: str, recrawl: bool = True) -> dict:
    pdir = G.project_dir(slug)
    if recrawl:
        import audit as A
        import crawl as C
        G.info("=== Re-crawling Site ===")
        C.run(slug)
        G.info("=== Re-running Site Audit ===")
        A.run(slug)

    audit = G.read_json(pdir / "audit.json", {})
    files = sorted((pdir / "metrics").glob("*.json")) if (pdir / "metrics").exists() else []
    metrics = G.read_json(files[-1], None) if files else None

    results, changed = [], 0
    with G.project_lock(slug):
        data = T.load(slug)
        if not data.get("tasks"):
            G.die("No action tickets found. Run first: python3 scripts/geo.py plan --slug " + slug)

        for t in data["tasks"]:
            ok, note, prog = check(t, audit, metrics)
            prev = t["status"]
            if prog:
                prog["at"] = G.now_iso()
                t.setdefault("progress_first", dict(prog))
                t["progress"] = prog
            if ok is True and t["status"] != "done":
                t["status"] = "done"
                t["closed_at"] = G.now_iso()
                changed += 1
            elif ok is False and t["status"] == "done":
                # Reopen a previously completed ticket when it regresses.
                t["status"] = "todo"
                t["closed_at"] = None
                changed += 1
            evidence = _evidence_history(t)
            evidence.append({"at": G.now_iso(), "check": (t.get("acceptance") or {}).get("check"),
                             "result": {True: "pass", False: "fail", None: "manual"}[ok], "note": note})
            t["evidence"] = evidence[-6:]
            results.append({"id": t["id"], "title": t["title"], "priority": t["priority"],
                            "market": t["market"], "package": t["package"],
                            "verdict": {True: "pass", False: "fail", None: "manual"}[ok],
                            "note": note, "was": prev, "now": t["status"],
                            "progress": prog, "progress_first": t.get("progress_first")})

        T.save(slug, data)
    report = {
        "slug": slug, "verified_at": G.now_iso(),
        "audit_avg_score": audit.get("avg_score"),
        "metrics_date": metrics.get("date") if metrics else None,
        "changed": changed,
        "summary": data["summary"],
        "results": results,
    }
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    G.write_json(pdir / "verify" / f"{stamp}.json", report)

    p = sum(1 for r in results if r["verdict"] == "pass")
    f = sum(1 for r in results if r["verdict"] == "fail")
    m = sum(1 for r in results if r["verdict"] == "manual")
    G.info(f"Verification: Passed {p} / Unmet {f} / Manual review {m}; Status changed: {changed} items")
    return report
