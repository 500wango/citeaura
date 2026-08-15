"""Crawl site-level signals and a representative set of content pages.

Outputs:
  work/<slug>/evidence/site.json      Site-level evidence
  work/<slug>/evidence/pages.jsonl    One structured record per page
  work/<slug>/evidence/html/<run>/    Raw HTML snapshots for review
"""

from __future__ import annotations

import re
import shutil
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from html import unescape
from pathlib import Path
from urllib.parse import urlparse

import geolib as G

# High-value path signals used only for crawl prioritization.
PRIORITY = [
    "product", "pricing", "price", "solution", "case", "customer", "doc", "docs",
    "help", "faq", "about", "news", "blog", "guide", "compare", "vs", "feature",
    "\u4ea7\u54c1", "\u4ef7\u683c", "\u65b9\u6848", "\u6848\u4f8b", "\u5ba2\u6237",
    "\u6587\u6863", "\u5e2e\u52a9", "\u5173\u4e8e", "\u65b0\u95fb", "\u535a\u5ba2",
]


def discover_sitemap(root: str, limit: int = 300) -> list[str]:
    urls: list[str] = []
    seen_maps = set()
    queue = [G.normalize_url(root, "/sitemap.xml"), G.normalize_url(root, "/sitemap_index.xml")]

    robots = G.fetch_text(G.normalize_url(root, "/robots.txt"))
    for m in re.findall(r"(?im)^\s*sitemap:\s*(\S+)", robots):
        candidate = G.normalize_url(root, unescape(m.strip()))
        if candidate and G.same_site(root, candidate):
            queue.append(candidate)

    # Bound sitemap fan-out because large indexes may reference hundreds of shards.
    while queue and len(urls) < limit and len(seen_maps) < 8:
        sm = queue.pop(0)
        if not sm or sm in seen_maps or not G.same_site(root, sm):
            continue
        seen_maps.add(sm)
        xml = G.fetch_text(sm)
        if not xml:
            continue
        locs = [G.normalize_url(root, unescape(value.strip()))
                for value in re.findall(r"<loc>\s*([^<]+?)\s*</loc>", xml, re.I)]
        locs = [value for value in locs if value and G.same_site(root, value)]
        if re.search(r"<sitemapindex\b", xml, re.I):
            queue.extend(locs[:20])
        else:
            urls.extend(locs)
    return urls


def discover_links(root: str, html: str, limit: int = 200) -> list[str]:
    soup = G.parse_html(html)
    out: list[str] = []
    for a in soup.find_all("a", href=True):
        u = G.normalize_url(root, a["href"])
        if u and G.same_site(root, u) and u not in out:
            out.append(u)
        if len(out) >= limit:
            break
    return out


def rank(urls: list[str], root: str) -> list[str]:
    """Rank shallow, high-value, primary-host URLs ahead of incidental pages."""
    root_host = urlparse(root).netloc.lower().removeprefix("www.")

    def key(u: str):
        parts = urlparse(u)
        p = parts.path or "/"
        depth = len([x for x in p.split("/") if x])
        hit = 0 if any(k in u.lower() for k in PRIORITY) else 1
        # Prefer the primary host over chat, status, and other application subdomains.
        subdomain = 0 if parts.netloc.lower().removeprefix("www.") == root_host else 1
        return (0 if u.rstrip("/") == root.rstrip("/") else 1, subdomain, hit, depth, len(u))

    # Drop non-document URLs and collapse trailing-slash variants.
    seen: "OrderedDict[str, str]" = OrderedDict()
    for u in [root] + urls:
        if not G.is_fetchable(u) or not G.same_site(root, u):
            continue
        seen.setdefault(u.rstrip("/") or u, u)
    return sorted(seen.values(), key=key)


LOCALE_SEGMENT = re.compile(r"^(?:[a-z]{2}(?:-[a-z]{2})?|zh-cn|zh-hans|zh-hant)$", re.I)


def url_role(url: str) -> str:
    path = urlparse(url).path.lower()
    if re.search(r"/(?:login|signin|signup|register|account|auth|cart|checkout)(?:/|$)", path):
        return "utility"
    if re.search(r"/(?:help|support|docs?|documentation|faq|kb|guide|tutorial)(?:/|$)", path):
        return "support"
    if re.search(r"/(?:blog|news|press|insights?|articles?)(?:/|$)", path):
        return "editorial"
    if re.search(r"/(?:product|pricing|solutions?|services?|features?|about|cases?|customers?)(?:/|$)", path):
        return "core"
    return "other"


def _url_family(url: str) -> str:
    parts = [part for part in urlparse(url).path.split("/") if part]
    if parts and LOCALE_SEGMENT.fullmatch(parts[0]):
        parts = parts[1:]
    return "/" + "/".join(parts).rstrip("/")


