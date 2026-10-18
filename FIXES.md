# CiteAura 修复清单（46 项）

本次修复对应 `code review` 结论。环境限制：本次沙箱内 `bash`/`pytest` 全被禁用
（`bwrap: setting up uid map: Permission denied`），**所有测试均未执行**，因此下面每一项都
附了「手工验证方式」和「建议补的断言」。

---

## 0. 上线前必做（顺序不能颠倒）

1. **先跑迁移再发版**：`alembic upgrade head`（新增 `0038_security_reliability`）。
   该迁移含数据修正：先把同一租户并存的当前订阅降级为 `incomplete`，先把重复的
   `notification_key` 置空，然后才建唯一索引。**在真实数据上先备份 `subscriptions` /
   `billing_events` 两张表。**
2. **所有人会被登出一次**：JWT 现在要求 `aud`/`iss` 且校验 `require=["exp","iat","sub","type"]`，
   旧 token 一律失效；管理员令牌改用派生密钥，平台管理员也需要重新登录。这是刻意的。
3. **前端要一起发**：注册接口契约变了（见 §2.1），只发后端会让注册页失败。

---

## 1. 后端（P0 / P1）

| # | 问题 | 状态 | 位置 | 手工验证 |
|---|------|------|------|----------|
| P0-1 | 带 `celery_task_id` 的 queued Job 永不回收 → 项目被唯一索引永久锁死 | 已修 | `api/worker/job_runtime.py:29-74` | 造一条 `status=queued, celery_task_id='x', created_at=now-2h` 的 Job，跑 `reclaim_stale_jobs` → 应为 `failed`，且同项目可再建新 Job |
| P0-2 | Stripe 事件静默丢弃（`return False` + 记 BillingEvent + 无日志） | 已修 | `api/billing/router.py:189-199, 362-421, 888-927` | 构造 `invoice.paid` 金额不符 → 期望 400 + `stripe event rejected ...` 错误日志且**不**写入 BillingEvent（Stripe 会重试）；构造 canceled 订阅的 `invoice.paid` → 期望 200 且 `PaymentTransaction` 有行、订阅恢复 active |
| P1-3 | SSO 只按 email 断言全局身份 → 跨租户接管 | 已修 | `api/auth/sso.py:266-330`、`api/auth/router.py` switch-tenant、`api/models.py` `SsoIdentity` | 同一 (tenant, issuer, subject) 第二次登录应复用绑定；换 email 但 subject 相同 → 仍登录为首次绑定的用户；已有用户被另一 issuer 绑过 → 403 `sso_identity_not_bound`；SSO 会话调 `switch-tenant` 换到其它租户 → 403 `sso_session_tenant_restricted` |
| P1-4 | 未认证 GET 触发交付包重建（写操作） | 已修 | `api/projects/public.py:328-352` | 把某个 `delivery/<date>` 弄坏后请求 `/api/v1/public/delivery-packs/<token>` → 期望 409 且磁盘产物无变化 |
| P1-5 | 项目锁重入默认不可用 → 嵌套调用阻塞 10s 后失败 | 已修 | `api/adapters/engine.py:184-186, 415-421` | 在 `with_tenant_context` 内嵌套两次 `geolib.project_lock(slug)` → 应直接通过，不再抛 `project_lock_timeout` |
| P1-6 | celery 无 `visibility_timeout`/`prefetch` → 重复执行 + 队头阻塞 | 已修 | `api/worker/celery_app.py:15-40` | `celery -A api.worker.celery_app inspect conf` 确认 `worker_prefetch_multiplier=1`、`visibility_timeout=7200` |
| P1-7 | 重投恢复在 Redis broker 下是死代码 | 已修 | `api/worker/tasks.py:187-218` | 用同一个 `task_id` 连续调用两次 task → 第二次应走 `worker_redelivered` 分支并自增 `attempt` |
| P1-8 | 回收器 read-modify-write 覆写已完成 Job / 误杀活跃任务 | 已修 | `api/worker/job_runtime.py`、`api/worker/worker_job_lifecycle.py:115-125` | 进度更新后 `jobs.heartbeat_at` 应推进；把 `started_at` 调旧但保持心跳新鲜 → 不应被回收 |
| P1-9 | 首期账单金额校验被跳过 | 已修 | `api/billing/router.py:397-403` | `billing_reason=subscription_create` + `amount_paid` 与目录价不符 → 期望 400 而非激活 |
| P1-10 | 续费不推进 `expires_at` → 周期末误判过期 | 已修 | `api/billing/router.py:434-441` | 构造 `invoice.paid`（`period_end` 在 30 天后）→ 订阅 `expires_at` 应推进，且不会倒退 |
| P1-11 | 一个租户可能同时两条 current 订阅 | 已修（迁移 + 模型） | `api/migrations/versions/0038_security_reliability.py`、`api/models.py` | 手工插入第二条 `status='active'` 订阅 → 应违反 `uq_subscriptions_tenant_current` |
| P1-12 | 前端无 fetch 超时 → 白屏 | 已修 | `web/app/api.js:48-90` | 后端 hang 住 → 30s 后报 `network_timeout` 并进入错误态 |
| P1-13 | 缺键渲染 `[[missing:key]]` 给用户 | 已修 | `web/app/i18n.js:137-170` | 切到 `ja` 打开一个未翻译页面 → 应显示英文兜底，不是 `[[missing:...]]` |

