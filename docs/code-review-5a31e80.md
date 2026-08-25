# Code Review — `5a31e80` refactor(billing): remove unused lite plan

**审查范围**: 全量代码审查（api/ + engine/ + web/）
**审查重点**: 安全、功能正确性、并发可靠性、计费逻辑、租户隔离
**日期**: 2026-08-25
**基线**: 引擎 248 测试全绿，API 443 测试全绿

---

## 结论摘要

工程质量整体偏高：无跨租户 IDOR、无 SQL 注入、无硬编码密钥、AES-GCM 用法正确、`.env` 未入库、Docker 非 root + lock 安装、CI 部署前跑测试。审查中实证复现了 3 个缺陷，其余按代码路径逐条核实。

最需要立即处理的是三类问题：**平台池代付无任何上限**（直接成本敞口）、**订阅到期完全不本地生效**（授权只靠 webhook）、**项目额度可无限绕过**（已实证复现）。

---

## 一、已实证复现的缺陷

### 1. 项目额度可无限绕过 — Critical

`api/projects/router.py:353-357`

```python
if existing is not None and existing.archived_at is None and existing.status != "archived":
    _error(status.HTTP_409_CONFLICT, "project_already_exists")
if existing is None or (existing.archived_at is None and existing.status != "archived"):
    check_project_creation(db, tenant)
```

命中已归档项目时，第一个条件不报错，第二个条件为假 → `check_project_creation` 被完全跳过，而紧接着的代码把该项目 `archived_at = None` 复活。

**实证复现（试用套餐上限 3）：**

```
4th create -> 403 {"error":"trial_limit_exceeded","detail":"trial projects limit is 3"}
restore p0 -> 202
restore p1 -> 202
ACTIVE PROJECTS AFTER RESTORE: 5
```

建 3 个 → 归档 2 个 → 新建 2 个 → 复活那 2 个 = 5 个活动项目，可无限重复。付费套餐同理（Pro 10 → 15 → 20…）。每个活动项目都能挂定时复跑并消耗平台池，与第 3 条叠加。

**修法：** 复活分支同样调用 `check_project_creation`。

---

### 2. 预算预留永久泄漏，项目自锁 — High

`api/adapters/sampling_control.py:258-260` 在投递前写入预留，`:110-117` 计算余额时对预留求和且**不过滤任务状态、不设时效**：

```python
Job.budget_reservation_status.in_(("reserved", "review")),
```

清除 `reserved` 的路径只有 3 处（`platform_pool.py:254-256`、`:305-306`、`:351-356`），其中 `reconcile_usage_outbox` 只回收 `review`。任何在进入 `_funded_engine_context` 之前失败的路径都会留下永久预留。

**实证复现（Celery 投递抛异常）：**

```
JOB 1 status= failed reservation= reserved reserved_calls=1 reserved_cost=50
```

任务已 `failed`，预留仍在，永久占用项目月度预算。累积到超过预算后 `ensure_allowed` 会拒绝该项目**所有**后续采样（含定时任务），只能手工改库。

**修法：** 预留求和加 `Job.status.in_(("queued","running"))`；`reclaim_stale_jobs` 与 API 投递失败分支都释放预留。

---

### 3. dev 环境 beat 服务无法启动 — High

`docker-compose.yml:100` 行尾多一个引号：

```yaml
--schedule=/tmp/citeaura-celerybeat-schedule"
```

Docker 自身拒绝解析：

```
services[beat].command invalid command line string
```

beat 是**唯一**触发 `reclaim_stale_jobs`（卡死任务回收）和 `reconcile_platform_usage`（计量补偿）的组件。dev 环境这两项完全不工作。`docker-compose.prod.yml:87` 用的是 exec 数组形式，正确 —— 所以这个 bug 一直没被发现。

---

## 二、计费与授权

### 4. 平台池代付无任何上限 — Critical（成本敞口）

`api/billing/platform_pool.py:112-120` 仅按套餐授予池访问权，`api/projects/sampling.py` 对付费租户**自动开启** `platform_pool_enabled`。而两处支出闸门完全相同：

```python
# api/projects/router.py:738 与 api/worker/tasks.py:1073
if project.monthly_budget_cny_fen is not None or project.sample_call_limit is not None:
    ...enforce...
```

