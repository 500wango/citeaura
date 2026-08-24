"""把引擎产物归一到 CiteAura 的多市场产品范围。"""

import re
from contextlib import contextmanager
from copy import deepcopy
from urllib.parse import urlparse

from api.adapters import action_scope, brand_facts, brand_identity, competitor_scope
from api.adapters.crawl_evidence import contains_han, deduplicate_crawl_evidence, deduplicate_crawl_pages, normalize_evidence_url
from api.adapters.engine import geolib


DOMESTIC_PLATFORM_CODES = frozenset((
    "glm", "doubao", "kimi", "minimax", "nano_ai", "baidu", "doubao_app",
))
GLOBAL_PLATFORM_CODES = frozenset((
    "gemini", "openai", "claude", "grok", "perplexity", "deepseek",
    "chatgpt", "claude_web", "google_ai_overview", "google_ai_mode", "copilot",
    "gemini_web", "meta_ai", "you_com", "mistral_le_chat",
))
SUPPORTED_PLATFORM_CODES = DOMESTIC_PLATFORM_CODES | GLOBAL_PLATFORM_CODES

GROUP_NAMES = {
    "推荐": "recommendation",
    "比较": "comparison",
    "替代": "alternative",
    "价格": "pricing",
    "风险": "risk",
    "品牌验证": "brand_verification",
    "场景": "scenario",
}

GLOBAL_CHANNEL_NAMES = {
    "official_en": "English Official Site",
    "wikipedia": "Wikipedia",
    "review": "G2 / Capterra / Product Hunt",
    "reddit": "Reddit / Hacker News",
    "youtube": "YouTube",
    "linkedin": "LinkedIn",
}

# 渠道必须由项目画像选择，不能把某一个行业的渠道硬编码给所有客户。
CHANNEL_STRATEGIES = {
    "manufacturer": [
        ("official_en", "English Official Site", "P0"),
        ("b2b_marketplaces", "B2B Manufacturing Marketplaces", "P1"),
        ("trade_media", "Trade Media and Buyer Publications", "P1"),
        ("certification", "Certification and Compliance Registries", "P1"),
        ("linkedin", "LinkedIn", "P1"),
        ("youtube", "YouTube", "P1"),
        ("reddit", "Relevant Reddit and Hacker News Communities", "P2"),
        ("buyer_communities", "Buyer Communities and Industry Associations", "P2"),
        ("wikipedia", "Wikipedia (only if independently notable)", "P2"),
    ],
    "software": [
        ("official_en", "English Official Site", "P0"),
        ("docs", "Product Documentation and API Reference", "P0"),
        ("review", "Software Review Platforms", "P1"),
        ("developer_community", "Developer Communities and Technical Media", "P1"),
        ("reddit", "Relevant Reddit and Hacker News Communities", "P1"),
        ("youtube", "YouTube", "P1"),
        ("linkedin", "LinkedIn", "P1"),
        ("industry_media", "Software Industry Media", "P2"),
        ("wikipedia", "Wikipedia (only if independently notable)", "P2"),
    ],
    "service": [
        ("official_en", "English Official Site", "P0"),
        ("linkedin", "LinkedIn", "P1"),
        ("industry_directories", "Industry Directories and Professional Associations", "P1"),
        ("trade_media", "Trade Media and Expert Publications", "P1"),
        ("youtube", "YouTube", "P1"),
        ("reddit", "Relevant Reddit and Hacker News Communities", "P2"),
        ("customer_communities", "Customer Communities and Q&A Sources", "P2"),
        ("industry_media", "Industry Media", "P2"),
        ("wikipedia", "Wikipedia (only if independently notable)", "P2"),
    ],
    "commerce": [
        ("official_en", "English Official Site", "P0"),
        ("shopping_feeds", "Search and Shopping Product Feeds", "P0"),
        ("marketplaces", "Relevant Retail Marketplaces", "P1"),
        ("review_communities", "Product Review and Customer Communities", "P1"),
        ("reddit", "Relevant Reddit and Hacker News Communities", "P1"),
        ("youtube", "YouTube", "P1"),
        ("social_discovery", "Visual and Social Discovery Channels", "P1"),
        ("consumer_media", "Consumer and Category Media", "P2"),
    ],
    "publisher": [
        ("official_en", "Primary Publication and Content Archive", "P0"),
        ("news_feeds", "Search, News, and Publisher Feeds", "P0"),
        ("syndication", "Relevant Content Syndication Partners", "P1"),
        ("expert_sources", "Expert Profiles and Primary Source Networks", "P1"),
        ("youtube", "YouTube", "P1"),
        ("reddit", "Relevant Reddit and Hacker News Communities", "P2"),
        ("social_distribution", "Relevant Social Distribution Channels", "P2"),
        ("industry_media", "Peer Publications and Industry Media", "P2"),
    ],
    "financial_services": [
        ("official_en", "English Official Site", "P0"),
        ("regulatory_registries", "Applicable Financial Regulatory Registers", "P0"),
        ("app_stores", "Official Mobile App Stores", "P0"),
        ("finance_comparison", "Independent Financial Comparison and Review Sources", "P1"),
        ("finance_media", "Financial Services and Consumer Finance Media", "P1"),
        ("customer_communities", "Relevant Customer Communities", "P2"),
        ("linkedin", "LinkedIn", "P2"),
        ("youtube", "YouTube", "P2"),
        ("wikipedia", "Wikipedia (only if independently notable)", "P2"),
    ],
    "generic": [
        ("official_en", "English Official Site", "P0"),
        ("linkedin", "LinkedIn", "P1"),
        ("industry_directories", "Relevant Industry Directories", "P1"),
        ("industry_media", "Relevant Industry Media", "P1"),
        ("youtube", "YouTube", "P2"),
        ("reddit", "Relevant Reddit and Hacker News Communities", "P2"),
        ("customer_communities", "Relevant Customer Communities", "P2"),
        ("wikipedia", "Wikipedia (only if independently notable)", "P2"),
    ],
}

