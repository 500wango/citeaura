"""Product message catalogs with explicit locale completeness."""

import json
from functools import lru_cache
from pathlib import Path

from api.i18n.locales import DEFAULT_LOCALE, SUPPORTED_LOCALES, normalize_locale

MESSAGES_DIR = Path(__file__).resolve().parent / "messages"


@lru_cache(maxsize=1)
def load_all_catalogs():
    """Load all supported locale JSON catalogs as {locale: {id: text}}."""
    catalogs = {}
    for locale in SUPPORTED_LOCALES:
        path = MESSAGES_DIR / f"{locale}.json"
        if not path.exists():
            catalogs[locale] = {}
            continue
        data = json.loads(path.read_text("utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"i18n catalog {path} must be a JSON object")
        catalogs[locale] = {str(key): str(value) for key, value in data.items()}
    return catalogs


def clear_catalog_cache():
    load_all_catalogs.cache_clear()


def resolve(message_id, locale=DEFAULT_LOCALE, catalogs=None):
    """Resolve copy for one locale without hiding a missing translation."""
    if message_id is None:
        return message_id
    key = str(message_id)
    if key == "":
        return key
    locale = normalize_locale(locale)
    catalogs = catalogs or load_all_catalogs()
    current = catalogs.get(locale) or {}
    if key in current:
        return current[key]
    return key


def translate_map(entries, locale=DEFAULT_LOCALE, catalogs=None):
    """Resolve mapping entries like {source_id: {en: text}} for one locale."""
    if not entries:
        return {}
    locale = normalize_locale(locale)
    catalogs = catalogs or load_all_catalogs()
    result = {}
    for key, mapping in entries.items():
        if isinstance(mapping, dict):
            if locale in mapping and mapping[locale]:
                result[key] = mapping[locale]
            elif locale == DEFAULT_LOCALE and mapping.get(DEFAULT_LOCALE):
                result[key] = mapping[DEFAULT_LOCALE]
            else:
                # A non-English locale must not silently inherit English copy.
                # Returning the stable message id keeps the gap visible to the
                # caller and to the catalog completeness checks.
                result[key] = resolve(key, locale, catalogs)
        else:
            result[key] = resolve(key, locale, catalogs)
    return result


def catalogs_as_json():
    """Return all catalogs as JSON for frontend injection."""
    return json.dumps(load_all_catalogs(), ensure_ascii=False, separators=(",", ":"))
