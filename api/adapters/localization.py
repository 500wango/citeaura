"""Attach English display fields to engine artifacts without rewriting tasks.json."""

import re
from api.i18n import DEFAULT_LOCALE, resolve

# Exact English mappings for standard ticket titles
EXACT_TITLES_EN = {
    "解除 robots.txt 对 AI 抓取器的封禁": "Unblock AI crawlers in robots.txt",
    "补 sitemap.xml 并提交各搜索引擎": "Add sitemap.xml and submit to search engines",
    "上线 /llms.txt 官方事实索引": "Deploy /llms.txt official brand fact manifest",
    "建英文原生内容区": "Build native English content section",
    "修复前端渲染空壳页（SSR / 预渲染）": "Fix client-rendered empty-shell pages (SSR / Prerender)",
    "全站补 JSON-LD 结构化数据": "Implement site-wide JSON-LD structured data",
    "全站补「数字事实」抽取块": "Add numeric-facts extraction blocks site-wide",
    "全站补「FAQ」抽取块": "Add FAQ extraction blocks site-wide",
    "全站补「定义」抽取块": "Add definition extraction blocks site-wide",
    "全站补「对比」抽取块": "Add comparison extraction blocks site-wide",
    "全站补「操作步骤」抽取块": "Add step-by-step extraction blocks site-wide",
    "核心页正文扩到 1000+ 词": "Expand core page content to 1,000+ words",
    "百科词条（实体消歧地基）": "Create encyclopedia entry for entity disambiguation",
    "统一一句话定义，四处逐字一致": "Standardize one-sentence definition with verbatim consistency",
    "建品牌事实卡并标注证据等级": "Build brand facts library with evidence confidence levels",
    "拿下榜单/品牌库站词条": "Establish presence on benchmark & ranking directories",
    "进内容平台生态": "Publish content on authoritative ecosystem platforms",
}

# Regex dynamic patterns for dynamic ticket titles
DYNAMIC_TITLE_PATTERNS_EN = [
    (re.compile(r"^站点均分从\s*([\d.]+)\s*提到\s*70$"), r"Raise average site audit score from \1 to 70"),
    (re.compile(r"^补齐(.+)侧内容，中英对等$"), r"Balance \1 content for bilingual parity"),
    (re.compile(r"^全站补「(.+)」抽取块$"), r"Add '\1' extraction blocks across site"),
    (re.compile(r"^复测「(.+)」提及率$"), r"Re-sample '\1' brand mention rate"),
    (re.compile(r"^消除认知偏差：「(.+)」$"), r"Resolve perception gap: '\1'"),
    (re.compile(r"^跨过平台生态门槛：(.+)$"), r"Overcome platform ecosystem threshold: \1"),
    (re.compile(r"^(.+)无提示提及率\s*([\d.]+%?)\s*→\s*([\d.]+%?)$"), r"\1 unprompted mention rate \2 → \3"),
    (re.compile(r"^(.+)让官网进得了 AI 的检索结果$"), r"\1: Ensure official site appears in AI search retrieval"),
]

