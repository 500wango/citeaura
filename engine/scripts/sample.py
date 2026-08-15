"""Sample AI answers and measure brand visibility across engines.

API and product-interface results are separate observation cohorts because
their source sets can differ. Each platform and terminal is recorded
independently.

Outputs: work/<slug>/samples/<run-id>.jsonl and
work/<slug>/metrics/<run-id>.json.
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

import requests

import geolib as G

# Provider registry. Market determines which question set a provider receives.
PROVIDERS = {
    # ---------------- China ----------------
    "glm": {
        "name": "Zhipu GLM", "market": "cn",
        "base": "https://open.bigmodel.cn/api/paas/v4",
        # Lightweight defaults prioritize comparable brand recognition measurements.
        "model": "glm-4-flash",
        "model_env": "GLM_MODEL",
        "key_env": "ZHIPUAI_API_KEY",
        "search": False,
        "note": "OpenAI-compatible endpoint without web search; sample the product interface separately.",
    },
    "doubao": {
        # Ark web search requires the optional content plugin.
        "name": "Doubao (Ark API)", "market": "cn",
        "protocol": "ark",
        "base": "https://ark.cn-beijing.volces.com/api/v3",
        "model": "doubao-seed-1-6-250615",
        "model_env": "ARK_MODEL",
        "key_env": "ARK_API_KEY",
        "search": True,
        "note": "Uses Responses with web_search when enabled, otherwise falls back to parametric knowledge.",
    },
    "deepseek": {
        "name": "DeepSeek", "market": "cn",
        "base": "https://api.deepseek.com/v1",
        "model": "deepseek-v4-flash",
        "model_env": "DEEPSEEK_MODEL",
        "key_env": "DEEPSEEK_API_KEY",
        "search": False,
        "note": "The official API does not search the web; it measures parametric brand knowledge.",
    },
    "kimi": {
        "name": "Kimi", "market": "cn",
        "base": "https://api.moonshot.cn/v1",
        "model": "kimi-k2-0905-preview",
        "model_env": "MOONSHOT_MODEL",
        "key_env": "MOONSHOT_API_KEY",
        "search": False,
        "note": "Web search is disabled; sample the product interface separately for search behavior.",
    },
    "minimax": {
        "name": "MiniMax", "market": "cn",
        "base": "https://api.minimaxi.com/v1",
        "model": "MiniMax-M2",
        "model_env": "MINIMAX_MODEL",
        "key_env": "MINIMAX_API_KEY",
        "search": False,
        "note": "OpenAI-compatible endpoint without web search; sample Hailuo AI separately.",
    },
    # ---------------- Global ----------------
    "gemini": {
        "name": "Gemini", "market": "global",
        "base": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-2.5-flash",
        "model_env": "GEMINI_MODEL",
        "key_env": "GEMINI_API_KEY",
        "search": False,
        "note": "The OpenAI-compatible endpoint has no grounding; sample AI Overviews separately.",
    },
    "openai": {
        "name": "OpenAI(ChatGPT)", "market": "global",
        "base": os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        "model": "gpt-4o-mini",
        "model_env": "OPENAI_MODEL",
        "key_env": "OPENAI_API_KEY",
        "search": False,
        "note": "Chat Completions does not search by default; sample ChatGPT Search separately.",
    },
    "claude": {
        # Anthropic Messages returns content blocks instead of OpenAI choices.
        "name": "Claude", "market": "global",
        "protocol": "anthropic",
        "base": "https://api.anthropic.com/v1",
        "model": "claude-sonnet-5",
        "model_env": "ANTHROPIC_MODEL",
        "key_env": "ANTHROPIC_API_KEY",
        "search": False,
        "note": "The API does not search the web; sample Claude Web Search separately.",
    },
    "grok": {
        "name": "Grok", "market": "global",
        "base": "https://api.x.ai/v1",
        "model": "grok-3-mini",
        "model_env": "GROK_MODEL",
        "key_env": "XAI_API_KEY",
        "search": False,
        "note": "The xAI API does not search the web; sample the X product interface separately.",
    },
    "perplexity": {
        "name": "Perplexity", "market": "global",
        "base": "https://api.perplexity.ai",
        "model": "sonar",
        "model_env": "PERPLEXITY_MODEL",
        "key_env": "PERPLEXITY_API_KEY",
        "search": True,
        "note": "Native web search with citations.",
    },
}

# Providers without a public search API require product-interface sampling.
MANUAL_ONLY = {
    "nano_ai": ("Nano AI Search (360)", "cn"),
    "baidu": ("Baidu AI Search", "cn"),
    "doubao_app": ("Doubao App / Web", "cn"),
    "chatgpt": ("ChatGPT Search", "global"),
    "claude_web": ("Claude Web Search", "global"),
}


def market_of(platform: str) -> str:
    if platform in PROVIDERS:
        return PROVIDERS[platform]["market"]
    if platform in MANUAL_ONLY:
        return MANUAL_ONLY[platform][1]
    # Unknown codes remain outside market aggregates.
    G.info(f"Unrecognized platform code {platform!r}, market tagged as unknown")
    return "unknown"


def label_of(platform: str) -> str:
    if platform in PROVIDERS:
        return PROVIDERS[platform]["name"]
    if platform in MANUAL_ONLY:
        return MANUAL_ONLY[platform][0]
    return platform


def questions_for(cfg: dict, platform: str) -> list[dict]:
    """Route questions by market without mixing regional cohorts."""
    m = market_of(platform)
    out = []
    for q in G.normalize_question_ids(cfg.get("questions", [])):
        qm = q.get("market") or cfg.get("market", "cn")
        if qm in ("both", m):
            out.append(q)
    return out


def _p_model(p: dict) -> str:
    """Resolve model overrides at call time so configuration changes apply immediately."""
    menv = p.get("model_env")
    return (os.environ.get(menv) if menv else None) or p["model"]


def model_for(platform: str) -> str:
    return _p_model(PROVIDERS[platform])


def available(platform: str) -> bool:
    p = PROVIDERS.get(platform)
    return bool(p and os.environ.get(p["key_env"]))


# Shared fallback order for modules that need one configured LLM.
LLM_PREFS = ("deepseek", "glm", "doubao", "openai", "gemini")


def pick_llm(prefer: str | None = None):
    """Return the first configured provider in the preference chain."""
    cands = [prefer] if prefer else list(LLM_PREFS)
    return next((c for c in cands if c and available(c)), None)


def ask_ark(p: dict, key: str, question: str, timeout: int) -> dict:
    """Use Ark Responses with web search, then fall back to chat completions."""
    H = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    try:
        r = requests.post(f"{p['base']}/responses", headers=H,
                          json={"model": _p_model(p), "input": question,
                                "tools": [{"type": "web_search"}]}, timeout=timeout)
        if r.status_code == 200:
            d = r.json()
            answer, refs = "", []
            for item in d.get("output") or []:
                for c in item.get("content") or []:
                    if c.get("type") in ("output_text", "text"):
                        answer += c.get("text", "")
                    for ann in c.get("annotations") or []:
                        if ann.get("url"):
                            refs.append({"url": ann["url"], "title": ann.get("title", "")})
                for res in item.get("results") or []:
                    if isinstance(res, dict) and res.get("url"):
                        refs.append({"url": res["url"], "title": res.get("title", "")})
            if answer:
                seen = set()
                refs = [c for c in refs if not (c["url"] in seen or seen.add(c["url"]))]
                return {"ok": True, "answer": answer, "citations": refs,
                        "raw_model": _p_model(p), "searched": True}
        elif "ToolNotOpen" not in r.text:
            return {"ok": False, "answer": "", "error": f"HTTP {r.status_code}: {r.text[:300]}"}
    except Exception:  # noqa: BLE001
        pass  # Fall through to the non-search endpoint.

    try:
        r = requests.post(f"{p['base']}/chat/completions", headers=H,
                          json={"model": _p_model(p),
                                "messages": [{"role": "user", "content": question}]}, timeout=timeout)
        if r.status_code != 200:
            return {"ok": False, "answer": "", "error": f"HTTP {r.status_code}: {r.text[:300]}"}
        d = r.json()
        return {"ok": True, "answer": d["choices"][0]["message"].get("content") or "",
                "citations": [], "raw_model": _p_model(p), "searched": False}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "answer": "", "error": f"{type(e).__name__}: {e}"}


def ask_anthropic(p: dict, key: str, question: str, timeout: int) -> dict:
    """Call the native Anthropic Messages API and parse content blocks."""
    delays = (1, 3)
    for attempt in range(len(delays) + 1):
        try:
            r = requests.post(
                f"{p['base']}/messages",
                headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                         "content-type": "application/json"},
                # Bound output length to keep requests within the default timeout.
                json={"model": _p_model(p), "max_tokens": 4096,
                      "messages": [{"role": "user", "content": question}]},
                timeout=timeout,
            )
            if r.status_code != 200:
                if (r.status_code == 429 or r.status_code >= 500) and attempt < len(delays):
                    time.sleep(delays[attempt])
                    continue
                return {"ok": False, "answer": "", "error": f"HTTP {r.status_code}: {r.text[:300]}"}
            d = r.json()
            if d.get("stop_reason") == "refusal":
                return {"ok": False, "answer": "", "error": "Model refusal (stop_reason=refusal)"}
            answer = "".join(b.get("text", "") for b in d.get("content", [])
                             if b.get("type") == "text")
            return {"ok": True, "answer": answer, "citations": [],
                    "raw_model": d.get("model", _p_model(p))}
        except requests.exceptions.Timeout as e:
            if attempt < len(delays):
                time.sleep(delays[attempt])
                continue
            return {"ok": False, "answer": "", "error": f"{type(e).__name__}: {e}"}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "answer": "", "error": f"{type(e).__name__}: {e}"}


def ask(platform: str, question: str, timeout: int = 120) -> dict:
    p = PROVIDERS[platform]
    key = os.environ.get(p["key_env"])
    if not key:
        return {"ok": False, "answer": "", "error": f"Missing environment variable {p['key_env']}"}
    if p.get("protocol") == "ark":
        return ask_ark(p, key, question, timeout)
    if p.get("protocol") == "anthropic":
        return ask_anthropic(p, key, question, timeout)
    body = {
        "model": _p_model(p),
        "messages": [{"role": "user", "content": question}],
        "temperature": 0.7,
    }
    body.update(p.get("extra", {}))
    delays = (1, 3)  # Retry timeouts, rate limits, and server errors twice.
    for attempt in range(len(delays) + 1):
        try:
            r = requests.post(
                f"{p['base']}/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json=body,
                timeout=timeout,
            )
            if r.status_code != 200:
                err = {"ok": False, "answer": "", "error": f"HTTP {r.status_code}: {r.text[:300]}"}
                if (r.status_code == 429 or r.status_code >= 500) and attempt < len(delays):
                    time.sleep(delays[attempt])
                    continue
                return err
            data = r.json()
            msg = data["choices"][0]["message"]
            answer = msg.get("content") or ""
            # Providers expose search sources through different response fields.
            refs = []
            for item in (data.get("search_info") or {}).get("search_results", []) or []:
                if item.get("url"):
                    refs.append({"url": item["url"], "title": item.get("title", "")})
            for item in data.get("search_results") or []:
                if isinstance(item, dict) and item.get("url"):
                    refs.append({"url": item["url"], "title": item.get("title", "")})
            for u in data.get("citations") or []:
                if isinstance(u, str):
                    refs.append({"url": u, "title": ""})
            seen = set()
            refs = [c for c in refs if not (c["url"] in seen or seen.add(c["url"]))]
            return {"ok": True, "answer": answer, "citations": refs, "raw_model": data.get("model", _p_model(p))}
        except requests.exceptions.Timeout as e:
            if attempt < len(delays):
                time.sleep(delays[attempt])
                continue
            return {"ok": False, "answer": "", "error": f"{type(e).__name__}: {e}"}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "answer": "", "error": f"{type(e).__name__}: {e}"}


# ------------------------------------------------------------ Answer analysis

URL_RE = re.compile(r"https?://[^\s\)\]\"'\u3002\uff0c\uff1b]+")
MIN_PLATFORM_SAMPLES = 5
MIN_TOTAL_SAMPLES = 20
MIN_REPRESENTATIVE_PLATFORMS = 2


def entities_of(cfg: dict) -> tuple[list[str], dict[str, list[str]]]:
    """Return all candidate names and aliases keyed by canonical name."""
    alias = {}
    b = cfg["brand"]
    alias[b["name"]] = [b["name"]] + list(b.get("aliases", []) or [])
    for c in cfg.get("competitors", []) or []:
        alias[c["name"]] = [c["name"]] + list(c.get("aliases", []) or [])
    return list(alias.keys()), alias


_LATIN = re.compile(r"[A-Za-z0-9]")
_NEG_RE = re.compile(
    r"\u4e0d\u662f|\u5e76\u975e|\u4e0d\u5c5e\u4e8e|\u4e0d\u540c\u4e8e|not |isn't|aren't",
    re.IGNORECASE,
)
_SENT_END = "\u3002\uff01\uff1f!?\n"

# Conservative multilingual cues only flag nearby text for human review.
NEG_CUES = re.compile(
    r"\u4e0d\u63a8\u8350|\u907f\u96f7|\u7f3a\u70b9|\u52a3\u52bf|\u6295\u8bc9|\u5dee\u8bc4|\u8dd1\u8def|\u9a97\u5c40|"
    r"\u5272\u97ed\u83dc|\u4e0d\u9760\u8c31|\u614e\u7528|\u7ffb\u8f66|\u5df2\u5012\u95ed|\u505c\u6b62\u8fd0\u8425|\u7ef4\u6743|\u9000\u6b3e\u96be"
    r"|not recommended|avoid|scam|complaints?|lawsuit|shut ?down|worse than|downsides?",
    re.IGNORECASE)


def _alias_spans(text: str, alias: str) -> list[tuple[int, int]]:
    """Return alias spans with Latin-token boundaries at Latin edges."""
    left = r"(?<![A-Za-z0-9])" if _LATIN.match(alias[0]) else ""
    right = r"(?![A-Za-z0-9])" if _LATIN.match(alias[-1]) else ""
    if left or right:
        return [m.span() for m in re.finditer(left + re.escape(alias) + right, text, re.IGNORECASE)]
    return [m.span() for m in re.finditer(re.escape(alias), text)]


def _sentence_at(text: str, pos: int) -> str:
    start = max([text.rfind(c, 0, pos) for c in _SENT_END] + [-1]) + 1
    ends = [text.find(c, pos) + 1 for c in _SENT_END if text.find(c, pos) != -1]
    return text[start:min(ends) if ends else len(text)]


def _entity_hit(text: str, aliases: list[str]) -> tuple[int, bool]:
    """Return the first valid hit and whether a negated hit needs review."""
    hits = sorted((s, e) for a in aliases if a for s, e in _alias_spans(text, a))
    valid, negated = [], False
    for s, e in hits:
        if _NEG_RE.search(_sentence_at(text, s)):
            negated = True
        else:
            valid.append(s)
    return (min(valid) if valid else -1), negated


def first_pos(text: str, names: list[str]) -> int:
    return _entity_hit(text, names)[0]


def _recommendation_order(text: str, aliases: dict[str, list[str]]) -> tuple[list[str], dict[str, int], str | None]:
    """Extract rank only from explicit numbered, bulleted, or tabular lists."""
    ranked: list[tuple[int, int, str]] = []
    sequence = 0
    for line_no, line in enumerate((text or "").splitlines()):
        number = re.match(r"^\s*(\d{1,2})[.)、:]\s+", line)
        bullet = re.match(r"^\s*[-*•]\s+", line)
        table = line.strip().startswith("|") and line.count("|") >= 2 and not re.search(r"\|\s*:?-{2,}", line)
        if not (number or bullet or table):
            continue
        sequence += 1
        rank = int(number.group(1)) if number else sequence
        for name, names in aliases.items():
            if any(alias and _alias_spans(line, alias) for alias in names):
                ranked.append((rank, line_no, name))
    ordered = []
    for _rank, _line, name in sorted(ranked):
        if name not in ordered:
            ordered.append(name)
    ranks = {}
    for rank, _line, name in sorted(ranked):
        ranks.setdefault(name, rank)
    return ordered, ranks, ("explicit_list" if ordered else None)


def _citation_supports_brand(citation: dict, aliases: list[str]) -> bool:
    if citation.get("supports_brand") is True:
        return True
    evidence = " ".join(str(citation.get(key) or "") for key in ("title", "snippet", "text", "name"))
    try:
        evidence += " " + urlparse(str(citation.get("url") or "")).path.replace("-", " ").replace("_", " ")
    except ValueError:
        pass
    return any(alias and _alias_spans(evidence, alias) for alias in aliases)


def brand_in_question(question: str, cfg: dict) -> bool:
    """Return whether the prompt names the brand and would bias mention rate."""
    b = cfg["brand"]
    names = [b["name"]] + list(b.get("aliases", []) or [])
    host = urlparse(b.get("site", "")).netloc.lower().removeprefix("www.")
    if host and host in question.lower():
        return True
    return any(n and n.lower() in question.lower() for n in names)


def analyze_answer(answer: str, cfg: dict, citations: list | None = None) -> dict:
    brand = cfg["brand"]["name"]
    names, alias = entities_of(cfg)
    positions, needs_review = {}, False
    for n in names:
        pos, negated = _entity_hit(answer, alias[n])
        positions[n] = pos
        needs_review = needs_review or negated
    present = {n: p >= 0 for n, p in positions.items()}
    ordered = [n for n, p in sorted(positions.items(), key=lambda x: x[1]) if p >= 0]
    ranked, recommendation_ranks, rank_basis = _recommendation_order(answer, alias)

    urls = [u for u in URL_RE.findall(answer)]
    brand_cited_domains = []
    for c in citations or []:
        if c.get("url"):
            urls.append(c["url"])
            try:
                host = urlparse(c["url"]).netloc.lower().removeprefix("www.")
            except ValueError:
                host = ""
            if host and _citation_supports_brand(c, alias[brand]):
                brand_cited_domains.append(host)
    domains = []
    for u in urls:
        try:
            h = urlparse(u).netloc.lower().removeprefix("www.")
            if h:
                domains.append(h)
        except Exception:  # noqa: BLE001
            pass

    own = urlparse(cfg["brand"]["site"]).netloc.lower().removeprefix("www.")

    # Negative cues are evaluated only near brand mentions.
    neg = set()
    if present.get(brand):
        for a in alias[brand]:
            for s, e in _alias_spans(answer, a):
                for mm in NEG_CUES.finditer(answer[max(0, s - 80):e + 160]):
                    neg.add(mm.group(0).lower())

    return {
        "brand_mentioned": present.get(brand, False),
        "brand_rank": recommendation_ranks.get(brand, 0),
        "rank_basis": rank_basis,
        "first_mention_order": (ordered.index(brand) + 1) if brand in ordered else 0,
        "candidates": ordered,
        "competitors_mentioned": [n for n in names if n != brand and present.get(n)],
        "cited_domains": sorted(set(domains)),
        "brand_cited_domains": sorted(set(brand_cited_domains)),
        "own_domain_cited": any(d == own or d.endswith("." + own) for d in domains),
        "answer_chars": len(answer),
        "needs_review": needs_review or bool(neg),
        "negative_cues": sorted(neg),
    }


def dedup_rows(rows: list[dict]) -> list[dict]:
    seen: dict[tuple, dict] = {}
    for r in rows:
        seen[(r.get("run_id") or "legacy", r.get("platform"), r.get("question_id"),
              r.get("round"), r.get("sample_mode"))] = r
    return list(seen.values())


def aggregate(rows: list[dict], cfg: dict) -> dict:
    by_platform: dict[str, list[dict]] = {}
    for r in rows:
        by_platform.setdefault(r["platform"], []).append(r)

    out = {}
    for plat, all_rs in by_platform.items():
        probe = [r for r in all_rs if r.get("brand_in_question")
                 or brand_in_question(r.get("question", ""), cfg)]
        rs = [r for r in all_rs if r not in probe]
        n = len(rs)
        market = (rs[0].get("market") if rs else None) or market_of(plat)
        mentioned = [r for r in rs if r["analysis"]["brand_mentioned"]]
        ranks = [r["analysis"]["brand_rank"] for r in mentioned if r["analysis"]["brand_rank"]]
        comp = {}
        dom = {}
        brand_dom = {}
        for r in rs:
            for c in r["analysis"]["competitors_mentioned"]:
                comp[c] = comp.get(c, 0) + 1
            for d in r["analysis"]["cited_domains"]:
                dom[d] = dom.get(d, 0) + 1
            for d in r["analysis"].get("brand_cited_domains") or []:
                brand_dom[d] = brand_dom.get(d, 0) + 1
        out[plat] = {
            "market": market,
            "label": label_of(plat),
            "samples": n,
            "mention_rate": round(len(mentioned) / n, 3) if n else None,
            "top1_rate": round(sum(1 for r in mentioned if r["analysis"]["brand_rank"] == 1) / n, 3) if n else None,
            "top3_rate": round(sum(1 for r in mentioned if 1 <= r["analysis"]["brand_rank"] <= 3) / n, 3) if n else None,
            "avg_rank": round(sum(ranks) / len(ranks), 2) if ranks else None,
            "own_domain_cite_rate": round(sum(1 for r in rs if r["analysis"]["own_domain_cited"]) / n, 3) if n else None,
            "competitor_mentions": dict(sorted(comp.items(), key=lambda x: -x[1])),
            "top_cited_domains": dict(sorted(dom.items(), key=lambda x: -x[1])[:15]),
            "top_brand_cited_domains": dict(sorted(brand_dom.items(), key=lambda x: -x[1])[:15]),
            "confidence": {
                "sufficient": n >= MIN_PLATFORM_SAMPLES,
                "minimum_samples": MIN_PLATFORM_SAMPLES,
                "limitations": [] if n >= MIN_PLATFORM_SAMPLES else
                    [f"Only {n} valid unprompted samples; {MIN_PLATFORM_SAMPLES} required for platform conclusions"],
            },
            "probe": {
                "samples": len(probe),
                "recognized_rate": round(sum(1 for r in probe if r["analysis"]["brand_mentioned"]) / len(probe), 3) if probe else None,
                "own_domain_cite_rate": round(sum(1 for r in probe if r["analysis"]["own_domain_cited"]) / len(probe), 3) if probe else None,
            },
        }
    return out


def confirm_competitors(slug: str, rows: list[dict]):
    evidence: dict[str, list[dict]] = {}
    for row in rows:
        if row.get("brand_in_question") or row.get("needs_review") or not row.get("ok"):
            continue
        for name in row.get("analysis", {}).get("competitors_mentioned") or []:
            evidence.setdefault(name, []).append(row)
    eligible = set()
    for name, hits in evidence.items():
        questions = {row.get("question_id") or row.get("question") for row in hits}
        platforms = {row.get("platform") for row in hits}
        if len(hits) >= 2 and (len(questions) >= 2 or len(platforms) >= 2):
            eligible.add(name)
    if not eligible:
        return
    cfg = G.load_config(slug)
    confirmed = []
    for c in cfg.get("competitors", []) or []:
        if c.get("confirmed") is False and c.get("name") in eligible:
            c["confirmed"] = True
            c["confirmation"] = {
                "method": "repeated_unprompted_samples",
                "samples": len(evidence[c["name"]]),
                "questions": len({r.get("question_id") or r.get("question") for r in evidence[c["name"]]}),
                "platforms": len({r.get("platform") for r in evidence[c["name"]]}),
                "confirmed_at": G.now_iso(),
            }
            confirmed.append(c["name"])
    if confirmed:
        G.save_config(slug, cfg)
        G.info("  Competitors confirmed by sampling: " + ", ".join(confirmed))


def _run_identity(cfg: dict, platforms: list[str], repeat: int, source: str) -> dict:
    questions = G.normalize_question_ids(cfg.get("questions", []))
    question_set_id = G.stable_hash([
        {"id": q["id"], "text": q.get("text", ""), "market": q.get("market")}
        for q in questions
    ])
    return {
        "run_id": G.new_run_id("sample"),
        "question_set_id": question_set_id,
        "cohort_id": G.stable_hash({"question_set_id": question_set_id,
                                     "platforms": sorted(platforms), "repeat": repeat, "source": source}),
    }


def _measurement(platforms: dict) -> dict:
    measured = [item for item in platforms.values() if item.get("mention_rate") is not None
                and int(item.get("samples") or 0) > 0]
    samples = sum(int(item.get("samples") or 0) for item in measured)
    platform_count = len(measured)
    limitations = []
    if samples < MIN_TOTAL_SAMPLES:
        limitations.append(f"Only {samples} valid unprompted samples; {MIN_TOTAL_SAMPLES} required")
    if platform_count < MIN_REPRESENTATIVE_PLATFORMS:
        limitations.append(f"Only {platform_count} measured platform(s); {MIN_REPRESENTATIVE_PLATFORMS} required")
    weighted = (sum(float(item["mention_rate"]) * int(item["samples"]) for item in measured) / samples
                if samples else None)
    return {
        "effective_samples": samples, "platform_count": platform_count,
        "minimum_samples": MIN_TOTAL_SAMPLES, "minimum_platforms": MIN_REPRESENTATIVE_PLATFORMS,
        "sufficient": not limitations, "limitations": limitations,
        "weighted_mention_rate": round(weighted, 4) if weighted is not None else None,
    }


def _history_snapshot(slug: str, rows: list[dict]) -> dict:
    """Freeze mutable health inputs so historical trends remain reproducible."""
    import analytics as A

    pdir = G.project_dir(slug)
    blueprint = G.read_json(pdir / "blueprint.json", None)
    factcheck = G.read_json(pdir / "factcheck.json", []) or []
    return {
        "captured_at": G.now_iso(),
        "health": A.health(slug, blueprint, factcheck, rows),
        "blueprint_coverage": (blueprint or {}).get("coverage"),
        "factcheck": {
            "checked": sum(item.get("state") in ("consistent", "incorrect", "missing") for item in factcheck),
            "consistent": sum(item.get("state") == "consistent" for item in factcheck),
        },
    }


# ------------------------------------------------------------ Commands


def run(slug: str, platforms: list[str] | None = None, repeat: int = 1, limit: int | None = None) -> dict:
    cfg = G.load_config(slug)
    cfg = {**cfg, "questions": G.normalize_question_ids(cfg.get("questions", []))}
    if not cfg.get("questions"):
        G.die("geo.json is missing questions. Please populate questions first.")

    plats = platforms or [p for p in cfg.get("platforms", []) if p in PROVIDERS]
    runnable = [p for p in plats if available(p)]
    skipped = [p for p in plats if not available(p)]
    if skipped:
        G.info("Skipped (Missing API Key): " + ", ".join(f"{p}({PROVIDERS[p]['key_env']})" for p in skipped))
    if not runnable:
        G.info("No runnable API platforms available. Use `geo.py sample-sheet` for manual sampling.")
        return {}

    jobs = []
    for plat in runnable:
        questions = questions_for(cfg, plat)
        if limit:
            questions = questions[:limit]
        if not questions:
            G.info(f"Skipped {plat}: No questions matching {market_of(plat)} market")
            continue
        G.info(f"[{plat}] {market_of(plat)} market · {len(questions)} questions × {repeat} round(s)")
        for q in questions:
            for k in range(repeat):
                jobs.append((plat, q, k + 1))

    identity = _run_identity(cfg, runnable, repeat, "api")
    pdir = G.project_dir(slug)
    path = pdir / "samples" / f"{identity['run_id']}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)

    def one(job):
        plat, q, rnd = job
        t0 = time.monotonic()
        res = ask(plat, q["text"])
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        rec = {
            "date": G.today(), "ts": G.now_iso(),
            **identity,
            "platform": plat, "platform_name": PROVIDERS[plat]["name"],
            "market": market_of(plat), "terminal": "api", "sample_mode": "api",
            "evidence_level": "B_reproducible_api",
            "search_enabled": res.get("searched", PROVIDERS[plat].get("search", False)),
            "question_id": q.get("id"), "question": q["text"], "round": rnd,
            "brand_in_question": brand_in_question(q["text"], cfg),
            "ok": res["ok"], "error": res.get("error"),
            "elapsed_ms": elapsed_ms,
            "answer": res.get("answer", ""), "citations": res.get("citations", []),
        }
        rec["sampling_label"] = ("api_search_grounded" if rec["search_enabled"] else "api_parametric_knowledge")
        rec["analysis"] = analyze_answer(rec["answer"], cfg, rec["citations"]) if res["ok"] else {
            "brand_mentioned": False, "brand_rank": 0, "candidates": [],
            "competitors_mentioned": [], "cited_domains": [], "own_domain_cited": False,
            "brand_cited_domains": [], "answer_chars": 0, "needs_review": False,
            "negative_cues": [], "first_mention_order": 0, "rank_basis": None,
        }
        rec["needs_review"] = bool(rec["analysis"].get("needs_review"))
        return rec

    # Providers run concurrently while requests within one provider stay serial.
    rows, done, total = [], 0, len(jobs)
    lock = threading.Lock()
    fh = path.open("a", encoding="utf-8")  # Preserve completed samples on interruption.

    def worker(plat_jobs):
        nonlocal done
        out = []
        for job in plat_jobs:
            rec = one(job)
            with lock:
                done += 1
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                fh.flush()
                flag = "✓" if rec["analysis"]["brand_mentioned"] else ("✗" if not rec["ok"] else "·")
                print(f"[geo] {done:3d}/{total} {flag} [{rec['platform']}] {rec['question'][:32]}",
                      file=sys.stderr, flush=True)
            out.append(rec)
            time.sleep(0.4)
        return out

    by_plat: dict[str, list] = {}
    for job in jobs:
        by_plat.setdefault(job[0], []).append(job)
    with ThreadPoolExecutor(max_workers=max(1, len(by_plat))) as ex:
        for fut in as_completed([ex.submit(worker, v) for v in by_plat.values()]):
            try:
                rows.extend(fut.result())
            except Exception as e:  # noqa: BLE001
                G.info(f"Engine query interrupted: {type(e).__name__}: {e}")
    fh.close()

    all_rows = dedup_rows(G.read_jsonl(path))
    ok_rows = [r for r in all_rows if r.get("ok")]
    aggregated = aggregate(ok_rows, cfg)
    metrics = {
        "slug": slug, "date": G.today(), "generated_at": G.now_iso(), **identity,
        "question_count": len(cfg.get("questions", [])), "sample_count": len(all_rows),
        "successful_sample_count": len(ok_rows), "platforms": aggregated,
        "measurement": _measurement(aggregated),
        "history_snapshot": _history_snapshot(slug, ok_rows),
    }
    G.write_json(pdir / "metrics" / f"{identity['run_id']}.json", metrics)
    confirm_competitors(slug, ok_rows)
    G.info(f"Sampling complete: {len(rows)} answers collected → {path}")
    return metrics


def sheet(slug: str) -> Path:
    """Export a Markdown sheet for product-interface sampling."""
    cfg = G.load_config(slug)
    plats = [p for p in cfg.get("platforms", []) if p in MANUAL_ONLY or not available(p)]
    lines = [
        f"# {cfg['brand']['name']} - Manual AI answer sampling - {G.today()}",
        "",
        "Ask every question on each platform and paste the complete answer, including citations,",
        "into its ```answer block. Then run `python3 scripts/geo.py sample-import --slug "
        + slug + " --file <sheet>`.",
        "",
        "Blank answers are skipped and never counted as missing brand mentions.",
        "",
    ]
    for plat in plats:
        qs = questions_for(cfg, plat)
        if not qs:
            continue
        mk = "China" if market_of(plat) == "cn" else "Global"
        lines += [f"## platform: {plat}", f"> {label_of(plat)} ({mk} market - {len(qs)} questions)", ""]
        for q in qs:
            lines += [f"### {q.get('id')} · {q['text']}", "", "```answer", "", "```", ""]
    path = G.project_dir(slug) / "samples" / f"{G.today()}-manual.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), "utf-8")
    G.info(f"Sampling sheet exported: {path}")
    return path


def sample_import(slug: str, file: str) -> dict:
    cfg = G.load_config(slug)
    cfg = {**cfg, "questions": G.normalize_question_ids(cfg.get("questions", []))}
    text = Path(file).read_text("utf-8")
    qmap = {q.get("id"): q["text"] for q in cfg.get("questions", [])}

    rows, platform = [], "manual"
    blocks = re.split(r"(?m)^##\s+platform:\s*(\S+)\s*$", text)
    manual_platforms = [blocks[i].strip() for i in range(1, len(blocks), 2)]
    identity = _run_identity(cfg, manual_platforms, 1, "manual")
    # Blocks alternate between platform identifiers and platform bodies.
    for i in range(1, len(blocks), 2):
        platform = blocks[i].strip()
        body = blocks[i + 1]
        for m in re.finditer(r"(?ms)^###\s+(\S+)\s*·\s*(.+?)\n(.*?)```answer\n(.*?)```", body):
            qid, qtext, _, answer = m.group(1), m.group(2).strip(), m.group(3), m.group(4).strip()
            if not answer or qid not in qmap:
                continue
            rec = {
                "date": G.today(), "ts": G.now_iso(),
                **identity,
                "platform": platform,
                "platform_name": label_of(platform),
                "market": market_of(platform),
                "terminal": "manual", "sample_mode": "manual",
                "sampling_label": "manual_product_interface",
                "evidence_level": "A_manual_product_sample", "search_enabled": None,
                "search_evidence": "not_recorded",
                "question_id": qid, "question": qmap.get(qid, qtext), "round": 1,
                "ok": True, "error": None, "answer": answer, "citations": [],
            }
            rec["analysis"] = analyze_answer(answer, cfg)
            rec["needs_review"] = bool(rec["analysis"].get("needs_review"))
            rows.append(rec)

    if not rows:
        G.die("No answers parsed, please check if ```answer blocks are filled")
    pdir = G.project_dir(slug)
    path = pdir / "samples" / f"{identity['run_id']}.jsonl"
    G.write_jsonl(path, rows)
    all_rows = [r for r in dedup_rows(rows) if r.get("ok")]
    aggregated = aggregate(all_rows, cfg)
    metrics = {
        "slug": slug, "date": G.today(), "generated_at": G.now_iso(), **identity,
        "question_count": len(qmap), "sample_count": len(all_rows),
        "successful_sample_count": len(all_rows), "platforms": aggregated,
        "measurement": _measurement(aggregated),
        "history_snapshot": _history_snapshot(slug, all_rows),
    }
    G.write_json(pdir / "metrics" / f"{identity['run_id']}.json", metrics)
    confirm_competitors(slug, all_rows)
    G.info(f"Imported {len(rows)} manual sample(s) → {path}")
    return metrics
