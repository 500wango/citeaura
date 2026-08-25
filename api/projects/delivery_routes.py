"""项目验收、交付下载和发送 API。"""

from api.projects.project_route_support import *  # noqa: F401,F403

router = APIRouter(tags=["projects"])

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

__all__ = tuple(name for name in globals() if not name.startswith("__"))
