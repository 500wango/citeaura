"""多语言消息目录：locale 平等，en 为缺失回退。"""

import json
from functools import lru_cache
from pathlib import Path

from api.i18n.locales import DEFAULT_LOCALE, SUPPORTED_LOCALES, normalize_locale

MESSAGES_DIR = Path(__file__).resolve().parent / "messages"


@lru_cache(maxsize=1)
def load_all_catalogs():
    """加载全部 locale JSON，返回 {locale: {id: text}}。"""
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
    """按 locale → en → id 解析文案。中文不是非 zh 语言的回退。"""
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
    if locale != DEFAULT_LOCALE:
        english = catalogs.get(DEFAULT_LOCALE) or {}
        if key in english:
            return english[key]
    # zh 下允许把未登记的中文 id 原样显示；其它语言不再回退到中文
    return key


def translate_map(entries, locale=DEFAULT_LOCALE, catalogs=None):
    """entries: {source_zh_or_id: {en, ja, ...}} → 解析后的字符串。"""
    if not entries:
        return {}
    locale = normalize_locale(locale)
    catalogs = catalogs or load_all_catalogs()
    result = {}
    for key, mapping in entries.items():
        if isinstance(mapping, dict):
            if locale in mapping and mapping[locale]:
                result[key] = mapping[locale]
            elif DEFAULT_LOCALE in mapping and mapping[DEFAULT_LOCALE]:
                result[key] = mapping[DEFAULT_LOCALE]
            else:
                result[key] = resolve(key, locale, catalogs)
        else:
            result[key] = resolve(key, locale, catalogs)
    return result


def catalogs_as_json():
    """供前端注入的完整目录。"""
    return json.dumps(load_all_catalogs(), ensure_ascii=False, separators=(",", ":"))
