"""GEO 建设蓝图：回答客户最关心的两个问题——**在哪些平台建、建什么内容**。

渠道优先级不是拍脑袋排的，是 CN-GEO 数据集 187,818 条去重引用实算出来的：
每个渠道带着全国引用量、平均引用位置、覆盖平台端数，以及"不做会怎样"。

产出 `blueprint.json`：
  channels   渠道矩阵：建什么形态的内容、多少量、什么节奏、谁做、现在覆盖了没
  contents   内容矩阵：每个目标问题需要什么类型的内容承接、现在有没有
  coverage   覆盖度：渠道覆盖率、问题承接率
  roadmap    30/60/90 分批
"""

from __future__ import annotations

import re
from pathlib import Path

import geolib as G

# ---------------------------------------------------------------- 渠道库
# national / position / platforms 均来自 references/cn-source-ranking.md 的实算值。
# position 越小 = 在 AI 答案里出现得越靠前。None 表示该数据集中样本不足。

# ---------------------------------------------------------------- 渠道库

CHANNELS_CN = [
    dict(id="official", name="Official Site", kind="Owned Asset", domains=[], national=2569, position=None,
         platforms=None, priority="P0",
         why="Brand official sites account for only 1.37% of citations—it is a **source of truth**, not the primary citation link. It ensures AI describes brand facts accurately.",
         forms=["Definition block & hero facts", "Product / Pricing / Case study pages", "FAQ (visible in static HTML)",
                "llms.txt", "JSON-LD structured data"],
         volume="8–15 core pages", cadence="Initial setup + quarterly maintenance", owner="Engineering + Content",
         effect="Aligns factual brand descriptions across frontier models"),
    dict(id="baike", name="Baidu Baike / Sogou Baike", kind="Encyclopedia", domains=["baike.baidu.com"],
         national=9396, position=None, platforms=9, priority="P0",
         why="Foundational entity disambiguation source; baidu.com provides 37.7% of Baidu AI citations.",
         forms=["Brand entity", "Product entry", "Disambiguation paragraph"],
         volume="1–2 entries", cadence="Initial setup + semi-annual updates", owner="Marketing",
         effect="Fixes brand entity categorization across multi-model knowledge bases"),
    dict(id="ranking", name="Ranking & Directory Platforms (Chinapp / Maigoo / PHB123)", kind="Directory",
         domains=["maigoo.com", "chinapp.com", "cnpp.cn", "phb123.com", "cnpp100.com"],
         national=17116, position=6.3, platforms=11, priority="P1",
         why="28 domains capture 9.1% of national citations with the highest placement ranks (#6.10–#6.36). AI frequently synthesizes listicles from directory databases.",
         forms=["Brand profile (long/medium/short)", "Category rankings inclusion", "Spec comparison tables"],
         volume="4–5 directory profiles", cadence="Initial submission + quarterly updates", owner="Marketing",
         effect="Highest leverage external authority channels"),
    dict(id="wechat", name="WeChat Official Accounts / Tencent News", kind="Media", domains=["qq.com", "mp.weixin.qq.com"],
         national=11017, position=None, platforms=11, priority="P1",
         why="qq.com spans 11 platforms and contributes 20.5% of Tencent Yuanbao citations.",
         forms=["In-depth articles (1,500+ words)", "Industry insights", "Case studies"],
         volume="2–4 articles/month", cadence="Bi-weekly", owner="Content",
         effect="Tencent Yuanbao and WeChat search ecosystem coverage"),
    dict(id="toutiao", name="Toutiao / Douyin Articles", kind="Media",
         domains=["toutiao.com", "iesdouyin.com"], national=20956, position=None, platforms=11,
         priority="P1",
         why="toutiao.com spans 11 platforms; iesdouyin.com represents 28.1% of Doubao App citations.",
         forms=["Visual articles", "Short videos with transcripts", "Industry primers"],
         volume="3–5 articles/month", cadence="Weekly", owner="Content",
         effect="Doubao and ByteDance ecosystem visibility"),
    dict(id="zhihu", name="Zhihu", kind="Q&A Community", domains=["zhihu.com", "zhuanlan.zhihu.com"],
         national=None, position=None, platforms=None, priority="P1",
         why="High-authority community discussion cited across multiple LLM search synthesis pipelines.",
         forms=["Direct answers to target queries", "Column articles"],
         volume="2–4 answers/month", cadence="Bi-weekly", owner="Content",
         effect="Captures comparison, recommendation, and selection intent"),
    dict(id="tech", name="CSDN / CNBlogs / Cloud Dev Communities", kind="Tech Community",
         domains=["csdn.net", "blog.csdn.net", "cnblogs.com", "cloud.tencent.com"],
         national=1388, position=7.53, platforms=11, priority="P1",
         why="High-weight authority sources for B2B tech products; cnblogs is Kimi's #2 citation domain (9.1%).",
         forms=["Technical walkthroughs", "Architecture comparisons", "Implementation guides"],
         volume="2–4 articles/month", cadence="Bi-weekly", owner="Content + Engineering",
         effect="High weight for DeepSeek, Kimi, and technical evaluators"),
    dict(id="quark", name="Quark / Shenma Search Indexing", kind="Search Index", domains=["sm.cn", "uc.cn"],
         national=6990, position=5.31, platforms=6, priority="P1",
         why="sm.cn has the highest placement rank (#5.31) and accounts for 19.2% of Qwen citations.",
         forms=["URL submission", "Sitemap ping"],
         volume="One-time submission", cadence="Initial + upon new URLs", owner="Engineering",
         effect="Directly boosts Qwen and Quark search citation probability"),
    dict(id="baijia", name="Baijiahao / Baidu Zhidao", kind="Platform Ecosystem", domains=["baijiahao.baidu.com"],
         national=9396, position=None, platforms=9, priority="P2",
         why="Baidu AI and Ernie heavily rely on native Baidu ecosystem content.",
         forms=["Baijiahao articles", "Zhidao Q&A entries"],
         volume="2–3 entries/month", cadence="Bi-weekly", owner="Content",
         effect="Baidu ecosystem gateway"),
    dict(id="media", name="Industry Media / Research Portals", kind="Media",
         domains=["36kr.com", "zol.com.cn", "askci.com", "iimedia.cn", "sohu.com", "163.com"],
         national=14733, position=6.8, platforms=11, priority="P2",
         why="General and vertical media account for 13.6% of national citations with high placement ranks.",
         forms=["Press releases", "Industry op-eds", "Research citations"],
         volume="1–2 articles/quarter", cadence="Periodic", owner="Marketing",
         effect="Domain authority endorsement"),
    dict(id="bilibili", name="Bilibili / Video Channels", kind="Video", domains=["bilibili.com"],
         national=None, position=None, platforms=11, priority="P2",
         why="Video transcripts are actively ingested by multimodal frontier search engines.",
         forms=["Product walkthroughs", "Tutorials with complete subtitles"],
         volume="1–2 videos/month", cadence="Monthly", owner="Content",
         effect="Multimodal text extraction via subtitles"),
]

