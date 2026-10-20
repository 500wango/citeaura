"""投影同步服务：从 samples/metrics 写可重建索引。"""

import json
from datetime import datetime, timezone
from pathlib import Path

from api.adapters.engine import geolib
from api.models import ProjectionState, PromptProjection, RunProjection, SampleProjection
from api.projections.hashing import rows_digest, sample_row_hash, stable_sha256


def _now():
    return datetime.now(timezone.utc)


def _read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text("utf-8"))
    except (OSError, ValueError):
        return default


def _metrics_files(project_directory):
    directory = Path(project_directory) / "metrics"
    return sorted(directory.glob("*.json")) if directory.exists() else []


def _metrics_for_run(project_directory, run_id):
    for path in reversed(_metrics_files(project_directory)):
        metrics = _read_json(path, {}) or {}
        if str(metrics.get("run_id") or "") == str(run_id):
            return metrics, path
    for path in (Path(project_directory) / "metrics").glob(f"{run_id}.json"):
        return _read_json(path, {}) or {}, path
    return {}, None


def _sample_files(project_directory):
    directory = Path(project_directory) / "samples"
    return sorted(directory.glob("*.jsonl")) if directory.exists() else []


def _rows_for_run(project_directory, run_id):
    rows = []
    for path in _sample_files(project_directory):
        for row in geolib.read_jsonl(path):
            if not isinstance(row, dict):
                continue
            if str(row.get("run_id") or "") == str(run_id):
                rows.append(row)
    # 同一 (question, platform, round) 以最后一条为准，避免补采重复。
    deduped = {}
    for row in rows:
        key = (
            str(row.get("question_id") or ""),
            str(row.get("platform") or ""),
            int(row.get("round") or 1),
        )
        deduped[key] = row
    return list(deduped.values())


def _state(db, tenant_id, project_id):
    state = db.query(ProjectionState).filter(ProjectionState.project_id == project_id).first()
    if state is None:
        state = ProjectionState(tenant_id=tenant_id, project_id=project_id, status="pending")
        db.add(state)
        db.flush()
    return state


def mark_projection_dirty(db, tenant_id, project_id, error=None):
    state = _state(db, tenant_id, project_id)
    state.status = "dirty" if error is None else "error"
    state.last_error = str(error)[:2000] if error else None
    db.commit()
    return state


def _upsert_run(db, tenant_id, project_id, run_id, metrics, rows):
    record = db.query(RunProjection).filter(
        RunProjection.project_id == project_id,
        RunProjection.run_id == str(run_id),
    ).first()
    source = rows_digest(rows)
    values = {
        "tenant_id": tenant_id,
        "project_id": project_id,
        "run_id": str(run_id),
        "source_sha256": source,
        "repeat": int((metrics or {}).get("repeat") or 0) or None,
        "platforms_json": json.dumps(sorted((metrics or {}).get("platforms") or {}), ensure_ascii=False),
        "aggregation_json": json.dumps({
            "question_count": (metrics or {}).get("question_count"),
            "sample_count": (metrics or {}).get("sample_count"),
            "successful_sample_count": (metrics or {}).get("successful_sample_count"),
            "measurement": (metrics or {}).get("measurement"),
        }, ensure_ascii=False, sort_keys=True),
        "started_at": None,
        "finished_at": None,
    }
    if record is None:
        record = RunProjection(**values)
        db.add(record)
    else:
        for key, value in values.items():
            setattr(record, key, value)
    return record


def _upsert_samples(db, tenant_id, project_id, run_id, rows):
    existing = {
        (item.question_id, item.platform, item.round): item
        for item in db.query(SampleProjection).filter(
            SampleProjection.project_id == project_id,
            SampleProjection.run_id == str(run_id),
        ).all()
    }
    seen = set()
    for row in rows:
        question_id = str(row.get("question_id") or "")
        platform = str(row.get("platform") or "")
        if not question_id or not platform:
            continue
        round_number = int(row.get("round") or 1)
        key = (question_id, platform, round_number)
        seen.add(key)
        analysis = row.get("analysis") if isinstance(row.get("analysis"), dict) else {}
        values = {
            "tenant_id": tenant_id,
            "project_id": project_id,
            "run_id": str(run_id),
            "question_id": question_id,
            "platform": platform,
            "sample_mode": row.get("sample_mode"),
            "round": round_number,
            "ok": bool(row.get("ok")),
            "mention": bool(analysis.get("brand_mentioned")),
            "top1": bool(analysis.get("brand_mentioned")) and int(analysis.get("brand_rank") or 0) == 1,
            "top3": bool(analysis.get("brand_mentioned")) and 1 <= int(analysis.get("brand_rank") or 0) <= 3,
            "raw_model": row.get("raw_model"),
            "search_enabled": row.get("search_enabled"),
            "answer_text": row.get("answer"),
            "row_sha256": sample_row_hash(row),
        }
        item = existing.get(key)
        if item is None:
            db.add(SampleProjection(**values))
        else:
            for field, value in values.items():
                setattr(item, field, value)
    for key, item in existing.items():
        if key not in seen:
            db.delete(item)
    return len(seen)


def _upsert_prompts(db, tenant_id, project_id, questions):
    existing = {
        item.prompt_id: item
        for item in db.query(PromptProjection).filter(PromptProjection.project_id == project_id).all()
    }
    seen = set()
    for question in questions or ():
        prompt_id = str((question or {}).get("id") or "")
        if not prompt_id:
            continue
        seen.add(prompt_id)
        text = str(question.get("text") or "")
        values = {
            "tenant_id": tenant_id,
            "project_id": project_id,
            "prompt_id": prompt_id,
            "market": question.get("market"),
            "language": question.get("language") or question.get("question_language"),
            "category": question.get("category"),
            "group_name": question.get("group"),
            "text": text,
            "source_sha256": stable_sha256({"prompt_id": prompt_id, "text": text}),
        }
        item = existing.get(prompt_id)
        if item is None:
            db.add(PromptProjection(**values))
        else:
            for field, value in values.items():
                setattr(item, field, value)
    for prompt_id, item in existing.items():
        if prompt_id not in seen:
            db.delete(item)
    return len(seen)


def sync_run(db, tenant_id, project_id, project_directory, run_id):
    """同步一个 run；返回 (行数, 题数, 运行指纹)。"""
    metrics, _path = _metrics_for_run(project_directory, run_id)
    rows = _rows_for_run(project_directory, run_id)
    if not rows and not metrics:
        return 0, 0, None
    record = _upsert_run(db, tenant_id, project_id, run_id, metrics, rows)
    samples = _upsert_samples(db, tenant_id, project_id, run_id, rows)
    config = _read_json(Path(project_directory) / "geo.json", {}) or {}
    prompts = _upsert_prompts(db, tenant_id, project_id, config.get("questions") or [])
    db.commit()
    return samples, prompts, record.source_sha256


def sync_latest_run(db, tenant_id, project_id, project_directory):
    files = _metrics_files(project_directory)
    if not files:
        return 0, 0, None
    metrics = _read_json(files[-1], {}) or {}
    run_id = metrics.get("run_id")
    if not run_id:
        return 0, 0, None
    return sync_run(db, tenant_id, project_id, project_directory, run_id)


def projection_fingerprint(db, project_id):
    state = db.query(ProjectionState).filter(ProjectionState.project_id == project_id).first()
    return {
        "status": state.status if state else "missing",
        "source_digest": state.source_digest if state else None,
        "indexed_digest": state.indexed_digest if state else None,
        "indexed_at": state.indexed_at.isoformat() if state and state.indexed_at else None,
        "last_error": state.last_error if state else None,
    }