PROFILE_RULES = (
    ("financial_services", (
        "fintech", "financial service", "payments app", "payment app", "global payments",
        "multi-currency", "money transfer", "remittance", "digital wallet", "e-money",
        "electronic money", "neobank", "banking app", "foreign exchange",
    )),
    ("manufacturer", ("manufacturer", "manufacturing", "oem", "odm", "factory", "private label", "contract production", "制造", "工厂", "代工", "生产商")),
    ("software", ("software", "saas", "api platform", "developer tool", "cloud platform", "web application", "software platform", "软件", "开发者工具", "云平台")),
    ("service", ("consulting", "agency", "professional service", "law firm", "accounting", "advisory", "studio", "咨询", "代理服务", "专业服务", "事务所")),
    ("commerce", ("ecommerce", "e-commerce", "online store", "retail brand", "consumer products", "shop", "电商", "零售", "消费品牌", "网店")),
    ("publisher", ("publisher", "publication", "newsroom", "magazine", "editorial", "media company", "出版社", "新闻", "杂志", "媒体")),
)

CHANNEL_FIELD_DEFAULTS = {
    "official_en": {
        "kind": "Owned Asset", "forms": ["Native English core pages", "FAQ", "llms.txt", "JSON-LD"],
        "volume": "8+ core pages", "cadence": "Initial setup + quarterly maintenance",
        "owner": "Content + Engineering", "domains": [],
        "why": "The official site is the controlled source of truth for entity and product facts.",
        "effect": "Aligns factual descriptions across AI retrieval systems",
    },
    "linkedin": {
        "kind": "Professional Network", "forms": ["Company profile", "Expert posts", "Case studies"],
        "volume": "2–4 posts/month", "cadence": "Monthly", "owner": "Marketing",
        "domains": ["linkedin.com"], "why": "Provides attributable company and expert identity signals.",
        "effect": "Supports B2B entity verification",
    },
    "youtube": {
        "kind": "Video", "forms": ["Product demonstrations", "How-to videos", "Complete subtitles"],
        "volume": "1–2 videos/month", "cadence": "Monthly", "owner": "Content",
        "domains": ["youtube.com"], "why": "Video transcripts provide accessible product and process evidence.",
        "effect": "Adds multimodal and transcript-based discovery coverage",
    },
    "wikipedia": {
        "kind": "Encyclopedia", "forms": ["Independent-source review", "Entity entry if notable"],
        "volume": "Only when independently notable", "cadence": "Evidence review first", "owner": "Marketing",
        "domains": ["wikipedia.org"], "why": "Entity authority requires substantial independent reliable coverage.",
        "effect": "May strengthen entity disambiguation when eligibility is established",
    },
    "regulatory_registries": {
        "kind": "Regulatory Register", "forms": ["Authorized entity record", "Licence scope", "Current status"],
        "volume": "Every applicable operating entity and jurisdiction", "cadence": "At onboarding and every status change",
        "owner": "Legal + Compliance", "domains": [],
        "why": "Official registers provide the strongest evidence for authorization and legal-entity claims.",
        "effect": "Supports legitimacy, regulation, and safeguarding questions",
    },
    "app_stores": {
        "kind": "Product Distribution", "forms": ["Verified publisher listing", "Current app description", "Support and privacy links"],
        "volume": "Every supported mobile platform", "cadence": "At every material app release",
        "owner": "Product + Compliance", "domains": ["apps.apple.com", "play.google.com"],
        "why": "Publisher-controlled store listings establish product identity, availability, and current support paths.",
        "effect": "Supports app legitimacy and product-discovery queries",
    },
    "finance_comparison": {
        "kind": "Independent Comparison", "forms": ["Provider profile", "Fee comparison", "Eligibility and limitation review"],
        "volume": "2-4 relevant sources per target market", "cadence": "Quarterly review",
        "owner": "Marketing + Compliance", "domains": [],
        "why": "Independent comparisons add evidence for fees, alternatives, and suitability claims.",
        "effect": "Supports recommendation, pricing, and alternatives queries",
    },
    "finance_media": {
        "kind": "Industry Media", "forms": ["Company profile", "Product review", "Regulatory or funding coverage"],
        "volume": "Evidence-led coverage as available", "cadence": "Review quarterly",
        "owner": "Communications + Compliance", "domains": [],
        "why": "Independent financial reporting provides context that owned pages cannot establish alone.",
        "effect": "Supports entity verification and trust queries",
    },
    "review": {
        "kind": "Review Platform", "forms": ["Product profile", "Verified customer reviews", "Comparison pages"],
        "volume": "2–3 relevant platforms", "cadence": "Initial setup + quarterly updates", "owner": "Marketing",
        "domains": ["g2.com", "capterra.com", "producthunt.com"],
        "why": "Independent product reviews support commercial comparison queries.",
        "effect": "Captures recommendation and alternatives intent",
    },
    "reddit": {
        "kind": "Community", "forms": ["Authentic community participation", "Expert answers", "AMA sessions"],
        "volume": "Ongoing participation", "cadence": "Weekly", "owner": "Product + Marketing",
        "domains": ["reddit.com", "news.ycombinator.com"],
        "why": "Independent peer discussions are frequently retrieved for recommendations, alternatives, and risk queries.",
        "effect": "Adds peer evidence and high-intent community citations",
    },
    "b2b_marketplaces": {
        "kind": "B2B Marketplace", "forms": ["Supplier profile", "Product catalog", "Verified capabilities"],
        "volume": "2–4 relevant marketplaces", "cadence": "Initial setup + monthly updates", "owner": "Sales + Marketing",
        "domains": ["alibaba.com", "made-in-china.com", "globalsources.com"],
        "why": "Buyer marketplaces are discovery surfaces for sourcing and supplier queries.",
        "effect": "Improves qualified B2B supplier discovery",
    },
    "trade_media": {
        "kind": "Trade Media", "forms": ["Technical profile", "Buyer guide", "Verified case study"],
        "volume": "1–2 placements/quarter", "cadence": "Quarterly", "owner": "Marketing",
        "domains": [], "why": "Trade publications provide independent context for specialist buyers.",
        "effect": "Adds category authority and third-party evidence",
    },
    "certification": {
        "kind": "Compliance Registry", "forms": ["Certification record", "Test report", "Compliance statement"],
        "volume": "Every current certification", "cadence": "At issuance and renewal", "owner": "Quality + Compliance",
        "domains": [], "why": "Verifiable certifications reduce uncertainty in supplier evaluation.",
        "effect": "Supports trust, compliance, and risk queries",
    },
    "buyer_communities": {
        "kind": "Industry Community", "forms": ["Expert answers", "Association profile", "Buyer education"],
        "volume": "Ongoing participation", "cadence": "Monthly", "owner": "Sales + Marketing",
        "domains": [], "why": "Buyer communities expose practical selection criteria and use cases.",
        "effect": "Builds trusted peer-discovery signals",
    },
    "docs": {
        "kind": "Owned Documentation", "forms": ["Product documentation", "API reference", "Implementation guides"],
        "volume": "Complete core documentation", "cadence": "Release-based", "owner": "Engineering + Product",
        "domains": [], "why": "Documentation is the primary evidence source for software capabilities.",
        "effect": "Improves technical retrieval and implementation confidence",
    },
    "developer_community": {
        "kind": "Developer Community", "forms": ["Technical articles", "Open examples", "Q&A answers"],
        "volume": "2–4 technical pieces/month", "cadence": "Monthly", "owner": "Engineering",
        "domains": ["github.com", "dev.to", "stackoverflow.com"],
        "why": "Developer communities provide implementation evidence outside the product site.",
        "effect": "Supports technical recommendation and troubleshooting queries",
    },
    "industry_media": {
        "kind": "Industry Media", "forms": ["Expert article", "Press coverage", "Research citation"],
        "volume": "1–2 placements/quarter", "cadence": "Quarterly", "owner": "Marketing",
        "domains": [], "why": "Relevant industry media provides independent category context.",
        "effect": "Strengthens third-party authority signals",
    },
    "industry_directories": {
        "kind": "Industry Directory", "forms": ["Verified company profile", "Service listing", "Association record"],
        "volume": "3–5 relevant directories", "cadence": "Quarterly", "owner": "Marketing",
        "domains": [], "why": "Professional directories help buyers verify providers in the relevant category.",
        "effect": "Improves category and local/entity discovery",
    },
    "customer_communities": {
        "kind": "Customer Community", "forms": ["Expert answers", "Case discussion", "Community profile"],
        "volume": "Ongoing participation", "cadence": "Monthly", "owner": "Marketing",
        "domains": [], "why": "Customer communities surface practical experience and decision criteria.",
        "effect": "Supports trust and use-case discovery",
    },
    "shopping_feeds": {
        "kind": "Search and Shopping Feed", "forms": ["Product feed", "Merchant profile", "Structured product data"],
        "volume": "All active products", "cadence": "Daily feed sync", "owner": "Commerce + Engineering",
        "domains": [], "why": "Product feeds give search systems structured inventory and offer facts.",
        "effect": "Improves product discovery and availability retrieval",
    },
    "marketplaces": {
        "kind": "Retail Marketplace", "forms": ["Product listings", "Store profile", "Verified reviews"],
        "volume": "Priority marketplaces", "cadence": "Weekly catalog maintenance", "owner": "Commerce",
        "domains": [], "why": "Retail marketplaces capture product and buying-intent queries.",
        "effect": "Expands product discovery beyond the official site",
    },
    "review_communities": {
        "kind": "Review Community", "forms": ["Verified reviews", "Product comparisons", "Customer questions"],
        "volume": "Ongoing review collection", "cadence": "Monthly", "owner": "Customer Success + Marketing",
        "domains": [], "why": "Customer evidence improves confidence in product recommendations.",
        "effect": "Supports comparison and purchase-decision queries",
    },
    "social_discovery": {
        "kind": "Social Discovery", "forms": ["Product demonstrations", "Creator explainers", "Accessible captions"],
        "volume": "2–4 pieces/month", "cadence": "Monthly", "owner": "Marketing",
        "domains": [], "why": "Visual discovery channels expose products through demonstrations and use cases.",
        "effect": "Adds multimodal product discovery signals",
    },
    "consumer_media": {
        "kind": "Consumer Media", "forms": ["Category guide", "Independent review", "Expert comparison"],
        "volume": "1–2 placements/quarter", "cadence": "Quarterly", "owner": "PR + Marketing",
        "domains": [], "why": "Consumer publications provide independent category and product context.",
        "effect": "Supports broad recommendation and alternatives queries",
    },
    "news_feeds": {
        "kind": "News and Publisher Feed", "forms": ["News sitemap", "Publisher profile", "Structured article data"],
        "volume": "All current publications", "cadence": "Per publication", "owner": "Editorial + Engineering",
        "domains": [], "why": "Publisher feeds make current and archival content discoverable to retrieval systems.",
        "effect": "Improves timely source discovery",
    },
    "syndication": {
        "kind": "Content Syndication", "forms": ["Licensed republishing", "Partner feed", "Canonical article"],
        "volume": "Selected authoritative partners", "cadence": "Per partnership", "owner": "Editorial",
        "domains": [], "why": "Controlled syndication extends reach while preserving canonical ownership.",
        "effect": "Expands reliable content retrieval",
    },
    "expert_sources": {
        "kind": "Expert Source Network", "forms": ["Author profile", "Expert commentary", "Primary source links"],
        "volume": "Core contributors", "cadence": "Quarterly review", "owner": "Editorial",
        "domains": [], "why": "Clear authorship and primary sources improve editorial trust signals.",
        "effect": "Strengthens expert and source attribution",
    },
    "social_distribution": {
        "kind": "Social Distribution", "forms": ["Article excerpts", "Author updates", "Discussion prompts"],
        "volume": "2–4 posts/month", "cadence": "Weekly", "owner": "Editorial + Marketing",
        "domains": [], "why": "Relevant distribution channels help readers discover authoritative publications.",
        "effect": "Extends content discovery without replacing primary sources",
    },
}

