"""从真实采样原文提取品牌 framing 短语。"""

import re

from api.adapters.engine import geolib
from api.adapters.global_scope import is_global_sample


_SENTENCES = re.compile(r"[^。！？!?;；\n]+[。！？!?;；]?")
_ZH_RELATIONS = (
    "被普遍认为是",
    "通常被认为是",
    "被描述为",
    "被认为是",
    "被视为",
    "定位为",
    "是一家",
    "是一个",
    "是一款",
    "是一种",
    "作为",
    "是",
)
_EN_RELATIONS = (
    r"is\s+widely\s+regarded\s+as",
    r"is\s+often\s+described\s+as",
    r"is\s+described\s+as",
    r"is\s+known\s+as",
    r"is\s+regarded\s+as",
    r"is\s+positioned\s+as",
    r"positions?\s+itself\s+as",
    r"is",
    r"are",
)
_GENERIC = {
    "brand",
    "company",
    "platform",
    "product",
    "service",
    "tool",
    "品牌",
    "公司",
    "平台",
    "产品",
    "服务",
    "工具",
}


def _clean_phrase(value):
    value = re.sub(r"https?://\S+", "", value)
    value = re.sub(r"[`*_#\[\]()]", " ", value)
    value = re.sub(r"\s+", " ", value).strip(" \t\r\n,，.。:：;；!?！？-'")
    value = re.sub(r"^(?:一家|一个|一款|一种)\s*", "", value)
    value = re.sub(r"^(?:a|an|the)\s+", "", value, flags=re.IGNORECASE)
    lowered = value.lower()
    for separator in ("，", "。", "；", " but ", " while ", " which ", " that "):
        position = lowered.find(separator.lower())
        if position >= 0:
            value = value[:position]
            lowered = value.lower()
    value = value.strip(" \t\r\n,，.。:：;；!?！？-'")
    if not value or len(value) > 96 or value.casefold() in _GENERIC:
        return ""
    if not re.search(r"[A-Za-z\u4e00-\u9fff]", value):
        return ""
    return value


def _phrases(sentence, alias):
    escaped = re.escape(alias)
    zh_relations = "|".join(re.escape(item) for item in _ZH_RELATIONS)
    patterns = [
        rf"{escaped}\s*(?:{zh_relations})\s*(?:一家|一个|一款|一种)?\s*([^，。！？；;\n]{{2,96}})",
        rf"(?:把|将)?\s*{escaped}\s*(?:描述为|称为)\s*(?:一家|一个|一款|一种)?\s*([^，。！？；;\n]{{2,96}})",
        rf"{escaped}\s+(?:{'|'.join(_EN_RELATIONS)})\s+(?:an?\s+|the\s+)?([^.,;!?\n]{{3,96}})",
        rf"(?:describes?|calls?)\s+{escaped}\s+as\s+(?:an?\s+|the\s+)?([^.,;!?\n]{{3,96}})",
    ]
    found = []
    for pattern in patterns:
        for match in re.finditer(pattern, sentence, flags=re.IGNORECASE):
            phrase = _clean_phrase(match.group(1))
            if phrase:
                found.append(phrase)
    return found


def _sampling_mode(row):
    if row.get("sample_mode") == "manual" or row.get("terminal") == "web":
        return "Manual - Product interface"
    return "API - Search grounded" if row.get("search_enabled") else "API - Parametric knowledge"


def _latest_samples(project_slug):
    directory = geolib.project_dir(project_slug) / "samples"
    files = sorted(directory.glob("*.jsonl")) if directory.exists() else []
    if not files:
        return None, []
    path = files[-1]
    return path, [row for row in geolib.read_jsonl(path) if is_global_sample(row)]


def build(project_slug):
    """返回最新一期 framing 短语及其原文证据。"""
    cfg = geolib.load_config(project_slug)
    brand = cfg.get("brand", {})
    aliases = [brand.get("name", "")] + list(brand.get("aliases", []) or [])
    aliases = sorted({item.strip() for item in aliases if item and item.strip()}, key=len, reverse=True)
    path, rows = _latest_samples(project_slug)
    buckets = {}
    mentioned_samples = 0
    for row in rows:
        answer = str(row.get("answer") or "")
        if not answer or not (row.get("analysis") or {}).get("brand_mentioned"):
            continue
        mentioned_samples += 1
        seen = set()
        for sentence_match in _SENTENCES.finditer(answer):
            sentence = sentence_match.group(0).strip()
            for alias in aliases:
                if not re.search(re.escape(alias), sentence, flags=re.IGNORECASE):
                    continue
                for phrase in _phrases(sentence, alias):
                    key = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", phrase.casefold())
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    item = buckets.setdefault(
                        key,
                        {"term": phrase, "count": 0, "engines": set(), "markets": set(), "evidence": []},
                    )
                    item["count"] += 1
                    item["engines"].add(row.get("platform_name") or row.get("platform") or "unknown")
                    item["markets"].add(row.get("market") or "unknown")
                    if len(item["evidence"]) < 3:
                        item["evidence"].append({
                            "question_id": row.get("question_id"),
                            "question": row.get("question", ""),
                            "platform": row.get("platform", ""),
                            "platform_name": row.get("platform_name") or row.get("platform") or "unknown",
                            "sampling_mode": _sampling_mode(row),
                            "excerpt": sentence[:360],
                        })
                break

    terms = []
    for item in buckets.values():
        terms.append({
            "term": item["term"],
            "count": item["count"],
            "share": round(item["count"] / mentioned_samples, 3) if mentioned_samples else 0,
            "engines": sorted(item["engines"]),
            "markets": sorted(item["markets"]),
            "evidence": item["evidence"],
        })
    terms.sort(key=lambda item: (-item["count"], -len(item["engines"]), item["term"].casefold()))
    status = "ready" if terms else (
        "no_samples" if not rows else ("brand_not_mentioned" if not mentioned_samples else "no_descriptors")
    )
    return {
        "status": status,
        "date": path.stem if path else None,
        "sample_count": len(rows),
        "mentioned_samples": mentioned_samples,
        "terms": terms[:24],
    }
