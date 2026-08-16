"""Shared GEO utilities for paths, configuration, HTTP, and content extraction.

This module intentionally depends only on requests, BeautifulSoup, and lxml.
"""

from __future__ import annotations

import fcntl
import hashlib
import ipaddress
import json
import os
import re
import socket
import sys
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
_ROOT_CONTEXT = ContextVar("geo_root_context", default=None)
_WORK_CONTEXT = ContextVar("geo_work_context", default=None)
_DIE_CONTEXT = ContextVar("geo_die_context", default=None)
_PROJECT_LOCK_CONTEXT = ContextVar("geo_project_lock_context", default=None)


def current_root() -> Path:
    """Return the active engine root for this execution context."""
    return _ROOT_CONTEXT.get() or ROOT


def current_work() -> Path:
    """Return the active engine workspace for this execution context."""
    return _WORK_CONTEXT.get() or WORK


@contextmanager
def scoped_paths(root: Path, work: Path):
    """Scope engine paths without mutating process-global module state."""
    root_token = _ROOT_CONTEXT.set(Path(root))
    work_token = _WORK_CONTEXT.set(Path(work))
    try:
        yield
    finally:
        _WORK_CONTEXT.reset(work_token)
        _ROOT_CONTEXT.reset(root_token)


@contextmanager
def scoped_runtime(*, die_handler=None, project_lock_factory=None):
    """Scope error and project-lock hooks without changing module globals."""
    die_token = _DIE_CONTEXT.set(die_handler)
    lock_token = _PROJECT_LOCK_CONTEXT.set(project_lock_factory)
    try:
        yield
    finally:
        _PROJECT_LOCK_CONTEXT.reset(lock_token)
        _DIE_CONTEXT.reset(die_token)


