"""把 GSC 查询筛成 AI 采样候选，并维护项目内的快照文件。"""

import hashlib
import re
import unicodedata
from datetime import datetime, timezone
from urllib.parse import urlparse

from api.adapters.crawl_evidence import contains_han
from api.searchdata import snapshot_store


SNAPSHOT_FILE = "gsc_snapshot.json"
MAX_CANDIDATES = 20
KEEP_ROWS = 200
LOW_VOLUME_CANDIDATES = 5
SCHEMA_VERSION = 1

INTENT_WORDS = (
    "how", "what", "which", "why", "when", "where", "who", "best", "top", "vs", "versus",
    "alternative", "alternatives", "review", "reviews", "compare", "comparison", "price",
    "pricing", "cost", "tool", "tools", "software", "platform",
    "wie", "was", "welche", "beste", "vergleich", "preis",
    "comment", "quel", "quelle", "meilleur", "meilleure", "prix",
    "cómo", "como", "qué", "que", "cuál", "mejor", "precio",
)
CJK_INTENT = (
    "怎么", "如何", "什么", "哪个", "哪些", "哪家", "推荐", "对比", "比较", "区别", "价格",
    "多少钱", "好用", "工具", "平台", "替代",
    "おすすめ", "比較", "とは", "方法", "料金", "ツール",
    "추천", "비교", "방법", "가격", "도구",
)
QUESTION_START = re.compile(
    r"^(how|what|which|why|when|where|who|is|are|can|should|does|do|wie|was|welche|comment|quel|quelle|cómo|como|qué|cuál)\b",
    re.I,
)
TOKEN = re.compile(r"[^\W_]+", re.U)


def _fold(value):
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return "".join(character for character in normalized if character.isalnum())


def brand_terms(config):
    """品牌名、别名和域名主标签；用于排除品牌词查询。"""
    brand = config.get("brand") if isinstance(config.get("brand"), dict) else {}
    values = [brand.get("name")]
    for key in ("aliases", "confirmed_aliases"):
        items = brand.get(key)
        if isinstance(items, list):
            values.extend(items)
    host = (urlparse(str(brand.get("site") or "")).hostname or "").lower().removeprefix("www.")
    if host:
        values.append(host.split(".")[0])
        values.append(host)
    terms = {_fold(value) for value in values if isinstance(value, str)}
    return {term for term in terms if len(term) >= 3}


def is_branded(query, terms):
    folded = _fold(query)
    return any(term in folded for term in terms)


def _tokens(query):
    return [token.casefold() for token in TOKEN.findall(query)]


def is_too_short(query):
    if contains_han(query) or re.search(r"[぀-ヿ가-힯]", query):
        return len(_fold(query)) < 4
    return len(_tokens(query)) < 2


def has_intent(query):
    lowered = query.casefold()
    if any(word in lowered for word in CJK_INTENT):
        return True
    tokens = set(_tokens(query))
    return any(word in tokens for word in INTENT_WORDS)


def is_question(query):
    text = query.strip()
    return text.endswith(("?", "？")) or bool(QUESTION_START.match(text))


def _capitalize(text):
    return text[:1].upper() + text[1:]


def suggest_prompt(query):
    """问句原样保留，其余查询用固定模板改写；不调用模型。"""
    text = re.sub(r"\s+", " ", query).strip()
    if is_question(text):
        return text if text.endswith(("?", "？")) else f"{_capitalize(text)}?"
    if contains_han(text):
        return f"关于“{text}”，有哪些值得推荐的选择？"
    tokens = set(_tokens(text))
    if tokens & {"vs", "versus", "compare", "comparison"}:
        return f"How do the options compare for {text}?"
    if tokens & {"alternative", "alternatives"}:
        return f"What are the best {text}?"
    if tokens & {"price", "pricing", "cost"}:
        return f"What does {text} typically look like, and which options are worth it?"
    if tokens & {"best", "top"}:
        return f"What are the {text}?"
    return f"What are the best options for {text}?"


def _candidate_id(query):
    return "gsc-" + hashlib.sha256(_fold(query).encode("utf-8")).hexdigest()[:12]


def select(rows, config, limit=MAX_CANDIDATES):
    """排除品牌词与短查询；意图词优先，再按展示量降序。"""
    terms = brand_terms(config)
    eligible = []
    excluded = {"branded": 0, "too_short": 0}
    for row in rows:
        query = str(row.get("query") or "").strip()
        if not query:
            continue
        if is_branded(query, terms):
            excluded["branded"] += 1
            continue
        if is_too_short(query):
            excluded["too_short"] += 1
            continue
        eligible.append({**row, "query": query, "intent": has_intent(query) or is_question(query)})
    eligible.sort(key=lambda row: (not row["intent"], -row["impressions"], -row["clicks"], row["query"]))
    return [
        {
            "id": _candidate_id(row["query"]),
            "query": row["query"],
            "prompt": suggest_prompt(row["query"]),
            "impressions": row["impressions"],
            "clicks": row["clicks"],
            "position": row["position"],
            "intent": row["intent"],
            "market": "cn" if contains_han(row["query"]) else "global",
        }
        for row in eligible[:limit]
    ], excluded


def anonymous_click_share(totals, rows):
    """总点击中无法归到具体查询的比例；总量为 0 时返回 None。"""
    total = int((totals or {}).get("clicks") or 0)
    if total <= 0:
        return None
    attributed = sum(int(row.get("clicks") or 0) for row in rows)
    return round(max(0.0, min(1.0, (total - attributed) / total)), 4)


def build_snapshot(site_url, fetched, config, now=None):
    rows = sorted(fetched["rows"], key=lambda row: (-row["impressions"], row["query"]))
    candidates, excluded = select(rows, config)
    return {
        "schema_version": SCHEMA_VERSION,
        "source": "google_search_console",
        "property": site_url,
        "window": fetched["window"],
        "search_type": "web",
        "data_state": "final",
        "fetched_at": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
        "totals": fetched["totals"],
        "query_count": len(rows),
        "anonymous_click_share": anonymous_click_share(fetched["totals"], rows),
        "excluded": excluded,
        "low_volume": len(candidates) < LOW_VOLUME_CANDIDATES,
        "candidates": candidates,
        "rows": rows[:KEEP_ROWS],
    }


def snapshot_path(project_slug):
    return snapshot_store.path(project_slug, SNAPSHOT_FILE)


def read_snapshot(project_slug):
    return snapshot_store.read(project_slug, SNAPSHOT_FILE, SCHEMA_VERSION)


def write_snapshot(project_slug, snapshot):
    return snapshot_store.write(project_slug, SNAPSHOT_FILE, snapshot)


def delete_snapshot(project_slug):
    return snapshot_store.delete(project_slug, SNAPSHOT_FILE)


def candidate_by_id(snapshot, candidate_id):
    for item in (snapshot or {}).get("candidates") or []:
        if item.get("id") == candidate_id:
            return item
    return None


def question_metadata(snapshot, candidate):
    """写入问题库的服务端元数据；客户端不能自带这些字段。"""
    return {
        "query": candidate["query"],
        "impressions": candidate["impressions"],
        "clicks": candidate["clicks"],
        "position": candidate["position"],
        "property": snapshot["property"],
        "window": snapshot["window"],
        "fetched_at": snapshot["fetched_at"],
        "candidate_id": candidate["id"],
    }
