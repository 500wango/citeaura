from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session
from api.auth.deps import get_current_user, require_editor
from api.db import get_db
from api.models import Tenant, User
from api.projects.access import project_for_user
from api.adapters.engine import with_tenant_read_context, geolib
from api.adapters import citation_sources, offsite_entities
from api import config

router = APIRouter(tags=["citation-sources"])

class CitationTicketPayload(BaseModel):
    domain: str = Field(min_length=1, max_length=253)
    run_id: str = Field(min_length=1, max_length=128)
    suggested_asset: str = Field(min_length=1, max_length=160)
    evidence_urls: list[str] = Field(default_factory=list, max_length=3)

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, value):
        normalized = citation_sources._domain("https://" + value)
        if not normalized or normalized != value.lower().removeprefix("www."):
            raise ValueError("invalid citation domain")
        return normalized

    @field_validator("run_id")
    @classmethod
    def validate_run_id(cls, value):
        if not citation_sources._RUN_ID.fullmatch(value): raise ValueError("invalid citation run id")
        return value

    @field_validator("evidence_urls")
    @classmethod
    def validate_evidence_urls(cls, value):
        for url in value: offsite_entities._valid(url)
        return list(dict.fromkeys(value))

def _ensure_citation_ticket(slug, payload):
    import tasks as engine_tasks
    key = f"{payload.run_id}:{payload.domain}"
    with geolib.project_lock(slug):
        data = engine_tasks.load(slug) or {}; tickets = data.get("tasks") if isinstance(data.get("tasks"), list) else []
        existing = next((item for item in tickets if item.get("citation_key") == key), None)
        if existing: return existing, True
        ticket = {"id": f"CIT-{len(tickets)+1:04d}", "kind": "citation_opportunity", "source": "citation_sources", "citation_key": key, "domain": payload.domain, "run_id": payload.run_id, "suggested_asset": payload.suggested_asset, "priority": "P1", "status": "todo", "package": "Content matrix", "market": "both", "owner": "Content", "effort": "M", "title": f"Build citation-ready asset for {payload.domain}", "action": f"Create or improve {payload.suggested_asset} using the linked evidence.", "acceptance": {"type": "verify", "desc": "Re-run the same question, sampling mode, and comparable cohort; record improved, unchanged, regressed, or unmeasured."}, "evidence": [{"source": "citation", "url": url, "run_id": payload.run_id} for url in payload.evidence_urls]}
        tickets.append(ticket); data["tasks"] = tickets; engine_tasks.save(slug, data); return ticket, False

@router.post("/{project_id}/citation-sources/tickets")
def create_citation_ticket(project_id: int, payload: CitationTicketPayload, current_user: User = Depends(require_editor), db: Session = Depends(get_db)):
    project = project_for_user(db, current_user, project_id); tenant = db.get(Tenant, project.tenant_id)
    with with_tenant_read_context(tenant, project.slug): ticket, reused = _ensure_citation_ticket(project.slug, payload)
    return {"ticket": ticket, "reused": reused}

@router.get("/{project_id}/citation-features")
def get_citation_features(project_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project_for_user(db, current_user, project_id)
    return {"api": config.citation_api_enabled(), "channels": config.citation_channels_enabled(), "overview": config.citation_overview_enabled(), "shadow": config.citation_shadow_enabled()}

@router.get("/{project_id}/citation-sources")
def get_citation_sources(project_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = project_for_user(db, current_user, project_id); tenant = db.get(Tenant, project.tenant_id)
    if not config.citation_api_enabled():
        return {"status": "unmeasured", "run_id": None, "sampled_at": None, "total_citations": 0, "domains": [], "warnings": [], "unmeasured_reason": "feature_disabled"}
    with with_tenant_read_context(tenant, project.slug): return citation_sources.aggregate(project.slug)
