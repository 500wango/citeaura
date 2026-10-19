#!/bin/sh
# 容器启动前自动完成数据库迁移：wait-for-db → 备份 → 预检 → upgrade → 校验。
#
# 设计取舍：
# - 默认 AUTO_MIGRATE=0，只在 docker-compose.prod.yml 的 api 服务里显式打开；
#   多副本部署（api 副本数 > 1）必须关掉，改由一次性 job 执行，否则会并发迁移。
# - 迁移失败时容器不会启动（fail closed），而不是带着旧 schema 提供服务。
set -eu

if [ "${AUTO_MIGRATE:-0}" = "1" ]; then
    echo "[entrypoint] AUTO_MIGRATE=1，等待数据库就绪 ..."
    attempt=0
    while [ "$attempt" -lt 60 ]; do
        if python3 - <<'PY' 2>/dev/null
import sys
from sqlalchemy import create_engine, text
from api import config

engine = create_engine(config.database_url())
with engine.connect() as conn:
    conn.execute(text("SELECT 1"))
PY
        then
            break
        fi
        attempt=$((attempt + 1))
        sleep 2
    done
    if [ "$attempt" -ge 60 ]; then
        echo "[entrypoint] 数据库 120 秒内未就绪，放弃启动" >&2
        exit 1
    fi
    # migrate_db.py 自带 pg_dump 备份、无重复订阅校验与失败回滚提示。
    # 版本已是最新时它会直接返回，不会每次都做一次全库备份。
    python3 scripts/migrate_db.py
fi

exec "$@"