CHANNELS_GLOBAL = [
    dict(id="official_en", name="English Official Site", kind="Owned Asset", domains=[], national=None, position=None,
         platforms=None, priority="P0",
         why="Global AI citations are dominated by English (82.90%–95.07%). Native English content is essential.",
         forms=["Native English product/pricing/comparison pages", "English FAQ", "llms.en.txt"],
         volume="8+ core pages", cadence="Initial setup + quarterly maintenance", owner="Content + Engineering",
         effect="Mandatory baseline for global frontier models"),
    dict(id="wikipedia", name="Wikipedia", kind="Encyclopedia", domains=["wikipedia.org"], national=None,
         position=None, platforms=None, priority="P1",
         why="Primary entity resolution foundation across ChatGPT, Claude, and Perplexity.",
         forms=["English entry with third-party citations"], volume="1 entry",
         cadence="Initial setup", owner="Marketing", effect="Long-term entity authority anchor"),
    dict(id="review", name="G2 / Capterra / Product Hunt", kind="Review Aggregator", domains=["g2.com", "capterra.com"],
         national=None, position=None, platforms=None, priority="P1",
         why="Frequently cited for 'best', 'vs', and 'alternatives' commercial queries.",
         forms=["Product profile", "Verified customer reviews", "Category comparisons"],
         volume="3–4 platforms", cadence="Initial setup + review collection", owner="Marketing",
         effect="Captures best / alternatives / comparison queries"),
    dict(id="reddit", name="Reddit / Hacker News", kind="Community", domains=["reddit.com"], national=None,
         position=None, platforms=None, priority="P1",
         why="Authentic peer discussions heavily prioritized by Perplexity and Google AI Overviews.",
         forms=["Authentic community participation", "AMA sessions"], volume="Ongoing participation", cadence="Weekly",
         owner="Product + Marketing",
         effect="Peer recommendations and high-intent citations"),
    dict(id="youtube", name="YouTube", kind="Video", domains=["youtube.com"], national=None,
         position=None, platforms=None, priority="P1",
         why="Leading citation domain across global AI models for product walkthroughs and comparisons.",
         forms=["Product demonstrations", "Tutorials", "Comparison reviews (with English subtitles)"],
         volume="1–2 videos/month", cadence="Monthly", owner="Content",
         effect="Top-tier global citation source"),
    dict(id="devsite", name="GitHub / Docs / dev.to", kind="Tech Community",
         domains=["github.com", "dev.to", "huggingface.co"], national=None, position=None,
         platforms=None, priority="P2",
         why="High-weight authority source for developer and technical tools.",
         forms=["Open source repositories", "Technical documentation", "Engineering blog"], volume="Ongoing",
         cadence="Ongoing", owner="Engineering", effect="Technical authority and developer mindshare"),
    dict(id="media_en", name="English Industry Media (TechCrunch / VentureBeat)", kind="Media",
         domains=["techcrunch.com", "venturebeat.com"], national=None, position=None,
         platforms=None, priority="P2",
         why="News and vertical portals account for 79.12%–87.52% of editorial citations in frontier models.",
         forms=["Press releases", "Guest columns"], volume="1–2 articles/quarter", cadence="Periodic",
         owner="Marketing", effect="High Domain Rating (DR 526–592) authoritative backlinks"),
    dict(id="linkedin", name="LinkedIn", kind="Social", domains=["linkedin.com"], national=None,
         position=None, platforms=None, priority="P2",
         why="B2B decision-maker network and corporate identity verification.",
         forms=["Company profile", "Founder long-form articles"], volume="2–4 posts/month", cadence="Weekly",
         owner="Marketing", effect="Supplementary B2B citation grounding"),
]


