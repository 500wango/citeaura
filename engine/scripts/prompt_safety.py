"""不可信文本隔离与 LLM JSON 结构校验。"""

import re
import secrets

ZERO_WIDTH = re.compile(r"[​-‏‪-‮⁠﻿]")
COMMENTS = re.compile(r"<!--.*?-->", re.S)
UNTRUSTED_TAGS = re.compile(r"</?\s*(untrusted[^>\s]*|system|instructions?)\b[^>]*>", re.I)


def sanitize_untrusted_text(text, limit=None):
    """剥离可闭合边界、注释与零宽字符，保留正文。"""
    value = str(text or "")
    value = COMMENTS.sub(" ", value)
    value = UNTRUSTED_TAGS.sub(" ", value)
    value = ZERO_WIDTH.sub("", value)
    if limit is not None:
        value = value[: int(limit)]
    return value


def wrap_untrusted(text, tag="untrusted_website_content", limit=None):
    """用随机 nonce 边界包裹不可信内容，内容无法伪造闭合标签。"""
    nonce = secrets.token_hex(8)
    boundary = f"{tag}_{nonce}"
    body = sanitize_untrusted_text(text, limit=limit)
    return f"<{boundary}>\n{body}\n</{boundary}>"


_JSON_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "number": (int, float),
    "boolean": bool,
}


def _check(value, schema, path):
    kind = schema.get("type")
    expected = _JSON_TYPES.get(kind)
    if expected is not None and not isinstance(value, expected):
        return [f"{path}: expected {kind}"]
    if isinstance(value, bool) and kind in ("number", "string"):
        return [f"{path}: expected {kind}"]
    problems = []
    if kind == "object":
        for key in schema.get("required") or ():
            if key not in value:
                problems.append(f"{path}.{key}: missing")
        for key, child in (schema.get("properties") or {}).items():
            if key in value:
                problems.extend(_check(value[key], child, f"{path}.{key}"))
    if kind == "array" and schema.get("items"):
        for index, item in enumerate(value[:20]):
            problems.extend(_check(item, schema["items"], f"{path}[{index}]"))
    return problems


def validate_json_schema(value, schema):
    """返回问题列表；空列表表示结构符合预期。"""
    if schema is None:
        return []
    return _check(value, schema, "$")


BRAND_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "industry": {"type": "string"},
        "definition": {"type": "string"},
        "key_numbers": {"type": "array", "items": {"type": "object", "properties": {
            "fact": {"type": "string"}, "value": {"type": "string"}, "source": {"type": "string"},
        }}},
        "pricing": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"}, "price": {"type": "string"},
            "currency": {"type": "string"}, "desc": {"type": "string"},
        }}},
        "aliases": {"type": "array", "items": {"type": "string"}},
    },
}

QUESTION_SCHEMA = {
    "type": "object",
    "required": ["questions"],
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["text"],
                "properties": {
                    "id": {"type": "string"},
                    "group": {"type": "string"},
                    "market": {"type": "string"},
                    "text": {"type": "string"},
                },
            },
        },
    },
}

COMPETITOR_SCHEMA = {
    "type": "object",
    "required": ["competitors"],
    "properties": {
        "competitors": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {"type": "string"},
                    "aliases": {"type": "array", "items": {"type": "string"}},
                    "market": {"type": "string"},
                },
            },
        },
    },
}