TASK_COPY = {
    "补 sitemap.xml 并提交各搜索引擎": {
        "title": "Add sitemap.xml and submit it to international search engines",
        "why": "A missing sitemap reduces discovery speed and coverage.",
        "action": "Generate sitemap.xml, reference it in robots.txt, and submit it to Google and Bing.",
    },
    "上线 /llms.txt 官方事实索引": {
        "why": "A curated official facts index gives AI systems a stable source of truth.",
    },
    "百科词条（实体消歧地基）": {
        "title": "Assess independent-source notability before encyclopedia work",
        "why": "An encyclopedia entry is appropriate only when substantial independent reliable coverage already establishes notability.",
        "action": "Review independent sources before drafting. If the threshold is not met, strengthen the owned facts library and verified third-party profiles instead.",
        "acceptance": "Record at least three substantial independent reliable sources, or document the non-encyclopedia alternative and its evidence.",
    },
}


def _profile_page_evidence(pages, keywords):
    evidence = []
    for page in pages if isinstance(pages, list) else []:
        if not isinstance(page, dict) or page.get("status") != 200:
            continue
        surface = " ".join([
            str(page.get("title") or ""),
            str(page.get("meta_description") or ""),
            *(str(value) for value in page.get("h1") or []),
            *(str(value) for value in page.get("h2") or []),
            str(page.get("text") or ""),
        ])
        lowered = surface.lower()
        hits = [keyword for keyword in keywords if keyword in lowered]
        if hits:
            first = lowered.find(hits[0])
            evidence.append({
                "source": "website",
                "url": str(page.get("url") or ""),
                "signals": list(dict.fromkeys(hits))[:8],
                "excerpt": " ".join(surface[max(0, first - 80):first + len(hits[0]) + 120].split()),
            })
    return evidence[:8]


