"""Citation Readiness 只读 API。"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.auth.deps import get_current_user, require_editor
from api.db import get_db
from api.models import Tenant, User
from api.projects.access import project_for_user
from api.adapters.engine import with_tenant_read_context, geolib
from api.adapters import citation_readiness
from api.adapters import global_scope

router = APIRouter(tags=["citation-readiness"])


def _ensure_tickets(slug, findings):
    """按稳定 code 幂等写入 readiness 工单。"""
    import tasks as engine_tasks
    with geolib.project_lock(slug):
        data = engine_tasks.load(slug) or {}
        tickets = data.get("tasks") if isinstance(data.get("tasks"), list) else []
        existing = {str(item.get("readiness_code")) for item in tickets}
        for finding in findings:
            code = str(finding.get("code") or "")
            if not code or code in existing:
                continue
            tickets.append({"id": f"R-{len(tickets)+1:04d}", "readiness_code": code, "kind": "readiness", "source": "citation_readiness", "priority": "P1", "status": "todo", "title": finding.get("message") or code, "why": "Citation Readiness evidence indicates this needs review.", "action": finding.get("message") or "Review the readiness evidence.", "evidence": finding.get("evidence") or []})
            existing.add(code)
        data["tasks"] = tickets
        engine_tasks.save(slug, data)
    return tickets


@router.get("/{project_id}/citation-readiness")
def get_citation_readiness(project_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = project_for_user(db, current_user, project_id)
    tenant = db.get(Tenant, project.tenant_id)
    with with_tenant_read_context(tenant, project.slug):
        return citation_readiness.assess(project.slug)


@router.post("/{project_id}/citation-readiness/tickets")
def create_readiness_tickets(project_id: int, current_user: User = Depends(require_editor), db: Session = Depends(get_db)):
    project = project_for_user(db, current_user, project_id)
    tenant = db.get(Tenant, project.tenant_id)
    with with_tenant_read_context(tenant, project.slug):
        result = citation_readiness.assess(project.slug)
        tickets = _ensure_tickets(project.slug, result.get("findings") or [])
    return {"created_or_existing": len([item for item in tickets if item.get("kind") == "readiness"]), "tickets": [item for item in tickets if item.get("kind") == "readiness"]}
