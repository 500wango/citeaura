"""平台 Key 池解析、BYOK 优先合并和按调用计费。"""

import json
import threading
from collections import Counter
from contextlib import contextmanager
from datetime import date, datetime, timezone

from sqlalchemy import func

from api import config
from api.adapters.engine import ENGINE_KEY_ENV, load_tenant_keys
from api.db import SessionLocal
from api.models import Job, PlatformUsage, Project, Tenant, UsageCounter


PAID_PLANS = frozenset(("pro", "agency", "enterprise"))


def _prices():
    try:
        value = json.loads(config.platform_pool_prices() or "{}")
    except (TypeError, ValueError):
        return {}
    if not isinstance(value, dict):
        return {}
    prices = {}
    for code, amount in value.items():
        code = str(code).strip().lower()
        if code not in ENGINE_KEY_ENV or isinstance(amount, bool):
            continue
        try:
            amount = int(amount)
        except (TypeError, ValueError):
            continue
        if amount > 0:
            prices[code] = amount
    return prices


def configured_pool():
    """返回已同时配置密钥和正数单价的平台；不对外暴露密钥。"""
    prices = _prices()
    pool = {}
    for code, provider_env in ENGINE_KEY_ENV.items():
        key = config.platform_pool_key(provider_env)
        if key and code in prices:
            pool[code] = {"key": key, "unit_price_cny_fen": prices[code]}
    return pool


def public_catalog():
    import sample

    catalog = []
    for code, item in sorted(configured_pool().items()):
        provider = sample.PROVIDERS.get(code, {})
        catalog.append({
            "engine_code": code,
            "engine_name": provider.get("name", code),
            "sampling_mode": "API·联网" if provider.get("search") else "API·参数化",
            "unit_price_cny_fen": item["unit_price_cny_fen"],
        })
    return catalog


def _tenant(db, tenant_id):
    try:
        return db.get(Tenant, int(tenant_id))
    except (TypeError, ValueError):
        return db.query(Tenant).filter(Tenant.name == str(tenant_id)).first()


def resolve_funding(db, tenant_id, project_slug, allow_pool=True):
    """合并当前租户 BYOK 与项目平台池；相同引擎始终由 BYOK 覆盖。"""
    tenant = _tenant(db, tenant_id)
    if tenant is None:
        return {"keys": {}, "pool_codes": frozenset(), "rates": {}, "tenant_id": None, "project_id": None}
    project = db.query(Project).filter(
        Project.tenant_id == tenant.id,
        Project.slug == project_slug,
    ).first()
    byok = load_tenant_keys(db, tenant.id)
    pool = {}
    if (
        allow_pool
        and project is not None
        and project.platform_pool_enabled
        and tenant.plan in PAID_PLANS
    ):
        pool = configured_pool()
    pool_codes = frozenset(code for code in pool if code not in byok)
    keys = {code: item["key"] for code, item in pool.items()}
    keys.update(byok)
    return {
        "keys": keys,
        "pool_codes": pool_codes,
        "rates": {code: pool[code]["unit_price_cny_fen"] for code in pool_codes},
        "tenant_id": tenant.id,
        "project_id": project.id if project is not None else None,
    }


@contextmanager
def meter_platform_calls(engine_codes):
    """统计通过平台池发出的逻辑引擎调用，覆盖采样及同管线 LLM 调用。"""
    codes = frozenset(engine_codes)
    counts = Counter()
    if not codes:
        yield counts
        return
    import sample

    original = sample.ask
    lock = threading.Lock()

    def metered(platform, *args, **kwargs):
        if platform in codes:
            with lock:
                counts[platform] += 1
        return original(platform, *args, **kwargs)

    sample.ask = metered
    try:
        yield counts
    finally:
        sample.ask = original


def _month_start(value=None):
    value = value or datetime.now(timezone.utc)
    return date(value.year, value.month, 1)


def record_usage(funding, counts, action, job_id=None):
    """把平台代付调用写入账本和月度汇总；同一任务/引擎只入账一次。"""
    if not funding.get("tenant_id") or not funding.get("project_id"):
        return []
    rows = []
    db = SessionLocal()
    try:
        valid_job_id = None
        if job_id is not None:
            try:
                candidate = int(job_id)
            except (TypeError, ValueError):
                candidate = None
            if candidate and db.get(Job, candidate) is not None:
                valid_job_id = candidate
        counter = db.get(UsageCounter, {
            "tenant_id": funding["tenant_id"],
            "month": _month_start(),
        })
        if counter is None:
            counter = UsageCounter(
                tenant_id=funding["tenant_id"],
                month=_month_start(),
                platform_calls=0,
                platform_cost_cny_fen=0,
            )
            db.add(counter)
        for code, count in sorted(counts.items()):
            count = int(count)
            if count <= 0 or code not in funding.get("pool_codes", ()):
                continue
            if valid_job_id is not None and db.query(PlatformUsage.id).filter(
                PlatformUsage.job_id == valid_job_id,
                PlatformUsage.engine_code == code,
            ).first() is not None:
                continue
            unit_price = int(funding["rates"][code])
            amount = count * unit_price
            row = PlatformUsage(
                tenant_id=funding["tenant_id"],
                project_id=funding["project_id"],
                job_id=valid_job_id,
                action=str(action),
                engine_code=code,
                calls=count,
                unit_price_cny_fen=unit_price,
                amount_cny_fen=amount,
            )
            db.add(row)
            counter.platform_calls = (counter.platform_calls or 0) + count
            counter.platform_cost_cny_fen = (counter.platform_cost_cny_fen or 0) + amount
            rows.append(row)
        db.commit()
        return rows
    finally:
        db.close()


def usage_summary(db, tenant):
    month = _month_start()
    if month.month == 12:
        next_month = datetime(month.year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        next_month = datetime(month.year, month.month + 1, 1, tzinfo=timezone.utc)
    counter = db.get(UsageCounter, {"tenant_id": tenant.id, "month": month})
    grouped = (
        db.query(
            PlatformUsage.engine_code,
            func.sum(PlatformUsage.calls),
            func.sum(PlatformUsage.amount_cny_fen),
        )
        .filter(
            PlatformUsage.tenant_id == tenant.id,
            PlatformUsage.created_at >= datetime(month.year, month.month, 1, tzinfo=timezone.utc),
            PlatformUsage.created_at < next_month,
        )
        .group_by(PlatformUsage.engine_code)
        .order_by(PlatformUsage.engine_code)
        .all()
    )
    calls = int((counter.platform_calls if counter else 0) or 0)
    amount = int((counter.platform_cost_cny_fen if counter else 0) or 0)
    return {
        "month": month.isoformat(),
        "calls": calls,
        "cost_cny_fen": amount,
        "cost_cny": f"{amount / 100:.2f}",
        "by_engine": [
            {"engine_code": code, "calls": int(engine_calls or 0), "cost_cny_fen": int(engine_amount or 0)}
            for code, engine_calls, engine_amount in grouped
        ],
    }
