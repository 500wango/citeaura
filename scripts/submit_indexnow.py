#!/usr/bin/env python3
"""Submit all public CiteAura URLs to IndexNow (Bing, Yandex, Seznam, etc.)."""

import json
import os
import sys
from pathlib import Path
import urllib.request
import urllib.error

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from api.landing import PUBLIC_PAGES, SITE_BASE_URL

INDEXNOW_KEY = os.getenv("INDEXNOW_KEY", "59f477dc828647979b6a25acfbbfca7d")
HOST = "citeaura.com"
KEY_LOCATION = f"https://{HOST}/{INDEXNOW_KEY}.txt"

INDEXNOW_ENDPOINTS = (
    "https://api.indexnow.org/indexnow",
    "https://www.bing.com/indexnow",
)


def get_url_list():
    """Extract all full canonical URLs from PUBLIC_PAGES."""
    urls = []
    for page in PUBLIC_PAGES:
        path = page["path"]
        url = f"https://{HOST}{path}"
        urls.append(url)
    return sorted(set(urls))


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
    urls = get_url_list()
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

    success = False
    for ep in INDEXNOW_ENDPOINTS:
        print(f"[*] Submitting to {ep} ...")
        status, response = submit_to_indexnow(ep, payload)
        print(f"    Response Status: {status}")
        if status in (200, 202):
            print(f"    [SUCCESS] IndexNow accepted {len(urls)} URLs!")
            success = True
            break
        else:
            print(f"    [WARN] Server returned status {status}: {response}")

    if not success:
        print("[!] Note: If the domain is not yet live or DNS has not resolved the key file, IndexNow will validate on next crawl.")


if __name__ == "__main__":
    main()
