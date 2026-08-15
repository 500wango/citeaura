# CiteAura 完整 Code Review 报告

**审查对象**: 仓库 HEAD `98e6b69`（fix: handle unscored pages in autopilot）
**审查日期**: 2026-08-15
**审查方式**: 六路并行只读深审（引擎 / API 核心·认证 / 适配层·Celery / 业务路由·计费 / 前端 / 部署配置）+ 对关键路径的运行时复核（Node 模块求值、Python API 可用性、配置交叉核对）
**文件状态**: 全程只读，未修改任何文件；本报告为唯一产物

> 说明：审查会话沙箱无临时目录写权限，`engine` 219 个测试与 `api` pytest 未能实跑（环境限制，非代码缺陷）。测试结论基于静态审读。

---

## 1. 总体结论

安全基线整体扎实：**租户隔离**（所有路由 `tenant_id` 均从 JWT/DB 推导而非请求体；路径全部 `SLUG_OK` 白名单 + `resolve/relative_to` 二次校验）、**BYOK**（解密 → `os.environ` 注入 → finally 恢复，密钥不进日志/异常/manifest）、**JWT/加密**（HS256 算法白名单、bcrypt cost=12、AES-256-GCM、`session_version` 全局会话吊销）、**前端**（HttpOnly + SameSite=strict Cookie、全站 CSP、统一 setSafeHtml 净化）均达到合格水准，**未发现可用的跨租户越权、路径穿越、存储型脚本执行**。

但存在 **1 个 P0 致命 bug（前端整体白屏）**、**约 12 个高危问题**（集中在计费强制边界、Celery 任务可靠性、交付包数据安全、部署配置失效安全）以及约 40 个中低危问题。

---

## 2. P0 — 致命（立即修复）

### P0-1  `web/app/api.js:319` — 默认导出引用未定义的 `integrations`，整个 SPA 无法加载

```js
export default { auth, projects, workspace, settings, branding, publishing, outreach,
  integrations,   // ← 未定义标识符，ES Module 严格模式求值即抛错
  team, billing, sso, archive };
```

- **复现**: 全仓 grep `integrations` 仅此一处；Node 实测 `import('./web/app/api.js')` → `ReferenceError: integrations is not defined`；43 个前端模块中 33 个（含 `app.js` 与全部视图）加载失败，`/app` 白屏。
- **引入点**: `81b84d4 refactor: remove legacy SEO integrations` 删除了 `integrations` 对象但遗漏默认导出中的引用。
- **修复**: 删除第 319 行；增加模块级冒烟测试（构建检查禁止未定义简写属性）。

---

## 3. 高危（12 条，建议 1–2 周内修复）

### 3.1 计费与配额（直接经济损失）

1. **平台池出资动作无预算检查** — `api/projects/router.py:1171-1199`：额度检查仅覆盖 `sample/autopilot/serve`；而 `api/worker/tasks.py:50-52` 的 `PLATFORM_FUNDED_ACTIONS` 含 `bootstrap/expand/generate/cycle` 等 7 个动作（注入平台池密钥并 `record_usage` 计费）。付费租户可无限触发 `expand/generate/bootstrap` 烧平台池成本。修法注：采样估算器（question_count×repeat×单价）不适用于 bootstrap/generate/expand——应为这些动作建立独立的预算预留模型；无法估算 LLM 负载的动作应禁止使用平台池（仅 BYOK）。
2. **试用额度可绕过且 create_project 直投 autopilot 无采样额度检查** — 已核实（`projects/router.py:687-694`）：同 slug 归档后重建会**复用原 Project 行**（额度保留，此路径无重置）；真正的缺口有二：① `create_project`（`router.py:668-725`）只调 `check_project_creation`（项目数），投递含采样的 `autopilot` 前**不调 `check_sample_run`**；② 换域名/换 slug 重建即得全新 project id 与全新 2 次采样额度。修法：限额按租户生命周期记账（如按 URL 去重），create_project 的 autopilot 纳入 `check_sample_run`/`ensure_allowed`。
3. **预算只在投递时按估算检查，且无预留** — `sampling_control.ensure_allowed` 基于 `estimate()` 估算值；worker 执行前不复查（复查仍有 TOCTOU）；并发投递共同超支。口径注：`record_usage` 记录的是**逻辑调用量 × 配置单价**，不是供应商真实账单（`sampling_control.py:114` 已注明 BYOK 账单不可见）。修法：在数据库事务内做**预算预留**（UPDATE 计数 WHERE 剩余 ≥ 估算），执行后按实际计量结算/释放；并发投递由同一事务串行化。

