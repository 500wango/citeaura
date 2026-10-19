"""一键执行迁移：备份 → 预检 → 升级 → 校验 → 出报告。

设计目标：不需要人工判断任何一步。

  python3 scripts/migrate_db.py            # 备份 + 迁移 + 校验
  python3 scripts/migrate_db.py --dry-run  # 只做预检和报告，不改库
  python3 scripts/migrate_db.py --allow-no-backup   # 显式放弃 pg_dump 备份

失败的迁移在 PostgreSQL 上是整事务回滚的，所以脚本失败时库会留在原版本；
如果连备份也没做，脚本会拒绝执行（除非显式 --allow-no-backup）。
"""

import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, inspect, text  # noqa: E402

from api import config  # noqa: E402

TARGET_REVISION = "0039_public_audit_consumed"
CURRENT_STATUSES = ("active", "trialing", "past_due")


def _engine():
    url = config.database_url()
    if url.startswith("sqlite"):
        raise SystemExit(
            "DATABASE_URL 指向 sqlite；迁移脚本只用于真实 PostgreSQL（测试环境请直接用 pytest）。"
        )
    return create_engine(url, future=True)


def current_revision(engine):
    with engine.connect() as conn:
        try:
            return conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        except Exception:  # noqa: BLE001 - 未初始化的库没有这张表
            return None


def preflight(engine):
    """跑迁移前先看清它会影响什么。只读。"""
    report = {"revision": current_revision(engine), "demote_candidates": [], "duplicate_notification": []}
    with engine.connect() as conn:
        try:
            current_rows = [
                dict(row._mapping) for row in conn.execute(text(
                    f"""
                    SELECT tenant_id, id, plan, status, started_at, provider_subscription_id
                    FROM subscriptions
                    WHERE status IN {CURRENT_STATUSES}
                    ORDER BY tenant_id, started_at DESC NULLS LAST, id DESC
                    """
                ))
            ]
        except Exception:  # noqa: BLE001 - 全新库还没有 subscriptions 表
            current_rows = []
        # 顺序与迁移里的 ROW_NUMBER() 完全一致：同一租户只留第一条，其余都会被降级。
        seen = {}
        for row in current_rows:
            tenant = row["tenant_id"]
            seen[tenant] = seen.get(tenant, 0) + 1
            if seen[tenant] > 1:
                report["demote_candidates"].append(row)
        try:
            report["duplicate_notification"] = [
                dict(row._mapping) for row in conn.execute(text(
                    """
                    SELECT notification_key, count(*) AS rows
                    FROM billing_events
                    WHERE notification_key IS NOT NULL
                    GROUP BY notification_key HAVING count(*) > 1
                    """
                ))
            ]
        except Exception:  # noqa: BLE001 - 旧库可能没有这张表
            report["duplicate_notification"] = []
    return report


def backup(engine):
    """用 pg_dump 做整库备份；返回备份文件路径（不可用时返回 None）。"""
    binary = shutil.which("pg_dump")
    if binary is None:
        return None
    directory = Path(os.getenv("CITEAURA_BACKUP_DIR", "backups"))
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = directory / f"pre-migrate-{stamp}.dump"
    parsed = engine.url
    env = {**os.environ, "PGPASSWORD": parsed.password or ""} if parsed.password else dict(os.environ)
    command = [
        binary, "-Fc",
        "-h", str(parsed.host or "127.0.0.1"),
        "-p", str(parsed.port or 5432),
        "-U", str(parsed.username or ""),
        "-d", str(parsed.database or ""),
        "-f", str(target),
    ]
    completed = subprocess.run(command, env=env, capture_output=True, text=True)
    if completed.returncode != 0:
        print(completed.stderr.strip(), file=sys.stderr)
        return None
    return target


def upgrade():
    from alembic import command
    from alembic.config import Config

    root = Path(__file__).resolve().parents[1]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "api" / "migrations"))
    command.upgrade(cfg, "head")


def verify(engine):
    """迁移后校验：唯一索引、新列、新表、降级留档。"""
    problems = []
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    for table in ("sso_identities", "subscription_demotions"):
        if table not in tables:
            problems.append(f"缺少表 {table}")
    columns = {
        "jobs": {"heartbeat_at"},
        "api_keys": {"key_suffix"},
        "api_access_tokens": {"expires_at"},
        "public_audits": {"consumed_at", "tenant_id"},
    }
    for table, expected in columns.items():
        present = {item["name"] for item in inspector.get_columns(table)}
        missing = expected - present
        if missing:
            problems.append(f"{table} 缺少列 {sorted(missing)}")
    with engine.connect() as conn:
        duplicates = conn.execute(text(
            f"""
            SELECT tenant_id FROM subscriptions
            WHERE status IN {CURRENT_STATUSES}
            GROUP BY tenant_id HAVING count(*) > 1
            """
        )).fetchall()
        if duplicates:
            problems.append(f"仍有 {len(duplicates)} 个租户存在多条当前订阅")
        demoted = conn.execute(text("SELECT count(*) FROM subscription_demotions")).scalar() or 0
        revision = current_revision(engine)
    if revision != TARGET_REVISION:
        problems.append(f"alembic 版本是 {revision}，期望 {TARGET_REVISION}")
    return problems, demoted, revision


def main():
    parser = argparse.ArgumentParser(description="CiteAura 一键迁移（含备份与校验）")
    parser.add_argument("--dry-run", action="store_true", help="只做预检，不改库")
    parser.add_argument("--allow-no-backup", action="store_true", help="pg_dump 不可用时仍然继续")
    args = parser.parse_args()

    engine = _engine()
    report = preflight(engine)
    print(f"当前版本: {report['revision']}  ->  目标: {TARGET_REVISION}")
    if report["revision"] == TARGET_REVISION:
        print("已经是最新版本，无需迁移。")
        return 0
    if report["demote_candidates"]:
        print(f"\n以下 {len(report['demote_candidates'])} 条重复当前订阅会被降级为 incomplete")
        print("（已写入 subscription_demotions 留档，可据此恢复；这些租户会失去套餐权限）：")
        for row in report["demote_candidates"]:
            print(f"  tenant={row['tenant_id']} subscription={row['id']} "
                  f"plan={row['plan']} status={row['status']} started={row['started_at']}")
    if report["duplicate_notification"]:
        print(f"\n有 {len(report['duplicate_notification'])} 个重复 notification_key 会被置空"
              "（只影响重复的付款成功邮件）。")
    if args.dry_run:
        print("\n--dry-run：未做任何修改。")
        return 0

    dump = backup(engine)
    if dump is None:
        if not args.allow_no_backup:
            print("\npg_dump 不可用，已中止。安装 postgresql-client 后重试，"
                  "或显式传 --allow-no-backup。", file=sys.stderr)
            return 2
        print("\n警告：没有备份就继续（--allow-no-backup）。", file=sys.stderr)
    else:
        print(f"\n已备份到 {dump}")

    print("\n开始迁移 ...")
    upgrade()

    problems, demoted, revision = verify(engine)
    print(f"\n迁移完成: {revision}，本次降级订阅 {demoted} 条。")
    if problems:
        print("校验未通过：", file=sys.stderr)
        for item in problems:
            print(f"  - {item}", file=sys.stderr)
        if dump is not None:
            print(f"\n回滚参考：pg_restore -c -d <db> {dump}", file=sys.stderr)
        return 1
    print("校验全部通过：唯一索引、新列、新表就位，无重复当前订阅。")
    if demoted:
        print("被降级的订阅明细：SELECT * FROM subscription_demotions;")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
