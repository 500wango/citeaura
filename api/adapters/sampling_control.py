"""采样调用量、平台成本估算和项目预算约束。"""

from datetime import datetime, timezone

from sqlalchemy import func

from api.adapters.engine import geolib, with_tenant_context
from api.billing.platform_pool import resolve_funding
from api.models import PlatformUsage


class SamplingBudgetExceeded(ValueError):
    def __init__(self, code, estimate):
        super().__init__(code)
        self.code = code
        self.estimate = estimate


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


def estimate(db, tenant, project, *, platforms=None, limit=None, repeat=1):
    """按当前问题集和资金来源估算一次采样，不返回密钥。"""
    import sample

    requested = platforms
    if isinstance(requested, str):
        requested = [item.strip() for item in requested.split(",") if item.strip()]
    funding = resolve_funding(db, tenant.id, project.slug)
    with with_tenant_context(tenant.name, project.slug):
        config_path = geolib.project_dir(project.slug) / "geo.json"
        config = geolib.load_config(project.slug) if config_path.is_file() else {
            "questions": [],
            "platforms": list(requested or []),
        }
        requested = list(dict.fromkeys(requested or [code for code in config.get("platforms", []) if code in sample.PROVIDERS]))
        items = []
        total_calls = 0
        pool_calls = 0
        pool_cost = 0
        byok_calls = 0
        for code in requested:
            if code not in sample.PROVIDERS:
                continue
            if code in funding.get("pool_codes", ()):
                source = "platform_pool"
            elif code in funding.get("keys", {}):
                source = "byok"
            else:
                source = "unavailable"
            question_count = len(sample.questions_for(config, code))
            if limit:
                question_count = min(question_count, int(limit))
            calls = question_count * int(repeat) if source != "unavailable" else 0
            unit_price = funding.get("rates", {}).get(code) if source == "platform_pool" else None
            estimated_cost = calls * int(unit_price) if unit_price is not None else None
            total_calls += calls
            if source == "platform_pool":
                pool_calls += calls
                pool_cost += estimated_cost or 0
            elif source == "byok":
                byok_calls += calls
            items.append({
                "engine_code": code,
                "engine_name": sample.PROVIDERS[code].get("name", code),
                "sampling_mode": "API·联网检索" if sample.PROVIDERS[code].get("search") else "API·参数化知识",
                "source": source,
                "questions": question_count,
                "repeat": int(repeat),
                "calls": calls,
                "estimated_cost_cny_fen": estimated_cost,
            })

    usage = _project_pool_spend(db, project.id)
    budget = project.monthly_budget_cny_fen
    projected = usage["cost_cny_fen"] + pool_cost
    call_limit_exceeded = project.sample_call_limit is not None and total_calls > project.sample_call_limit
    budget_exceeded = budget is not None and pool_calls > 0 and projected > budget
    paused = bool(project.pause_on_budget_exceeded and (call_limit_exceeded or budget_exceeded))
    return {
        "project_id": project.id,
        "platforms": items,
        "estimate": {
            "calls": total_calls,
            "byok_calls": byok_calls,
            "platform_pool_calls": pool_calls,
            "platform_pool_cost_cny_fen": pool_cost,
            "byok_cost_cny_fen": None,
            "byok_cost_note": "BYOK 费用由 API 供应商直接收取，DisvorAI 无法读取供应商账单。",
            "minutes": max(1, round(total_calls * 0.4)) if total_calls else 0,
        },
        "budget": {
            "monthly_budget_cny_fen": budget,
            "sample_call_limit": project.sample_call_limit,
            "pause_on_budget_exceeded": bool(project.pause_on_budget_exceeded),
            "month": usage["month"],
            "used_platform_pool_calls": usage["calls"],
            "used_platform_pool_cost_cny_fen": usage["cost_cny_fen"],
            "projected_platform_pool_cost_cny_fen": projected,
            "remaining_cny_fen": None if budget is None else max(0, budget - usage["cost_cny_fen"]),
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
