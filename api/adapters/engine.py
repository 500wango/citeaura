"""CiteAura 与开源 GEO 引擎之间的运行时适配。"""

import os
import re
import sys
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from urllib.parse import urljoin, urlparse

from requests.adapters import HTTPAdapter
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool

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
_NETWORK_GUARD_ACTIVE = ContextVar("citeaura_network_guard_active", default=False)
ENGINE_KEY_ENV = {
    "gemini": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
    "claude": "ANTHROPIC_API_KEY",
    "grok": "XAI_API_KEY",
    "perplexity": "PERPLEXITY_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}
GLOBAL_LLM_PREFS = ("openai", "gemini", "claude", "grok", "perplexity", "deepseek")
NETWORK_REDIRECT_STATUSES = frozenset((301, 302, 303, 307, 308))
NETWORK_RETRY_STATUSES = frozenset((429, 500, 502, 503, 504))
NETWORK_MAX_REDIRECTS = 5
NETWORK_MAX_ATTEMPTS = 2
ENGINE_MAX_REPEAT = geolib.MAX_SAMPLE_REPEAT

CUSTOM_PROVIDER_CODE = re.compile(r"^custom_[a-z0-9][a-z0-9_-]{2,55}$")


class _PinnedAddressAdapter(HTTPAdapter):
    """让一次引擎请求复用已校验的 DNS 地址，并保留 HTTPS SNI。"""

    def __init__(self, hostname, address, port, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.hostname = hostname
        self.address = str(address)
        self.port = int(port)

    def get_connection(self, url, proxies=None):
        if proxies:
            raise GeoEngineError("network_proxy_not_allowed")
        parsed = urlparse(url)
        if parsed.scheme == "https":
            return HTTPSConnectionPool(
                self.address,
                self.port,
                maxsize=self._pool_maxsize,
                block=self._pool_block,
                retries=self.max_retries,
                assert_hostname=self.hostname,
                server_hostname=self.hostname,
            )
        return HTTPConnectionPool(
            self.address,
            self.port,
            maxsize=self._pool_maxsize,
            block=self._pool_block,
            retries=self.max_retries,
        )

    def send(self, request, **kwargs):
        host = self.hostname
        if (self.port, request.url.lower().startswith("https://")) not in ((443, True), (80, False)):
            host = f"{host}:{self.port}"
        request.headers.setdefault("Host", host)
        return super().send(request, **kwargs)


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
    raw = getattr(value, "directory_slug", None) or getattr(value, "name", None) or value
    return _valid_slug(geolib.slugify(str(raw or "")), "tenant")


def job_log_path(tenant_id: str, project_slug: str, job_id: int) -> Path:
    """返回租户项目内的 worker 日志路径。"""
    project_slug = _valid_slug(str(project_slug or ""), "project")
    job_id = int(job_id)
    if job_id <= 0:
        raise ValueError("invalid job id")
    return WORK_ROOT / tenant_slug(tenant_id) / project_slug / ".jobs" / f"{job_id}.log"


def tenant_project_dir(tenant_id: str, project_slug: str) -> Path:
    """返回租户项目绝对路径；只读 API 可直接使用，避免切换引擎全局路径。"""
    return WORK_ROOT / tenant_slug(tenant_id) / _valid_slug(str(project_slug or ""), "project")


@contextmanager
def with_tenant_read_context(tenant_id: str, project_slug: str):
    """为文件型 API 读取设置并发安全的租户路径，不修改引擎全局状态。"""
    tenant_directory = tenant_slug(tenant_id)
    _valid_slug(str(project_slug or ""), "project")
    def raise_error(message, code=1):
        raise GeoEngineError(message)

    def distributed_lock(slug):
        return locking.project_lock(tenant_directory, _valid_slug(slug, "project"))

    with geolib.scoped_paths(PROJECT_ROOT, WORK_ROOT / tenant_directory), geolib.scoped_runtime(
        die_handler=raise_error,
        project_lock_factory=distributed_lock,
    ):
        yield


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
    """校验每一跳网络目标，固定已解析地址并安全跟随同站跳转。"""
    original_request = geolib.requests.sessions.Session.request

    def same_site(source, target):
        source_host = (urlparse(source).hostname or "").lower().removeprefix("www.")
        target_host = (urlparse(target).hostname or "").lower().removeprefix("www.")
        return bool(source_host and target_host) and (
            source_host == target_host
            or source_host.endswith("." + target_host)
            or target_host.endswith("." + source_host)
        )

    def request_once(session, method, url, args, kwargs, addresses):
        retryable = str(method).upper() in ("GET", "HEAD")
        parsed = urlparse(url)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        adapter = _PinnedAddressAdapter(parsed.hostname, addresses[0], port)
        previous_adapters = session.adapters.copy()
        previous_trust_env = session.trust_env
        session.trust_env = False
        session.mount(f"{parsed.scheme}://", adapter)
        try:
            for attempt in range(NETWORK_MAX_ATTEMPTS):
                try:
                    response = original_request(
                        session, method, url, *args, **kwargs, allow_redirects=False,
                    )
                except geolib.requests.RequestException:
                    if not retryable or attempt + 1 >= NETWORK_MAX_ATTEMPTS:
                        raise
                    time.sleep(0.35)
                    continue
                if (
                    retryable
                    and response.status_code in NETWORK_RETRY_STATUSES
                    and attempt + 1 < NETWORK_MAX_ATTEMPTS
                ):
                    response.close()
                    time.sleep(0.35)
                    continue
                return response
            raise GeoEngineError("network_retry_exhausted")
        finally:
            session.adapters = previous_adapters
            session.trust_env = previous_trust_env

    def guarded_request(session, method, url, *args, **kwargs):
        if not _NETWORK_GUARD_ACTIVE.get():
            return original_request(session, method, url, *args, **kwargs)
        follow_redirects = bool(kwargs.pop("allow_redirects", True))
        current_url = str(url)
        original_url = current_url
        history = []
        for redirect_count in range(NETWORK_MAX_REDIRECTS + 1):
            try:
                _validated, addresses = validate_outbound_url(
                    current_url,
                    require_https=False,
                    return_addresses=True,
                )
            except NetworkTargetError as exc:
                raise GeoEngineError(str(exc)) from exc
            response = request_once(session, method, current_url, args, kwargs, addresses)
            location = response.headers.get("Location") if hasattr(response, "headers") else None
            if (
                not follow_redirects
                or str(method).upper() not in ("GET", "HEAD")
                or response.status_code not in NETWORK_REDIRECT_STATUSES
                or not location
            ):
                if hasattr(response, "history"):
                    response.history = history
                return response
            redirected = urljoin(str(getattr(response, "url", None) or current_url), location)
            if not same_site(original_url, redirected):
                response.close()
                raise GeoEngineError("network_cross_site_redirect")
            try:
                validate_outbound_url(redirected, require_https=False)
            except NetworkTargetError as exc:
                response.close()
                raise GeoEngineError(str(exc)) from exc
            if redirect_count >= NETWORK_MAX_REDIRECTS:
                response.close()
                raise GeoEngineError("network_redirect_limit")
            history.append(response)
            current_url = redirected
        raise GeoEngineError("network_redirect_limit")

    geolib.requests.sessions.Session.request = guarded_request
    token = _NETWORK_GUARD_ACTIVE.set(True)
    try:
        yield
    finally:
        _NETWORK_GUARD_ACTIVE.reset(token)
        geolib.requests.sessions.Session.request = original_request


def load_tenant_keys(db, tenant_id):
    """从数据库解密当前租户的 Key，供 worker 注入环境变量。"""
    from sqlalchemy import or_

    from api.models import ApiKey, CustomProvider, Tenant
    from api.settings.crypto import decrypt_key

    try:
        tenant = db.get(Tenant, int(tenant_id))
    except (TypeError, ValueError):
        tenant = db.query(Tenant).filter(or_(
            Tenant.name == str(tenant_id),
            Tenant.directory_slug == str(tenant_id),
        )).first()
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
    from sqlalchemy import or_

    from api.models import CustomProvider, Tenant
    from api.settings.crypto import decrypt_key

    try:
        tenant = db.get(Tenant, int(tenant_id))
    except (TypeError, ValueError):
        tenant = db.query(Tenant).filter(or_(
            Tenant.name == str(tenant_id),
            Tenant.directory_slug == str(tenant_id),
        )).first()
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
    """在租户隔离、Key 注入和异常转换上下文中运行引擎代码。

    路径与 die/lock 走 ContextVar，文件读写不再占用进程锁。
    只有注入密钥、改采样注册表或打网络补丁时才串行化进程全局状态。
    """
    raw_tenant = getattr(tenant_id, "directory_slug", None) or getattr(tenant_id, "name", None) or str(tenant_id or "")
    raw_tenant = str(raw_tenant)
    if "/" in raw_tenant or "\\" in raw_tenant or ".." in raw_tenant:
        raise ValueError(f"invalid tenant slug: {raw_tenant!r}")
    tenant_directory = tenant_slug(raw_tenant)
    project_slug = _valid_slug(project_slug, "project")

    def raise_error(message, code=1):
        raise GeoEngineError(message)

    def distributed_lock(slug):
        return locking.project_lock(tenant_directory, _valid_slug(slug, "project"))

    needs_process_state = keys is not None or custom_providers is not None
    with geolib.scoped_paths(PROJECT_ROOT, WORK_ROOT / tenant_directory), geolib.scoped_runtime(
        die_handler=raise_error,
        project_lock_factory=distributed_lock,
    ):
        if not needs_process_state:
            yield
            return
        with _CONTEXT_LOCK:
            with inject_keys(keys), protect_network_fetches(), _custom_provider_context(custom_providers):
                yield


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
