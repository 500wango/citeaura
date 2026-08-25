# Neon 迁移到同机 Compose PostgreSQL

本文档用于将 CiteAura 生产数据库从 Neon 迁移到生产服务器上的独立 Compose PostgreSQL。

当前生产服务器已有另一套应用的 Compose PostgreSQL。本方案不复用另一套应用的容器、网络、数据卷或数据库，也不把 CiteAura PostgreSQL 映射到宿主机 `5432`。

> 当前状态：迁移已于 2026-08-25 完成。本文保留完整操作步骤，便于审计、回滚演练和灾备恢复；不得把文中的占位符直接用于生产。

实际生产结果：源 Neon PostgreSQL 18.4 已导出并恢复到 CiteAura 独立 `postgres:18-alpine`（运行时 18.6）；生产 readiness 全绿，当前数据库目标为 `postgres:5432/citeaura`。最终 dump、工作卷备份、迁移前环境文件和 Neon 原库均保留在回滚窗口内。正式切换未复用 `arcmux-pg`，也未映射宿主机 `5432`。

## 1. 迁移边界

数据库迁移对象包括所有由 Alembic 管理的表、索引、约束、序列和 `alembic_version`，重点表包括：

```text
tenants users memberships projects api_keys jobs subscriptions
usage_counters billing_events payment_transactions public_audits api_access_tokens
```

数据库 dump 不包含以下管线产物：

```text
work/<tenant-directory>/<project-slug>/
```

这些文件仍位于 Docker volume `citeaura_work`，必须单独备份。数据库中的 `Tenant.directory_slug` 必须与工作目录匹配。

迁移期间必须保持不变：`JWT_SECRET`、`AES_KEY`、Stripe/SMTP 配置、平台模型 Key、`PUBLIC_BASE_URL`、生产代理和 Cookie 安全配置。特别不能更换 `AES_KEY`，否则数据库内已加密的 BYOK Key 将无法解密。

## 2. 迁移前代码和 Compose 准备

当前生产代码需要先发布一版同时支持 Neon 和本地 Compose PostgreSQL 的部署代码，再切换数据库：

1. 在 `docker-compose.prod.yml` 增加独立 `postgres` 服务和 `postgres_data` volume；服务使用 `local-postgres` profile。
2. `scripts/deploy.sh` 根据 `DATABASE_URL` 主机名判断目标：Neon 只启动 Redis，本地 `postgres` 先启动并等待健康检查，再执行 Alembic。
3. `scripts/production_preflight.py` 不再把 `sslmode=require` 写死为 Neon 专属规则：外部 Neon 要求 TLS，Compose 内部连接允许内部连接策略。
4. `.env.production.example` 增加本地 PostgreSQL 配置示例。

目标服务的关键结构：

```yaml
services:
  postgres:
    profiles: ["local-postgres"]
    image: postgres:${POSTGRES_MAJOR:-18}-alpine
    restart: unless-stopped
    environment:
      POSTGRES_DB: ${POSTGRES_DB:-citeaura}
      POSTGRES_USER: ${POSTGRES_USER:-citeaura}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-}
    volumes:
      - postgres_data:/var/lib/postgresql
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $${POSTGRES_USER} -d $${POSTGRES_DB}"]
      interval: 5s
      timeout: 5s
      retries: 20
    networks:
      - citeaura

volumes:
  postgres_data:
```

切换到本地数据库时，部署脚本实际使用 `--profile local-postgres`。约束：不设置 `container_name`，不添加 `ports: "5432:5432"`，不加入另一应用的 external network，不使用另一应用的 PostgreSQL volume。

发布兼容代码后，先保留 Neon `DATABASE_URL` 部署一次，确认 API、Worker、Beat 和 readiness 正常，再执行数据迁移。

## 3. 盘点生产 Compose 和工作卷

在生产服务器执行：

```bash
cd /opt/citeaura
docker compose ls
docker compose --env-file .env.production -f docker-compose.prod.yml ps

API_CONTAINER="$(docker compose --env-file .env.production \
  -f docker-compose.prod.yml ps -q api)"
docker inspect "$API_CONTAINER" \
  --format '{{ index .Config.Labels "com.docker.compose.project" }}'

docker volume ls
docker network ls
docker volume ls | grep -E 'citeaura|work'
docker volume inspect <实际的_citeaura_work_卷名>
```

