"""Locale catalog behavior and translation completeness."""

import json
import re
from pathlib import Path

from api.i18n import DEFAULT_LOCALE, SUPPORTED_LOCALES, detect_locale, normalize_locale, resolve
from api.i18n.catalog import load_all_catalogs, translate_map
from api.adapters.localization import localize_ticket, normalize_english_typography


def test_supported_locales_and_default():
    assert DEFAULT_LOCALE == "en"
    assert SUPPORTED_LOCALES == ("en", "zh", "ja", "ko", "es", "fr", "de")


def test_normalize_and_detect_locale():
    assert normalize_locale("zh-CN") == "zh"
    assert normalize_locale("ja-JP") == "ja"
    assert normalize_locale("fr-FR") == "fr"
    assert detect_locale(query_lang="ja") == "ja"
    assert detect_locale(stored="zh") == "zh"
    assert detect_locale(accept_language="en-US,en;q=0.9") == "en"
    assert detect_locale(accept_language="zh-CN,zh;q=0.9") == "zh"
    assert detect_locale() == "en"


def test_resolve_uses_locale_without_silent_english_fallback():
    catalogs = load_all_catalogs()
    assert resolve("nav.cta", "en", catalogs) == "Start free trial"
    assert resolve("nav.cta", "zh", catalogs) == "开始免费试用"
    assert resolve("nav.cta", "ja", catalogs) == "無料トライアルを開始"
    assert resolve("landing.hero_copy", "zh", catalogs) != resolve("landing.hero_copy", "en", catalogs)
    assert resolve("unknown.chrome.key", "en", catalogs) == "unknown.chrome.key"
    assert "Chinese" not in resolve("统一一句话定义，四处逐字一致", "en", catalogs)
    assert "Standardize" in resolve("统一一句话定义，四处逐字一致", "en", catalogs)


def test_translate_map_does_not_inherit_english_for_non_english_locale():
    catalogs = {
        "en": {"known": "Known English"},
        "zh": {"known": "已知"},
    }
    entries = {
        "known": {"en": "Known English", "zh": "已知"},
        "missing": {"en": "English only"},
    }
    assert translate_map(entries, "zh", catalogs) == {"known": "已知", "missing": "missing"}
    assert translate_map(entries, "en", catalogs) == {"known": "Known English", "missing": "English only"}


def test_all_locale_catalogs_have_the_same_keys_and_placeholders():
    catalogs = load_all_catalogs()
    english_keys = set(catalogs["en"])
    for locale in SUPPORTED_LOCALES:
        assert set(catalogs[locale]) == english_keys, locale
        if locale == "en":
            continue
        for key, source in catalogs["en"].items():
            source_tokens = set(re.findall(r"\{[^{}]+\}", source))
            translated_tokens = set(re.findall(r"\{[^{}]+\}", catalogs[locale][key]))
            assert translated_tokens == source_tokens, (locale, key)


def test_every_frontend_t_key_is_registered():
    root = Path(__file__).resolve().parents[2] / "web" / "app"
    keys = set()
    for path in root.rglob("*.js"):
        text = path.read_text("utf-8")
        keys.update(re.findall(r"\bt\(\s*['\"]([^'\"]+)['\"]", text))
        keys.update(re.findall(r"\btError\(\s*err\s*,\s*['\"]([^'\"]+)['\"]", text))
    assert keys <= set(load_all_catalogs()["en"]), sorted(keys - set(load_all_catalogs()["en"]))


def test_workspace_navigation_keys_cover_all_track_items():
    app_js = (Path(__file__).resolve().parents[2] / "web" / "app" / "app.js").read_text("utf-8")
    track_block = re.search(r"export const TRACKS = \[.*?\n\];", app_js, re.S)
    assert track_block, "TRACKS export not found in app.js"
    required = set(re.findall(r"labelKey:\s*'([^']+)'", track_block.group(0)))
    assert "nav.blueprint" in required
    assert "nav.plan" in required
    catalogs = load_all_catalogs()
    for locale, catalog in catalogs.items():
        assert required <= set(catalog), (locale, sorted(required - set(catalog)))
        assert catalog["nav.blueprint"] not in {"", "[[missing:nav.blueprint]]"}


def test_frontend_legacy_localize_literals_are_catalogued():
    root = Path(__file__).resolve().parents[2]
    catalog = load_all_catalogs()["en"]
    catalog_values = set(catalog.values())
    patterns = [
        (root / "web" / "assets" / "landing.js", r"\blocalize\(\s*['\"]([^'\"]+)['\"]", "landing localize"),
        (root / "web" / "app", r"\btranslateText\(\s*['\"]([^'\"]+)['\"]", "app translateText"),
    ]
    missing = []
    for path, pattern, label in patterns:
        paths = path.rglob("*.js") if path.is_dir() else [path]
        for source in paths:
            for literal in re.findall(pattern, source.read_text("utf-8")):
                if literal not in catalog and literal not in catalog_values:
                    missing.append(f"{label}: {source}:{literal}")
    assert not missing, missing


