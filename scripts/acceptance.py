#!/usr/bin/env python3
"""执行公开页面、API 健康和生产 readiness 验收。"""

import argparse
import json
from urllib.parse import urljoin

import requests


def _get(base_url, path, **kwargs):
    return requests.get(urljoin(base_url.rstrip("/") + "/", path.lstrip("/")), timeout=15, **kwargs)


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
        for path, marker in (("/about", "About CiteAura"), ("/contact", "Contact CiteAura")):
            page = _get(base_url, path)
            check(f"public:{path}", page.status_code == 200 and marker in page.text, page.status_code)
        for asset in (
            "/site-assets/styles/tokens.css",
            "/site-assets/styles/landing.css",
            "/site-assets/landing.js",
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