def infer_business_profile(config, pages=None):
    """从项目画像推断渠道策略；模型结论必须与网站证据分开记录。"""
    brand = config.get("brand") if isinstance(config, dict) and isinstance(config.get("brand"), dict) else {}
    declared = config.get("business_profile") if isinstance(config, dict) else None
    if isinstance(declared, dict) and declared.get("confirmed") is True:
        profile = str(declared.get("id") or "")
        if profile in CHANNEL_STRATEGIES:
            return {
                **declared,
                "id": profile,
                "label": declared.get("label") or profile.replace("_", " ").title(),
                "confidence": "high",
                "confirmed": True,
                "review_required": False,
                "evidence": list(declared.get("evidence") or ["Business profile confirmed in project configuration"]),
            }
    industry = str(brand.get("industry") or "").lower()
    fields = [brand.get("target_users"), brand.get("business_goal")]
    fields += brand.get("products") if isinstance(brand.get("products"), list) else []
    supporting = " ".join(str(value or "").lower() for value in fields if value)
    matches = []
    for profile, keywords in PROFILE_RULES:
        industry_hits = [keyword for keyword in keywords if keyword in industry]
        support_hits = [keyword for keyword in keywords if keyword in supporting]
        page_evidence = _profile_page_evidence(pages, keywords)
        page_hits = list(dict.fromkeys(
            signal for item in page_evidence for signal in item.get("signals") or []
        ))
        hits = list(dict.fromkeys(industry_hits + support_hits + page_hits))
        if hits:
            score = len(industry_hits) * 3 + len(support_hits) + min(len(page_hits), 3) * 2
            matches.append((score, profile, industry_hits, support_hits, page_evidence, hits))
    if matches:
        matches.sort(key=lambda item: (-item[0], item[1]))
        candidates = [
            {
                "id": item[1],
                "label": item[1].replace("_", " ").title(),
                "score": item[0],
                "signals": item[5],
                "evidence": item[4],
            }
            for item in matches
        ]
        eligible = [
            item for item in matches
            if item[2] or item[3] or (
                len({row.get("url") for row in item[4] if row.get("url")}) >= 2
                and len(item[5]) >= 2
            )
        ]
        if not eligible:
            return {
                "id": "generic",
                "label": "General business",
                "industry": str(brand.get("industry") or ""),
                "confidence": "low",
                "confirmed": False,
                "review_required": True,
                "evidence": [],
                "evidence_details": [],
                "candidates": candidates,
            }
        _score, profile, industry_hits, support_hits, page_evidence, hits = eligible[0]
        evidence = []
        if industry_hits:
            evidence.append(f"Model or project industry metadata matched the {profile} profile")
        if support_hits:
            evidence.append(f"brand products, audience, or business goal matched the {profile} profile")
        if page_evidence:
            evidence.append(f"Crawled website content matched the {profile} profile")
        confidence = "high" if industry_hits and page_evidence else "medium"
        return {
            "id": profile,
            "label": profile.replace("_", " ").title(),
            "industry": str(brand.get("industry") or ""),
            "confidence": confidence,
            "confirmed": False,
            "review_required": True,
            "evidence": evidence,
            "evidence_details": page_evidence,
            "candidates": candidates,
        }
    return {
        "id": "generic",
        "label": "General business",
        "industry": str(brand.get("industry") or ""),
        "confidence": "low",
        "confirmed": False,
        "review_required": True,
        "evidence": [],
        "evidence_details": [],
        "candidates": [],
    }


def _domain_host(value):
    value = str(value or "").strip().lower()
    if not value:
        return ""
    parsed = urlparse(value if "://" in value else f"//{value}")
    return (parsed.hostname or "").removeprefix("www.").rstrip(".")


def _same_domain(left, right):
    left = _domain_host(left)
    right = _domain_host(right)
    return bool(left and right and geolib.same_site(f"https://{left}", f"https://{right}"))