# Exact English mappings for ticket descriptions and actions
EXACT_DESCS_EN = {
    "无 sitemap，收录效率和覆盖面打折（method.md 可抓取性）": "No sitemap found, reducing crawler indexing efficiency and coverage.",
    "生成 sitemap.xml，robots.txt 里声明，提交百度/必应/Google/夸克": "Generate sitemap.xml, declare it in robots.txt, and submit to major search engines.",
    "低成本给 AI 一份人工整理的官方索引，国内很多站没做（content-patterns.md 第 7 节）": "Provide AI models with a curated official facts index via /llms.txt.",
    "用 `geo.py generate --asset llms` 产出后部署到网站根目录": "Generate /llms.txt asset and deploy it to your website root directory.",
    "静态 HTML 无正文，多数 AI 抓取器看到的是空白页——国内官网最常见致命伤（method.md 可抓取性）": "Static HTML contains no body text; AI crawlers see an empty page (use SSR or prerendering).",
    "对受影响路由启用 SSR 或预渲染，确保 curl 拿到的 HTML 含完整正文": "Enable SSR or static prerendering for affected routes so curl requests return full body text.",
    "无结构化数据，机器读不懂这页在讲什么实体（method.md 权威信号）": "No structured data found; machine crawlers cannot extract core entities.",
    "用 `geo.py generate --asset jsonld` 产出补丁，按页面类型挂 Organization / SoftwareApplication / Article / FAQPage / BreadcrumbList": "Generate and deploy JSON-LD Schema.org patches (Organization, SoftwareApplication, FAQPage, BreadcrumbList).",
    "高影响力页面平均 1,943 词，Bottom 四分位仅 170 词（method.md 内容长度）": "High-impact pages average 1,943 words; expand depth to improve information extractability.",
    "优先扩产品页、案例页、对比页；加定义、数字表、步骤、边界说明，不是灌水": "Expand product, case study, and comparison pages with definitions, data tables, and step-by-step guides.",
    "均分低于 70 说明整体处于「需要改造」区间（method.md 评分口径）": "Average site score is below 70, indicating critical extractability and SEO issues.",
    "按 audit.json 里分数最低的 10 页逐页改：H1 唯一、H2 拆到 6–10 节、列表密度 ≥0.35、加更新日期": "Improve the lowest-scoring pages: ensure unique H1, 6-10 H2 sections, high list density, and publication dates.",
    "口径不一致是 AI 描述品牌漂移的头号原因（content-patterns.md 第 6 节）": "Inconsistent brand messaging causes AI models to hallucinate or misrepresent your core features.",
    "所有内容生产的事实底座；无来源的事实一律标待确认（method.md 采样纪律）": "Establish a single source of truth (SSOT) for all brand claims and evidence.",
    "移除对应 Disallow，或改为仅屏蔽后台路径": "Remove Disallow directives for AI bots, or restrict Disallow to internal admin paths.",
    "海外 AI 引用的可识别语言里英文占 82.90%–95.07%，机翻页进不了候选池（global-platforms.md）": "English accounts for 82.9%–95.1% of global AI citations; machine-translated pages rarely get selected.",
    "至少 8 个英文原生页面：首页、产品、定价、对比、FAQ、案例 ×3。不是翻译中文页": "Create at least 8 native English pages: Homepage, Product, Pricing, Comparison, FAQ, and 3 Case Studies.",
    "仅 28 个榜单站域名占全库引用 9.1%，且引用位置全库最靠前；AI 回答「有哪些/哪个好/怎么选」时最省事就是抄现成榜单（cn-source-ranking.md）": "Benchmark and ranking directory domains account for high citation priority when AI models answer recommendation queries.",
    "内容平台四家占全库引用 16.4%；qq.com 是元宝 20.5% 的来源，toutiao.com 是豆包系入口（cn-source-ranking.md）": "Authoritative content platforms account for high citation shares across major AI search engines.",
}

DYNAMIC_DESC_PATTERNS_EN = [
    (re.compile(r"^robots 封禁 (.+)，这些引擎永远抓不到你.*"), r"robots.txt blocks \1, preventing these AI engines from indexing your site."),
    (re.compile(r"^([\d/]+)\s*页缺失[；;]\s*实测影响力增益\s*([^\s（]+).*"), r"Missing on \1 pages (estimated impact gain: \2)."),
    (re.compile(r"^参照 content-patterns\.md，在核心页补(.+)块.*"), r"Add extractable \1 blocks across core pages."),
    (re.compile(r"^把「(.+)」的定义句同步到：.*"), r"Synchronize the one-sentence definition for '\1' across homepage hero, about page, JSON-LD, and /llms.txt verbatim."),
    (re.compile(r"^填 content/facts\.md：.*"), r"Populate brand facts sheet: entities, aliases, products, key metrics, and evidence confidence levels A-E."),
]

