"""Worker BYOK and platform-pool funding runtime."""

import json
import os
import time
from contextlib import contextmanager

from sqlalchemy.exc import SQLAlchemyError

from api import config
from api.adapters import sampling_control
from api.adapters.engine import (
    _environment_name,
    geolib,
    load_custom_providers,
    load_tenant_keys,
    with_tenant_context,
)
from api.adapters.workspace import ensure_global_engine_scope
from api.billing.platform_pool import (
    meter_platform_calls,
    persist_usage_outbox,
    record_usage,
    resolve_funding,
)
from api.db import SessionLocal


def _task_facade():
    from api.worker import tasks as task_module

    return task_module


def _engine_keys(tenant_id):
    """读取租户 Key。数据库不可用时失败，避免把空集合注入成无密钥运行。"""
    db = _task_facade().SessionLocal()
    try:
        return load_tenant_keys(db, tenant_id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise RuntimeError("engine_keys_unavailable") from exc
    finally:
        db.close()


def _engine_funding(tenant_id, project_slug, allow_pool=True):
    """读取项目有效密钥及其中由平台池承担的引擎。"""
    db = _task_facade().SessionLocal()
    try:
        return resolve_funding(db, tenant_id, project_slug, allow_pool=allow_pool)
    except SQLAlchemyError as exc:
        db.rollback()
        raise RuntimeError("engine_funding_unavailable") from exc
    finally:
        db.close()


class SamplingPlatformUnavailable(RuntimeError):
    """显式请求的平台没有被 Worker funding 提供。"""

    def __init__(self, missing, funding):
        self.missing = tuple(sorted(set(missing)))
        self.funding = funding
        super().__init__("sampling_platform_unavailable:" + ",".join(self.missing))


def _funding_diagnostic(tenant_id, project_slug, funding, custom_providers):
    """生成不含密钥值的 Worker funding 诊断快照。"""
    keys = funding.get("keys", {}) if isinstance(funding, dict) else {}
    engine_codes = sorted(str(code) for code in keys)
    env_names = []
    for code in engine_codes:
        try:
            env_names.append(_environment_name(code))
        except ValueError:
            continue
    tenant_directory = funding.get("tenant_directory_slug") if isinstance(funding, dict) else None
    return {
        "tenant_arg": str(tenant_id),
        "tenant_id": funding.get("tenant_id") if isinstance(funding, dict) else None,
        "tenant_directory_slug": tenant_directory,
        "runtime_tenant": tenant_directory or str(tenant_id),
        "project_slug": str(project_slug),
        "source_revision": config.source_revision(),
        "database_target_fingerprint": config.database_target_fingerprint(),
        "funded_engine_codes": engine_codes,
        "pool_engine_codes": sorted(str(code) for code in (funding.get("pool_codes", ()) if isinstance(funding, dict) else ())),
        "custom_engine_codes": sorted(str(item.get("code")) for item in (custom_providers or []) if item.get("code")),
        "injected_env_names": sorted(set(env_names)),
    }


def _validate_requested_platforms(platforms, funding, project_market=None):
    """显式平台必须有 funding 且属于项目市场，否则阻断本次采样。"""
    if not platforms or not isinstance(funding, dict) or funding.get("tenant_id") is None:
        return
    if isinstance(platforms, str):
        platforms = platforms.split(",")
    requested = [str(code).strip().lower() for code in platforms if str(code).strip()]
    funded = set(funding.get("keys", {})) | set(funding.get("pool_codes", ()))
    missing = [code for code in requested if code not in funded]
    if missing:
        raise SamplingPlatformUnavailable(missing, funding)
    if project_market in ("cn", "global", "both"):
        mismatched = [
            code for code in requested
            if not sampling_control.platform_matches_market(code, project_market)
        ]
        if mismatched:
            raise sampling_control.SamplingPlatformMarketMismatch(mismatched, project_market)


def _engine_custom_providers(tenant_id):
    """读取租户自定义供应商。数据库不可用时失败，避免静默丢掉供应商。"""
    db = _task_facade().SessionLocal()
    try:
        return load_custom_providers(db, tenant_id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise RuntimeError("engine_providers_unavailable") from exc
    finally:
        db.close()


def _sync_custom_provider_scope(project_slug, providers):
    """把当前租户自定义供应商加入项目默认采样集合。"""
    config_path = geolib.project_dir(project_slug) / "geo.json"
    if not config_path.is_file():
        return
    config = geolib.load_config(project_slug)
    configured = {provider["code"] for provider in providers}
    original = list(config.get("platforms") or [])
    platforms = [code for code in original if not code.startswith("custom_") or code in configured]
    for provider in providers:
        if provider["code"] not in platforms:
            platforms.append(provider["code"])
    labels = {provider["code"]: provider["name"] for provider in providers if provider.get("name")}
    model_ids = {
        provider["code"]: provider["model_id"]
        for provider in providers
        if provider.get("code") and provider.get("model_id")
    }
    changed = (
        platforms != original
        or config.get("provider_labels") != labels
        or config.get("provider_model_ids") != model_ids
    )
    if changed:
        config["platforms"] = platforms
        if labels:
            config["provider_labels"] = labels
        else:
            config.pop("provider_labels", None)
        if model_ids:
            config["provider_model_ids"] = model_ids
        else:
            config.pop("provider_model_ids", None)
        geolib.save_config(project_slug, config)


def _sync_funded_engine_scope(project_slug, funded_codes):
    """把当前 funding 中可运行、符合项目市场的 API 引擎加入默认集合。"""
    config_path = geolib.project_dir(project_slug) / "geo.json"
    if not config_path.is_file():
        return
    config = geolib.load_config(project_slug)
    funded = {
        str(code).strip().lower()
        for code in (funded_codes or ())
        if str(code).strip()
    }
    original = list(config.get("platforms") or [])
    platforms = list(original)
    config_market = config.get("market") if config.get("market") in ("cn", "global", "both") else "global"
    builtin_codes = sampling_control.BUILTIN_CN_SAMPLE_PLATFORMS + sampling_control.BUILTIN_GLOBAL_SAMPLE_PLATFORMS
    import sample
    for code in builtin_codes:
        provider_market = (sample.PROVIDERS.get(code) or {}).get("market")
        if config_market == "cn" and provider_market == "global":
            continue
        if config_market == "global" and provider_market == "cn":
            continue
        if code in funded and code not in platforms:
            platforms.append(code)
    if platforms != original:
        config["platforms"] = platforms
        geolib.save_config(project_slug, config)


@contextmanager
def _funded_engine_context(tenant_id, project_slug, action, job_id=None, allow_pool=True):
    """注入 BYOK/平台池密钥，并在退出时持久化平台代付逻辑调用。"""
    funding = _task_facade()._engine_funding(tenant_id, project_slug, allow_pool=allow_pool)
    if funding.get("tenant_id") is None:
        raise RuntimeError("worker_tenant_not_found")
    custom_providers = _task_facade()._engine_custom_providers(tenant_id)
    runtime_tenant = funding.get("tenant_directory_slug") or str(tenant_id)
    diagnostic = _task_facade()._funding_diagnostic(tenant_id, project_slug, funding, custom_providers)
    _task_facade().logger.info(
        "Worker funding resolved tenant_arg=%s tenant_id=%s tenant_directory_slug=%s "
        "project_slug=%s source_revision=%s database_target_fingerprint=%s "
        "funded_engine_codes=%s pool_engine_codes=%s custom_engine_codes=%s injected_env_names=%s",
        diagnostic["tenant_arg"], diagnostic["tenant_id"], diagnostic["tenant_directory_slug"],
        diagnostic["project_slug"], diagnostic["source_revision"],
        diagnostic["database_target_fingerprint"], diagnostic["funded_engine_codes"],
        diagnostic["pool_engine_codes"], diagnostic["custom_engine_codes"],
        diagnostic["injected_env_names"],
    )
    context_options = {"keys": funding["keys"]}
    if custom_providers:
        context_options["custom_providers"] = custom_providers
    with _task_facade().with_tenant_context(runtime_tenant, project_slug, **context_options):
        diagnostic["runtime_env_present"] = {
            name: bool(os.environ.get(name)) for name in diagnostic["injected_env_names"]
        }
        funding["_worker_diagnostic"] = {
            "source_revision": diagnostic["source_revision"],
            "database_target_fingerprint": diagnostic["database_target_fingerprint"],
            "funded_engine_codes": diagnostic["funded_engine_codes"],
            "injected_env_names": diagnostic["injected_env_names"],
            "runtime_env_present": diagnostic["runtime_env_present"],
        }
        _task_facade().logger.info(
            "Worker funding runtime environment present source_revision=%s "
            "database_target_fingerprint=%s runtime_env_present=%s",
            diagnostic["source_revision"], diagnostic["database_target_fingerprint"],
            diagnostic["runtime_env_present"],
        )
        if job_id is not None:
            _task_facade()._append_job_event(
                _task_facade().job_log_path(tenant_id, project_slug, job_id),
                "funding resolved " + json.dumps(diagnostic, sort_keys=True, ensure_ascii=True),
            )
        _task_facade().ensure_global_engine_scope(project_slug)
        _task_facade()._sync_funded_engine_scope(
            project_slug,
            set(funding.get("keys", {})) | set(funding.get("pool_codes", ())),
        )
        _task_facade()._sync_custom_provider_scope(project_slug, custom_providers)
        with _task_facade().meter_platform_calls(funding["pool_codes"]) as counts:
            try:
                yield funding
            except BaseException:
                raise
            finally:
                accounted = False
                for attempt in range(3):
                    try:
                        _task_facade().record_usage(funding, counts, action, job_id=job_id)
                        accounted = True
                        break
                    except Exception:
                        _task_facade().logger.warning(
                            "Platform usage accounting attempt %s failed",
                            attempt + 1,
                            exc_info=True,
                            extra={"action": action, "job_id": job_id},
                        )
                        if attempt < 2:
                            time.sleep(0.2 * (attempt + 1))
                if not accounted:
                    _task_facade().persist_usage_outbox(
                        funding,
                        counts,
                        action,
                        job_id=job_id,
                        error="platform usage accounting failed after retries",
                    )
                    _task_facade().logger.error(
                        "Platform usage accounting requires reconciliation",
                        extra={"action": action, "job_id": job_id, "calls": dict(counts)},
                    )

__all__ = tuple(name for name in globals() if not name.startswith("__"))
