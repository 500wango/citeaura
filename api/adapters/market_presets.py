"""市场预设：市场决定引擎范围，语言决定题库文案。"""

MARKETS = ("cn", "global", "both")
QUESTION_LANGUAGES = ("auto", "en", "zh", "ja", "ko", "es", "fr", "de")
REPORT_LANGUAGES = ("en",)

DEFAULT_QUESTION_LANGUAGE = {"cn": "zh", "global": "en", "both": "auto"}


def normalize_market(value, default="global"):
    text = str(value or "").strip().lower()
    return text if text in MARKETS else default


def normalize_question_language(value, default="auto"):
    text = str(value or "").strip().lower()
    return text if text in QUESTION_LANGUAGES else default


def default_question_language(market):
    return DEFAULT_QUESTION_LANGUAGE.get(normalize_market(market), "en")


def preset(market):
    market = normalize_market(market)
    return {
        "market": market,
        "question_language": default_question_language(market),
        "report_language": "en",
    }
