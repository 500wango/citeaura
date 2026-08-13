"""把引擎产物约束为 CiteAura 的国际市场范围。"""

import re
from contextlib import contextmanager
from copy import deepcopy

from api.adapters.engine import geolib


HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
DOMESTIC_PLATFORM_CODES = frozenset((
    "glm", "doubao", "deepseek", "kimi", "minimax", "nano_ai", "baidu", "doubao_app",
))
GLOBAL_PLATFORM_CODES = frozenset((
    "gemini", "openai", "claude", "grok", "perplexity", "chatgpt", "claude_web",
))

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
    "devsite": "GitHub / Docs / dev.to",
    "media_en": "English Industry Media (TechCrunch / VentureBeat)",
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
        ("buyer_communities", "Buyer Communities and Industry Associations", "P2"),
        ("wikipedia", "Wikipedia (only if independently notable)", "P2"),
    ],
    "software": [
        ("official_en", "English Official Site", "P0"),
        ("docs", "Product Documentation and API Reference", "P0"),
        ("review", "Software Review Platforms", "P1"),
        ("developer_community", "Developer Communities and Technical Media", "P1"),
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
        ("customer_communities", "Customer Communities and Q&A Sources", "P2"),
        ("industry_media", "Industry Media", "P2"),
        ("wikipedia", "Wikipedia (only if independently notable)", "P2"),
    ],
    "commerce": [
        ("official_en", "English Official Site", "P0"),
        ("shopping_feeds", "Search and Shopping Product Feeds", "P0"),
        ("marketplaces", "Relevant Retail Marketplaces", "P1"),
        ("review_communities", "Product Review and Customer Communities", "P1"),
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
        ("social_distribution", "Relevant Social Distribution Channels", "P2"),
        ("industry_media", "Peer Publications and Industry Media", "P2"),
    ],
    "generic": [
        ("official_en", "English Official Site", "P0"),
        ("linkedin", "LinkedIn", "P1"),
        ("industry_directories", "Relevant Industry Directories", "P1"),
        ("industry_media", "Relevant Industry Media", "P1"),
        ("youtube", "YouTube", "P2"),
        ("customer_communities", "Relevant Customer Communities", "P2"),
        ("wikipedia", "Wikipedia (only if independently notable)", "P2"),
    ],
}

