"""采样调用量、平台成本估算和项目预算约束。"""

from datetime import datetime, timezone

from sqlalchemy import func

from api.adapters.engine import geolib, load_custom_providers, with_tenant_context
from api.adapters import measurement, sampling_modes
from api.billing.platform_pool import resolve_funding
from api.models import Job, PlatformUsage, Project, Tenant
from api.billing.limits import check_sample_run


class SamplingBudgetExceeded(ValueError):
    def __init__(self, code, estimate):
        super().__init__(code)
        self.code = code
        self.estimate = estimate


class SamplingPlatformMarketMismatch(ValueError):
    """显式请求的平台与项目市场不匹配。"""

    code = "sample_platform_market_mismatch"

    def __init__(self, platforms, project_market):
        self.platforms = tuple(sorted(set(platforms)))
        self.project_market = project_market
        super().__init__(f"{self.code}:{','.join(self.platforms)}:{project_market}")


BUILTIN_GLOBAL_SAMPLE_PLATFORMS = ("openai", "claude", "gemini", "grok", "perplexity", "deepseek")
BUILTIN_CN_SAMPLE_PLATFORMS = ("glm", "doubao", "deepseek", "kimi", "minimax")


def _market_matches(provider_market, project_market):
    provider_market = provider_market or "both"
    project_market = project_market or "both"
    return provider_market == "both" or project_market == "both" or provider_market == project_market


def platform_matches_market(code, project_market, custom_providers=None):
    """判断内置或租户自定义 API 平台是否属于项目市场。"""
    import sample

    custom = next(
        (item for item in (custom_providers or []) if item.get("code") == code),
        None,
    )
    provider = custom or sample.PROVIDERS.get(code) or {}
    return _market_matches(provider.get("market"), project_market)


def default_sample_platforms(funding, custom_providers, config_platforms=None, project_market="both"):
    """Prefer funded built-in APIs and saved custom endpoints, then geo.json."""
    import sample

    funded = set((funding or {}).get("keys") or {}) | set((funding or {}).get("pool_codes") or ())
    # Saved custom providers are first-class engines. They are not in sample.PROVIDERS
    # until tenant context registers them, so do not require that registry here.
    custom_codes = [
        provider["code"]
        for provider in (custom_providers or [])
        if provider.get("code")
    ]
    built_in = []
    for code in BUILTIN_CN_SAMPLE_PLATFORMS + BUILTIN_GLOBAL_SAMPLE_PLATFORMS:
        provider = sample.PROVIDERS.get(code) or {}
        if code in funded and _market_matches(provider.get("market"), project_market):
            built_in.append(code)
    custom_codes = [
        code for code in custom_codes
        if platform_matches_market(code, project_market, custom_providers)
    ]
    chosen = list(dict.fromkeys(built_in + custom_codes))
    if chosen:
        return chosen
    known = set(sample.PROVIDERS) | set(custom_codes)
    return [
        code for code in (config_platforms or [])
        if code in known and _market_matches((sample.PROVIDERS.get(code) or {}).get("market"), project_market)
    ]


def _month_range():
    now = datetime.now(timezone.utc)
    start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    if now.month == 12:
        end = datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(now.year, now.month + 1, 1, tzinfo=timezone.utc)
    return start, end


def _project_pool_spend(db, project_id):
    start, end = _month_range()
    calls, amount = db.query(
        func.coalesce(func.sum(PlatformUsage.calls), 0),
        func.coalesce(func.sum(PlatformUsage.amount_cny_fen), 0),
    ).filter(
        PlatformUsage.project_id == project_id,
        PlatformUsage.created_at >= start,
        PlatformUsage.created_at < end,
    ).one()
    return {"month": start.date().isoformat(), "calls": int(calls or 0), "cost_cny_fen": int(amount or 0)}


def _project_pool_reservations(db, project_id):
    calls, amount = db.query(
        func.coalesce(func.sum(Job.reserved_platform_calls), 0),
        func.coalesce(func.sum(Job.reserved_platform_cost_cny_fen), 0),
    ).filter(
        Job.project_id == project_id,
        Job.budget_reservation_status.in_(("reserved", "review")),
    ).one()
    return {"calls": int(calls or 0), "cost_cny_fen": int(amount or 0)}


