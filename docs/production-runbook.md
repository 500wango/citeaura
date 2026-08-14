# CiteAura 生产上线手册

移动端 App 不在上线范围内。

## 上线前配置

1. 复制 `.env.production.example` 为 `.env.production`，填写真实域名、Neon 的 pooled `DATABASE_URL`、`JWT_SECRET` 和 `AES_KEY`。
2. 在 Neon 创建生产项目，复制连接串并将协议改为 `postgresql+psycopg2://`，保留 `?sslmode=require`。生产 Compose 不启动本地 Postgres，迁移会直接写入 Neon。
3. 将 `PUBLIC_BASE_URL` 设置为 `https://DOMAIN`，并将 `SESSION_COOKIE_SECURE=true`。
4. 保持 `RATE_LIMIT_ENABLED=true` 和 `RATE_LIMIT_TRUST_PROXY_HEADERS=true`。默认每个用户或来源 IP 每分钟 120 个 API 请求，注册、登录和刷新每分钟 20 个；可通过 `RATE_LIMIT_*` 调整。
5. 暂不开放支付时保持 `BILLING_ENABLED=false`，Stripe 配置可以留空。开放支付时改为 `true`，并在 Stripe Dashboard 创建订阅 Checkout Webhook；事件至少包括 `checkout.session.completed`、`checkout.session.async_payment_succeeded`、`customer.subscription.updated`、`customer.subscription.deleted`、`invoice.paid` 和 `invoice.payment_failed`，地址为 `https://DOMAIN/api/v1/billing/webhook`。
6. 宿主机 Caddy 独占 `80/443` 并自动管理证书。CiteAura 默认仅监听 `127.0.0.1:18000`，可用 `APP_PORT` 调整。
7. 暂不开放密码重置邮件时保持 `PASSWORD_RESET_EMAIL_ENABLED=false`，认证 SMTP 可以留空。开放时改为 `true` 并配置 `AUTH_SMTP_*` 全局发件账号。外链联络 SMTP 仍由各租户在工作台单独配置。
8. 如果启用归档，填写 S3 或 R2 兼容对象存储配置。外链 SMTP 和 OIDC 凭证在租户工作台内配置，并由对应连接测试确认。

## 预检与部署

首次部署或日常更新使用一键脚本。脚本会完成生产预检、镜像构建、数据库迁移、API/Worker/Beat 启动，并为宿主机 Caddy 写入独立站点配置。Caddy 校验或 reload 失败时会自动恢复原配置。

```bash
scripts/one-click-deploy.sh --env-file .env.production
scripts/acceptance.py --base-url https://your-domain.example --production
```

`production_preflight.py` 不打印密钥值，会拒绝占位符、HTTP 公网地址和无效 AES Key。`BILLING_ENABLED=true` 时还会拒绝测试 Stripe Key，`PASSWORD_RESET_EMAIL_ENABLED=true` 时会校验认证 SMTP。脚本可重复执行，不会启动仓库内的 Nginx，也不会改动其他 Docker Compose 项目。

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
```

脚本会确保主 `/etc/caddy/Caddyfile` 包含 `import /etc/caddy/sites/*.caddy`，然后执行 Caddy validate 与 reload。自定义 Caddy 路径时使用 `--caddyfile` 和 `--site-dir`。仅更新容器、不修改 Caddy 时可继续运行 `scripts/deploy.sh`。

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

## 可选基础设施验收

- SMTP：保存凭证、创建草稿，人工核对收件人、主题和正文后发送。
- 对象存储：创建快照、检查远端对象和清单，再执行恢复演练。
- OIDC：使用允许域名登录，确认成员角色和审计事件。
