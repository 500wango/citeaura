# CiteAura 全量代码审查报告（2026-09-07）

## 结论

本次对 `main` 的 `318143c` 进行了静态审查、隔离复现和既有测试验证。发现 13 项需要处理的问题：2 项 P0、6 项 P1、5 项 P2，另有 1 项工程质量基线问题。最先应阻断的是租户 ID/目录名歧义和生产环境 DNS 固定失效；两者都会突破 BYOK 与出站访问的安全边界。

这里的“全量”指 API、Worker、适配层、引擎网络入口、Web SPA/静态工具、迁移/部署、计量与数据交接边界均已审查。它不表示每一条正常生产路径都已以真实第三方凭据执行。每项均标记为“已证实”或“条件风险”，避免把推断表述为已发生事故。

## 范围与方法

| 项目 | 内容 |
| --- | --- |
| 代码基线 | `main`，`318143c`；审查开始时没有 tracked diff。原有 157 个未跟踪文件未修改。 |
| 覆盖范围 | `api/`、`engine/scripts/`、`web/`、Alembic、Docker/CI、依赖锁定和数据/计量边界。 |
| 静态检查 | Python 编译、JavaScript 语法、路由到适配层的调用链、租户/授权筛选、外部网络调用、任务状态机、持久化约束及前后端请求契约。 |
| 动态验证 | 隔离 SQLite、mock DNS、mock 交付状态和锁定版 Requests；未访问生产数据库、内部地址或第三方账户。 |
| 已有测试 | 之前完整执行：API `493 passed`、Engine `248 OK, 2 skipped`；本轮相关集 `18 passed`。现有测试通过不抵消下述未覆盖路径。 |
| 工具质量 | `ruff check api engine scripts` 报 1332 项；其中 `F821` 有 8 项，正好命中 GitHub PR 与 delivery 的确定性运行时错误。 |

## 风险排序

| ID | 级别 | 状态 | 问题 |
| --- | --- | --- | --- |
| C-01 | P0 | 已证实 | 数字工作区名可把一个租户的 BYOK / 自定义供应商解析为另一个租户 |
| C-02 | P0 | 已证实 | 锁定的 Requests 版本绕过 DNS 固定，出站 SSRF/DNS rebinding 防护失效 |
| H-01 | P1 | 已证实 | 预检在两次 DNS 解析之间发生 TOCTOU，可固定到未经验证的私网地址 |
| H-02 | P1 | 已证实 | GitHub PR 功能缺少实现和导入，配置完成后仍必然 500 |
| H-03 | P1 | 已证实 | delivery 自动补采的日志分支缺少 `json` 导入，任务必然失败 |
| H-04 | P1 | 已证实 | SSO 设置页发送的请求不符合后端必填契约，无法保存配置 |
| H-05 | P1 | 条件风险 | 项目创建先提交 queued Job，预算预留失败可留下无法立即恢复的任务 |
| H-06 | P1 | 条件风险 | Stripe Checkout 没有按租户去重或稳定幂等键，并发/超时重试可生成多个订阅入口 |
| M-01 | P2 | 已证实 | 公共 Schema 工具将远端 JSON-LD 原样写入 `innerHTML` |
| M-02 | P2 | 已证实 | 公共工具每小时配额信任可伪造转发头，且只存在于单进程内存 |
| M-03 | P2 | 条件风险 | Archive/outreach 没保存 Celery task ID，worker 丢失后的 redelivery 会被忽略 |
| M-04 | P2 | 条件风险 | OIDC endpoint 校验后用普通 Requests 连接，仍存在 DNS rebinding / 环境代理路径 |
| M-05 | P2 | 条件风险 | 平台代付计量的 outbox 写失败会被吞掉，成功任务可能永久少计费 |
| Q-01 | P3 | 已证实 | 1332 条 Ruff 基线错误掩盖了会导致生产失败的 undefined name |

## 详细问题

### C-01：数字工作区名造成跨租户密钥/供应商选择

**证据。** [`api/adapters/engine.py:294`](../api/adapters/engine.py) 的 `resolve_tenant` 把参数转为字符串后优先查询 `directory_slug` 和 `name`，只有没有结果时才 `db.get()` ID。工作区名来自 [`api/auth/router.py:104`](../api/auth/router.py)，`tenant_slug` 不排除纯数字。相反，Worker 的 [`api/worker/tasks.py:108`](../api/worker/tasks.py) 又先按整数 ID 查询，两个解析器的优先级相反。