记录当前 Compose project 名称。后续命令继续使用该名称；改名可能创建新的空 `citeaura_work` volume。如果必须改名，将旧卷显式声明为 external：

```yaml
volumes:
  citeaura_work:
    external: true
    name: <当前实际工作卷名>
```

迁移期间禁止执行 `docker compose down -v`、`docker volume prune`、`docker system prune` 或目标不明确的 `docker volume rm`。

后续命令如果引用 `POSTGRES_USER`、`POSTGRES_PASSWORD` 或其他生产变量，先在当前受控 shell 会话加载环境文件：

```bash
set -a
. /opt/citeaura/.env.production
set +a
```

不要把 `.env.production` 内容打印到终端、日志或聊天记录。

## 4. 确认 Neon 版本并备份工作卷

在 Neon 执行：

```sql
SELECT version();
SHOW server_version_num;
SELECT pg_size_pretty(pg_database_size(current_database()));
SELECT extname FROM pg_extension ORDER BY extname;
```

目标 PostgreSQL 主版本必须与 Neon 相同或更高。使用 Neon 直连地址，不使用 pooler 地址。

备份 CiteAura 工作卷：

```bash
sudo install -d -m 700 /var/backups/citeaura

docker run --rm \
  -v <实际_citeaura_work_卷名>:/data:ro \
  -v /var/backups/citeaura:/backup \
  alpine \
  tar -czf /backup/citeaura-work-before-db-migration.tar.gz -C /data .

tar -tzf /var/backups/citeaura/citeaura-work-before-db-migration.tar.gz | head
sha256sum /var/backups/citeaura/*
```

工作卷备份必须复制到对象存储或另一台服务器；只留在生产主机上不算灾备。

## 5. 演练 dump/restore

演练恢复到临时数据库，API 继续连接 Neon。以下值均为占位符，不能写入 Git、文档或 shell 历史：

```bash
SOURCE_MAJOR=<Neon主版本>
NEON_DIRECT_HOST=<Neon直连主机>
NEON_USER=<Neon数据库用户>
NEON_DATABASE=<Neon数据库名>
mkdir -p /var/backups/citeaura/rehearsal
```

使用与源库主版本匹配的客户端容器导出 custom-format dump：

```bash
docker run --rm \
  -e PGPASSWORD="$NEON_PASSWORD" \
  -v /var/backups/citeaura/rehearsal:/backup \
  postgres:"$SOURCE_MAJOR" \
  pg_dump --host="$NEON_DIRECT_HOST" --port=5432 \
  --username="$NEON_USER" --dbname="$NEON_DATABASE" \
  --format=custom --no-owner --no-acl --blobs \
  --file=/backup/neon-rehearsal.dump

docker run --rm \
  -v /var/backups/citeaura/rehearsal:/backup \
  postgres:"$SOURCE_MAJOR" \
  pg_restore --list /backup/neon-rehearsal.dump | head -40
```

推荐使用权限为 `600` 的 `.pgpass` 或受保护的环境变量提供密码，不要把密码写在命令参数中。

启动独立 PostgreSQL：

```bash
docker compose -p <当前_CiteAura_Compose_project> --profile local-postgres \
  --env-file .env.production -f docker-compose.prod.yml up -d postgres
docker compose -p <当前_CiteAura_Compose_project> --profile local-postgres \
  --env-file .env.production -f docker-compose.prod.yml ps postgres
docker compose -p <当前_CiteAura_Compose_project> --profile local-postgres \
  --env-file .env.production -f docker-compose.prod.yml port postgres 5432
```

`port postgres 5432` 不应返回宿主机或公网端口映射。

创建临时库并恢复：

