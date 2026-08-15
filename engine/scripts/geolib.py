"""Shared GEO utilities for paths, configuration, HTTP, and content extraction.

This module intentionally depends only on requests, BeautifulSoup, and lxml.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"


def load_env(path: Path | None = None):
    """Load a gitignored project .env without overriding process variables."""
    p = path or (ROOT / ".env")
    if not p.exists():
        return
    for line in p.read_text("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip("'\""))


load_env()

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 geo-skill/1.0"
)

# ---------------------------------------------------------------- Core utilities


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def slugify(text: str) -> str:
    text = re.sub(r"^https?://", "", (text or "").strip().lower())
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", text).strip("-")
    return text[:48] or "project"


def die(msg: str, code: int = 1):
    print(f"[geo] Error: {msg}", file=sys.stderr)
    sys.exit(code)


def info(msg: str):
    print(f"[geo] {msg}", file=sys.stderr)


# ---------------------------------------------------------------- Project directories

SLUG_OK = re.compile(r"^[a-z0-9\u4e00-\u9fff][a-z0-9\u4e00-\u9fff-]{0,47}$")
QUESTION_ID_OK = re.compile(r"^q\d{3,6}$")


def project_dir(slug: str) -> Path:
    if not SLUG_OK.match(slug or ""):
        die(f"Invalid project slug: {slug!r}")
    return WORK / slug


def normalize_question_ids(questions: list) -> list[dict]:
    """Return unique filename-safe IDs without trusting model-provided values."""
    rows = [dict(q) for q in questions or [] if isinstance(q, dict)]
    used: set[str] = set()
    next_id = 1
    for row in rows:
        raw = str(row.get("id") or "").strip().lower()
        if QUESTION_ID_OK.fullmatch(raw) and raw not in used:
            qid = raw
        else:
            while f"q{next_id:03d}" in used:
                next_id += 1
            qid = f"q{next_id:03d}"
            next_id += 1
        row["id"] = qid
        used.add(qid)
    return rows


def safe_child(directory: Path, name: str, suffix: str = "") -> Path:
    """Build a direct child path and reject traversal or invalid question IDs."""
    value = str(name or "")
    if not QUESTION_ID_OK.fullmatch(value):
        raise ValueError(f"Invalid question id: {value!r}")
    base = Path(directory).resolve()
    target = (base / f"{value}{suffix}").resolve()
    if target.parent != base:
        raise ValueError(f"Unsafe output path: {target}")
    return target


def stable_hash(value, length: int = 16) -> str:
    body = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:length]


def new_run_id(prefix: str = "run") -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{prefix}-{stamp}-{uuid.uuid4().hex[:8]}"


@contextmanager
def project_lock(slug: str):
    """Serialize project-level load-modify-write operations across processes."""
    d = project_dir(slug)
    d.mkdir(parents=True, exist_ok=True)
    with (d / ".lock").open("w") as fd:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)


def load_config(slug: str) -> dict:
    p = project_dir(slug) / "geo.json"
    if not p.exists():
        die(f"Project config not found {p}. Run first: python3 scripts/geo.py init --url <URL>")
    return json.loads(p.read_text("utf-8"))


def save_config(slug: str, cfg: dict):
    """Back up curated project configuration before replacing it."""
    p = project_dir(slug) / "geo.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        bak = p.parent / ".geo.bak"
        bak.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        (bak / f"geo-{stamp}.json").write_text(p.read_text("utf-8"), "utf-8")
        old = sorted(bak.glob("geo-*.json"))
        for f in old[:-10]:
            f.unlink()
    p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), "utf-8")


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    os.replace(tmp, path)


def read_json(path: Path, default=None):
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text("utf-8"))
    except json.JSONDecodeError:
        info(f"Warning: {p} is corrupt; using the default value")
        return default


def write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def read_jsonl(path: Path):
    p = Path(path)
    if not p.exists():
        return []
    out = []
    for line in p.read_text("utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


# ---------------------------------------------------------------- HTTP

MAX_BYTES = 4_000_000  # Bound page reads so large downloads cannot stall the pipeline.

# Skip obvious downloads, media, and static assets before opening a request.
SKIP_EXT = re.compile(
    r"\.(zip|gz|tgz|bz2|7z|rar|dmg|pkg|exe|msi|apk|ipa|deb|rpm|bin|iso"
    r"|mp4|mov|avi|mkv|mp3|wav|flac|png|jpe?g|gif|webp|svg|ico|bmp|tiff"
    r"|woff2?|ttf|eot|css|js|csv|xlsx?|docx?|pptx?|pdf)(\?|$)",
    re.I,
)
SKIP_PATH = re.compile(r"/(downloads?|dl|releases?|assets|static|cdn)/", re.I)


def is_fetchable(url: str) -> bool:
    if SKIP_EXT.search(url) or SKIP_PATH.search(url):
        return False
    tail = url.rstrip("/").rsplit("/", 1)[-1].lower()
    return tail not in {"download", "dl"}



def fetch(url: str, timeout: int = 12, retries: int = 1) -> dict:
    """Fetch a bounded web document and return normalized response metadata."""
    if not is_fetchable(url):
        return {"url": url, "final_url": url, "status": 0, "html": "", "content_type": "",
                "elapsed": 0, "error": "Skipped: URL points to a download, media file, or static asset"}
    last = ""
    for attempt in range(retries + 1):
        try:
            t0 = time.time()
            r = requests.get(
                url,
                timeout=timeout,
                headers={"User-Agent": UA, "Accept-Language": os.environ.get("GEO_ACCEPT_LANGUAGE", "en")},
                allow_redirects=True,
                stream=True,
            )
            # Server errors and rate limits are usually transient and follow the retry policy.
            if (r.status_code >= 500 or r.status_code == 429) and attempt < retries:
                r.close()
                time.sleep(1.5)
                continue
            ctype = r.headers.get("Content-Type", "")
            if ctype and not any(k in ctype.lower() for k in ("html", "text/plain", "xml")):
                r.close()
                return {"url": url, "final_url": r.url, "status": r.status_code, "html": "",
                        "content_type": ctype, "elapsed": round(time.time() - t0, 2),
                        "error": f"Skipped non-document content ({ctype.split(';')[0]})"}
            chunks, size = [], 0
            for chunk in r.iter_content(65536):
                chunks.append(chunk)
                size += len(chunk)
                if size >= MAX_BYTES:
                    break
            r.close()
            raw = b"".join(chunks)
            enc = r.encoding if r.encoding and r.encoding.lower() != "iso-8859-1" else None
            if not enc:
                m = re.search(rb'charset=["\']?([\w\-]+)', raw[:4000], re.I)
                enc = m.group(1).decode("ascii", "ignore") if m else "utf-8"
            return {
                "url": url,
                "final_url": r.url,
                "status": r.status_code,
                "html": raw.decode(enc, "replace"),
                "content_type": ctype,
                "elapsed": round(time.time() - t0, 2),
                "error": None,
            }
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}: {e}"
            if attempt < retries:
                time.sleep(1.5)
    return {"url": url, "final_url": url, "status": 0, "html": "", "content_type": "", "elapsed": 0, "error": last}


def fetch_text(url: str, timeout: int = 8) -> str:
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": UA})
        if r.status_code == 200:
            r.encoding = r.apparent_encoding or r.encoding
            return r.text
    except Exception:  # noqa: BLE001
        pass
    return ""


def same_site(a: str, b: str) -> bool:
    ha, hb = normalize_host(a), normalize_host(b)
    if not ha or not hb:
        return False
    return ha == hb or ha.endswith("." + hb) or hb.endswith("." + ha)


def normalize_host(value: str) -> str:
    """Return a lowercase host without credentials, port, ``www`` or a trailing dot."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlparse(raw if "://" in raw or raw.startswith("//") else "//" + raw)
        host = (parsed.hostname or "").strip().lower().rstrip(".")
    except ValueError:
        return ""
    return host.removeprefix("www.")