def estimate(db, tenant, project, *, platforms=None, limit=None, repeat=1, question_ids=None, allow_pool=True):
    """按当前问题集和资金来源估算一次采样，不返回密钥。"""
    import sample

    requested = platforms
    selected_question_ids = {str(value).strip() for value in (question_ids or []) if str(value).strip()}
    if isinstance(requested, str):
        requested = [item.strip() for item in requested.split(",") if item.strip()]
    funding = resolve_funding(db, tenant.id, project.slug, allow_pool=allow_pool)
    custom_providers = load_custom_providers(db, tenant.id)
    with with_tenant_context(tenant.directory_slug, project.slug, custom_providers=custom_providers):
        config_path = geolib.project_dir(project.slug) / "geo.json"
        config = geolib.load_config(project.slug) if config_path.is_file() else {
            "questions": [],
            "platforms": list(requested or []),
        }
        configured = [provider["code"] for provider in custom_providers]
        custom_codes = set(configured)
        project_market = getattr(project, "market", None)
        if project_market not in ("cn", "global", "both"):
            project_market = config.get("market") if config.get("market") in ("cn", "global", "both") else "both"
        if requested:
            mismatched = [
                code for code in requested
                if not platform_matches_market(code, project_market, custom_providers)
            ]
            if mismatched:
                raise SamplingPlatformMarketMismatch(mismatched, project_market)
        requested = list(dict.fromkeys(requested or default_sample_platforms(
            funding, custom_providers, list(config.get("platforms", [])) + configured,
            project_market,
        )))
        items = []
        total_calls = 0
        pool_calls = 0
        pool_cost = 0
        byok_calls = 0
        for code in requested:
            provider = sample.PROVIDERS.get(code)
            if provider is None and code not in custom_codes:
                continue
            if provider is None:
                provider = next(
                    (item for item in custom_providers if item["code"] == code),
                    {"name": code, "search": False},
                )
            if code in funding.get("pool_codes", ()):
                source = "platform_pool"
            elif code in funding.get("keys", {}) or code in custom_codes:
                source = "byok"
            else:
                source = "unavailable"
            question_count = len(sample.questions_for(config, code, selected_question_ids or None))
            if limit:
                question_count = min(question_count, int(limit))
            calls = question_count * int(repeat) if source != "unavailable" else 0
            unit_price = funding.get("rates", {}).get(code) if source == "platform_pool" else None
            estimated_cost = calls * int(unit_price) if unit_price is not None else None
            model_id = provider.get("model_id") or provider.get("model")
            total_calls += calls
            if source == "platform_pool":
                pool_calls += calls
                pool_cost += estimated_cost or 0
            elif source == "byok":
                byok_calls += calls
            items.append({
                "engine_code": code,
                "engine_name": provider.get("name", code),
                "provider_name": provider.get("name", code),
                "model_id": model_id,
                "sampling_mode": sampling_modes.for_provider(provider),
                "source": source,
                "funding_source": source,
                "questions": question_count,
                "repeat": int(repeat),
                "calls": calls,
                "estimated_cost_cny_fen": estimated_cost,
            })

    usage = _project_pool_spend(db, project.id)
    reservations = _project_pool_reservations(db, project.id)
    budget = project.monthly_budget_cny_fen
    projected = usage["cost_cny_fen"] + reservations["cost_cny_fen"] + pool_cost
    call_limit_exceeded = project.sample_call_limit is not None and total_calls > project.sample_call_limit
    budget_exceeded = budget is not None and pool_calls > 0 and projected > budget
    paused = bool(project.pause_on_budget_exceeded and (call_limit_exceeded or budget_exceeded))
    return {
        "project_id": project.id,
        "question_set_version": measurement.question_set_version(config),
        "question_ids": sorted(selected_question_ids),
        "platforms": items,
        "estimate": {
            "calls": total_calls,
            "byok_calls": byok_calls,
            "platform_pool_calls": pool_calls,
            "platform_pool_cost_cny_fen": pool_cost,
            "byok_cost_cny_fen": None,
            "byok_cost_note": "BYOK costs are billed directly by API providers; CiteAura does not read provider invoices.",
            "minutes": max(1, round(total_calls * 0.4)) if total_calls else 0,
        },
        "budget": {
            "monthly_budget_cny_fen": budget,
            "sample_call_limit": project.sample_call_limit,
            "pause_on_budget_exceeded": bool(project.pause_on_budget_exceeded),
            "month": usage["month"],
            "used_platform_pool_calls": usage["calls"],
            "used_platform_pool_cost_cny_fen": usage["cost_cny_fen"],
            "reserved_platform_pool_calls": reservations["calls"],
            "reserved_platform_pool_cost_cny_fen": reservations["cost_cny_fen"],
            "projected_platform_pool_cost_cny_fen": projected,
            "remaining_cny_fen": None if budget is None else max(
                0, budget - usage["cost_cny_fen"] - reservations["cost_cny_fen"],
            ),
            "call_limit_exceeded": call_limit_exceeded,
            "budget_exceeded": budget_exceeded,
            "paused": paused,
        },
    }


def ensure_allowed(db, tenant, project, **kwargs):
    result = estimate(db, tenant, project, **kwargs)
    budget = result["budget"]
    if budget["paused"]:
        code = "sample_call_limit_exceeded" if budget["call_limit_exceeded"] else "monthly_budget_exceeded"
        raise SamplingBudgetExceeded(code, result)
    return result


def reserve(db, tenant, project, job, **kwargs):
    """Lock the project budget row and reserve an estimated platform-pool amount."""
    locked_tenant = db.query(Tenant).filter(Tenant.id == tenant.id).with_for_update().one()
    locked_project = db.query(Project).filter(Project.id == project.id).with_for_update().one()
    check_sample_run(db, locked_tenant, locked_project)
    result = ensure_allowed(db, locked_tenant, locked_project, **kwargs)
    estimate_data = result["estimate"]
    calls = int(estimate_data["platform_pool_calls"] or 0)
    cost = int(estimate_data["platform_pool_cost_cny_fen"] or 0)
    job.reserved_platform_calls = calls
    job.reserved_platform_cost_cny_fen = cost
    job.budget_reservation_status = "reserved" if calls or cost else None
    return result
