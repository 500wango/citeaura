"""平台 Key 池解析、BYOK 优先合并和按调用计费。"""

import json
from collections import Counter
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from api import config
from api.adapters.engine import ENGINE_KEY_ENV, load_tenant_keys, resolve_tenant
from api.adapters import sampling_modes
from api.billing.metering import meter_platform_calls  # noqa: F401 - 保持原有导出
from api.db import SessionLocal
from api.models import Job, PlatformUsage, PlatformUsageOutbox, Project, UsageCounter
from api.billing.access import sync_tenant_plan


POOL_PLANS = frozenset(("trial", "starter", "pro", "agency"))
PAID_PLANS = frozenset(("starter", "pro", "agency"))


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
            "sampling_mode": sampling_modes.for_provider(provider),
            "sampling_mode_code": sampling_modes.code_for_provider(provider),
            "search": bool(provider.get("search")),
            "unit_price_cny_fen": item["unit_price_cny_fen"],
        })
    return catalog


def _tenant(db, tenant_id):
    return resolve_tenant(db, tenant_id)


def trial_pool_remaining(db, tenant_id):
    """试用期平台池剩余预算（分）；按租户历史代付总额封顶。"""
    spent = db.query(func.coalesce(func.sum(PlatformUsage.amount_cny_fen), 0)).filter(
        PlatformUsage.tenant_id == tenant_id,
    ).scalar()
    return max(0, config.trial_starting_budget_cny_fen() - int(spent or 0))


