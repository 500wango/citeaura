"""发布渠道的租户配置与引擎调用适配。"""

import re
import os
from urllib.parse import urlparse

import requests

from api.adapters.engine import geolib
from api.adapters.network import NetworkTargetError, validate_outbound_url


CREDENTIAL_PREFIX = "publisher:"
_REQUIRED_CONFIG = {
    "github": ("repo",),
    "wordpress": ("site_url",),
    "wechat_draft": ("thumb_media_id",),
    "webhook": (),
}


def _engine_publish():
    import publish

    return publish


def platforms():
    """返回引擎支持的发布渠道代码。"""
    return tuple(_engine_publish().PUBLISHERS)


def credential_code(platform, env_name):
    """生成数据库中的发布凭证键。"""
    spec = _publisher(platform)
    if env_name not in spec["env"]:
        raise ValueError(f"unsupported credential for {platform}: {env_name}")
    return f"{CREDENTIAL_PREFIX}{platform}:{env_name}"


def credential_map(platform):
    """返回存储键到运行时环境变量名的映射。"""
    spec = _publisher(platform)
    return {credential_code(platform, env_name): env_name for env_name in spec["env"]}


def _publisher(platform):
    publishers = _engine_publish().PUBLISHERS
    if platform not in publishers:
        raise ValueError(f"unsupported publishing platform: {platform}")
    return publishers[platform]


def _clean_url(value, field):
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError(f"{field} must be a valid http(s) URL")
    if parsed.username or parsed.password:
        raise ValueError(f"{field} must not contain credentials")
    if parsed.query or parsed.fragment:
        raise ValueError(f"{field} must not contain a query or fragment")
    try:
        validate_outbound_url(value, require_https=True, resolve=False)
    except NetworkTargetError as exc:
        raise ValueError(f"{field} must point to a public HTTPS host") from exc
    return value.rstrip("/")


def _public_url(value):
    value = str(value or "").strip()
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        return ""
    try:
        validate_outbound_url(value, require_https=True, resolve=False)
    except NetworkTargetError:
        return ""
    return value


def _clean_record(record):
    if not isinstance(record, dict):
        return {}
    return {**record, "url": _public_url(record.get("url"))}


def validate_config(platform, values):
    """按引擎渠道注册表校验非敏感配置。"""
    spec = _publisher(platform)
    allowed = {key for key, _ in spec["cfg"]}
    if not isinstance(values, dict):
        raise ValueError("publisher config must be an object")
    unknown = sorted(set(values) - allowed)
    if unknown:
        raise ValueError("unsupported publisher config: " + ", ".join(unknown))

    cleaned = {}
    for key in allowed:
        value = str(values.get(key) or "").strip()
        if len(value) > 2048 or "\n" in value or "\r" in value:
            raise ValueError(f"invalid publisher config: {key}")
        cleaned[key] = value

    if platform == "github":
        repo = cleaned.get("repo", "")
        if repo and not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
            raise ValueError("repo must use owner/repo format")
        branch = cleaned.get("branch", "")
        if branch and (branch.startswith("-") or not re.fullmatch(r"[A-Za-z0-9._/-]+", branch)):
            raise ValueError("invalid GitHub branch")
        directory = cleaned.get("dir", "").strip("/")
        if directory and any(part in ("", ".", "..") for part in directory.split("/")):
            raise ValueError("invalid GitHub directory")
        cleaned["dir"] = directory
    elif platform == "wordpress" and cleaned.get("site_url"):
        cleaned["site_url"] = _clean_url(cleaned["site_url"], "site_url")
    return cleaned


def validate_credentials(platform, values):
    """校验渠道凭证，避免把服务端请求地址当作普通密钥保存。"""
    _publisher(platform)
    if not isinstance(values, dict):
        raise ValueError("publisher credentials must be an object")
    for env_name, value in values.items():
        if value is None:
            continue
        if platform == "webhook" and env_name == "PUBLISH_WEBHOOK_URL":
            try:
                validate_outbound_url(value, require_https=True, resolve=False)
            except NetworkTargetError as exc:
                raise ValueError("webhook URL must point to a public HTTPS host") from exc
    return values