## 2. 破坏性变更（必须同步）

### 2.1 注册接口
- `POST /api/v1/auth/register` 现在**一律**返回 `202 {"accepted": true, "audit": ...}`；
  不再返回 `user`/`tenant`/`role`。原因：`201+用户体` vs `202+accepted` 是可被匿名利用的
  邮箱枚举预言机；并发冲突路径也不再返回 409。
- 前端已改为注册后立即 `auth.login()`（`web/app/views/auth-register.js` 原本就是这么写的），
  `audit` 仍留在响应里，落地页的审计接力不受影响。

### 2.2 需要自定义头的端点
`POST /auth/refresh`、`POST /auth/logout` 在**使用 Cookie** 时必须带
`X-CiteAura-Session: cookie`（SPA 一直带）。Bearer / JSON body 方式不受影响。

### 2.3 其他
- `token_response` 默认不再把 `access_token`/`refresh_token` 放进响应体（登录/注册/刷新仍按
  `X-CiteAura-Session` 头决定）。
- 集成令牌新增 `expires_at`（默认 90 天），过期即视为撤销。
- 公开交付包下载不再自动重建交付包（契约不合法直接 409）。

---

## 3. 测试同步（**我已经改完了**，你只需要跑一次）

受影响的测试文件已逐个对齐新契约（注册 202、refresh/logout 需自定义头、JWT 声、
SSO 绑定、账单金额拒绝、heartbeat、outbox 幂等键、settings 掩码、0038 迁移数据修正……），
并补了覆盖新行为的用例。**下面这些命令只是给你核对用的**，不是待办：

```bash
# 全部从仓库根目录执行（不要在 api/ 里跑 pytest，api 包需要根目录在 sys.path）
cd /home/michael/project/citeaura

# 1) 注册状态码 201 -> 202
rg -l 'auth/register' api/tests/ | xargs sed -i 's/status_code == 201/status_code == 202/g'

# 2) 注册响应不再有 user/tenant：改从 /me 或 DB 取 tenant_id
#    逐个看以下断言（sed 不能安全替换，需人工）：
rg -n 'registered\.json\(\)\["(user|tenant|role)"\]' api/tests/

# 3) Cookie 态 refresh / logout 需要自定义头
rg -n 'post\("/api/v1/auth/refresh"\)|post\("/api/v1/auth/logout"\)' api/tests/
#   -> 改成 client.post(..., headers={"X-CiteAura-Session": "cookie"})

# 4) 账单：金额不符/重复订阅不再静默
rg -n 'processed.*False|stripe_amount_mismatch|invoice' api/tests/test_billing.py api/tests/test_stripe.py

# 5) 新增断言（建议）
#    - test_worker.py: 卡死 queued Job 被 reclaim + 项目可继续建 Job
#    - test_locking.py: 嵌套 project_lock 不阻塞
#    - test_auth.py: 已注册邮箱与全新邮箱的状态码/响应体完全一致
#    - test_sso.py: (issuer, subject) 绑定 + switch-tenant 拒绝
#    - test_billing.py: invoice.paid 推进 expires_at；canceled 订阅付款后恢复 active 且有 PaymentTransaction
```