def resolve_funding(db, tenant_id, project_slug, allow_pool=True):
    """合并当前租户 BYOK 与项目平台池；相同引擎始终由 BYOK 覆盖。"""
    tenant = _tenant(db, tenant_id)
    if tenant is not None:
        sync_tenant_plan(db, tenant.id)
    if tenant is None:
        return {
            "keys": {}, "pool_codes": frozenset(), "rates": {},
            "tenant_id": None, "tenant_directory_slug": None, "project_id": None,
        }
    project = db.query(Project).filter(
        Project.tenant_id == tenant.id,
        Project.slug == project_slug,
    ).first()
    byok = load_tenant_keys(db, tenant.id)
    pool = {}
    pool_allowed = (
        allow_pool
        and project is not None
        and project.platform_pool_enabled
        and tenant.plan in POOL_PLANS
    )
    if pool_allowed and tenant.plan == "trial":
        pool_allowed = config.trial_pool_enabled() and trial_pool_remaining(db, tenant.id) > 0
    if pool_allowed:
        pool = configured_pool()
    pool_codes = frozenset(code for code in pool if code not in byok)
    keys = {code: item["key"] for code, item in pool.items()}
    keys.update(byok)
    return {
        "keys": keys,
        "pool_codes": pool_codes,
        "rates": {code: pool[code]["unit_price_cny_fen"] for code in pool_codes},
        "tenant_id": tenant.id,
        "tenant_directory_slug": tenant.directory_slug,
        "project_id": project.id if project is not None else None,
    }


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
            if candidate and db.query(Job.id).filter(
                Job.id == candidate,
                Job.project_id == funding["project_id"],
            ).first() is not None:
                valid_job_id = candidate
        if valid_job_id is None:
            # 没有有效 job_id 就没有幂等键：重复调用会重复计入配额与账单。
            # 平台代付只发生在任务内，无主调用直接丢弃并留痕。
            print("[citeaura] platform usage skipped: no valid job_id", flush=True)
            return []
        month = _month_start()
        accepted = []
        total_calls = 0
        total_cost = 0
        for code, count in sorted(counts.items()):
            count = int(count)
            if count <= 0 or code not in funding.get("pool_codes", ()):
                continue
            unit_price = int(funding["rates"][code])
            amount = count * unit_price
            values = {
                "tenant_id": funding["tenant_id"],
                "project_id": funding["project_id"],
                "job_id": valid_job_id,
                "action": str(action),
                "engine_code": code,
                "calls": count,
                "unit_price_cny_fen": unit_price,
                "amount_cny_fen": amount,
            }
            dialect = db.bind.dialect.name
            if dialect == "postgresql":
                statement = postgres_insert(PlatformUsage).values(**values).on_conflict_do_nothing(
                    constraint="uq_platform_usage_job_engine",
                )
            elif dialect == "sqlite":
                statement = sqlite_insert(PlatformUsage).values(**values).on_conflict_do_nothing(
                    index_elements=["job_id", "engine_code"],
                )
            else:
                row = PlatformUsage(**values)
                db.add(row)
                db.flush()
                statement = None
            inserted = True if statement is None else (db.execute(statement).rowcount or 0) > 0
            if inserted:
                accepted.append(values)
                total_calls += count
                total_cost += amount

        if accepted:
            counter_values = {
                "tenant_id": funding["tenant_id"],
                "month": month,
                "sample_runs": 0,
                "projects_active": 0,
                "platform_calls": total_calls,
                "platform_cost_cny_fen": total_cost,
            }
            dialect = db.bind.dialect.name
            if dialect == "postgresql":
                statement = postgres_insert(UsageCounter).values(**counter_values).on_conflict_do_update(
                    index_elements=["tenant_id", "month"],
                    set_={
                        "platform_calls": UsageCounter.platform_calls + total_calls,
                        "platform_cost_cny_fen": UsageCounter.platform_cost_cny_fen + total_cost,
                    },
                )
                db.execute(statement)
            elif dialect == "sqlite":
                statement = sqlite_insert(UsageCounter).values(**counter_values).on_conflict_do_update(
                    index_elements=["tenant_id", "month"],
                    set_={
                        "platform_calls": UsageCounter.platform_calls + total_calls,
                        "platform_cost_cny_fen": UsageCounter.platform_cost_cny_fen + total_cost,
                    },
                )
                db.execute(statement)
            else:
                counter = db.query(UsageCounter).filter(
                    UsageCounter.tenant_id == funding["tenant_id"], UsageCounter.month == month,
                ).with_for_update().first()
                if counter is None:
                    counter = UsageCounter(**counter_values)
                    db.add(counter)
                else:
                    counter.platform_calls += total_calls
                    counter.platform_cost_cny_fen += total_cost
        if valid_job_id is not None:
            reservation_job = db.get(Job, valid_job_id)
            if (
                reservation_job is not None
                and reservation_job.budget_reservation_status in ("reserved", "review")
            ):
                pending = db.query(PlatformUsageOutbox.id).filter(
                    PlatformUsageOutbox.job_id == valid_job_id,
                    PlatformUsageOutbox.status == "pending",
                ).first()
                if not pending:
                    existing_usage = accepted or db.query(PlatformUsage.id).filter(
                        PlatformUsage.job_id == valid_job_id,
                    ).first()
                    reservation_job.budget_reservation_status = "settled" if existing_usage else "released"
        db.commit()
        rows = [PlatformUsage(**values) for values in accepted]
        return rows
    finally:
        db.close()


