"""Supported product locales and normalization rules."""

SUPPORTED_LOCALES = ("en", "zh", "ja", "ko", "es", "fr", "de")
DEFAULT_LOCALE = "en"
LOCALE_HTML_LANG = {
    "en": "en",
    "zh": "zh-CN",
    "ja": "ja",
    "ko": "ko",
    "es": "es",
    "fr": "fr",
    "de": "de",
}
LOCALE_LABELS = {
    "en": "English",
    "zh": "简体中文",
    "ja": "日本語",
    "ko": "한국어",
    "es": "Español",
    "fr": "Français",
    "de": "Deutsch",
}


def normalize_locale(value, default=DEFAULT_LOCALE):
    """Normalize any input to a supported locale code."""
    if value is None:
        return default
    raw = str(value).strip().lower().replace("_", "-")
    if not raw:
        return default
    primary = raw.split("-", 1)[0]
    if primary in SUPPORTED_LOCALES:
        return primary
    if raw.startswith("en"):
        return "en"
    return default


def detect_locale(query_lang=None, stored=None, accept_language=None):
    """Query string > stored preference > Accept-Language > default English."""
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
