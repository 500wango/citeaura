"""投影哈希：只覆盖稳定业务字段，避免排序或分析细节造成假变更。"""

import hashlib
import json


SAMPLE_FIELDS = (
    "run_id", "question_id", "platform", "sample_mode", "round",
    "ok", "raw_model", "search_enabled",
)


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def stable_sha256(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _analysis(row):
    analysis = row.get("analysis") if isinstance(row.get("analysis"), dict) else {}
    return {
        "brand_mentioned": bool(analysis.get("brand_mentioned")),
        "brand_rank": int(analysis.get("brand_rank") or 0),
        "own_domain_cited": bool(analysis.get("own_domain_cited")),
        "competitors_mentioned": sorted(str(item) for item in analysis.get("competitors_mentioned") or ()),
        "cited_domains": sorted(str(item) for item in analysis.get("cited_domains") or ()),
        "negative_cues": sorted(str(item) for item in analysis.get("negative_cues") or ()),
    }


def sample_row_hash(row):
    payload = {field: row.get(field) for field in SAMPLE_FIELDS}
    payload["analysis"] = _analysis(row)
    return stable_sha256(payload)


def rows_digest(rows):
    return stable_sha256(sorted(sample_row_hash(row) for row in rows or ()))


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()