默认值为 NULL → 从不检查。付费套餐 `plans.sample_runs` 均为 `None`（无限），`config.py` 也没有任何全局或人均池上限。一个 Starter 租户挂满定时复跑，可无限量把供应商调用记在平台账上。`usage_counters.platform_cost_cny_fen` 只用于展示，不参与拦截。

---

### 5. 订阅到期不本地生效 — High

`api/billing/router.py:207-222` 的 `_sync_tenant_plan` 只看 `status`，从不比较 `expires_at`。全库检索确认：**没有任何一处按 `expires_at` 降级**，`beat_schedule` 里也没有到期核对任务。后果：

- `past_due` 在授权集合内 → 扣款失败仍享全量付费权限，直到 `subscription.deleted` webhook 到达；
- webhook 丢失（`BILLING_ENABLED=false` 或超过 Stripe 约 3 天重试窗口）→ 所有租户永久保留付费套餐。授权没有独立可信来源。

---

### 6. 乱序 webhook 可复活已取消订阅 — High

`_update_subscription`（`router.py:238-285`）无任何顺序水印，直接写入 payload 里的 status。对比发票路径 `router.py:342` 是有防复活保护的：

```python
if paid and row.status in ("canceled", "unpaid"):
    return False
```

`_update_subscription` 没有对应逻辑。`deleted`(T2) 先到 → 降级为 trial；延迟的 `updated`(T1, status=active) 后到，因 event_id 不同不被幂等表拦截 → 恢复付费套餐且背后已无真实订阅。Stripe 不保证顺序，无需攻击者即可触发。

---

### 7. 按比例计费发票被静默丢弃 — Medium-High

`_update_invoice_status`（`router.py:310-326`）要求 `amount_paid` 严格等于**整周期**金额，但 `/subscribe` 升级走 `proration_behavior: "always_invoice"`（`stripe.py:170`），发票金额是差额。结果 `invoice.paid` 返回 False → 无 `PaymentTransaction`、不刷新状态、无收据邮件，且 webhook 返回 **200**，Stripe 不再重试。含税、优惠券、余额抵扣的发票同样中招。

补充：`invoice.payment_failed` 分支完全不校验金额，无条件置 `past_due`，与上面形成不对称。

---

### 8. 失败任务退还配额 — Medium

`api/billing/limits.py:48` 用 `Job.status != "failed"` 统计配额。试用租户只要能让任务在采样后阶段失败（中途吊销自己的 BYOK Key 即可），就能无限刷采样次数，绕过 2 次/项目、6 次/工作区的限制。

---

### 9. 非 USD 币种金额写入 NULL — Medium（依赖配置）

`router.py:367` 与 `:413`：

```python
amount_usd_cents=amount if currency == "usd" else None,
```

`PaymentTransaction` 表（`models.py:325-343`）只有 `amount_usd_cents`，没有 CNY 列。而 `config.stripe_currency()` 合法接受 `cny`。若部署为 CNY，所有交易金额落 NULL 且不可恢复，管理端收入统计全部归零，退款去重（`router.py:397-407`）也会因 `coalesce(...)=0` 而重复入账。两个 env 示例默认都是 `usd`，所以当前仅是配置雷。

---

## 三、任务与可靠性

### 10. queued 任务被误杀且消息被静默丢弃 — High

`api/worker/job_runtime.py:34-37` 把**排队等待**当作故障：

```python
stale_queued = db.query(Job).filter(
    Job.status == "queued",
    Job.created_at < cutoff,   # 2 小时
).all()
```

排队 2 小时在有积压时很正常（生产 worker 未固定 `--concurrency`）。任务被标 `failed`/`worker_lost_or_timeout`、项目标 `failed`，而 Redis 里的消息仍然存在；worker 稍后取到时 `prepare()` 发现 `status != "queued"` 直接返回 `{"status":"ignored"}` —— 用户看到一个从未执行过的任务失败，消息被吃掉，预留同时泄漏（第 2 条）。

`running` 的回收是合理的（`task_time_limit=3600` 使 >2h 运行不可能），但 `queued` 回收没有依据。

---

### 11. 卡死窗口最长 2 小时，期间项目硬锁死 — High

无心跳、无 revoke，唯一存活信号是 `started_at`。`task_time_limit=3600` 触发时 Celery 直接 SIGKILL 子进程，不抛 Python 异常 → `_job_status` 的 `except BaseException` 不执行，行永久停在 `running`。

