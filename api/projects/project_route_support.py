"""项目 CRUD、Bootstrap 和任务查询 API。"""

import json
import re
import tempfile
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from starlette.background import BackgroundTask
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
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
from api.adapters import brand_identity, delivery, delivery_share, export as report_export, framing, global_scope, measurement, preflight, product_insights, report_quality, sampling_control, sampling_modes, ticket_workflow, workspace
from api.adapters.network import NetworkTargetError, validate_outbound_url
from api.auth.deps import get_current_user, require_editor, require_owner
from api.billing.limits import check_project_creation, check_sample_run
from api.billing.platform_pool import PAID_PLANS, public_catalog, usage_summary
from api.db import get_db
from api import config
from api.models import Job, Project, PublicAudit, Tenant, User
from api.product_events import record_product_event
from api.worker.tasks import (
    MAX_JOB_ATTEMPTS,
    task_bootstrap,
    task_cycle,
    task_deliver,
    task_pipeline,
    task_sample,
    task_verify,
)
from api.pipeline_catalog import PIPELINE_ACTIONS, RETRYABLE_ACTIONS
from api.adapters.localization import localize_tickets
from api.projects import sampling as project_sampling
from api.projects.schemas import (
    DeliverySendRequest,
    OffsiteTicketCreate,
    PipelineActionRequest,
    ProjectCreate,
    ProjectPreflight,
    SampleEstimateRequest,
    SampleRequest,
    SamplingBudgetRequest,
    SamplingFundingRequest,
    ScheduleRequest,
    TicketBulkUpdate,
    TicketUpdate,
)
from api.projects import reporting as _reporting
from api.projects.access import error as _error
from api.projects.access import project_for_user as _project_for_user
from api.projects.access import tenant_for_user as _tenant_for_user
from api.projects.jobs import active_job as _active_job
from api.projects.jobs import dispatch_retry as _dispatch_retry
from api.projects.jobs import job_payload as _job_payload
from api.projects.jobs import request_payload as _request_payload
from api.projects.jobs import safe_request_json as _safe_request_json
from api.projects.sampling import enable_platform_pool_if_available as _enable_platform_pool_if_available
from api.projects.sampling import has_api_keys as _has_api_keys
from api.projects.sampling import has_sampling_access as _has_sampling_access
from api.projects.sampling import normalize_sample_question_ids as _normalize_sample_question_ids
from api.projects.sampling import normalize_estimate_payload as _normalize_sample_estimate_payload
from api.projects.sampling import pipeline_flag as _pipeline_flag
from api.projects.sampling import pipeline_sample_payload as _pipeline_sample_payload
from api.projects.sampling import require_project_questions as _require_project_questions
from api.projects.sampling import reserve as _reserve_sample_estimate
from api.projects.sampling import validated_estimate as _validated_sample_estimate


router = APIRouter(prefix="/api/v1/projects", tags=["projects"])
PLAYBOOK_PRIORITY = {"P0": 0, "P1": 1, "P2": 2}
PLAYBOOK_EFFORT = {"S": 0, "M": 1, "L": 2}


def _route_facade():
    """Resolve the public facade so existing test/integration patches remain effective."""
    from api.projects import router as project_router

    return project_router


def _latest_file(directory: Path, pattern: str):
    files = sorted(directory.glob(pattern)) if directory.exists() else []
    return files[-1] if files else None


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


# Stable facade exports: report aggregation lives in api.projects.reporting.
_grade_for_score = _reporting.grade_for_score
_engine_rows_by_mode = _reporting.engine_rows_by_mode
_include_configured_engines = _reporting.include_configured_engines
_provider_identity = _reporting.provider_identity
_current_sample_rows = _reporting.current_sample_rows
_product_report = _reporting.product_report
_project_report_payload = _reporting.project_report_payload


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
        "enabled": project.schedule_interval_days in (1, 7, 14, 30),
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
            "market": competitor.get("market") if competitor.get("market") in ("cn", "global", "both") else "both",
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

__all__ = tuple(name for name in globals() if not name.startswith("__"))
