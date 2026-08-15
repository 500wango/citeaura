"""Derive normalized product metrics from raw sampling evidence.

Unmeasured inputs remain ``None`` and health-score weights are renormalized.
Fact consistency is measured only from explicit records in factcheck.json.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

import geolib as G

WEIGHTS = {"mention": 30, "cite": 25, "channel": 20, "content": 15, "fact": 10}


def _own_host(cfg) -> str:
    return urlparse(cfg["brand"]["site"]).netloc.lower().removeprefix("www.")


def _is_own(domain: str, own: str) -> bool:
    d = (domain or "").lower().removeprefix("www.")
    return d == own or d.endswith("." + own)


def _sample_files(pdir: Path):
    d = pdir / "samples"
    return sorted(d.glob("*.jsonl")) if d.exists() else []


def _rows(path: Path):
    return _usable_rows(G.read_jsonl(path))


def _usable_rows(rows):
    return [
        row for row in rows
        if isinstance(row, dict) and row.get("ok") and isinstance(row.get("analysis"), dict)
    ]


def _unprompted(rows):
    return [r for r in rows if not r.get("brand_in_question")]


def _cite_share(rows, own) -> tuple[float | None, int, int]:
    """Return own-domain share and counts, or None when no citations exist."""
    total = mine = 0
    for r in rows:
        for d in (r.get("analysis") or {}).get("cited_domains") or []:
            total += 1
            if _is_own(d, own):
                mine += 1
    return (mine / total if total else None), mine, total


def _mention(rows) -> float | None:
    if not rows:
        return None
    return sum(1 for r in rows if r["analysis"]["brand_mentioned"]) / len(rows)


def _median(vals):
    vals = sorted(vals)
    return vals[len(vals) // 2] if vals else None


# ---------------------------------------------------------------- Health score

def health(slug: str, bp: dict | None, factcheck: list, rows_latest) -> dict:
    rows_latest = _usable_rows(rows_latest)
    cfg = G.load_config(slug)
    own = _own_host(cfg)
    up = _unprompted(rows_latest)
    subs: dict[str, float | None] = {
        "mention": _mention(up),
        "cite": _cite_share(up, own)[0],
        "channel": None, "content": None, "fact": None,
    }
    if bp:
        cov = bp["coverage"]
        subs["channel"] = cov["channel_covered"] / cov["channel_total"] if cov["channel_total"] else None
        subs["content"] = cov["content_done"] / cov["content_total"] if cov["content_total"] else None
    # Fact consistency is measurable only after explicit human review.
    checked = [f for f in factcheck if f.get("state") in ("consistent", "incorrect", "missing")]
    if checked:
        subs["fact"] = sum(1 for f in checked if f["state"] == "consistent") / len(checked)

    wsum = sum(WEIGHTS[k] for k, v in subs.items() if v is not None)
    score = (sum(WEIGHTS[k] * v for k, v in subs.items() if v is not None) / wsum * 100) if wsum else None
    return {"score": round(score, 1) if score is not None else None,
            "subs": {k: (round(v, 3) if v is not None else None) for k, v in subs.items()},
            "weights": WEIGHTS,
            "measured": [k for k, v in subs.items() if v is not None]}


# ---------------------------------------------------------------- Engines

def _verdict(m, own_cited, peers, samples=0) -> str:
    """Describe platform performance only when peer sample sizes are comparable."""
    if m is None:
        return "No samples this cycle"
    if samples < 5:
        return f"Insufficient samples ({samples}/5); observation only"
    if m == 0:
        return "No observed visibility; inspect the sources preferred by this engine"
    vals = [m] + [p for p, n in peers if p is not None and n >= 5]
    if len(vals) < 2 or len(set(vals)) < 2:
        rel = "Insufficient comparable samples"
    elif m >= max(vals):
        rel = "Highest-performing measured engine; prioritize reinforcement"
    else:
        rel = "Visible but unstable" if m >= 0.05 else "Occasional mentions; not yet a stable candidate"
    parts = [rel]
    if not own_cited:
        parts.append("Never cited the official domain")
    return "; ".join(parts)


def _brand_dist(rows) -> list[dict]:
    """Return per-sample mention distribution for configured entities."""
    n = len(rows)
    if not n:
        return []
    cnt: dict[str, int] = {}
    for r in rows:
        for name in r["analysis"].get("candidates") or []:
            cnt[name] = cnt.get(name, 0) + 1
    return [{"name": k, "hits": v, "rate": round(v / n, 3)}
            for k, v in sorted(cnt.items(), key=lambda x: -x[1])]


def engines(slug: str, rows_latest, metrics: dict | None) -> list[dict]:
    rows_latest = _usable_rows(rows_latest)
    cfg = G.load_config(slug)
    own = _own_host(cfg)
    by: dict[str, list] = {}
    for r in rows_latest:
        by.setdefault(r["platform"], []).append(r)
    mkt = {p: rs[0].get("market", "cn") for p, rs in by.items()}
    ment = {p: _mention(_unprompted(rs)) for p, rs in by.items()}
    out = []
    for plat, rs in by.items():
        up = _unprompted(rs)
        m = ment[plat]
        ranks = [r["analysis"]["brand_rank"] for r in up
                 if r["analysis"]["brand_mentioned"] and r["analysis"]["brand_rank"]]
        share, mine, total = _cite_share(up, own)
        meta = (metrics or {}).get("platforms", {}).get(plat, {})
        # Prefer an unprompted positive sample for replay.
        ex = next((r for r in up if r["analysis"]["brand_mentioned"]), up[0] if up else (rs[0] if rs else None))
        example = None
        if ex:
            ans = ex.get("answer", "")
            brand = cfg["brand"]["name"]
            i = ans.find(brand)
            lo = max(0, (i if i >= 0 else 0) - 120)
            example = {"question": ex.get("question", ""), "date": ex.get("date", ""),
                       "excerpt": ans[lo:lo + 320], "brand_pos": (i - lo) if i >= 0 else -1,
                       "mentioned": ex["analysis"]["brand_mentioned"],
                       "rank": ex["analysis"]["brand_rank"],
                       "n_cites": len(ex["analysis"].get("cited_domains") or []),
                       "own_cited": ex["analysis"].get("own_domain_cited", False),
                       "negative_cues": ex["analysis"].get("negative_cues") or []}
        lat = sorted(r["elapsed_ms"] for r in rs if r.get("elapsed_ms"))
        out.append({
            "platform": plat, "label": meta.get("label", plat),
            "market": rs[0].get("market", "cn"),
            "searched": any(r.get("search_enabled") for r in rs),
            "samples": len(up), "mention": round(m, 3) if m is not None else None,
            "pos_median": _median(ranks),
            "cite_share": round(share, 3) if share is not None else None,
            "cite_counts": [mine, total],
            "top_sources": list((meta.get("top_cited_domains") or {}).keys())[:4],
            "avg_ms": lat[len(lat) // 2] if lat else None,
            "neg_n": sum(1 for r in up if r["analysis"].get("negative_cues")),
            "brand_dist": _brand_dist(up)[:8],
            "verdict": _verdict(m,
                                any(r["analysis"].get("own_domain_cited") for r in rs),
                                [(ment[p], len(_unprompted(by[p]))) for p in by
                                 if p != plat and mkt[p] == mkt[plat]], len(up)),
            "example": example,
        })
    out.sort(key=lambda x: -(x["mention"] or 0))
    return out


# ---------------------------------------------------------------- Competitors

def competitors(slug: str, rows_latest) -> dict:
    rows_latest = _usable_rows(rows_latest)
    cfg = G.load_config(slug)
    comps = cfg.get("competitors", [])
    up = _unprompted(rows_latest)
    bym = {"cn": [r for r in up if r.get("market", "cn") == "cn"],
           "global": [r for r in up if r.get("market") == "global"]}

    def comp_markets(c) -> list[str]:
        m = c.get("market")
        return [m] if m in ("cn", "global") else ["cn", "global"]

    # Compute market-specific competitor tables with separate denominators.
    tables: dict[str, list] = {}
    for market, rows in bym.items():
        n = len(rows)
        byp: dict[str, list] = {}
        for r in rows:
            byp.setdefault(r["platform"], []).append(r)
        t = []
        for c in comps:
            if market not in comp_markets(c):
                continue
            hit = sum(1 for r in rows if c["name"] in (r["analysis"].get("competitors_mentioned") or []))
            # Strongest engine presence identifies the best source-research target.
            tops = []
            for plat, rs in byp.items():
                h = sum(1 for r in rs if c["name"] in (r["analysis"].get("competitors_mentioned") or []))
                if h:
                    tops.append({"platform": plat,
                                 "label": rs[0].get("platform_name", plat),
                                 "rate": round(h / len(rs), 2)})
            tops.sort(key=lambda x: -x["rate"])
            t.append({"name": c["name"], "market": c.get("market", "both"),
                      "presence": round(hit / n, 3) if n else None, "hits": hit,
                      "top_engines": tops[:3], "conclusion_ready": n >= 5,
                      "minimum_samples": 5})
        t.sort(key=lambda x: -(x["presence"] or 0))
        tables[market] = t
    # Flatten by competitor name while preserving the strongest market presence.
    flat: dict[str, dict] = {}
    for x in sorted((x for t in tables.values() for x in t),
                    key=lambda x: -(x["presence"] or 0)):
        flat.setdefault(x["name"], x)
    table = list(flat.values())

    # Aggregate questions into competitor-led and brand-only opportunities.
    byq: dict[str, list] = {}
    for r in up:
        byq.setdefault(r.get("question_id") or r.get("question", ""), []).append(r)
    lost, won = [], []
    for qid, rs in byq.items():
        me = _mention(rs) or 0
        rivals: dict[str, int] = {}
        for r in rs:
            for cname in r["analysis"].get("competitors_mentioned") or []:
                rivals[cname] = rivals.get(cname, 0) + 1
        top_rival = max(rivals.items(), key=lambda x: x[1]) if rivals else None
        row = {"qid": qid, "question": rs[0].get("question", ""),
               "market": rs[0].get("market", "cn"), "samples": len(rs),
               "mine": round(me, 2),
               "rival": top_rival[0] if top_rival else None,
               "rival_rate": round(top_rival[1] / len(rs), 2) if top_rival else 0}
        if len(rs) >= 3 and me == 0 and top_rival:
            lost.append(row)
        elif len(rs) >= 3 and me > 0 and not rivals:
            won.append(row)
    lost.sort(key=lambda x: -x["rival_rate"])
    won.sort(key=lambda x: -x["mine"])
    return {"tables": tables, "table": table, "lost": lost[:8], "won": won[:8],
            "sample_n": len(up), "sample_ns": {m: len(rs) for m, rs in bym.items()}}


# ---------------------------------------------------------------- Questions

def _diagnose(m, rank_med, rival, rival_rate, neg_n, samples=0):
    """Return a deterministic question-level diagnostic classification."""
    if m is None:
        return None
    if samples < 3:
        return {"type": "sample_insufficient", "sev": "review",
                "detail": f"Only {samples} samples; at least 3 are required"}
    if neg_n:
        return {"type": "suspected_negative", "sev": "P0",
                "detail": f"{neg_n} samples contain negative context near the brand; review sample replay"}
    if m == 0 and rival and rival_rate >= 0.5:
        return {"type": "competitor_dominant", "sev": "P0",
                "detail": f"Brand 0%; {rival} presence {round(rival_rate * 100)}%; inspect its cited sources"}
    if m == 0:
        return {"type": "absent", "sev": "P1", "detail": "Never mentioned in unprompted samples"}
    if rank_med and rank_med > 3:
        return {"type": "low_rank", "sev": "P2",
                "detail": f"Mentioned at median position {rank_med}; strengthen the primary recommendation case"}
    return {"type": "normal", "sev": "ok", "detail": ""}


def questions(slug: str, rows_latest, bp: dict | None) -> list[dict]:
    rows_latest = _usable_rows(rows_latest)
    cfg = G.load_config(slug)
    status = {c["id"]: c["status"] for c in (bp or {}).get("contents", [])}
    byq: dict[str, list] = {}
    for r in rows_latest:
        byq.setdefault(r.get("question_id"), []).append(r)
    brand = cfg.get("brand", {})
    names = [brand.get("name", "")] + list(brand.get("aliases") or [])

    def is_probe(q, rs) -> bool:
        if any(r.get("brand_in_question") for r in rs):
            return True
        text = (q.get("text") or "").lower()
        return any(n and n.lower() in text for n in names)

    out = []
    for q in cfg.get("questions", []):
        rs = byq.get(q.get("id"), [])
        m = _mention(rs)
        probe = is_probe(q, rs)
        ranks = [r["analysis"]["brand_rank"] for r in rs
                 if r["analysis"]["brand_mentioned"] and r["analysis"].get("brand_rank")]
        rivals: dict[str, int] = {}
        for r in rs:
            for c in r["analysis"].get("competitors_mentioned") or []:
                rivals[c] = rivals.get(c, 0) + 1
        top = max(rivals.items(), key=lambda x: x[1]) if rivals else None
        neg_n = sum(1 for r in rs if r["analysis"].get("negative_cues"))
        out.append({"id": q.get("id"), "text": q.get("text", ""), "group": q.get("group", ""),
                    "market": q.get("market", "cn"),
                    "brand_probe": probe,
                    "mention": round(m, 2) if m is not None else None,
                    "samples": len(rs),
                    "diagnosis": None if probe else _diagnose(
                        m, _median(ranks),
                        top[0] if top else None,
                        (top[1] / len(rs)) if top and rs else 0, neg_n, len(rs)),
                    "content": status.get(q.get("id"), "gap")})
    # Missing visibility and content sort first; brand probes remain separate.
    out.sort(key=lambda x: (x["brand_probe"], (x["mention"] or 0), x["content"] == "ready"))
    return out


# ---------------------------------------------------------------- Trends

def trend(slug: str) -> list[dict]:
    cfg = G.load_config(slug)
    own = _own_host(cfg)
    pdir = G.project_dir(slug)
    metric_files = sorted((pdir / "metrics").glob("*.json")) if (pdir / "metrics").exists() else []
    metrics_by_run = {}
    for path in metric_files:
        metric = G.read_json(path, {}) or {}
        if metric.get("run_id"):
            metrics_by_run[metric["run_id"]] = metric
    pts = []
    for f in _sample_files(pdir):
        rows = _rows(f)
        if not rows:
            continue
        run_id = rows[0].get("run_id")
        metric = metrics_by_run.get(run_id, {})
        snapshot = metric.get("history_snapshot") or {}
        h = snapshot.get("health") or {}
        up = _unprompted(rows)
        mention = _mention(up)
        share = _cite_share(up, own)[0]
        pts.append({"date": rows[0].get("date") or f.stem, "run_id": run_id,
                    "health": h.get("score"),
                    "mention": round(mention, 3) if mention is not None else None,
                    "cite": round(share, 3) if share is not None else None,
                    "samples": len(rows),
                    "historical_context": "snapshot" if snapshot else "unavailable"})
    return pts


def question_delta(slug: str) -> list[dict]:
    """Compare per-question mention rates across the two latest comparable runs."""
    files = _sample_files(G.project_dir(slug))
    if len(files) < 2:
        return []
    def per_q(path):
        rows = _unprompted(_rows(path))
        out = {}
        for r in rows:
            out.setdefault(r.get("question_id"), []).append(r)
        return rows, {k: _mention(v) for k, v in out.items() if k}
    before_rows, before = per_q(files[-2])
    after_rows, after = per_q(files[-1])
    before_identity = ((before_rows[0].get("question_set_id"), before_rows[0].get("cohort_id"))
                       if before_rows else (None, None))
    after_identity = ((after_rows[0].get("question_set_id"), after_rows[0].get("cohort_id"))
                      if after_rows else (None, None))
    if any(before_identity) or any(after_identity):
        if before_identity != after_identity:
            return []
    evidence_rows = before_rows + after_rows
    qtext = {r.get("question_id"): r.get("question", "") for r in evidence_rows if r.get("question_id")}
    qmkt = {r.get("question_id"): r.get("market", "cn") for r in evidence_rows if r.get("question_id")}
    rows = []
    for qid in sorted(set(before) | set(after)):
        b, a = before.get(qid), after.get(qid)
        rows.append({"qid": qid, "question": qtext.get(qid, qid),
                     "market": qmkt.get(qid, "cn"),
                     "before": round(b, 2) if b is not None else None,
                     "after": round(a, 2) if a is not None else None,
                     "note": "Unmeasured this cycle" if a is None else "",
                     "dates": [before_rows[0].get("date") if before_rows else files[-2].stem,
                               after_rows[0].get("date") if after_rows else files[-1].stem]})
    # Unmeasured current-cycle rows sort last.
    rows.sort(key=lambda x: (x["after"] is None, -(((x["after"] or 0) - (x["before"] or 0)))))
    return rows


# ---------------------------------------------------------------- Aggregate entry point

def build(slug: str) -> dict:
    pdir = G.project_dir(slug)
    bp = G.read_json(pdir / "blueprint.json", None)
    fc = G.read_json(pdir / "factcheck.json", []) or []
    files = _sample_files(pdir)
    rows_latest = _rows(files[-1]) if files else []
    mfiles = sorted((pdir / "metrics").glob("*.json")) if (pdir / "metrics").exists() else []
    metrics = G.read_json(mfiles[-1], None) if mfiles else None

    return {
        "latest_date": files[-1].stem if files else None,
        "health": health(slug, bp, fc, rows_latest),
        "engines": engines(slug, rows_latest, metrics),
        "brand_dist": {m: _brand_dist([r for r in _unprompted(rows_latest)
                                       if r.get("market", "cn") == m])
                       for m in ("cn", "global")},
        "competitors": competitors(slug, rows_latest),
        "questions": questions(slug, rows_latest, bp),
        "trend": trend(slug),
        "factcheck": fc,
        "q_delta": question_delta(slug),
    }


# ---------------------------------------------------------------- Content precheck

BLOCK_LIFT = {key: "Reference association, not causal; validate per project"
              for key in ("definition", "numeric_facts", "comparison", "steps", "faq")}


def precheck(text: str) -> dict:
    """Precheck content using the same extraction rules as audit.py."""
    import audit as A

    body = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    wc = G.word_count(body)
    h2 = len(re.findall(r"^##\s|^<h2", body, re.M))
    blocks = {
        "definition": bool(A.RE_DEFINITION.search(body)),
        "numeric_facts": len(A.RE_NUMBER.findall(body)) >= 3,
        "comparison": bool(A.RE_COMPARE.search(body)) or bool(re.search(r"^\|.*\|$", body, re.M)),
        "steps": bool(A.RE_HOWTO.search(body)),
        "faq": bool(A.RE_FAQ.search(body)),
    }
    hits = sum(blocks.values())
    grade = ("A" if wc >= 1000 and h2 >= 6 and hits >= 5 else
             "B" if wc >= 800 and hits >= 4 else
             "C" if wc >= 400 and hits >= 2 else "D")
    checks = [{"t": f"{k} block", "ok": v, "lift": BLOCK_LIFT[k]} for k, v in blocks.items()]
    checks.insert(0, {"t": f"Body length {wc} words (threshold 1,000)", "ok": wc >= 1000, "lift": ""})
    checks.insert(1, {"t": f"H2 sections {h2} (target >=6)", "ok": h2 >= 6, "lift": ""})
    return {"grade": grade, "wc": wc, "h2": h2, "blocks": blocks, "checks": checks}