因为 `uq_jobs_project_active` 是真实 DB 约束且 `_active_job` 返回 409，项目期间**完全锁死**：新建任务 409、`retry_project_job`（`router.py:808`）409、`archive_project_record`（`router.py:1175`）也 409 —— 用户连归档都做不到。而回收器只挂在 beat 上（第 3 条：dev 环境 beat 起不来，且 prod 的 beat 无 healthcheck）。

另：`MAX_JOB_ATTEMPTS` 重投递恢复逻辑（`tasks.py:653`）以 `request.redelivered` 为前提，Redis 传输走 `visibility_timeout` 而非 AMQP redelivery 标志，这段很可能是死代码。**这一点未在 `.venv` 中验证 kombu 的实际行为**，建议补一个显式测试。

---

### 12. 迁移 0014 在非空表上会失败 — Medium

`0014_active_job_uniqueness.py` 直接建部分唯一索引，无前置清理。任何跑过 0001–0013 的库都可能有违约行（当时既无约束也无回收器），`CREATE UNIQUE INDEX` 会中止，`alembic upgrade head` 卡在 0014。需要前置数据迁移合并重复活动任务。

其余迁移核对过：0012、0020、0022 加 NOT NULL 列都带了 `server_default`；revision 链 0001→0031 线性、单 head 单 base，无分叉。

---

### 13. 配额检查在跨项目场景仍有竞态 — Medium

只有 `sampling_control.reserve`（`:252-253`）持 `FOR UPDATE` 并在锁内重跑 `check_sample_run`。`create_project`、`run_pipeline_action` 的 autopilot/serve 路径都是裸读后插入。per-project 限制被 `uq_jobs_project_active` 顺带保护，但工作区级终身限制（6 次）跨项目并发可突破。

---

## 四、认证与安全

### 14. 管理员登录存在邮箱枚举时序侧信道 — Medium

`api/admin/router.py:221-222`：

```python
admin = db.query(PlatformAdmin).filter(...).first()
valid = admin is not None and admin.status == "active" and verify_password(...)
```

`and` 短路 → 邮箱不存在时**不执行** bcrypt，亚毫秒返回；存在时跑 cost-12（约 100-300ms），约 100 倍差异。

租户登录路径（`api/auth/router.py:283-285`）做对了 —— 用 `DUMMY_PASSWORD_HASH` 烧掉一轮 bcrypt。同样的防护没应用到权限最高的管理台。修法照抄租户路径即可。

---

### 15. logout 的 `break` 位置导致可能不撤销会话 — Low

`api/auth/router.py:396-418`：`break` 在 `sv` 判断**之外**。第一个能解码的 token 若 `sv` 过期，什么都不撤销就退出循环，后面仍有效的 refresh cookie 不被检查，接口照样返回 `{"ok": True}`。

需要客户端同时携带过期 bearer 和当前 cookie 才触发，SPA 走 cookie 模式不发 bearer，实际可达性有限。修法：`sv` 不匹配时 `continue` 而非 `break`。

---

### 16. 注册接口用状态码泄露账号是否存在 — Medium

`api/auth/router.py:181-183` 特意用 `DUMMY_PASSWORD_HASH` 抹平时序，却紧接着返回 `409 email_already_registered` —— 一个比它所防护的时序信道更廉价的完整预言机。同文件的 `/auth/password/forgot` 恒返回 `202` 是正确做法，内部不一致。

---

### 17. 无按账号的暴力破解锁定 — Medium-Low

`api/rate_limit.py:130-140` 只按 IP 计数（20 次/60 秒），无账号维度计数或锁定。分布式攻击对单账号无上限。租户密码下限仅 8 位（`router.py:46`）、无复杂度或泄露库校验。

`check_request` 对非 auth 路径在 Redis 不可用时 fail-open（`main.py:95-102`），但 auth 路径正确 fail-closed。

---

### 18. 死代码可返回明文 API Key — Low

`api/settings/router.py:95-108` 的 `_provider_response(include_key=True)` 会把 BYOK 明文放进 HTTP 响应体。检索了所有调用点，**当前无任何一处传 True**，不构成实际泄漏。建议直接删除该参数。

---

### 19. AES-GCM 未绑定归属（无 AAD）— Low