### 3.2 任务可靠性（重复执行 = 重复烧 BYOK/平台池额度）

4. **Celery 硬超时/worker 崩溃后任务无限重投** — `api/worker/celery_app.py:18-21`：`acks_late + reject_on_worker_lost + time_limit=3600`，任务无 `max_retries`/启动去重；`_job_status.prepare()`（`tasks.py:465-469`）无条件把 job 重新标 running。超时任务每小时重跑整条管线，重复消耗 LLM 额度；DB 侧 2 小时回收（`_reclaim_stale_jobs`）拦不住 broker 重投。修复：**原子认领**（`UPDATE jobs SET status='running' WHERE id=? AND status='queued'`，0 行即正常结束 ack）——注意 `max_retries` 约束不了 broker 级 redelivery（reject_on_worker_lost 的重投不经过 task.retry）；硬超时/OOM/进程被杀无法由任务内部捕获，仍需外部孤儿回收（现有 `_reclaim_stale_jobs` 2 小时窗口偏长，且原子认领同时修复「迟到重投复活 failed job」竞态）。
5. **同一项目可并发跑两个任务（无整管线锁）** — `with_tenant_context` 只 patch 引擎逐操作短锁（`engine/scripts/tasks.py:289,347`）；`_active_job` 是无锁 SELECT（TOCTOU）；`uq_jobs_project_active` 只防同时建 job 不防重投。并发任务对 `metrics/*.json` 的 `provenance/sample_summary` 无锁读改写互踩（`measurement.py:304-314`），jsonl 读到半行计数偏低。修复：任务开头 `with_for_update` 认领 Job + 整管线持 Redis 项目锁。
6. **交付包重建失败会删除上一版完好交付包** — `api/adapters/delivery.py:2173-2177`：except 分支 `if target.exists(): shutil.rmtree(target)`，此时 `target` 仍是旧包（`_build_delivery` 尚未 rename）；下载接口（`projects/router.py:1636`）**每次 ZIP 下载都触发整包重建**。任何一次重建失败（语言校验、源文件缺失）即删光上一版交付包并 404。修复：旧包先改名再 rename，失败回滚。

### 3.3 引擎

7. **`geolib.fetch` 无内网地址防护、redirect 不校验最终主机（SSRF 面）** — `engine/scripts/geolib.py:232-291`：`requests.get(url, allow_redirects=True)` 跟随重定向后不重新校验 final_url。**严重级细分（外部评审后调整）**：生产 SaaS 全部经 `with_tenant_context` → `protect_network_fetches` 逐跳校验（每跳 validate_outbound_url + 同站跳转），故 **SaaS 语境为中危**；引擎独立 CLI/库路径（绕过预检）仍为高危。残余风险：校验与连接之间的 **DNS 重绑定 TOCTOU**——仅重解析 host 不能根治，需 IP 固定连接或基础设施出网限制（egress 白名单）。
8. **旧格式样本行 `r["analysis"]` 直接下标访问 → KeyError 拖垮聚合（中危·健壮性）** — `engine/scripts/analytics.py:54,120,138-139,152-153` 与 `sample.py:574`：`aggregate()`/`trend()` 无 `.get` 保护。外部评审后降级说明：`dedup_rows`（`sample.py:557`）的 "legacy" 仅指**缺 `run_id` 的行**，并非缺 `analysis`；仓库现存样本（`work/michael-rich2010/citeaura-com/samples/2026-08-13.jsonl`，17 行）全部含 `analysis`，**无实证表明历史数据普遍缺该字段**。保留为中危：升级/导入第三方数据时仍可能触发，建议统一在读取边界规范化或跳过畸形记录，避免各处散落 `.get()`。

