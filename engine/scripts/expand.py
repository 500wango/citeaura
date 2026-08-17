"""Expand candidate questions from public search-suggestion endpoints.

Expansion produces candidates only; users explicitly add them to the stable
question bank. Per-cycle snapshots record first-seen terms as observations.
"""
from __future__ import annotations

import json
import re
import time
from urllib.parse import quote

import geolib as G
import requests

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}

# Root modifiers vary by brand, competitor, and category intent.
MODS = {
    "cn": {
        "brand":      ["", " \u600e\u4e48\u6837", " \u9760\u8c31\u5417", " \u66ff\u4ee3", " \u5bf9\u6bd4", " \u4ef7\u683c"],
        "competitor": ["", " \u600e\u4e48\u6837", " \u66ff\u4ee3", " \u5bf9\u6bd4", " \u7f3a\u70b9"],
        "category":   ["", " \u63a8\u8350", " \u54ea\u4e2a\u597d", " \u5bf9\u6bd4", " \u4ef7\u683c"],
    },
    "global": {
        "brand":      ["", " review", " alternative", " vs", " pricing"],
        "competitor": ["", " review", " alternative", " vs"],
        "category":   ["", " best", " comparison", " pricing"],
    },
}

# Intent cues map to canonical question groups.
GROUP_CUES = [
    ("alternative", ["\u66ff\u4ee3", "\u5e73\u66ff", "alternative", "instead of", "\u66ff\u6362"]),
    ("comparison", [" vs", "\u5bf9\u6bd4", "\u6bd4\u8f83", "\u533a\u522b", "\u54ea\u4e2a\u597d", "comparison", "compare", "versus"]),
    ("pricing", ["\u4ef7\u683c", "\u591a\u5c11\u94b1", "\u6536\u8d39", "\u514d\u8d39", "pricing", "price", "cost", "free"]),
    ("risk", ["\u9760\u8c31", "\u9a97", "\u6295\u8bc9", "\u7f3a\u70b9", "\u5751", "scam", "safe", "problem", "\u7f3a\u9677"]),
    ("brand_verification", ["\u600e\u4e48\u6837", "\u8bc4\u6d4b", "\u6d4b\u8bc4", "\u597d\u7528\u5417", "review", "worth it"]),
    ("recommendation", ["\u63a8\u8350", "\u6392\u884c", "\u6392\u540d", "best", "top", "\u54ea\u5bb6"]),
]

# Templates provide deterministic fallback question phrasing.
TEMPLATES = {
    "cn": {
        "recommendation": "{t}\uff0c\u6709\u503c\u5f97\u63a8\u8350\u7684\u5417\uff1f",
        "comparison": "{t}\uff0c\u5230\u5e95\u8be5\u600e\u4e48\u9009\uff1f",
        "alternative": "{t}\uff0c\u6709\u54ea\u4e9b\u66ff\u4ee3\u65b9\u6848\uff1f",
        "pricing": "{t}\u5927\u6982\u662f\u4ec0\u4e48\u4ef7\u4f4d\uff1f\u503c\u4e0d\u503c\uff1f",
        "risk": "{t}\uff0c\u6709\u4ec0\u4e48\u8981\u907f\u7684\u5751\u5417\uff1f",
        "brand_verification": "{t}\uff1f\u7528\u8fc7\u7684\u8bf4\u8bf4\u5b9e\u9645\u4f53\u9a8c\u3002",
        "scenario": "{t}\uff0c\u5b9e\u9645\u7528\u8d77\u6765\u600e\u4e48\u6837\uff1f",
    },
    "global": {
        "recommendation": "Any recommendations for {t}?",
        "comparison": "How should I choose between options for {t}?",
        "alternative": "What are good alternatives for {t}?",
        "pricing": "Is {t} worth the price?",
        "risk": "Any pitfalls to watch out for with {t}?",
        "brand_verification": "Is {t} actually good in practice?",
        "scenario": "How does {t} work in real use?",
    },
}

STOP_BIGRAMS = {"\u5de5\u5177", "\u8f6f\u4ef6", "\u667a\u80fd", "\u5e73\u53f0", "\u7cfb\u7edf", "\u670d\u52a1", "\u5728\u7ebf", "\u514d\u8d39",
                "\u662f\u4ec0", "\u4ec0\u4e48", "\u600e\u4e48", "\u4e48\u6837", "\u600e\u6837", "\u5982\u4f55", "\u54ea\u4e2a", "\u54ea\u4e9b", "\u6ca1\u6709",
                "\u6709\u6ca1", "\u53ef\u4ee5", "\u4e00\u4e2a", "\u8fd9\u4e2a", "\u4e3a\u4ec0", "\u63a8\u8350", "\u597d\u7528", "\u7528\u5417"}


