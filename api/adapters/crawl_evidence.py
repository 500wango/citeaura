"""抓取证据的 URL 规范化和重复页面归并。"""

import hashlib
import re
import unicodedata
from copy import deepcopy
from urllib.parse import urljoin, urlparse, urlunparse

from api.adapters.engine import geolib


HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def contains_han(value):
    return bool(HAN.search(str(value or "")))


def normalize_evidence_url(value, base=""):
    value = str(value or "").strip()
    if not value:
        return ""
    try:
        parsed = urlparse(urljoin(base, value))
        if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
            return ""
        port = parsed.port
    except ValueError:
        return ""
    host = parsed.hostname.lower().rstrip(".")
    if port and not (parsed.scheme.lower() == "http" and port == 80) and not (
        parsed.scheme.lower() == "https" and port == 443
    ):
        host = f"{host}:{port}"
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    return urlunparse((parsed.scheme.lower(), host, path, "", parsed.query, ""))


def _page_text_fingerprint(page):
    text = unicodedata.normalize("NFKC", str(page.get("text") or ""))
    text = " ".join(text.split()).casefold()
    return hashlib.sha256(text.encode("utf-8")).hexdigest() if text else ""


def _page_canonical(page):
    page_url = normalize_evidence_url(page.get("final_url") or page.get("url"))
    canonical = normalize_evidence_url(page.get("canonical"), page_url)
    if not canonical or not page_url or not geolib.same_site(page_url, canonical):
        return ""
    return canonical


def _page_path_family(page):
    url = normalize_evidence_url(page.get("final_url") or page.get("url"))
    if not url:
        return ""
    parsed = urlparse(url)
    return f"{parsed.netloc}{parsed.path}"


def _duplicate_page(left, right):
    left_fingerprint = _page_text_fingerprint(left)
    right_fingerprint = _page_text_fingerprint(right)
    same_content = bool(left_fingerprint and left_fingerprint == right_fingerprint)
    left_canonical = _page_canonical(left)
    right_canonical = _page_canonical(right)
    if left_canonical and left_canonical == right_canonical:
        if left_fingerprint and right_fingerprint and not same_content:
            return False
        return True
    return bool(
        same_content
        and _page_path_family(left)
        and _page_path_family(left) == _page_path_family(right)
    )


def _page_preference(page):
    url = normalize_evidence_url(page.get("url"))
    parsed = urlparse(url) if url else None
    text = str(page.get("text") or "").strip()
    return (
        int(page.get("status") == 200),
        int(bool(text)),
        int(bool(parsed) and not parsed.query),
        int(bool(url) and url == _page_canonical(page)),
        int(page.get("word_count") or 0),
        len(text),
        -len(url),
    )


def deduplicate_crawl_pages(pages):
    """只合并 canonical/正文等价的抓取记录，并保留原 URL 别名。"""
    groups = []
    for page in pages if isinstance(pages, list) else []:
        if not isinstance(page, dict):
            continue
        for group in groups:
            if all(_duplicate_page(page, member) for member in group):
                group.append(page)
                break
        else:
            groups.append([page])

    deduplicated = []
    for group in groups:
        representative = max(group, key=_page_preference)
        item = deepcopy(representative)
        aliases = []
        for member in group:
            existing_aliases = member.get("duplicate_urls") or []
            if not isinstance(existing_aliases, list):
                existing_aliases = [existing_aliases]
            values = [member.get("url"), *existing_aliases]
            for value in values:
                value = str(value or "").strip()
                if value and value != item.get("url") and value not in aliases:
                    aliases.append(value)
        if aliases:
            item["duplicate_urls"] = aliases
        else:
            item.pop("duplicate_urls", None)
        deduplicated.append(item)
    return deduplicated


def deduplicate_crawl_evidence(project_slug):
    """审计前去重抓取证据，确保所有聚合都使用同一页面口径。"""
    project_directory = geolib.project_dir(project_slug)
    pages_path = project_directory / "evidence" / "pages.jsonl"
    pages = geolib.read_jsonl(pages_path)
    if not pages:
        return {"removed": 0, "pages": [], "site": {}}
    deduplicated = deduplicate_crawl_pages(pages)
    removed = len(pages) - len(deduplicated)
    if deduplicated != pages:
        geolib.write_jsonl(pages_path, deduplicated)

    site_path = project_directory / "evidence" / "site.json"
    site = geolib.read_json(site_path, {}) or {}
    normalized_site = {
        **site,
        "pages_crawled": len(deduplicated),
        "pages_ok": sum(page.get("status") == 200 for page in deduplicated),
    }
    if removed:
        normalized_site["pages_crawled_raw"] = max(
            int(site.get("pages_crawled_raw") or site.get("pages_crawled") or 0),
            len(pages),
        )
        normalized_site["duplicate_pages_removed"] = (
            normalized_site["pages_crawled_raw"] - len(deduplicated)
        )
    if normalized_site != site:
        geolib.write_json(site_path, normalized_site)
    return {"removed": removed, "pages": deduplicated, "site": normalized_site}
