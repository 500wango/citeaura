"""项目 CRUD、Bootstrap 和任务查询 API。"""

import json
import os
import re
import tempfile
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, status
from starlette.background import BackgroundTask
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy.orm import Session

from api.adapters import engine as engine_adapter
from api.adapters.engine import (
    ENGINE_KEY_ENV,
    geolib,
    job_log_path,
    load_custom_providers,
    load_tenant_keys,
    tenant_project_dir,
    with_tenant_read_context,
    with_tenant_context,
)
from api.adapters.exceptions import GeoEngineError
from api.adapters import audit_presentation, brand_identity, delivery, delivery_share, framing, global_scope, measurement, preflight, product_insights, report_quality, sampling_control, sampling_modes, ticket_workflow, workspace
from api.adapters.network import NetworkTargetError, validate_outbound_url
from api.auth.deps import get_current_user, require_editor, require_owner
from api.billing.limits import check_project_creation, check_sample_run
from api.billing.platform_pool import PAID_PLANS, public_catalog, usage_summary
from api.db import get_db
from api import config
from api.models import Job, Project, Tenant, User
from api.product_events import record_product_event
from api.worker.tasks import (
    PIPELINE_ACTIONS,
    task_bootstrap,
    task_cycle,
    task_deliver,
    task_pipeline,
    task_sample,
    task_verify,
)
from api.adapters.localization import localize_tickets
from api.adapters.log_translator import translate_engine_log


router = APIRouter(prefix="/api/v1/projects", tags=["projects"])
PLAYBOOK_PRIORITY = {"P0": 0, "P1": 1, "P2": 2}
PLAYBOOK_EFFORT = {"S": 0, "M": 1, "L": 2}
RETRYABLE_ACTIONS = frozenset((
    "bootstrap", "autopilot", "sample", "cycle", "verify", "deliver",
    "crawl", "audit", "deliverables", "plan", "expand", "blueprint", "generate", "lint", "report",
    "sample-sheet", "serve", "archive", "archive_restore", "outreach_send",
))