def test_non_english_catalogs_do_not_contain_known_machine_translation_artifacts():
    forbidden = {
        "zh": (
            "审判", "车票", "签名", "发动机", "动作车票", "能见度", "14-day",
            "教会网站", "演员", "机器人.txt", "出界核查", "快速报道", "代代代",
            "传送包", "门票", "票价", "模式提供者", "未知模式", "点即时", "点入时",
        ),
        "ja": (
            "14-day", "Bi-Weekly", "キヤノン", "白い標識", "CABot",
            "Mention-only", "Drafts",
        ),
        "ko": (
            "이름 *", "공지사항", "제품정보", "Crawlability", "Inject ",
            "Evidence-backed", "One-click", "Compile ", "Current English",
            "맞은 측정", "주문 webhook", "적출", "matrix",
        ),
        "es": (
            "Subscribe Pro", "Subscribe Agency", "14-day", "Perplejidad",
            "Profundos Buscos", "Boletos", "billetes y paquetes",
            "Tigres transparentes", "carreras de trabajo", "previsar",
        ),
        "fr": (
            "Subscribe Pro", "Subscribe Agency", "14-day", "Current English",
            "AI réponses", "Link client", "Package de", "recrawl",
        ),
        "de": (
            "Subscribe Pro", "Subscribe Agency", "14-day", "Blueprint Recover",
            "Kanalblaupausdruck", "Arbeitsbereichbesitzer", "Schauspieler",
            "View Ergebnisse", "Save Fact", "Compile Executive",
            "Single Source of Truth", "Pipeline-Running", "Offener Arbeitsbereich",
            "Arbeitsplatz", "Musteranbieter", "Aktionskarten", "Standard-Action-Tickets",
        ),
    }
    catalogs = load_all_catalogs()
    failures = []
    for locale, needles in forbidden.items():
        for key, value in catalogs[locale].items():
            if any(needle in value for needle in needles):
                failures.append((locale, key, value))
    assert not failures, failures[:30]


def test_non_english_catalogs_do_not_silently_copy_long_english_copy():
    """Long English sentences are only valid in the English catalog or as identifiers."""
    catalogs = load_all_catalogs()
    failures = []
    allowed_exact = {
        "CiteAura", "GEO", "FAQ", "Meta AI", "Microsoft", "Copilot", "You", "You.com",
        "AES-256-GCM", "Claude", "DeepSeek", "Gemini", "Grok", "OpenAI",
        "Perplexity", "SSR", "WAF", "linear.app", "yourbrand.com", "Google",
        "Mistral", "Le", "Chat", "Sonnet", "Opus", "Sol", "Terra", "Flash",
        "Pro", "xAI", "Doubao", "App", "Web", "GPT", "Baidu", "AI", "Search",
        "Google", "Overviews", "Mistral", "Le", "Chat", "Nano", "Sonar", "Research",
        "content", "facts", "md", "Deep", "facts.md",
    }
    for locale in SUPPORTED_LOCALES:
        if locale == "en":
            continue
        for key, value in catalogs[locale].items():
            if value == catalogs["en"].get(key) and value not in allowed_exact:
                words = re.findall(r"[A-Za-z]{2,}", value)
                # Provider/model labels are product identifiers, not prose.
                identifier_only = key.startswith("literal.") and words and all(word in allowed_exact for word in words)
                if len(words) >= 3 and not identifier_only:
                    failures.append((locale, key, value))
    assert not failures, failures[:30]


def test_non_english_catalogs_do_not_leak_translation_markers():
    """Protected-term markers are an internal detail and must never reach the UI."""
    catalogs = load_all_catalogs()
    failures = []
    for locale in SUPPORTED_LOCALES:
        if locale == "en":
            continue
        for key, value in catalogs[locale].items():
            if "§" in value or re.search(r"\bCA\d+\b", value):
                failures.append((locale, key, value))
    assert not failures, failures[:30]


