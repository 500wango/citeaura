"""项目 Job 的序列化、日志进度和重试派发。"""

import json
import os
import re

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from api.adapters.log_translator import translate_engine_log
from api.models import Job
from api.pipeline_catalog import PIPELINE_ACTIONS, RETRYABLE_ACTIONS
from api.worker.tasks import (
    task_bootstrap,
    task_cycle,
    task_deliver,
    task_pipeline,
    task_sample,
    task_verify,
)


def job_payload(job: Job, include_log: bool = True, log_offset: int | None = None) -> dict:
    log = ""
    next_offset = 0
    if include_log and job.log_path:
        try:
            with open(job.log_path, "rb") as handle:
                handle.seek(0, os.SEEK_END)
                file_size = handle.tell()
                start = max(0, file_size - 20_000) if log_offset is None else min(max(0, log_offset), file_size)
                handle.seek(start)
                chunk = handle.read(20_000)
            log = chunk.decode("utf-8", "replace")
            next_offset = start + len(chunk)
        except OSError:
            log = ""
    derived_stage, derived_progress = progress_from_log(log)
    progress = max(int(job.progress or 0), derived_progress)
    stage = derived_stage if progress > int(job.progress or 0) else (job.stage or "queued")
    if job.status == "done":
        stage, progress = "complete", 100
    elif job.status == "failed":
        stage = "failed"
    return {
        "id": job.id,
        "project_id": job.project_id,
        "action": job.action,
        "status": job.status,
        "stage": stage,
        "progress": progress,
        "attempt": job.attempt or 1,
        "request": request_payload(job.request_json),
        "celery_task_id": job.celery_task_id,
        "retry_of_job_id": job.retry_of_job_id,
        "can_retry": job.status == "failed" and job.action in RETRYABLE_ACTIONS,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "error": translate_engine_log(job.error) if job.error else None,
        "log": translate_engine_log(log),
        "log_offset": next_offset,
    }


def progress_from_log(log: str):
    """从旧引擎已有的 info 输出推导阶段，不修改 engine。"""
    if not log:
        return None, 0
    stage = None
    progress = 0
    for match in re.finditer(r"═══\s*(\d+)\s*/\s*(\d+)\s*([^═\n]*)═══", log):
        current, total = int(match.group(1)), max(1, int(match.group(2)))
        progress = max(progress, min(95, round(current / total * 90)))
        stage = match.group(3).strip() or stage
    for match in re.finditer(r"\[geo\]\s*(\d+)\s*/\s*(\d+)", log):
        current, total = int(match.group(1)), max(1, int(match.group(2)))
        progress = max(progress, min(95, round(current / total * 90)))
        stage = "sampling" if stage is None else stage
    return stage, progress


def request_payload(value):
    if not value:
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


def safe_request_json(action, params=None):
    """只保存动作白名单内的参数，避免把用户误传的密钥写入数据库。"""
    params = params or {}
    if action == "sample":
        values = {
            "limit": params.get("limit"),
            "platforms": params.get("platforms"),
            "repeat": params.get("repeat", 1),
            "question_ids": params.get("question_ids"),
        }
    elif action in PIPELINE_ACTIONS:
        allowed = set(PIPELINE_ACTIONS[action].get("args", []))
        values = {}
        for name, value in params.items():
            flag = str(name)
            if not flag.startswith("--"):
                flag = "--" + flag.replace("_", "-")
            if flag in allowed:
                values[flag] = value
    else:
        values = params
    return json.dumps(values, ensure_ascii=False, default=str)[:10000]


def active_job(db: Session, project_id: int):
    return db.query(Job).filter(
        Job.project_id == project_id,
        Job.status.in_(("queued", "running")),
    ).order_by(Job.id.desc()).first()


def _pipeline_flag(params, name):
    return params.get(f"--{name}", params.get(name, False)) is True


def dispatch_retry(task_name, tenant_name, project_slug, request, job_id, source_action):
    if source_action in ("bootstrap", "autopilot"):
        return task_bootstrap.delay(
            tenant_name,
            project_slug,
            skip_llm=bool(request.get("skip_llm", request.get("--skip-llm", False))),
            no_sample=_pipeline_flag(request, "no-sample") or _pipeline_flag(request, "no_sample"),
            job_action=source_action,
            job_id=job_id,
        )
    if source_action == "sample":
        return task_sample.delay(
            tenant_name,
            project_slug,
            limit=request.get("limit", request.get("--limit")),
            platforms=request.get("platforms", request.get("--platforms")),
            repeat=int(request.get("repeat", request.get("--repeat", 1)) or 1),
            question_ids=request.get("question_ids", request.get("--question-ids")),
            job_id=job_id,
        )
    if source_action == "cycle":
        return task_cycle.delay(tenant_name, project_slug, job_id=job_id)
    if source_action == "verify":
        return task_verify.delay(tenant_name, project_slug, job_id=job_id)
    if source_action == "deliver":
        return task_deliver.delay(tenant_name, project_slug, job_id=job_id)
    if source_action == "archive":
        from api.archive.router import task_archive_project
        return task_archive_project.delay(tenant_name, project_slug, job_id=job_id)
    if source_action == "archive_restore":
        from api.archive.router import task_restore_project
        archive_id = request.get("archive_id")
        overwrite = bool(request.get("overwrite", False))
        if not archive_id:
            raise ValueError("archive_restore request is missing archive_id")
        return task_restore_project.delay(tenant_name, project_slug, archive_id, overwrite, job_id=job_id)
    if source_action == "outreach_send":
        from api.outreach.router import task_send_outreach
        draft_id = request.get("draft_id")
        if not draft_id:
            raise ValueError("outreach_send request is missing draft_id")
        return task_send_outreach.delay(tenant_name, project_slug, draft_id, job_id=job_id)
    return task_pipeline.delay(tenant_name, project_slug, source_action, params=request, job_id=job_id)
