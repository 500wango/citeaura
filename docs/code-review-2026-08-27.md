# CiteAura 完整代码审查报告

> **审查范围**：API 后端（FastAPI + Celery）、前端 SPA、引擎适配层、基础设施配置
> **审查日期**：2026-08-27
> **发现总计**：**3 个 CRITICAL** · **5 个 HIGH** · **3 个 MEDIUM**

---

## 总览

| 模块 | CRITICAL | HIGH | MEDIUM |
|------|----------|------|--------|
| 认证 / SSO | 1 | 1 | — |
| API 核心 | — | 1 | 1 |
| 引擎适配器 | — | 1 | — |
| 基础设施 / 部署 | 1 | 2 | 2 |
| 安全 / 密钥管理 | 1 | — | — |
| 前端 SPA | — | — | — |

> **备注**：前端 SPA 经过完整审查，未发现影响运行的严重问题。应用在 XSS 防护（`safe-html.js` + `escapeHtml`）、Token 刷新（coalesced `refreshPromise`）、路由竞态保护（`renderSequence`）等方面设计合理。

---

## 🔴 CRITICAL 级别

### C1. SSO 账户接管：缺少域名所有权验证

- **文件**：`api/auth/sso.py`（`save_sso_config` L124-L148，`sso_callback` L188-L265）
- **严重程度**：🔴 CRITICAL

**问题描述**：

任何企业租户的 Owner 可以在 SSO 配置中指定 **任意域名** 作为 `allowed_domains`（例如 `targetcompany.com`），同时配置自己控制的恶意 OIDC Provider。在 `sso_callback` 中，系统仅检查 Identity 声明的 email 域名是否在 `allowed_domains` 列表中（L222），但 **不验证该域名是否真正属于该租户**。

```python
# sso.py L222 — 唯一的域名检查
if email.rsplit("@", 1)[-1] not in _domains(configuration):
    ...  # 拒绝
# 但 _domains 来自攻击者自己配置的 allowed_domains！
```

攻击链路：
1. 攻击者创建企业租户，在 `allowed_domains` 中填入 `victim.com`
2. 配置恶意 OIDC Provider，签发 `admin@victim.com` 的 Identity
3. 系统查找或创建全局 `User(email='admin@victim.com')`（L230-L240）
4. 攻击者获得该全局用户的 session，可通过 `switch-tenant` 访问受害者的工作区

**影响**：完整账户接管。攻击者可以冒充系统中任意用户。

**修复建议**：
- 新增域名所有权验证（DNS TXT 记录验证）后才允许将域名添加到 `allowed_domains`
- SSO 创建的 User 身份应严格绑定到该租户，不应共享全局 User 记录

---

### C2. .env 文件泄露加密密钥

- **文件**：`.env`（L3-4）
- **严重程度**：🔴 CRITICAL

**问题描述**：

`.env` 文件包含实际的 `JWT_SECRET` 和 `AES_KEY` 密钥值。虽然 `.gitignore` 中已排除 `.env`，但该文件 **存在于磁盘上并包含可用的密钥**。

**影响**：如果该文件曾被意外提交到版本控制、备份系统、或共享给协作者，则整个应用的 JWT 认证和 AES-256-GCM 数据加密将被完全破坏。

**修复建议**：
- 立即轮换生产环境的 `JWT_SECRET` 和 `AES_KEY`
- 检查 git 历史确认 `.env` 从未被提交过（`git log --all -- .env`）
- 开发环境使用明确标记为测试用途的密钥

---

### C3. Nginx 硬编码域名导致部署失败

- **文件**：`deploy/nginx.conf`（L13-42）
- **严重程度**：🔴 CRITICAL

**问题描述**：

Nginx 配置完全硬编码为 `citeaura.com`：
- `server_name citeaura.com www.citeaura.com;`
- 非匹配域名返回 HTTP 444（连接重置）
- Proxy headers 传递硬编码的 `Host: citeaura.com`

**影响**：使用 `standalone-nginx` profile 在自定义域名上部署时，应用完全不可访问。后端 API 也会基于错误的代理头生成错误的绝对 URL。

**修复建议**：
```nginx
# 使用变量而非硬编码
server_name $DOMAIN www.$DOMAIN;
proxy_set_header Host $host;
proxy_set_header X-Forwarded-Host $host;
```

---

