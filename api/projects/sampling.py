"""项目采样权限、参数校验和预算估算。"""

from fastapi import HTTPException, status
from pydantic import ValidationError

from api.adapters import sampling_control, workspace
from api.adapters.engine import load_custom_providers, load_tenant_keys, with_tenant_read_context
from api.adapters.exceptions import GeoEngineError
from api.billing.platform_pool import PAID_PLANS, public_catalog
from api.projects.schemas import SampleEstimateRequest, SampleRequest
from api.projects.access import error


def require_project_questions(tenant, project):
    """采样入队前确认项目已有目标问题。"""
    try:
        with with_tenant_read_context(tenant, project.slug):
            config = workspace.ensure_global_engine_scope(project.slug)
    except GeoEngineError:
        config = {}
    if not config.get("questions"):
        error(status.HTTP_409_CONFLICT, "project_questions_required")


def normalize_sample_question_ids(tenant, project, payload: SampleRequest):
    """验证问题级采样范围，避免把错误 ID 投递到 Worker 后才失败。"""
    if not payload.question_ids:
        return payload
    with with_tenant_read_context(tenant, project.slug):
        config = workspace.ensure_global_engine_scope(project.slug)
    valid = {
        str(question.get("id"))
        for question in config.get("questions") or []
        if isinstance(question, dict) and question.get("id")
    }
    selected = []
    for value in payload.question_ids:
        question_id = str(value).strip()
        if question_id and question_id not in selected:
            selected.append(question_id)
    unknown = [question_id for question_id in selected if question_id not in valid]
    if unknown:
        error(status.HTTP_422_UNPROCESSABLE_ENTITY, "sample_question_not_found")
    return payload.model_copy(update={"question_ids": selected or None})


def has_api_keys(db, tenant_id):
    return bool(load_tenant_keys(db, tenant_id))


def enable_platform_pool_if_available(tenant, project):
    """Paid workspaces can run the first matrix from the platform pool."""
    if project.platform_pool_enabled:
        return True
    if tenant.plan in PAID_PLANS and public_catalog():
        project.platform_pool_enabled = True
        return True
    return False


def has_sampling_access(db, tenant, project):
    return (
        has_api_keys(db, tenant.id)
        or bool(load_custom_providers(db, tenant.id))
        or bool(project.platform_pool_enabled and tenant.plan in PAID_PLANS and public_catalog())
    )


def estimate(db, tenant, project, payload, enforce=False, allow_pool=True):
    import sample

    platforms = payload.platforms if payload else None
    custom_codes = {provider["code"] for provider in load_custom_providers(db, tenant.id)}
    if platforms and any(code not in sample.PROVIDERS and code not in custom_codes for code in platforms):
        error(status.HTTP_422_UNPROCESSABLE_ENTITY, "sample_platform_must_have_api")
    function = sampling_control.ensure_allowed if enforce else sampling_control.estimate
    try:
        return function(
            db, tenant, project,
            platforms=platforms,
            limit=payload.limit if payload else None,
            repeat=payload.repeat if payload else 1,
            question_ids=payload.question_ids if payload else None,
            allow_pool=allow_pool,
        )
    except sampling_control.SamplingPlatformMarketMismatch as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": exc.code,
                "platforms": list(exc.platforms),
                "project_market": exc.project_market,
            },
        ) from exc
    except sampling_control.SamplingBudgetExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": exc.code, "estimate": exc.estimate},
        ) from exc


def normalize_estimate_payload(tenant, project, payload):
    payload = payload or SampleEstimateRequest()
    if payload.question_ids:
        sample_payload = SampleRequest(
            limit=payload.limit,
            platforms=payload.platforms,
            repeat=payload.repeat,
            question_ids=payload.question_ids,
        )
        payload = payload.model_copy(update={
            "question_ids": normalize_sample_question_ids(tenant, project, sample_payload).question_ids,
        })
    return payload


def validated_estimate(db, tenant, project, payload, enforce=False, allow_pool=True):
    payload = normalize_estimate_payload(tenant, project, payload)
    return estimate(db, tenant, project, payload, enforce=enforce, allow_pool=allow_pool)


def reserve(db, tenant, project, job, payload):
    try:
        return sampling_control.reserve(
            db, tenant, project, job,
            platforms=payload.platforms if payload else None,
            limit=payload.limit if payload else None,
            repeat=payload.repeat if payload else 1,
            question_ids=payload.question_ids if payload else None,
        )
    except sampling_control.SamplingPlatformMarketMismatch as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": exc.code,
                "platforms": list(exc.platforms),
                "project_market": exc.project_market,
            },
        ) from exc
    except sampling_control.SamplingBudgetExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": exc.code, "estimate": exc.estimate},
        ) from exc


def pipeline_sample_payload(params):
    def value(name, default=None):
        return params.get(f"--{name}", params.get(name, default))

    platforms = value("platforms")
    if isinstance(platforms, str):
        platforms = [item.strip() for item in platforms.split(",") if item.strip()]
    question_ids = value("question-ids")
    if isinstance(question_ids, str):
        question_ids = [item.strip() for item in question_ids.split(",") if item.strip()]
    try:
        return SampleEstimateRequest(
            limit=value("limit"),
            platforms=platforms,
            repeat=value("repeat", 1),
            question_ids=question_ids,
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "invalid_sample_parameters", "detail": str(exc)},
        ) from exc


def pipeline_flag(params, name):
    return params.get(f"--{name}", params.get(name, False)) is True