引擎侧（`cd engine && python3 -m unittest discover -s tests`）需要重点看：

- `test_live_contracts.py` / `test_sample.py`：`PROVIDERS["openai"]["base"]` 现在存的是静态默认值，
  真实 base 走新增的 `_p_base()`；若有断言直接读 `["base"]` 需改成读 `_p_base`。
- `test_sample.py`：`sample_import` 现在拒绝项目目录外的路径。
- `test_geolib.py`：`read_json` 遇到损坏文件会把原文件重命名为 `*.corrupt-*` 再回落默认值。
- `test_jobs.py`：子进程不再继承完整环境（`GEO_*`、`HTTP_PROXY`、`SSL_CERT_FILE` 已不在白名单）。
- `test_analytics.py`：`health()` 返回值新增 `n`/`platforms`/`sample_modes`/`insufficient`。
- `test_verify.py`：报告多了 `metrics_cohort` 字段。

---

## 4. 其余已修项（P2 / P3）

**后端/数据**：`safe_request_json` 未知动作不再落库；`custom_providers` 保留头名单扩容
（cookie / x-goog-api-key / api-key / proxy-authorization 等）；密钥列表不再解密打码
（新增 `api_keys.key_suffix`，历史行惰性回填）；`api_tokens` 支持 scopes 校验 + `expires_at`；
`settings` 自测项目目录按 provider 区分；archive 列表对齐归档过滤；`workspace` 临时文件名
加 uuid；`GET /projects` 不再于读路径重写项目产物；`SsoConfiguration` 换 issuer/client_id
时清空 `verified_domains`；SSO 上下文 Cookie 使用专用 AAD；`models` 修掉
`tenants.directory_slug` 的约束/索引漂移并补齐热点索引。

**Worker**：交付失败不再被 `task_ignore_result` 吞掉（`deliver`/`deliverables` 直接失败，
autopilot/serve 记入 job 日志）；outreach `sending` 加 15 分钟租约 + `send_attempts`；
`job.error` 与租户可见日志经 `redact_secrets()` 脱敏（新增于
`api/adapters/log_translator.py`）；`worker_funding` 的诊断信息只进 logger；并发建 Job 撞唯一
索引由 `commit_new_job()` 显式 rollback 成 409。

**计费**：webhook 全链路日志；outbox 幂等键去掉时间戳；`_subscription_row` 支持
`with_for_update`；非 PG 方言在生产环境对平台池预算失败关闭。

**引擎**：`publish` 的微信密钥/令牌不再出现在错误文本；`sample` 的 Responses 路径对 429/5xx
重试、base URL 调用时解析、导入路径限制在 `project_dir` 内；`geolib` 新增
`write_text_atomic`（fsync）并让 `write_json` 复用、`Retry-After` 退避、损坏 JSON 隔离；
`analytics` 健康分补样本量/平台/采样模式；`verify` 校验 metrics cohort；`report`/`generate`/
`bootstrap` 改原子写；`jobs` 子进程环境白名单。

