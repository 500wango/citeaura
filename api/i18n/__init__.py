"""CiteAura product i18n: English-only product locale with English fallback."""

from api.i18n.catalog import catalogs_as_json, clear_catalog_cache, load_all_catalogs, resolve
from api.i18n.locales import (
    DEFAULT_LOCALE,
    LOCALE_HTML_LANG,
    LOCALE_LABELS,
    SUPPORTED_LOCALES,
    detect_locale,
    normalize_locale,
)

__all__ = [
    "DEFAULT_LOCALE",
    "LOCALE_HTML_LANG",
    "LOCALE_LABELS",
    "SUPPORTED_LOCALES",
    "catalogs_as_json",
    "clear_catalog_cache",
    "detect_locale",
    "load_all_catalogs",
    "normalize_locale",
    "resolve",
]