## 🟠 HIGH 级别

### H1. 同步 Redis 调用阻塞异步事件循环

- **文件**：`api/main.py` L92-96（`api_rate_limiter` 中间件）+ `api/rate_limit.py` L130
- **严重程度**：🟠 HIGH

**问题描述**：

`api_rate_limiter` 是 `async` ASGI 中间件，但它直接调用 `check_request(request)`，该函数内部执行同步的 `redis_client().eval(...)` 网络请求。

```python
# main.py L92-96 — async 中间件中的同步阻塞调用
@app.middleware("http")
async def api_rate_limiter(request: Request, call_next):
    decision = check_request(request)  # ← 同步 Redis I/O 阻塞事件循环
```

**影响**：每个 API 请求都会在主事件循环上阻塞等待 Redis 响应，严重降低应用的并发性能和延迟。在高并发场景下可能导致请求排队和超时。

**修复建议**：
```python
from starlette.concurrency import run_in_threadpool
decision = await run_in_threadpool(check_request, request)
```
或迁移到 `redis.asyncio` 客户端。

---

### H2. 注册接口缺失账号级别限流

- **文件**：`api/auth/router.py` L175
- **严重程度**：🟠 HIGH

**问题描述**：

`/auth/register` 端点没有实施任何限流保护。`/auth/login` 正确使用了 `check_account(payload.email)` 进行邮箱级别限流，但注册路由完全缺失此保护。

> **注意**：虽然全局 IP 限流中间件会对 AUTH_PATHS（包含 `/api/v1/auth/register`）生效，但这只能限制单个 IP 的请求速率，无法防御分布式注册攻击。

**影响**：攻击者可以自动化批量创建账户，消耗数据库资源，并通过注册流程中的 `send_welcome_email_safe` 轰炸第三方邮箱。

**修复建议**：在注册路由中添加 `check_account(payload.email)` 调用。

---

### H3. SSRF / DNS 重绑定漏洞

- **文件**：`api/adapters/engine.py` L376-386 + `api/adapters/preflight.py` L69, L104
- **严重程度**：🟠 HIGH

**问题描述**：

两个独立的网络安全缺口：

1. **引擎适配器**：`with_tenant_context` 在 `needs_process_state = False`（无 LLM Key）时 **跳过** `protect_network_fetches()`，导致引擎发起的网络请求没有 SSRF 防护：

```python
# engine.py L381-383
if not needs_process_state:
    yield        # ← 直接放行，无网络保护
    return
```

2. **Preflight 检查**：`_resolve_public` 验证域名解析到公网 IP 后，`requests.get` 使用原始 URL 而非 pinned IP，存在经典的 TOCTOU DNS 重绑定漏洞：

```python
# preflight.py L69 — 验证后直接用 URL 发请求，DNS 可能已重绑定
homepage = requests.get(normalized, timeout=timeout, ...)
```

**影响**：攻击者可通过低 TTL 域名绕过 IP 检查，访问内网服务（如 `169.254.169.254` AWS 元数据端点）。

**修复建议**：
- `protect_network_fetches()` 应始终在 `with_tenant_context` 中启用
- Preflight 检查应使用 `_PinnedAddressAdapter` 固定已验证的 IP

---

### H4. Celery Beat 调度数据库不持久化

- **文件**：`docker-compose.prod.yml` L87 + `docker-compose.yml` L100
- **严重程度**：🟠 HIGH

**问题描述**：

Celery `beat` 服务将调度数据库写入 `/tmp/citeaura-celerybeat-schedule`，且生产环境的 `beat` 容器 **完全没有挂载持久卷**。

**影响**：每次容器重启或重新部署时，调度历史全部丢失。定期任务（如每日报告、计费清算、清理）会在重启后 **立即重新触发**，导致重复操作和数据不一致。

**修复建议**：
- 为 `beat` 服务挂载 `citeaura_work` 卷
- 将 `--schedule` 指向持久路径如 `/app/work/celerybeat-schedule`

---

### H5. Redis 密码在进程列表中明文暴露

- **文件**：`docker-compose.prod.yml` L37-41
- **严重程度**：🟠 HIGH

**问题描述**：

Redis 通过命令行参数传递密码：
```yaml
command: redis-server --requirepass "$$REDIS_PASSWORD"
healthcheck:
  test: ["CMD-SHELL", "redis-cli -a \"$$REDIS_PASSWORD\" ping"]
```

