import asyncio
import json
import time

import pytest
from redis.exceptions import ConnectionError

from api import config
from api.adapters import engine as engine_adapter
from api.adapters import locking
from api.adapters.engine import geolib, with_tenant_context
from api.adapters.exceptions import DistributedLockError
from api.main import distributed_lock_exception_handler


def test_tenant_context_uses_namespaced_distributed_lock(project_lock_redis, tmp_path, monkeypatch):
    monkeypatch.setattr(engine_adapter, "WORK_ROOT", tmp_path / "work")
    original = geolib.project_lock

    with with_tenant_context("Tenant A", "example"):
        with geolib.project_lock("example"):
            pass

    assert geolib.project_lock is original
    name, lock = project_lock_redis.created[-1]
    assert name == "citeaura:project-lock:tenant-a:example"
    assert lock.options == {
        "timeout": config.project_lock_ttl_seconds(),
        "blocking_timeout": config.project_lock_wait_seconds(),
        "thread_local": False,
    }
    assert lock.acquired is False


def test_project_lock_blocks_same_tenant_project_but_not_other_tenant(monkeypatch):
    monkeypatch.setattr(locking, "_lock_settings", lambda: (1, 0.02, 0.01))

    with locking.project_lock("tenant-a", "example"):
        with locking.project_lock("tenant-b", "example"):
            pass
        with pytest.raises(DistributedLockError, match="project_lock_timeout"):
            with locking.project_lock("tenant-a", "example"):
                pass


def test_project_lock_renews_lease_and_reports_lost_lock(project_lock_redis, monkeypatch):
    monkeypatch.setattr(locking, "_lock_settings", lambda: (0.08, 0.02, 0.01))
    with locking.project_lock("tenant-a", "renewed"):
        time.sleep(0.035)
    assert project_lock_redis.created[-1][1].extend_count >= 2

    class LostLock:
        def acquire(self, **kwargs):
            return True

        def extend(self, *args, **kwargs):
            return False

        def release(self):
            return None

    class LostRedis:
        def lock(self, *args, **kwargs):
            return LostLock()

    monkeypatch.setattr(locking, "redis_client", lambda: LostRedis())
    critical_section_completed = False
    with pytest.raises(DistributedLockError, match="project_lock_lost"):
        with locking.project_lock("tenant-a", "lost"):
            time.sleep(0.025)
            critical_section_completed = True
    assert critical_section_completed is True


def test_project_lock_connection_failure_is_retryable(monkeypatch):
    class BrokenRedis:
        def lock(self, *args, **kwargs):
            raise ConnectionError("secret redis address")

    monkeypatch.setattr(locking, "redis_client", lambda: BrokenRedis())
    with pytest.raises(DistributedLockError, match="project_lock_unavailable"):
        with locking.project_lock("tenant-a", "example"):
            pass

    response = asyncio.run(
        distributed_lock_exception_handler(None, DistributedLockError("project_lock_unavailable"))
    )
    assert response.status_code == 503
    assert response.headers["retry-after"] == "1"
    assert json.loads(response.body) == {"error": "project_lock_unavailable"}