def _channel_coverage(channel_id, defaults, previous, brand_domains, observed_domains, own_domain):
    targets = [own_domain] if channel_id == "official_en" else defaults.get("domains", [])
    targets = [host for host in (_domain_host(value) for value in targets) if host]
    if not targets:
        return "manual", []
    if brand_domains is None and observed_domains is None:
        previous_status = previous.get("coverage_status")
        if previous_status in ("brand_cited", "covered", "observed_source", "gap"):
            return previous_status, deepcopy(previous.get("coverage_evidence") or [])
        if isinstance(previous.get("covered"), bool):
            return ("covered" if previous["covered"] else "gap"), []
        return "gap", []
    matches = sorted({
        cited
        for cited in (_domain_host(value) for value in (brand_domains or ()))
        if cited and any(_same_domain(cited, target) for target in targets)
    })
    if matches:
        return "brand_cited", matches
    observed = sorted({
        cited
        for cited in (_domain_host(value) for value in (observed_domains or ()))
        if cited and any(_same_domain(cited, target) for target in targets)
    })
    return ("observed_source" if observed else "gap"), observed


def channel_coverage_status(channel):
    status = channel.get("coverage_status")
    if status in ("brand_cited", "covered", "observed_source", "gap", "manual"):
        return status
    return "covered" if channel.get("covered") else "gap"


def summarize_channel_coverage(channels):
    measurable = [channel for channel in channels if channel_coverage_status(channel) != "manual"]
    p0p1 = [channel for channel in measurable if channel.get("priority") in ("P0", "P1")]
    manual = [channel for channel in channels if channel_coverage_status(channel) == "manual"]
    return {
        "channel_all_total": len(channels),
        "channel_total": len(measurable),
        "channel_covered": sum(channel_coverage_status(channel) in ("brand_cited", "covered") for channel in measurable),
        "channel_observed": sum(channel_coverage_status(channel) == "observed_source" for channel in measurable),
        "channel_manual": len(manual),
        "p0p1_total": len(p0p1),
        "p0p1_covered": sum(channel_coverage_status(channel) in ("brand_cited", "covered") for channel in p0p1),
        "p0p1_manual": sum(channel.get("priority") in ("P0", "P1") for channel in manual),
    }


def _latest_channel_evidence(project_slug):
    directory = geolib.project_dir(project_slug) / "metrics"
    files = sorted(directory.glob("*.json")) if directory.is_dir() else []
    if not files:
        return None
    metrics = geolib.read_json(files[-1], {}) or {}
    cited = set()
    brand_cited = set()
    citation_domains_available = False
    for item in (metrics.get("platforms") or {}).values():
        if not isinstance(item, dict) or item.get("market") not in ("cn", "global", "both", None):
            continue
        if "top_cited_domains" not in item:
            continue
        citation_domains_available = True
        cited.update(
            host for host in (_domain_host(value) for value in (item.get("top_cited_domains") or {})) if host
        )
        brand_cited.update(
            host for host in (_domain_host(value) for value in (item.get("top_brand_cited_domains") or {})) if host
        )
    return {"observed": cited, "brand": brand_cited} if citation_domains_available else None


def _profile_channels(profile, existing, *, cited_domains=None, observed_domains=None, own_domain=""):
    existing_by_id = {
        str(channel.get("id")): channel
        for channel in existing
        if isinstance(channel, dict) and channel.get("market") in ("cn", "global", "both", None)
    }
    rows = []
    for channel_id, name, priority in CHANNEL_STRATEGIES[profile["id"]]:
        previous = existing_by_id.get(channel_id, {})
        defaults = deepcopy(CHANNEL_FIELD_DEFAULTS.get(channel_id, {
            "kind": "Configured Channel", "forms": ["Relevant authoritative profile", "Evidence-backed content"],
            "volume": "As appropriate for the project", "cadence": "Review quarterly", "owner": "Marketing",
            "domains": [], "why": "Use a relevant authoritative source for this project profile.",
            "effect": "Supports project-specific discovery and verification",
        }))
        coverage_status, coverage_evidence = _channel_coverage(
            channel_id, defaults, previous, cited_domains, observed_domains, own_domain,
        )
        rows.append({
            **defaults,
            "id": channel_id,
            "name": name,
            "priority": priority,
            "market": "both",
            "covered": coverage_status in ("brand_cited", "covered"),
            "coverage_status": coverage_status,
            "coverage_evidence": coverage_evidence if coverage_status in ("brand_cited", "covered") else [],
            "observed_source_evidence": coverage_evidence if coverage_status == "observed_source" else [],
            "strategy_profile": profile["id"],
        })
    return rows


def is_global_sample(row, config=None):
    """兼容旧调用点，按项目市场筛选当前支持的样本。"""
    if not isinstance(row, dict) or not row.get("platform"):
        return False
    row_market = row.get("market")
    if row_market not in ("cn", "global", "both", None):
        return False
    project_market = (config or {}).get("market") if isinstance(config, dict) else None
    if project_market == "cn":
        return row_market in ("cn", "both", None)
    if project_market == "global":
        return row_market in ("global", "both", None)
    return True


def normalize_questions(questions, *, strict=False):
    """保留中文、全球和双市场问题，确保每条问题都有合法市场。"""
    if not isinstance(questions, list):
        if strict:
            raise ValueError("questions must be an array")
        return []
    normalized = []
    seen_ids = set()
    for item in questions:
        if not isinstance(item, dict):
            if strict:
                raise ValueError("each question must be an object")
            continue
        text = str(item.get("text") or "").strip()
        market = item.get("market")
        if not text:
            if strict:
                raise ValueError("question text is required")
            continue
        if market not in ("cn", "global", "both", None):
            if strict:
                raise ValueError("question market must be cn, global, or both")
            continue
        market = market or "both"
        question_id = str(item.get("id") or "").strip().lower()
        if strict and (not re.fullmatch(r"q\d{3,6}", question_id) or question_id in seen_ids):
            raise ValueError("question id must be a unique q followed by 3-6 digits")
        if question_id:
            seen_ids.add(question_id)
        normalized.append({
            **item,
            "text": text,
            "market": market,
            "group": GROUP_NAMES.get(item.get("group"), item.get("group") or "recommendation"),
        })
    return geolib.normalize_question_ids(normalized)


