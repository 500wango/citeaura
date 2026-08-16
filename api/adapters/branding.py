"""租户级白标交付配置与 HTML 模板。"""

import base64
import binascii
import html
import re
from pathlib import Path

from api.adapters.engine import geolib


BRANDING_FILENAME = ".delivery-branding.json"
MAX_LOGO_BYTES = 512 * 1024
LOGO_PATTERN = re.compile(r"^data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/=]+)$")
COLOR_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}$")
STYLE_START = "<!-- delivery-branding-style:start -->"
STYLE_END = "<!-- delivery-branding-style:end -->"
BODY_START = "<!-- delivery-branding-body:start -->"
BODY_END = "<!-- delivery-branding-body:end -->"


def default_branding():
    return {
        "enabled": False,
        "company_name": "",
        "logo_data_url": "",
        "accent_color": "#1F4E79",
        "footer_text": "",
    }


def _single_line(value, field, limit):
    value = str(value or "").strip()
    if len(value) > limit or any(character in value for character in "\r\n\x00"):
        raise ValueError(f"invalid {field}")
    return value


def _logo_data_url(value):
    value = str(value or "").strip()
    if not value:
        return ""
    match = LOGO_PATTERN.fullmatch(value)
    if not match:
        raise ValueError("logo must be a PNG, JPEG, or WebP data URL")
    try:
        raw = base64.b64decode(match.group(2), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("logo contains invalid base64 data") from exc
    if not raw or len(raw) > MAX_LOGO_BYTES:
        raise ValueError(f"logo must not exceed {MAX_LOGO_BYTES} bytes")
    image_type = match.group(1)
    valid = (
        image_type == "png" and raw.startswith(b"\x89PNG\r\n\x1a\n")
        or image_type == "jpeg" and raw.startswith(b"\xff\xd8\xff")
        or image_type == "webp" and len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP"
    )
    if not valid:
        raise ValueError("logo data does not match its image type")
    return value


def normalize_branding(value):
    """校验并收敛可写入租户目录的白标配置。"""
    if not isinstance(value, dict):
        raise ValueError("branding must be an object")
    config = {
        "enabled": bool(value.get("enabled", False)),
        "company_name": _single_line(value.get("company_name"), "company_name", 120),
        "logo_data_url": _logo_data_url(value.get("logo_data_url")),
        "accent_color": str(value.get("accent_color") or "#1F4E79").strip().upper(),
        "footer_text": _single_line(value.get("footer_text"), "footer_text", 240),
    }
    if not COLOR_PATTERN.fullmatch(config["accent_color"]):
        raise ValueError("accent_color must be #RRGGBB")
    if config["enabled"] and not config["company_name"]:
        raise ValueError("company_name is required when branding is enabled")
    return config


def branding_path():
    return Path(geolib.current_work()) / BRANDING_FILENAME


def load_branding():
    value = geolib.read_json(branding_path(), None)
    if value is None:
        return default_branding()
    try:
        return normalize_branding(value)
    except ValueError:
        return default_branding()


def save_branding(value):
    config = normalize_branding(value)
    geolib.write_json(branding_path(), config)
    return config


def delete_branding():
    path = branding_path()
    if path.exists():
        path.unlink()
    return default_branding()


def _without_branding(document):
    document = re.sub(
        re.escape(STYLE_START) + r".*?" + re.escape(STYLE_END) + r"\n?",
        "",
        document,
        flags=re.DOTALL,
    )
    return re.sub(
        r"\n?" + re.escape(BODY_START) + r".*?" + re.escape(BODY_END),
        "",
        document,
        flags=re.DOTALL,
    )


def _template(config):
    company_name = html.escape(config["company_name"])
    footer_text = html.escape(config["footer_text"] or config["company_name"])
    accent_color = config["accent_color"]
    logo = ""
    if config["logo_data_url"]:
        logo = (
            '<img class="delivery-branding-logo" alt="" src="'
            + html.escape(config["logo_data_url"], quote=True)
            + '">'
        )
    style = f"""{STYLE_START}
<style id="delivery-branding-style">
:root{{--delivery-branding-accent:{accent_color}}}
.delivery-branding-header{{display:flex;align-items:center;gap:12px;margin:0 auto 22px;padding:12px 0 10px;border-bottom:2px solid var(--delivery-branding-accent);max-width:920px;color:#1f2328}}
.delivery-branding-logo{{display:block;max-width:180px;max-height:34px;object-fit:contain}}
.delivery-branding-name{{font:600 14px/1.3 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:var(--delivery-branding-accent)}}
.delivery-branding-footer{{display:none;max-width:920px;margin:28px auto 0;padding:10px 0;border-top:1px solid #d9dce1;text-align:center;font:11px/1.4 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#68707d}}
@media print{{
  @page{{margin:22mm 14mm 18mm}}
  .delivery-branding-header{{position:fixed;top:-16mm;left:0;right:0;height:10mm;margin:0;max-width:none;padding:0 0 2mm;background:#fff;z-index:10}}
  .delivery-branding-footer{{display:block;position:fixed;bottom:-13mm;left:0;right:0;height:7mm;margin:0;max-width:none;padding:2mm 0 0;background:#fff;z-index:10}}
  .delivery-branding-logo{{max-height:7mm;max-width:45mm}}
  .delivery-branding-name{{font-size:9pt}}
}}
</style>
{STYLE_END}"""
    body = f"""{BODY_START}
<header class="delivery-branding-header" aria-label="Delivery brand">{logo}<span class="delivery-branding-name">{company_name}</span></header>
<footer class="delivery-branding-footer">{footer_text}</footer>
{BODY_END}"""
    return style, body


def _apply_to_document(document, config):
    document = _without_branding(document)
    if not config["enabled"]:
        return document
    head_match = re.search(r"</head\s*>", document, flags=re.IGNORECASE)
    if head_match is None:
        return document
    if not re.search(r"<body(?:\s[^>]*)?>", document, flags=re.IGNORECASE):
        return document
    style, body = _template(config)
    document = document[:head_match.start()] + style + "\n" + document[head_match.start():]
    body_match = re.search(r"<body(?:\s[^>]*)?>", document, flags=re.IGNORECASE)
    offset = body_match.end()
    return document[:offset] + "\n" + body + document[offset:]


def apply_delivery_branding(delivery_directory, config=None):
    """把当前租户白标模板应用到交付目录根级 HTML，重复调用不会叠加。"""
    directory = Path(delivery_directory)
    config = normalize_branding(config) if config is not None else load_branding()
    changed = 0
    for path in sorted(directory.glob("*.html")):
        current = path.read_text("utf-8")
        rendered = _apply_to_document(current, config)
        if rendered != current:
            path.write_text(rendered, "utf-8")
            changed += 1
    return changed