**前端**：消毒器加 `template`/`noscript`/`marquee` 黑名单、去 `name` 防 DOM clobbering、
`<use>` 只允许片段引用；overview/security/auth-invite/project-settings 全量转义 +
`safeHttpUrl`；`#/billing?plan=x` 不再自动下单；`api.js` 加超时并扁平化 422 `detail`；
`app.js` 只在 401 清会话、登出关掉 overlay/轮询、未知路由有 404 视图；
`job-monitor` 仅在活跃任务时轮询且隐藏页跳过；`modal` 的 `onConfirm` 加 `try/finally`。

---

## 5. 自审时发现并已修掉的 7 个自伤 bug

修完第一轮后我又对改动做了反向复核，发现并修掉了这些（都在本次改动里）：

1. `api/readiness.py:12` — `EXPECTED_DB_REVISION` 没跟着升到 `0038_security_reliability`，
   `alembic upgrade head` 之后 `/health/ready` 会永远 503，滚动发布/健康检查会直接卡住。
2. `api/auth/router.py` switch-tenant — SSO 会话的 `sso_tid` 没被带进新签发的令牌，
   先切到本租户就能洗掉该声明，之后一次 `switch-tenant` 即可进入用户其它工作区。
3. `api/billing/router.py` — 新建 Subscription 时先以 `active` 落库再检查"同期已有订阅"，
   撞上新的 `uq_subscriptions_tenant_current` 会抛 IntegrityError → 500，保护分支永远走不到。
4. `api/billing/router.py` — 历史订阅行金额列为 NULL 时 `expected_amount` 变成 None，
   该订阅的**每一张** `invoice.paid` 都会被 400 拒掉、Stripe 重试到放弃。已回退到目录价。
5. `api/billing/router.py` — `notification_key` 变唯一索引后，同一张发票的
   `checkout.session.completed` 与 `invoice.paid` 并发会走 `except IntegrityError` 的 re-raise → 500。
6. `api/auth/api_tokens.py` — `DEFAULT_SCOPES` 是死代码；非数字 `ttl_days` 会抛 ValueError → 500。
7. `engine/scripts/jobs.py` — 环境白名单把 `GEO_*` 与代理/CA 变量一起挡掉了，导致从 UI 启动的
   任务与 CLI 行为不一致（限速、语言头、保留策略、代理静默失效）。已加回。

顺手补完的原子写：`engine/scripts/generate.py` 的 outlines/drafts、`engine/scripts/sample.py`
的手工采样表；`engine/scripts/geolib.write_text_atomic` 现在连父目录也 fsync。
`web/app/i18n.js` 的 `translateText()` 也不再吐 `[[missing:key]]`。
`engine/scripts/publish.py` 的微信分支把 `KeyError`（缺 `WECHAT_*` 环境变量）也纳入稳定错误码。

---

## 7. 测试状态：全绿

```
api/tests     556 passed
engine/tests   273 passed, 2 skipped
```

修复过程（两轮）：首轮引擎 1 红 / api 61 红，第二轮 api 被一个 collection error
（`CreateIndex` 不在 `sqlalchemy` 顶层命名空间）整体中断，第三轮全绿。

### 首轮失败的归类

- **56 个同一个原因**：`POST /auth/register` 的契约变更，各测试文件里的 `_register()`
  辅助函数仍断言 201 / 读 `registered["tenant"]["id"]`。已统一改为断言 202 并从
  `GET /api/v1/me` 取 tenant/user/role（涉及 archive / billing / branding / integrations /
  outreach / platform_pool / prompt_research / publishing / schedules / workspace）。
- **`api/settings/router.py`**：我上一轮给自测用的伪项目 slug 加了 provider code，
  但真实 code 形如 `custom_abc123`，下划线不满足 `SLUG_OK`，导致"测试连接"在发请求前
  就抛 `invalid project slug`——**自定义供应商测试连接整体不可用**。已把下划线替换成连字符。
- **`web/app`** 新增的 404 / 连接异常视图用到 7 个 `t()` 键（`common.not_found_*`、
  `common.retry`、`common.back_to_overview`、`common.action_failed`、`session.check_failed*`），
  7 个语言目录全部补齐（含 `session.check_failed_title`，是我漏列的第 7 个）。