def select_candidates(urls: list[str], root: str, limit: int, market: str = "cn") -> list[str]:
    """Allocate crawl quota across page roles and locale variants."""
    ordered = rank(urls, root)
    caps = {
        "utility": 1,
        "support": max(2, int(limit * 0.25)),
        "editorial": max(2, int(limit * 0.30)),
    }
    family_cap = 2 if market == "both" else 1
    selected: list[str] = []
    role_counts: dict[str, int] = {}
    family_counts: dict[str, int] = {}
    deferred: list[str] = []
    for url in ordered:
        role = url_role(url)
        family = _url_family(url)
        if role_counts.get(role, 0) >= caps.get(role, limit):
            continue
        if family_counts.get(family, 0) >= family_cap:
            deferred.append(url)
            continue
        selected.append(url)
        role_counts[role] = role_counts.get(role, 0) + 1
        family_counts[family] = family_counts.get(family, 0) + 1
        if len(selected) >= limit:
            return selected
    for url in deferred:
        if len(selected) >= limit:
            break
        selected.append(url)
    return selected


def _robots_groups(text: str) -> list[tuple[list[str], list[tuple[str, str]]]]:
    groups: list[tuple[list[str], list[tuple[str, str]]]] = []
    agents: list[str] = []
    rules: list[tuple[str, str]] = []
    saw_rule = False
    for raw in (text or "").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = (part.strip() for part in line.split(":", 1))
        key = key.lower()
        if key == "user-agent":
            if saw_rule and agents:
                groups.append((agents, rules))
                agents, rules, saw_rule = [], [], False
            agents.append(value.lower())
        elif key in ("allow", "disallow") and agents:
            rules.append((key, value))
            saw_rule = True
    if agents:
        groups.append((agents, rules))
    return groups


def robots_disallows_root(text: str, bot: str) -> bool:
    """Evaluate root access using longest user-agent and path matches."""
    name = bot.lower()
    matches = []
    for agents, rules in _robots_groups(text):
        specificity = max((len(agent) for agent in agents if agent == "*" or agent in name), default=-1)
        if specificity >= 0:
            matches.append((specificity, rules))
    if not matches:
        return False
    best = max(item[0] for item in matches)
    decisions = []
    for specificity, rules in matches:
        if specificity != best:
            continue
        for kind, pattern in rules:
            if not pattern:
                continue
            regex = re.escape(pattern).replace(r"\*", ".*")
            if regex.endswith(r"\$"):
                regex = regex[:-2] + "$"
            if re.match(regex, "/"):
                decisions.append((len(pattern), kind == "allow"))
    if not decisions:
        return False
    longest = max(length for length, _allow in decisions)
    return not any(allow for length, allow in decisions if length == longest)


def analyze_page(url: str, res: dict) -> dict:
    soup = G.parse_html(res["html"])
    main = G.main_content(soup)
    text = re.sub(r"\n{3,}", "\n\n", main.get_text("\n", strip=True))
    blocks = G.jsonld(soup)

    h1 = [h.get_text(" ", strip=True) for h in main.find_all("h1")]
    h2 = [h.get_text(" ", strip=True) for h in main.find_all("h2")]
    h3 = [h.get_text(" ", strip=True) for h in main.find_all("h3")]
    paras = [p for p in main.find_all("p") if p.get_text(strip=True)]
    lis = main.find_all("li")
    tables = main.find_all("table")

    canonical = soup.find("link", rel=lambda v: v and "canonical" in v)
    desc = soup.find("meta", attrs={"name": "description"})
    robots_meta = soup.find("meta", attrs={"name": "robots"})

    # Count external links in main content as a coarse evidence-path signal.
    ext = 0
    for a in main.find_all("a", href=True):
        u = G.normalize_url(url, a["href"])
        if u and u.startswith("http") and not G.same_site(url, u):
            ext += 1

    return {
        "url": url,
        "final_url": res["final_url"],
        "status": res["status"],
        "error": res["error"],
        "title": (soup.title.get_text(" ", strip=True) if soup.title else ""),
        "meta_description": (desc.get("content", "") if desc else ""),
        "meta_robots": (robots_meta.get("content", "") if robots_meta else ""),
        "canonical": (canonical.get("href", "") if canonical else ""),
        "lang": (soup.html.get("lang", "") if soup.html else ""),
        "h1": h1,
        "h2": h2,
        "h3_count": len(h3),
        "para_count": len(paras),
        "li_count": len(lis),
        "table_count": len(tables),
        "img_count": len(main.find_all("img")),
        "external_links": ext,
        "jsonld_types": G.jsonld_types(blocks),
        "jsonld_raw": blocks,
        "word_count": G.word_count(text),
        "language": G.page_language(text, (soup.html.get("lang", "") if soup.html else "")),
        "cjk_ratio": G.cjk_ratio(text),
        "text": text[:20000],
        "fetched_at": G.now_iso(),
    }


