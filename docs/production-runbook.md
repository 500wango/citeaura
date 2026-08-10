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
8. 如果启用归档，填写 S3 或 R2 兼容对象存储配置。Semrush、外链 SMTP、OIDC 和 Search Console 凭证在租户工作台内配置，并由对应连接测试确认。

## 预检与部署

首次部署或日常更新使用一键脚本。脚本会完成生产预检、镜像构建、数据库迁移、API/Worker/Beat 启动，并为宿主机 Caddy 写入独立站点配置。Caddy 校验或 reload 失败时会自动恢复原配置。

```bash
scripts/one-click-deploy.sh --env-file .env.production
scripts/acceptance.py --base-url https://your-domain.example --production
```

`production_preflight.py` 不打印密钥值，会拒绝占位符、HTTP 公网地址和无效 AES Key。`BILLING_ENABLED=true` 时还会拒绝测试 Stripe Key，`PASSWORD_RESET_EMAIL_ENABLED=true` 时会校验认证 SMTP。脚本可重复执行，不会启动仓库内的 Nginx，也不会改动其他 Docker Compose 项目。

默认生成 `/etc/caddy/sites/citeaura.caddy`：

```caddy
your-domain.example {
    reverse_proxy 127.0.0.1:18000
}
```

脚本会确保主 `/etc/caddy/Caddyfile` 包含 `import /etc/caddy/sites/*.caddy`，然后执行 Caddy validate 与 reload。自定义 Caddy 路径时使用 `--caddyfile` 和 `--site-dir`。仅更新容器、不修改 Caddy 时可继续运行 `scripts/deploy.sh`。

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

## 外部集成验收

- Search Console：完成 OAuth、绑定项目 property，并确认最新快照出现。
- Semrush：保存租户 key、运行同步，并确认快照写入项目文件系统。
- SMTP：保存凭证、创建草稿，人工核对收件人、主题和正文后发送。
- 对象存储：创建快照、检查远端对象和清单，再执行恢复演练。
- OIDC：使用允许域名登录，确认成员角色和审计事件。