### 3.4 部署与认证

9. **preflight 的 TLS 证书校验必然崩溃且所有部署路径都跳过它** — `scripts/production_preflight.py:196-199` 调用 `ssl.match_hostname`（Python 3.9 已移除；**本机 3.12 实测 `hasattr=False`**）；`Makefile:20`、`deploy.sh:20`、`one-click-deploy.sh:91` 全部带 `--skip-certificate` → 唯一的证书校验从未真正运行。另 `deploy/certs/` 未列入 .gitignore。修法（外部评审后调整）：用 `openssl x509 -checkhost` 或 cryptography 校验 CN/SAN 替代已移除的 API；**`--skip-certificate` 是否移除取决于 TLS 终止位置**——nginx 本机证书（`deploy/certs/`）场景应启用校验，Caddy/Cloudflare 终止 TLS 的场景无需校验应用侧证书，应保留跳过并显式声明。
10. **CI 无测试 job，push main 即部署生产** — `.github/workflows/deploy-production.yml` 无任何 test step（引擎 219 测试 + API pytest 都不跑），`on: push branches: [main]` 直接 SSH 部署。修复：前置 `make test` job + `needs: test`。

### 3.5 认证

11. **JWT_SECRET 运行时/readiness 校验弱（中危，外部评审后降级）** — 已核实 `scripts/production_preflight.py:15,92-94`：**生产 preflight 已拒绝占位符与 <32 字符的密钥**（`PLACEHOLDERS=("replace-with","example.com","changeme")` + 长度检查），正式部署路径受保护；缺口在于：① 应用运行时（`config.py:78-79` 只取非空、`auth/security.py:18-23` 仅查 not secret、`api/readiness.py:46` 只查 `len>=32`）不拒绝占位符；② dev/直跑 Docker（不经 preflight）环境照抄 `.env.example` 即暴露。修复：把统一 secret 校验集中到运行时/readiness（拒绝占位符 + 强度下限，fail-closed）。
12. **refresh token 轮换不吊销旧令牌、无复用检测** — `api/auth/router.py:237-272` + `security.py:64-66`：无 jti、无服务端存储、无 family/reuse 检测；旧 refresh token 直到 30 天过期前始终有效。泄露后可反复刷新维持会话。修复：refresh token 服务端存储（哈希 + jti/家族 + 复用标记）或至少 jti 黑名单。

---

## 4. 中危（约 20 条）

### 4.1 认证与安全

- **认证限流仅按 IP、无按账号锁定** — `api/rate_limit.py:69-79`：auth_scope 直接按 IP 计桶；无 failed_attempt 计数/lockout；admin 登录同桶。攻击者用代理池可无限尝试单账号。另注册 409（`auth/router.py:139-140`）泄露邮箱是否已注册；登录对不存在用户跳过 bcrypt（:211-213）形成时序侧信道（应 dummy bcrypt 抹平）。
- **代理头信任与部署形态错配** — `api/rate_limit.py:50-58`：仅当 `RATE_LIMIT_TRUST_PROXY_HEADERS` 开启才读 XFF 首段；uvicorn 未配 `--forwarded-allow-ips`。无真实代理时开启 trust → 自设 XFF 绕过限流；代理后保持关闭 → 全站共享代理 IP 桶（20 次/分），单点流量锁死所有用户登录。应由 uvicorn `--proxy-headers --forwarded-allow-ips=<CIDR>` 维护客户端 IP。
- **`SESSION_COOKIE_SECURE` 默认 false** — `api/config.py:86-87`；令牌 cookie 可明文传输。readiness 有 `checks["https"]` 但不是硬门槛（不 fail-closed）。
- **`forgot_password` 可被滥用** — `api/auth/router.py:305-329`：每次调用作废该用户全部未用 token 并触发发信 → 邮件轰炸 + 重置流程 DoS。应按 email 限流 + 冷却期。
- **OIDC `email_verified` 缺失时放行** — `api/auth/oidc.py:155-157`：仅 `is False` 拒绝，缺失即放行。应要求必须存在且为 True。
- **async 中间件同步 Redis + fail-closed 503** — `api/main.py:53-81` + `rate_limit.py:99`：`check_request` 同步阻塞事件循环；Redis 抖动全站 503。建议 async redis/线程池 + fail-open 选项。
- **注册无账号创建上限** — 仅受 IP 限流，多 IP 可批量注册（低）。
- **Swagger/Redoc 生产默认暴露** — `api/main.py:32`，含 admin 路由面（低）。