CHANNEL_FITS = {
    "official": ["recommendation", "comparison", "alternative", "pricing", "risk", "brand_verification", "scenario",
                 "推荐", "比较", "替代", "价格", "风险", "品牌验证", "场景"],
    "baike": ["brand_verification", "品牌验证"],
    "ranking": ["recommendation", "comparison", "alternative", "推荐", "比较", "替代"],
    "wechat": ["scenario", "recommendation", "risk", "场景", "推荐", "风险"],
    "toutiao": ["scenario", "recommendation", "场景", "推荐"],
    "zhihu": ["recommendation", "comparison", "alternative", "risk", "推荐", "比较", "替代", "风险"],
    "tech": ["scenario", "comparison", "risk", "场景", "比较", "风险"],
    "quark": [],
    "baijia": ["recommendation", "scenario", "brand_verification", "推荐", "场景", "品牌验证"],
    "media": ["recommendation", "brand_verification", "推荐", "品牌验证"],
    "bilibili": ["scenario", "场景"],
    "official_en": ["recommendation", "comparison", "alternative", "pricing", "risk", "brand_verification", "scenario",
                    "推荐", "比较", "替代", "价格", "风险", "品牌验证", "场景"],
    "wikipedia": ["brand_verification", "品牌验证"],
    "review": ["recommendation", "comparison", "alternative", "推荐", "比较", "替代"],
    "reddit": ["recommendation", "alternative", "risk", "推荐", "替代", "风险"],
    "youtube": ["scenario", "comparison", "场景", "比较"],
    "devsite": ["scenario", "risk", "场景", "风险"],
    "media_en": ["recommendation", "brand_verification", "推荐", "品牌验证"],
    "linkedin": ["brand_verification", "scenario", "品牌验证", "场景"],
}


# ---------------------------------------------------------------- 内容矩阵

GROUP_PLAN = {
    "recommendation": ("Listicle / Category Page", "Addresses 'best / top' queries — provide evaluation criteria first"),
    "comparison": ("Comparison Matrix Page", "6–10 standardized dimensions, acknowledge trade-offs for credibility"),
    "alternative": ("Alternative Guide Page", "Directly addresses migration considerations and key differentiators"),
    "pricing": ("Transparent Pricing Page", "Pricing clarity directly influences model confidence scores"),
    "risk": ("Security & Reliability Page", "Addresses data safety and compliance proactively"),
    "brand_verification": ("About Us & Knowledge Graph", "Primary factual source for entity recognition queries"),
    "scenario": ("How-To Tutorial Page", "Step-by-step instructions with numeric facts (+61.6% impact)"),
    "推荐": ("Listicle / Category Page", "Addresses 'best / top' queries — provide evaluation criteria first"),
    "比较": ("Comparison Matrix Page", "6–10 standardized dimensions, acknowledge trade-offs for credibility"),
    "替代": ("Alternative Guide Page", "Directly addresses migration considerations and key differentiators"),
    "价格": ("Transparent Pricing Page", "Pricing clarity directly influences model confidence scores"),
    "风险": ("Security & Reliability Page", "Addresses data safety and compliance proactively"),
    "品牌验证": ("About Us & Knowledge Graph", "Primary factual source for entity recognition queries"),
    "场景": ("How-To Tutorial Page", "Step-by-step instructions with numeric facts (+61.6% impact)"),
}