PROFILE_RULES = (
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
        "volume": "2-4 posts/month", "cadence": "Monthly", "owner": "Marketing",
        "domains": ["linkedin.com"], "why": "Provides attributable company and expert identity signals.",
        "effect": "Supports B2B entity verification",
    },
    "youtube": {
        "kind": "Video", "forms": ["Product demonstrations", "How-to videos", "Complete subtitles"],
        "volume": "1-2 videos/month", "cadence": "Monthly", "owner": "Content",
        "domains": ["youtube.com"], "why": "Video transcripts provide accessible product and process evidence.",
        "effect": "Adds multimodal and transcript-based discovery coverage",
    },
    "wikipedia": {
        "kind": "Encyclopedia", "forms": ["Independent-source review", "Entity entry if notable"],
        "volume": "Only when independently notable", "cadence": "Evidence review first", "owner": "Marketing",
        "domains": ["wikipedia.org"], "why": "Entity authority requires substantial independent reliable coverage.",
        "effect": "May strengthen entity disambiguation when eligibility is established",
    },
    "review": {
        "kind": "Review Platform", "forms": ["Product profile", "Verified customer reviews", "Comparison pages"],
        "volume": "2-3 relevant platforms", "cadence": "Initial setup + quarterly updates", "owner": "Marketing",
        "domains": [], "why": "Independent product reviews support commercial comparison queries.",
        "effect": "Captures recommendation and alternatives intent",
    },
    "b2b_marketplaces": {
        "kind": "B2B Marketplace", "forms": ["Supplier profile", "Product catalog", "Verified capabilities"],
        "volume": "2-4 relevant marketplaces", "cadence": "Initial setup + monthly updates", "owner": "Sales + Marketing",
        "domains": ["alibaba.com", "made-in-china.com", "globalsources.com"],
        "why": "Buyer marketplaces are discovery surfaces for sourcing and supplier queries.",
        "effect": "Improves qualified B2B supplier discovery",
    },
    "trade_media": {
        "kind": "Trade Media", "forms": ["Technical profile", "Buyer guide", "Verified case study"],
        "volume": "1-2 placements/quarter", "cadence": "Quarterly", "owner": "Marketing",
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
        "volume": "2-4 technical pieces/month", "cadence": "Monthly", "owner": "Engineering",
        "domains": ["github.com", "dev.to", "stackoverflow.com"],
        "why": "Developer communities provide implementation evidence outside the product site.",
        "effect": "Supports technical recommendation and troubleshooting queries",
    },
    "industry_media": {
        "kind": "Industry Media", "forms": ["Expert article", "Press coverage", "Research citation"],
        "volume": "1-2 placements/quarter", "cadence": "Quarterly", "owner": "Marketing",
        "domains": [], "why": "Relevant industry media provides independent category context.",
        "effect": "Strengthens third-party authority signals",
    },
    "industry_directories": {
        "kind": "Industry Directory", "forms": ["Verified company profile", "Service listing", "Association record"],
        "volume": "3-5 relevant directories", "cadence": "Quarterly", "owner": "Marketing",
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
        "volume": "2-4 pieces/month", "cadence": "Monthly", "owner": "Marketing",
        "domains": [], "why": "Visual discovery channels expose products through demonstrations and use cases.",
        "effect": "Adds multimodal product discovery signals",
    },
    "consumer_media": {
        "kind": "Consumer Media", "forms": ["Category guide", "Independent review", "Expert comparison"],
        "volume": "1-2 placements/quarter", "cadence": "Quarterly", "owner": "PR + Marketing",
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
        "volume": "2-4 posts/month", "cadence": "Weekly", "owner": "Editorial + Marketing",
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


def contains_han(value):
    return bool(HAN.search(str(value or "")))


def infer_business_profile(config):
    """从项目画像推断渠道策略；信息不足时返回通用策略并降低置信度。"""
    brand = config.get("brand") if isinstance(config, dict) and isinstance(config.get("brand"), dict) else {}
    industry = str(brand.get("industry") or "").lower()
    fields = [brand.get("target_users"), brand.get("business_goal")]
    fields += brand.get("products") if isinstance(brand.get("products"), list) else []
    supporting = " ".join(str(value or "").lower() for value in fields if value)
    matches = []
    for profile, keywords in PROFILE_RULES:
        industry_hits = [keyword for keyword in keywords if keyword in industry]
        support_hits = [keyword for keyword in keywords if keyword in supporting]
        hits = list(dict.fromkeys(industry_hits + support_hits))
        if hits:
            matches.append((len(industry_hits) * 3 + len(support_hits), profile, industry_hits, hits))
    if matches:
        _score, profile, industry_hits, hits = max(matches, key=lambda item: item[0])
        evidence = []
        if industry_hits:
            evidence.append(f"brand.industry matched the {profile} profile")
        if len(hits) > len(industry_hits):
            evidence.append(f"brand products, audience, or business goal matched the {profile} profile")
        return {
            "id": profile,
            "label": profile.replace("_", " ").title(),
            "confidence": "high" if industry_hits else "medium",
            "evidence": evidence,
        }
    return {
        "id": "generic",
        "label": "General business",
        "confidence": "low",
        "evidence": [],
    }


def _profile_channels(profile, existing):
    existing_by_id = {
        str(channel.get("id")): channel
        for channel in existing
        if isinstance(channel, dict) and channel.get("market") == "global"
    }
    rows = []
    for channel_id, name, priority in CHANNEL_STRATEGIES[profile["id"]]:
        previous = existing_by_id.get(channel_id, {})
        defaults = CHANNEL_FIELD_DEFAULTS.get(channel_id, {
            "kind": "Configured Channel", "forms": ["Relevant authoritative profile", "Evidence-backed content"],
            "volume": "As appropriate for the project", "cadence": "Review quarterly", "owner": "Marketing",
            "domains": [], "why": "Use a relevant authoritative source for this project profile.",
            "effect": "Supports project-specific discovery and verification",
        })
        rows.append({
            **defaults,
            **previous,
            "id": channel_id,
            "name": name,
            "priority": priority,
            "market": "global",
            "covered": bool(previous.get("covered")),
            "strategy_profile": profile["id"],
        })
    return rows


def is_global_sample(row):
    return (
        isinstance(row, dict)
        and row.get("platform") not in DOMESTIC_PLATFORM_CODES
        and row.get("market") in ("global", "both", None)
        and not contains_han(row.get("question"))
    )


def normalize_questions(questions, *, strict=False):
    """只保留英文或其他非汉字的国际问题。"""
    if not isinstance(questions, list):
        if strict:
            raise ValueError("questions must be an array")
        return []
    normalized = []
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
        if contains_han(text):
            if strict:
                raise ValueError("question text must not contain Chinese characters")
            continue
        if market == "cn" or market not in ("global", "both"):
            if strict:
                raise ValueError("question market must be global")
            continue
        normalized.append({
            **item,
            "text": text,
            "market": "global",
            "group": GROUP_NAMES.get(item.get("group"), item.get("group") or "recommendation"),
        })
    return normalized


def _normalize_competitors(competitors):
    normalized = []
    for item in competitors if isinstance(competitors, list) else []:
        if not isinstance(item, dict) or item.get("market") == "cn":
            continue
        if item.get("market") not in ("global", "both", None):
            continue
        normalized.append({**item, "market": "global"})
    return normalized


def _normalize_platforms(platforms):
    normalized = []
    for code in platforms if isinstance(platforms, list) else []:
        code = str(code or "").strip()
        if not code or code in DOMESTIC_PLATFORM_CODES:
            continue
        if code in GLOBAL_PLATFORM_CODES or code.startswith("custom_"):
            if code not in normalized:
                normalized.append(code)
    return normalized


def normalize_config_data(config):
    current = deepcopy(config) if isinstance(config, dict) else {}
    current["market"] = "global"
    current["questions"] = normalize_questions(current.get("questions"))
    current["competitors"] = _normalize_competitors(current.get("competitors"))
    current["platforms"] = _normalize_platforms(current.get("platforms"))
    return current


def normalize_config(project_slug):
    with geolib.project_lock(project_slug):
        current = geolib.load_config(project_slug)
        normalized = normalize_config_data(current)
        if normalized != current:
            geolib.save_config(project_slug, normalized)
        return normalized


def _rate(items, predicate):
    return round(sum(1 for item in items if predicate(item)) / len(items), 3) if items else 0


def normalize_blueprint_data(blueprint, *, profile=None):
    current = deepcopy(blueprint) if isinstance(blueprint, dict) else {}
    existing_channels = [
        {
            **channel,
            "name": GLOBAL_CHANNEL_NAMES.get(channel.get("id"), channel.get("name")),
            "market": "global",
        }
        for channel in current.get("channels", [])
        if isinstance(channel, dict) and channel.get("market") == "global"
    ]
    profile = profile if isinstance(profile, dict) and profile.get("id") in CHANNEL_STRATEGIES else None
    channels = _profile_channels(profile, existing_channels) if profile else existing_channels
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
        "channel_total": len(channels),
        "channel_covered": sum(bool(channel.get("covered")) for channel in channels),
        "channel_rate": _rate(channels, lambda channel: bool(channel.get("covered"))),
        "p0p1_total": sum(channel.get("priority") in ("P0", "P1") for channel in channels),
        "p0p1_covered": sum(
            channel.get("priority") in ("P0", "P1") and bool(channel.get("covered"))
            for channel in channels
        ),
        "content_total": len(contents),
        "content_done": sum(content.get("status") in ("ready", "done", "已成稿") for content in contents),
        "content_rate": _rate(contents, lambda content: content.get("status") in ("ready", "done", "已成稿")),
        "content_gap": sum(content.get("status") == "gap" for content in contents),
    }
    roadmap = [
        {
            "window": "0-30 Days",
            "focus": "Foundational Baseline",
            "items": [channel.get("name") for channel in channels if channel.get("priority") == "P0"]
            + ["Brand verification and pricing guide pages"],
        },
        {
            "window": "30-60 Days",
            "focus": "High-Leverage Channels & Content Matrix",
            "items": [channel.get("name") for channel in channels if channel.get("priority") == "P1"][:6]
            + ["1-2 articles each for recommendations, comparisons, and alternatives"],
        },
        {
            "window": "60-90 Days",
            "focus": "Scale & Closed-Loop Verification",
            "items": [channel.get("name") for channel in channels if channel.get("priority") == "P2"][:5]
            + ["Complete scenario tutorials and risk explanations", "Run 6 consecutive verification cycles"],
        },
    ]
    return {
        **current,
        "market": "global",
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
        profile = infer_business_profile(config)
        normalized = normalize_blueprint_data(current, profile=profile)
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
        "by_market": {"cn": 0, "global": len(tasks), "both": 0},
        "auto_verifiable": sum(
            isinstance(task.get("acceptance"), dict) and task["acceptance"].get("type") == "auto"
            for task in tasks
        ),
    }


