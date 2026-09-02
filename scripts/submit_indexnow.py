#!/usr/bin/env python3
"""Submit all public CiteAura URLs to IndexNow (Bing, Yandex, Seznam, etc.).

This script is 100% self-contained and uses only Python standard library.
No third-party packages (like fastapi, requests) are required.
"""

import json
import os
import sys
from pathlib import Path
import urllib.request
import urllib.error

INDEXNOW_KEY = os.getenv("INDEXNOW_KEY", "59f477dc828647979b6a25acfbbfca7d")
HOST = "citeaura.com"
KEY_LOCATION = f"https://{HOST}/{INDEXNOW_KEY}.txt"

INDEXNOW_ENDPOINTS = (
    "https://api.indexnow.org/indexnow",
    "https://www.bing.com/indexnow",
    "https://yandex.com/indexnow",
)

# Canonical 33 public pages on CiteAura
DEFAULT_PUBLIC_PATHS = [
    "/",
    "/docs",
    "/ai-visibility-audit",
    "/for-agencies",
    "/for-brands",
    "/methodology",
    "/pricing",
    "/sample-report",
    "/about",
    "/contact",
    "/blog",
    "/blog/best-ai-visibility-tools",
    "/blog/measure-if-chatgpt-mentions-your-brand",
    "/blog/why-chatgpt-does-not-mention-my-brand",
    "/blog/perplexity-citation-audit",
    "/blog/google-ai-overviews-citation-guide",
    "/blog/what-to-put-in-llms-txt",
    "/blog/gptbot-blocked-by-robots-txt",
    "/blog/ai-crawler-access-checklist",
    "/blog/geo-vs-seo",
    "/blog/extractability-audit",
    "/blog/white-label-geo-diagnostic-report",
    "/blog/brand-fact-library-guide",
    "/blog/how-to-get-ai-to-cite-your-site",
    "/blog/geo-blueprint-guide",
    "/blog/sampling-modes-explained",
    "/blog/citation-readiness-score",
    "/blog/geo-verification-loop",
    "/blog/ai-visibility-diagnosis-for-brands",
    "/blog/sell-geo-retainers-with-delivery-packs",
    "/blog/ai-search-directory-listings-guide",
    "/privacy",
    "/terms",
]


def discover_public_urls():
    """Discover URLs from local web files if available, otherwise use default catalog."""
    script_dir = Path(__file__).resolve().parent
    web_dir = script_dir.parent / "web"
    
    if web_dir.exists() and web_dir.is_dir():
        paths = ["/"]
        for p in web_dir.glob("*.html"):
            if p.name != "index.html":
                paths.append(f"/{p.stem}")
        blog_dir = web_dir / "blog"
        if blog_dir.exists():
            paths.append("/blog")
            for p in blog_dir.glob("*.html"):
                if p.name != "index.html":
                    paths.append(f"/blog/{p.stem}")
        return sorted({f"https://{HOST}{path}" for path in paths})
    
    return sorted({f"https://{HOST}{path}" for path in DEFAULT_PUBLIC_PATHS})


def submit_to_indexnow(endpoint: str, payload: dict) -> tuple[int, str]:
    """Send POST request to an IndexNow endpoint."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=data,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "CiteAura-IndexNow/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
            return resp.status, body
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        return e.code, body
    except Exception as e:
        return 0, str(e)


def main():
    urls = discover_public_urls()
    print(f"[*] Prepared {len(urls)} URLs for IndexNow submission on host '{HOST}':")
    for u in urls[:5]:
        print(f"    - {u}")
    print(f"    ... and {len(urls) - 5} more")

    payload = {
        "host": HOST,
        "key": INDEXNOW_KEY,
        "keyLocation": KEY_LOCATION,
        "urlList": urls,
    }

    all_success = []
    for ep in INDEXNOW_ENDPOINTS:
        print(f"[*] Submitting to {ep} ...")
        status, response = submit_to_indexnow(ep, payload)
        print(f"    Response Status: {status}")
        if status in (200, 202):
            print(f"    [SUCCESS] {ep} accepted {len(urls)} URLs!")
            all_success.append(ep)
        else:
            print(f"    [WARN] Returned status {status}: {response}")

    if all_success:
        print(f"\n[DONE] Successfully pushed to {len(all_success)} search engine endpoint(s)!")
    else:
        print("\n[!] Failed to push to endpoints.")


if __name__ == "__main__":
    main()