def _existing_content(slug: str) -> dict[str, list[str]]:
    pdir = G.project_dir(slug)
    hit: dict[str, list[str]] = {}
    for d, tag in ((pdir / "content", "ready"), (pdir / "assets" / "drafts", "draft"),
                   (pdir / "assets" / "outlines", "outline_only")):
        if not d.exists():
            continue
        for f in d.glob("*.md"):
            head = f.read_text("utf-8", "replace")[:600]
            for qid in re.findall(r"\bq\d{3}\b", head + f.stem):
                hit.setdefault(qid, []).append(tag)
    return hit


def build(slug: str) -> dict:
    cfg = G.load_config(slug)
    pdir = G.project_dir(slug)
    market = cfg.get("market", "global")

    files = sorted((pdir / "metrics").glob("*.json")) if (pdir / "metrics").exists() else []
    metrics = G.read_json(files[-1], {}) if files else {}
    cited: dict[str, set] = {"cn": set(), "global": set()}
    for m in (metrics.get("platforms") or {}).values():
        mk = m.get("market", "cn")
        for d in (m.get("top_cited_domains") or {}):
            cited[mk].add(d.lower())

    def covered(ch, mk):
        if ch["id"] in ("official", "official_en"):
            own = cfg["brand"]["site"].split("//")[-1].split("/")[0].removeprefix("www.")
            return any(d == own or d.endswith("." + own) for d in cited[mk])
        return any(any(c == dom or c.endswith("." + dom) for c in cited[mk])
                   for dom in ch["domains"])

    channels = []
    for mk, lst in (("cn", CHANNELS_CN), ("global", CHANNELS_GLOBAL)):
        if market not in (mk, "both"):
            continue
        for ch in lst:
            channels.append({**ch, "market": mk, "covered": covered(ch, mk),
                             "fits": CHANNEL_FITS.get(ch["id"], [])})

    # 内容矩阵
    hits = _existing_content(slug)
    contents = []
    for q in cfg.get("questions", []):
        form, note = GROUP_PLAN.get(q.get("group", ""), ("Definition / Guide Page", ""))
        st = hits.get(q.get("id"), [])
        status = "ready" if "ready" in st else "draft" if "draft" in st else "outline_only" if st else "gap"
        contents.append({"id": q.get("id"), "market": q.get("market", market),
                          "group": q.get("group", ""), "question": q.get("text", ""),
                          "form": form, "note": note, "status": status})

    def rate(items, ok):
        return round(sum(1 for x in items if ok(x)) / len(items), 3) if items else 0

    coverage = {
        "channel_total": len(channels),
        "channel_covered": sum(1 for c in channels if c["covered"]),
        "channel_rate": rate(channels, lambda c: c["covered"]),
        "p0p1_total": sum(1 for c in channels if c["priority"] in ("P0", "P1")),
        "p0p1_covered": sum(1 for c in channels if c["priority"] in ("P0", "P1") and c["covered"]),
        "content_total": len(contents),
        "content_done": sum(1 for c in contents if c["status"] == "ready"),
        "content_rate": rate(contents, lambda c: c["status"] == "ready"),
        "content_gap": sum(1 for c in contents if c["status"] == "gap"),
    }

    roadmap = [
        {"window": "0–30 Days", "focus": "Foundational Baseline",
         "items": [c["name"] for c in channels if c["priority"] == "P0"] +
                  ["Brand verification and pricing guide pages"]},
        {"window": "30–60 Days", "focus": "High-Leverage Channels & Content Matrix",
         "items": [c["name"] for c in channels if c["priority"] == "P1"][:6] +
                  ["1–2 articles each for recommendations, comparisons, and alternatives"]},
        {"window": "60–90 Days", "focus": "Scale & Closed-Loop Verification",
         "items": [c["name"] for c in channels if c["priority"] == "P2"][:5] +
                  ["Complete scenario tutorials and risk explanations", "Run 6 consecutive verification cycles"]},
    ]

    data = {"slug": slug, "generated_at": G.now_iso(), "market": market,
            "channels": channels, "contents": contents,
            "coverage": coverage, "roadmap": roadmap}
    G.write_json(pdir / "blueprint.json", data)
    G.info(f"Blueprint: {coverage['channel_covered']}/{coverage['channel_total']} channels covered, "
           f"{coverage['content_done']}/{coverage['content_total']} drafts completed → blueprint.json")
    return data