class ProjectCreate(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    name: str | None = Field(default=None, max_length=128)
    skip_llm: bool = False
    no_sample: bool = False

    @field_validator("url")
    @classmethod
    def normalize_url(cls, value: str):
        value = value.strip()
        if not value:
            raise ValueError("url is required")
        if "://" not in value:
            value = "https://" + value
        parsed = urlparse(value)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("url must be a valid http(s) URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("url must not contain credentials, query, or fragment")
        return value.rstrip("/")

class SampleRequest(BaseModel):
    limit: int | None = Field(default=None, ge=1, le=1000)
    platforms: list[str] | None = None
    repeat: int = Field(default=1, ge=1, le=10)
    question_ids: list[str] | None = Field(default=None, max_length=1000)


class ProjectPreflight(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    question_count: int = Field(default=30, ge=1, le=1000)
    platforms: list[str] | None = None

    @field_validator("url")
    @classmethod
    def normalize_url(cls, value: str):
        return preflight.normalize_url(value)


class TicketUpdate(BaseModel):
    status: str | None = None
    owner: str | None = Field(default=None, min_length=1, max_length=128)
    due_date: str | None = None
    note: str = Field(default="", max_length=2000)

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str):
        if value is None:
            return value
        if value not in ("todo", "doing", "done", "blocked", "wontfix"):
            raise ValueError("invalid ticket status")
        return value

    @field_validator("due_date")
    @classmethod
    def validate_due_date(cls, value):
        if value in (None, ""):
            return value
        date.fromisoformat(value)
        return value


class TicketBulkUpdate(TicketUpdate):
    ticket_ids: list[str] = Field(min_length=1, max_length=100)


class OffsiteTicketCreate(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    ask_text: str = Field(min_length=1, max_length=5000)
    influenced_questions: list[str] = Field(min_length=1, max_length=200)


class PipelineActionRequest(BaseModel):
    params: dict = Field(default_factory=dict)


class ScheduleRequest(BaseModel):
    interval_days: int = 0
    alert_on_regression: bool | None = None

    @field_validator("interval_days")
    @classmethod
    def validate_interval_days(cls, value: int):
        if value not in (0, 7, 14, 30):
            raise ValueError("interval_days must be 0, 7, 14, or 30")
        return value


class DeliverySendRequest(BaseModel):
    recipient_email: str | None = None


class SamplingFundingRequest(BaseModel):
    platform_pool_enabled: bool


class SamplingBudgetRequest(BaseModel):
    monthly_budget_cny_fen: int | None = Field(default=None, ge=0, le=100_000_000)
    sample_call_limit: int | None = Field(default=None, ge=1, le=1_000_000)
    pause_on_budget_exceeded: bool = True


class SampleEstimateRequest(BaseModel):
    limit: int | None = Field(default=None, ge=1, le=1000)
    platforms: list[str] | None = None
    repeat: int = Field(default=1, ge=1, le=10)
    question_ids: list[str] | None = Field(default=None, max_length=1000)


def _error(status_code: int, message: str):
    """抛出统一 API 错误。"""
    raise HTTPException(status_code=status_code, detail={"error": message})


def _tenant_for_user(db: Session, user: User, for_update=False) -> Tenant:
    if for_update:
        tenant = db.query(Tenant).filter(Tenant.id == user.tenant_id).with_for_update().first()
    else:
        tenant = db.get(Tenant, user.tenant_id)
    if tenant is None:
        _error(status.HTTP_403_FORBIDDEN, "no_tenant_membership")
    return tenant


def _project_for_user(db: Session, user: User, project_id: int) -> Project:
    tenant = _tenant_for_user(db, user)
    project = (
        db.query(Project)
        .filter(
            Project.id == project_id,
            Project.tenant_id == tenant.id,
            Project.archived_at.is_(None),
            Project.status != "archived",
        )
        .first()
    )
    if project is None:
        _error(status.HTTP_404_NOT_FOUND, "project_not_found")
    return project


def _job_payload(job: Job, include_log: bool = True, log_offset: int | None = None) -> dict:
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
    derived_stage, derived_progress = _progress_from_log(log)
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
        "request": _request_payload(job.request_json),
        "celery_task_id": job.celery_task_id,
        "retry_of_job_id": job.retry_of_job_id,
        "can_retry": job.status == "failed" and job.action in RETRYABLE_ACTIONS,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "error": translate_engine_log(job.error) if job.error else None,
        "log": translate_engine_log(log),
        "log_offset": next_offset,
    }


def _progress_from_log(log: str):
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


def _request_payload(value):
    if not value:
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


def _safe_request_json(action, params=None):
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


def _latest_file(directory: Path, pattern: str):
    files = sorted(directory.glob(pattern)) if directory.exists() else []
    return files[-1] if files else None


def _active_job(db: Session, project_id: int):
    return db.query(Job).filter(
        Job.project_id == project_id,
        Job.status.in_(("queued", "running")),
    ).order_by(Job.id.desc()).first()


def _require_project_questions(tenant: Tenant, project: Project):
    """采样入队前确认项目已有目标问题。"""
    try:
        with with_tenant_read_context(tenant, project.slug):
            config = workspace.ensure_global_engine_scope(project.slug)
    except GeoEngineError:
        config = {}
    if not config.get("questions"):
        _error(status.HTTP_409_CONFLICT, "project_questions_required")


def _normalize_sample_question_ids(tenant: Tenant, project: Project, payload: SampleRequest):
    """验证问题级采样范围，避免把错误 ID 投递到 Worker 后才失败。"""
    if not payload.question_ids:
        return payload
    with with_tenant_read_context(tenant, project.slug):
        config = workspace.ensure_global_engine_scope(project.slug)
    valid = {
        str(question.get("id"))
        for question in config.get("questions") or []
        if isinstance(question, dict) and question.get("id")
    }
    selected = []
    for value in payload.question_ids:
        question_id = str(value).strip()
        if question_id and question_id not in selected:
            selected.append(question_id)
    unknown = [question_id for question_id in selected if question_id not in valid]
    if unknown:
        _error(status.HTTP_422_UNPROCESSABLE_ENTITY, "sample_question_not_found")
    return payload.model_copy(update={"question_ids": selected or None})


def _available_outputs(project_slug):
    directory = geolib.project_dir(project_slug)
    return {
        "audit": (directory / "audit.json").is_file(),
        "metrics": bool(list((directory / "metrics").glob("*.json"))) if (directory / "metrics").exists() else False,
        "tasks": (directory / "tasks.json").is_file(),
        "delivery": bool(list((directory / "delivery").glob("*"))) if (directory / "delivery").exists() else False,
    }


def _project_directory_exists(tenant_name: str, project_slug: str) -> bool:
    return (engine_adapter.WORK_ROOT / engine_adapter.tenant_slug(tenant_name) / project_slug).is_dir()


def _dispatch_retry(task_name, tenant_name, project_slug, request, job_id, source_action):
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


def _grade_for_score(score):
    if score is None:
        return None
    if score >= 90:
        return "A"
    if score >= 75:
        return "B"
    if score >= 60:
        return "C"
    return "D"


def _engine_rows_by_mode(item, platform_rows):
    """Keep knowledge, retrieval, and product-surface cohorts on separate rows."""
    grouped = {}
    for row in platform_rows:
        grouped.setdefault(sampling_modes.for_row(row), []).append(row)
    if not grouped:
        return [{
            "engine_code": item.get("platform"),
            "engine_name": item.get("label") or item.get("platform"),
            "sampling_mode": sampling_modes.MODE_API,
            "mention_rate": item.get("mention"),
            "mention_interval": None,
            "median_rank": item.get("pos_median"),
            "sample_count": item.get("samples", 0),
            "citation_share": item.get("cite_share"),
            "citation_counts": item.get("cite_counts", [0, 0]),
            "top_sources": item.get("top_sources", []),
            "example": item.get("example"),
            "negative_sample_count": item.get("neg_n", 0),
        }]
    rows = []
    for mode, mode_rows in grouped.items():
        ok_rows = [row for row in mode_rows if row.get("ok")]
        mentioned = [
            row for row in ok_rows
            if (row.get("analysis") or {}).get("brand_mentioned")
        ]
        ranks = [
            (row.get("analysis") or {}).get("brand_rank")
            for row in mentioned
            if (row.get("analysis") or {}).get("brand_rank")
        ]
        ranks = [value for value in ranks if value]
        mention_rate = (len(mentioned) / len(ok_rows)) if ok_rows else None
        rows.append({
            "engine_code": item.get("platform"),
            "engine_name": item.get("label") or item.get("platform"),
            "sampling_mode": mode,
            "mention_rate": mention_rate,
            "mention_interval": measurement.wilson_interval(len(mentioned), len(ok_rows)),
            "median_rank": sorted(ranks)[len(ranks) // 2] if ranks else None,
            "sample_count": len(ok_rows),
            "citation_share": item.get("cite_share") if len(grouped) == 1 else None,
            "citation_counts": item.get("cite_counts", [0, 0]) if len(grouped) == 1 else [0, 0],
            "top_sources": item.get("top_sources", []) if len(grouped) == 1 else [],
            "example": item.get("example"),
            "negative_sample_count": sum(
                1 for row in ok_rows if (row.get("analysis") or {}).get("negative_cues")
            ),
        })
    mode_order = {
        sampling_modes.MODE_SEARCH: 0,
        sampling_modes.MODE_API: 1,
        sampling_modes.MODE_MANUAL: 2,
    }
    rows.sort(key=lambda item: mode_order.get(item["sampling_mode"], 9))
    return rows


def _include_configured_engines(db, tenant, engines):
    """把已配置但尚未采到样本的引擎补成 Unmeasured 行。"""
    import sample

    rows = list(engines or [])
    seen = {str(item.get("engine_code") or "") for item in rows}
    configured = set(load_tenant_keys(db, tenant.id))
    custom = load_custom_providers(db, tenant.id)
    for code in list(ENGINE_KEY_ENV) + [provider["code"] for provider in custom]:
        if code in seen:
            continue
        if code not in configured and not any(provider["code"] == code for provider in custom):
            if code not in ENGINE_KEY_ENV:
                continue
        provider = sample.PROVIDERS.get(code) or next(
            (item for item in custom if item["code"] == code),
            {"name": code, "search": False},
        )
        rows.append({
            "engine_code": code,
            "engine_name": provider.get("name") or code,
            "sampling_mode": sampling_modes.for_provider(provider),
            "mention_rate": None,
            "mention_interval": None,
            "median_rank": None,
            "sample_count": 0,
            "citation_share": None,
            "citation_counts": [0, 0],
            "top_sources": [],
            "example": None,
            "negative_sample_count": 0,
        })
        seen.add(code)
    return rows


def _provider_identity(code, item, config):
    """Return one stable provider identity object for API/UI consumers."""
    import sample

    code = str(code or "")
    item = item if isinstance(item, dict) else {}
    config = config if isinstance(config, dict) else {}
    labels = config.get("provider_labels") if isinstance(config.get("provider_labels"), dict) else {}
    model_ids = config.get("provider_model_ids") if isinstance(config.get("provider_model_ids"), dict) else {}
    provider = sample.PROVIDERS.get(code) or {}
    provider_name = str(labels.get(code) or item.get("engine_name") or item.get("label") or provider.get("name") or code)
    model_id = str(model_ids.get(code) or item.get("model_id") or provider.get("model") or "")
    internal_custom = code == "custom" or code.startswith("custom_")
    if internal_custom and not labels.get(code):
        provider_name = "Configured OpenAI-compatible provider"
    mode = item.get("sampling_mode") or sampling_modes.for_provider(provider)
    return {
        "engine_code": code,
        "provider_name": provider_name,
        "model_id": model_id or None,
        "sampling_mode": mode,
        "funding_source": item.get("source") or item.get("funding_source") or "unknown",
    }


def _current_sample_rows(project_slug, config=None):
    """读取当前问题集样本，统一过滤历史身份和市场残留。"""
    config = config or geolib.load_config(project_slug)
    project_directory = geolib.project_dir(project_slug)
    sample_path = _latest_file(project_directory / "samples", "*.jsonl")
    rows = [
        row for row in (geolib.read_jsonl(sample_path) if sample_path else [])
        if global_scope.is_global_sample(row) and brand_identity.is_current_sample(row, config)
    ]
    return sample_path, rows


def _product_report(project_slug, metrics):
    """Normalize filesystem artifacts into the stable product report contract."""
    import analytics

    project_directory = geolib.project_dir(project_slug)
    config = geolib.load_config(project_slug)
    audit = audit_presentation.present_audit(project_slug)
    sample_path, rows = _current_sample_rows(project_slug, config)
    engine_rows = analytics.engines(project_slug, rows, metrics)
    insights = product_insights.build(
        project_slug,
        rows,
        config,
        geolib.read_json(project_directory / "blueprint.json", None),
        expected_cohorts=((metrics or {}).get("provenance") or {}).get("platforms") or [],
    )

    engines = []
    citations = {}
    for item in engine_rows:
        platform_rows = [row for row in rows if row.get("platform") == item.get("platform")]
        engines.extend(_engine_rows_by_mode(item, platform_rows))
        for row in platform_rows:
            if not row.get("ok"):
                continue
            for domain in (row.get("analysis") or {}).get("cited_domains") or []:
                evidence = citations.setdefault(domain, {
                    "count": 0,
                    "engines": set(),
                    "questions": set(),
                })
                evidence["count"] += 1
                engine_name = row.get("platform_name") or row.get("platform")
                if engine_name:
                    evidence["engines"].add(engine_name)
                if row.get("question"):
                    evidence["questions"].add(row["question"])

    measured = [item for item in engines if item["mention_rate"] is not None and item["sample_count"]]
    for item in engines:
        identity = _provider_identity(item.get("engine_code"), item, config)
        item["provider_identity"] = identity
        item["provider_name"] = identity["provider_name"]
        item["model_id"] = identity["model_id"]
    measured_count = sum(item["sample_count"] for item in measured)
    mention_rate = (
        sum(item["mention_rate"] * item["sample_count"] for item in measured) / measured_count
        if measured_count else None
    )
    channels = [
        {
            "domain": domain,
            "count": evidence["count"],
            "engines": sorted(evidence["engines"]),
            "question_count": len(evidence["questions"]),
            "sample_questions": sorted(evidence["questions"])[:3],
        }
        for domain, evidence in sorted(
            citations.items(), key=lambda pair: (-pair[1]["count"], pair[0]),
        )
    ]
    return {
        **(metrics or {}),
        "mention_rate": round(mention_rate, 4) if mention_rate is not None else None,
        "grade": audit.get("applicable_grade") or _grade_for_score(audit.get("avg_score")),
        "engines": engines,
        "channels": channels,
        "audit": audit,
        "insights": insights,
        "measured": bool(measured),
        "sample_artifact": sample_path.stem if sample_path else None,
    }


def _top_actions(tickets, limit=3):
    indexed = [(index, item) for index, item in enumerate(tickets or []) if isinstance(item, dict)]
    indexed = [pair for pair in indexed if pair[1].get("status") not in ("done", "wontfix")]
    indexed.sort(key=lambda pair: (
        PLAYBOOK_PRIORITY.get(pair[1].get("priority"), 99),
        PLAYBOOK_EFFORT.get(pair[1].get("effort"), 99),
        pair[0],
    ))
    items = []
    for _, raw in indexed[:limit]:
        item = dict(raw)
        evidence = item.get("evidence") or []
        if not isinstance(evidence, list):
            evidence = [evidence]
        first_evidence = evidence[0] if evidence and isinstance(evidence[0], dict) else {}
        item.setdefault("why", item.get("reason") or first_evidence.get("detail") or "High-priority action; recommended for completion this cycle")
        item.setdefault("action", item.get("title") or item.get("description") or "Execute ticket playbook")
        item.setdefault("owner", item.get("owner") or "GEO Strategist")
        item.setdefault("acceptance", item.get("acceptance") or {"type": "manual", "desc": "Re-run verification after deployment"})
        item["evidence"] = evidence
        items.append(item)
    return localize_tickets(items)


def _schedule_payload(project: Project):
    return {
        "enabled": project.schedule_interval_days in (7, 14, 30),
        "interval_days": project.schedule_interval_days or 0,
        "next_run_at": project.schedule_next_run_at,
        "last_enqueued_at": project.schedule_last_enqueued_at,
        "alert_on_regression": bool(project.alert_on_regression),
        "alert_email_ready": config.auth_smtp_configured(),
    }


def _competitor_discovery_payload(config):
    """返回自动发现竞品的候选与采样确认状态。"""
    items = []
    for competitor in config.get("competitors", []) or []:
        name = competitor.get("name") if isinstance(competitor, dict) else None
        if not isinstance(name, str) or not name.strip():
            continue
        aliases = competitor.get("aliases", [])
        aliases = aliases if isinstance(aliases, list) else []
        alias_review = competitor.get("alias_review", [])
        alias_review = alias_review if isinstance(alias_review, list) else []
        confirmed = competitor.get("confirmed")
        if confirmed is True:
            discovery_status = "sample_confirmed"
        elif confirmed is False:
            discovery_status = "candidate"
        else:
            discovery_status = "configured"
        items.append({
            "name": name.strip(),
            "aliases": [alias for alias in aliases if isinstance(alias, str) and alias],
            "alias_review": [item for item in alias_review if isinstance(item, dict)],
            "market": "global",
            "relationship": competitor.get("relationship") or "direct_competitor",
            "relationship_confidence": competitor.get("relationship_confidence") or "needs_review",
            "relationship_review_required": competitor.get("relationship_review_required") is not False,
            "benchmark_eligible": competitor.get("benchmark_eligible") is not False,
            "domain": competitor.get("domain") or competitor.get("official_url") or competitor.get("url"),
            "discovery_status": discovery_status,
        })
    return {
        "items": items,
        "summary": {
            "total": len(items),
            "sample_confirmed": sum(item["discovery_status"] == "sample_confirmed" for item in items),
            "candidate": sum(item["discovery_status"] == "candidate" for item in items),
            "configured": sum(item["discovery_status"] == "configured" for item in items),
        },
    }


def _sampling_funding_payload(db, tenant, project, user):
    byok = sorted(load_tenant_keys(db, tenant.id))
    custom_codes = {provider["code"] for provider in load_custom_providers(db, tenant.id)}
    catalog = public_catalog()
    pool_codes = {item["engine_code"] for item in catalog}
    effective = []
    for code in sorted(set(ENGINE_KEY_ENV) | pool_codes | set(byok) | custom_codes):
        if code in byok or code in custom_codes:
            source = "byok"
        elif project.platform_pool_enabled and tenant.plan in PAID_PLANS and code in pool_codes:
            source = "platform_pool"
        else:
            source = "unavailable"
        effective.append({"engine_code": code, "source": source})
    return {
        "project_id": project.id,
        "platform_pool_enabled": bool(project.platform_pool_enabled),
        "eligible": tenant.plan in PAID_PLANS,
        "can_edit": getattr(user, "tenant_role", None) == "owner",
        "plan": tenant.plan,
        "byok_engines": byok,
        "pool_engines": catalog,
        "effective_engines": effective,
        "usage": usage_summary(db, tenant),
        "budget_settings": {
            "monthly_budget_cny_fen": project.monthly_budget_cny_fen,
            "sample_call_limit": project.sample_call_limit,
            "pause_on_budget_exceeded": bool(project.pause_on_budget_exceeded),
        },
    }


def _has_api_keys(db, tenant_id):
    return bool(load_tenant_keys(db, tenant_id))


def _enable_platform_pool_if_available(tenant, project):
    """Paid workspaces can run the first matrix from the platform pool without filling every BYOK key."""
    if project.platform_pool_enabled:
        return True
    if tenant.plan in PAID_PLANS and public_catalog():
        project.platform_pool_enabled = True
        return True
    return False


def _has_sampling_access(db, tenant, project):
    return (
        _has_api_keys(db, tenant.id)
        or bool(load_custom_providers(db, tenant.id))
        or bool(project.platform_pool_enabled and tenant.plan in PAID_PLANS and public_catalog())
    )


def _sample_estimate(db, tenant, project, payload, enforce=False, allow_pool=True):
    import sample

    platforms = payload.platforms if payload else None
    custom_codes = {provider["code"] for provider in load_custom_providers(db, tenant.id)}
    if platforms and any(
        code in global_scope.DOMESTIC_PLATFORM_CODES
        or (code not in sample.PROVIDERS and code not in custom_codes)
        for code in platforms
    ):
        _error(status.HTTP_422_UNPROCESSABLE_ENTITY, "sample_platform_must_have_api")
    function = sampling_control.ensure_allowed if enforce else sampling_control.estimate
    try:
        return function(
            db, tenant, project,
            platforms=platforms,
            limit=payload.limit if payload else None,
            repeat=payload.repeat if payload else 1,
            question_ids=payload.question_ids if payload else None,
            allow_pool=allow_pool,
        )
    except sampling_control.SamplingBudgetExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": exc.code, "estimate": exc.estimate},
        ) from exc


def _normalize_sample_estimate_payload(tenant, project, payload):
    payload = payload or SampleEstimateRequest()
    if payload.question_ids:
        sample_payload = SampleRequest(
            limit=payload.limit,
            platforms=payload.platforms,
            repeat=payload.repeat,
            question_ids=payload.question_ids,
        )
        payload = payload.model_copy(update={
            "question_ids": _normalize_sample_question_ids(tenant, project, sample_payload).question_ids,
        })
    return payload


def _validated_sample_estimate(db, tenant, project, payload, enforce=False, allow_pool=True):
    payload = _normalize_sample_estimate_payload(tenant, project, payload)
    return _sample_estimate(db, tenant, project, payload, enforce=enforce, allow_pool=allow_pool)


def _reserve_sample_estimate(db, tenant, project, job, payload):
    try:
        return sampling_control.reserve(
            db, tenant, project, job,
            platforms=payload.platforms if payload else None,
            limit=payload.limit if payload else None,
            repeat=payload.repeat if payload else 1,
            question_ids=payload.question_ids if payload else None,
        )
    except sampling_control.SamplingBudgetExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": exc.code, "estimate": exc.estimate},
        ) from exc


def _pipeline_sample_payload(params):
    def value(name, default=None):
        return params.get(f"--{name}", params.get(name, default))

    platforms = value("platforms")
    if isinstance(platforms, str):
        platforms = [item.strip() for item in platforms.split(",") if item.strip()]
    question_ids = value("question-ids")
    if isinstance(question_ids, str):
        question_ids = [item.strip() for item in question_ids.split(",") if item.strip()]
    try:
        return SampleEstimateRequest(
            limit=value("limit"),
            platforms=platforms,
            repeat=value("repeat", 1),
            question_ids=question_ids,
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "invalid_sample_parameters", "detail": str(exc)},
        ) from exc