### 4.2 前端

- **safe-html 白名单缺 `form`/`ping`/`id` 剥离** — `web/app/safe-html.js:5-54`：AI 回答（prompt 注入可控）经 `engines.js:163`、`workbench.js:36`、`gaps.js:28`、`overview.js:78` 渲染时可注入 `<form action>`、元素 ID 冲突、`<a ping>` 外带。CSP 挡住脚本执行，但 UI 劫持/钓鱼真实存在。
- **`app.js:481-484` document 级 click 监听器随每次渲染累积** — 路由切换/任务完成重渲染后无限叠加（内存泄漏 + 陈旧回调）。应模块初始化注册一次。
- **`app.js:549-552` job 消失（含 failed）一律 toast「completed successfully」** — 失败误报成功。
- **`web/docs.html:977` 内联脚本被全站 CSP `script-src 'self'` 拦截** — `/docs` 搜索/目录高亮失效；`index.html:33` 内联 JSON-LD 同理。
- **`publishing.js:56,105` 教用户把 API 密钥拼进 URL query** — 进代理日志/浏览器历史。
- **`i18n.js:84` 插值用 `String.replace` 字符串替换** — 插值含 `$&`/`$'`/`$1` 时输出损坏（Node 实测复现）。
- **`app.js:599-604` reset/invite token 写进 URL hash** 残留浏览器历史；`modal.js:102-108` ESC 监听器非 ESC 关闭路径不清理。

### 4.3 适配层 / worker

- **计费入账失败令成功任务判 failed** — `tasks.py:327-333`：`record_usage` 瞬时 DB 错误 → job 判 failed、项目 status failed，用户重跑重复消耗配额。应独立短事务 + 有限重试，失败只记日志。
- **`_sampling_succeeded` 回退历史 metrics** — `tasks.py:108-130`：本次零新增样本（密钥全缺/平台全跳过）也可能判成功，产出假阳性报告。
- **manifest 平台模式按 provider 配置标注，可能高估「联网检索」** — `measurement.py:271-273` vs 引擎逐行实际 `searched`（`sample.py:781`）；与 workbench/交付逐行标注矛盾（硬约束 #7 准确性）。另 `delivery._sample_modes`（`delivery.py:531-552`）存在第二套判定 + 静默 fallback 参数化。
- **进程级 patch `requests.Session.request` 影响并发无关请求** — `adapters/engine.py:145-222`：patch 期间同进程其他 requests 调用被套同站跳转策略，跨站直接抛错。
- **outreach 草稿状态机缺陷** — 卡 `queued`（DB 提交失败，`outreach/router.py:290-308`）与卡 `sending`（进程被杀，`outreach.py:205-221`）均无回收路径。需统一超时回收 + 失败回滚。
- **`_job_status` 只捕 Exception** — `tasks.py:502`：硬超时/SystemExit 等 BaseException 使 job 卡 running 最长 2 小时。
- **archive 状态追加/恢复无项目锁** — `archive.py:255-258,370-415`：并发归档丢记录、恢复期混入 worker 写入。
- **`_engine_keys` 吞 DB 错返回 {}，`inject_keys` 反而抹掉全部引擎 Key** — `tasks.py:223-232` + `engine.py:127-133`：DB 抖动时 verify/deliver 在无密钥状态运行。

