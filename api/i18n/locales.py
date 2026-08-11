"""支持的界面语言与解析规则。"""

SUPPORTED_LOCALES = ("en", "zh", "ja")
DEFAULT_LOCALE = "en"
LOCALE_HTML_LANG = {"en": "en", "zh": "zh-CN", "ja": "ja"}
LOCALE_LABELS = {"en": "EN", "zh": "ZH", "ja": "JA"}


def normalize_locale(value, default=DEFAULT_LOCALE):
    """把任意输入收敛到支持的 locale 代码。"""
    if value is None:
        return default
    raw = str(value).strip().lower().replace("_", "-")
    if not raw:
        return default
    primary = raw.split("-", 1)[0]
    if primary in SUPPORTED_LOCALES:
        return primary
    if raw.startswith("zh"):
        return "zh"
    if raw.startswith("ja"):
        return "ja"
    if raw.startswith("en"):
        return "en"
    return default


def detect_locale(query_lang=None, stored=None, accept_language=None):
    """查询参数 > 本地存储 > Accept-Language > 默认 en。"""
    if query_lang:
        return normalize_locale(query_lang)
    if stored:
        return normalize_locale(stored)
    if accept_language:
        # 取第一个质量最高的语言标签
        first = str(accept_language).split(",", 1)[0].strip()
        if first:
            primary = first.split(";", 1)[0].strip()
            normalized = normalize_locale(primary, default=None)
            if normalized:
                return normalized
    return DEFAULT_LOCALE