# ---------------------------------------------------------------- Suggestion sources

def suggest_baidu(q: str, timeout: int = 6) -> list[str]:
    """Fetch Baidu's public UTF-8 JSONP suggestions."""
    url = f"https://suggestion.baidu.com/su?wd={quote(q)}&ie=utf-8&oe=utf-8"
    r = requests.get(url, headers=UA, timeout=timeout)
    m = re.search(r"s:(\[.*?\])", r.text)
    return json.loads(m.group(1)) if m else []


def suggest_google(q: str, hl: str = "en", timeout: int = 6) -> list[str]:
    """Fetch Google's public Firefox-client JSON suggestions."""
    url = (f"https://suggestqueries.google.com/complete/search"
           f"?client=firefox&hl={hl}&q={quote(q)}")
    r = requests.get(url, headers=UA, timeout=timeout)
    data = json.loads(r.text)
    return [s for s in (data[1] if len(data) > 1 else []) if isinstance(s, str)]


# ---------------------------------------------------------------- Roots and matching

def _roots(cfg: dict) -> list[dict]:
    """Build up to 14 prioritized brand, competitor, and category roots."""
    out, seen = [], set()

    def add(root, kind, market):
        r = (root or "").strip()
        if len(r) < 2 or r.lower() in seen:
            return
        seen.add(r.lower())
        out.append({"root": r, "kind": kind, "market": market})

    b = cfg.get("brand") or {}
    market = cfg.get("market", "cn")
    add(b.get("name"), "brand", market)
    for al in (b.get("aliases") or [])[:2]:
        add(al, "brand", market)
    for c in cfg.get("competitors") or []:
        if c.get("confirmed") is False:
            continue
        add(c.get("name"), "competitor", c.get("market") or market)
    add(b.get("industry"), "category", market)
    for pdt in (b.get("products") or [])[:4]:
        add(pdt, "category", market)
    return out[:14]


NAV_RX = re.compile(r"\u4e0b\u8f7d|\u5b98\u7f51|\u5b98\u65b9\u7f51\u7ad9|\u5b89\u88c5|\u767b\u5f55|\u6ce8\u518c|\u5165\u53e3|\u5ba2\u6237\u7aef|\u624b\u673a\u7248|\u7834\u89e3|\u6fc0\u6d3b|\u4f1a\u5458|app\b|"
                    r"download|install|login|sign ?in|sign ?up|app store", re.I)


def _relevant(term: str, root: str) -> bool:
    """Reject navigation intent and entity drift in search suggestions."""
    if NAV_RX.search(term):
        return False
    tl = term.lower().replace(" ", "")
    latin = re.findall(r"[A-Za-z]{4,}", root.lower())
    if latin:
        return any(w in tl for w in latin)
    rb = {b for b in _bigrams(root) if re.match(r"[\u4e00-\u9fff]", b)}
    if not rb:
        return False
    tb = _bigrams(term)
    return len(rb & tb) * 2 >= len(rb)


def _classify(term: str, kind: str) -> str:
    low = term.lower()
    for grp, cues in GROUP_CUES:
        if any(c in low for c in cues):
            # Review cues imply recommendation intent when the root is a category.
            if grp == "brand_verification" and kind == "category":
                return "recommendation"
            return grp
    return "scenario"


def _bigrams(s: str) -> set[str]:
    cjk = re.findall(r"[\u4e00-\u9fff]{2,}", s)
    out = set()
    for w in cjk:
        out.update(w[i:i + 2] for i in range(len(w) - 1))
    out.update(w.lower() for w in re.findall(r"[A-Za-z]{3,}", s))
    return out - STOP_BIGRAMS


def _match_questions(cfg: dict, terms: list[dict]) -> dict:
    """Map expanded terms to question-bank demand signals without changing metrics."""
    demand: dict[str, dict] = {}
    for q in cfg.get("questions") or []:
        qb = _bigrams(q.get("text", ""))
        hits, roots, has_new = [], set(), False
        ql = q.get("text", "").lower()
        for t in terms:
            tb = _bigrams(t["term"]) | _bigrams(t["root"])
            latin_hit = any(w in ql for w in tb if re.match(r"[a-z]{4,}", w))
            if latin_hit or len(qb & tb) >= 2:
                hits.append(t["term"])
                roots.add(t["root"])
                has_new = has_new or t.get("new", False)
        if hits:
            demand[q["id"]] = {"terms": hits[:5], "n": len(hits),
                               "roots": sorted(roots)[:4], "new": has_new}
    return demand