def _pipeline_flag(params, name):
    return params.get(f"--{name}", params.get(name, False)) is True


@router.post("/preflight")
def project_preflight(
    payload: ProjectPreflight,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """创建项目之前检查站点、采样能力并估算调用量。"""
    tenant = _tenant_for_user(db, current_user)
    import sample

    custom_providers = load_custom_providers(db, tenant.id)
    custom_codes = {provider["code"] for provider in custom_providers}
    available = set(sample.PROVIDERS) - global_scope.DOMESTIC_PLATFORM_CODES
    byok = set(load_tenant_keys(db, tenant.id))
    catalog = public_catalog() if tenant.plan in PAID_PLANS else []
    pool_codes = {item["engine_code"] for item in catalog}
    funding = {"keys": {code: True for code in byok}, "pool_codes": pool_codes}
    requested = list(dict.fromkeys(payload.platforms or sampling_control.default_sample_platforms(
        funding, custom_providers, sorted(available | custom_codes),
    )))
    invalid = sorted(set(requested) - available - custom_codes)
    if invalid:
        _error(status.HTTP_422_UNPROCESSABLE_ENTITY, "unsupported_api_platform")
    effective = [
        code for code in requested
        if code in byok or code in pool_codes or code in custom_codes
    ]
    pool_only = [code for code in effective if code in pool_codes and code not in byok]
    prices = {item["engine_code"]: item["unit_price_cny_fen"] for item in catalog}
    quick_questions = min(5, payload.question_count)
    full_questions = payload.question_count
    quick_calls = quick_questions * len(effective)
    full_calls = full_questions * len(effective)
    site = preflight.run(payload.url)
    return {
        "site": site,
        "byok_engines": sorted(byok),
        "pool_engines": sorted(pool_codes),
        "manual_only": [
            {"engine_code": code, "name": name, "sampling_mode": sampling_modes.MODE_MANUAL, "market": market}
            for code, (name, market) in sorted(sample.MANUAL_ONLY.items())
            if market == "global"
        ],
        "requested_platforms": requested,
        "effective_platforms": effective,
        "can_sample": bool(site["ready"] and effective),
        "estimate": {
            "quick": {"questions": quick_questions, "platforms": len(effective), "calls": quick_calls,
                      "minutes": max(1, round(quick_calls * 0.4)) if quick_calls else 0},
            "full": {"questions": full_questions, "platforms": len(effective), "calls": full_calls,
                     "minutes": max(1, round(full_calls * 0.4)) if full_calls else 0},
            "repeat": 1,
            "platform_pool_cost_cny_fen": sum(full_questions * prices[code] for code in pool_only if code in prices),
            "cost_note": "BYOK costs are billed directly by API providers. Platform-pool engines are billed by CiteAura at the listed unit price.",
        },
    }


@router.post("", status_code=status.HTTP_202_ACCEPTED)
def create_project(
    payload: ProjectCreate,
    current_user: User = Depends(require_editor),
    db: Session = Depends(get_db),
):
    """创建项目、初始化引擎目录并投递 Bootstrap 任务。"""
    try:
        validate_outbound_url(payload.url, require_https=False)
    except NetworkTargetError as exc:
        _error(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
    tenant = _tenant_for_user(db, current_user, for_update=True)
    slug = geolib.slugify(payload.url)
    existing = db.query(Project).filter(Project.tenant_id == tenant.id, Project.slug == slug).first()
    if existing is not None and existing.archived_at is None and existing.status != "archived":
        _error(status.HTTP_409_CONFLICT, "project_already_exists")
    if existing is None or (existing.archived_at is None and existing.status != "archived"):
        check_project_creation(db, tenant)

    restoring_existing_workspace = existing is not None and _project_directory_exists(tenant.directory_slug, slug)
    if existing is not None:
        project = existing
        project.url = payload.url
        project.market = "global"
        project.status = "initializing"
        project.archived_at = None
        project.schedule_interval_days = None
        project.schedule_next_run_at = None
    else:
        project = Project(
            tenant_id=tenant.id,
            slug=slug,
            url=payload.url,
            market="global",
            status="initializing",
        )
        db.add(project)
    db.flush()
    if not payload.no_sample:
        _enable_platform_pool_if_available(tenant, project)
    has_sampling_access = _has_sampling_access(db, tenant, project)
    skip_llm = payload.skip_llm or not has_sampling_access
    no_sample = payload.no_sample or not has_sampling_access
    job_action = "bootstrap" if no_sample else "autopilot"
    if job_action == "autopilot":
        check_sample_run(db, tenant, project)
    job = Job(
        project_id=project.id,
        action=job_action,
        status="queued",
        stage="initializing",
        request_json=json.dumps({"skip_llm": skip_llm, "no_sample": no_sample, "job_action": job_action}),
    )
    db.add(job)
    record_product_event(
        db,
        "project_created",
        tenant_id=tenant.id,
        user_id=current_user.id,
        country_code=tenant.acquisition_country_code,
        properties={"project_id": project.id, "job_action": job_action},
    )
    db.commit()
    db.refresh(project)
    db.refresh(job)

    if not restoring_existing_workspace:
        try:
            import geo

            args = SimpleNamespace(
                url=payload.url,
                name=payload.name.strip() if payload.name else None,
                slug=slug,
                market="global",
                max_pages=25,
                force=False,
            )
            with with_tenant_context(tenant.directory_slug, slug):
                geo.cmd_init(args)
        except GeoEngineError as exc:
            project.status = "failed"
            job.status = "failed"
            job.stage = "failed"
            job.error = str(exc)
            job.finished_at = datetime.now(timezone.utc)
            db.commit()
            _error(status.HTTP_400_BAD_REQUEST, "engine_init_failed")
        except Exception as exc:  # noqa: BLE001
            project.status = "failed"
            job.status = "failed"
            job.stage = "failed"
            job.error = f"{type(exc).__name__}: {exc}"
            job.finished_at = datetime.now(timezone.utc)
            db.commit()
            _error(status.HTTP_500_INTERNAL_SERVER_ERROR, "project_init_failed")

    project.status = "bootstrapping"
    job.log_path = str(job_log_path(tenant.directory_slug, project.slug, job.id))
    db.commit()
    try:
        task_result = task_bootstrap.delay(
            tenant.directory_slug,
            slug,
            skip_llm=skip_llm,
            no_sample=no_sample,
            job_action=job_action,
            job_id=job.id,
        )
        job.celery_task_id = getattr(task_result, "id", None)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        project.status = "failed"
        job.status = "failed"
        job.stage = "failed"
        job.error = f"{type(exc).__name__}: {exc}"
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
        _error(status.HTTP_503_SERVICE_UNAVAILABLE, "worker_unavailable")

    return {
        "project_id": project.id,
        "job_id": job.id,
        "action": job_action,
        "slug": project.slug,
        "status": project.status,
    }


@router.get("")
def list_projects(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """列出当前租户项目。"""
    tenant = _tenant_for_user(db, current_user)
    projects = (
        db.query(Project)
        .filter(Project.tenant_id == tenant.id, Project.archived_at.is_(None), Project.status != "archived")
        .order_by(Project.created_at.desc(), Project.id.desc())
        .all()
    )
    summaries = {}
    if projects:
        try:
            with with_tenant_read_context(tenant, projects[0].slug):
                import dashboard

                for project in projects:
                    workspace.ensure_global_engine_scope(project.slug)
                summaries = {item["slug"]: item for item in dashboard.list_projects()}
        except Exception:  # noqa: BLE001 - 损坏的管线摘要不能阻断 DB 项目列表
            summaries = {}
    return {
        "projects": [
            {
                "id": p.id,
                "slug": p.slug,
                "url": p.url,
                "name": summaries.get(p.slug, {}).get("name", p.slug),
                "site": summaries.get(p.slug, {}).get("site", p.url),
                "market": p.market,
                "status": p.status,
                "avg_score": summaries.get(p.slug, {}).get("avg_score"),
                "pages": summaries.get(p.slug, {}).get("pages"),
                "tasks_total": summaries.get(p.slug, {}).get("tasks_total", 0),
                "tasks_done": summaries.get(p.slug, {}).get("tasks_done", 0),
                "p0_open": summaries.get(p.slug, {}).get("p0_open", 0),
                "created_at": p.created_at,
            }
            for p in projects
        ]
    }


@router.get("/actions")
def pipeline_actions(current_user: User = Depends(get_current_user)):
    """返回 SaaS worker 支持的引擎动作白名单。"""
    return {"actions": PIPELINE_ACTIONS}


@router.get("/{project_id}")
def project_detail(project_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """返回项目索引和引擎 dashboard 聚合详情。"""
    project = _project_for_user(db, current_user, project_id)
    tenant = _tenant_for_user(db, current_user)
    try:
        with with_tenant_read_context(tenant, project.slug):
            import dashboard

            cfg = workspace.ensure_global_engine_scope(project.slug)
            detail = dashboard.project(project.slug)
            detail["questions"] = cfg.get("questions", [])
            detail["competitor_discovery"] = _competitor_discovery_payload(cfg)
            _, current_rows = _current_sample_rows(project.slug, cfg)
            metrics_path = _latest_file(geolib.project_dir(project.slug) / "metrics", "*.json")
            latest_metrics = geolib.read_json(metrics_path, {}) if metrics_path else {}
            detail["insights"] = product_insights.build(
                project.slug,
                current_rows,
                cfg,
                detail.get("blueprint"),
                expected_cohorts=((latest_metrics.get("provenance") or {}).get("platforms") or []),
            )
            detail["report_quality"] = report_quality.assess(project.slug, _has_sampling_access(db, tenant, project))
    except GeoEngineError:
        detail = {
            "slug": project.slug,
            "brand": {},
            "questions": [],
            "competitor_discovery": _competitor_discovery_payload({}),
            "insights": {
                "prompt_explorer": {"items": [], "measured_count": 0, "total_count": 0, "minimum_samples": 3},
                "competitor_heatmap": {"entities": [], "cohorts": [], "questions": [], "sample_count": 0},
                "takeover_alerts": [],
                "campaign_proposals": {
                    "items": [],
                    "counts": {"blocked": 0, "review_required": 0, "ready_for_approval": 0},
                    "total_count": 0,
                    "source_summary": {
                        "prompt_candidates": 0,
                        "takeover_candidates": 0,
                        "tickets": 0,
                        "assets": 0,
                        "brand_facts": "missing",
                    },
                    "policy": {
                        "human_approval_required": True,
                        "automatic_publication": False,
                        "impact_claims": "hypothesis_only",
                    },
                },
            },
            "report_quality": {"score": 0, "level": "missing", "effective_report": False, "issues": []},
        }
    detail["project"] = {
        "id": project.id,
        "slug": project.slug,
        "url": project.url,
        "market": project.market,
        "status": project.status,
        "created_at": project.created_at,
    }
    detail["tasks"] = localize_tickets(ticket_workflow.enrich(detail.get("tasks", [])))
    detail["top_actions"] = _top_actions(detail.get("tasks", []))
    return detail


@router.get("/{project_id}/status")
def project_status(project_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """返回文件系统项目进度和最近任务状态。"""
    project = _project_for_user(db, current_user, project_id)
    tenant = _tenant_for_user(db, current_user)
    with with_tenant_read_context(tenant, project.slug):
        import dashboard

        workspace.ensure_global_engine_scope(project.slug)
        summary = next(
            (item for item in dashboard.list_projects() if item.get("slug") == project.slug),
            {
                "slug": project.slug,
                "name": project.slug,
                "site": project.url,
                "market": project.market,
                "avg_score": None,
                "pages": None,
                "tasks_total": 0,
                "tasks_done": 0,
                "p0_open": 0,
            },
        )
        quality = report_quality.assess(project.slug, _has_sampling_access(db, tenant, project))
        outputs = _available_outputs(project.slug)
    latest_job = db.query(Job).filter(Job.project_id == project.id).order_by(Job.id.desc()).first()
    return {
        "project_id": project.id,
        "slug": project.slug,
        "status": project.status,
        "summary": summary,
        "available_outputs": outputs,
        "report_quality": quality,
        "latest_job": _job_payload(latest_job, include_log=False) if latest_job else None,
    }


@router.get("/{project_id}/schedule")
def project_schedule(project_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """返回项目周期复跑设置。"""
    project = _project_for_user(db, current_user, project_id)
    return {"schedule": _schedule_payload(project)}


@router.get("/{project_id}/sampling-funding")
def sampling_funding(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """返回项目采样的 BYOK/平台代付来源及本月计费。"""
    project = _project_for_user(db, current_user, project_id)
    tenant = _tenant_for_user(db, current_user)
    return _sampling_funding_payload(db, tenant, project, current_user)


@router.put("/{project_id}/sampling-funding")
def update_sampling_funding(
    project_id: int,
    payload: SamplingFundingRequest,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """owner 显式启停按量计费的平台 Key 后备。"""
    project = _project_for_user(db, current_user, project_id)
    tenant = _tenant_for_user(db, current_user)
    if payload.platform_pool_enabled:
        if tenant.plan not in PAID_PLANS:
            _error(status.HTTP_403_FORBIDDEN, "platform_pool_paid_plan_required")
        if not public_catalog():
            _error(status.HTTP_409_CONFLICT, "platform_pool_unavailable")
    project.platform_pool_enabled = payload.platform_pool_enabled
    db.commit()
    return _sampling_funding_payload(db, tenant, project, current_user)


@router.get("/{project_id}/sampling-budget")
def sampling_budget(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """返回项目预算、当月平台代付用量和默认采样估算。"""
    project = _project_for_user(db, current_user, project_id)
    tenant = _tenant_for_user(db, current_user)
    return _validated_sample_estimate(db, tenant, project, SampleEstimateRequest())


@router.put("/{project_id}/sampling-budget")
def update_sampling_budget(
    project_id: int,
    payload: SamplingBudgetRequest,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """设置项目月度平台预算、单次调用上限和超额暂停策略。"""
    project = _project_for_user(db, current_user, project_id)
    tenant = _tenant_for_user(db, current_user)
    project.monthly_budget_cny_fen = payload.monthly_budget_cny_fen
    project.sample_call_limit = payload.sample_call_limit
    project.pause_on_budget_exceeded = payload.pause_on_budget_exceeded
    db.commit()
    return _validated_sample_estimate(db, tenant, project, SampleEstimateRequest())


@router.post("/{project_id}/sample/estimate")
def estimate_project_sample(
    project_id: int,
    payload: SampleEstimateRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """在任务投递前按问题集、平台和轮次估算调用量。"""
    project = _project_for_user(db, current_user, project_id)
    tenant = _tenant_for_user(db, current_user)
    return _validated_sample_estimate(db, tenant, project, payload)


@router.post("/{project_id}/schedule")
def update_project_schedule(
    project_id: int,
    payload: ScheduleRequest,
    current_user: User = Depends(require_editor),
    db: Session = Depends(get_db),
):
    """启用 7/14/30 天周期复跑，传 0 时关闭。"""
    project = _project_for_user(db, current_user, project_id)
    tenant = _tenant_for_user(db, current_user)
    if payload.interval_days == 0:
        project.schedule_interval_days = None
        project.schedule_next_run_at = None
    else:
        check_sample_run(db, tenant, project)
        if project.monthly_budget_cny_fen is not None or project.sample_call_limit is not None:
            _validated_sample_estimate(db, tenant, project, SampleEstimateRequest(), enforce=True)
        if project.schedule_interval_days != payload.interval_days or project.schedule_next_run_at is None:
            project.schedule_next_run_at = datetime.now(timezone.utc) + timedelta(days=payload.interval_days)
        project.schedule_interval_days = payload.interval_days
    if payload.alert_on_regression is not None:
        project.alert_on_regression = bool(payload.alert_on_regression)
    db.commit()
    db.refresh(project)
    return {"schedule": _schedule_payload(project)}


@router.get("/{project_id}/jobs")
def project_jobs(project_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """返回当前项目任务历史。"""
    project = _project_for_user(db, current_user, project_id)
    jobs = db.query(Job).filter(Job.project_id == project.id).order_by(Job.id.desc()).all()
    return {"jobs": [_job_payload(job, include_log=False) for job in jobs]}


@router.get("/{project_id}/jobs/{job_id}")
def project_job(
    project_id: int,
    job_id: int,
    offset: int | None = Query(default=None, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """返回任务状态、错误和可用日志尾部。"""
    project = _project_for_user(db, current_user, project_id)
    job = db.query(Job).filter(Job.id == job_id, Job.project_id == project.id).first()
    if job is None:
        _error(status.HTTP_404_NOT_FOUND, "job_not_found")
    return {"job": _job_payload(job, log_offset=offset)}


@router.post("/{project_id}/jobs/{job_id}/retry", status_code=status.HTTP_202_ACCEPTED)
def retry_project_job(
    project_id: int,
    job_id: int,
    current_user: User = Depends(require_editor),
    db: Session = Depends(get_db),
):
    """重试失败任务并保留 retry_of_job_id 链。"""
    project = _project_for_user(db, current_user, project_id)
    tenant = _tenant_for_user(db, current_user)
    source = db.query(Job).filter(Job.id == job_id, Job.project_id == project.id).first()
    if source is None:
        _error(status.HTTP_404_NOT_FOUND, "job_not_found")
    if source.status != "failed":
        _error(status.HTTP_409_CONFLICT, "job_not_failed")
    if source.action not in RETRYABLE_ACTIONS:
        _error(status.HTTP_409_CONFLICT, "job_retry_not_supported")
    if _active_job(db, project.id) is not None:
        _error(status.HTTP_409_CONFLICT, "project_job_already_running")
    if source.action == "sample":
        _require_project_questions(tenant, project)
    request = _request_payload(source.request_json)
    request_no_sample = _pipeline_flag(request, "no-sample") or _pipeline_flag(request, "no_sample")
    estimate = None
    if source.action in ("sample", "cycle", "autopilot", "serve"):
        if source.action not in ("autopilot", "serve") or not request_no_sample:
            check_sample_run(db, tenant, project)
            estimate = _validated_sample_estimate(
                db,
                tenant,
                project,
                _pipeline_sample_payload(request),
                enforce=True,
            )
    job = Job(
        project_id=project.id,
        action=source.action,
        status="queued",
        stage="queued",
        attempt=(source.attempt or 1) + 1,
        request_json=source.request_json,
        retry_of_job_id=source.id,
    )
    db.add(job)
    project.status = {
        "sample": "sampling", "verify": "verifying", "deliver": "delivering", "bootstrap": "bootstrapping",
        "autopilot": "bootstrapping", "cycle": "processing",
    }.get(source.action, "processing")
    db.commit()
    db.refresh(job)
    job.log_path = str(job_log_path(tenant.directory_slug, project.slug, job.id))
    db.commit()
    try:
        result = _dispatch_retry("retry", tenant.directory_slug, project.slug, request, job.id, source.action)
        job.celery_task_id = getattr(result, "id", None)
        db.commit()
    except ValueError as exc:
        job.status = "failed"
        job.stage = "failed"
        job.error = str(exc)
        job.finished_at = datetime.now(timezone.utc)
        project.status = source.status if source.status != "failed" else "ready"
        db.commit()
        _error(status.HTTP_400_BAD_REQUEST, "job_retry_invalid")
    except Exception as exc:  # noqa: BLE001
        job.status = "failed"
        job.stage = "failed"
        job.error = f"{type(exc).__name__}: {exc}"
        job.finished_at = datetime.now(timezone.utc)
        project.status = "failed"
        db.commit()
        _error(status.HTTP_503_SERVICE_UNAVAILABLE, "worker_unavailable")
    return {
        "job": _job_payload(job, include_log=False),
        "job_id": job.id,
        "project_id": project.id,
        "status": project.status,
        "estimate": estimate,
    }


@router.post("/{project_id}/sample/gaps", status_code=status.HTTP_202_ACCEPTED)
def sample_project_gaps(
    project_id: int,
    payload: SampleRequest | None = None,
    current_user: User = Depends(require_editor),
    db: Session = Depends(get_db),
):
    """只补采当前问题集中低于最低证据量的问题。"""
    project = _project_for_user(db, current_user, project_id)
    tenant = _tenant_for_user(db, current_user)
    payload = payload or SampleRequest()
    with with_tenant_read_context(tenant, project.slug):
        config_data = workspace.ensure_global_engine_scope(project.slug)
        _, rows = _current_sample_rows(project.slug, config_data)
    evidence = measurement.question_cohort_evidence(
        rows, config_data, measurement.MIN_QUESTION_SAMPLES,
    )
    measured = {
        str(item.get("id")): int(item.get("samples") or 0)
        for item in evidence.get("items") or []
        if isinstance(item, dict) and item.get("id")
    }
    requested = [str(value).strip() for value in (payload.question_ids or []) if str(value).strip()]
    question_ids = requested or [
        str(item.get("id"))
        for item in evidence.get("gaps") or []
        if isinstance(item, dict) and item.get("id")
    ]
    question_ids = list(dict.fromkeys(question_ids))
    if not question_ids:
        return {
            "status": "no_gaps", "project_id": project.id, "question_ids": [],
            "estimate": None, "cohort_gaps": [],
        }
    targeted = payload.model_copy(update={
        "question_ids": question_ids,
        # sample.run replaces the targeted question/platform rows; using the
        # full minimum gives every selected cohort a deterministic denominator.
        "repeat": max(measurement.MIN_QUESTION_SAMPLES, payload.repeat),
    })
    estimate = _validated_sample_estimate(db, tenant, project, targeted)
    if not targeted.platforms:
        funded = [
            item["engine_code"] for item in estimate.get("platforms") or []
            if item.get("source") in ("byok", "platform_pool") and item.get("calls")
        ]
        if funded:
            targeted = targeted.model_copy(update={"platforms": funded})
        else:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "sampling_platform_unavailable",
                    "message": "No funded API platform can fill the requested cohort gaps",
                    "estimate": estimate,
                },
            )
    expected_cohorts = [
        item for item in estimate.get("platforms") or []
        if item.get("source") in ("byok", "platform_pool") and item.get("calls")
    ]
    evidence = measurement.question_cohort_evidence(
        rows, config_data, measurement.MIN_QUESTION_SAMPLES,
        expected_cohorts=expected_cohorts,
    )
    cohort_gaps = [
        {
            "question_id": item.get("id"),
            "samples": item.get("samples", 0),
            "required": item.get("required", measurement.MIN_QUESTION_SAMPLES),
            "missing_samples": item.get("missing_samples", measurement.MIN_QUESTION_SAMPLES),
            "cohorts": item.get("cohorts") or [],
        }
        for item in evidence.get("gaps") or []
        if item.get("id") in question_ids
    ]
    result = sample_project(project_id, targeted, current_user, db)
    if isinstance(result, dict):
        result["gap_fill"] = {
            "question_ids": question_ids,
            "minimum_samples": measurement.MIN_QUESTION_SAMPLES,
            "previous_samples": {qid: measured.get(qid, 0) for qid in question_ids},
            "cohort_gaps": cohort_gaps,
            "target_platforms": targeted.platforms,
        }
        result["estimate"] = result.get("estimate") or estimate
    return result


@router.post("/{project_id}/sample", status_code=status.HTTP_202_ACCEPTED)
def sample_project(
    project_id: int,
    payload: SampleRequest | None = None,
    current_user: User = Depends(require_editor),
    db: Session = Depends(get_db),
):
    """投递一次 API 采样任务。"""
    project = _project_for_user(db, current_user, project_id)
    tenant = _tenant_for_user(db, current_user)
    _enable_platform_pool_if_available(tenant, project)
    check_sample_run(db, tenant, project)
    if _active_job(db, project.id) is not None:
        _error(status.HTTP_409_CONFLICT, "project_job_already_running")
    _require_project_questions(tenant, project)
    payload = payload or SampleRequest()
    payload = _normalize_sample_question_ids(tenant, project, payload)
    if not payload.platforms:
        estimate_preview = _sample_estimate(db, tenant, project, payload, enforce=False)
        funded = [
            item["engine_code"]
            for item in estimate_preview.get("platforms") or []
            if item.get("source") in ("byok", "platform_pool") and item.get("calls")
        ]
        if funded:
            payload = payload.model_copy(update={"platforms": funded})
    request_values = {
        "limit": payload.limit,
        "platforms": payload.platforms,
        "repeat": payload.repeat,
        "question_ids": payload.question_ids,
    }
    job = Job(project_id=project.id, action="sample", status="queued", stage="queued",
              request_json=_safe_request_json("sample", request_values))
    estimate = _reserve_sample_estimate(db, tenant, project, job, payload)
    db.add(job)
    record_product_event(
        db,
        "sample_started",
        tenant_id=tenant.id,
        user_id=current_user.id,
        country_code=tenant.acquisition_country_code,
        properties={"project_id": project.id, "job_id": job.id},
    )
    project.status = "sampling"
    db.commit()
    db.refresh(job)
    job.log_path = str(job_log_path(tenant.directory_slug, project.slug, job.id))
    db.commit()
    try:
        task_result = task_sample.delay(
            tenant.directory_slug,
            project.slug,
            limit=payload.limit,
            platforms=payload.platforms,
            repeat=payload.repeat,
            question_ids=payload.question_ids,
            job_id=job.id,
        )
        job.celery_task_id = getattr(task_result, "id", None)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        job.status = "failed"
        job.stage = "failed"
        job.error = f"{type(exc).__name__}: {exc}"
        job.finished_at = datetime.now(timezone.utc)
        project.status = "failed"
        db.commit()
        _error(status.HTTP_503_SERVICE_UNAVAILABLE, "worker_unavailable")
    return {"job_id": job.id, "project_id": project.id, "status": project.status, "estimate": estimate}


@router.post("/{project_id}/actions/{action}", status_code=status.HTTP_202_ACCEPTED)
def run_pipeline_action(
    project_id: int,
    action: str,
    payload: PipelineActionRequest | None = None,
    current_user: User = Depends(require_editor),
    db: Session = Depends(get_db),
):
    """投递一个白名单内的引擎管线动作。"""
    if action not in PIPELINE_ACTIONS:
        _error(status.HTTP_400_BAD_REQUEST, "unsupported_pipeline_action")
    project = _project_for_user(db, current_user, project_id)
    tenant = _tenant_for_user(db, current_user)
    if _active_job(db, project.id) is not None:
        _error(status.HTTP_409_CONFLICT, "project_job_already_running")
    params = (payload or PipelineActionRequest()).params
    if action == "sample":
        _require_project_questions(tenant, project)
    no_sample = _pipeline_flag(params, "no-sample") or _pipeline_flag(params, "no_sample")
    estimate = None
    sample_payload = None
    if action in ("sample", "autopilot", "serve") and not no_sample:
        check_sample_run(db, tenant, project)
        sample_payload = _pipeline_sample_payload(params)
        sample_payload = _normalize_sample_estimate_payload(tenant, project, sample_payload)
        if action != "sample":
            estimate = _validated_sample_estimate(
                db, tenant, project, sample_payload,
                enforce=True, allow_pool=False,
            )

    job = Job(project_id=project.id, action=action, status="queued", stage="queued",
              request_json=_safe_request_json(action, params))
    if action == "sample" and sample_payload is not None:
        estimate = _reserve_sample_estimate(db, tenant, project, job, sample_payload)
    db.add(job)
    project.status = {
        "sample": "sampling",
        "verify": "verifying",
        "deliver": "delivering",
        "bootstrap": "bootstrapping",
    }.get(action, "processing")
    db.commit()
    db.refresh(job)
    job.log_path = str(job_log_path(tenant.directory_slug, project.slug, job.id))
    db.commit()
    try:
        task_result = task_pipeline.delay(tenant.directory_slug, project.slug, action, params=params, job_id=job.id)
        job.celery_task_id = getattr(task_result, "id", None)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        job.status = "failed"
        job.stage = "failed"
        job.error = f"{type(exc).__name__}: {exc}"
        job.finished_at = datetime.now(timezone.utc)
        project.status = "failed"
        db.commit()
        _error(status.HTTP_503_SERVICE_UNAVAILABLE, "worker_unavailable")
    return {
        "job_id": job.id,
        "project_id": project.id,
        "action": action,
        "status": project.status,
        "estimate": estimate,
    }


@router.get("/{project_id}/report")
def project_report(project_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """返回最新 metrics 报告。"""
    project = _project_for_user(db, current_user, project_id)
    tenant = _tenant_for_user(db, current_user)
    with with_tenant_read_context(tenant, project.slug):
        global_scope.normalize_project(project.slug)
        path = _latest_file(geolib.project_dir(project.slug) / "metrics", "*.json")
        if path is None:
            _error(status.HTTP_404_NOT_FOUND, "report_not_found")
        metrics = geolib.read_json(path, None)
        product_report = _product_report(project.slug, metrics)
        quality = report_quality.assess(project.slug, _has_sampling_access(db, tenant, project))
    return {"report": product_report, "date": metrics.get("date") if metrics else None,
            "sample_artifact": (metrics.get("run_id") or metrics.get("date")) if metrics else None,
            "report_quality": quality}


@router.get("/{project_id}/engines")
def project_engines(project_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """返回分引擎指标，并标明 API 采样模式。"""
    project = _project_for_user(db, current_user, project_id)
    tenant = _tenant_for_user(db, current_user)
    with with_tenant_read_context(tenant, project.slug):
        global_scope.normalize_project(project.slug)
        pdir = geolib.project_dir(project.slug)
        metrics_path = _latest_file(pdir / "metrics", "*.json")
        metrics = geolib.read_json(metrics_path, None) if metrics_path else None
        engines = _product_report(project.slug, metrics)["engines"]
        engines = _include_configured_engines(db, tenant, engines)
        config_data = geolib.load_config(project.slug)
        for item in engines:
            identity = _provider_identity(item.get("engine_code"), item, config_data)
            item["provider_identity"] = identity
            item["provider_name"] = identity["provider_name"]
            item["model_id"] = identity["model_id"]
        quality_payload = report_quality.assess(
            project.slug, _has_sampling_access(db, tenant, project),
        )
        measurement_quality = quality_payload["measurement_quality"]
        readiness = quality_payload.get("readiness") or {}
        provider_observability = (metrics or {}).get("provider_observability") if metrics else None
    return {
        "project_id": project.id,
        "project_slug": project.slug,
        "date": metrics.get("date") if metrics else None,
        "sample_artifact": (metrics.get("run_id") or metrics.get("date")) if metrics else None,
        "engines": [
            {
                **item,
                "platform": item.get("engine_code"),
                "platform_name": item.get("engine_name"),
            }
            for item in engines
        ],
        "provenance": metrics.get("provenance") if metrics else None,
        "question_set_version": metrics.get("question_set_version") if metrics else None,
        "sample_summary": metrics.get("sample_summary") if metrics else None,
        "sampling_receipt": metrics.get("sampling_receipt") if metrics else None,
        "measurement_quality": measurement_quality,
        "readiness": readiness,
        "provider_observability": provider_observability,
    }


@router.delete("/{project_id}")
def archive_project_record(project_id: int, current_user: User = Depends(require_owner), db: Session = Depends(get_db)):
    """停用项目并释放套餐名额，磁盘产物保留以便后续归档处理。"""
    project = _project_for_user(db, current_user, project_id)
    if _active_job(db, project.id) is not None:
        _error(status.HTTP_409_CONFLICT, "project_job_already_running")
    project.status = "archived"
    project.archived_at = datetime.now(timezone.utc)
    project.schedule_interval_days = None
    project.schedule_next_run_at = None
    db.commit()
    return {"ok": True, "project_id": project.id, "status": project.status}


@router.get("/{project_id}/framing")
def project_framing(project_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """返回最新采样中 AI 对品牌的描述短语和原文证据。"""
    project = _project_for_user(db, current_user, project_id)
    tenant = _tenant_for_user(db, current_user)
    with with_tenant_read_context(tenant, project.slug):
        global_scope.normalize_project(project.slug)
        result = framing.build(project.slug)
    return {"framing": result}


@router.get("/{project_id}/samples/{sample_date}")
def project_samples(
    project_id: int,
    sample_date: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """按日期返回原始答案回放。"""
    if not re.fullmatch(r"(?:\d{4}-\d{2}-\d{2}|sample-[A-Za-z0-9-]{20,80})", sample_date):
        _error(status.HTTP_400_BAD_REQUEST, "invalid_sample_date")
    project = _project_for_user(db, current_user, project_id)
    tenant = _tenant_for_user(db, current_user)
    with with_tenant_read_context(tenant, project.slug):
        config = global_scope.normalize_project(project.slug)
        sample_dir = geolib.project_dir(project.slug) / "samples"
        path = sample_dir / f"{sample_date}.jsonl"
        if not path.is_file() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", sample_date):
            candidates = []
            for candidate in sorted(sample_dir.glob("sample-*.jsonl")) if sample_dir.is_dir() else []:
                first = geolib.read_jsonl(candidate)[:1]
                if first and first[0].get("date") == sample_date:
                    candidates.append(candidate)
            path = candidates[-1] if candidates else path
        if not path.is_file():
            _error(status.HTTP_404_NOT_FOUND, "samples_not_found")
        all_rows = geolib.read_jsonl(path)
        rows = [
            row for row in all_rows
            if global_scope.is_global_sample(row) and brand_identity.is_current_sample(row, config)
        ]
        excluded = [row for row in all_rows if row not in rows]
        exclusion_reasons = {}
        for row in excluded:
            reason = row.get("sample_exclusion_reason") or (
                "market_or_language_mismatch" if not global_scope.is_global_sample(row)
                else brand_identity.sample_exclusion_reason(row, config) or "not_in_current_cohort"
            )
            exclusion_reasons[reason] = exclusion_reasons.get(reason, 0) + 1
    return {
        "project_id": project.id,
        "project_slug": project.slug,
        "date": sample_date,
        "sample_artifact": path.stem,
        "samples": rows,
        "excluded_sample_count": len(excluded),
        "exclusion_reasons": exclusion_reasons,
    }


@router.get("/{project_id}/tickets")
def project_tickets(
    project_id: int,
    ticket_status: str | None = Query(default=None, alias="status"),
    owner: str | None = Query(default=None, max_length=128),
    priority: str | None = Query(default=None, pattern="^P[0-2]$"),
    q: str | None = Query(default=None, max_length=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """读取 engine 生成的工单列表。"""
    project = _project_for_user(db, current_user, project_id)
    tenant = _tenant_for_user(db, current_user)
    with with_tenant_read_context(tenant, project.slug):
        import tasks as engine_tasks

        data = global_scope.normalize_tasks(project.slug) or engine_tasks.load(project.slug)
    tickets = ticket_workflow.filter_tickets(
        data.get("tasks", []), status=ticket_status, owner=owner, priority=priority, query=q,
    )
    return {"tickets": localize_tickets(tickets), "summary": data.get("summary", {}), "filtered_count": len(tickets)}


@router.get("/{project_id}/playbook")
def project_playbook(
    project_id: int,
    ticket_status: str | None = Query(default=None, alias="status"),
    owner: str | None = Query(default=None, max_length=128),
    priority: str | None = Query(default=None, pattern="^P[0-2]$"),
    q: str | None = Query(default=None, max_length=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """按影响、工作量和原始顺序稳定返回 Playbook。"""
    project = _project_for_user(db, current_user, project_id)
    tenant = _tenant_for_user(db, current_user)
    with with_tenant_read_context(tenant, project.slug):
        import tasks as engine_tasks

        data = global_scope.normalize_tasks(project.slug) or engine_tasks.load(project.slug)
    filtered = ticket_workflow.filter_tickets(
        data.get("tasks", []), status=ticket_status, owner=owner, priority=priority, query=q,
    )
    indexed = [
        (index, ticket)
        for index, ticket in enumerate(filtered)
        if isinstance(ticket, dict)
    ]
    indexed.sort(key=lambda pair: (
        pair[1].get("status") in ("done", "wontfix"),
        PLAYBOOK_PRIORITY.get(pair[1].get("priority"), 99),
        PLAYBOOK_EFFORT.get(pair[1].get("effort"), 99),
        pair[0],
    ))
    return {
        "playbook": localize_tickets([ticket for _, ticket in indexed]),
        "top_actions": _top_actions([ticket for _, ticket in indexed]),
        "summary": data.get("summary", {}),
        "filtered_count": len(indexed),
        "generated_at": data.get("generated_at"),
    }


@router.post("/{project_id}/tickets", status_code=status.HTTP_201_CREATED)
def create_ticket(
    project_id: int,
    payload: OffsiteTicketCreate,
    current_user: User = Depends(require_editor),
    db: Session = Depends(get_db),
):
    """创建需要人工验收的 offsite 工单。"""
    project = _project_for_user(db, current_user, project_id)
    tenant = _tenant_for_user(db, current_user)
    if _active_job(db, project.id) is not None:
        _error(status.HTTP_409_CONFLICT, "project_job_already_running")
    try:
        with with_tenant_read_context(tenant, project.slug):
            ticket = workspace.create_offsite_ticket(
                project.slug,
                payload.url,
                payload.ask_text,
                payload.influenced_questions,
            )
    except (GeoEngineError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "ticket_creation_failed", "detail": str(exc)},
        ) from exc
    return {"ticket": ticket}


@router.patch("/{project_id}/tickets")
def bulk_update_tickets(
    project_id: int,
    payload: TicketBulkUpdate,
    current_user: User = Depends(require_editor),
    db: Session = Depends(get_db),
):
    """在一次项目锁内批量修改工单工作流字段。"""
    project = _project_for_user(db, current_user, project_id)
    tenant = _tenant_for_user(db, current_user)
    if _active_job(db, project.id) is not None:
        _error(status.HTTP_409_CONFLICT, "project_job_already_running")
    changes = payload.model_dump(exclude_unset=True)
    changes.pop("ticket_ids", None)
    if not changes or not any(key == "due_date" or value not in (None, "") for key, value in changes.items()):
        _error(status.HTTP_422_UNPROCESSABLE_ENTITY, "ticket_update_empty")
    try:
        with with_tenant_read_context(tenant, project.slug):
            tickets = ticket_workflow.bulk_update(
                project.slug, payload.ticket_ids, changes, current_user.email,
            )
    except KeyError:
        _error(status.HTTP_404_NOT_FOUND, "ticket_not_found")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"error": "ticket_update_failed", "detail": str(exc)}) from exc
    return {"tickets": localize_tickets(ticket_workflow.enrich(tickets)), "updated": len(tickets)}


@router.get("/{project_id}/tickets/{ticket_id}/timeline")
def ticket_timeline(
    project_id: int,
    ticket_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """返回工单手动修改和自动验收时间线。"""
    project = _project_for_user(db, current_user, project_id)
    tenant = _tenant_for_user(db, current_user)
    with with_tenant_read_context(tenant, project.slug):
        import tasks as engine_tasks

        data = global_scope.normalize_tasks(project.slug) or engine_tasks.load(project.slug)
        ticket = next((item for item in data.get("tasks", []) if item.get("id") == ticket_id), None)
    if ticket is None:
        _error(status.HTTP_404_NOT_FOUND, "ticket_not_found")
    enriched = ticket_workflow.enrich([ticket])[0]
    return {"ticket_id": ticket_id, "activity": enriched["activity"], "notes": enriched["notes"]}


@router.patch("/{project_id}/tickets/{ticket_id}")
def update_ticket(
    project_id: int,
    ticket_id: str,
    payload: TicketUpdate,
    current_user: User = Depends(require_editor),
    db: Session = Depends(get_db),
):
    """更新工单状态、负责人、截止日期或备注。"""
    project = _project_for_user(db, current_user, project_id)
    tenant = _tenant_for_user(db, current_user)
    if _active_job(db, project.id) is not None:
        _error(status.HTTP_409_CONFLICT, "project_job_already_running")
    changes = payload.model_dump(exclude_unset=True)
    if not changes or not any(key == "due_date" or value not in (None, "") for key, value in changes.items()):
        _error(status.HTTP_422_UNPROCESSABLE_ENTITY, "ticket_update_empty")
    try:
        with with_tenant_read_context(tenant, project.slug):
            ticket = ticket_workflow.update(project.slug, ticket_id, changes, current_user.email)
    except KeyError:
        _error(status.HTTP_404_NOT_FOUND, "ticket_not_found")
    except (GeoEngineError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"error": "ticket_update_failed", "detail": str(exc)}) from exc
    return {"ticket": localize_tickets(ticket_workflow.enrich([ticket]))[0]}


@router.post("/{project_id}/verify", status_code=status.HTTP_202_ACCEPTED)
def verify_project(project_id: int, current_user: User = Depends(require_editor), db: Session = Depends(get_db)):
    """投递工单自动验收任务。"""
    project = _project_for_user(db, current_user, project_id)
    if _active_job(db, project.id) is not None:
        _error(status.HTTP_409_CONFLICT, "project_job_already_running")
    job = Job(project_id=project.id, action="verify", status="queued", stage="queued", request_json="{}")
    db.add(job)
    project.status = "verifying"
    db.commit()
    db.refresh(job)
    tenant = _tenant_for_user(db, current_user)
    job.log_path = str(job_log_path(tenant.directory_slug, project.slug, job.id))
    db.commit()
    try:
        task_result = task_verify.delay(tenant.directory_slug, project.slug, job_id=job.id)
        job.celery_task_id = getattr(task_result, "id", None)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        job.status = "failed"
        job.stage = "failed"
        job.error = f"{type(exc).__name__}: {exc}"
        job.finished_at = datetime.now(timezone.utc)
        project.status = "failed"
        db.commit()
        _error(status.HTTP_503_SERVICE_UNAVAILABLE, "worker_unavailable")
    return {"job_id": job.id, "project_id": project.id, "status": project.status}


@router.get("/{project_id}/verify/history")
def verify_history(project_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """返回 engine verify 生成的验收历史。"""
    project = _project_for_user(db, current_user, project_id)
    tenant = _tenant_for_user(db, current_user)
    with with_tenant_read_context(tenant, project.slug):
        import verify as engine_verify

        directory = geolib.project_dir(project.slug) / "verify"
        files = sorted(directory.glob("*.json"), key=engine_verify.report_key) if directory.exists() else []
        history = [geolib.read_json(path, {}) for path in files]
    return {"history": history}


@router.post("/{project_id}/deliver", status_code=status.HTTP_202_ACCEPTED)
def deliver_project(project_id: int, current_user: User = Depends(require_editor), db: Session = Depends(get_db)):
    """投递客户交付包生成任务。"""
    project = _project_for_user(db, current_user, project_id)
    if _active_job(db, project.id) is not None:
        _error(status.HTTP_409_CONFLICT, "project_job_already_running")
    job = Job(project_id=project.id, action="deliver", status="queued", stage="queued", request_json="{}")
    db.add(job)
    project.status = "delivering"
    db.commit()
    db.refresh(job)
    tenant = _tenant_for_user(db, current_user)
    job.log_path = str(job_log_path(tenant.directory_slug, project.slug, job.id))
    db.commit()
    try:
        task_result = task_deliver.delay(tenant.directory_slug, project.slug, job_id=job.id)
        job.celery_task_id = getattr(task_result, "id", None)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        job.status = "failed"
        job.stage = "failed"
        job.error = f"{type(exc).__name__}: {exc}"
        job.finished_at = datetime.now(timezone.utc)
        project.status = "failed"
        db.commit()
        _error(status.HTTP_503_SERVICE_UNAVAILABLE, "worker_unavailable")
    return {"job_id": job.id, "project_id": project.id, "status": project.status}


@router.get("/{project_id}/deliveries")
def deliveries(project_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """返回已生成的交付包及其资产就绪状态。"""
    project = _project_for_user(db, current_user, project_id)
    tenant = _tenant_for_user(db, current_user)
    directory = tenant_project_dir(tenant, project.slug) / "delivery"
    packages = []
    directories = sorted((item for item in directory.iterdir() if item.is_dir()), reverse=True) \
        if directory.exists() else []
    for item in directories:
        asset_index = geolib.read_json(item / "assets" / "index.json", {}) or {}
        sendable = bool(
            tenant.plan in delivery_share.WHITE_LABEL_PLANS
            and (asset_index.get("diagnostic_ready") or asset_index.get("readiness") == "customer_ready")
        )
        packages.append({
            "date": item.name,
            "readiness": asset_index.get("readiness", "unknown"),
            "pack_kind": asset_index.get("pack_kind") or "unknown",
            "diagnostic_ready": bool(asset_index.get("diagnostic_ready")),
            "visibility_ready": bool(asset_index.get("visibility_ready")),
            "implementation_ready": bool(asset_index.get("implementation_ready")),
            "implementation_backlog": list(asset_index.get("implementation_backlog") or []),
            "asset_summary": asset_index.get("summary") or {"ready": 0, "needs_review": 0, "template": 0},
            "can_send": sendable,
        })
    return {
        "deliveries": [item["date"] for item in packages],
        "packages": packages,
        "can_send": tenant.plan in delivery_share.WHITE_LABEL_PLANS,
    }


@router.get("/{project_id}/deliveries/{delivery_date}")
def download_delivery(
    project_id: int,
    delivery_date: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """把指定交付目录打成 zip 下载。"""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", delivery_date):
        _error(status.HTTP_400_BAD_REQUEST, "invalid_delivery_date")
    project = _project_for_user(db, current_user, project_id)
    tenant = _tenant_for_user(db, current_user)
    with with_tenant_read_context(tenant, project.slug):
        directory = geolib.project_dir(project.slug) / "delivery" / delivery_date
        if not directory.is_dir():
            _error(status.HTTP_404_NOT_FOUND, "delivery_not_found")
        asset_index = geolib.read_json(directory / "assets" / "index.json", {}) or {}
        quality_status = str((asset_index.get("quality_gate") or {}).get("status") or "")
        reuse_existing = quality_status == "passed"
        served_last_known_good = False
        if not reuse_existing:
            try:
                directory = delivery.ensure_delivery_contract(project.slug, directory)
            except GeoEngineError as exc:
                if not directory.is_dir():
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail={"error": "delivery_contract_invalid", "detail": str(exc)},
                    ) from exc
                served_last_known_good = True
        asset_index = geolib.read_json(directory / "assets" / "index.json", {}) or {}
        readiness = "last_known_good" if served_last_known_good else str(asset_index.get("readiness") or "unknown")
        package_kind = _delivery_package_kind(asset_index, readiness)
        source_revision = str(asset_index.get("source_revision") or "unknown")
        return _stream_delivery_zip(directory, package_kind, delivery_date, readiness, source_revision)


def _stream_delivery_zip(directory, package_kind, delivery_date, readiness, source_revision):
    archive = tempfile.TemporaryFile(prefix="citeaura-delivery-", suffix=".zip")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for file_path in sorted(directory.rglob("*")):
            if file_path.is_file():
                bundle.write(file_path, file_path.relative_to(directory).as_posix())
    archive.seek(0)

    def close_archive():
        archive.close()

    return StreamingResponse(
        iter(lambda: archive.read(64 * 1024), b""),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="delivery-{package_kind}-{delivery_date}.zip"',
            "X-CiteAura-Delivery-Readiness": readiness,
            "X-CiteAura-Source-Revision": source_revision,
        },
        background=BackgroundTask(close_archive),
    )


def _delivery_package_kind(asset_index, readiness="unknown"):
    if asset_index.get("implementation_ready"):
        return "implementation-ready"
    if readiness == "customer_ready" or asset_index.get("diagnostic_ready"):
        return "diagnostic-ready"
    return "review"


@router.post("/{project_id}/deliveries/{delivery_date}/send")
def send_delivery_pack(
    project_id: int,
    delivery_date: str,
    payload: DeliverySendRequest | None = None,
    current_user: User = Depends(require_editor),
    db: Session = Depends(get_db),
):
    """Create a 7-day client download link and optionally email it. Agency/Enterprise only."""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", delivery_date):
        _error(status.HTTP_400_BAD_REQUEST, "invalid_delivery_date")
    project = _project_for_user(db, current_user, project_id)
    tenant = _tenant_for_user(db, current_user)
    if tenant.plan not in delivery_share.WHITE_LABEL_PLANS:
        _error(status.HTTP_403_FORBIDDEN, "white_label_plan_required")
    payload = payload or DeliverySendRequest()
    try:
        recipient = delivery_share.clean_email(payload.recipient_email)
    except ValueError:
        _error(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid_recipient_email")
    if recipient and not config.auth_smtp_configured():
        _error(status.HTTP_409_CONFLICT, "alert_email_not_configured")
    with with_tenant_read_context(tenant, project.slug):
        directory = geolib.project_dir(project.slug) / "delivery" / delivery_date
        if not directory.is_dir():
            _error(status.HTTP_404_NOT_FOUND, "delivery_not_found")
        asset_index = geolib.read_json(directory / "assets" / "index.json", {}) or {}
    if not (asset_index.get("diagnostic_ready") or asset_index.get("readiness") == "customer_ready"):
        _error(status.HTTP_409_CONFLICT, "delivery_not_sendable")
    share, token = delivery_share.create_share(db, project, current_user.id, delivery_date, recipient)
    url = delivery_share.public_url(token)
    email_sent = False
    if recipient:
        try:
            with with_tenant_read_context(tenant, project.slug):
                delivery_share.send_share_email(recipient, project, delivery_date, url, share.expires_at)
            email_sent = True
        except Exception as exc:  # noqa: BLE001
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"error": "delivery_share_email_failed", "url": url, "expires_at": share.expires_at.isoformat()},
            ) from exc
    db.commit()
    return {
        "url": url,
        "delivery_date": delivery_date,
        "expires_at": share.expires_at,
        "recipient_email": recipient,
        "email_sent": email_sent,
        "share_id": share.id,
    }
