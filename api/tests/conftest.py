import threading

import pytest

from api.adapters import locking
from redis.exceptions import LockNotOwnedError


class MemoryLock:
    def __init__(self, guard, **options):
        self.guard = guard
        self.options = options
        self.acquired = False
        self.extend_count = 0

    def acquire(self, blocking=True, blocking_timeout=None):
        timeout = -1 if blocking_timeout is None else blocking_timeout
        self.acquired = self.guard.acquire(blocking=blocking, timeout=timeout)
        return self.acquired

    def extend(self, additional_time, replace_ttl=False):
        self.extend_count += 1
        return self.acquired

    def release(self):
        if not self.acquired:
            raise LockNotOwnedError("lock is not owned")
        self.acquired = False
        self.guard.release()


class MemoryRedis:
    def __init__(self):
        self.guards = {}
        self.created = []
        self.values = {}
        self.values_lock = threading.Lock()

    def lock(self, name, **options):
        guard = self.guards.setdefault(name, threading.Lock())
        lock = MemoryLock(guard, **options)
        self.created.append((name, lock))
        return lock

    def eval(self, script, numkeys, key, ttl):
        with self.values_lock:
            self.values[key] = self.values.get(key, 0) + 1
            return self.values[key]


@pytest.fixture(autouse=True)
def project_lock_redis(monkeypatch):
    client = MemoryRedis()
    monkeypatch.setattr(locking, "redis_client", lambda: client)
    return client