隔离 SQLite 复现创建 `(id=1, slug=alpha)` 与 `(id=2, slug=1)` 两个租户后，`resolve_tenant(db, 1)` 输出 slug `1`，而不是 `alpha`。随后 [`api/billing/platform_pool.py:100`](../api/billing/platform_pool.py) 先正确依据目录找到项目所属租户，却在第 114 行以 `tenant.id` 再调用 `load_tenant_keys`；该调用会加载 slug 为 `"1"` 的另一租户凭据。相同模式还出现在 [`api/projects/sampling.py:47`](../api/projects/sampling.py) 及多个 reporting/worker 调用点。

**影响。** 攻击者或普通新租户只要得到一个等于他人现有 tenant ID 的纯数字目录名，就能让该 ID 的项目运行时使用自己的 API key/自定义 provider。受害租户的请求内容会发送给错误的供应商账户，BYOK 成本和结果也可能归属错误租户。这违反租户隔离和 BYOK 约束。

**建议。** 删除“一个参数同时代表 ID、name、slug”的解析语义。内部调用应只接受 `Tenant` 或整数 ID 并直接 `db.get`；仅边界输入使用单独的 `resolve_tenant_slug`。迁移前阻止新增纯数字 `name`/`directory_slug` 并审计现存冲突。为“ID 1 + slug 1 属于不同租户”加入一个回归用例。

### C-02：生产 Requests 2.34.2 未执行现有 DNS 固定

**证据。** 两个 `_PinnedAddressAdapter` 仅覆盖旧的 `get_connection`：[`api/adapters/engine.py:67`](../api/adapters/engine.py) 和 [`engine/scripts/geolib.py:90`](../engine/scripts/geolib.py)。`requirements.lock` 锁定 `requests==2.34.2`，该 Requests 发送路径使用 `get_connection_with_tls_context`。因此会回落到父类按原域名建连接。

在 `/tmp` 的隔离环境安装锁定版本后，对两个 adapter 调用 `get_connection_with_tls_context`，均得到 `pool_host=public-review.example`，而预期固定地址为 `93.184.216.34`。未发出网络请求。`requests>=2.31,<3` 的宽松声明也使开发环境 2.31 掩盖了该问题。

**影响。** 引擎受保护的抓取、公共预检、站点扫描以及可能经 `protect_network_fetches` 的调用，会在“先验证 DNS，后按域名连接”之间重新解析。攻击者控制的域名可进行 DNS rebinding，访问内部或云元数据地址。现有代理禁用、Host/SNI 设置和重定向检查都不能弥补连接目标已经错误的问题。

**建议。** 两处 adapter 都实现并测试 Requests 2.32+ 的 `get_connection_with_tls_context`，确保其返回以已验证 IP 为 host 的连接池并保留 TLS SNI。为锁定的依赖版本运行该回归测试；最好把网络 adapter 归并为一个经测试的公共实现，防止 API/engine 漂移。

### H-01：预检重新解析 DNS，固定的是未校验地址

**证据。** [`api/adapters/preflight.py:77`](../api/adapters/preflight.py) 先通过 `assert_public_host` 完成第一次解析和公网判断，第 78 行又调用只负责解析、不检查 `is_global` 的 `resolve_public_addresses`，并在第 94、130 行使用第二次结果的 `addresses[0]`。`resolve_public_addresses` 的行为见 [`api/adapters/network.py:12`](../api/adapters/network.py)。

mock 第一次 DNS 为 `93.184.216.34`、第二次为 `127.0.0.1`，隔离调用得到 `dns_calls=2 pinned_address=127.0.0.1`。即使 C-02 已修复，这个 TOCTOU 仍可绕过预检。

**影响。** 公共预检可能连接内部地址，造成 SSRF。它也会给用户报告一个不可信的可达性结果。

**建议。** 让一次 `validate_outbound_url(..., return_addresses=True)` 同时返回已验证地址，并只使用这一次结果；不要重新解析。对所有返回地址而非仅第一个地址保持公网验证。

### H-02：GitHub PR 路由是不可用的半实现

**证据。** [`api/adapters/github_pr.py:5`](../api/adapters/github_pr.py) 引用未定义 `_read_state`；还缺失 `requests`、`_api`、`geolib`、`_state_path`，并且没有 `create` 函数。`ruff --select F821` 确认其中 6 个未定义名称。`list_github_prs` 直接调用它（[`api/publishing/router.py:171`](../api/publishing/router.py)），创建路由在第 208 行调用不存在的 `github_pr.create`。