### 4.4 业务路由

- **调度器不校验 `tenant.status`** — `tasks.py:664-747`：禁用租户的 7/14/30 天周期仍持续执行并产生平台池计费。
- **subscribe 无行锁** — `billing/router.py:506-509`：并发请求各自创建 Stripe Checkout，重复付费。
- **create_project 并发唯一约束冲突返回裸 500** — `main.py:120-126` 只映射 `uq_jobs_project_active`。
- **retry 校验错误误报 503** — `projects/router.py:1095-1106`：`archive_restore` 缺 archive_id 等 ValueError 被当 worker 故障，job 固化 failed。
- **accept_invitation 不校验租户状态** — `team/router.py:261-294`：可为禁用租户签发一组死 token。
- **GET /billing/usage 带写副作用** — `limits.py:20-76` 每次 UPSERT + commit。
- **满额租户无法重激活归档项目** — `projects/router.py:680-694`：check_project_creation 在归档复用判断之前执行且不豁免该项目。
- **quota_blocked 调度空转** — `tasks.py:705-711`：不推进 `schedule_next_run_at`，每分钟重复扫描。

### 4.5 引擎

- **`deliver.py:186-189` 无条件 rmtree 重建当天交付目录、无锁** — 并发/重投互删交付包。
- **`jobs.py:261-269` start() 参数无类型约束** — list/bool 被 `str()` 拼进 argv 导致子进程解析失败。
- **LLM 调用最坏 ~15 分钟/次** — `sample.py:344-390` 重试 2 次各自独立 timeout；bootstrap 三次串行最长 ~45 分钟占住项目（claim 被拒）。
- **`sample_import`（`sample.py:893-896`）任意路径读取、无大小上限** — SaaS 侧受 workspace 适配约束，引擎 CLI 无约束。

### 4.6 部署

- **生产 Redis 无口令** — `docker-compose.prod.yml:15`：同一 bridge 网络内任何被攻破进程可读写 Celery broker/backend、限流计数、分布式锁。
- **容器无 cap_drop/read_only/no-new-privileges** — 单点加固只靠非 root。
- **readiness 硬编码迁移版本 `0021`** — 新增迁移忘记同步 → /ready 永久 503 → nginx 永不启动。
- **api 健康检查依赖 worker 存活，worker/beat 无自身健康检查** — worker 宕机 api 被判不健康但 restart 不触发；广播 ping 每 10s 一次。
- **nginx `server_name _` + 反射 `$host`** — Host 头攻击面（开放重定向/缓存投毒/重置邮件劫持），应用无 TrustedHostMiddleware。
- **preflight 强制项与生产示例直接矛盾** — `TRUST_CLOUDFLARE_COUNTRY_HEADER` 被强制 true 但示例缺失（且 Caddy 直连模型下置 true 会信任可伪造的 CF-IPCountry 头）；`STRIPE_CURRENCY` 示例 cny vs preflight 强制 usd。
- **requirements 未锁版本**（无 lockfile/hash，dev compose 还现场 pip install）；**配置漂移**（`CELERY_RESULT_BACKEND`/`WORK_ROOT` 被 config.py 读取但示例未列；.env.example 缺 5 个平台池 key）；**dev compose 的 JWT_SECRET/AES_KEY 空默认**（auth 直接 RuntimeError）且本地 `.env` 的 DATABASE_URL 指向旧项目（disvorai）与本机端口，与 compose postgres 服务脱节；**`dump.rdb` 未排除出构建上下文**。

---

## 5. 低危（择要）