def load_env(path: Path | None = None):
    """Load a gitignored project .env without overriding process variables."""
    p = path or (current_root() / ".env")
    if not p.exists():
        return
    for line in p.read_text("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip("'\""))


UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 CiteAuraEngine/1.0 (+https://citeaura.com)"
)


class _PinnedAddressAdapter(HTTPAdapter):
    """Connect to a validated address while preserving the origin Host and SNI."""

    def __init__(self, hostname: str, address: str, port: int):
        super().__init__()
        self.hostname = hostname
        self.address = address
        self.port = port

    def get_connection(self, url, proxies=None):
        if proxies:
            raise ValueError("fetch proxies are not supported")
        parsed = urlparse(url)
        options = {
            "maxsize": self._pool_maxsize,
            "block": self._pool_block,
            "retries": self.max_retries,
        }
        if parsed.scheme == "https":
            return HTTPSConnectionPool(
                self.address,
                self.port,
                assert_hostname=self.hostname,
                server_hostname=self.hostname,
                **options,
            )
        return HTTPConnectionPool(self.address, self.port, **options)

    def send(self, request, **kwargs):
        host = self.hostname
        if (self.port, request.url.lower().startswith("https://")) not in ((443, True), (80, False)):
            host = f"{host}:{self.port}"
        request.headers.setdefault("Host", host)
        return super().send(request, **kwargs)

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
    handler = _DIE_CONTEXT.get()
    if handler is not None:
        return handler(msg, code)
    print(f"[geo] Error: {msg}", file=sys.stderr)
    sys.exit(code)


def info(msg: str):
    print(f"[geo] {msg}", file=sys.stderr)


# ---------------------------------------------------------------- Project directories

SLUG_OK = re.compile(r"^[a-z0-9\u4e00-\u9fff][a-z0-9\u4e00-\u9fff-]{0,47}$")
QUESTION_ID_OK = re.compile(r"^q\d{3,6}$")
MAX_SAMPLE_REPEAT = 20


def project_dir(slug: str) -> Path:
    if not SLUG_OK.match(slug or ""):
        die(f"Invalid project slug: {slug!r}")
    return current_work() / slug


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
    lock_factory = _PROJECT_LOCK_CONTEXT.get()
    if lock_factory is not None:
        with lock_factory(slug):
            yield
        return
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
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        (bak / f"geo-{stamp}.json").write_text(p.read_text("utf-8"), "utf-8")
        old = sorted(bak.glob("geo-*.json"))
        for f in old[:-10]:
            f.unlink()
    write_json(p, cfg)


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def read_json(path: Path, default=None):
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        info(f"Warning: {p} is corrupt; using the default value")
        return default


def write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with tmp.open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def read_jsonl(path: Path):
    p = Path(path)
    if not p.exists():
        return []
    out = []
    for line_no, line in enumerate(p.read_text("utf-8", errors="replace").splitlines(), 1):
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                info(f"Warning: {p}:{line_no} is corrupt; skipping the record")
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


def _validate_fetch_target(url: str):
    """Reject credentials, non-HTTP schemes, and non-public resolved addresses."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("unsafe fetch target")
    try:
        addresses = {
            item[4][0].split("%", 1)[0]
            for item in socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
        }
    except (OSError, UnicodeError) as exc:
        raise ValueError("fetch target could not be resolved") from exc
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ValueError("fetch target resolves to a non-public address")
    return parsed, tuple(sorted(addresses, key=lambda address: (ipaddress.ip_address(address).version, address)))


def _request_pinned(session, url, parsed, addresses, **kwargs):
    """Send one request to an address from the validated DNS result."""
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    session.mount(
        f"{parsed.scheme}://",
        _PinnedAddressAdapter(parsed.hostname, addresses[0], port),
    )
    return session.get(url, **kwargs)



def fetch(url: str, timeout: int = 12, retries: int = 1) -> dict:
    """Fetch a bounded web document and return normalized response metadata."""
    if not is_fetchable(url):
        return {"url": url, "final_url": url, "status": 0, "html": "", "content_type": "",
                "elapsed": 0, "error": "Skipped: URL points to a download, media file, or static asset"}
    last = ""
    deadline = time.monotonic() + max(1, timeout) * (retries + 1)
    for attempt in range(retries + 1):
        r = None
        session = requests.Session()
        session.trust_env = False
        try:
            t0 = time.time()
            current_url = url
            for redirect_count in range(6):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise requests.Timeout("fetch wall-clock deadline exceeded")
                connect_timeout = min(3.0, max(0.1, remaining / 3))
                read_timeout = max(0.1, remaining - connect_timeout)
                parsed, addresses = _validate_fetch_target(current_url)
                r = _request_pinned(
                    session,
                    current_url,
                    parsed,
                    addresses,
                    timeout=(connect_timeout, read_timeout),
                    headers={"User-Agent": UA, "Accept-Language": os.environ.get("GEO_ACCEPT_LANGUAGE", "en")},
                    allow_redirects=False,
                    stream=True,
                )
                location = r.headers.get("Location")
                if r.status_code not in (301, 302, 303, 307, 308) or not location:
                    break
                redirected = urljoin(current_url, location)
                r.close()
                r = None
                if redirect_count >= 5:
                    raise ValueError("fetch redirect limit exceeded")
                current_url = redirected
            # Server errors and rate limits are usually transient and follow the retry policy.
            if (r.status_code >= 500 or r.status_code == 429) and attempt < retries:
                r.close()
                r = None
                time.sleep(1.5)
                continue
            ctype = r.headers.get("Content-Type", "")
            if ctype and not any(k in ctype.lower() for k in ("html", "text/plain", "xml")):
                return {"url": url, "final_url": r.url, "status": r.status_code, "html": "",
                        "content_type": ctype, "elapsed": round(time.time() - t0, 2),
                        "error": f"Skipped non-document content ({ctype.split(';')[0]})"}
            chunks, size = [], 0
            for chunk in r.iter_content(65536):
                if time.monotonic() >= deadline:
                    raise requests.Timeout("fetch wall-clock deadline exceeded")
                remaining = MAX_BYTES - size
                if remaining <= 0:
                    break
                chunks.append(chunk[:remaining])
                size += min(len(chunk), remaining)
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
                if r is not None:
                    r.close()
                    r = None
                time.sleep(1.5)
        finally:
            if r is not None:
                r.close()
            session.close()
    return {"url": url, "final_url": url, "status": 0, "html": "", "content_type": "", "elapsed": 0, "error": last}


def fetch_text(url: str, timeout: int = 8) -> str:
    result = fetch(url, timeout=timeout, retries=0)
    return result["html"] if result["status"] == 200 else ""


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
    if any(ch.isspace() for ch in host):
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
    try:
        u = urljoin(base, href)
    except ValueError:
        return None
    u, _, _ = u.partition("#")
    try:
        parts = urlparse(u)
        if (parts.scheme.lower() not in ("http", "https") or not parts.hostname
                or parts.username is not None or parts.password is not None
                or not normalize_host(u)):
            return None
    except ValueError:
        return None
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
