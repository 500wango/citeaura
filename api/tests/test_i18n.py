"""English-only locale catalog behavior."""

from api.i18n import DEFAULT_LOCALE, SUPPORTED_LOCALES, detect_locale, normalize_locale, resolve
from api.i18n.catalog import load_all_catalogs
from api.adapters.localization import localize_ticket, normalize_english_typography


def test_supported_locales_and_default():
    assert DEFAULT_LOCALE == "en"
    assert SUPPORTED_LOCALES == ("en",)


def test_normalize_and_detect_locale():
    assert normalize_locale("zh-CN") == "en"
    assert normalize_locale("ja-JP") == "en"
    assert normalize_locale("fr-FR") == "en"
    assert detect_locale(query_lang="ja") == "en"
    assert detect_locale(stored="zh") == "en"
    assert detect_locale(accept_language="en-US,en;q=0.9") == "en"
    assert detect_locale(accept_language="zh-CN,zh;q=0.9") == "en"
    assert detect_locale() == "en"


def test_resolve_is_english_only():
    catalogs = load_all_catalogs()
    assert resolve("nav.cta", "en", catalogs) == "Start free trial"
    assert resolve("nav.cta", "zh", catalogs) == "Start free trial"
    assert resolve("nav.cta", "ja", catalogs) == "Start free trial"
    assert resolve("unknown.chrome.key", "en", catalogs) == "unknown.chrome.key"
    assert "Chinese" not in resolve("统一一句话定义，四处逐字一致", "en", catalogs)
    assert "Standardize" in resolve("统一一句话定义，四处逐字一致", "en", catalogs)


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


def test_english_typography_normalization_preserves_measurement_symbols_and_urls():
    value = "Review：GPTBot、ClaudeBot；coverage ≥ 95％；https://example.com/a?x=1"

    assert normalize_english_typography(value) == (
        "Review: GPTBot, ClaudeBot; coverage ≥ 95%; https://example.com/a?x=1"
    )