直接调用 `list_prs('project', {}, None)` 产生 `NameError: name '_read_state' is not defined`；模块上 `create` 不存在。路由只捕获 `GeoEngineError`、`RuntimeError`、`ValueError`，所以两种情况都是 HTTP 500。前端 [`web/app/views/publishing.js:20`](../web/app/views/publishing.js) 吞掉列表异常后显示 “No GitHub PRs yet”，使故障不可见。

**影响。** 任何已配置的 GitHub PR 列表/创建操作都无法完成，且用户得到误导性空状态。

**建议。** 在开放该入口前补齐一个可工作的 adapter（状态文件、GitHub API、错误转换、创建函数），或暂时移除 PR 路由与 UI。增加两个路由级最小用例：读取空列表和配置完成后的创建失败/成功；前端应展示请求错误。

### H-03：交付自动补采在日志记录时必然抛异常

**证据。** [`api/worker/worker_pipeline.py:88`](../api/worker/worker_pipeline.py) 与第 139 行调用 `json.dumps`，文件没有 `import json`。该函数在存在 `active_cohorts` 且 `needs_sampling=True`、并且 Job 有 ID 时进入该分支。

使用 mock 的有效项目、funding 和缺失采样状态调用 `_prepare_delivery_measurement(..., job_id=7)`，隔离复现输出 `NameError name 'json' is not defined`，发生在执行补采前。

**影响。** 交付前需要补齐样本的客户任务会失败，无法生成交付包，也不会执行预算预留和采样。

**建议。** 添加缺失的导入并为该分支保留一个最小的 worker 回归测试。日志 JSON 只应是辅助记录，不能成为采样主路径的单点故障。

### H-04：SSO 设置 UI 与 API 契约不一致，配置无法保存

**证据。** API model [`api/auth/sso.py:32`](../api/auth/sso.py) 把 `provider_name` 和非空 `allowed_domains` 设为必填字段；页面 [`web/app/views/security.js:115`](../web/app/views/security.js) 只提交 `issuer_url`、`client_id`、`client_secret`。隔离 Pydantic 验证返回缺失字段 `['provider_name', 'allowed_domains']`。

页面也没有填写 provider name、允许域、默认角色、启用状态和域验证的控件，虽然 API 已支持这些字段。

**影响。** Enterprise 所有者无法通过产品 UI 配置或启用 OIDC SSO；每次保存稳定返回 422。

**建议。** 使 UI 和 `SsoConfigRequest` 采用同一契约。最小修复是补齐必填输入并明确默认值，保存后展示字段验证错误；完整 SSO 使用流程还应提供域验证与 enabled 的安全确认。

### H-05：预算预留失败后会遗留未投递 queued Job

**证据。** [`api/projects/lifecycle_routes.py:163`](../api/projects/lifecycle_routes.py) 创建 Job，并在第 192 行先提交。工作目录初始化和 public audit 写入后，第 235-236 行的 `_reserve_sample_estimate` 位于任务入队 `try` 之外；只有第 241 行之后的 `.delay()` 失败会回写 failed 状态。若预算检查抛异常，已提交的 Job 没有 `celery_task_id`，也没有立即失败或释放路径。

[`api/worker/job_runtime.py:28`](../api/worker/job_runtime.py) 只能在 stale timeout 后回收没有 task ID 的 queued job，期间项目的活跃 Job 唯一约束会阻断用户重试。

**影响。** 预算边界或数据库异常时，用户会得到失败响应但项目长时间停在 queued/initializing，至少直到 stale cleanup，再以 worker lost 形式失败，失去真实故障原因。

**建议。** 把“创建项目、预算预留、入队”的失败补偿视为一个状态机：预留失败立即将该 Job/Project 标记失败并保留明确错误，或在入队前完成所有可失败的本地步骤。不要把 1 小时后的 stale cleanup 当作正常错误处理。

### H-06：订阅创建没有稳定幂等边界

**证据。** [`api/billing/router.py:645`](../api/billing/router.py) 查询 active subscription 但没有锁、pending checkout 记录或数据库约束；两个并发请求均可观察到“无 active”，并分别进入第 702 行。[`api/billing/stripe.py:61`](../api/billing/stripe.py) 对每次调用生成新的随机 `Idempotency-Key`，Stripe 将重试视为新的创建请求。`Subscription` 只唯一约束 provider 的 ID，不限制每租户一个 active subscription（[`api/models.py:284`](../api/models.py)）。