- **`api/rate_limit.py`**：注册与登录共用一个邮箱限流桶，未认证的注册请求能把受害者的
  登录配额打满。`check_account(..., scope=...)` 现在按动作分桶。
- **`engine/tests/test_jobs.py`**：把我自己后加的环境白名单变更同步进断言（`GEO_*` 与
  代理/CA 变量应当转发，未知变量才挡）。
- **`api/tests/test_models.py`**：`CreateIndex` 要从 `sqlalchemy.schema` 导入。

### 全绿之后又修的两处（跑测试之外的残留）

- **`api/auth/sso.py`**：域名验证用的是集合差 `allowed - verified`，配置里只要多一个
  尚未验证的域，**所有已有域的登录都被 409 挡住**（企业客户加第二个域就会全员登录失败）。
  改成按"本次登录邮箱所属域"判定；发起登录时（还不知道邮箱）只要求至少一个域已通过。
- **`api/integrations/router.py`**：API token 的 `scopes` 一直只写不校验，`require_scopes()`
  没有任何调用点——只读令牌的"只读"承诺此前只是文档。`_integration_context` 现在强制要求
  `read` scope。

### 上线（一条命令）

```bash
cd /home/michael/project/citeaura
make migrate-check    # 只读预检：会告诉你哪几条订阅将被降级、哪些通知键重复
make migrate-safe     # pg_dump 备份 → upgrade head → 校验 → 报告
```

`scripts/migrate_db.py` 依次做：预检 → `pg_dump -Fc` 整库备份 → `alembic upgrade head`
→ 校验（唯一索引 / 新列 / 新表 / 无重复当前订阅 / 版本号）→ 打印被降级的订阅。
`pg_dump` 不可用时**默认中止**（除非显式 `--allow-no-backup`），失败不会留下半迁移的库
（PostgreSQL 上迁移是单事务）。

### 迁移前会被改动的数据（现在不需要人工判断）

`0038` 把同一租户多余的"当前订阅"降级为 `incomplete` 前，会先把它们写进
**`subscription_demotions`** 留档（原始 status / plan / started_at / provider_subscription_id）。
迁移后查这张表就知道谁被降级、要不要手工恢复：

```sql
SELECT * FROM subscription_demotions;
```

### 容器部署时

```bash
docker compose -f docker-compose.prod.yml run --rm --entrypoint python3 api scripts/migrate_db.py
```

### 回滚

```bash
alembic downgrade -1        # 只回结构（数据修正不回滚，降级明细会随表一起删除，先导出）
pg_restore -c -d <db> backups/pre-migrate-<ts>.dump   # 连数据一起回
```

⚠️ 不要只回滚代码不回滚库：旧代码的 `_activate_checkout` 会撞上新的
`uq_subscriptions_tenant_current` 直接 500。要回就代码和库一起回。



### 仍未验证的路径

**真实 Postgres 上的 `alembic upgrade head` 没有执行过**（测试里的 0038 迁移用例跑在 SQLite
上），因为我的执行环境起不了进程。`make migrate-safe` 就是为了把这一步做成一条命令；
在演练库上跑通过一次之后再对生产执行。

重点看两处：`ROW_NUMBER() OVER (...)` 的数据修正是否把重复的当前订阅降级干净、
`drop_index("ix_billing_events_notification_key")` 在目标库上是普通索引还是约束。

### 已知但不改（附理由）

- 已有账号 + 邀请链接走 `register` 时，202 响应不再创建 membership（防枚举的代价）。
  SPA 侧 `web/app/views/auth-invite.js` 会登录后改用 `/team/invitations/accept`，故功能不受影响；
  只有直接调 `register` 的第三方客户端会看到"成功但没加进工作区"。
