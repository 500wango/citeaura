# CiteAura 生产上线手册

移动端 App 不在上线范围内。

## 自托管快速开始

本手册适用于在一台 Linux 主机上运行 CiteAura。要求主机已安装 Docker Engine、Docker Compose v2、Git、Python 3.12 和 `curl`；使用默认的一键部署路径时，还需要宿主机安装 Caddy。生产服务由 API、Celery Worker、Celery Beat、Redis 和 PostgreSQL 组成，管线产物写入 Docker volume `citeaura_work`，不要把 `/app/work` 改为临时目录。

### 1. 获取代码并创建环境文件

```bash
sudo mkdir -p /opt/citeaura
sudo chown "$USER" /opt/citeaura
git clone https://github.com/500wango/citeaura.git /opt/citeaura
cd /opt/citeaura
cp .env.production.example .env.production
chmod 600 .env.production
```

编辑 `.env.production`，至少填写真实值：

- `DOMAIN`：规范公网域名，例如 `app.example.com`。
- `PUBLIC_BASE_URL`：必须是 `https://` 加 `DOMAIN`，例如 `https://app.example.com`。
- `DATABASE_URL`：同机 Compose 数据库使用 `postgresql+psycopg2://<user>:<password>@postgres:5432/<db>`；外部 PostgreSQL 使用其 TLS 连接串。
- `POSTGRES_PASSWORD`：仅当 `DATABASE_URL` 的主机名为 `postgres` 时需要。
- `REDIS_PASSWORD` 与带密码的 `REDIS_URL`。
- `JWT_SECRET`：至少 32 个字符的随机值。
- `AES_KEY`：有效的 32 字节 Base64 密钥。部署后不要更换，否则已保存的 BYOK 无法解密。
- `PRODUCTION_PROXY_MODE=true`、`SESSION_COOKIE_SECURE=true`、`RATE_LIMIT_ENABLED=true`。
- `SSO_REQUIRE_DOMAIN_VERIFICATION=true`（启用企业 SSO 时保持开启）。
- `ALLOWED_HOSTS`：逗号分隔的额外 Host；通常留空即可，主域及其子域会由 `PUBLIC_BASE_URL` 自动允许。

不要把 `.env.production` 提交到 Git、同步到聊天工具或写入备份文档。部署脚本会拒绝缺失值、占位符、HTTP 公网地址和无效密钥。

### 2. DNS 与反向代理

将 `DOMAIN` 的 A/AAAA 记录指向主机。默认推荐使用宿主机 Caddy 终止 TLS：

```bash
sudo systemctl enable --now caddy
scripts/one-click-deploy.sh --env-file .env.production
```

该脚本会运行生产预检、构建镜像、执行 Alembic 迁移、启动服务，并在 `/etc/caddy/sites/citeaura.caddy` 写入站点配置。Caddy 负责 `80/443`、自动证书和 `www` 到规范域名的跳转；CiteAura API 只绑定 `127.0.0.1:${APP_PORT:-18000}`。

如果不使用 Caddy，可启用 Compose 的 `standalone-nginx` profile。先准备 `deploy/certs/fullchain.pem` 和 `deploy/certs/privkey.pem`，确保主机的 `80/443` 未被其他服务占用，然后运行：

```bash
ENV_FILE=.env.production scripts/deploy.sh
docker compose --env-file .env.production -f docker-compose.prod.yml --profile standalone-nginx up -d nginx
```

Nginx 会从 `deploy/nginx.conf` 模板将 `__DOMAIN__` 替换为环境文件中的 `DOMAIN`。此模式不会配置 Caddy；证书续期和 DNS 记录由操作者负责。

### 3. 部署后检查

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml ps
curl --fail https://$DOMAIN/api/v1/health/ready
scripts/acceptance.py --base-url https://$DOMAIN --production
```

`/api/v1/health/ready` 应返回 HTTP 200，且数据库、迁移、Redis、Worker、加密和 JWT 检查为 true。若只运行 `docker compose up` 而未执行 `scripts/deploy.sh`，必须手动执行 `docker compose ... run --rm api alembic upgrade head`；当前数据库 head 为 `0034_sso_domain_verification`。

### 4. 首次注册与 SSO 域名验证

首次打开 `https://$DOMAIN/app` 注册的用户会自动成为自己工作区的 `owner`，即该工作区的租户 Owner。只有 Enterprise 工作区可以配置 SSO。

SSO 启用前，Owner 需要完成每个登录邮箱域的 DNS TXT 验证：

1. 在工作台保存 SSO 配置，暂时将 `enabled` 设为 `false`，`allowed_domains` 填企业邮箱域名，例如 `example.com`。
2. 使用 Owner 的 Bearer token 调用：

   ```bash
   curl -X POST https://$DOMAIN/api/v1/sso/domains/verify \
     -H "Authorization: Bearer ACCESS_TOKEN"
   ```

