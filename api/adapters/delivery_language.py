"""交付包 English-only 语言门禁。"""

import html
import json
import re
from pathlib import Path

from api.adapters.exceptions import GeoEngineError


HAN_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U0002fa1f]")
CJK_TYPOGRAPHY_PATTERN = re.compile(
    r"[\u3000-\u303f\ufe10-\ufe1f\ufe30-\ufe4f\uff01-\uff65\uffe0-\uffe6]"
)
UNICODE_ESCAPE_PATTERN = re.compile(r"\\u([0-9a-fA-F]{4})")
LONG_UNICODE_ESCAPE_PATTERN = re.compile(r"\\U([0-9a-fA-F]{8})")
SURROGATE_PAIR_PATTERN = re.compile(r"[\ud800-\udbff][\udc00-\udfff]")
SURROGATE_PATTERN = re.compile(r"[\ud800-\udfff]")
TEXT_SUFFIXES = frozenset((".md", ".html", ".csv", ".json", ".txt", ".xml", ".js", ".css"))


def _decoded_text(value):
    text = str(value or "")
    for _ in range(3):
        decoded = html.unescape(text)
        if decoded == text:
            break
        text = decoded

    def decode_long_escape(match):
        codepoint = int(match.group(1), 16)
        return chr(codepoint) if codepoint <= 0x10FFFF else match.group(0)

    text = LONG_UNICODE_ESCAPE_PATTERN.sub(decode_long_escape, text)
    text = UNICODE_ESCAPE_PATTERN.sub(lambda match: chr(int(match.group(1), 16)), text)
    text = SURROGATE_PAIR_PATTERN.sub(
        lambda match: chr(
            0x10000
            + (ord(match.group(0)[0]) - 0xD800) * 0x400
            + ord(match.group(0)[1])
            - 0xDC00
        ),
        text,
    )
    return text


def _contains_han(value):
    return bool(HAN_PATTERN.search(_decoded_text(value)))


def _contains_disallowed_english(value):
    text = _decoded_text(value)
    return bool(
        HAN_PATTERN.search(text)
        or CJK_TYPOGRAPHY_PATTERN.search(text)
        or SURROGATE_PATTERN.search(text)
    )


def _json_language_violation(value):
    if isinstance(value, dict):
        return any(
            _contains_disallowed_english(key) or _json_language_violation(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_json_language_violation(item) for item in value)
    return isinstance(value, str) and _contains_disallowed_english(value)


def delivery_language_violations(delivery_directory):
    """Return paths containing Han text or unnormalized CJK/fullwidth typography."""
    directory = Path(delivery_directory)
    violations = set()
    for path in sorted(directory.rglob("*")):
        relative = path.relative_to(directory)
        if any(_contains_disallowed_english(part) for part in relative.parts):
            violations.add(relative.as_posix())
        if not path.is_file():
            continue
        try:
            text = path.read_text("utf-8")
        except UnicodeDecodeError:
            if path.suffix.lower() in TEXT_SUFFIXES:
                violations.add(relative.as_posix())
            continue
        if _contains_disallowed_english(text):
            violations.add(relative.as_posix())
            continue
        if path.suffix.lower() == ".json":
            try:
                value = json.loads(text)
            except json.JSONDecodeError:
                violations.add(relative.as_posix())
                continue
            if _json_language_violation(value):
                violations.add(relative.as_posix())
    return sorted(violations)


def validate_delivery_language(delivery_directory):
    """Reject a package if any path or decoded text violates the English contract."""
    violations = delivery_language_violations(delivery_directory)
    if violations:
        raise GeoEngineError("delivery contains non-English content: " + ", ".join(violations))
    return Path(delivery_directory)