# Strip tracking parameters so one page is not crawled under multiple URLs.
TRACKING_PARAMS = {"fbclid", "gclid", "dclid", "msclkid", "igshid", "mc_cid", "mc_eid",
                   "ref", "spm", "scm"}


def normalize_url(base: str, href: str) -> str | None:
    if not href:
        return None
    href = href.strip()
    if href.startswith(("mailto:", "tel:", "javascript:", "#")):
        return None
    u = urljoin(base, href)
    u, _, _ = u.partition("#")
    parts = urlparse(u)
    if parts.query:
        qs = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
              if not (k.lower().startswith("utm_") or k.lower() in TRACKING_PARAMS)]
        u = urlunparse(parts._replace(query=urlencode(qs)))
    return u


# ---------------------------------------------------------------- Main-content extraction

_DROP_TAGS = ["script", "style", "noscript", "svg", "iframe", "form", "template"]
_BOILER = re.compile(r"(nav|header|footer|sidebar|menu|breadcrumb|cookie|banner|advert)", re.I)


def parse_html(html: str) -> BeautifulSoup:
    return BeautifulSoup(html or "", "lxml")


def main_content(soup: BeautifulSoup) -> BeautifulSoup:
    """Return a cloned content DOM without navigation or interactive boilerplate."""
    body = soup.find("article") or soup.find("main") or soup.body or soup
    clone = BeautifulSoup(str(body), "lxml")
    for t in clone(_DROP_TAGS):
        t.decompose()
    for t in clone.find_all(attrs={"class": _BOILER}):
        t.decompose()
    for t in clone.find_all(attrs={"id": _BOILER}):
        t.decompose()
    return clone