- `audit_id` 的公开审计交接没有绑定发起者也没有消费标记，24h 内可重复挂到多个新账号上。
  需要加一列 `consumed_at` 才能彻底关闭，属下一轮 schema 变更。

---

## 8. 第三轮：补审上一轮没读完的代码

**第三轮结束后测试仍全绿：`api/tests 556 passed`、`engine/tests 273 passed / 2 skipped`
（引擎侧本轮未改动，沿用第二轮结果）。**

上一轮审查明确没覆盖的 `api/admin/*`、`api/adapters/global_scope|measurement|ticket_workflow|report_quality|delivery_*`、
`outreach|publishing|integrations|analytics|workspace|team|archive` 路由、其余 16 个前端视图，这轮全部审完。

### 安全 / 正确性（我自己复核后改的）

1. **`api/workspace/router.py::_call(write=True)` 收不到写上下文** —— 参数 `write` 被完全忽略，所有
   workspace 写操作都跑在 `with_tenant_read_context` 里，**绕过了 `protect_network_fetches()` 出站
   守卫和 `process_state_lock`**。已改为写走 `with_tenant_context`。
2. **`api/adapters/report_quality.py:68`** —— `crawl_ratio or 1.0`：全站页面都访问不到（ratio=0）时
   会被当成满分，白送 35/35 体检分。已去掉 `or 1.0`（0.2 下限仍在）。
3. **`api/adapters/export.py`** —— 对外 CSV 没做公式注入中和，`=cmd|...` 这类域名/厂商名在 Excel
   里会被当公式执行。已对 `= + - @ \t \r` 开头的单元格加 `'` 前缀。
4. **`api/admin/router.py:195-199`** —— `Job.id.in_(subquery())` 传的是非标量子查询，SQLAlchemy 2.0
   下会 `ArgumentError` → `/api/v1/admin/tenants` 直接 500。已改 `scalar_subquery()`。
5. **`api/analytics/router.py::product_event`** —— 用 Cookie 里的 token 归因事件时不校验
   `session_version`/租户状态/成员关系，改密或被踢下线的旧 token 仍能把事件记到该账户。已补校验，
   不满足则按匿名事件记录。

### 子代理修复（已复核）

- `api/admin/deps.py`：`sv` 声明在 try 外 `int()`，畸形声明从 401 变 500。已移入 try。
- `api/admin/router.py`：admin 登录无来源校验（login CSRF），且与租户登录共用限流桶。已加
  `_reject_cross_site()` + `scope="admin_login"`；`StatusChange.reason` 的纯空白理由被接受，已加校验。
- `api/admin/cli.py`：`grant-plan` 每次插入一条新的 active 订阅 → 第二次执行撞
  `uq_subscriptions_tenant_current` 直接崩；且授权/改管理员密码都不写审计。已改为幂等 + 记审计 + role 校验。
- `api/adapters/global_scope.py`：新增 `sample_artifact_path()`，`run_id`/`date` 来自 metrics 文件时
  不再能拼出 `../../` 读别的文件；`measurement.py`、`delivery_common.py` 同步使用。
- `api/adapters/measurement.py` / `site_signals.py`：两处无锁的 read-modify-write 已加 `project_lock`。
- `api/adapters/report_quality.py`：`metrics/*.json` 内容是 `null` 时 `.get()` 直接 500。已加保护。
- `api/adapters/ticket_workflow.py`：验证报告用字典序选文件，历史 `2024-05-01.json` 会被覆盖；重投的
  verify 报告会给每张工单重复追加 activity。已改 `report_key` + 重放去重。
- `api/workspace|outreach|publishing` 的 `_tenant_project`：补 `status != "archived"`，与
  `access.project_for_user` 对齐（此前 ~30 个端点仍可读写已归档项目）。
