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
    available = set(sample.PROVIDERS)
    byok = set(load_tenant_keys(db, tenant.id))
    catalog = public_catalog() if tenant.plan in PAID_PLANS else []
    pool_codes = {item["engine_code"] for item in catalog}
    funding = {"keys": {code: True for code in byok}, "pool_codes": pool_codes}
    requested = list(dict.fromkeys(payload.platforms or sampling_control.default_sample_platforms(
        funding, custom_providers, sorted(available | custom_codes), payload.market,
    )))
    invalid = sorted(set(requested) - available - custom_codes)
    if invalid:
        _error(status.HTTP_422_UNPROCESSABLE_ENTITY, "unsupported_api_platform")
    mismatched = [
        code for code in requested
        if not sampling_control.platform_matches_market(code, payload.market, custom_providers)
    ]
    if mismatched:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": sampling_control.SamplingPlatformMarketMismatch.code,
                "platforms": sorted(set(mismatched)),
                "project_market": payload.market,
            },
        )
    effective = [
        code for code in requested
        if code in byok or code in pool_codes or code in custom_codes
        if sampling_control.platform_matches_market(code, payload.market, custom_providers)
    ]
    pool_only = [code for code in effective if code in pool_codes and code not in byok]
    prices = {item["engine_code"]: item["unit_price_cny_fen"] for item in catalog}
    quick_questions = min(5, payload.question_count)
    full_questions = payload.question_count
    quick_calls = quick_questions * len(effective)
    full_calls = full_questions * len(effective)
    try:
        site = preflight.run(payload.url)
    except (preflight.PreflightError, ValueError) as exc:
        record_product_event(
            db,
            "preflight_failed",
            tenant_id=tenant.id,
            user_id=current_user.id,
            country_code=tenant.acquisition_country_code,
            properties={"error": type(exc).__name__},
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "preflight_failed", "detail": str(exc)},
        ) from exc
    # The preflight adapter may carry bounded in-process signals for a caller
    # that can reuse them; never expose those private fields through the API.
    site = {key: value for key, value in site.items() if not str(key).startswith("_")}
    record_product_event(
        db,
        "preflight_completed",
        tenant_id=tenant.id,
        user_id=current_user.id,
        country_code=tenant.acquisition_country_code,
        properties={"ready": bool(site.get("ready")), "url_host": urlparse(payload.url).hostname},
    )
    db.commit()
    return {
        "site": site,
        "byok_engines": sorted(byok),
        "pool_engines": sorted(pool_codes),
        "manual_only": [
            {"engine_code": code, "name": name, "sampling_mode": sampling_modes.MODE_MANUAL, "sampling_mode_code": sampling_modes.CODE_MANUAL, "market": market}
            for code, (name, market) in sorted(sample.MANUAL_ONLY.items())
            if market in ("cn", "global", "both")
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
    public_audit = None
    audit_snapshot = None
    if payload.audit_id:
        public_audit = db.query(PublicAudit).filter(
            PublicAudit.audit_id == payload.audit_id,
            PublicAudit.expires_at > datetime.now(timezone.utc),
        ).first()
        if public_audit is None:
            _error(status.HTTP_400_BAD_REQUEST, "audit_handoff_expired")
        try:
            audit_snapshot = json.loads(public_audit.result_json or "{}")
        except (TypeError, ValueError):
            audit_snapshot = None
    slug = geolib.slugify(payload.url)
    existing = db.query(Project).filter(Project.tenant_id == tenant.id, Project.slug == slug).first()
    if existing is not None and existing.archived_at is None and existing.status != "archived":
        _error(status.HTTP_409_CONFLICT, "project_already_exists")
    check_project_creation(db, tenant)

    restoring_existing_workspace = existing is not None and _project_directory_exists(tenant.directory_slug, slug)
    if existing is not None:
        project = existing
        project.url = payload.url
        project.market = payload.market
        project.status = "initializing"
        project.archived_at = None
        project.schedule_interval_days = None
        project.schedule_next_run_at = None
    else:
        project = Project(
            tenant_id=tenant.id,
            slug=slug,
            url=payload.url,
            market=payload.market,
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
        request_json=json.dumps({
            "skip_llm": skip_llm,
            "no_sample": no_sample,
            "job_action": job_action,
            "audit_id": payload.audit_id,
        }),
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
    record_product_event(
        db,
        "audit_only_selected" if no_sample else "full_baseline_selected",
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
                market=payload.market,
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

    if audit_snapshot:
        with with_tenant_context(tenant.directory_slug, slug):
            geolib.write_json(geolib.project_dir(slug) / "public_audit.json", audit_snapshot)

    if job_action == "autopilot":
        _reserve_sample_estimate(db, tenant, project, job, SampleRequest())

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
        sampling_control.release_reservation(job)
        db.commit()
        _error(status.HTTP_503_SERVICE_UNAVAILABLE, "worker_unavailable")

    return {
        "project_id": project.id,
        "job_id": job.id,
        "action": job_action,
        "slug": project.slug,
        "status": project.status,
        "audit_id": payload.audit_id,
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
            detail["public_audit"] = geolib.read_json(geolib.project_dir(project.slug) / "public_audit.json", None)
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
                "sentiment": {"sample_count": 0, "bands": [], "method": "heuristic answer context; inspect raw replay before making a claim"},
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
def project_jobs(
    project_id: int,
    limit: int = Query(default=50, ge=1, le=100),
    before_id: int | None = Query(default=None, ge=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """返回有限任务历史；用 before_id 继续翻页，避免无限增长响应。"""
    project = _project_for_user(db, current_user, project_id)
    query = db.query(Job).filter(Job.project_id == project.id)
    if before_id is not None:
        query = query.filter(Job.id < before_id)
    rows = query.order_by(Job.id.desc()).limit(limit + 1).all()
    has_more = len(rows) > limit
    jobs = rows[:limit]
    return {
        "jobs": [_job_payload(job, include_log=False) for job in jobs],
        "pagination": {
            "limit": limit,
            "has_more": has_more,
            "next_before_id": jobs[-1].id if has_more and jobs else None,
        },
    }


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
    sample_payload = None
    if source.action in ("sample", "cycle", "autopilot", "serve"):
        if source.action not in ("autopilot", "serve") or not request_no_sample:
            check_sample_run(db, tenant, project)
            sample_payload = _pipeline_sample_payload(request)
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
    if sample_payload is not None:
        estimate = _reserve_sample_estimate(db, tenant, project, job, sample_payload)
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
        sampling_control.release_reservation(job)
        project.status = source.status if source.status != "failed" else "ready"
        db.commit()
        _error(status.HTTP_400_BAD_REQUEST, "job_retry_invalid")
    except Exception as exc:  # noqa: BLE001
        job.status = "failed"
        job.stage = "failed"
        job.error = f"{type(exc).__name__}: {exc}"
        job.finished_at = datetime.now(timezone.utc)
        sampling_control.release_reservation(job)
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
        estimate_preview = project_sampling.estimate(db, tenant, project, payload, enforce=False)
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
        sampling_control.release_reservation(job)
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

    job = Job(project_id=project.id, action=action, status="queued", stage="queued",
              request_json=_safe_request_json(action, params))
    if sample_payload is not None:
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
        sampling_control.release_reservation(job)
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
    return _project_report_payload(db, tenant, project)


@router.get("/{project_id}/export.csv")
def export_project_csv(project_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """下载当前可见度报告和引用信源的平面 CSV。"""
    project = _project_for_user(db, current_user, project_id)
    tenant = _tenant_for_user(db, current_user)
    payload = _project_report_payload(db, tenant, project)
    response = Response(
        content=report_export.report_csv(project.slug, payload["report"]),
        media_type="text/csv; charset=utf-8",
    )
    response.headers["Content-Disposition"] = f'attachment; filename="citeaura-{project.slug}-report.csv"'
    response.headers["X-CiteAura-Sampling-Mode"] = "labeled per provider row"
    return response


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
            if global_scope.is_global_sample(row, config) and brand_identity.is_current_sample(row, config)
        ]
        excluded = [row for row in all_rows if row not in rows]
        exclusion_reasons = {}
        for row in excluded:
            reason = row.get("sample_exclusion_reason") or (
                "market_or_language_mismatch" if not global_scope.is_global_sample(row, config)
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
    record_product_event(
        db,
        "ticket_updated",
        tenant_id=tenant.id,
        user_id=current_user.id,
        country_code=tenant.acquisition_country_code,
        properties={"project_id": project.id, "ticket_id": ticket_id, "status": changes.get("status")},
    )
    db.commit()
    return {"ticket": localize_tickets(ticket_workflow.enrich([ticket]))[0]}


@router.post("/{project_id}/verify", status_code=status.HTTP_202_ACCEPTED)
def verify_project(project_id: int, current_user: User = Depends(require_editor), db: Session = Depends(get_db)):
    """投递工单自动验收任务。"""
    project = _project_for_user(db, current_user, project_id)
    if _active_job(db, project.id) is not None:
        _error(status.HTTP_409_CONFLICT, "project_job_already_running")
    job = Job(project_id=project.id, action="verify", status="queued", stage="queued", request_json="{}")
    db.add(job)
    record_product_event(
        db,
        "verify_started",
        tenant_id=project.tenant_id,
        user_id=current_user.id,
        properties={"project_id": project.id},
    )
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
    record_product_event(
        db,
        "delivery_started",
        tenant_id=project.tenant_id,
        user_id=current_user.id,
        properties={"project_id": project.id},
    )
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
    with with_tenant_context(tenant.directory_slug, project.slug):
        directory = geolib.project_dir(project.slug) / "delivery" / delivery_date
        if not directory.is_dir():
            _error(status.HTTP_404_NOT_FOUND, "delivery_not_found")
        try:
            # Published formal packages are immutable snapshots. Legacy or
            # incomplete directories are rebuilt through the SaaS contract.
            directory = delivery.validate_existing_delivery_contract(directory)
        except GeoEngineError as exc:
            try:
                directory = delivery.ensure_delivery_contract(project.slug, directory)
            except GeoEngineError as rebuild_exc:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"error": "delivery_contract_invalid", "detail": str(rebuild_exc)},
                ) from rebuild_exc
        asset_index = geolib.read_json(directory / "assets" / "index.json", {}) or {}
        readiness = str(asset_index.get("readiness") or "unknown")
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
    with with_tenant_context(tenant.directory_slug, project.slug):
        directory = geolib.project_dir(project.slug) / "delivery" / delivery_date
        if not directory.is_dir():
            _error(status.HTTP_404_NOT_FOUND, "delivery_not_found")
        try:
            directory = delivery.validate_existing_delivery_contract(directory)
        except GeoEngineError as exc:
            try:
                directory = delivery.ensure_delivery_contract(project.slug, directory)
            except GeoEngineError as rebuild_exc:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"error": "delivery_contract_invalid", "detail": str(rebuild_exc)},
                ) from rebuild_exc
        asset_index = geolib.read_json(directory / "assets" / "index.json", {}) or {}
    if not (asset_index.get("diagnostic_ready") or asset_index.get("readiness") == "customer_ready"):
        _error(status.HTTP_409_CONFLICT, "delivery_not_sendable")
    share, token = delivery_share.create_share(db, project, current_user.id, delivery_date, recipient)
    record_product_event(
        db,
        "delivery_shared",
        tenant_id=tenant.id,
        user_id=current_user.id,
        country_code=tenant.acquisition_country_code,
        properties={"project_id": project.id, "delivery_date": delivery_date, "email_sent": bool(recipient)},
    )
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
                detail={"error": "delivery_share_email_failed", "expires_at": share.expires_at.isoformat()},
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