- `api/worker/tasks.py:102-131` vs `:279-306` — `_latest_metrics`/`_sampling_succeeded`/`_require_sampling_output` **整段重复定义**，后者静默覆盖前者。
- `api/admin/router.py` — 报表 N+1 + 全表加载（租户规模数千后超时）。
- `api/adapters/delivery.py:745` — Ticket CSV「Affected Pages」列写入数量而非页面列表，与文档契约不一致。
- `api/migrations/versions/0021_remove_seo_integrations.py` — 破坏性 DELETE 且 downgrade 为空，不可回滚。
- `/files/` 端点不在 `/api/v1/` 前缀下，不受限流。
- `api/adapters/engine.py:279-290` — `_CONTEXT_LOCK` 进程级全局锁串行化 API 进程内全部引擎调用（可用性瓶颈；env 注入段必须互斥，但执行段不应持锁——需结构性解耦）。
- `api/adapters/locking.py` — Redis 不可用时项目锁硬失败无降级（有意取舍，建议记录）。
- patch 顺序脆弱：`adapters/engine.py:279-290` patch_die 之后、try 之前若后续 patch 抛错则 die patch 泄漏（当前不可达）。
- job 日志全量落盘引擎 stdout/stderr 与异常原文（防御性建议：对 `*_API_KEY` 形态掩码）。
- 限流固定窗口（边界 2x 突发）；已认证用户按 user 计桶而非 tenant（多用户租户获得成倍配额）。
- `web/admin/admin.js:304,318` 少量属性值未转义；`branding.js` 前端不验 logo MIME（后端 `adapters/branding.py:39-59` 有魔数校验兜底）；`plan.js:162` impact 大小写比较样式错配；`telemetry-modal.js:393` `job.progress ||` 吞掉 0；`billing.js:242` checkout_url 无协议校验。
- `engine/scripts/crawl.py:352-355` evidence/html 快照从不清理；`:143-146` deferred 列表绕过 role 配额；robots.txt 每 URL Disallow 未遵守（只记录 root 级阻塞）。
- `engine/scripts/report.py:398` 读 `metrics/{today}.json` 是永真死路径（metrics 文件名恒为 `<run_id>.json`）。
- nginx 缺 HSTS/ciphers/limit_req；deploy.sh 未校验 APP_PORT 数字、打印 Caddy endpoint 但自身不配 Caddy；CI 无应用层回滚。
- 全仓 76 个 api Python 文件含中文 docstring/注释，与 AGENTS.md「代码注释统一英文」不符。

---

## 6. 已验证为良好的实践（无需改动）

- **跨租户隔离**：所有路由 `_project_for_user`/`_tenant_for_user` 按 tenant 过滤；`/files/`（`ui.py:29-50`）resolve+relative_to+仅 delivery/；archive 解包按 manifest 白名单逐文件校验 sha256/size 防 zip-slip。
- **BYOK**：`inject_keys`（`adapters/engine.py:122-141`）previous 快照 + finally 恢复语义正确；密钥未出现在日志/异常/manifest；`threading.RLock` 保证进程内 env 互斥。
- **die→raise patch**：引擎所有 `G.die` 调用点均经 `geolib.die` 转发，`sys.exit` 仅存在于 geolib.die 内部；ROOT/WORK patch 时机与恢复正确。
- **引擎基础**：无 shell 子进程、无 eval/exec、网络全有超时 + 4MB 上限、JSON 原子写（tmp+os.replace）、normalize_url 拒绝 credentials/query、crawl 执行 same_site + max_pages + 页面级 robots meta 检查。robots.txt 说明（外部评审后修正）：引擎**读取** robots.txt 并记录 root 级 AI bot 阻塞状态（`crawl.py:329-335` 的 `ai_bots_blocked`），但**不执行每 URL Allow/Disallow 过滤**——这是已知低危缺陷（见第 5 节），非「完整遵守」。
- **采样模式契约（AGENTS.md #7）**：引擎行级 `sample_mode`/`terminal`/`search_enabled` → `api/adapters/sampling_modes.py:12-15` 三类中文标注 → web 渲染一致（`engines.js:156`）。注意：`sampling_label`（英文枚举）适配层未使用，实际契约字段为上述三个。
- **认证**：bcrypt、HS256 算法白名单、JWT/AES 无内置默认值（缺省即抛错）、OIDC 完整 state/nonce/PKCE/issuer/audience 校验、邀请/重置 token 256-bit 仅存哈希、`session_version` 吊销链路完整、cookie SameSite=strict + CSRF 头、SSO redirect_uri 固定无开放重定向、无 CORS（同源 SPA）。
- **前端**：401 并发刷新共享 Promise 无竞态；端点路径与后端一致；主渲染路径统一 setSafeHtml。
- **部署**：密钥不入镜像、git 只跟踪 env 示例、多阶段非 root 构建、Actions StrictHostKeyChecking + 独立 known_hosts + BatchMode、生产 api 仅绑 loopback、Makefile 与 tasks.md 一致。
- **测试**：引擎 219 个测试覆盖扎实（fetch 上限、原子写、路径穿越、采样去重/聚合、jobs claim/stop/orphan），网络全 mock，无「跳过即绿」；仅 test_live_contracts 2 个默认跳过（设计如此）。已知盲点：test_verify 仅 5 用例（mention_rate_gte/own_cite_gte 分支未覆盖）、jobs.start 真实子进程路径全 mock、expand 响应格式无测试、dashboard HTTP handler 无端到端测试。
- 上一轮 review（`docs/code-review-2debf66.md`）的 global_scope 合并顺序/covered 恒 False 问题已确认修复。

