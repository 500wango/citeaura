"""品牌身份别名、样本分析版本和问题集归属适配。"""

import hashlib
import json
import os
import re
import unicodedata
from copy import deepcopy
from urllib.parse import urlparse

from api.adapters.engine import geolib


ANALYSIS_VERSION = 2
IDENTITY_SCHEMA_VERSION = 1
LATIN_WORD = re.compile(r"[A-Za-z0-9]+")
CAMEL_WORD = re.compile(r"[A-Z]+(?=[A-Z][a-z]|\b)|[A-Z]?[a-z]+|[0-9]+")
DECLARED_SHORT_FORM = re.compile(r"(?<![A-Za-z0-9])[A-Z][A-Z0-9.+-]{1,11}(?![A-Za-z0-9])")
PARENTHETICAL = re.compile(r"[（(]([^()（）]{2,80})[）)]")


def _fold(value):
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return "".join(character for character in normalized if character.isalnum())


def _values(items):
    if isinstance(items, str):
        items = [items]
    if not isinstance(items, (list, tuple, set)):
        return []
    return [str(item).strip() for item in items if isinstance(item, str) and item.strip()]


def _name_initialism(name):
    words = []
    for token in LATIN_WORD.findall(str(name or "")):
        words.extend(CAMEL_WORD.findall(token) or [token])
    if len(words) < 2:
        return ""
    return "".join(word[0] for word in words if word).casefold()


def _category_signatures(brand):
    surfaces = [brand.get("industry")]
    surfaces.extend(brand.get("products") if isinstance(brand.get("products"), list) else [])
    signatures = set()
    for surface in _values(surfaces):
        folded = _fold(surface)
        if folded:
            signatures.add(folded)
        signatures.update(_fold(value) for value in PARENTHETICAL.findall(surface) if _fold(value))
        signatures.update(_fold(value) for value in DECLARED_SHORT_FORM.findall(surface) if _fold(value))
        initialism = _name_initialism(surface)
        if len(initialism) >= 3:
            signatures.add(initialism)
    return signatures


def _category_collision(value, signatures):
    folded = _fold(value)
    if not folded:
        return False
    return any(
        folded == signature
        or (len(folded) >= 4 and folded in signature)
        for signature in signatures
    )


def _explicit_aliases(entity):
    confirmed = {_fold(value) for value in _values(entity.get("confirmed_aliases") or [])}
    for item in entity.get("alias_evidence") or []:
        if not isinstance(item, dict) or item.get("status") != "confirmed":
            continue
        if item.get("value") and (item.get("source_url") or item.get("quote")):
            confirmed.add(_fold(item["value"]))
    return confirmed


def _identity_relation(value, name, site=""):
    folded = _fold(value)
    canonical = _fold(name)
    if not folded or not canonical:
        return ""
    if folded == canonical:
        return "canonical_variant"
    initialism = _name_initialism(name)
    if len(initialism) >= 3 and folded == initialism:
        return "canonical_initialism"
    host = urlparse(str(site or "")).hostname or ""
    domain_label = host.lower().removeprefix("www.").split(".")[0]
    if domain_label and folded == _fold(domain_label):
        return "official_domain_variant"
    return ""


def _alias_candidates(entity):
    values = []
    for item in entity.get("alias_review") or []:
        if isinstance(item, dict) and item.get("value"):
            values.append(str(item["value"]).strip())
    values.extend(_values(entity.get("aliases") or []))
    unique = []
    seen = set()
    for value in values:
        key = _fold(value)
        if key and key not in seen:
            seen.add(key)
            unique.append(value)
    return unique


def _normalize_entity(entity, *, category_signatures=None):
    current = deepcopy(entity) if isinstance(entity, dict) else {}
    name = str(current.get("name") or "").strip()
    explicit = _explicit_aliases(current)
    signatures = category_signatures or set()
    aliases = []
    review = []
    for value in _alias_candidates(current):
        relation = _identity_relation(value, name, current.get("site"))
        key = _fold(value)
        if relation and unicodedata.normalize("NFKC", value).casefold() == unicodedata.normalize("NFKC", name).casefold():
            review.append({"value": value, "status": "redundant", "reason": relation})
        elif relation:
            aliases.append(value)
            review.append({"value": value, "status": "active", "reason": relation})
        elif key in explicit:
            aliases.append(value)
            review.append({"value": value, "status": "active", "reason": "confirmed_evidence"})
        elif _category_collision(value, signatures):
            review.append({"value": value, "status": "rejected", "reason": "category_or_product_term"})
        else:
            review.append({"value": value, "status": "pending", "reason": "identity_evidence_required"})
    current["aliases"] = aliases
    if review:
        current["alias_review"] = review
    else:
        current.pop("alias_review", None)
    current["alias_review_required"] = any(item["status"] == "pending" for item in review)
    return current