`api/settings/crypto.py:36` 的 AAD 为 `None`。原语用法本身正确（12 字节随机 nonce、有认证标签、密钥强制 32 字节）。但密文未与 `tenant_id`/`engine_code` 绑定，具备写库能力者可把 A 租户的密钥行搬到 B 租户下正常解密。传 `f"{tenant_id}:{engine_code}".encode()` 作 AAD 即可闭合。

---

## 五、前端

前端有两套安全姿态。**SPA** 所有视图字符串统一经 `setSafeHtml` → `sanitizeHtml`（`safe-html.js:28-58`，`<template>` 惰性解析 + 移除危险标签/`on*`/危险 URL，最后 `replaceChildren` 插入 DocumentFragment，不再序列化）。配合 `api/main.py:146-149` 的 `script-src 'self'`（无 `unsafe-inline`），**未发现可执行脚本的 XSS**。

### 20. workbench.js 问题文本与来源路径未转义 — Medium

`web/app/views/workbench.js:26,28`：

```js
<strong>${question?.text || ...}</strong>
<span class="tag tag-neutral">${source.kind}: ${source.path}</span>
```

追完整链路：`add_questions`/`update_question`（`api/adapters/workspace.py:493-563`）只校验长度与市场，**不清洗 HTML**；`dashboard.workbench`（`engine/scripts/dashboard.py:127`）原样返回；前端未转义渲染。同文件其他字段（`sample.answer`、`engine_name`、citations）都正确调用了 `escapeHtml` —— 所以这是遗漏而非设计。

影响是内容伪造/点击劫持（`sanitizeHtml` 不拦 `form`/`input`，`style` 白名单也允许 `position:absolute`），CSP 阻止脚本执行。

---

### 21. team.js 完全未引入转义函数 — Medium

`web/app/views/team.js:61,109,110,111` 直接渲染 `m.email`、`inv.email`、`inv.role`、`inv.status`，该文件没有 import 任何转义工具。

邮箱正则（`api/auth/router.py:57`、`api/team/router.py:30`）是 `[^@\s]+@[^@\s]+\.[^@\s]+`，只排除 `@` 和空白。实测确认以下载荷全部通过校验：

```
'<b>@evil.co' True
'<img/src=x/onerror=alert(1)>@e.co' True
'<input/id=invite-email-input>@e.co' True
```

DOM clobbering 链可达：`web/app/index.html` 中 `#app`(21 行) 在 `#modal-root`(30 行) **之前**，而 `sanitizeHtml` 不拦 `<input>` 也不删 `id` 属性。注入的 `<input id="invite-email-input">` 会在 `getElementById`（`team.js:151`）中胜出 → 邀请邮箱被静默替换。攻击路径：以恶意邮箱注册 → 被正常邀请进工作区（外包/代理商场景）→ owner 打开团队页。同类模式还有 `competitors.js:172`、`report.js:227`、`facts.js:105`。

**修法：** 邮箱正则收紧（禁 `<>"'`），team.js 全字段转义，`BLOCKED_TAGS` 增加 `template`/`form`/`input`。

---

### 22. 管理台无 sanitizer — Medium

`web/admin/admin.js` 11 处裸 `.innerHTML` + 5 处 `insertAdjacentHTML`，仅靠局部 `escapeHtml`。逐个核对了所有插值：租户可控字段（`item.email`、`item.name`、`item.error` 等）**当前都已转义**，未发现实际 XSS。问题是这里没有第二道防线 —— 未来一处遗漏即等于最高权限控制台的存储型 XSS。建议同样接入 `setSafeHtml`。

---

### 23. 错误横幅永久显示 "undefined" — Medium

`web/app/app.js:341` 用 `${err.message}`，但 `api.js` 抛出的是**没有 `message` 字段**的对象字面量（`api.js:75,84,99-104`）。任何视图 render 期间的 API 失败都显示 `Error loading view: undefined`，且所有语言下都是英文。应改用已导出的 `tError(err)`。

---

### 24. 遥测弹窗日志流可永久冻结 — Medium

`telemetry-modal.js:399-401` 的 `finally` 仅在 `token === streamToken` 时重置 `isFetching`，而 `resetForRetry`(`:189`) 和 `openTelemetryModal`(`:243`) 递增 `streamToken` 时不重置该标志。轮询在途时切换 token → `isFetching` 永久为 true → `:328` 的守卫使后续每次 tick 都提前返回，弹窗永远停在"连接中"。

