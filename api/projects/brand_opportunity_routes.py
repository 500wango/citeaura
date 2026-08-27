"""品牌事实冲突与内容机会 API。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.adapters import brand_opportunities
from api.adapters.engine import with_tenant_read_context
from api.auth.deps import get_current_user, require_editor
from api.db import get_db
from api.models import Tenant, User
from api.projects.access import project_for_user
from api.adapters.engine import geolib

router = APIRouter(tags=["brand-opportunities"])


def _ensure_opportunity_tickets(slug, opportunities):
    import tasks as engine_tasks
    with geolib.project_lock(slug):
        data = engine_tasks.load(slug) or {}
        tickets = data.get("tasks") if isinstance(data.get("tasks"), list) else []
        existing = {str(item.get("opportunity_id") or item.get("opportunity_question")) for item in tickets}
        for item in opportunities:
            question = str(item.get("question") or "").strip()
            opportunity_id = str(item.get("id") or "")
            if not question or (opportunity_id and opportunity_id in existing) or question in existing:
                continue
            tickets.append({"id": f"C-{len(tickets)+1:04d}", "kind": "content_opportunity", "source": "brand_opportunities", "opportunity_id": opportunity_id, "opportunity_question": question, "question_id": item.get("question_id"), "priority": "P1", "status": "todo", "package": "Content matrix", "market": "both", "owner": "Content", "effort": "M", "title": f"Answer: {question}", "action": f"Create or improve a {item.get('suggested_page_type') or 'answer page'}.", "acceptance": item.get("acceptance_criteria") or {"type": "verify", "desc": "Re-run sampling and verify the target question."}, "evidence": item.get("evidence") or []})
            existing.add(opportunity_id or question)
            existing.add(question)
        data["tasks"] = tickets
        engine_tasks.save(slug, data)
    return tickets


@router.get("/{project_id}/brand-opportunities")
def get_brand_opportunities(project_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = project_for_user(db, current_user, project_id)
    tenant = db.get(Tenant, project.tenant_id)
    with with_tenant_read_context(tenant, project.slug):
        return brand_opportunities.assess(project.slug)


@router.post("/{project_id}/brand-opportunities/tickets")
def create_opportunity_tickets(project_id: int, current_user: User = Depends(require_editor), db: Session = Depends(get_db)):
    project = project_for_user(db, current_user, project_id)
    tenant = db.get(Tenant, project.tenant_id)
    with with_tenant_read_context(tenant, project.slug):
        result = brand_opportunities.assess(project.slug)
        tickets = _ensure_opportunity_tickets(project.slug, result.get("opportunities") or [])
    return {"tickets": [item for item in tickets if item.get("kind") == "content_opportunity"]}

@router.post("/{project_id}/brand-opportunities/{opportunity_id}/ticket")
def create_one_opportunity_ticket(project_id: int, opportunity_id: str, current_user: User = Depends(require_editor), db: Session = Depends(get_db)):
    project = project_for_user(db, current_user, project_id); tenant = db.get(Tenant, project.tenant_id)
    with with_tenant_read_context(tenant, project.slug):
        result = brand_opportunities.assess(project.slug)
        item = next((row for row in result.get("opportunities") or [] if str(row.get("id")) == opportunity_id), None)
        if item is None: raise HTTPException(status_code=404, detail={"error": "opportunity_not_found"})
        before = _ensure_opportunity_tickets(project.slug, [])
        existing = next((row for row in before if row.get("opportunity_id") == opportunity_id), None)
        tickets = _ensure_opportunity_tickets(project.slug, [item])
        ticket = next(row for row in tickets if row.get("opportunity_id") == opportunity_id)
        return {"ticket": ticket, "reused": existing is not None}
