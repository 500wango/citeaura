"""项目创建、预检、项目状态和采样配置 API。"""

from api.projects.project_route_support import *  # noqa: F401,F403

router = APIRouter(tags=["projects"])

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


def create_project(
    payload: ProjectCreate,
    current_user: User = Depends(require_editor),
    db: Session = Depends(get_db),
):
    """创建项目、初始化引擎目录并投递 Bootstrap 任务。"""
    try:
        _route_facade().validate_outbound_url(payload.url, require_https=False)
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
            with _route_facade().with_tenant_context(tenant.directory_slug, slug):
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
        with _route_facade().with_tenant_context(tenant.directory_slug, slug):
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

__all__ = tuple(name for name in globals() if not name.startswith("__"))