---

## 7. 建议修复优先级

1. **立即（今天）**：
   - P0-1：删 `web/app/api.js:319` 的 `integrations`；
   - 高 #9：修 preflight `ssl.match_hostname`（`scripts/production_preflight.py:197`）；
   - 高 #10：CI 增加 `make test` 门禁 job。
2. **本周**：
   - 高 #4/#5：**原子认领**（queued→running）+ 整管线项目锁 + 外部孤儿回收（三件套，缺一不可）；
   - 高 #6：delivery 事务式切换（staging 构建 → 旧包改名 backup → 原子切换，失败回滚）；
   - 高 #1/#2/#3：计费三处边界（平台池出资动作建立预算预留模型、无法估算的动作禁止用池、create_project 的 autopilot 纳入 `check_sample_run`、DB 事务内预留+执行后按实际计量结算）。
3. **本月**：
   - 高 #12：refresh token 服务端化（哈希 + family + 轮换 + 复用检测）；中危项 JWT_SECRET 运行时统一校验（preflight 已覆盖生产部署路径）；
   - 中危组：认证限流按账号（认证端点 fail-closed，普通业务请求短超时/熔断）、forgot 限流、safe-html 补 form/ping/id、app.js 监听器与成功 toast、preflight 与 .env.production.example 对齐（含 TRUST_CLOUDFLARE_COUNTRY_HEADER 与 STRIPE_CURRENCY）、引擎 analytics 读取边界规范化、outreach 状态机回收（卡 queued/sending 均需超时回收）、record_usage 失败用事务 outbox/持久重试（不能只记日志，会漏计费）。

---

## 附录：六路审查对账表

| 路 | 范围 | 问题数 | 关键结论 |
|---|---|---|---|
| A | engine/ 全部模块 + 测试 | 12 | SSRF 纵深缺失、旧样本行 KeyError、deliver 无锁 rmtree；测试 219 个无假绿 |
| B | API 核心 + 认证 + 迁移 | 14 | 认证核心扎实；短板在 refresh 吊销、JWT 强度、按 IP 限流、枚举侧信道 |
| C | api/adapters/ + worker | 18 | 租户隔离/BYOK/die→raise 正确；高危在 delivery 删旧包、Celery 重投、并发竞态 |
| D | 业务路由 + 计费 | 15 | 授权无 IDOR；计费强制边界三处高危 + 竞态/错误处理瑕疵 |
| E | 前端 SPA + admin + 落地页 | 15 | P0 为 api.js integrations；安全基线（Cookie/CSP/净化/401）扎实 |
| F | 部署/CI/配置 | 15 | CI 无测试门禁、preflight 与示例矛盾、证书校验必崩、Redis 无口令 |