**影响。** 双击、并发请求或网络超时重试可返回多个 checkout session；若都完成支付，租户可能拥有多笔独立订阅。现有 webhook 处理能关联各 provider ID，但不阻止第二笔生效或收费。

**建议。** 为每个租户/订阅意图持久化短生命周期 pending checkout，并复用稳定幂等键；用行锁或数据库约束保护 active/pending 状态。Webhook 收到第二个有效订阅时需要有明确的拒绝、取消或人工处理策略。

### M-01：公共 Schema 工具存在已证实的 HTML 注入

**证据。** 后端把网站 JSON-LD 的 `@type` 原样转成字符串返回（[`api/projects/public.py:246`](../api/projects/public.py)）；静态页 [`web/assets/free-tools-schema.js:5`](../web/assets/free-tools-schema.js) 把 `data.types.join(', ')` 拼入 `rows.innerHTML`。主 SPA 使用 `setSafeHtml`，该独立公共工具没有使用它。

**影响。** 被检查网站能让结果页插入任意 HTML。当前 CSP 的 `script-src 'self'` 阻止通常的内联事件脚本，因此本审查没有把它表述为已执行的 JavaScript XSS；但 HTML 注入足以伪造界面、链接/表单并为 CSP 或前端改动后的 DOM XSS 留下入口。

**建议。** 用 DOM API 的 `textContent` 构造行，或对每个不可信字段运行同一 sanitizer；不要将服务端抓取的内容拼到 `innerHTML`。

### M-02：公共工具的严格小时配额可被伪造且不共享

**证据。** [`api/projects/public.py:56`](../api/projects/public.py) 无条件采用 `CF-Connecting-IP`，其次采用 `X-Forwarded-For` 第一项。这个值不经过 socket peer/可信代理链校验，和 [`api/rate_limit.py`](../api/rate_limit.py) 的处理不同。计数存储在进程内 `_AUDIT_REQUESTS`（第 53 行），重启丢失且多 worker 不共享。

**影响。** 外部客户端可轮换伪造头绕过每 IP 每小时 3 次的公共审计/抓取配额；多 worker 部署时也会按 worker 倍增。全局 Redis API 限流仍会限制请求速率，因此不是“所有限流均失效”。

**建议。** 复用 `rate_limit._source_ip` 的可信代理规则，并把公共工具的窗口计数放到 Redis；若 CDN 在前，明确由受信边缘清除/覆盖这些头。

### M-03：部分异步任务在 worker 丢失后无法按 redelivery 恢复

**证据。** Archive [`api/archive/router.py:79`](../api/archive/router.py) 和 outreach [`api/outreach/router.py:310`](../api/outreach/router.py) 调 `.delay()` 后丢弃返回的 task ID。Worker 以 `acks_late=True`、`task_reject_on_worker_lost=True` 配置重投（[`api/worker/celery_app.py:15`](../api/worker/celery_app.py)），但 [`api/worker/worker_job_lifecycle.py:32`](../api/worker/worker_job_lifecycle.py) 只有 `job.celery_task_id == redelivered_task_id` 才把 running Job 重新置 queued。没有保存 ID 的 Job 将在第 67 行被视为非 queued 并被忽略。

**影响。** 正在执行 archive/outreach 的 worker 被杀死或 broker 重投时，消息可能被忽略，任务保持 running，最终只会由 stale timeout 标记失败，不会按预期重试。

**建议。** 所有创建 Job 的 `.delay()` 都保存返回 task ID，或把 redelivery 认定建立在 job ID + 受控 attempt token 上；两条路径应使用共同的入队 helper。

### M-04：OIDC 出站请求没有使用已验证地址

**证据。** [`api/auth/oidc.py:37`](../api/auth/oidc.py) 验证 endpoint URL 和 DNS，但 [`api/auth/oidc.py:64`](../api/auth/oidc.py)、121、135 随后使用普通 `requests.get/post`，未使用固定 IP session，也未 `trust_env=False`。

**影响。** 在恶意或被劫持的 issuer DNS 于验证后改变时，discovery、token exchange 或 JWKS 请求可转向新地址；环境代理也可能参与。这条路径需要拥有 enterprise SSO 配置权限或其 IdP 被攻击，故按条件风险而非已被利用处理。