def save_config(project_slug, platform, values):
    """把渠道非敏感配置写回项目 geo.json。"""
    cleaned = validate_config(platform, values)
    with geolib.project_lock(project_slug):
        config = geolib.load_config(project_slug)
        publishing = config.get("publishing")
        if not isinstance(publishing, dict):
            publishing = {}
        publishing[platform] = cleaned
        config["publishing"] = publishing
        geolib.save_config(project_slug, config)
    return cleaned


PUBLISHER_NAMES_EN = {
    "github": "GitHub Repository",
    "wordpress": "WordPress",
    "wechat_draft": "WeChat Official Account Drafts",
    "webhook": "Custom Webhook",
}

PUBLISHER_NOTES_EN = {
    "github": "Submit Markdown to your repository via Contents API (deploys instantly with GitHub Pages or static site generators).",
    "wordpress": "Create draft posts via REST API; review and publish from your WordPress admin console.",
    "wechat_draft": "Create drafts in WeChat Official Account for editorial review and broadcast; server IP must be whitelisted.",
    "webhook": "POST JSON payload {title, markdown, html, slug, path} to your custom webhook endpoint.",
}

HINT_MAP_EN = {
    "永久素材封面 media_id（草稿必需）": "Permanent cover image media_id (required for drafts)",
}


def overview(project_slug, configured_codes):
    """返回脱敏后的渠道状态和发布记录。"""
    engine_publish = _engine_publish()
    config = geolib.load_config(project_slug)
    publishing = config.get("publishing") if isinstance(config.get("publishing"), dict) else {}
    configured_codes = set(configured_codes)
    items = []
    for platform, spec in engine_publish.PUBLISHERS.items():
        current = publishing.get(platform) if isinstance(publishing.get(platform), dict) else {}
        missing = [
            env_name
            for env_name in spec["env"]
            if credential_code(platform, env_name) not in configured_codes
        ]
        missing.extend(key for key in _REQUIRED_CONFIG[platform] if not current.get(key))
        items.append({
            "code": platform,
            "name": spec["name"],
            "name_en": PUBLISHER_NAMES_EN.get(platform, spec["name"]),
            "env": list(spec["env"]),
            "cfg": [
                {
                    "key": key,
                    "hint": hint,
                    "hint_en": HINT_MAP_EN.get(hint, hint),
                    "value": str(current.get(key) or ""),
                }
                for key, hint in spec["cfg"]
            ],
            "note": spec["note"],
            "note_en": PUBLISHER_NOTES_EN.get(platform, spec["note"]),
            "missing": missing,
            "ready": not missing,
        })
    records = engine_publish.records(project_slug)
    if not isinstance(records, list):
        records = []
    return {"publishers": items, "records": [_clean_record(record) for record in records]}


def publish(project_slug, platform, path, title=""):
    """调用引擎发布实现；调用方负责注入本租户凭证。"""
    _publisher(platform)
    try:
        if platform == "wordpress":
            validate_outbound_url(
                (geolib.load_config(project_slug).get("publishing") or {}).get(platform, {}).get("site_url"),
                require_https=True,
            )
        elif platform == "webhook":
            validate_outbound_url(os.environ.get("PUBLISH_WEBHOOK_URL"), require_https=True)
    except NetworkTargetError as exc:
        raise ValueError("publishing_target_blocked") from exc
    try:
        result = _engine_publish().publish(project_slug, platform, path, title)
    except requests.RequestException:
        return {"ok": False, "error": "Publishing destination request failed; check URL, credentials, and network connectivity"}
    if not isinstance(result, dict):
        return {"ok": False, "error": "Publishing destination returned an invalid response"}
    cleaned = dict(result)
    if "url" in cleaned:
        cleaned["url"] = _public_url(cleaned["url"])
    if "record" in cleaned:
        cleaned["record"] = _clean_record(cleaned["record"])
    return cleaned