def normalize_tasks_data(data):
    current = deepcopy(data) if isinstance(data, dict) else {}
    normalized = []
    for task in current.get("tasks", []):
        if not isinstance(task, dict) or task.get("market") == "cn":
            continue
        task = {**task, "market": "global"}
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
        "market": "global",
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
        if normalized != current:
            geolib.write_json(path, normalized)
        return normalized


def normalize_audit(project_slug):
    path = geolib.project_dir(project_slug) / "audit.json"
    if not path.is_file():
        return None
    with geolib.project_lock(project_slug):
        current = geolib.read_json(path, {}) or {}
        if current.get("market") != "global":
            current["market"] = "global"
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


def normalize_metrics(project_slug, question_count=None):
    directory = geolib.project_dir(project_slug) / "metrics"
    if not directory.is_dir():
        return []
    normalized_files = []
    with geolib.project_lock(project_slug):
        for path in sorted(directory.glob("*.json")):
            current = geolib.read_json(path, {}) or {}
            platforms = {
                code: {**item, "market": "global"}
                for code, item in (current.get("platforms") or {}).items()
                if code not in DOMESTIC_PLATFORM_CODES
                and isinstance(item, dict)
                and item.get("market") in ("global", "both", None)
            }
            normalized = {**current, "platforms": platforms}
            date = str(current.get("date") or "")
            sample_path = geolib.project_dir(project_slug) / "samples" / f"{date}.jsonl"
            if sample_path.is_file():
                rows = [row for row in geolib.read_jsonl(sample_path) if is_global_sample(row)]
                normalized["sample_count"] = len(rows)
                normalized["sample_summary"] = _sample_summary(rows)
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
                provenance["requested_platforms"] = [
                    code for code in provenance.get("requested_platforms", [])
                    if code not in DOMESTIC_PLATFORM_CODES
                ]
                provenance["platforms"] = [
                    item for item in provenance.get("platforms", [])
                    if isinstance(item, dict) and item.get("engine_code") not in DOMESTIC_PLATFORM_CODES
                ]
                if isinstance(provenance.get("question_set"), dict) and question_count is not None:
                    provenance["question_set"] = {**provenance["question_set"], "count": question_count}
                normalized["provenance"] = provenance
            if normalized != current:
                geolib.write_json(path, normalized)
            normalized_files.append(normalized)
    return normalized_files