def persist_usage_outbox(funding, counts, action, job_id=None, error=None):
    """在主计量失败后保存幂等补偿事件，避免成功业务永久漏计。"""
    if not funding.get("tenant_id") or not funding.get("project_id"):
        return 0
    db = SessionLocal()
    created = 0
    try:
        for code, count in sorted(counts.items()):
            count = int(count)
            if count <= 0 or code not in funding.get("pool_codes", ()):
                continue
            unit_price = int(funding["rates"][code])
            if job_id is not None:
                event_key = f"job:{int(job_id)}:{code}"
            else:
                # 幂等键里不能带时间戳：每次重试都会新增一行，重放时重复计费。
                event_key = (
                    f"direct:{funding['tenant_id']}:{funding['project_id']}:{action}:{code}"
                )
            existing = db.query(PlatformUsageOutbox).filter(
                PlatformUsageOutbox.event_key == event_key,
            ).first()
            if existing is not None:
                if existing.status == "pending":
                    existing.calls = count
                    existing.unit_price_cny_fen = unit_price
                    existing.amount_cny_fen = count * unit_price
                    existing.last_error = str(error)[:2000] if error else existing.last_error
                continue
            db.add(PlatformUsageOutbox(
                event_key=event_key,
                tenant_id=funding["tenant_id"],
                project_id=funding["project_id"],
                job_id=int(job_id) if job_id is not None else None,
                action=str(action),
                engine_code=code,
                calls=count,
                unit_price_cny_fen=unit_price,
                amount_cny_fen=count * unit_price,
                last_error=str(error)[:2000] if error else None,
            ))
            created += 1
        if job_id is not None:
            reservation_job = db.get(Job, int(job_id))
            if reservation_job is not None and reservation_job.budget_reservation_status == "reserved":
                reservation_job.budget_reservation_status = "review"
        db.commit()
        return created
    except Exception:
        db.rollback()
        return 0
    finally:
        db.close()


def reconcile_usage_outbox(limit=100):
    """重放持久化计量事件；PlatformUsage 的唯一键保证重试幂等。"""
    db = SessionLocal()
    processed = 0
    now = datetime.now(timezone.utc)
    try:
        rows = db.query(PlatformUsageOutbox).filter(
            PlatformUsageOutbox.status == "pending",
            (PlatformUsageOutbox.next_attempt_at.is_(None) | (PlatformUsageOutbox.next_attempt_at <= now)),
        ).order_by(PlatformUsageOutbox.id).limit(int(limit)).all()
        for row in rows:
            funding = {
                "tenant_id": row.tenant_id,
                "project_id": row.project_id,
                "pool_codes": frozenset((row.engine_code,)),
                "rates": {row.engine_code: row.unit_price_cny_fen},
            }
            try:
                if row.job_id is not None:
                    accepted = record_usage(
                        funding,
                        Counter({row.engine_code: row.calls}),
                        row.action,
                        job_id=row.job_id,
                    )
                    # 空结果可能是重复入账（唯一键已存在）或 Job 已被删除；
                    # 只在 Job 确实不存在时留痕，避免把幂等命中误报成异常。
                    if accepted or db.query(Job.id).filter(Job.id == row.job_id).first() is not None:
                        row.last_error = None
                    else:
                        row.last_error = "job_not_found"
                else:
                    # 没有 job_id 就无法用唯一键去重；标记原因而不是静默丢弃，
                    # 否则这些未入账调用在运维侧完全不可见。
                    row.last_error = "missing_job_id"
                row.status = "processed"
                row.processed_at = now
                db.flush()
                if row.job_id is not None and row.last_error is None:
                    pending = db.query(PlatformUsageOutbox.id).filter(
                        PlatformUsageOutbox.job_id == row.job_id,
                        PlatformUsageOutbox.status == "pending",
                    ).first()
                    if not pending:
                        job = db.get(Job, row.job_id)
                        if job is not None and job.budget_reservation_status == "review":
                            job.budget_reservation_status = "settled"
                processed += 1
            except Exception as exc:  # noqa: BLE001 - 保留事件等待下一轮补偿
                row.attempts += 1
                row.next_attempt_at = now + timedelta(seconds=min(3600, 2 ** min(row.attempts, 10)))
                row.last_error = str(exc)[:2000]
            db.commit()
        stale_cutoff = now - timedelta(hours=2)
        stale = db.query(Job).filter(
            Job.budget_reservation_status == "review",
            Job.finished_at.isnot(None),
            Job.finished_at < stale_cutoff,
            (Job.error.is_(None) | ~Job.error.contains("platform_usage_accounting_pending")),
            ~db.query(PlatformUsageOutbox.id).filter(
                PlatformUsageOutbox.job_id == Job.id,
                PlatformUsageOutbox.status == "pending",
            ).exists(),
        ).all()
        for job in stale:
            job.budget_reservation_status = "released"
        if stale:
            db.commit()
        return processed
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
