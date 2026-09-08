"""
服务端 HTML 国际化渲染器。

把 web/index.html 中的 data-i18n* 属性在服务端替换为目标语言的译文，
返回完整 HTML 字符串，让搜索引擎可以直接索引多语言内容。

支持的属性：
  data-i18n="key"             → 替换元素文本（值含 HTML 标签时用 innerHTML）
  data-i18n-html="key"        → 强制替换 innerHTML（富文本）
  data-i18n-content="key"     → 替换 content="" 属性（meta 标签）
  data-i18n-alt="key"         → 替换 alt="" 属性（img）
  data-i18n-aria="key"        → 替换 aria-label="" 属性
  data-i18n-title="key"       → 替换 title="" 属性
  data-i18n-annual="key"      → 替换 data-annual="" 属性（定价切换）
  data-i18n-monthly="key"     → 替换 data-monthly="" 属性（定价切换）
"""

import json
import re
from functools import lru_cache
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString

_WEB_ROOT = Path(__file__).resolve().parents[2] / "web"
_MESSAGES_DIR = Path(__file__).resolve().parents[1] / "i18n" / "messages"
_PUBLIC_MESSAGES_DIR = _MESSAGES_DIR / "public"

# 落地页 SSR 只支持的语言（英语由静态 HTML 直接服务，无需 SSR）
LANDING_SSR_LOCALES = ("fr",)

_HTML_LANG = {
    "fr": "fr",
}


@lru_cache(maxsize=4)
def _load_catalog(locale: str) -> dict:
    """合并主目录 + public 子目录，public 优先级更低（主目录覆盖 public）。"""
    catalog: dict[str, str] = {}
    pub_path = _PUBLIC_MESSAGES_DIR / f"{locale}.json"
    if pub_path.is_file():
        catalog.update(json.loads(pub_path.read_text("utf-8")))
    main_path = _MESSAGES_DIR / f"{locale}.json"
    if main_path.is_file():
        catalog.update(json.loads(main_path.read_text("utf-8")))
    return catalog


@lru_cache(maxsize=2)
def _load_source_html() -> str:
    """缓存读取 index.html 源文件。"""
    return (_WEB_ROOT / "index.html").read_text("utf-8")


def _t(catalog: dict, key: str) -> str | None:
    """查找译文；找不到返回 None（保留原文）。"""
    return catalog.get(key)


def _has_html_tags(text: str) -> bool:
    return bool(re.search(r"<[a-zA-Z/]", text))


def render_landing(locale: str, site_base: str = "https://citeaura.com") -> str:
    """
    返回服务端渲染后的 index.html 译文版本。

    locale  目标语言代码（如 "fr"）
    site_base  站点根 URL（不带尾斜杠）
    """
    return _render_landing_cached(locale, site_base)


