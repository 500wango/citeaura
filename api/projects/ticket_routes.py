"""项目工单和 Playbook API。"""

from api.projects.project_route_support import *  # noqa: F401,F403

router = APIRouter(tags=["projects"])

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

__all__ = tuple(name for name in globals() if not name.startswith("__"))
