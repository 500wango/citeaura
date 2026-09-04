"""项目采样、报告、导出和引擎操作 API。"""

from api.projects.project_route_support import *  # noqa: F401,F403

router = APIRouter(tags=["projects"])

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
    if int(source.attempt or 1) >= MAX_JOB_ATTEMPTS:
        _error(status.HTTP_409_CONFLICT, "job_retry_attempt_limit")
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

__all__ = tuple(name for name in globals() if not name.startswith("__"))
