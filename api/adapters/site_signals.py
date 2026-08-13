"""Validate website-level discovery assets before downstream engine steps consume them."""

import re
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from urllib.parse import urljoin, urlparse

import requests

from api.adapters.engine import geolib
from api.adapters.network import NetworkTargetError, validate_outbound_url


MAX_SIGNAL_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 3
HTML_MARKERS = re.compile(r"(?is)<\s*(?:!doctype\s+html|html|head|body|script|div)\b")


def _same_site(source, target):
    source_host = (urlparse(source).hostname or "").lower().removeprefix("www.")
    target_host = (urlparse(target).hostname or "").lower().removeprefix("www.")
    return bool(source_host and target_host) and (
        source_host == target_host
        or source_host.endswith("." + target_host)
        or target_host.endswith("." + source_host)
    )


def _result(valid, reason, response=None, **extra):
    value = {
        "valid": bool(valid),
        "reason": reason,
        "status": getattr(response, "status_code", 0) if response is not None else 0,
        "content_type": str((getattr(response, "headers", {}) or {}).get("Content-Type", "")).split(";", 1)[0],
        "final_url": str(getattr(response, "url", "") or ""),
    }
    value.update(extra)
    return value


def validate_llms_response(response, root_url):
    """Accept only a same-site, meaningful plain-text facts index."""
    if response.status_code != 200:
        return _result(False, "http_status", response)
    if not _same_site(root_url, response.url):
        return _result(False, "cross_site_redirect", response)
    text = str(response.text or "").strip()
    if HTML_MARKERS.search(text):
        return _result(False, "html_fallback", response)
    content_type = str(response.headers.get("Content-Type", "")).lower()
    if not any(item in content_type for item in ("text/plain", "text/markdown")):
        return _result(False, "wrong_content_type", response)
    meaningful_lines = [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("<!--")]
    has_structure = any(line.startswith("#") for line in meaningful_lines) or sum(
        line.startswith(("- ", "* ")) for line in meaningful_lines
    ) >= 2
    if len(text) < 80 or len(meaningful_lines) < 3 or not has_structure:
        return _result(False, "insufficient_content", response, character_count=len(text))
    return _result(True, "valid", response, character_count=len(text))


def validate_sitemap_response(response, root_url):
    """Accept only a same-site XML sitemap containing at least one loc entry."""
    if response.status_code != 200:
        return _result(False, "http_status", response, url_count=0)
    if not _same_site(root_url, response.url):
        return _result(False, "cross_site_redirect", response, url_count=0)
    content_type = str(response.headers.get("Content-Type", "")).lower()
    if not any(item in content_type for item in ("xml", "text/plain")):
        reason = "html_fallback" if "html" in content_type else "wrong_content_type"
        return _result(False, reason, response, url_count=0)
    text = str(response.text or "").strip()
    if HTML_MARKERS.search(text):
        return _result(False, "html_fallback", response, url_count=0)
    try:
        document = ET.fromstring(text)
    except (ET.ParseError, ValueError):
        return _result(False, "invalid_xml", response, url_count=0)
    root_name = document.tag.rsplit("}", 1)[-1].lower()
    if root_name not in ("urlset", "sitemapindex"):
        return _result(False, "invalid_root", response, url_count=0)
    locations = [
        str(node.text or "").strip()
        for node in document.iter()
        if node.tag.rsplit("}", 1)[-1].lower() == "loc" and str(node.text or "").strip()
    ]
    if not locations:
        return _result(False, "empty_sitemap", response, url_count=0)
    return _result(True, "valid", response, url_count=len(locations))


def _fetch(url, timeout=10):
    try:
        current = validate_outbound_url(url, require_https=False)
        response = None
        for _redirect in range(MAX_REDIRECTS + 1):
            response = requests.get(
                current,
                timeout=timeout,
                headers={"User-Agent": geolib.UA, "Accept": "text/plain, application/xml, text/xml;q=0.9"},
                allow_redirects=False,
                stream=True,
            )
            if response.status_code not in (301, 302, 303, 307, 308):
                break
            location = response.headers.get("Location")
            if not location:
                break
            redirected = urljoin(current, location)
            response.close()
            if not _same_site(url, redirected):
                raise NetworkTargetError("network_cross_site_redirect")
            current = validate_outbound_url(redirected, require_https=False)
        else:
            raise NetworkTargetError("network_redirect_limit")
        chunks = []
        size = 0
        for chunk in response.iter_content(65536):
            chunks.append(chunk)
            size += len(chunk)
            if size >= MAX_SIGNAL_BYTES:
                break
        response._content = b"".join(chunks)[:MAX_SIGNAL_BYTES]
        response._content_consumed = True
        return response
    except (NetworkTargetError, requests.RequestException) as exc:
        return exc


def _fetch_result(url, root_url, validator):
    response = _fetch(url)
    if isinstance(response, (NetworkTargetError, requests.RequestException)):
        return {
            "valid": False,
            "reason": "network_target_rejected" if isinstance(response, NetworkTargetError) else "request_failed",
            "status": 0,
            "content_type": "",
            "final_url": url,
            "error_type": type(response).__name__,
        }
    try:
        return validator(response, root_url)
    finally:
        response.close()


def validate_project_signals(project_slug):
    """Re-check sitemap and llms.txt semantics and persist the verdict in site evidence."""
    directory = geolib.project_dir(project_slug)
    site_path = directory / "evidence" / "site.json"
    site = geolib.read_json(site_path, {}) or {}
    config = geolib.load_config(project_slug)
    root = str(site.get("root") or ((config.get("brand") or {}).get("site")) or "").rstrip("/")
    if not root:
        return site
    llms = _fetch_result(urljoin(root + "/", "llms.txt"), root, validate_llms_response)
    sitemap = _fetch_result(urljoin(root + "/", "sitemap.xml"), root, validate_sitemap_response)
    site.update({
        "has_llms_txt": llms["valid"],
        "has_sitemap": sitemap["valid"],
        "sitemap_url_count": sitemap.get("url_count", 0),
        "signal_validation": {
            "validated_at": geolib.now_iso(),
            "llms_txt": llms,
            "sitemap": sitemap,
        },
    })
    geolib.write_json(site_path, site)
    return site


@contextmanager
def semantic_site_signals(project_slug):
    """Validate crawl outputs immediately, before audit/tasks/report consume site.json."""
    import crawl as engine_crawl

    original_run = engine_crawl.run

    def run_with_validation(slug, *args, **kwargs):
        result = original_run(slug, *args, **kwargs)
        return validate_project_signals(project_slug) if slug == project_slug else result

    engine_crawl.run = run_with_validation
    try:
        yield
    finally:
        engine_crawl.run = original_run