```bash
docker compose -p <当前_CiteAura_Compose_project> --profile local-postgres \
  --env-file .env.production -f docker-compose.prod.yml \
  exec -T postgres createdb -U "$POSTGRES_USER" citeaura_rehearsal

docker compose -p <当前_CiteAura_Compose_project> --profile local-postgres \
  --env-file .env.production -f docker-compose.prod.yml \
  exec -T postgres pg_restore --no-owner --no-acl --exit-on-error \
  -U "$POSTGRES_USER" -d citeaura_rehearsal \
  < /var/backups/citeaura/rehearsal/neon-rehearsal.dump
```

对临时库执行迁移：

```bash
docker compose -p <当前_CiteAura_Compose_project> --profile local-postgres \
  --env-file .env.production -f docker-compose.prod.yml run --rm \
  -e DATABASE_URL="postgresql+psycopg2://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/citeaura_rehearsal" \
  api alembic upgrade head

docker compose -p <当前_CiteAura_Compose_project> --profile local-postgres \
  --env-file .env.production -f docker-compose.prod.yml \
  exec -T postgres psql -U "$POSTGRES_USER" -d citeaura_rehearsal \
  -Atc 'SELECT version_num FROM alembic_version;'
```

必须返回 `0031_job_history_index`。对 Neon 和临时库分别统计 `tenants`、`users`、`projects`、`api_keys`、`jobs`、`subscriptions`、`billing_events`、`payment_transactions`、`public_audits`、`api_access_tokens`，确认行数和关键状态一致。

演练完成后只删除临时数据库：

```bash
docker compose -p <当前_CiteAura_Compose_project> --profile local-postgres \
  --env-file .env.production -f docker-compose.prod.yml \
  exec -T postgres dropdb -U "$POSTGRES_USER" citeaura_rehearsal
```

不要删除 `postgres_data` 或 `citeaura_work` volume。

## 6. 正式停写和最终导出

正式切换前确认：兼容代码已发布、源版本已确认、工作卷已备份、演练成功、原 `JWT_SECRET`/`AES_KEY` 已保留、回滚配置已准备、停机窗口已通知。

先停止 Beat：

```bash
docker compose -p <当前_CiteAura_Compose_project> \
  --env-file .env.production -f docker-compose.prod.yml stop beat
```

在 Neon 检查任务：

```sql
SELECT status, count(*) FROM jobs GROUP BY status ORDER BY status;
SELECT id, project_id, action, status, started_at
FROM jobs WHERE status IN ('queued', 'running') ORDER BY id;
```

等待运行中的任务完成后停止 API 和 Worker：

```bash
docker compose -p <当前_CiteAura_Compose_project> \
  --env-file .env.production -f docker-compose.prod.yml stop worker api
```

执行最终 `pg_dump`，文件名使用 UTC 时间戳：

```bash
FINAL_DUMP="/var/backups/citeaura/neon-final-$(date -u +%Y%m%dT%H%M%SZ).dump"
```

最终 dump 完成后计算 `sha256sum`，并用匹配版本的 `pg_restore --list` 检查归档。此刻开始禁止旧 Neon 接受生产写入。

## 7. 恢复正式数据库并切换

在生产服务器 `.env.production` 设置：

```env
POSTGRES_MAJOR=<Neon主版本>
POSTGRES_DB=citeaura
POSTGRES_USER=citeaura
POSTGRES_PASSWORD=<新生成的数据库密码>
DATABASE_URL=postgresql+psycopg2://citeaura:<密码>@postgres:5432/citeaura
```

保持原生产 `JWT_SECRET`、`AES_KEY` 和其他服务配置不变。启动数据库和 Redis：

```bash
docker compose -p <当前_CiteAura_Compose_project> --profile local-postgres \
  --env-file .env.production -f docker-compose.prod.yml up -d postgres redis
```

恢复最终 dump。目标库必须是可丢弃的新库；不要对未知数据使用 `--clean`：

```bash
docker compose -p <当前_CiteAura_Compose_project> --profile local-postgres \
  --env-file .env.production -f docker-compose.prod.yml \
  exec -T postgres pg_restore --no-owner --no-acl --exit-on-error \
  -U "$POSTGRES_USER" -d "$POSTGRES_DB" < "$FINAL_DUMP"
```

执行并检查 Alembic：

