#!/usr/bin/env python3
"""执行公开页面、API 健康和生产 readiness 验收。"""

import argparse
import json
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin
from xml.etree import ElementTree

import requests


# ``python scripts/acceptance.py`` places only ``scripts/`` on sys.path.
# Add the repository root so the SEO contract can reuse the public-page source
# of truth just as ``python -m scripts.acceptance`` does.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _get(base_url, path, **kwargs):
    return requests.get(urljoin(base_url.rstrip("/") + "/", path.lstrip("/")), timeout=15, **kwargs)


class _SEOHeadParser(HTMLParser):
    """提取公开页的最小 SEO 合同，不执行页面脚本。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.description = ""
        self.robots = ""
        self.canonical = ""
        self.h1_count = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        values = {key.lower(): value or "" for key, value in attrs}
        tag = tag.lower()
        if tag == "title":
            self._in_title = True
        elif tag == "h1":
            self.h1_count += 1
        elif tag == "meta":
            name = values.get("name", "").lower()
            if name == "description":
                self.description = values.get("content", "")
            elif name == "robots":
                self.robots = values.get("content", "")
        elif tag == "link" and values.get("rel", "").lower() == "canonical":
            self.canonical = values.get("href", "")

    def handle_endtag(self, tag):
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data


def _public_seo_contract(base_url):
    """校验公开页面、canonical 和动态 sitemap 的一致性。"""
    from api.landing import PUBLIC_PAGES, SITE_BASE_URL

    failures = []
    expected = {SITE_BASE_URL + page["path"] for page in PUBLIC_PAGES}
    for page in PUBLIC_PAGES:
        path = page["path"]
        response = _get(base_url, path)
        parser = _SEOHeadParser()
        try:
            parser.feed(response.text)
        except (TypeError, ValueError):
            failures.append(f"{path}:invalid_html")
            continue
        robots = parser.robots.lower()
        if response.status_code != 200:
            failures.append(f"{path}:status={response.status_code}")
        if not parser.title.strip() or not 20 <= len(parser.title.strip()) <= 90:
            failures.append(f"{path}:title")
        if not parser.description.strip() or len(parser.description.strip()) < 80:
            failures.append(f"{path}:description")
        if "index" not in robots or "follow" not in robots:
            failures.append(f"{path}:robots")
        if parser.canonical != SITE_BASE_URL + path:
            failures.append(f"{path}:canonical")
        if parser.h1_count != 1:
            failures.append(f"{path}:h1={parser.h1_count}")

    sitemap = _get(base_url, "/sitemap.xml")
    sitemap_urls = set()
    if sitemap.status_code == 200:
        try:
            root = ElementTree.fromstring(sitemap.text)
            namespace = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
            sitemap_urls = {node.text for node in root.findall(f"{namespace}url/{namespace}loc") if node.text}
        except (ElementTree.ParseError, TypeError):
            failures.append("sitemap:invalid_xml")
    else:
        failures.append(f"sitemap:status={sitemap.status_code}")
    if sitemap_urls != expected:
        failures.append("sitemap:url_set")
    return failures


def collect_checks(base_url, production=False):
    checks = []

    def check(name, passed, detail):
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    try:
        landing = _get(base_url, "/")
        check("landing", landing.status_code == 200 and "CiteAura" in landing.text, landing.status_code)
        modes_ok = all(
            label in landing.text
            for label in ("API · Model knowledge", "API · Web-grounded retrieval", "Manual · Product surface")
        )
        check(
            "truthful_sampling_copy",
            modes_ok
            and "保证上首页" not in landing.text
            and "geolook" not in landing.text.lower(),
            "sampling labels and no forbidden claims",
        )
        app = _get(base_url, "/app")
        check("application", app.status_code == 200 and "CiteAura" in app.text, app.status_code)
        llms = _get(base_url, "/llms.txt")
        check(
            "llms_manifest",
            llms.status_code == 200
            and "# CiteAura" in llms.text
            and "https://citeaura.com/docs" in llms.text,
            llms.status_code,
        )
        seo_failures = _public_seo_contract(base_url)
        check("seo_public_contract", not seo_failures, ", ".join(seo_failures[:8]) or "all public pages pass")
        for path, marker in (("/about", "About CiteAura"), ("/contact", "Contact CiteAura")):
            page = _get(base_url, path)
            check(f"public:{path}", page.status_code == 200 and marker in page.text, page.status_code)
        for asset in (
            "/site-assets/styles/tokens.css",
            "/site-assets/styles/landing.css",
            "/site-assets/landing.js",
            "/site-assets/site-nav.js",
            "/site-assets/seo-attribution.js",
            "/site-assets/styles/seo-pages.css",
            "/site-assets/product-audit-clay.webp",
            "/site-assets/product-plan-clay.webp",
            "/site-assets/product-assets-clay.webp",
        ):
            response = _get(base_url, asset)
            check(f"asset:{asset}", response.status_code == 200, response.status_code)
        health = _get(base_url, "/api/v1/health")
        check("health", health.status_code == 200 and health.json().get("status") == "ok", health.status_code)
        if production:
            slash = _get(base_url, "/docs/", allow_redirects=False)
            canonical_docs = urljoin(base_url.rstrip("/") + "/", "docs")
            check(
                "canonical_trailing_slash",
                slash.status_code == 308 and slash.headers.get("location") == canonical_docs,
                f"{slash.status_code} {slash.headers.get('location', '')}".strip(),
            )
            ready = _get(base_url, "/api/v1/health/ready")
            check("production_readiness", ready.status_code == 200 and ready.json().get("status") == "ready", ready.status_code)
    except (OSError, requests.RequestException, ValueError) as exc:
        check("http", False, type(exc).__name__)
    return checks


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--production", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    checks = collect_checks(args.base_url, production=args.production)
    result = {"passed": all(item["passed"] for item in checks), "checks": checks}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for item in checks:
            print(f"{'PASS' if item['passed'] else 'FAIL'} {item['name']}: {item['detail']}")
        print("Acceptance passed." if result["passed"] else "Acceptance failed.")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
