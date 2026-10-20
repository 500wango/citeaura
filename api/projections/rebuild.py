"""从文件系统重建投影索引；支持 dry-run 与幂等重跑。"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from api.db import SessionLocal
from api.models import Project, RunProjection, SampleProjection, Tenant
from api.projections.hashing import rows_digest, stable_sha256
from api.projections.service import (
    _metrics_files,
    _read_json,
    _rows_for_run,
    _state,
    _upsert_prompts,
    sync_run,
)


def _source_snapshot(project_directory):
    directory = Path(project_directory)
    config = _read_json(directory / "geo.json", {}) or {}
    runs = {}
    for path in _metrics_files(directory):
        metrics = _read_json(path, {}) or {}
        run_id = str(metrics.get("run_id") or path.stem)
        rows = _rows_for_run(directory, run_id)
        runs[run_id] = {"metrics": metrics, "rows": rows, "digest": rows_digest(rows)}
    prompts = [
        {
            "id": str(question.get("id")),
            "text": question.get("text") or "",
            "market": question.get("market"),
            "group": question.get("group"),
        }
        for question in (config.get("questions") or ())
        if isinstance(question, dict) and question.get("id")
    ]
    digest = stable_sha256({
        "runs": {run_id: item["digest"] for run_id, item in runs.items()},
        "prompts": prompts,
    })
    return config, runs, prompts, digest


def rebuild_index(db, tenant_id, project_id, project_directory, force=False, dry_run=False):
    """重建一个项目的投影；未变化时直接返回 changed=False。"""
    config, runs, prompts, source_digest = _source_snapshot(project_directory)
    state = _state(db, tenant_id, project_id)
    if not force and state.indexed_digest == source_digest:
        db.commit()
        return {
            "changed": False,
            "source_digest": source_digest,
            "indexed_digest": state.indexed_digest,
            "runs": len(runs),
            "prompts": len(prompts),
        }
    counts = {
        "runs": len(runs),
        "samples": sum(len(item["rows"]) for item in runs.values()),
        "prompts": len(prompts),
    }
    if dry_run:
        db.rollback()
        return {"changed": True, "dry_run": True, "source_digest": source_digest, **counts}
    try:
        _upsert_prompts(db, tenant_id, project_id, prompts)
        for run_id, item in runs.items():
            sync_run(db, tenant_id, project_id, project_directory, run_id)
        known_runs = set(runs)
        for record in db.query(RunProjection).filter(RunProjection.project_id == project_id).all():
            if record.run_id not in known_runs:
                db.query(SampleProjection).filter(
                    SampleProjection.project_id == project_id,
                    SampleProjection.run_id == record.run_id,
                ).delete(synchronize_session=False)
                db.delete(record)
        state.source_digest = source_digest
        state.indexed_digest = source_digest
        state.status = "ok"
        state.last_error = None
        state.indexed_at = datetime.now(timezone.utc)
        db.commit()
        return {"changed": True, "source_digest": source_digest, **counts}
    except Exception as exc:  # noqa: BLE001 - 记录投影错误，源文件不受影响
        db.rollback()
        failed = _state(db, tenant_id, project_id)
        failed.status = "error"
        failed.last_error = str(exc)[:2000]
        db.commit()
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description="Rebuild CiteAura measurement projections")
    parser.add_argument("--tenant", required=True, help="Tenant directory slug")
    parser.add_argument("--project", required=True, help="Project slug")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    from api.adapters.engine import geolib, tenant_slug, with_tenant_read_context
    db = SessionLocal()
    try:
        project = db.query(Project).join(Tenant, Tenant.id == Project.tenant_id).filter(
            Project.slug == args.project,
            Tenant.directory_slug == tenant_slug(args.tenant),
        ).first()
        if project is None:
            raise SystemExit(f"Project not found: {args.project}")
        tenant_record = db.get(Tenant, project.tenant_id)
        with with_tenant_read_context(tenant_record.directory_slug, args.project):
            result = rebuild_index(
                db, tenant_record.id, project.id, geolib.project_dir(args.project),
                force=args.force, dry_run=args.dry_run,
            )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
