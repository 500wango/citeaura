"""线程池上下文传播：网络守卫与租户路径必须进入工作线程。"""

from concurrent.futures import ThreadPoolExecutor as _ThreadPoolExecutor
from contextvars import copy_context


class ThreadPoolExecutor(_ThreadPoolExecutor):
    """把提交时的 ContextVar 复制到每个工作线程。"""

    def submit(self, fn, /, *args, **kwargs):
        return super().submit(copy_context().run, fn, *args, **kwargs)