def normalize_project(project_slug):
    if not (geolib.project_dir(project_slug) / "geo.json").is_file():
        return {}
    config = normalize_config(project_slug)
    normalize_audit(project_slug)
    normalize_metrics(project_slug, question_count=len(config.get("questions") or []))
    normalize_tasks(project_slug)
    normalize_blueprint(project_slug)
    return config


@contextmanager
def normalize_generated_outputs(project_slug):
    """确保引擎生成的问题、工单和蓝图在下游步骤前立即归一。"""
    import blueprint as engine_blueprint
    import bootstrap as engine_bootstrap
    import tasks as engine_tasks

    original_bootstrap = engine_bootstrap.run
    original_tasks = engine_tasks.build
    original_blueprint = engine_blueprint.build

    def bootstrap_run(slug, *args, **kwargs):
        result = original_bootstrap(slug, *args, **kwargs)
        if slug == project_slug:
            return normalize_config(project_slug)
        return result

    def tasks_build(slug, *args, **kwargs):
        result = original_tasks(slug, *args, **kwargs)
        return normalize_tasks(project_slug) if slug == project_slug else result

    def blueprint_build(slug, *args, **kwargs):
        result = original_blueprint(slug, *args, **kwargs)
        return normalize_blueprint(project_slug) if slug == project_slug else result

    engine_bootstrap.run = bootstrap_run
    engine_tasks.build = tasks_build
    engine_blueprint.build = blueprint_build
    try:
        yield
    finally:
        engine_bootstrap.run = original_bootstrap
        engine_tasks.build = original_tasks
        engine_blueprint.build = original_blueprint
        normalize_project(project_slug)