def _normalize_competitors(competitors):
    normalized = []
    for item in competitors if isinstance(competitors, list) else []:
        if not isinstance(item, dict):
            continue
        if item.get("market") not in ("cn", "global", "both", None):
            continue
        normalized.append({**item, "market": item.get("market") or "both"})
    return normalized


def _normalize_platforms(platforms):
    normalized = []
    for code in platforms if isinstance(platforms, list) else []:
        code = str(code or "").strip()
        if not code:
            continue
        if code in SUPPORTED_PLATFORM_CODES or code.startswith("custom_"):
            if code not in normalized:
                normalized.append(code)
    return normalized


def normalize_config_data(config):
    current = deepcopy(config) if isinstance(config, dict) else {}
    current["market"] = current.get("market") if current.get("market") in ("cn", "global", "both") else "both"
    current["questions"] = normalize_questions(current.get("questions"))
    current["competitors"] = _normalize_competitors(current.get("competitors"))
    current["platforms"] = _normalize_platforms(current.get("platforms"))
    current = competitor_scope.normalize_config(current)
    return brand_identity.normalize_config_identity(current)


def normalize_config(project_slug):
    with geolib.project_lock(project_slug):
        current = geolib.load_config(project_slug)
        normalized = normalize_config_data(current)
        if normalized != current:
            geolib.save_config(project_slug, normalized)
        return normalized


def _rate(items, predicate):
    return round(sum(1 for item in items if predicate(item)) / len(items), 3) if items else 0


def normalize_blueprint_data(blueprint, *, profile=None, cited_domains=None, observed_domains=None, own_domain=""):
    current = deepcopy(blueprint) if isinstance(blueprint, dict) else {}
    existing_channels = [
        {
            **channel,
            "name": GLOBAL_CHANNEL_NAMES.get(channel.get("id"), channel.get("name")),
            "market": channel.get("market") or "both",
        }
        for channel in current.get("channels", [])
        if isinstance(channel, dict) and channel.get("market") in ("cn", "global", "both", None)
    ]
    profile = profile if isinstance(profile, dict) and profile.get("id") in CHANNEL_STRATEGIES else None
    channels = _profile_channels(
        profile, existing_channels, cited_domains=cited_domains,
        observed_domains=observed_domains, own_domain=own_domain,
    ) if profile else existing_channels
    contents = normalize_questions([
        {
            **content,
            "text": content.get("question"),
        }
        for content in current.get("contents", [])
        if isinstance(content, dict)
    ])
    contents = [
        {key: value for key, value in content.items() if key != "text"}
        | {"question": content.get("text", "")}
        for content in contents
    ]
    coverage = {
        **summarize_channel_coverage(channels),
        "channel_rate": _rate(
            [channel for channel in channels if channel_coverage_status(channel) != "manual"],
            lambda channel: channel_coverage_status(channel) in ("brand_cited", "covered"),
        ),
        "content_total": len(contents),
        "content_done": sum(content.get("status") in ("ready", "done") for content in contents),
        "content_rate": _rate(contents, lambda content: content.get("status") in ("ready", "done")),
        "content_gap": sum(content.get("status") == "gap" for content in contents),
    }
    roadmap = [
        {
            "window": "0–30 Days",
            "focus": "Foundational Baseline",
            "items": [channel.get("name") for channel in channels if channel.get("priority") == "P0"]
            + ["Brand verification and pricing guide pages"],
        },
        {
            "window": "30–60 Days",
            "focus": "High-Leverage Channels & Content Matrix",
            "items": [channel.get("name") for channel in channels if channel.get("priority") == "P1"][:6]
            + ["1–2 articles each for recommendations, comparisons, and alternatives"],
        },
        {
            "window": "60–90 Days",
            "focus": "Scale & Closed-Loop Verification",
            "items": [channel.get("name") for channel in channels if channel.get("priority") == "P2"][:5]
            + ["Complete scenario tutorials and risk explanations", "Run 6 consecutive verification cycles"],
        },
    ]
    return {
        **current,
        "market": current.get("market") if current.get("market") in ("cn", "global", "both") else "both",
        **({"channel_strategy": profile} if profile else {}),
        "channels": channels,
        "contents": contents,
        "coverage": coverage,
        "roadmap": roadmap,
    }


def normalize_blueprint(project_slug):
    path = geolib.project_dir(project_slug) / "blueprint.json"
    if not path.is_file():
        return None
    with geolib.project_lock(project_slug):
        current = geolib.read_json(path, {}) or {}
        config = geolib.load_config(project_slug)
        pages = geolib.read_jsonl(geolib.project_dir(project_slug) / "evidence" / "pages.jsonl")
        profile = infer_business_profile(config, pages=pages)
        channel_evidence = _latest_channel_evidence(project_slug)
        normalized = normalize_blueprint_data(
            current,
            profile=profile,
            cited_domains=(channel_evidence or {}).get("brand") if channel_evidence is not None else None,
            observed_domains=(channel_evidence or {}).get("observed") if channel_evidence is not None else None,
            own_domain=_domain_host((config.get("brand") or {}).get("site")),
        )
        if normalized != current:
            geolib.write_json(path, normalized)
        return normalized


def _task_summary(tasks):
    def count(**values):
        return sum(all(task.get(key) == value for key, value in values.items()) for task in tasks)

    packages = []
    for task in tasks:
        package = task.get("package")
        if package and package not in packages:
            packages.append(package)
    return {
        "total": len(tasks),
        "by_priority": {priority: count(priority=priority) for priority in ("P0", "P1", "P2")},
        "by_status": {state: count(status=state) for state in ("todo", "doing", "done", "blocked", "wontfix")},
        "by_package": {package: count(package=package) for package in packages},
        "by_market": {
            market: sum(task.get("market") == market for task in tasks)
            for market in ("cn", "global", "both")
        },
        "auto_verifiable": sum(
            isinstance(task.get("acceptance"), dict) and task["acceptance"].get("type") == "auto"
            for task in tasks
        ),
    }