def check_crawl_health(pages: list[dict]):
    """Terminate early if crawling fails entirely."""
    if not pages:
        G.die("Crawl failed: No candidate page was available.")
    ok = sum(1 for p in pages if p["status"] == 200)
    if ok == 0:
        G.die("Crawl failed: No page returned 200 OK. Check site accessibility or WAF.")
    if len(pages) >= 5 and ok / len(pages) < 0.2:
        G.die(f"Crawl failed: Only {ok}/{len(pages)} pages accessible (<20%). Check WAF/anti-scraping.")


def run(slug: str, max_pages: int | None = None, delay: float = 0.5) -> dict:
    cfg = G.load_config(slug)
    root = cfg["brand"]["site"].rstrip("/")
    limit = max_pages or cfg.get("pages", {}).get("max", 25)
    outdir = G.project_dir(slug) / "evidence"
    run_id = G.new_run_id("crawl")
    staging = outdir / ".staging" / run_id
    (staging / "html").mkdir(parents=True, exist_ok=True)

    G.info(f"Crawling {root} (limit: {limit} pages)")

    robots_txt = G.fetch_text(G.normalize_url(root, "/robots.txt"))
    llms_txt = G.fetch_text(G.normalize_url(root, "/llms.txt"))
    sitemap_urls = discover_sitemap(root)

    home = G.fetch(root)
    link_urls = discover_links(root, home["html"]) if home["html"] else []

    seeds = [u for u in cfg.get("pages", {}).get("seed", []) if u]
    candidates = select_candidates(seeds + sitemap_urls + link_urls, root, limit, cfg.get("market", "cn"))

    def crawl_one(i: int, u: str) -> dict:
        res = home if u.rstrip("/") == root else G.fetch(u)
        if res.get("final_url") and not G.same_site(root, res["final_url"]):
            res = {**res, "status": 0, "html": "",
                   "error": f"Redirect left the configured site: {res['final_url']}"}
        if res["status"] and res["html"]:
            (staging / "html" / f"{i:03d}.html").write_text(res["html"], "utf-8")
        page = analyze_page(u, res)
        page["snapshot"] = f"evidence/html/{run_id}/{i:03d}.html"
        page["crawl_run_id"] = run_id
        return page

    # Crawl serially per host with a polite delay; independent hosts may run concurrently.
    # Sitemaps and internal links may legitimately include docs or other subdomains.
    groups: "OrderedDict[str, list[tuple[int, str]]]" = OrderedDict()
    for i, u in enumerate(candidates, 1):
        groups.setdefault(urlparse(u).netloc.lower(), []).append((i, u))

    def crawl_group(items: list[tuple[int, str]]) -> dict[int, dict]:
        out = {}
        for i, u in items:
            page = crawl_one(i, u)
            out[i] = page
            G.info(f"  [{i}/{len(candidates)}] {page['status']} {u}")
            time.sleep(delay)
        return out

    try:
        pages_by_idx: dict[int, dict] = {}
        with ThreadPoolExecutor(max_workers=max(1, min(3, len(groups)))) as pool:
            for out in pool.map(crawl_group, groups.values()):
                pages_by_idx.update(out)
        pages = [pages_by_idx[i] for i in range(1, len(candidates) + 1)]
        check_crawl_health(pages)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    # Record whether robots policy blocks known answer-engine crawlers at the root.
    ai_bots = ["GPTBot", "OAI-SearchBot", "ClaudeBot", "PerplexityBot", "Bytespider",
               "Baiduspider", "Sogou web spider", "YisouSpider", "Google-Extended"]
    blocked = []
    for bot in ai_bots:
        if robots_disallows_root(robots_txt, bot):
            blocked.append(bot)

    site = {
        "slug": slug,
        "crawl_run_id": run_id,
        "cohort_id": G.stable_hash(candidates),
        "cohort_urls": candidates,
        "root": root,
        "crawled_at": G.now_iso(),
        "has_robots": bool(robots_txt),
        "has_llms_txt": bool(llms_txt),
        "has_sitemap": bool(sitemap_urls),
        "sitemap_url_count": len(sitemap_urls),
        "ai_bots_blocked": blocked,
        "pages_crawled": len(pages),
        "pages_ok": sum(1 for p in pages if p["status"] == 200),
    }
    final_snapshots = outdir / "html" / run_id
    final_snapshots.parent.mkdir(parents=True, exist_ok=True)
    if (staging / "html").exists():
        (staging / "html").replace(final_snapshots)
    shutil.rmtree(staging, ignore_errors=True)
    G.write_json(outdir / "site.json", site)
    G.write_jsonl(outdir / "pages.jsonl", pages)
    G.info(f"Complete: {site['pages_ok']}/{len(pages)} pages accessible → {outdir}")
    return site


if __name__ == "__main__":
    import sys

    run(sys.argv[1])