# ---------------------------------------------------------------- LLM rewriting

CONVERT_PROMPT = """Rewrite each search suggestion below as a natural question a real user would ask an AI assistant.

Requirements:
- Answer Chinese suggestions in Chinese and English suggestions in natural English.
- Preserve the original intent and entities without adding unsupported details.
- Return one question per input line in the same order.
- Output JSON only: {"questions": ["...", "..."]}

Search suggestions:
"""


def _convert_llm(terms: list[dict]) -> bool:
    """Rewrite suggestions in batches of 40; retain templates on batch failure."""
    import sample as S
    plat = S.pick_llm()
    if not plat or not terms:
        return False
    ok_any = False
    for i in range(0, len(terms), 40):
        chunk = terms[i:i + 40]
        res = S.ask(plat, CONVERT_PROMPT + "\n".join(t["term"] for t in chunk), timeout=180, search=False)
        if not res.get("ok"):
            continue
        m = re.search(r"\{.*\}", res["answer"], re.S)
        if not m:
            continue
        try:
            qs = json.loads(m.group(0)).get("questions") or []
        except Exception:  # noqa: BLE001
            continue
        if len(qs) != len(chunk):
            continue
        changed = False
        for t, q in zip(chunk, qs):
            if isinstance(q, str) and q.strip():
                t["question"] = q.strip()
                changed = True
        ok_any = ok_any or changed
    return ok_any


# ---------------------------------------------------------------- Main flow

def run(slug: str, use_llm: bool = True) -> dict:
    cfg = G.load_config(slug)
    path = G.project_dir(slug) / "expand.json"
    prev = G.read_json(path, {}) or {}
    first_seen = {str(t.get("term") or "").strip().casefold():
                  t.get("first_seen") or prev.get("generated_at", "")
                  for t in prev.get("terms", []) if t.get("term")}

    roots = _roots(cfg)
    today = G.today()
    proj_market = cfg.get("market", "cn")
    seen, terms = set(), []
    root_n: dict[str, int] = {r["root"]: 0 for r in roots}
    n_calls = 0

    for r in roots:
        mkts = ["cn", "global"] if (r["market"] or proj_market) == "both" else [r["market"] or proj_market]
        for mk in mkts:
            for mod in MODS[mk][r["kind"]]:
                q = r["root"] + mod
                sugs = None
                for _ in range(2):
                    try:
                        sugs = suggest_baidu(q) if mk == "cn" else suggest_google(q)
                        break
                    except Exception as e:  # noqa: BLE001
                        err = type(e).__name__
                        time.sleep(0.5)
                if sugs is None:
                    G.info(f"  Query expansion request failed ({q}): {err}")
                    continue
                n_calls += 1
                time.sleep(0.15)
                for s in sugs[:10]:
                    key = s.strip().lower()
                    if not key or key == r["root"].lower() or key in seen:
                        continue
                    if not _relevant(s, r["root"]):
                        continue
                    if root_n[r["root"]] >= 25 or len(terms) >= 200:
                        continue
                    root_n[r["root"]] += 1
                    seen.add(key)
                    grp = _classify(s, r["kind"])
                    st = s.strip()
                    if re.search(r"[\uff1f?]$", st):
                        qtext = st
                    elif re.search(r"\u662f\u4ec0\u4e48|\u600e\u4e48|\u5982\u4f55|\u54ea\u4e2a|\u54ea\u4e9b|\u591a\u5c11\u94b1|\u5417$|^how |^what |^which |^is |^can ", st, re.I):
                        qtext = st + ("\uff1f" if mk == "cn" else "?")
                    else:
                        qtext = TEMPLATES[mk][grp].format(t=st)
                    terms.append({"term": st, "root": r["root"], "kind": r["kind"],
                                  "market": mk, "group": grp,
                                  "question": qtext,
                                  "first_seen": first_seen.get(key, today),
                                  "new": key not in first_seen})

    llm_used = use_llm and _convert_llm(terms)
    existing = {q.get("text", "").strip().lower() for q in cfg.get("questions") or []}
    for t in terms:
        t["in_bank"] = t["question"].strip().lower() in existing

    out = {"generated_at": today, "calls": n_calls, "llm": llm_used,
           "roots": roots, "terms": terms,
           "q_demand": _match_questions(cfg, terms)}
    G.write_json(path, out)
    G.info(f"Query expansion complete: {len(roots)} root terms → {len(terms)} candidates "
           f"({sum(1 for t in terms if t['new'])} new; rewriting: {'LLM' if llm_used else 'template'})")
    return out
