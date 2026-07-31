"""租户项目级 Redis 分布式锁。"""

import threading
from contextlib import contextmanager
from functools import lru_cache

from redis import Redis
from redis.exceptions import LockError, RedisError

from api import config
from api.adapters.exceptions import DistributedLockError


LOCK_PREFIX = "disvorai:project-lock"


@lru_cache(maxsize=8)
def _client_for_url(url):
    return Redis.from_url(url)


def redis_client():
    return _client_for_url(config.redis_url())


def lock_key(tenant_slug, project_slug):
    return f"{LOCK_PREFIX}:{tenant_slug}:{project_slug}"


def _lock_settings():
    ttl = config.project_lock_ttl_seconds()
    wait = config.project_lock_wait_seconds()
    renew_interval = max(0.25, min(ttl / 3, ttl - 0.25))
    return ttl, wait, renew_interval


@contextmanager
def project_lock(tenant_slug, project_slug):
    """获取带自动续期的 Redis 锁；失败时不降级到单机文件锁。"""
    ttl, wait, renew_interval = _lock_settings()
    try:
        lock = redis_client().lock(
            lock_key(tenant_slug, project_slug),
            timeout=ttl,
            blocking_timeout=wait,
            thread_local=False,
        )
        acquired = lock.acquire(blocking=True, blocking_timeout=wait)
    except (RedisError, ValueError) as exc:
        raise DistributedLockError("project_lock_unavailable") from exc
    if not acquired:
        raise DistributedLockError("project_lock_timeout")

    stop = threading.Event()
    renewal_errors = []

    def renew():
        while not stop.wait(renew_interval):
            try:
                if not lock.extend(ttl, replace_ttl=True):
                    renewal_errors.append(RuntimeError("lock extension rejected"))
                    return
            except (RedisError, LockError) as exc:
                renewal_errors.append(exc)
                return

    renewer = threading.Thread(
        target=renew,
        name=f"project-lock-renew:{tenant_slug}:{project_slug}",
        daemon=True,
    )
    renewer.start()
    body_failed = False
    try:
        yield
    except BaseException:
        body_failed = True
        raise
    finally:
        stop.set()
        renewer.join(timeout=max(1, renew_interval + 0.25))
        release_error = None
        try:
            lock.release()
        except (RedisError, LockError) as exc:
            release_error = exc
        if not body_failed:
            if renewal_errors:
                raise DistributedLockError("project_lock_lost") from renewal_errors[0]
            if release_error is not None:
                raise DistributedLockError("project_lock_lost") from release_error
