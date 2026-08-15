"""Publish approved content to configured destinations and record outcomes.

Credentials remain in .env. Every publishing action requires an explicit UI or
CLI command. WordPress and WeChat integrations create drafts only.
"""

from __future__ import annotations

import base64
import html
import json
import os
import re
from urllib.parse import urlparse

import requests

import geolib as G

# Destination registry: env contains secret names; cfg contains non-secret project settings.
PUBLISHERS = {
    "github": {
        "name": "GitHub Repository", "env": ["GITHUB_TOKEN"],
        "cfg": [("repo", "owner/repo"), ("branch", "main"), ("dir", "docs/geo")],
        "note": "Commit Markdown to the configured repository through the Contents API",
    },
    "wordpress": {
        "name": "WordPress", "env": ["WP_USER", "WP_APP_PASSWORD"],
        "cfg": [("site_url", "https://blog.example.com")],
        "note": "Create a draft post through the REST API for editorial review",
    },
    "wechat_draft": {
        "name": "WeChat Drafts", "env": ["WECHAT_APPID", "WECHAT_APPSECRET"],
        "cfg": [("thumb_media_id", "Permanent cover media_id required for drafts")],
        "note": "Create a draft for preview and manual distribution; server IP must be allowlisted",
    },
    "webhook": {
        "name": "Custom Webhook", "env": ["PUBLISH_WEBHOOK_URL"],
        "cfg": [],
        "note": "POST JSON {title, markdown, html, slug, path} to the configured receiver",
    },
}


def missing_env(code: str) -> list[str]:
    return [e for e in PUBLISHERS[code]["env"] if not os.environ.get(e)]


def _cfg(slug: str, code: str) -> dict:
    return (G.load_config(slug).get("publishing") or {}).get(code) or {}


# ---------------------------------------------------------------- markdown → html
# WeChat and WordPress require a minimal HTML conversion for draft preview.

def md2html(md: str) -> str:
    md = re.sub(r"<!--.*?-->", "", md, flags=re.S)
    out, in_code, in_list = [], False, False

    def inline(s):
        links = []

        def hold_link(match):
            label, href = match.group(1), match.group(2).strip()
            try:
                scheme = urlparse(href).scheme.lower()
            except ValueError:
                return label
            if scheme and scheme not in ("http", "https", "mailto"):
                return label
            token = f"\x00LINK{len(links)}\x00"
            links.append((token, label, href))
            return token

        s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", hold_link, s)
        s = html.escape(s)
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        for token, label, href in links:
            s = s.replace(token, f'<a href="{html.escape(href, quote=True)}">{html.escape(label)}</a>')
        return s

    for line in md.splitlines():
        if line.strip().startswith("```"):
            out.append("</code></pre>" if in_code else "<pre><code>")
            in_code = not in_code
            continue
        if in_code:
            out.append(html.escape(line))
            continue
        m = re.match(r"(#{1,6})\s+(.*)", line)
        li = re.match(r"\s*[-*]\s+(.*)", line) or re.match(r"\s*\d+[.、]\s+(.*)", line)
        if in_list and not li:
            out.append("</ul>")
            in_list = False
        if m:
            n = min(len(m.group(1)) + 1, 6)
            out.append(f"<h{n}>{inline(m.group(2))}</h{n}>")
        elif li:
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{inline(li.group(1))}</li>")
        elif line.strip():
            out.append(f"<p>{inline(line.strip())}</p>")
    if in_list:
        out.append("</ul>")
    if in_code:
        out.append("</code></pre>")
    return "\n".join(out)


# ---------------------------------------------------------------- Destination implementations

def _pub_github(cfg, text, title, fname):
    repo, branch = cfg.get("repo", ""), cfg.get("branch", "main")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        return {"ok": False, "error": "Configure repo as owner/repo first"}
    remote_dir = cfg.get("dir", "").strip("/")
    if any(part in ("", ".", "..") for part in remote_dir.split("/")) and remote_dir:
        return {"ok": False, "error": "Configure dir as a repository-relative path"}
    path = (remote_dir + "/" + fname).lstrip("/")
    H = {"Authorization": "Bearer " + os.environ["GITHUB_TOKEN"],
         "Accept": "application/vnd.github+json"}
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    body = {"message": f"geo: publish {title}", "branch": branch,
            "content": base64.b64encode(text.encode()).decode()}
    r0 = requests.get(url, headers=H, params={"ref": branch}, timeout=30)
    if r0.status_code == 200:
        body["sha"] = r0.json().get("sha")
    r = requests.put(url, headers=H, json=body, timeout=30)
    if r.status_code in (200, 201):
        return {"ok": True, "url": r.json().get("content", {}).get("html_url", "")}
    return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:200]}"}


