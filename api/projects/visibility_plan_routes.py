"""AI 可见性运营计划与基线 API。"""

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from api.auth.deps import get_current_user, require_editor
from api.db import get_db
from api.models import Project, Tenant, User
from api.projects.access import project_for_user
from api.projects import reporting
from api.adapters.engine import with_tenant_read_context, geolib
from api.adapters import citation_readiness, brand_opportunities

router = APIRouter(tags=["visibility-plan"])
GOAL_TYPES = {"mention_rate", "citation_rate", "accuracy", "crawler_access", "ticket_completion"}
PHASES = ("baseline", "technical", "citation", "content", "offsite", "review")


class VisibilityGoal(BaseModel):
    type: str
    target: float = Field(ge=0)
    label: str | None = Field(default=None, max_length=160)

    @field_validator("type")
    @classmethod
    def validate_type(cls, value):
        if value not in GOAL_TYPES:
            raise ValueError("unsupported visibility goal type")
        return value


class VisibilityPlanUpdate(BaseModel):
    status: str = Field(default="active", pattern="^(active|paused|completed)$")
    current_phase: str = Field(default="baseline", pattern="^(baseline|technical|citation|content|offsite|review)$")
    next_review_at: datetime | None = None
    goals: list[VisibilityGoal] = Field(default_factory=list, max_length=20)
    completed_phases: list[str] = Field(default_factory=list, max_length=6)

    @field_validator("completed_phases")
    @classmethod
    def validate_completed_phases(cls, value):
        invalid = set(value) - set(PHASES)
        if invalid:
            raise ValueError("unsupported visibility phase")
        return list(dict.fromkeys(value))


def _decode(value, fallback):
    if not value:
        return fallback
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, type(fallback)) else fallback
    except (TypeError, ValueError):
        return fallback


def _timeline(project: Project):
    """基于现有证据和工单生成阶段状态，不自动修改计划。"""
    with with_tenant_read_context(project.tenant, project.slug):
        directory = geolib.project_dir(project.slug)
        tasks_data = geolib.read_json(directory / "tasks.json", {}) or {}
        tickets = [item for item in (tasks_data.get("tasks") or []) if isinstance(item, dict)]
        readiness = citation_readiness.assess(project.slug)
        opportunities = brand_opportunities.assess(project.slug)
    plan = _decode(project.visibility_plan_json, {})
    current = plan.get("current_phase", "baseline")
    done = {
        item.get("key") if isinstance(item, dict) else str(item)
        for item in (plan.get("completed_phases") or [])
        if isinstance(item, (dict, str))
    }
    phase_rules = {
        "baseline": bool(_decode(project.visibility_baseline_json, None)),
        "technical": any(item.get("key") == "crawlability" and item.get("score") is not None for item in readiness.get("dimensions", [])),
        "citation": any(item.get("key") == "citation_evidence" and item.get("score") is not None for item in readiness.get("dimensions", [])),
        "content": bool(opportunities.get("opportunities")),
        "offsite": False,
        "review": bool(_decode(project.visibility_baseline_json, None)) and bool(tickets),
    }
    phases = []
    labels = {"baseline": "Baseline", "technical": "Technical crawl", "citation": "Citation readiness", "content": "Content opportunities", "offsite": "Off-site entity", "review": "Review & re-measure"}
    for key in PHASES:
        status = "complete" if key in done or phase_rules.get(key) else ("active" if key == current else "pending")
        phases.append({"key": key, "label": labels[key], "status": status})
    return phases


def _payload(project: Project):
    plan = _decode(project.visibility_plan_json, {})
    baseline = _decode(project.visibility_baseline_json, None)
    return {
        "plan": plan or {"status": "active", "current_phase": "baseline", "goals": []},
        "baseline": baseline,
        "phases": list(PHASES),
        "timeline": _timeline(project),
    }


@router.get("/{project_id}/visibility-plan")
def get_visibility_plan(project_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _payload(project_for_user(db, current_user, project_id))


@router.put("/{project_id}/visibility-plan")
def put_visibility_plan(project_id: int, payload: VisibilityPlanUpdate, current_user: User = Depends(require_editor), db: Session = Depends(get_db)):
    project = project_for_user(db, current_user, project_id)
    value = payload.model_dump(mode="json")
    value.setdefault("started_at", datetime.now(timezone.utc).isoformat())
    project.visibility_plan_json = json.dumps(value, separators=(",", ":"))
    db.commit()
    return _payload(project)


@router.post("/{project_id}/visibility-plan/baseline")
def capture_visibility_baseline(project_id: int, current_user: User = Depends(require_editor), db: Session = Depends(get_db)):
    project = project_for_user(db, current_user, project_id)
    existing = _decode(project.visibility_baseline_json, None)
    if existing:
        return _payload(project)
    tenant = db.get(Tenant, project.tenant_id)
    try:
        report = reporting.project_report_payload(db, tenant, project)
        report_data = report.get("report") or {}
        quality = report.get("report_quality") or {}
        baseline = {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "mention_rate": report_data.get("mention_rate"),
            "citation_rate": report_data.get("citation_rate"),
            "sample_count": report_data.get("sample_count"),
            "engines": report_data.get("engines") or [],
            "sampling_mode": quality.get("measurement_quality", {}).get("sampling_mode") if isinstance(quality, dict) else None,
        }
    except Exception as exc:
        return {**_payload(project), "baseline_error": str(exc)}
    project.visibility_baseline_json = json.dumps(baseline, separators=(",", ":"))
    db.commit()
    return _payload(project)


@router.get("/{project_id}/offsite-attribution")
def get_offsite_attribution(project_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """返回站外审核清单与归因合同；外部数据源未配置时不虚构结果。"""
    project = project_for_user(db, current_user, project_id)
    plan = _decode(project.visibility_plan_json, {})
    return {
        "status": "not_configured",
        "sources": plan.get("offsite_sources", []),
        "review_queue": [],
        "attribution": {
            "window_days": 30,
            "fields": ["landing_path", "source_host", "utm_source", "utm_medium", "audit_id", "diagnostic_ready"],
            "caveat": "Association with an organic or AI visibility change is not causal proof.",
        },
        "next_steps": ["Connect a verified GSC property", "Connect GA4 with read-only scope", "Review third-party brand facts manually"],
    }