**建议。** 复用修复后的统一安全网络客户端，验证一次后固定 IP，显式禁用环境代理，对每次 redirect/endpoint 做同样检查。

### M-05：平台代付的最终 outbox 写入失败会静默漏账

**证据。** Worker 计量重试三次后调用 [`api/worker/worker_funding.py:247`](../api/worker/worker_funding.py) 的 `persist_usage_outbox`，但不检查返回值。[`api/billing/platform_pool.py:267`](../api/billing/platform_pool.py) 在数据库异常时 rollback 后直接返回 `0`（第 312-314 行）。任务可以保持业务成功，且没有 durable reconciliation event。

**影响。** 当主记账和 outbox 写入都因数据库故障失败，但模型调用已经发生时，平台代付调用可能永久不计费。进程硬终止发生在 finally 前也有相同的计量缺口。这个问题不意味着每次重投都会重复收费：`(job_id, engine_code)` 唯一键在成功落库时会去重。

**建议。** 将“outbox 未持久化”作为可观察的失败状态，至少让任务/Job 进入明确的 billing-review 状态并告警；长期方案是先持久化调用意图/计量事件再执行不可逆外部调用，或采用可恢复的账本协议。

### Q-01：静态检查基线掩盖运行时缺陷

`ruff check api engine scripts` 当前有 1332 项。单独执行 `--select F821` 的 8 项均为可执行代码的 undefined name：GitHub adapter 6 项、delivery 的 `json` 2 项。已有 18 项相关测试仍通过，原因是没有触达对应条件分支。

建议先把 `F821` 作为阻断项清零，再按目录逐步降低其他历史 lint；不要一次性格式化全仓库，以免制造无关 diff。

## 覆盖缺口和未列为缺陷的检查

* 多数项目 CRUD 都通过 membership 的 tenant 过滤，未找到直接的普通 IDOR；共享 delivery token 有高熵、过期和撤销校验。
* Archive 对 tar 路径穿越、符号链接和 hash 有防护；其“恢复为 merge”是明确文档契约，未当作漏洞。
* SPA 主渲染入口使用 sanitizer，因此没有把所有 template interpolation 一概报告为 XSS；M-01 是绕过该入口的独立静态页。
* 公共审计 `audit_id` 在项目创建时没有校验其 URL 与项目 URL 相同（[`api/projects/lifecycle_routes.py:119`](../api/projects/lifecycle_routes.py)）。这会把别站诊断写入新项目并生成错误首工单，属于 P2 数据完整性问题；建议与 H-05 一起修复，但其 ID 随机且短期过期，影响小于上表项。
* AES-GCM 解密在 AAD 校验失败后回退无 AAD（[`api/settings/crypto.py:43`](../api/settings/crypto.py)）。旧密文迁移需求可以解释该行为；在能改写数据库密文的前提下会削弱租户绑定，建议完成旧密文迁移后移除回退。没有证据表明外部攻击者可直接写库，故未升为主问题。

## 修复顺序与验收

1. 先修 C-01、C-02、H-01，并在锁定依赖环境加入冲突租户和 DNS 固定的回归测试。上线前轮换受 C-01 影响租户的供应商凭据，并检查任务/计量日志是否存在错配。
2. 修 H-02 至 H-05，恢复 GitHub PR、delivery gap-fill、SSO 配置和项目创建失败状态。每项添加一条入口级成功/失败路径测试。
3. 修 H-06、M-01 至 M-05，优先处理收费和公共入口；将异步入队及计量写入归并到可恢复状态机。
4. 验收应在 `requirements.lock` 的完整环境执行 `make test`、`ruff --select F821 api engine scripts` 为零，并用生产拓扑的可信代理配置验证公共限流和 OIDC/预检的固定连接。

## 本轮命令摘要

```bash
cd api && pytest tests/test_publishing.py tests/test_worker_funding.py tests/test_growth_funnel.py -q
# 18 passed, 1 warning

ruff check api engine scripts --select F821 --output-format concise
# 8 个 F821：github_pr.py 6 个，worker_pipeline.py 2 个
```

另运行了不接触生产资源的隔离脚本，分别复现了数字租户冲突、Requests 2.34.2 连接池 host、两次 DNS 解析、delivery `NameError`、SSO schema 422 与 GitHub adapter `NameError`。
