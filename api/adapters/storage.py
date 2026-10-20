"""租户工作区磁盘配额。"""

import os

from api import config
from api.adapters.engine import WORK_ROOT, tenant_slug


class StorageQuotaExceeded(ValueError):
    code = "tenant_storage_quota_exceeded"


def tenant_usage_bytes(tenant_id):
    """统计租户目录占用；不跟随符号链接。"""
    root = WORK_ROOT / tenant_slug(tenant_id)
    if not root.is_dir():
        return 0
    total = 0
    for directory, _subdirs, files in os.walk(root, followlinks=False):
        for name in files:
            path = os.path.join(directory, name)
            try:
                if os.path.islink(path):
                    continue
                total += os.path.getsize(path)
            except OSError:
                continue
    return total


def tenant_storage_status(tenant_id):
    limit_mb = config.tenant_storage_quota_mb()
    used = tenant_usage_bytes(tenant_id)
    limit = limit_mb * 1024 * 1024
    return {
        "used_bytes": used,
        "limit_bytes": limit,
        "used_mb": round(used / (1024 * 1024), 2),
        "limit_mb": limit_mb,
        "exceeded": used >= limit,
    }


def ensure_capacity(tenant_id, incoming_bytes=0):
    """超出配额时拒绝新的建项/采样；incoming_bytes 为预计新增量。"""
    status = tenant_storage_status(tenant_id)
    if status["used_bytes"] + max(0, int(incoming_bytes)) >= status["limit_bytes"]:
        raise StorageQuotaExceeded(StorageQuotaExceeded.code)
