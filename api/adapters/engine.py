"""CiteAura 与开源 GEO 引擎之间的运行时适配。"""

import os
import re
import sys
import threading
from contextlib import contextmanager
from pathlib import Path

from api import config
from api.adapters import locking
from api.adapters.exceptions import GeoEngineError
from api.adapters.network import NetworkTargetError, validate_outbound_url


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENGINE_SCRIPTS = PROJECT_ROOT / "engine" / "scripts"
WORK_ROOT = config.work_root(PROJECT_ROOT / "work")

if str(ENGINE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(ENGINE_SCRIPTS))

import geolib  # noqa: E402 - 引擎路径必须先加入 sys.path


_MISSING = object()
_CONTEXT_LOCK = threading.RLock()
ENGINE_KEY_ENV = {
    "gemini": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
    "claude": "ANTHROPIC_API_KEY",
    "grok": "XAI_API_KEY",
    "perplexity": "PERPLEXITY_API_KEY",
}
GLOBAL_LLM_PREFS = ("openai", "gemini", "claude", "grok", "perplexity")

CUSTOM_PROVIDER_CODE = re.compile(r"^custom_[a-z0-9][a-z0-9_-]{2,55}$")


def custom_provider_env(code: str) -> str:
    """返回自定义供应商专用的运行时 Key 环境变量名。"""
    code = str(code or "").strip().lower()
    if not CUSTOM_PROVIDER_CODE.fullmatch(code):
        raise ValueError("invalid custom provider code")
    return f"CITEAURA_{code.upper()}_API_KEY"


def _valid_slug(value: str, label: str) -> str:
    """校验租户/项目目录标识，拒绝路径穿越。"""
    value = str(value or "")
    if not geolib.SLUG_OK.fullmatch(value):
        raise ValueError(f"invalid {label} slug: {value!r}")
    return value


def tenant_slug(value: str) -> str:
    """把租户名称转换为引擎可接受的目录标识。"""
    return _valid_slug(geolib.slugify(str(value or "")), "tenant")


def job_log_path(tenant_id: str, project_slug: str, job_id: int) -> Path:
    """返回租户项目内的 worker 日志路径。"""
    project_slug = _valid_slug(str(project_slug or ""), "project")
    job_id = int(job_id)
    if job_id <= 0:
        raise ValueError("invalid job id")
    return WORK_ROOT / tenant_slug(tenant_id) / project_slug / ".jobs" / f"{job_id}.log"


def patch_die():
    """将引擎的 sys.exit 错误改为 GeoEngineError，并返回原函数。"""
    previous = geolib.die

    def raise_error(message, code=1):
        raise GeoEngineError(message)

    geolib.die = raise_error
    return previous


def patch_paths(tenant_slug: str, project_slug: str):
    """临时把引擎路径切到租户工作区，并返回原路径。"""
    tenant_slug = _valid_slug(tenant_slug, "tenant")
    _valid_slug(project_slug, "project")
    previous = (geolib.ROOT, geolib.WORK)
    geolib.ROOT = PROJECT_ROOT
    geolib.WORK = WORK_ROOT / tenant_slug
    return previous


def patch_project_lock(tenant_slug: str):
    """把引擎文件锁临时替换为带租户隔离的 Redis 锁。"""
    tenant_slug = _valid_slug(tenant_slug, "tenant")
    previous = geolib.project_lock

    def distributed_lock(project_slug):
        project_slug = _valid_slug(project_slug, "project")
        return locking.project_lock(tenant_slug, project_slug)

    geolib.project_lock = distributed_lock
    return previous


def _environment_name(name: str) -> str:
    """把引擎代码转换为引擎约定的 API Key 环境变量名。"""
    name = str(name)
    if name.lower() in ENGINE_KEY_ENV:
        return ENGINE_KEY_ENV[name.lower()]
    if str(name).lower().startswith("custom_"):
        return custom_provider_env(name)
    if name.isupper() or name.endswith("_API_KEY"):
        return name
    return f"{name.upper()}_API_KEY"


@contextmanager
def inject_keys(keys: dict | None):
    """临时注入 API Key 环境变量，并准确恢复原值。"""
    updates = {_environment_name(name): value for name, value in (keys or {}).items()}
    previous = {}
    for env_name in set(ENGINE_KEY_ENV.values()) | set(updates):
        previous[env_name] = os.environ.get(env_name, _MISSING)
        value = updates.get(env_name, _MISSING)
        if value is _MISSING or value is None:
            os.environ.pop(env_name, None)
        else:
            os.environ[env_name] = str(value)
    try:
        yield
    finally:
        for env_name, old_value in previous.items():
            if old_value is _MISSING:
                os.environ.pop(env_name, None)
            else:
                os.environ[env_name] = old_value