3. 按响应中的 `txt_name` 和 `txt_value` 创建 DNS TXT 记录。记录通常是 `_citeaura.example.com`，值为 `citeaura-domain-verification=TENANT_ID:example.com`。
4. 等待 DNS 传播后再次调用验证接口，确认 `verified: true`。
5. 保存同一 SSO 配置并设置 `enabled: true`。当 `SSO_REQUIRE_DOMAIN_VERIFICATION=true` 且任一域名未验证时，API 返回 `409 sso_domains_unverified`，不会启用登录。

OIDC 回调地址固定为 `https://$DOMAIN/api/v1/sso/callback`。IdP 返回的 `email_verified` 必须为 true；当前实现不会自动把已经存在但未加入该租户的全局用户静默绑定进来，而是返回 `sso_identity_not_bound`，应通过团队邀请完成绑定。

### 5. 更新、回滚与数据备份

日常更新使用：

```bash
git pull --ff-only origin main
scripts/one-click-deploy.sh --env-file .env.production
```

更新前确认 `git status` 没有未提交的受管文件。脚本会重新构建 API/Worker/Beat、执行迁移并检查 readiness；Caddy 配置校验失败会自动恢复旧配置。不要删除 `citeaura_work`、`postgres_data` 或 `redis_data` volume。数据库备份不包含 `citeaura_work`，必须分别快照工作区 volume；本机备份还要复制到异机或对象存储。

发生故障时先保留容器日志和当前迁移版本：

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml logs --tail=200 api worker beat
docker compose --env-file .env.production -f docker-compose.prod.yml ps
```

不要通过更换 `AES_KEY`、删除迁移或直接清空 volume“修复”启动问题；这会破坏既有租户数据和加密凭证。

数据库从 Neon 迁移到同机独立 Compose PostgreSQL 的完整步骤和回滚说明见 [`docs/neon-to-compose-postgres-migration.md`](neon-to-compose-postgres-migration.md)。迁移已于 2026-08-25 完成；当前生产使用 CiteAura 自己的 `local-postgres` Compose profile，另一应用的 PostgreSQL 不在本项目内。

## 上线前配置

1. 复制 `.env.production.example` 为 `.env.production`，填写真实域名、本地 Compose PostgreSQL 的 `POSTGRES_*` 变量、`JWT_SECRET` 和 `AES_KEY`。
2. 生产 `DATABASE_URL` 使用 `postgresql+psycopg2://<POSTGRES_USER>:<POSTGRES_PASSWORD>@postgres:5432/<POSTGRES_DB>`；不要映射宿主机 `5432`，也不要复用另一应用的 PostgreSQL 容器、网络或卷。Neon 连接只作为迁移回滚材料保留。
3. 将 `PUBLIC_BASE_URL` 设置为 `https://DOMAIN`，并将 `SESSION_COOKIE_SECURE=true`。
4. 保持 `PRODUCTION_PROXY_MODE=true`、`RATE_LIMIT_ENABLED=true` 和 `RATE_LIMIT_TRUST_PROXY_HEADERS=true`。默认每个用户或来源 IP 每分钟 120 个 API 请求，注册、登录和刷新每分钟 20 个；可通过 `RATE_LIMIT_*` 调整。
5. 暂不开放支付时保持 `BILLING_ENABLED=false`，Stripe 配置可以留空。开放支付时改为 `true`，并在 Stripe Dashboard 创建订阅 Checkout Webhook；事件至少包括 `checkout.session.completed`、`checkout.session.async_payment_succeeded`、`customer.subscription.updated`、`customer.subscription.deleted`、`invoice.paid` 和 `invoice.payment_failed`，地址为 `https://DOMAIN/api/v1/billing/webhook`。
6. 宿主机 Caddy 独占 `80/443` 并自动管理证书。CiteAura 默认仅监听 `127.0.0.1:18000`，可用 `APP_PORT` 调整；生产 API 容器启用 Uvicorn `--proxy-headers`，并通过 `FORWARDED_ALLOW_IPS=127.0.0.1`（或明确的可信代理 CIDR）限制转发头来源，不要使用 `*` 或把 API 端口直接暴露到公网。
7. Worker 固定使用 Celery `prefork` 池；不要在生产覆盖为 `threads`、`gevent` 或 `eventlet`，因为引擎租户上下文会临时注入进程环境和供应商注册表。
8. 镜像和 CI 使用提交到仓库的 `requirements.lock`；依赖变更时同步更新 `requirements.txt` 与锁文件并重新跑全量测试。
9. 配置 `AUTH_SMTP_*` 全局发件账号后，CiteAura 会发送注册欢迎邮件、付款成功通知、密码重置、交付包分享和回归告警；密码重置仍由 `PASSWORD_RESET_EMAIL_ENABLED` 单独控制。自建邮件服务器使用隐式 TLS 时配置 `AUTH_SMTP_PORT=465` 与 `AUTH_SMTP_SECURITY=ssl`；使用提交端口时配置 `AUTH_SMTP_PORT=587` 与 `AUTH_SMTP_SECURITY=starttls`，两者不能混用。SMTP 未配置时，欢迎/付款通知会记录跳过，且不会阻断注册或付款 Webhook。外链联络 SMTP 仍由各租户在工作台单独配置。
10. 如果启用归档，填写 S3 或 R2 兼容对象存储配置。外链 SMTP 和 OIDC 凭证在租户工作台内配置，并由对应连接测试确认。

