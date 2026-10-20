"""市场与语言解析：市场决定引擎集，语言决定题库与报告文案。"""

SUPPORTED_LANGUAGES = ("en", "zh", "ja", "ko", "es", "fr", "de")
AUTO = "auto"

LANGUAGE_NAMES = {
    "en": "English",
    "zh": "Simplified Chinese",
    "ja": "Japanese",
    "ko": "Korean",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
}

MARKET_DEFAULT_LANGUAGE = {"cn": "zh", "global": "en", "both": "auto"}


def normalize_language(value, default=AUTO):
    text = str(value or "").strip().lower()
    if text in SUPPORTED_LANGUAGES or text == AUTO:
        return text
    return default


def normalize_market(value, default="global"):
    text = str(value or "").strip().lower()
    return text if text in ("cn", "global", "both") else default


def resolve_question_language(market, configured=AUTO):
    """把 auto 解析为项目级默认；both 市场保留逐题语言。"""
    language = normalize_language(configured)
    if language != AUTO:
        return language
    return MARKET_DEFAULT_LANGUAGE.get(normalize_market(market), "en")


def question_language(question, market, configured=AUTO):
    """单题语言：显式配置优先，其次题目市场，最后项目市场。"""
    language = normalize_language(configured)
    if language != AUTO:
        return language
    question_market = normalize_market((question or {}).get("market"), market)
    if question_market == "cn":
        return "zh"
    if question_market == "global":
        return "en"
    return MARKET_DEFAULT_LANGUAGE.get(normalize_market(market), "en")


def instruction(language):
    return LANGUAGE_NAMES.get(normalize_language(language), LANGUAGE_NAMES["en"])