def normalize_tasks_data(data):
    current = deepcopy(data) if isinstance(data, dict) else {}
    normalized = []
    for task in current.get("tasks", []):
        if not isinstance(task, dict):
            continue
        task = {
            **task,
            "market": task.get("market") if task.get("market") in ("cn", "global", "both") else "both",
        }
        replacement = TASK_COPY.get(task.get("title"))
        if replacement:
            task.update({key: value for key, value in replacement.items() if key != "acceptance"})
            if replacement.get("acceptance"):
                task["acceptance"] = {
                    **(task.get("acceptance") if isinstance(task.get("acceptance"), dict) else {}),
                    "desc": replacement["acceptance"],
                }
        normalized.append(task)
    return {
        **current,
        "market": current.get("market") if current.get("market") in ("cn", "global", "both") else "both",
        "tasks": normalized,
        "summary": _task_summary(normalized),
    }


def normalize_tasks(project_slug):
    path = geolib.project_dir(project_slug) / "tasks.json"
    if not path.is_file():
        return None
    with geolib.project_lock(project_slug):
        current = geolib.read_json(path, {}) or {}
        normalized = normalize_tasks_data(current)
        from api.adapters import audit_presentation, measurement

        project_directory = geolib.project_dir(project_slug)
        audit = audit_presentation.present_audit_data(
            geolib.read_json(project_directory / "audit.json", {}) or {},
            geolib.read_jsonl(project_directory / "evidence" / "pages.jsonl"),
            geolib.read_json(project_directory / "evidence" / "site.json", {}) or {},
        )
        normalized = action_scope.scope_task_data(
            normalized,
            audit,
            measurement.sampling_quality(project_slug),
        )
        if normalized != current:
            geolib.write_json(path, normalized)
        return normalized


def normalize_audit(project_slug):
    path = geolib.project_dir(project_slug) / "audit.json"
    if not path.is_file():
        return None
    with geolib.project_lock(project_slug):
        deduplication = deduplicate_crawl_evidence(project_slug)
        current = geolib.read_json(path, {}) or {}
        evidence_pages = deduplication.get("pages") or []
        audit_urls = {
            str(page.get("url") or "")
            for page in current.get("pages") or []
            if isinstance(page, dict)
        }
        duplicate_urls = {
            str(url)
            for page in evidence_pages
            for url in (page.get("duplicate_urls") or [])
        }
        if deduplication.get("removed") or audit_urls & duplicate_urls:
            import audit as engine_audit

            current = engine_audit.run(project_slug)
        config = geolib.load_config(project_slug)
        market = config.get("market") if config.get("market") in ("cn", "global", "both") else "both"
        if current.get("market") != market:
            current["market"] = market
            geolib.write_json(path, current)
        return current


def _sample_summary(rows):
    per_platform = {}
    successful = 0
    for row in rows:
        code = row.get("platform") or "unknown"
        item = per_platform.setdefault(code, {"total": 0, "successful": 0, "failed": 0})
        item["total"] += 1
        if row.get("ok"):
            successful += 1
            item["successful"] += 1
        else:
            item["failed"] += 1
    return {
        "total": len(rows),
        "successful": successful,
        "failed": len(rows) - successful,
        "per_platform": per_platform,
    }


def normalize_metrics(project_slug, question_count=None, config=None):
    directory = geolib.project_dir(project_slug) / "metrics"
    if not directory.is_dir():
        return []
    config = brand_identity.normalize_config_identity(config or geolib.load_config(project_slug))
    current_question_version = brand_identity.question_set_version(config)["version"]
    metrics_paths = sorted(directory.glob("*.json"))
    latest_path = metrics_paths[-1] if metrics_paths else None
    normalized_files = []
    with geolib.project_lock(project_slug):
        for path in metrics_paths:
            current = geolib.read_json(path, {}) or {}
            platforms = {
                code: {**item, "market": item.get("market") or "both"}
                for code, item in (current.get("platforms") or {}).items()
                if isinstance(item, dict)
                and item.get("market") in ("cn", "global", "both", None)
            }
            normalized = {**current, "platforms": platforms}
            artifact = str(current.get("run_id") or current.get("date") or "")
            sample_path = geolib.project_dir(project_slug) / "samples" / f"{artifact}.jsonl"
            if sample_path.is_file():
                import sample as engine_sample

                rows = [
                    row for row in geolib.read_jsonl(sample_path)
                    if is_global_sample(row, config) and brand_identity.is_current_sample(row, config)
                ]
                rows = engine_sample.dedup_rows(rows)
                successful = [row for row in rows if row.get("ok")]
                if rows or path == latest_path:
                    normalized["platforms"] = engine_sample.aggregate(successful, config) if successful else {}
                    normalized["sample_count"] = len(successful)
                    normalized["sample_summary"] = _sample_summary(rows)
                    normalized["question_set_version"] = current_question_version
                    normalized["cohort_status"] = "current" if rows else "no_current_samples"
            elif isinstance(current.get("sample_summary"), dict):
                successful = sum(int(item.get("samples") or 0) for item in platforms.values())
                normalized["sample_count"] = successful
                normalized["sample_summary"] = {
                    "total": successful,
                    "successful": successful,
                    "failed": 0,
                    "per_platform": {
                        code: {
                            "total": int(item.get("samples") or 0),
                            "successful": int(item.get("samples") or 0),
                            "failed": 0,
                        }
                        for code, item in platforms.items()
                    },
                }
            if question_count is not None:
                normalized["question_count"] = question_count
            provenance = normalized.get("provenance")
            if isinstance(provenance, dict):
                provenance = deepcopy(provenance)
                provenance["requested_platforms"] = list(provenance.get("requested_platforms", []))
                provenance["platforms"] = list(provenance.get("platforms", []))
                if isinstance(provenance.get("question_set"), dict) and question_count is not None:
                    provenance["question_set"] = {
                        **provenance["question_set"],
                        "version": normalized.get("question_set_version", provenance["question_set"].get("version")),
                        "count": question_count,
                    }
                normalized["provenance"] = provenance
            if normalized != current:
                geolib.write_json(path, normalized)
            normalized_files.append(normalized)
    return normalized_files


