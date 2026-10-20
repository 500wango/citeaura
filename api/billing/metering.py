"""平台池调用计量：只依赖 ContextVar，不导入数据库。

引擎子进程会导入本模块统计平台池调用；子进程环境刻意剥离
`DATABASE_URL`，因此这里不能触碰 `api.db` 或 `api.models`。
"""

import threading
from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar

_METER_CONTEXT = ContextVar("citeaura_platform_meter", default=None)
_METER_HOOK_LOCK = threading.Lock()


def _ensure_meter_hook():
    """安装一次稳定的计量入口；每个任务的计数保存在 ContextVar 中。"""
    import sample

    with _METER_HOOK_LOCK:
        if getattr(sample.ask, "_citeaura_meter_hook", False):
            return
        original = sample.ask

        def metered(platform, *args, **kwargs):
            meter = _METER_CONTEXT.get()
            if meter is not None and platform in meter["codes"]:
                with meter["lock"]:
                    meter["counts"][platform] += 1
            return original(platform, *args, **kwargs)

        metered._citeaura_meter_hook = True
        sample.ask = metered


@contextmanager
def meter_platform_calls(engine_codes):
    """统计通过平台池发出的逻辑引擎调用，覆盖采样及同管线 LLM 调用。"""
    codes = frozenset(engine_codes)
    counts = Counter()
    if not codes:
        yield counts
        return
    _ensure_meter_hook()
    token = _METER_CONTEXT.set({"codes": codes, "counts": counts, "lock": threading.Lock()})
    try:
        yield counts
    finally:
        _METER_CONTEXT.reset(token)