```bash
docker compose -p <当前_CiteAura_Compose_project> --profile local-postgres \
  --env-file .env.production -f docker-compose.prod.yml \
  run --rm api alembic upgrade head

docker compose -p <当前_CiteAura_Compose_project> --profile local-postgres \
  --env-file .env.production -f docker-compose.prod.yml \
  exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -Atc 'SELECT version_num FROM alembic_version;'
```

结果必须为 `0031_job_history_index`。

## 8. 启动和验收

```bash
docker compose -p <当前_CiteAura_Compose_project> \
  --env-file .env.production -f docker-compose.prod.yml config --quiet

ENV_FILE=.env.production ./scripts/deploy.sh

docker compose -p <当前_CiteAura_Compose_project> \
  --env-file .env.production -f docker-compose.prod.yml ps

curl -fsS https://citeaura.com/api/v1/health/ready
```

Readiness 必须显示 `database`、`migrations`、`redis`、`worker` 成功。

业务验收顺序：

1. 使用现有账号登录。
2. 确认租户和项目列表完整。
3. 打开 Job 历史、报告和交付包。
4. 确认已有 BYOK Key 数量，并对一个已有 Key 执行连接测试。
5. 创建测试 Job，确认 Worker 能领取并更新状态。
6. 确认 Beat 能创建到期调度任务。
7. 检查 API、Worker、Beat 没有数据库连接错误。
8. 确认另一应用的 PostgreSQL、容器、网络和数据未受影响。
9. 确认 CiteAura PostgreSQL 没有宿主机端口映射。

## 9. 迁移后备份和回滚

迁移后每日执行 custom-format dump，并复制到对象存储或另一台主机：

```bash
mkdir -p /var/backups/citeaura/daily

docker compose -p <当前_CiteAura_Compose_project> --profile local-postgres \
  --env-file .env.production -f docker-compose.prod.yml \
  exec -T postgres pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  --format=custom --no-owner --no-acl \
  > "/var/backups/citeaura/daily/citeaura-$(date -u +%Y%m%dT%H%M%SZ).dump"
```

Neon 原库和最终 dump 至少保留 24 至 72 小时。

如果目标库尚未重新开放写入，回滚步骤是：停止 API/Worker/Beat，将 `DATABASE_URL` 恢复为 Neon，保留本地 PostgreSQL volume，重新部署并检查 readiness。如果目标库已经产生新写入，不能直接切回 Neon，必须先导出并处理新增数据。

## 10. 最终执行顺序

```text
发布 Neon/Compose 双兼容代码
→ 盘点 Compose project 和 volume
→ 查询 Neon 版本和大小
→ 备份 citeaura_work
→ 演练 pg_dump/pg_restore 和 Alembic 0031
→ 停止 Beat，等待 Worker 清空
→ 停止 API/Worker
→ 执行 Neon 最终 dump
→ 启动独立 Compose postgres
→ 恢复最终 dump
→ 执行 Alembic upgrade head
→ 切换 DATABASE_URL
→ 启动 API/Worker/Beat
→ readiness 和业务验收
→ 配置异机/对象存储备份
→ 保留 Neon 回滚窗口
```

## 11. 本次执行记录

- 代码兼容提交：`076c3cd`；PostgreSQL 18 卷布局修复：`b660c5f`；两次生产 Actions 均成功。
- 工作卷备份：`/var/backups/citeaura/citeaura-work-before-db-migration.tar.gz`，权限 600。
- 最终数据库归档：`/var/backups/citeaura/neon-final-20260825T004850Z.dump`；目标恢复后 `0031_job_history_index`、关键表行数、Job 状态和 AES 加密 Key 解密均通过。
- 迁移前环境文件备份：`/var/backups/citeaura/env-production-before-db-migration-20260825T004937Z`，权限 600。
- 迁移后每日备份：`/usr/local/sbin/citeaura-postgres-backup`，由 `/etc/cron.d/citeaura-postgres-backup` 每日 03:17 执行，保留 14 天；对象存储/异机复制仍需配置。
- 验收：`https://citeaura.com/`、`/app/` 返回 200，未认证 API 返回 401，readiness 的 database/migrations/redis/worker/encryption/jwt 等检查全部为 `true`；`arcmux-pg` 保持健康。