def normalize_project(project_slug):
    if not (geolib.project_dir(project_slug) / "geo.json").is_file():
        return {}
    config = normalize_config(project_slug)
    brand_identity.reanalyze_samples(project_slug, config)
    normalize_audit(project_slug)
    normalize_metrics(project_slug, question_count=len(config.get("questions") or []), config=config)
    normalize_tasks(project_slug)
    normalize_blueprint(project_slug)
    brand_facts.ensure_english_facts(project_slug, config=config)
    return config


@contextmanager
def normalize_generated_outputs(project_slug):
    """确保引擎生成的问题、工单、蓝图和资产在下游步骤前立即归一。"""
    import blueprint as engine_blueprint
    import bootstrap as engine_bootstrap
    import audit as engine_audit
    import crawl as engine_crawl
    import generate as engine_generate
    import tasks as engine_tasks

    original_bootstrap = engine_bootstrap.run
    original_brand_facts = engine_bootstrap.brand_facts
    original_competitors = engine_bootstrap.competitors
    original_render_facts = engine_bootstrap.render_facts
    original_audit = engine_audit.run
    original_crawl = engine_crawl.run
    original_generate = engine_generate.run
    original_parse_facts = engine_generate.parse_facts
    original_tasks = engine_tasks.build
    original_blueprint = engine_blueprint.build

    def crawl_run(slug, *args, **kwargs):
        result = original_crawl(slug, *args, **kwargs)
        if slug != project_slug:
            return result
        normalized = deduplicate_crawl_evidence(project_slug)
        if isinstance(result, dict) and normalized.get("site"):
            return {**result, **{
                key: value for key, value in normalized["site"].items()
                if key in ("pages_crawled", "pages_ok", "pages_crawled_raw", "duplicate_pages_removed")
            }}
        return result

    def audit_run(slug, *args, **kwargs):
        if slug == project_slug:
            deduplicate_crawl_evidence(project_slug)
        result = original_audit(slug, *args, **kwargs)
        if slug != project_slug or not isinstance(result, dict):
            return result
        config = geolib.load_config(project_slug)
        normalized = {
            **result,
            "market": config.get("market") if config.get("market") in ("cn", "global", "both") else "both",
        }
        if normalized != result:
            geolib.write_json(geolib.project_dir(project_slug) / "audit.json", normalized)
        return normalized

    def bootstrap_run(slug, *args, **kwargs):
        result = original_bootstrap(slug, *args, **kwargs)
        if slug == project_slug:
            brand_facts.ensure_english_facts(project_slug, prefer_ai_candidate=True)
            return normalize_config(project_slug)
        return result

    def extract_brand_facts(slug, digest):
        if slug != project_slug:
            return original_brand_facts(slug, digest)
        return brand_facts.extract_brand_facts(engine_bootstrap._ask_json, slug, digest)

    def discover_competitors(brand, market):
        configured = geolib.load_config(project_slug)
        configured_brand = configured.get("brand") if isinstance(configured.get("brand"), dict) else {}
        profile = {**configured_brand, **(brand if isinstance(brand, dict) else {})}
        return competitor_scope.discover_competitors(
            engine_bootstrap._ask_json,
            profile,
            configured.get("market") if configured.get("market") in ("cn", "global", "both") else "both",
        )

    def render_brand_facts(slug, data):
        return brand_facts.render_facts(slug, data) if slug == project_slug else original_render_facts(slug, data)

    def parse_brand_facts(slug):
        return brand_facts.parse_facts(slug) if slug == project_slug else original_parse_facts(slug)

    def generate_run(slug, *args, **kwargs):
        if slug != project_slug:
            return original_generate(slug, *args, **kwargs)
        from api.adapters import generated_assets

        normalize_config(project_slug)
        with generated_assets.preserve_manual_asset_edits(project_slug):
            result = original_generate(slug, *args, **kwargs)
        generated_assets.normalize_project_assets(project_slug, config=normalize_config(project_slug))
        return result

    def tasks_build(slug, *args, **kwargs):
        result = original_tasks(slug, *args, **kwargs)
        return normalize_tasks(project_slug) if slug == project_slug else result

    def blueprint_build(slug, *args, **kwargs):
        result = original_blueprint(slug, *args, **kwargs)
        return normalize_blueprint(project_slug) if slug == project_slug else result

    engine_bootstrap.run = bootstrap_run
    engine_bootstrap.brand_facts = extract_brand_facts
    engine_bootstrap.competitors = discover_competitors
    engine_bootstrap.render_facts = render_brand_facts
    engine_audit.run = audit_run
    engine_crawl.run = crawl_run
    engine_generate.run = generate_run
    engine_generate.parse_facts = parse_brand_facts
    engine_tasks.build = tasks_build
    engine_blueprint.build = blueprint_build
    try:
        yield
    finally:
        engine_bootstrap.run = original_bootstrap
        engine_bootstrap.brand_facts = original_brand_facts
        engine_bootstrap.competitors = original_competitors
        engine_bootstrap.render_facts = original_render_facts
        engine_audit.run = original_audit
        engine_crawl.run = original_crawl
        engine_generate.run = original_generate
        engine_generate.parse_facts = original_parse_facts
        engine_tasks.build = original_tasks
        engine_blueprint.build = original_blueprint
        config = normalize_project(project_slug)
        from api.adapters import generated_assets

        generated_assets.normalize_project_assets(project_slug, config=config)