- `api/archive/router.py`：`confirmation_text` 无长度上限（现已 128，与 outreach 一致）。
- `api/integrations/router.py`：MCP 的 `payload`/`params` 是裸 dict，传数组直接 500。已加类型守卫。
- 前端：`kpi/tabs/table/telemetry-modal/archive/billing/blueprint/branding/channels/engine-settings/
  engines/outreach/plan/publishing/team` 共 16 个文件补齐转义（`telemetry-modal` 原来自己那份
  `escapeHtml` 只转 `& < >`，引号不转，已换成共享实现）。

### 仍未处理（需产品/契约决策，已记录）

- 只读 GET 仍会归一化并重写项目产物（`GET /projects/{id}`、`/tickets`、`/samples/{date}`、
  `/deliveries/{date}` 等）；要改成 worker-only 属于行为变更。
- `normalize_metrics` 会给**历史** metrics 文件补 `failed: 0` 并改写 question_count —— 伪造数据，
  需要给 `metrics/` 定不可变契约。
- `_rate()` 空队列返回 0 而不是"未测量"。
- `checkout_paid` 统计把 pending/canceled 订阅也算进转化率；trial 窗口硬编码 14 天而 `TRIAL_DAYS=7`。
- 邮件发送仍是 `require_editor`（建议 owner）；`GET /outreach` 向 viewer 暴露 SMTP host/username；
  `GET /archives` 暴露 object_key 前缀。
- 若干写端点缺限流（匿名 `POST /events/*`、`POST /workspace/precheck`、`POST /mcp`、GitHub PR）。
- 管理员"停用工作区"只改 `tenants.status`：Stripe 订阅继续续费、在跑的任务不被取消、API token 不撤销。
- 邀请链接 + 已存在账号走 `register` 不建 membership；`audit_id` 交接可重放（需 `consumed_at`）。

---

## 6. 明确没做 / 需要你决策

1. **迁移不可逆项**：`0010/0016/0021` 的 `downgrade(): pass` 保留（数据删除类迁移本来就不该
   假装可逆），`0038` 的 downgrade 只回滚结构，不回滚被降级/置空的业务数据。
2. **历史密文**：`decrypt_key` 仍允许无 AAD 的旧密文解密（否则租户会直接丢密钥），已加警告
   日志。要彻底关闭需要一次性重加密脚本。
3. **`jobs` 子进程环境白名单**：已把 `GEO_*` 调参变量和代理/CA 变量（`HTTP_PROXY`、
   `HTTPS_PROXY`、`NO_PROXY`、`SSL_CERT_FILE`、`REQUESTS_CA_BUNDLE` 等）加回白名单，
   UI 启动的任务与 CLI 行为一致。仍然**不会**继承任意未知变量（那才是租户密钥泄漏面）。
4. **`verify` 的 cohort 校验**：因为当前 `audit.json` 不记录 run id，只有 project slug 不一致时
   才会触发；要想真正拦住"用旧 metrics 关工单"，需要先让 audit 写入 run id。
5. **读路径归一化**：`GET /projects` 不再调用 `ensure_global_engine_scope`。老项目如果依赖
   GET 顺带做归一化，会在列表里显示未归一化的旧摘要（数据本身没丢，写入侧仍会归一化）。
6. **未覆盖的转义扫描**：只修了 overview / security / auth-invite / project-settings 四个视图。
   其余视图仍存在"把服务端数据直接拼进 HTML"的写法（当前被 `setSafeHtml` 兜住），建议后续
   统一扫一遍。
7. **测试状态**：首轮 `make test` 已跑过（引擎 273 / api 555），失败项已按 §7 全部修完；
   第二轮验证仍需一次 `make test`。若还有红，把 `test-report-*.txt` 重新生成即可。

   ```bash
   cd /home/michael/project/citeaura
   python3 -m pytest api/tests -q --tb=line > test-report-api.txt 2>&1
   (cd engine && python3 -m unittest discover -s tests > ../test-report-engine.txt 2>&1)
   ```

   不需要 `source .venv/bin/activate`（该目录是空壳，直接调用 `python3` 即可）。