def _pub_wordpress(cfg, text, title, fname):
    site = (cfg.get("site_url") or "").rstrip("/")
    if not site:
        return {"ok": False, "error": "Configure site_url first"}
    r = requests.post(f"{site}/wp-json/wp/v2/posts",
                      auth=(os.environ["WP_USER"], os.environ["WP_APP_PASSWORD"]),
                      json={"title": title, "content": md2html(text), "status": "draft"},
                      timeout=30)
    if r.status_code == 201:
        return {"ok": True, "url": r.json().get("link", ""),
                "note": "Draft created; review and publish it in WordPress"}
    return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:200]}"}


def _pub_wechat(cfg, text, title, fname):
    thumb = cfg.get("thumb_media_id", "")
    if not thumb:
        return {"ok": False, "error": "Configure a permanent cover thumb_media_id first"}
    tr = requests.get("https://api.weixin.qq.com/cgi-bin/token",
                      params={"grant_type": "client_credential",
                              "appid": os.environ["WECHAT_APPID"],
                              "secret": os.environ["WECHAT_APPSECRET"]}, timeout=30).json()
    tok = tr.get("access_token")
    if not tok:
        return {"ok": False, "error": f"Token request failed: {tr.get('errmsg', tr)}"}
    art = {"title": title[:60], "content": md2html(text), "thumb_media_id": thumb,
           "digest": re.sub(r"\s+", " ", text)[:100]}
    r = requests.post(f"https://api.weixin.qq.com/cgi-bin/draft/add?access_token={tok}",
                      data=json.dumps({"articles": [art]}, ensure_ascii=False).encode(),
                      timeout=30).json()
    if r.get("media_id"):
        return {"ok": True, "url": "", "note": "Draft created; preview and distribute it in WeChat"}
    return {"ok": False, "error": f"draft/add failed: {r.get('errmsg', r)}"}


def _pub_webhook(cfg, text, title, fname):
    r = requests.post(os.environ["PUBLISH_WEBHOOK_URL"],
                      json={"title": title, "markdown": text, "html": md2html(text),
                            "path": fname}, timeout=30)
    if 200 <= r.status_code < 300:
        url = ""
        try:
            url = (r.json() or {}).get("url", "")
        except Exception:  # noqa: BLE001 - a successful receiver may return no JSON
            pass
        return {"ok": True, "url": url}
    return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:200]}"}


_IMPL = {"github": _pub_github, "wordpress": _pub_wordpress,
         "wechat_draft": _pub_wechat, "webhook": _pub_webhook}


# ---------------------------------------------------------------- Entry point and records

def _read_source(slug: str, rel: str) -> tuple[str, str]:
    """Read a source confined to content/ or assets/ and return text and name."""
    pdir = G.project_dir(slug).resolve()
    target = (pdir / rel).resolve()
    if not any(target.is_relative_to(pdir / d) for d in ("content", "assets")):
        raise ValueError("Only files under content/ or assets/ can be published")
    return target.read_text("utf-8"), target.name


def _title_of(text: str, fname: str) -> str:
    m = re.search(r"^#\s+(.+)$", text, re.M)
    return m.group(1).strip() if m else fname.rsplit(".", 1)[0]


def records(slug: str) -> list[dict]:
    return G.read_json(G.project_dir(slug) / "publish.json", []) or []


def publish(slug: str, code: str, rel: str, title: str = "") -> dict:
    if code not in PUBLISHERS:
        return {"ok": False, "error": f"Unknown destination: {code}"}
    miss = missing_env(code)
    if miss:
        return {"ok": False, "error": "Missing credentials: " + ", ".join(miss)}
    try:
        text, fname = _read_source(slug, rel)
    except (OSError, RuntimeError, ValueError):
        return {"ok": False, "error": f"File unavailable: {rel}"}
    title = title or _title_of(text, fname)
    try:
        res = _IMPL[code](_cfg(slug, code), text, title, fname)
    except requests.RequestException:
        return {"ok": False, "error":
                "Publishing destination request failed; check URL, credentials, and network connectivity"}
    entry = {"at": G.now_iso(), "platform": code, "platform_name": PUBLISHERS[code]["name"],
             "path": rel, "title": title, "ok": res.get("ok", False),
             "url": res.get("url", ""), "note": res.get("note", ""),
             "error": res.get("error", "")}
    rows = records(slug)
    rows.append(entry)
    G.write_json(G.project_dir(slug) / "publish.json", rows[-200:])
    return {**res, "record": entry}
