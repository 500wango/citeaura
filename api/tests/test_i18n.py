"""国际化目录与回退链：en 为默认，中文不是非 zh 的展示回退。"""

from api.i18n import DEFAULT_LOCALE, SUPPORTED_LOCALES, detect_locale, normalize_locale, resolve
from api.i18n.catalog import load_all_catalogs
from api.adapters.localization import localize_ticket


def test_supported_locales_and_default():
    assert DEFAULT_LOCALE == "en"
    assert "en" in SUPPORTED_LOCALES
    assert "zh" in SUPPORTED_LOCALES
    assert "ja" in SUPPORTED_LOCALES


def test_normalize_and_detect_locale():
    assert normalize_locale("zh-CN") == "zh"
    assert normalize_locale("ja-JP") == "ja"
    assert normalize_locale("fr-FR") == "en"
    assert detect_locale(query_lang="ja") == "ja"
    assert detect_locale(stored="zh") == "zh"
    assert detect_locale(accept_language="en-US,en;q=0.9") == "en"
    assert detect_locale(accept_language="zh-CN,zh;q=0.9") == "zh"
    assert detect_locale() == "en"


def test_resolve_prefers_locale_then_english_not_chinese():
    catalogs = load_all_catalogs()
    assert resolve("nav.cta", "en", catalogs) == "Start free trial"
    assert resolve("nav.cta", "zh", catalogs) == "免费试用"
    assert resolve("nav.cta", "ja", catalogs) == "無料トライアル"
    # 未知键：非 zh 不把中文当魔法回退
    assert resolve("unknown.chrome.key", "en", catalogs) == "unknown.chrome.key"
    # 管线工单中文 id 在 en 下解析为英文
    assert "Chinese" not in resolve("统一一句话定义，四处逐字一致", "en", catalogs)
    assert "Standardize" in resolve("统一一句话定义，四处逐字一致", "en", catalogs)


def test_localize_ticket_uses_english_fallback():
    ticket = {
        "id": "T1",
        "title": "统一一句话定义，四处逐字一致",
        "package": "内容矩阵",
        "owner": "内容",
    }
    localized = localize_ticket(ticket)
    assert localized["title"] == "统一一句话定义，四处逐字一致"
    assert localized["title_en"] == "Standardize the one-sentence definition across four surfaces"
    assert "マトリクス" in localized["package_ja"] or localized["package_ja"] == "コンテンツマトリクス"
    assert localized["owner_en"] == "Content"