DYNAMIC_ACCEPTANCE_PATTERNS_EN = [
    (re.compile(r"^重抓后 robots 不再整站封禁任何 AI 抓取器$"), r"robots.txt no longer blocks AI crawlers on re-crawl"),
    (re.compile(r"^重抓能取到 sitemap\.xml$"), r"sitemap.xml is successfully fetched on re-crawl"),
    (re.compile(r"^重抓能取到 /llms\.txt$"), r"/llms.txt is successfully fetched on re-crawl"),
    (re.compile(r"^受影响页面重抓后正文词数 ≥ 120$"), r"Affected pages have word count ≥ 120 on re-crawl"),
    (re.compile(r"^受影响页面重抓后含 JSON-LD$"), r"Affected pages contain valid JSON-LD on re-crawl"),
    (re.compile(r"^缺「(.+)」的页面数下降 ≥ 50%$"), r"Pages missing '\1' blocks decrease by ≥ 50%"),
    (re.compile(r"^正文 <1000 词的页面数下降 ≥ 40%$"), r"Pages with <1000 words decrease by ≥ 40%"),
    (re.compile(r"^重跑 audit 均分 ≥ 70$"), r"Re-audit average site score is ≥ 70"),
    (re.compile(r"^英文有效内容页 ≥ 8$"), r"Valid English content pages ≥ 8"),
    (re.compile(r"^四处定义句文本完全一致（人工核对）$"), r"Definition sentence is verbatim identical across all 4 surfaces (Manual verification)"),
    (re.compile(r"^facts\.md 存在且每条事实有证据等级$"), r"facts.md exists and all facts have evidence grades assigned"),
]


def _localize_text(text, locale):
    if not text or not isinstance(text, str):
        return text
    
    # 1. Direct i18n catalog lookup
    resolved = resolve(text, locale)
    if resolved != text:
        return resolved
    
    # 2. English fallbacks
    if locale == "en" or locale != "zh":
        # Exact title
        if text in EXACT_TITLES_EN:
            return EXACT_TITLES_EN[text]
        # Dynamic title patterns
        for pat, repl in DYNAMIC_TITLE_PATTERNS_EN:
            if pat.search(text):
                return pat.sub(repl, text)
        # Exact descriptions
        if text in EXACT_DESCS_EN:
            return EXACT_DESCS_EN[text]
        # Dynamic descriptions
        for pat, repl in DYNAMIC_DESC_PATTERNS_EN:
            if pat.search(text):
                return pat.sub(repl, text)
        # Dynamic acceptance checks
        for pat, repl in DYNAMIC_ACCEPTANCE_PATTERNS_EN:
            if pat.search(text):
                return pat.sub(repl, text)

    return text


def localize_ticket(ticket):
    """复制工单并附加展示层语言字段，原字段保持与引擎契约一致。"""
    result = dict(ticket)
    title = ticket.get("title") or ticket.get("name")
    desc = ticket.get("desc") or ticket.get("description")
    action = ticket.get("action")
    package = ticket.get("package") or ticket.get("category")
    owner = ticket.get("owner") or ticket.get("role")

    for locale in ("en",):
        result[f"title_{locale}"] = _localize_text(title, locale)
        result[f"desc_{locale}"] = _localize_text(desc, locale)
        if action:
            result[f"action_{locale}"] = _localize_text(action, locale)
        if package:
            result[f"package_{locale}"] = _localize_text(package, locale)
            result[f"category_{locale}"] = result[f"package_{locale}"]
        if owner:
            result[f"owner_{locale}"] = _localize_text(owner, locale)
            result[f"role_{locale}"] = result[f"owner_{locale}"]
            
    # Localize acceptance criteria if present
    acc = ticket.get("acceptance")
    if isinstance(acc, dict) and "desc" in acc:
        acc_copy = dict(acc)
        for locale in ("en",):
            acc_copy[f"desc_{locale}"] = _localize_text(acc.get("desc"), locale)
        result["acceptance"] = acc_copy

    return result


def localize_tickets(tickets):
    return [localize_ticket(ticket) if isinstance(ticket, dict) else ticket for ticket in tickets]