@lru_cache(maxsize=8)
def _render_landing_cached(locale: str, site_base: str) -> str:
    """缓存渲染结果——同一 locale+site_base 只渲染一次。"""
    catalog = _load_catalog(locale)
    html_lang = _HTML_LANG.get(locale, locale)
    locale_path = f"/{locale}"

    # html.parser 序列化输出标准 HTML（<link> 而非 <link/>），lxml 会产生 XHTML 风格
    soup = BeautifulSoup(_load_source_html(), "html.parser")

    # ── 1. <html lang="..."> ───────────────────────────────────────────────
    soup.html["lang"] = html_lang

    # ── 2. 替换 <title> ────────────────────────────────────────────────────
    title_tag = soup.find("title")
    if title_tag:
        key = title_tag.get("data-i18n")
        if key:
            val = _t(catalog, key)
            if val:
                title_tag.string = val

    # ── 3. 替换 meta content（description 等）──────────────────────────────
    for tag in soup.find_all(attrs={"data-i18n-content": True}):
        val = _t(catalog, tag["data-i18n-content"])
        if val:
            tag["content"] = val

    # ── 4. 替换普通元素文本 / innerHTML（data-i18n）──────────────────────
    for tag in soup.find_all(attrs={"data-i18n": True}):
        if tag.name == "title":
            continue  # 已处理
        key = tag["data-i18n"]
        val = _t(catalog, key)
        if val is None:
            continue
        if _has_html_tags(val):
            tag.clear()
            tag.append(BeautifulSoup(val, "html.parser"))
        else:
            # 只替换文本节点，保留子标签（如 <span>）
            for child in list(tag.children):
                if isinstance(child, NavigableString):
                    child.replace_with(val)
                    break
            else:
                tag.string = val

    # ── 5. 强制 innerHTML 替换（data-i18n-html）──────────────────────────
    for tag in soup.find_all(attrs={"data-i18n-html": True}):
        val = _t(catalog, tag["data-i18n-html"])
        if val:
            tag.clear()
            tag.append(BeautifulSoup(val, "html.parser"))

    # ── 6. alt 属性（img）────────────────────────────────────────────────
    for tag in soup.find_all(attrs={"data-i18n-alt": True}):
        val = _t(catalog, tag["data-i18n-alt"])
        if val:
            tag["alt"] = val

    # ── 7. aria-label 属性 ────────────────────────────────────────────────
    for tag in soup.find_all(attrs={"data-i18n-aria": True}):
        val = _t(catalog, tag["data-i18n-aria"])
        if val:
            tag["aria-label"] = val

    # ── 8. title 属性 ────────────────────────────────────────────────────
    for tag in soup.find_all(attrs={"data-i18n-title": True}):
        val = _t(catalog, tag["data-i18n-title"])
        if val:
            tag["title"] = val

    # ── 9. 定价切换 data-annual / data-monthly ───────────────────────────
    for tag in soup.find_all(attrs={"data-i18n-annual": True}):
        val = _t(catalog, tag["data-i18n-annual"])
        if val:
            tag["data-annual"] = val
    for tag in soup.find_all(attrs={"data-i18n-monthly": True}):
        val = _t(catalog, tag["data-i18n-monthly"])
        if val:
            tag["data-monthly"] = val

    # ── 10. 规范化 canonical + hreflang ──────────────────────────────────
    canonical = soup.find("link", rel="canonical")
    if canonical:
        canonical["href"] = f"{site_base}{locale_path}"

    # 移除旧 hreflang，重新写入
    for tag in soup.find_all("link", rel="alternate"):
        if tag.get("hreflang"):
            tag.decompose()

    head = soup.head
    if head:
        hreflang_tags = [
            ("x-default", f"{site_base}/"),
            ("en",        f"{site_base}/"),
            ("fr",        f"{site_base}/fr"),
        ]
        canonical_tag = soup.find("link", rel="canonical")
        insert_after = canonical_tag or head
        for hl, href in reversed(hreflang_tags):
            new_tag = soup.new_tag("link", rel="alternate", hreflang=hl, href=href)
            if canonical_tag:
                canonical_tag.insert_after(new_tag)
            else:
                head.append(new_tag)

    # ── 11. Open Graph URL / locale ───────────────────────────────────────
    og_url = soup.find("meta", property="og:url")
    if og_url:
        og_url["content"] = f"{site_base}{locale_path}"
    og_locale = soup.find("meta", property="og:locale")
    if og_locale:
        og_locale["content"] = "fr_FR"

    # ── 12. og:title / og:description / twitter:title / twitter:description
    og_title_val = _t(catalog, "landing.title")
    og_desc_val = _t(catalog, "landing.meta_description")
    if og_title_val:
        for tag in soup.find_all("meta", property="og:title"):
            tag["content"] = og_title_val
        for tag in soup.find_all("meta", attrs={"name": "twitter:title"}):
            tag["content"] = og_title_val
    if og_desc_val:
        for tag in soup.find_all("meta", property="og:description"):
            tag["content"] = og_desc_val
        for tag in soup.find_all("meta", attrs={"name": "twitter:description"}):
            tag["content"] = og_desc_val

    return str(soup)