**审查人注**：本报告为静态审读 + 定点运行时复核的产物；沙箱无法执行测试套件（无临时目录），测试结论以外部环境复核为准（见第 8 节），部署前建议在正常环境跑 `make test` 复核。
---

## 8. 修订记录（2026-08-15 依据外部评审意见）

| # | 原结论 | 修订后 | 依据（外部评审 + 本人复核） |
|---|--------|--------|------|
| 1 | 高 #1 修法：PLATFORM_FUNDED_ACTIONS 纳入 ensure_allowed | 采样估算器不适用于 bootstrap/generate/expand，应建独立预算预留模型；无法估算的动作禁止用平台池 | 估算器为 question_count×repeat×单价，动作 LLM 负载形态不同 |
| 2 | 高 #2「归档→重建」无限重置 | 同 slug 重建复用原 Project 行（额度保留，无重置）；真正缺口：create_project 直投 autopilot 不查 check_sample_run + 换域名重建获新额度 | 读 projects/router.py:687-694 确认 project = existing |
| 3 | 高 #3 修法：worker 执行前复查 | 复查仍有 TOCTOU；应在 DB 事务内预算预留，执行后按实际计量结算/释放；口径为逻辑调用量×单价，非供应商账单 | sampling_control.py:114 已注明 BYOK 账单不可见 |
| 4 | 高 #4 修法：投递上限 + 状态校验 | 原子认领（queued→running，非 queued 即 ack 短路）；max_retries 约束不了 broker redelivery；硬杀需外部孤儿回收 | Celery 语义：reject_on_worker_lost 重投不经 task.retry |
| 5 | 高 #7 SSRF（高危） | SaaS 语境降为中危（适配层逐跳校验兜底）；引擎独立路径仍高危；DNS TOCTOU 需 IP 固定/出网限制 | protect_network_fetches 覆盖 SaaS 全部引擎调用 |
| 6 | 高 #8 analytics KeyError（高危） | 降为中危·健壮性：dedup_rows 的 legacy 仅指缺 run_id；仓库现存样本 17 行全部含 analysis，无实证 | 检查 work/ 实际样本 + 读 sample.py:554-559 |
| 7 | 高 #9 修法：删 --skip-certificate | 修崩溃用 openssl x509 -checkhost/cryptography；是否删跳过取决于 TLS 终止位置（nginx 本机 vs Caddy/Cloudflare） | deploy/nginx.conf 与 one-click Caddy 两种模型并存 |
| 8 | 高 #11 JWT_SECRET（高危） | 降为中危：production_preflight.py:15,92-94 已拒绝占位符与短密钥（生产部署路径受保护）；缺口在运行时/readiness 与 dev 环境 | 读 production_preflight.py 确认 PLACEHOLDERS 与长度校验 |
| 9 | 第 6 节「crawl 遵守 robots.txt」 | 修正为：读取并记录 root 级阻塞（ai_bots_blocked），不执行每 URL Disallow 过滤（低危缺陷） | 读 crawl.py:329-335，确认仅记录不阻止 |
| 10 | 修复优先级 | 按上述修订更新：预算预留模型、原子认领三件套、outbox 记账、认证端点 fail-closed | — |

**测试复核补充（外部环境执行，非本沙箱）**：引擎 `python3 -m unittest discover -s tests` → **219 tests OK（2 skipped）**；API `pytest tests/ -q` → **295 passed**。与本报告静态审读无冲突；仍建议 CI 门禁固化（见高 #10），避免回归。

**关于代码语言规范的说明**：仓库 HEAD 的 AGENTS.md:75-77 与审查依据一致——「代码、注释、docstring、日志、异常统一使用英文」「中文仅允许存在于 locales/zh-CN、中文 NLP 规则、方法论引用和测试夹具」。全仓 76 个 api Python 文件含中文 docstring 的判断不因规范版本不同而改变（两份规范要求一致，不存在冲突）。
