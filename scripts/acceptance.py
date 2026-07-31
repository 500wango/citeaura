#!/usr/bin/env python3
"""执行公开页面、API 健康和生产 readiness 验收。"""

import argparse
import json
import sys
from urllib.parse import urljoin

import requests


def _get(base_url, path):
    return requests.get(urljoin(base_url.rstrip("/") + "/", path.lstrip("/")), timeout=15)


def collect_checks(base_url, production=False):
    checks = []

    def check(name, passed, detail):
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    try:
        landing = _get(base_url, "/")
        check("landing", landing.status_code == 200 and "DisvorAI" in landing.text, landing.status_code)
        check(
            "truthful_sampling_copy",
            all(label in landing.text for label in ("API·参数化", "API·联网", "人工·网页端"))
            and "保证上首页" not in landing.text
            and "geolook" not in landing.text.lower(),
            "sampling labels and no forbidden claims",
        )
        app = _get(base_url, "/app")
        check("application", app.status_code == 200 and "DisvorAI" in app.text, app.status_code)
        for asset in ("/site-assets/styles.css", "/site-assets/landing.js", "/site-assets/product-audit.webp"):
            response = _get(base_url, asset)
            check(f"asset:{asset}", response.status_code == 200, response.status_code)
        health = _get(base_url, "/api/v1/health")
        check("health", health.status_code == 200 and health.json().get("status") == "ok", health.status_code)
        if production:
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