def identity_version(config):
    brand = config.get("brand") if isinstance(config, dict) else {}
    competitors = config.get("competitors") if isinstance(config, dict) else []
    payload = {
        "schema": IDENTITY_SCHEMA_VERSION,
        "brand": {
            "name": (brand or {}).get("name"),
            "site": (brand or {}).get("site"),
            "aliases": (brand or {}).get("aliases") or [],
        },
        "competitors": [
            {"name": item.get("name"), "aliases": item.get("aliases") or []}
            for item in competitors or [] if isinstance(item, dict)
        ],
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def normalize_config_identity(config):
    current = deepcopy(config) if isinstance(config, dict) else {}
    brand = current.get("brand") if isinstance(current.get("brand"), dict) else {}
    current["brand"] = _normalize_entity(brand, category_signatures=_category_signatures(brand))
    current["competitors"] = [
        _normalize_entity(item)
        for item in current.get("competitors") or []
        if isinstance(item, dict)
    ]
    current["identity"] = {
        "schema_version": IDENTITY_SCHEMA_VERSION,
        "version": identity_version(current),
        "review_required": bool(current["brand"].get("alias_review_required"))
        or any(item.get("alias_review_required") for item in current["competitors"]),
    }
    return current


def question_set_version(config):
    questions = []
    for item in config.get("questions", []) or []:
        if not isinstance(item, dict):
            continue
        questions.append({key: item.get(key) for key in ("id", "text", "market", "group")})
    canonical = json.dumps(
        sorted(questions, key=lambda item: (item.get("id") or "", item.get("text") or "")),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return {"version": hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16], "count": len(questions)}


def _current_question(row, config):
    question_id = str(row.get("question_id") or "")
    question_text = str(row.get("question") or "").strip()
    return any(
        str(item.get("id") or "") == question_id
        and str(item.get("text") or "").strip() == question_text
        for item in config.get("questions") or []
        if isinstance(item, dict)
    )


def sample_exclusion_reason(row, config):
    if not _current_question(row, config):
        return "question_set_mismatch"
    expected = question_set_version(config)["version"]
    if row.get("question_set_version") not in (None, expected):
        return "question_set_version_mismatch"
    return ""


def is_current_sample(row, config):
    return isinstance(row, dict) and not sample_exclusion_reason(row, config)


def _matched_identity(answer, config, engine_sample):
    brand = config.get("brand") or {}
    names = [brand.get("name"), *(brand.get("aliases") or [])]
    names = [str(value) for value in names if value]
    position, _negated = engine_sample._entity_hit(answer, names)
    if position < 0:
        return None
    for index, value in enumerate(names):
        for start, end in engine_sample._alias_spans(answer, value):
            if start == position:
                return {
                    "value": value,
                    "text": answer[start:end],
                    "kind": "canonical" if index == 0 else "alias",
                    "start": start,
                    "end": end,
                }
    return None


def analyze_answer(answer, config, citations=None):
    import sample as engine_sample

    normalized_citations = [
        {"url": item} if isinstance(item, str) else item
        for item in citations or [] if isinstance(item, (str, dict))
    ]
    analysis = engine_sample.analyze_answer(answer, config, normalized_citations)
    matched = _matched_identity(answer, config, engine_sample)
    if analysis.get("brand_mentioned") and matched is None:
        brand = (config.get("brand") or {}).get("name")
        analysis["brand_mentioned"] = False
        analysis["brand_rank"] = 0
        analysis["candidates"] = [item for item in analysis.get("candidates") or [] if item != brand]
    analysis["matched_identity"] = matched
    analysis["analysis_version"] = ANALYSIS_VERSION
    analysis["identity_version"] = identity_version(config)
    analysis["evidence_fingerprint"] = _evidence_fingerprint(answer, normalized_citations)
    return analysis


def _evidence_fingerprint(answer, citations=None):
    payload = json.dumps(
        {"answer": str(answer or ""), "citations": citations or []},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _failed_analysis(config, answer="", citations=None):
    return {
        "brand_mentioned": False,
        "brand_rank": 0,
        "candidates": [],
        "competitors_mentioned": [],
        "cited_domains": [],
        "own_domain_cited": False,
        "answer_chars": 0,
        "needs_review": False,
        "negative_cues": [],
        "matched_identity": None,
        "analysis_version": ANALYSIS_VERSION,
        "identity_version": identity_version(config),
        "evidence_fingerprint": _evidence_fingerprint(answer, citations),
    }


def _legacy_question_version(row):
    value = f"{row.get('question_id') or ''}\n{row.get('question') or ''}"
    return "legacy-" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _write_jsonl_atomic(path, rows):
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def reanalyze_samples(project_slug, config=None):
    """保留原始回答，只更新可重建分析、身份版本和问题集归属。"""
    config = normalize_config_identity(config or geolib.load_config(project_slug))
    expected_identity = identity_version(config)
    expected_questions = question_set_version(config)["version"]
    sample_directory = geolib.project_dir(project_slug) / "samples"
    result = {"files": 0, "rows": 0, "changed": 0, "excluded": 0}
    if not sample_directory.is_dir():
        return result
    with geolib.project_lock(project_slug):
        for path in sorted(sample_directory.glob("*.jsonl")):
            rows = geolib.read_jsonl(path)
            changed = False
            for row in rows:
                result["rows"] += 1
                before = deepcopy(row)
                current_question = _current_question(row, config)
                row["question_set_version"] = expected_questions if current_question else _legacy_question_version(row)
                row["included_in_metrics"] = bool(current_question)
                if current_question:
                    row.pop("sample_exclusion_reason", None)
                else:
                    row["sample_exclusion_reason"] = "question_set_mismatch"
                    result["excluded"] += 1
                analysis = row.get("analysis") or {}
                stale = (
                    analysis.get("analysis_version") != ANALYSIS_VERSION
                    or analysis.get("identity_version") != expected_identity
                    or analysis.get("evidence_fingerprint") != _evidence_fingerprint(
                        row.get("answer") or "", row.get("citations") or [],
                    )
                )
                if stale:
                    row["analysis"] = (
                        analyze_answer(row.get("answer") or "", config, row.get("citations"))
                        if row.get("ok") else _failed_analysis(
                            config, row.get("answer") or "", row.get("citations") or [],
                        )
                    )
                    row["needs_review"] = bool(row["analysis"].get("needs_review"))
                if row != before:
                    changed = True
                    result["changed"] += 1
            if changed:
                _write_jsonl_atomic(path, rows)
                result["files"] += 1
    return result
