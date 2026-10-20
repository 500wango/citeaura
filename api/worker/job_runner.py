"""子进程入口：只执行白名单引擎动作，不读写数据库。"""

import ctypes
import json
import sys
from contextlib import ExitStack, contextmanager
from types import SimpleNamespace

_PROTOCOL_STDOUT = sys.stdout
sys.stdout = sys.stderr


def _die_with_parent():
    """Linux 下父进程被硬杀时一并终止，避免遗留密钥进程。"""
    if not sys.platform.startswith("linux"):
        return
    try:
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        libc.prctl(1, 9)  # PR_SET_PDEATHSIG, SIGKILL
    except Exception:  # noqa: BLE001 - 平台不支持时退化为普通子进程
        pass


def _namespace(action, params):
    from api.pipeline_catalog import ACTION_DEFAULTS, PIPELINE_ACTIONS

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
        if flag in {"--no-recrawl", "--draft", "--no-sample", "--skip-llm", "--no-llm"}:
            values[name] = value is True
        elif value in (None, "", []):
            continue
        elif flag in {"--max-pages", "--limit", "--repeat", "--draft-limit"}:
            values[name] = int(value)
        elif flag in {"--platforms", "--asset", "--question-ids"}:
            values[name] = ",".join(str(item) for item in value) if isinstance(value, list) else str(value)
    return SimpleNamespace(**values)


@contextmanager
def _normalize_project(slug):
    from api.adapters import global_scope

    global_scope.normalize_project(slug)
    yield


def _wrapper(name, slug):
    """父进程里的引擎补丁必须在同一进程生效，因此迁到子进程包裹执行。"""
    if name == "normalize_project":
        return _normalize_project(slug)
    if name == "normalize_generated_outputs":
        from api.adapters import global_scope
        return global_scope.normalize_generated_outputs(slug)
    if name == "semantic_site_signals":
        from api.adapters import site_signals
        return site_signals.semantic_site_signals(slug)
    if name == "preserve_manual_tickets":
        from api.adapters.workspace import preserve_manual_tickets
        return preserve_manual_tickets(slug)
    if name == "resilient_crawl_evidence":
        from api.adapters.workspace import resilient_crawl_evidence
        return resilient_crawl_evidence(slug)
    raise ValueError(f"unsupported engine wrapper: {name}")


def _dispatch(action, slug, kwargs, tenant=None):
    if action == "probe":
        # 诊断动作只返回环境变量是否存在，便于验证隔离，不暴露任何值。
        import os
        import time
        time.sleep(float(kwargs.get("sleep") or 0))
        names = (
            "OPENAI_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY",
            "DATABASE_URL", "CITEAURA_ISOLATED_JOBS", "CITEAURA_WORK_ROOT",
        )
        return {
            "tenant": tenant,
            "env_present": {name: bool(os.environ.get(name)) for name in names},
        }
    if action == "sample":
        import sample
        allowed = ("platforms", "repeat", "limit", "question_ids")
        return sample.run(slug, **{name: kwargs[name] for name in allowed if name in kwargs})
    if action == "verify":
        import verify
        return verify.run(slug)
    if action == "autopilot":
        import geo
        return geo.cmd_autopilot(SimpleNamespace(slug=slug, **kwargs))
    if action == "cycle":
        import geo
        return geo.cmd_cycle(SimpleNamespace(slug=slug, **kwargs))
    if action == "pipeline":
        import geo
        from api.pipeline_catalog import ACTION_METHODS
        pipeline_action = kwargs["pipeline_action"]
        getattr(geo, ACTION_METHODS[pipeline_action])(_namespace(pipeline_action, kwargs.get("params")))
        return {"status": "done", "action": pipeline_action, "project_slug": slug}
    raise ValueError(f"unsupported engine action: {action}")


def execute(payload):
    """在租户隔离与密钥上下文中执行一次动作。"""
    from api.adapters.engine import with_tenant_context
    from api.billing.metering import meter_platform_calls

    action = payload["action"]
    slug = payload["project_slug"]
    keys = payload.get("keys") or {}
    providers = payload.get("custom_providers") or []
    pool_codes = payload.get("pool_codes") or ()
    kwargs = payload.get("kwargs") or {}
    usage = {}
    with meter_platform_calls(pool_codes) as counts:
        with with_tenant_context(
            payload["tenant_directory"], slug, keys=keys, custom_providers=providers,
        ):
            with ExitStack() as stack:
                for name in payload.get("wrappers") or ():
                    stack.enter_context(_wrapper(name, slug))
                result = _dispatch(action, slug, kwargs, payload.get("tenant_directory"))
        usage = dict(counts)
    return result if isinstance(result, dict) else {"status": "done"}, usage


def main():
    _die_with_parent()
    from api.worker.job_protocol import decode_job_request, error_event, result_event

    try:
        payload = decode_job_request(sys.stdin.read())
        result, usage = execute(payload)
        _PROTOCOL_STDOUT.write(result_event(result, usage) + "\n")
        _PROTOCOL_STDOUT.flush()
        return 0
    except Exception as exc:  # noqa: BLE001 - 把失败转换回父进程协议
        _PROTOCOL_STDOUT.write(error_event(f"{type(exc).__name__}: {exc}") + "\n")
        _PROTOCOL_STDOUT.flush()
        return 1


if __name__ == "__main__":
    sys.exit(main())
