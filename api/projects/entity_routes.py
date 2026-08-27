from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from api.auth.deps import get_current_user, require_editor
from api.db import get_db
from api.models import Tenant, User
from api.projects.access import project_for_user
from api.adapters.engine import with_tenant_read_context
from api.adapters import citation_sources, offsite_entities

router = APIRouter(tags=["entities"])
class EntityPayload(BaseModel): items: list[dict] = Field(default_factory=list, max_length=100)
@router.get("/{project_id}/entities")
def get_entities(project_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project=project_for_user(db,current_user,project_id); tenant=db.get(Tenant,project.tenant_id)
    with with_tenant_read_context(tenant, project.slug):
        citation=citation_sources.aggregate(project.slug)
        return {"items": offsite_entities.load(project.slug, [x["domain"] for x in citation.get("domains",[])]), "deleted": offsite_entities.deleted(project.slug)}
@router.put("/{project_id}/entities")
def put_entities(project_id: int, payload: EntityPayload, current_user: User = Depends(require_editor), db: Session = Depends(get_db)):
    project=project_for_user(db,current_user,project_id); tenant=db.get(Tenant,project.tenant_id)
    try:
        with with_tenant_read_context(tenant, project.slug): return {"items": offsite_entities.save(project.slug, payload.items)}
    except ValueError as exc: raise HTTPException(status_code=422, detail={"error": str(exc)})

@router.post("/{project_id}/entities/{entity_id}/restore")
def restore_entity(project_id: int, entity_id: str, current_user: User = Depends(require_editor), db: Session = Depends(get_db)):
    project=project_for_user(db,current_user,project_id); tenant=db.get(Tenant,project.tenant_id)
    with with_tenant_read_context(tenant, project.slug):
        return {"restored": offsite_entities.restore(project.slug, entity_id)}
