"""Worker pipeline measurement and action dispatch helpers."""

from types import SimpleNamespace

from api.adapters import global_scope, measurement, sampling_control
from api.adapters.engine import ENGINE_MAX_REPEAT, geolib, job_log_path
from api.db import SessionLocal
from api.models import Job, Project
from api.pipeline_catalog import ACTION_DEFAULTS, ACTION_METHODS, PIPELINE_ACTIONS


def _task_facade():
    from api.worker import tasks as task_module

    return task_module


_INTEGER_LIMITS = {
    "--max-pages": (1, 1000),
    "--limit": (1, 1000),
    "--repeat": (1, ENGINE_MAX_REPEAT),
    "--draft-limit": (1, 100),
}
_FLAG_ARGS = {"--no-recrawl", "--draft", "--no-sample", "--skip-llm", "--no-llm"}
_CSV_ARGS = {"--platforms", "--asset", "--question-ids"}

def _reserve_delivery_gap_sampling(tenant_id, project_slug, job_id, platforms, question_ids, repeat):
    """为交付前自动补采复用当前交付 Job 的预算预留。"""
    if job_id is None:
        return None
    db = SessionLocal()
    try:
        tenant = _task_facade()._tenant_record(db, tenant_id)
        project = db.query(Project).filter(
            Project.tenant_id == (tenant.id if tenant is not None else -1),
            Project.slug == project_slug,
        ).first() if tenant is not None else None
        job = db.get(Job, int(job_id))
        if tenant is None or project is None or job is None:
            raise RuntimeError("delivery_job_not_found")
        try:
            estimate = sampling_control.reserve(
                db,
                tenant,
                project,
                job,
                platforms=list(platforms),
                repeat=int(repeat),
                question_ids=list(question_ids),
            )
        except sampling_control.SamplingBudgetExceeded as exc:
            raise RuntimeError(f"delivery_sampling_budget_exceeded:{exc.code}") from exc
        db.commit()
        return estimate
    finally:
        db.close()


def _prepare_delivery_measurement(tenant_id, project_slug, job_id=None):
    """补齐当前 active funded cohort，并在仍缺证据时让交付失败关闭。"""
    project_directory = geolib.project_dir(project_slug)
    if not (project_directory / "geo.json").is_file():
        return None
    custom_providers = _task_facade()._engine_custom_providers(tenant_id)
    with _task_facade()._funded_engine_context(
        tenant_id,
        project_slug,
        "sample",
        job_id=job_id,
        allow_pool=True,
    ) as funding:
        state = measurement.delivery_question_evidence(
            project_slug,
            funding=funding,
            custom_providers=custom_providers,
        )
        if not state.get("active_cohorts"):
            # A diagnostic-only delivery remains valid without API funding.
            return state
        if state.get("needs_sampling"):
            platforms = list(state.get("target_platforms") or [])
            question_ids = list(state.get("target_question_ids") or [])
            repeat = measurement.MIN_QUESTION_SAMPLES
            if job_id is not None:
                _task_facade()._append_job_event(
                    job_log_path(tenant_id, project_slug, job_id),
                    "delivery evidence gap-fill "
                    + json.dumps({
                        "platform_count": len(platforms),
                        "question_count": len(question_ids),
                        "repeat": repeat,
                        "cohort_changed": bool(state.get("cohort_changed")),
                    }, sort_keys=True),
                )
            _reserve_delivery_gap_sampling(
                tenant_id,
                project_slug,
                job_id,
                platforms,
                question_ids,
                repeat,
            )
            import sample

            result = sample.run(
                project_slug,
                platforms=platforms,
                repeat=repeat,
                question_ids=question_ids,
            )
            _task_facade()._require_sampling_output(
                result,
                project_slug,
                job_id=job_id,
                funding=funding,
            )
            measurement.record_sampling(
                project_slug,
                source="api",
                requested_platforms=platforms,
                question_ids=question_ids,
                repeat=repeat,
                job_id=job_id,
                byok_codes=(funding.get("keys") or {}).keys(),
                pool_codes=funding.get("pool_codes", ()),
                result=result,
                funding=funding,
            )
            global_scope.normalize_project(project_slug)
            state = measurement.delivery_question_evidence(
                project_slug,
                funding=funding,
                custom_providers=custom_providers,
            )
            if job_id is not None:
                _task_facade()._append_job_event(
                    job_log_path(tenant_id, project_slug, job_id),
                    "delivery evidence gap-fill complete "
                    + json.dumps({
                        "ready": bool(state.get("ready")),
                        "measured_platform_count": len(state.get("measured_platforms") or []),
                    }, sort_keys=True),
                )
        if not state.get("ready"):
            evidence = state.get("evidence") or {}
            missing = sum(
                int(item.get("missing_samples") or 0)
                for item in evidence.get("gaps") or []
            )
            raise RuntimeError(
                "delivery_evidence_incomplete:"
                f"{len(evidence.get('gaps') or [])} question(s), {missing} provider/mode sample(s) missing"
            )
        return state


def _should_require_sampling_result(action, params):
    if action == "sample":
        return True
    if action not in ("autopilot", "serve"):
        return False
    params = params or {}
    if params.get("--no-sample", False) or params.get("no_sample", False):
        return False
    return True


def _action_namespace(action, params=None):
    """按引擎动作白名单清洗参数，并转换为 geo.cmd_* 所需对象。"""
    if action not in PIPELINE_ACTIONS:
        raise ValueError(f"unsupported pipeline action: {action}")
    values = dict(ACTION_DEFAULTS[action])
    allowed = set(PIPELINE_ACTIONS[action]["args"])
    for raw_name, value in (params or {}).items():
        flag = str(raw_name)
        if not flag.startswith("--"):
            flag = "--" + flag.replace("_", "-")
        if flag not in allowed:
            continue
        name = flag[2:].replace("-", "_")
        if flag in _FLAG_ARGS:
            values[name] = value is True
        elif value in (None, "", []):
            continue
        elif flag in _INTEGER_LIMITS:
            number = int(value)
            minimum, maximum = _INTEGER_LIMITS[flag]
            if not minimum <= number <= maximum:
                raise ValueError(f"{flag} must be between {minimum} and {maximum}")
            values[name] = number
        elif flag in _CSV_ARGS:
            values[name] = ",".join(str(item) for item in value) if isinstance(value, list) else str(value)
    return SimpleNamespace(**values)


def _run_pipeline_action(action, project_slug, params=None):
    import geo

    method = getattr(geo, ACTION_METHODS[action])
    args = _task_facade()._action_namespace(action, params)
    args.slug = project_slug
    method(args)
    return {"status": "done", "action": action, "project_slug": project_slug}

__all__ = tuple(name for name in globals() if not name.startswith("__"))