## 预检与部署

首次部署或日常更新使用一键脚本。脚本会完成生产预检、镜像构建、数据库迁移、API/Worker/Beat 启动，并为宿主机 Caddy 写入独立站点配置。Caddy 校验或 reload 失败时会自动恢复原配置。

```bash
scripts/one-click-deploy.sh --env-file .env.production
scripts/acceptance.py --base-url https://your-domain.example --production
```

`production_preflight.py` 不打印密钥值，会拒绝占位符、HTTP 公网地址和无效 AES Key。部署脚本带 `--migrate-legacy`，只会为旧环境文件补写非敏感的 `FORWARDED_ALLOW_IPS=127.0.0.1` 默认值；显式空值、通配符或非法代理地址仍会失败。配置了认证 SMTP 时会校验端口与加密模式：`465` 只能配 `ssl`，`ssl` 只能配 `465`；`587` 应配 `starttls`。`BILLING_ENABLED=true` 时还会拒绝测试 Stripe Key，`PASSWORD_RESET_EMAIL_ENABLED=true` 时会校验认证 SMTP。脚本可重复执行，不会启动仓库内的 Nginx，也不会改动其他 Docker Compose 项目。

数据库每日备份由宿主机 `/usr/local/sbin/citeaura-postgres-backup` 执行，cron 时刻为 03:17，保留 14 天且备份文件权限为 600。`/var/backups/citeaura/` 仍属于本机故障域，必须复制到异机或对象存储。

可将仓库内的只读检查脚本接入 cron、systemd timer 或监控探针；它会检查最近 dump 的新鲜度、`600` 权限和 custom-format 可读性，失败时返回非零状态：

```bash
BACKUP_DIR=/var/backups/citeaura/daily MAX_AGE_HOURS=26 \
  scripts/verify-postgres-backup.sh
```

## 平台管理员密码恢复

生产管理员密码必须在正在运行的 API 容器内重置，确保命令使用与线上 API 完全相同的 `.env.production` 和数据库。不要在生产宿主机直接运行本地 `reset-admin-password` 目标。

```bash
cd /opt/citeaura
make reset-admin-password-prod EMAIL=admin@citeaura.com ENV_FILE=.env.production
```

命令会要求输入并再次确认新密码；密码至少 12 位。成功后已有后台会话会全部失效，可在 `https://citeaura.com/admin/` 使用新密码登录。

测试或客服赠送套餐权益时使用生产容器命令；它只修改工作区权益，不生成 Stripe 订阅或付款记录：

```bash
make grant-plan-prod EMAIL=user@example.com PLAN=pro ENV_FILE=.env.production
```

账号拥有多个工作区时，命令会列出工作区 ID 并停止；确认目标后追加 `TENANT_ID=<id>`。

默认生成 `/etc/caddy/sites/citeaura.caddy`：

```caddy
your-domain.example {
    reverse_proxy 127.0.0.1:18000
}

www.your-domain.example {
    redir https://your-domain.example{uri} permanent
}
```

脚本会确保主 `/etc/caddy/Caddyfile` 包含 `import /etc/caddy/sites/*.caddy`，然后执行 Caddy validate 与 reload。`www` 别名由 Caddy 完成 TLS，并永久跳转到 `DOMAIN` 对应的规范域名；公开检查同时验证该跳转，避免 CDN 连接到未配置 `www` 证书的源站时返回 525。自定义 Caddy 路径时使用 `--caddyfile` 和 `--site-dir`。仅更新容器、不修改 Caddy 时可继续运行 `scripts/deploy.sh`。

## GitHub 推送自动部署

`.github/workflows/deploy-production.yml` 会在 `main` 分支收到 push 后自动连接 VPS，在 `/opt/citeaura` 执行快进更新和一键部署。也可以在 GitHub 的 Actions 页面通过 `workflow_dispatch` 手动触发。并发部署会排队，避免两个 Compose 更新同时运行。