---

### 25. i18n：工单标题被当作翻译键 — Medium

`overview.js:271`：`t(ticket.title, {}, ticket.title_en || ...)`。`i18n.js:130-134` 仅在 `currentLocale === DEFAULT_LOCALE` 时使用 fallback，否则返回 `[[missing:${key}]]`。引擎生成的工单标题不是目录键 → 中/日/韩等语言下仪表盘直接显示 `[[missing:Add FAQ schema to pricing page]]`。应先用 `hasCatalogKey` 判断。

另有一批硬编码英文绕过目录：`report.js:91,97,157-161`、`assets.js:41-43,69,87-90,131`、`competitors.js:127,130`、`facts.js:56`。

---

### 26. 可访问性 — Medium-Low

- `job-monitor.js:59` 顶栏任务进度是挂了 click 的 `div`，无 `role`/`tabindex`/键盘处理，键盘不可达。
- `telemetry-modal.js:283` 有 `role="dialog" aria-modal="true"`，但无初始焦点、无 Tab 焦点陷阱、无 ESC 关闭、无焦点归还。`modal.js:82-138` 这四项都实现正确，可直接移植。
- 弹窗内 `<label>` 均未关联控件：`team.js:139,143,200`、`competitors.js:160,164`、`report.js:217`。
- `table.js:24,38` 对 `col.label` 和 `val` 原样插值，把转义责任推给调用方，是潜在隐患。

---

## 六、与 AGENTS.md 的偏差

约束 #1 保持完好：`api/adapters/` 里没有 SaaS 逻辑泄进 `engine/`，引擎 248 测试全绿。

但适配层实现已经**优于**文档描述，文档没跟上：

- 文档说 monkey-patch `geolib.die()` 和 `geolib.ROOT/WORK`。实际走的是 `geolib.scoped_paths`/`scoped_runtime` 的 **ContextVar**（`geolib.py:31-68`），并发安全性远好于全局赋值。
- `engine.py` 里的 `patch_die`、`patch_paths`、`patch_project_lock` 检索确认**零调用**，是死代码，且与文档描述冲突，容易误导后续开发。建议删除并更新 AGENTS.md。

顺带确认适配层几个关键点是可靠的：
- 租户目录隔离经 `slugify` + DB 唯一约束 + 迁移 0024 去重三重保障，无碰撞
- 引擎 `sample.py:31-36` 覆写 `ThreadPoolExecutor.submit` 用 `copy_context().run`，使 ContextVar 路径作用域能穿透引擎线程
- `geolib.write_json/write_jsonl` 用 `os.replace` 原子写

另有死代码：`api/billing/limits.py:125` 的 `reconcile_usage_counter` 全库（含测试）零引用。

---

## 建议修复顺序

| 优先级 | 项 | 理由 |
|--------|-----|------|
| P0 | 4 平台池无上限 | 无界成本敞口 |
| P0 | 1 项目额度绕过 | 已复现，可无限重复 |
| P0 | 5 到期不生效 | 授权无独立可信来源 |
| P0 | 3 beat 引号 | 一行修复，解锁回收与计量补偿 |
|------|------|------|
| P1 | 2 预留泄漏 / 10 误杀 queued / 11 硬锁死 | 用户可见的自锁死 |
| P1 | 6 乱序 webhook / 7 proration 丢单 | 收入正确性 |
| P1 | 14 管理台时序 / 21 邮箱正则+team.js | 最高权限枚举面 + 唯一可达注入链 |
|------|------|------|
| P2 | 12 迁移 0014 / 8 配额退还 / 13 竞态 / 23-25 前端 | 部署阻塞与体验 |
| P3 | 15-19 认证加固、18 死代码、AGENTS.md 同步 | 纵深防御与一致性 |

---

## 未能验证

- **kombu Redis 传输是否置位 `request.redelivered`**：决定第 11 条中重投递恢复逻辑是否为死代码，建议补一个显式测试。
- **`api/adapters/log_translator.py` 是否对 job 错误与日志尾部做密钥脱敏**：若不脱敏，考虑到引擎 stdout/stderr 被直接重定向进对成员可见的日志文件，BYOK Key 泄漏风险需要提级。