@contextmanager
def protect_network_fetches():
    """在引擎网络调用期间阻止私网目标和跨主机重定向。"""
    original_request = geolib.requests.sessions.Session.request

    def guarded_request(session, method, url, *args, **kwargs):
        try:
            validate_outbound_url(url, require_https=False)
        except NetworkTargetError as exc:
            raise GeoEngineError(str(exc)) from exc
        kwargs["allow_redirects"] = False
        return original_request(session, method, url, *args, **kwargs)

    geolib.requests.sessions.Session.request = guarded_request
    try:
        yield
    finally:
        geolib.requests.sessions.Session.request = original_request


def load_tenant_keys(db, tenant_id):
    """从数据库解密当前租户的 Key，供 worker 注入环境变量。"""
    from api.models import ApiKey, CustomProvider, Tenant
    from api.settings.crypto import decrypt_key

    try:
        tenant = db.get(Tenant, int(tenant_id))
    except (TypeError, ValueError):
        tenant = db.query(Tenant).filter(Tenant.name == str(tenant_id)).first()
    if tenant is None:
        return {}
    rows = db.query(ApiKey).filter(
        ApiKey.tenant_id == tenant.id,
        ApiKey.engine_code.in_(tuple(ENGINE_KEY_ENV)),
    ).all()
    keys = {row.engine_code: decrypt_key(row.encrypted_value) for row in rows}
    custom_rows = db.query(CustomProvider).filter(CustomProvider.tenant_id == tenant.id).all()
    keys.update({row.code: decrypt_key(row.encrypted_api_key) for row in custom_rows})
    return keys


def load_custom_providers(db, tenant_id):
    """读取当前租户的自定义供应商配置（含仅供运行时使用的 Key）。"""
    from api.models import CustomProvider, Tenant
    from api.settings.crypto import decrypt_key

    try:
        tenant = db.get(Tenant, int(tenant_id))
    except (TypeError, ValueError):
        tenant = db.query(Tenant).filter(Tenant.name == str(tenant_id)).first()
    if tenant is None:
        return []
    rows = db.query(CustomProvider).filter(CustomProvider.tenant_id == tenant.id).order_by(CustomProvider.id).all()
    return [
        {
            "code": row.code,
            "name": row.name,
            "base_url": row.base_url,
            "model_id": row.model_id,
            "market": "global",
            "api_key": decrypt_key(row.encrypted_api_key),
        }
        for row in rows
    ]


@contextmanager
def with_tenant_context(tenant_id: str, project_slug: str, keys: dict | None = None, custom_providers: list[dict] | None = None):
    """在租户隔离、Key 注入和异常转换上下文中运行引擎代码。"""
    raw_tenant = str(tenant_id or "")
    if "/" in raw_tenant or "\\" in raw_tenant or ".." in raw_tenant:
        raise ValueError(f"invalid tenant slug: {raw_tenant!r}")
    tenant_directory = tenant_slug(raw_tenant)
    project_slug = _valid_slug(project_slug, "project")
    with _CONTEXT_LOCK:
        previous_die = patch_die()
        previous_root, previous_work = patch_paths(tenant_directory, project_slug)
        previous_project_lock = patch_project_lock(tenant_directory)
        try:
            with inject_keys(keys), protect_network_fetches(), _custom_provider_context(custom_providers):
                yield
        finally:
            geolib.die = previous_die
            geolib.ROOT = previous_root
            geolib.WORK = previous_work
            geolib.project_lock = previous_project_lock


@contextmanager
def _custom_provider_context(providers):
    """临时把租户自定义 OpenAI-compatible 供应商注册到引擎采样注册表。"""
    import sample

    providers = providers or []
    previous = {}
    previous_preferences = sample.LLM_PREFS
    for provider in providers:
        code = provider["code"]
        previous[code] = sample.PROVIDERS.get(code, _MISSING)
        sample.PROVIDERS[code] = {
            "name": provider["name"],
            "market": "global",
            "base": provider["base_url"],
            "model": provider["model_id"],
            "model_env": None,
            "key_env": custom_provider_env(code),
            "search": False,
            "note": "Custom OpenAI-compatible provider",
        }
    sample.LLM_PREFS = GLOBAL_LLM_PREFS + tuple(provider["code"] for provider in providers)
    try:
        yield
    finally:
        sample.LLM_PREFS = previous_preferences
        for code, old in previous.items():
            if old is _MISSING:
                sample.PROVIDERS.pop(code, None)
            else:
                sample.PROVIDERS[code] = old