def main_text(soup: BeautifulSoup) -> str:
    clone = main_content(soup)
    text = clone.get_text("\n", strip=True)
    return re.sub(r"\n{3,}", "\n\n", text)


CJK = re.compile(r"[\u4e00-\u9fff]")
KANA = re.compile(r"[\u3040-\u30ff]")
HANGUL = re.compile(r"[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]")
THAI = re.compile(r"[\u0e00-\u0e7f]")
ARABIC = re.compile(r"[\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff]")
DEVANAGARI = re.compile(r"[\u0900-\u097f]")


def cjk_ratio(text: str) -> float:
    """Return the Han share among Han characters and Latin words."""
    cjk = len(CJK.findall(text))
    latin = len(re.findall(r"[A-Za-z][A-Za-z'\-]*", text))
    total = cjk + latin
    return round(cjk / total, 3) if total else 0.0


def page_language(text: str, lang_attr: str = "") -> str:
    """Detect common writing systems, using the lang attribute only for short text."""
    aliases = {"zh": "zh", "ja": "ja", "en": "en", "ko": "ko", "th": "th",
               "ar": "ar", "hi": "hi", "mr": "hi", "ne": "hi"}
    if len(text) < 80:
        la = (lang_attr or "").lower()
        return next((lang for prefix, lang in aliases.items() if la.startswith(prefix)), "unknown")
    # Require a meaningful Kana share so occasional Japanese terms do not flip the result.
    kana = len(KANA.findall(text))
    if kana >= 5 and kana / (kana + len(CJK.findall(text))) > 0.2:
        return "ja"
    counts = {
        "zh": len(CJK.findall(text)),
        "ko": len(HANGUL.findall(text)),
        "th": len(THAI.findall(text)),
        "ar": len(ARABIC.findall(text)),
        "hi": len(DEVANAGARI.findall(text)),
        "en": len(re.findall(r"[A-Za-z][A-Za-z'\-]*", text)),
    }
    lang, count = max(counts.items(), key=lambda item: item[1])
    total = sum(counts.values())
    if not total:
        return "unknown"
    return lang if count / total >= 0.55 else "mixed"


def word_count(text: str) -> int:
    """Estimate words across writing systems with and without whitespace boundaries."""
    cjk = len(CJK.findall(text)) + len(KANA.findall(text))
    latin = len(re.findall(r"[A-Za-z][A-Za-z'\-]*", text))
    hangul = len(re.findall(r"[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]+", text))
    thai = len(THAI.findall(text)) / 4
    arabic = len(re.findall(r"[\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff]+", text))
    devanagari = len(re.findall(r"[\u0900-\u097f]+", text))
    return int(cjk / 1.6 + latin + hangul + thai + arabic + devanagari)


_QUERY_STOP = re.compile(
    "\u4ec0\u4e48|\u600e\u4e48|\u5982\u4f55|\u54ea\u4e2a|\u54ea\u4e9b|\u6709\u6ca1\u6709|"
    "\u662f\u5426|\u53ef\u4ee5|\u9002\u5408|\u63a8\u8350|\u597d\u7528|\u6700\u597d|"
    "\u8bf7\u95ee|\u591a\u5c11|\u54ea\u91cc|"
    r"\b(?:the|and|for|how|what|which|best|good|recommend|is|are|can)\b",
    re.I,
)


def relevance_tokens(text: str) -> list[str]:
    """Split natural-language questions into reproducible query-intent tokens."""
    out: list[str] = []
    source = str(text or "").lower()
    for phrase in re.findall(r"[\u4e00-\u9fff]{2,}", source):
        if phrase not in out:
            out.append(phrase)
    cleaned = _QUERY_STOP.sub(" ", source)
    for token in re.findall(r"[a-z][a-z0-9+.#'\-]{1,}|[\u4e00-\u9fff]{2,}", cleaned):
        candidates = [token]
        if CJK.search(token) and len(token) > 3:
            candidates.extend(token[i:i + size] for size in (2, 3, 4)
                              for i in range(0, len(token) - size + 1))
        for candidate in candidates:
            if candidate not in out:
                out.append(candidate)
    return out


def jsonld(soup: BeautifulSoup) -> list:
    out = []
    for tag in soup.find_all("script", type=lambda v: v and "ld+json" in v):
        try:
            data = json.loads(tag.string or "{}")
        except Exception:  # noqa: BLE001
            continue
        out.extend(data if isinstance(data, list) else [data])
    return out


def jsonld_types(blocks: list) -> list[str]:
    types = []
    for b in blocks:
        if not isinstance(b, dict):
            continue
        t = b.get("@type")
        if isinstance(t, list):
            types.extend(str(x) for x in t)
        elif t:
            types.append(str(t))
        for sub in b.get("@graph", []) or []:
            if isinstance(sub, dict) and sub.get("@type"):
                st = sub["@type"]
                types.extend(st if isinstance(st, list) else [st])
    return sorted(set(types))