生产 `.env.production` 始终只保存在 VPS 的 `/opt/citeaura/.env.production`，工作流不会创建、上传或打印它。VPS 上若有已跟踪文件的未提交修改，或本地 `main` 无法快进，工作流会失败而不是覆盖现场改动。

### 1. 创建专用 SSH 密钥

在可信任的管理电脑生成仅供 CiteAura 自动部署使用的 Ed25519 密钥，不要复用日常登录私钥：

```bash
ssh-keygen -t ed25519 -C github-actions-citeaura -f ./citeaura_deploy_key
```

把 `citeaura_deploy_key.pub` 的整行内容追加到部署用户的 `~/.ssh/authorized_keys`。可以在公钥前增加以下限制；这些限制保留远程命令能力，但禁用端口转发、代理转发和 PTY：

```text
restrict ssh-ed25519 AAAAC3... github-actions-citeaura
```

当前 VPS 使用 `root` 部署时，GitHub 的 `VPS_USER` 可先设为 `root`，但必须使用上述独立密钥。更严格的长期方案是创建只拥有 `/opt/citeaura` 更新权限的部署用户，并通过 `sudoers` 仅允许它免密运行 `/opt/citeaura/scripts/one-click-deploy.sh --env-file /opt/citeaura/.env.production`。不要给 GitHub 配置个人通用 SSH 私钥。

### 2. 固定 VPS 主机指纹

在 VPS 控制台查看 SSH 主机公钥指纹：

```bash
sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

在可信任的管理电脑获取主机公钥，并用 `ssh-keygen -lf` 核对指纹完全一致：

```bash
ssh-keyscan -p 22 -t ed25519 YOUR_VPS_IP > ./citeaura_known_hosts
ssh-keygen -lf ./citeaura_known_hosts
```

不要在 GitHub Actions 中临时运行 `ssh-keyscan`，否则无法确认连接的是实际 VPS。SSH 不是 22 端口时，两条命令都换成真实端口，known-hosts 内容会使用 `[host]:port` 格式。

### 3. 配置 GitHub Environment

在仓库 `Settings -> Environments` 新建 `production`，然后添加 Environment secrets：

| Secret | 内容 |
| --- | --- |
| `VPS_HOST` | VPS 公网 IP 或可解析主机名 |
| `VPS_PORT` | SSH 端口；留空时使用 `22` |
| `VPS_USER` | 部署用户；当前可填写 `root` |
| `VPS_SSH_PRIVATE_KEY` | `citeaura_deploy_key` 私钥全文 |
| `VPS_KNOWN_HOSTS` | 已核验的 `citeaura_known_hosts` 整行内容 |

确认 VPS 的 `/opt/citeaura` 已克隆本仓库、`main` 跟踪 `origin/main`，并保留可用的 `.env.production`。首次配置完成后，可在 Actions 页面手动运行一次 `Deploy production`，验证成功后再依赖 `main` push 自动发布。

## 完整业务闭环验收

为专用验收租户配置至少一个引擎 Key，然后运行真实建项、采样、验收和交付流程。密码和 Token 不通过命令行参数传递，也不会出现在结果中。

```bash
export ACCEPTANCE_EMAIL=acceptance@example.com
export ACCEPTANCE_PASSWORD='replace-with-acceptance-password'
export ACCEPTANCE_PROJECT_URL=https://acceptance-brand.example
python3 scripts/workflow_acceptance.py --base-url https://your-domain.example --json
```

重复验证同一项目时增加 `--reuse-existing`。脚本会检查分引擎采样模式、raw answer、工单、verify 历史，以及交付 zip 的 `index.html`、01–06 文档和 `assets/`。

## 付款验收

用 Stripe 测试环境应在独立 staging 配置中完成。生产配置只接受 `sk_live_` 和 `whsec_`。订阅请求只创建 Checkout 会话，租户套餐必须在签名 Webhook 到达后才变为 Pro 或 Agency；重复 Webhook 应返回 `duplicate: true` 且不重复创建订阅。

## 邮件通知验收

- 用新的测试邮箱注册一次，确认收到 `Welcome to CiteAura`；重复注册应返回冲突且不再发送。
- 在 Stripe 测试环境完成一次 Checkout，确认收到 `CiteAura payment successful`；重复投递同一个 Webhook event 不应重复发送。
- 检查 API/Worker 日志中的 `welcome email delivery failed` 或 `payment email delivery failed`，并在 SMTP 服务商后台核对投递状态。
- Stripe 官方收据和发票仍由 Stripe Dashboard 的 Customer emails 设置负责，不能用 CiteAura 应用邮件替代。

## 可选基础设施验收

- SMTP：保存凭证、创建草稿，人工核对收件人、主题和正文后发送。
- 对象存储：创建快照、检查远端对象和清单，再执行恢复演练。
- OIDC：使用允许域名登录，确认成员角色和审计事件。