**影响**：任何有宿主机或容器 shell 访问权限的人都可以通过 `ps aux` 看到明文 Redis 密码。

**修复建议**：
```yaml
# 使用环境变量而非 CLI 参数
healthcheck:
  test: ["CMD-SHELL", "REDISCLI_AUTH=\"$$REDIS_PASSWORD\" redis-cli ping"]
```

---

## 🟡 MEDIUM 级别

### M1. 国际化只支持中文，其他语言全部 404

- **文件**：`api/landing.py` L241
- **严重程度**：🟡 MEDIUM

**问题描述**：

公共 i18n 端点的条件判断逻辑错误：

```python
# L241 — "or" 逻辑导致非中文 locale 直接 404
if code != "zh" or not path.is_file():
    raise HTTPException(status_code=404, ...)
```

当 `code = "en"` 时，`code != "zh"` 为 `True`，短路求值直接抛出 404，**即使 en.json 文件存在也无法返回**。

**影响**：公共落地页的国际化完全失效，除中文外所有语言返回 404。

**修复建议**：
```python
if not path.is_file():
    raise HTTPException(status_code=404, ...)
```

---

### M2. 生产环境缺失 PostgreSQL 依赖声明

- **文件**：`docker-compose.prod.yml` L7-9
- **严重程度**：🟡 MEDIUM

**问题描述**：

`x-app` 锚点的 `depends_on` 只声明了 `redis: service_healthy`，**未包含 `postgres`**。

**影响**：宿主机重启或 Docker 守护进程重启时，`api`、`worker`、`beat` 容器可能在 PostgreSQL 就绪前启动，导致短暂的崩溃循环和错误日志。

**修复建议**：在 `depends_on` 中添加 `postgres: condition: service_healthy`。

---

### M3. Worker / Beat 缺失健康检查

- **文件**：`docker-compose.prod.yml` L72-87
- **严重程度**：🟡 MEDIUM

**问题描述**：

Celery `worker` 和 `beat` 服务均未配置 Docker 健康检查。

**影响**：如果 Worker 死锁或静默崩溃（进程未退出但停止处理任务），Docker 无法检测到不健康状态，后台任务将无限期停滞。

**修复建议**：
```yaml
worker:
  healthcheck:
    test: ["CMD-SHELL", "celery -A api.worker.celery_app inspect ping -d celery@$$HOSTNAME"]
    interval: 30s
    timeout: 10s
    retries: 3
```

---

## ✅ 前端 SPA 审查结果

经完整审查，前端应用未发现 CRITICAL 或 HIGH 级别问题：

| 检查项 | 结果 |
|--------|------|
| XSS 防护 | ✅ `safe-html.js` + `escapeHtml()` 覆盖所有 `innerHTML` 赋值 |
| Token 处理 | ✅ 401 拦截器合并并发刷新请求（`refreshPromise`） |
| 路由竞态 | ✅ `renderSequence` 防止快速导航导致的状态覆盖 |
| 事件监听泄漏 | ✅ 模态框等临时监听器正确绑定了清理函数 |
| API 客户端 | ✅ 端点前缀、状态码处理、FormData 使用正确 |

---

## 修复优先级建议

> 以下按照 **业务风险** 排序，建议从上到下依次处理：

| 优先级 | Issue | 修复复杂度 | 紧急度 |
|--------|-------|-----------|--------|
| P0 | C1 — SSO 账户接管 | 高 | 🚨 立即 |
| P0 | C2 — 密钥泄露风险 | 低 | 🚨 立即 |
| P1 | H3 — SSRF/DNS 重绑定 | 中 | 尽快 |
| P1 | H1 — 事件循环阻塞 | 低 | 尽快 |
| P1 | H2 — 注册限流缺失 | 低 | 尽快 |
| P2 | C3 — Nginx 域名硬编码 | 低 | 部署前 |
| P2 | H4 — Beat 调度不持久 | 低 | 部署前 |
| P2 | H5 — Redis 密码暴露 | 低 | 部署前 |
| P2 | M1 — i18n 404 bug | 极低 | 本周 |
| P3 | M2 — Postgres 依赖声明 | 极低 | 下次部署 |
| P3 | M3 — Worker 健康检查 | 低 | 下次部署 |