def test_latin_catalogs_do_not_expose_known_english_ui_residue():
    """Keep ordinary English UI phrases out of the reviewed Latin catalogs."""
    forbidden = {
        "es": (
            "Action:", "Save Asset", "Deploy Assets", "Prompt Coverage", "Prompt log",
            "User Prompt:", "View Setup Preview", "Sitewide GEO Audit", "Campaigns",
            "Libre AI Auditoría", "Percepción Gaps", "Effort: Med", "Copied!",
            "Snapshot creado",
        ),
        "fr": (
            "Action:", "Save Asset", "Deploy Assets", "Prompt Coverage", "Prompt log",
            "User Prompt:", "View Setup Preview", "Sitewide GEO Audit", "Brand fact",
            "Libre AI Vérification", "Current English", "Snapshot créé",
        ),
        "de": (
            "Backup Snapshots", "Start Lite", "User Prompt:", "View Setup Preview",
            "Sitewide GEO Audit", "Brand Fact Bibliothek", "Deploy Assets", "Save Asset",
            "Current English", "Web-Based Retrieval", "Manual · Surface", "Snapshot erfolgreich",
            "Snapshot erstellen",
        ),
    }
    catalogs = load_all_catalogs()
    failures = []
    for locale, phrases in forbidden.items():
        for key, value in catalogs[locale].items():
            for phrase in phrases:
                if phrase.casefold() in value.casefold():
                    failures.append((locale, key, phrase, value))
    assert not failures, failures[:30]


def test_localize_ticket_uses_english_fallback():
    ticket = {
        "id": "T1",
        "title": "统一一句话定义，四处逐字一致",
        "package": "内容矩阵",
        "owner": "内容",
        "desc": "口径不一致是 AI 描述品牌漂移的头号原因（content-patterns.md 第 6 节）",
    }
    localized = localize_ticket(ticket)
    assert localized["title"] == "统一一句话定义，四处逐字一致"
    assert "Standardize" in localized["title_en"]
    assert "Content" in localized["owner_en"]
    assert "Inconsistent brand messaging" in localized["desc_en"]


def test_localize_ticket_dynamic_titles():
    # robots.txt ticket
    t_robots = {
        "id": "T2",
        "title": "解除 robots.txt 对 AI 抓取器的封禁",
        "desc": "robots 封禁 GPTBot、ClaudeBot，这些引擎永远抓不到你（method.md 可抓取性）",
        "action": "移除对应 Disallow，或改为仅屏蔽后台路径",
    }
    loc_robots = localize_ticket(t_robots)
    assert loc_robots["title_en"] == "Unblock AI crawlers in robots.txt"
    assert "robots.txt blocks GPTBot, ClaudeBot" in loc_robots["desc_en"]
    assert "、" not in loc_robots["desc_en"]
    assert "Remove Disallow" in loc_robots["action_en"]

    # sitemap ticket
    t_sitemap = {
        "id": "T3",
        "title": "补 sitemap.xml 并提交各搜索引擎",
        "desc": "无 sitemap，收录效率和覆盖面打折（method.md 可抓取性）",
    }
    loc_sitemap = localize_ticket(t_sitemap)
    assert loc_sitemap["title_en"] == "Add sitemap.xml and submit to search engines"
    assert "No sitemap found" in loc_sitemap["desc_en"]

    # dynamic score ticket
    t_score = {
        "id": "T4",
        "title": "站点均分从 28.6 提到 70",
        "desc": "均分低于 70 说明整体处于「需要改造」区间（method.md 评分口径）",
    }
    loc_score = localize_ticket(t_score)
    assert loc_score["title_en"] == "Raise average site audit score from 28.6 to 70"
    assert "Average site score is below 70" in loc_score["desc_en"]


def test_sampling_mode_faq_quotes_canonical_badges():
    catalogs = load_all_catalogs()
    for locale, catalog in catalogs.items():
        for key in ("landing.mode_parametric", "landing.mode_search", "landing.mode_manual"):
            assert catalog[key] in catalog["landing.faq_1_a"], (locale, key, catalog[key])
    assert catalogs["zh"]["landing.mode_manual"] == "人工 · 产品端"
    assert catalogs["zh"]["landing.mode_parametric"] in catalogs["zh"]["landing.faq_1_a"]
    assert "API · 模型知识" not in catalogs["zh"]["landing.faq_1_a"]


def test_api_error_codes_are_catalogued():
    catalog = load_all_catalogs()["en"]
    for key in (
        "error.generic",
        "trial_limit_exceeded",
        "email_already_registered",
        "project_job_already_running",
        "insufficient_role",
        "network_error",
        "session_expired",
    ):
        assert key in catalog
        assert catalog[key]


def test_english_typography_normalization_preserves_measurement_symbols_and_urls():
    value = "Review：GPTBot、ClaudeBot；coverage ≥ 95％；https://example.com/a?x=1"

    assert normalize_english_typography(value) == (
        "Review: GPTBot, ClaudeBot; coverage ≥ 95%; https://example.com/a?x=1"
    )
