# CiteAura 产品功能 Code Review

**审查对象**：仓库 HEAD `fe0decc`（`Enforce delivery review readiness`）  
**对照文档**：`PRD.md` v2.0、`AGENTS.md`、`tasks.md`  
**代码审查时间**：2026-08-17（对照当时 HEAD，工作树干净）  
**文档修订时间**：2026-08-17（写入本文件后，工作树仅多出未跟踪的 `docs/code-review-fe0decc.md`）  
**审查方式**：整仓只读深审（产品旅程 / SPA / 适配层·Worker·计费），对照 PRD §3.2 核心旅程与 §5.1 P0  
**上一份整仓审查**：`docs/code-review-98e6b69.md`（2026-08-15）

本报告目标是**完善产品功能设计**，不是风格点评。条目均有 `file:line`。未在当前代码中复核过的旧问题不沿用。

**修订说明**：首版成稿后按复核收窄了五处表述——工作树时间戳、创建项目的出网校验、预算预留泄漏范围、采样回放的安全定性、Celery 硬超时评级。详见文末「附录 A」。

---

## 1. 总判断

引擎和 API 已经把 GEO 闭环做出来了：域名建项、爬站、bootstrap、多引擎采样（带模式标签）、站点审计、工单、验收写盘、交付包 readiness、BYOK、试用限额、7/14/30 调度。

产品层没有把它走顺。默认试用用户最容易卡在：

1. 建了项目却看不到可见性报告  
2. 工单 2×2 全员掉进 Deprioritize  
3. 点验收没有自动通过/回归  
4. 不知道下一步该点哪

**缺的不是模块，是一条不会走丢的主路径。** 接入、报告、工单、验收四块对齐数据契约，比再加 Publishing / Outreach / SSO 更值钱。

相对 `98e6b69` 已修好、不要当现行缺陷：

| 旧问题 | 现状 |
|---|---|
| SPA 默认导出未定义的 `integrations`，整站白屏 | 已删除该引用 |
| 任务结束一律 toast 成功 | `done` / `failed` 已区分（`web/app/app.js:577-580`） |
| 创建项目投递 autopilot 不查采样额度 | 已调用 `check_sample_run`（`api/projects/router.py:728-729`） |
| 交付重建失败删光上一版 | staging + `.backup` 回滚（`api/adapters/delivery.py:2463-2484`） |
| 平台池给 bootstrap/expand/generate 买单 | `PLATFORM_FUNDED_ACTIONS == {"sample"}` |
| 无原子认领、无项目锁 | worker 有 queued→running 认领 + Redis 项目锁 |
| `record_usage` 失败把成功任务判失败 | 重试 + outbox |
| refresh 无复用检测、登录缺用户跳过 bcrypt | 已补 family 复用吊销、dummy bcrypt |
| CI 不跑测试就部署 | `.github/workflows/deploy-production.yml` 先 `make test` |
| 创建项目无出网/内网校验（旧审查的 SSRF 面） | `create_project` 已调用 `validate_outbound_url()`（`api/projects/router.py:694`）。缺口是产品 preflight 与平台池识别，不是基础 SSRF |

---

## 2. 产品闭环对照 PRD

承诺旅程（PRD §3.2）：

```
只填域名 → 爬站/bootstrap → 采样/可见性报告 → Playbook + 工单 → 验收 → 交付 zip
```

| PRD | 后端 | 前端 | 结论 |
|---|---|---|---|
| F-P0-01 只填域名，3 分钟出报告 | `create_project` + `cmd_autopilot` | URL 表单 | 未走 preflight；无 Key 静默跳过推理和采样 |
| F-P0-02 分引擎报告 + 模式 + raw 回放 | `_product_report` 含 `sampling_mode` / `citation_share` | Overview / Engines 有 badge | 无独立报告页；未测引擎不出现；引用份额列未展示 |
| F-P0-03 题库可编辑 + 拓词确认入库 | `questions` / `expand` API | 只能追加 | 不能改删；拓词无确认流 |
| F-P0-04 站点审计 + 建设地图 | `audit` + `blueprint` | 有 Site Audit | Blueprint 前端零引用；Gaps 实际是 Framing |
| F-P0-05 Playbook + 工单 | `/playbook` 已按 P0/S 排序 | Plan 自画 2×2 | 矩阵字段接错；排序接口闲置 |
| F-P0-06 自动验收 + 回归重开 | `verify` + `ticket_workflow` | 只有汇总计数 | **页面工单 checker 对不上，自动通过/重开不生效** |
| F-P0-07 资产生成 + lint | generate + facts 审批 | Assets 可编辑 | 缺独立生成入口和 lint 说明 |
| F-P0-08 交付包 | 带 readiness 的 zip | 可下载 | 与「报告」混页；下载会重建，失败 409 |
| F-P0-09 多租户 | 路径 + JWT tenant | — | 隔离看起来完整 |
| F-P0-10 BYOK | AES + 运行时注入 | 5 个西方引擎 + 自定义 | 接入不强制配 Key；平台池无 UI |
| F-P0-11 计费 | 试用 3 项目、终身 2 次/项目 | 只显示项目数 | 终身限额 vs 当月用量口径不一致 |
| F-P0-12 诚实边界 | `for_row` 模式标签、Unmeasured | 引擎行有 badge | 总提及率无旁注；落地页引擎/联网口径过满 |
| §3.2 调度 | 7/14/30 已实现 | Automation 页 | P1 已上线；禁用租户仍会跑 |

后端已有「下一步」契约：`report_quality.issues` 带 `message` / `action` / `route`。Overview 完全没用。

---

## 3. P0 缺陷（先修这些，Demo 才成立）

### 3.1 接入勾选框绑错字段

**文件**：`web/app/views/onboarding.js:38-42, 94-101`  
**相关**：`api/projects/router.py:65-66, 724-727`；`engine/scripts/bootstrap.py:316-318`；`api/worker/tasks.py:641-658`

勾选框文案是「跳过初始 LLM 采样，只做爬站和问题生成」。提交的是 `skip_llm`，不是 `no_sample`。

- `skip_llm`：跳过品牌事实和题库推理，直接返回骨架配置  
- `no_sample`：才跳过 `sample.run`

已配 Key 且勾选时：`skip_llm=true`、`no_sample=false` → 走 autopilot → 题库为空 → 采样被跳过 → worker 仍可能要求采样产出或把空跑标成成功。用户要的是「先出题、后采样」，得到的是「既没题也没采」。

无 Key 时系统会同时打开两个开关，任务能跑完，但只有站点审计，没有可见性数字。成功 toast 仍是 “Crawling and analyzing...”。

**建议**：勾选只提交 `no_sample`。`skip_llm` 不要出现在首屏。无 Key 时明确二选一：「只做站点审计」或「先去配 Key」。

---

### 3.2 无 Key / 未跑 preflight，首跑会装死

**文件**：`web/app/views/onboarding.js:90-117`；`api/projects/router.py:694, 724-727`；`api/adapters/preflight.py:46-105`；`web/app/api.js:135`

PRD §9：「引擎 Key 缺失时引导设置，不装死。」

创建项目**已经**做基础出网校验：`validate_outbound_url(payload.url)`（`router.py:694`）会拒绝内网、回环和不可解析主机。这里缺的不是 SSRF 门闩。

真正缺的是完整产品 preflight 和采样能力识别：

- `projects.preflight` 已实现（DNS / TLS / 首页可达 / 可采样估计），**没有任何视图调用**  
- 创建只认 `_has_api_keys`，不认已开启的平台池（`_has_sampling_access`）  
- 无 Key 静默 `skip_llm + no_sample`，Overview 主按钮却是 「View Delivery Pack」  
- `report_quality` 已发出 `api_key_missing` → `engine-settings`，首页不渲染

死站、WAF 站、只返回 3xx 的站点仍会进 8 段管线，最后以红任务收场。这是可达性与引导问题，不是「URL 没做私网拦截」。

**建议**：提交前跑 preflight（注意 301 / HTTPS 跳转不要误判未就绪）。无采样能力时阻断完整 autopilot，或走「审计-only」并写清后果。识别平台池与 BYOK 用同一套 `_has_sampling_access`。Overview 用 `report_quality.issues` 做就绪清单。

---

### 3.3 工单 2×2 字段接错，全员 Deprioritize

**文件**：`web/app/views/plan.js:35-42, 162, 233-265, 303-305`  
**相关**：`engine/scripts/tasks.py:20-27`；`api/projects/router.py:53-54, 1407-1444`

引擎工单是 `priority: P0/P1/P2` + `effort: S/M/L`，**没有 `impact`**。

前端：

```js
const imp = String(t.impact || 'high').toLowerCase();
const eff = String(t.effort || 'low').toLowerCase();
```

缺省 impact 变成 `high`；effort 变成 `s`/`m`/`l`，对不上 `'low'`/`'high'`。四个 if 全不中，**全部掉进 Deprioritize**。表格模式还把 Impact 画成字面量 `High`。

`GET /playbook` 已按 P0→P2、S→L 排好，`projects.getPlaybook` 从未被调用。

详情同样对不上：

| UI 读的 | 引擎实际 | 结果 |
|---|---|---|
| `desc` / `description` | `why` / `why_en` | 退化成 “Actionable engineering implementation item.” |
| `notes` 当字符串 | `notes` 是对象数组 | textarea 出现 `[object Object]` |
| 状态三档 | API 五档 | 没有 `blocked` / `wontfix` |
| Offsite 手填 `q001` | 题库页不显示 ID | 创建基本失败 |

保存工单后 `navigate('#/plan')` 已在该 hash 上，不重新挂载，卡片状态还是旧的。

**建议**：象限用 `priority × effort`（或直接消费 `/playbook`）。详情固定 Why / Action / Acceptance。备注追加。问题用多选文本，底层传 ID。保存后 `reloadCurrentView()`。

---

### 3.4 自动验收对当前工单基本不生效

**文件**：`api/adapters/action_scope.py:239-244`；`engine/scripts/verify.py:201, 231-239`；`api/worker/tasks.py:847`；`web/app/views/verify.js:5-40`

这不是「UI 太薄」这么简单。

Worker 跑 verify 前会 `normalize_project()`，把页面工单验收改写成 `pages.applicable:<id>`。`verify.check()` **没有这个分支**，落到 `Unknown checker` → `ok is None`。自动关闭要求 `ok is True`，回归重开要求 `ok is False`。产品里真正在用的页面工单会一直停在 `manual`。

交付包里的 `scope_verification()` 会另算一遍，**zip 和产品内验收会打架**。

UI 侧只有 Closed / Reopened / Pass / Fail / Manual 四个数字，没有单票 before/after，没有 `manual` 确认按钮。无工单时仍可点 Verify，引擎 `die("No action tickets found")`。

**建议**：

1. 在 `verify.check` 实现 `pages.applicable:*`，规则与 `action_scope.scope_verification` 一致  
2. 验收页展开 `results[]`：判定、证据、`progress_first` vs `progress`、跳转工单  
3. `acceptance.type === 'manual'` 提供确认/驳回  
4. 无票时禁用按钮

在 checker 修好之前，应把页面工单标成「仅人工」，不要暗示一键闭环。

---

### 3.5 采样成功定义不统一，旧报告会被标成这次的

**文件**：`api/worker/tasks.py:152-163, 641-658, 907-925`；`web/app/views/overview.js:271`

`task_bootstrap` / `task_cycle` 先 `measurement.record_sampling()` 再 `_require_sampling_output()`。`record_sampling()` 会改**最新** metrics 的 `provenance.job_id`，即使本轮没写出新样本。随后成功检查看到「job_id 对上了 + 旧的 successful > 0」就返回 True。项目标 `ready`，数字是上周的。

Overview「Rerun Autopilot」走 `task_pipeline`，空 params 时 `_should_require_sampling_result` 为 False：只爬站也能标 ready。创建项目走 `task_bootstrap`，两条路径结果不同。

**建议**：与 `task_sample` 对齐——先确认**本 job** 的 `sample.run()` 产出，再写 provenance。本轮 0 样本就标 `sampled=false`，不要碰旧 metrics。Rerun 若只要重爬，确认框应写明并传 `no_sample`。

---

### 3.6 接入任务被交付英文门禁绑架

**文件**：`api/worker/tasks.py:638-640`；`engine/scripts/geo.py:219`；`api/adapters/delivery.py:2154-2155, 2451-2485`

`cmd_autopilot` 末尾无条件 `deliver.run` + `ensure_delivery_contract`。中文站点事实/工单触发 Han/质量门禁时，**整次接入判失败**，即使 crawl/audit/tickets 已在磁盘上。用户只看到红任务，只能「从头再跑」。

下载 zip 每次再重建一遍。门禁失败返回 **409**，不提供上一版可用包。

**建议**：把「基线就绪」和「客户包就绪」拆开。审计+工单在就标 `done`，交付失败记 `delivery_error` 并另开 deliver 任务。下载优先打已有目录的 zip；重建失败返回 last-known-good，并带 `X-CiteAura-Delivery-Readiness: last_known_good`。

---

## 4. P1 产品设计缺口

### 4.1 Overview 不是报告，是零件堆

**文件**：`web/app/views/overview.js:50-116`；`api/adapters/report_quality.py:54-81`

创建后首屏：四个 Unmeasured KPI + 「View Delivery Pack」。`report_quality`（完整度、置信度、缺失项、跳转）只在 Delivery 页露出一条标签。

诊断路由还指错页：

- `sampling_missing` → `automation`（应为 engines）  
- `playbook_missing` → `automation`（应为 plan）

「Active Engines」用的是报告里已出现的引擎数，配了 5 把 Key 只采到 1 个会显示 `1`。

**建议**：Overview 做成状态机：需要 Key → 采样 → 审事实 → 执行工单 → 验收 → 交付。清单直接用 `report_quality.issues`。交付按钮在 `effective_report` 之前降为次要。

---

### 4.2 建设地图在引擎里，产品里看不见

**文件**：`web/app/app.js:32-44`；`web/app/views/gaps.js:14-32`；`engine/scripts/geo.py:207-208`

`cmd_autopilot` 会跑 `blueprint.build()`。`web/app` 对 `blueprint` **零引用**。Diagnosis 的 Gaps 是 Framing（描述词云，PRD P1-03），不是站点缺口，也不是 19 渠道地图。代理商要讲的「该去哪些渠道、覆盖了没有」只活在 zip 的 `06-Build-Map` 里。

**建议**：Diagnostics 下增加 Blueprint 页（优先级、覆盖、自动/人工）。Framing 改名放到 Monitor。

---

### 4.3 题库、竞品、拓词停在「能存」

| 能力 | 现状 | 应该长什么样 |
|---|---|---|
| 题库 | 只能追加；不显示 ID/来源；手写题也标 `source: "expand"` | 编辑、删除/停用、分组；显示 `q00N` |
| 拓词 | `GET /expand` 闲置 | 候选队列，确认后入库 |
| 人工采样表 | `POST /samples/import` 闲置 | Engines/Settings 提供导入，补 ChatGPT Search / Claude Web |
| 竞品 | 手工增删；用户添加直接 `confirmed` | 用 `competitor_discovery`：候选 / 已确认 + 分引擎提及率 |
| Playbook | 接口闲置 | Plan 默认用 playbook 排序 |

---

### 4.4 引擎矩阵不完整，落地页口径过满

**文件**：`web/app/views/engines.js:78-112, 163`；`api/adapters/engine.py:35-41`；`web/index.html:446-500`；`engine/scripts/sample.py:809`

- 表格只列本轮已有样本的引擎；未配、已配未测、全失败的都会消失，违反「未测显示 Unmeasured、不显示 0%」  
- `_product_report` 已算 `citation_share`，表上没有这一列  
- `median_rank === 0` 被当成 Unmeasured  
- 原始回答先拼进 HTML 再经 `setSafeHtml()` 挂载（`engines.js:163` + `safe-html.js:27`）。脚本、`style`/`iframe`、事件属性和危险 URL 会被清掉，**源码不能证明可直接执行脚本**；`form` 等标签仍可通过，属于不受信任 HTML / UI 注入。Facts / Site Audit 已 `escapeHtml`，回放应对齐  
- SaaS 可配引擎只有 gemini / openai / claude / grok / perplexity。落地页仍写 DeepSeek / Qwen / Kimi / GLM，并把 Gemini / GPT 标成 Web-grounded。约束 #7 禁止这种暗示

`searched` 缺省会回落到 provider 目录的 `search: True`（`sample.py:809`），参数化回答可能被标成「API·联网检索」。

**建议**：矩阵 = 已配 Key ∪ 内置引擎 ∪ 人工端。行状态 Measured / Unmeasured / Failed。模式只看本行是否真的 search。落地页引擎列表与 BYOK 矩阵一致；Gemini/OpenAI/Claude/Grok 标模型知识，仅 Perplexity 标联网。

---

### 4.5 导航比主路径宽太多

**文件**：`web/app/app.js:12-88`

6 轨 24 个视图把 Publishing、Outreach、Archive、SSO、White-label 和主路径放在同一级。Onboarding 不是 TRACK 项，`#/onboarding` 会高亮 Overview。登录后有 `citeaura_pending_domain` 也不会进建项页。

建议默认 IA：

```
Overview          就绪度 + 一句话结论 + 下一步
Visibility        分引擎 / 原始回答 / 引用域 / 竞品份额
Diagnostics       站点审计 / 题库与事实 / 建设地图
Execution         工单（矩阵+列表）/ 验收
Delivery          交付包 + 白标（Agency）
Settings          Key、调度、成员、账单、发布、外联、归档
```

Publishing / Outreach 进 Settings 或 Agency 开关。MVP 写明「不做自动发布」，却在执行轨占两个一级入口。

---

### 4.6 其它会卡住人手的 UX

| 问题 | 位置 | 影响 |
|---|---|---|
| 任务结束整页 `renderApp()` | `app.js:577-588` | Facts / Assets / 设置未保存内容被冲掉 |
| `projects.get` 失败一直转骨架 | `overview.js:46-47` | 没有重试，也回不到「添加品牌」 |
| 重新审计吞掉结果 | `siteaudit.js:179-184` | 按钮像坏了 |
| 空状态 CTA 用 `setTimeout(0)` 绑事件 | `empty.js:15-20` | 与 `setSafeHtml` 竞态，经常点不了 |
| 发布页 catalog 教把密钥写进 URL | `en.json` `publishing.tip_body` | `t()` 优先目录，覆盖页面里正确的 fallback |
| 调度 catalog 声称会自动 verify | `en.json` vs `automation.js:31` | 目录赢，文案不诚实 |
| Workbench 打出中文模式原文 | `workbench.js:35` | 英文产品里中英混用 |
| 落地页假扫描后标 WORKSPACE READY | `web/assets/landing.js:404-438` | 预览被说成真实工作区 |
| 进度 `progress \|\| 45` | `app.js:552` | 0 被吞，假显示 45% |
| Assets 空态没有「生成」按钮 | `assets.js:26-30` | generate 只能靠 Autopilot |
| Sample 按钮不做预估/Key 检查 | `engines.js` / `channels.js` | 只有 Autopilot 有成本确认 |
| 仅 Overview 会把「无问题」导去题库 | `overview.js:304-307` | 引擎页只 toast |

---

## 5. 计费、调度与可靠性（影响钱和信任）

### 5.1 试用口径三套

**文件**：`api/billing/limits.py:16-17, 120-145, 185-188`；`api/billing/plans.py:10`；`web/app/views/billing.js:125-126`

- 强制执行：终身 2 次/项目、工作区 6 次（3×2）  
- `/usage`：当月 Job 计数；不返回终身 6  
- `PLANS["trial"]["sample_runs"] = 2` 未被 `check_sample_run` 使用  
- 账单 UI 只显示项目数  

用户以为是每月额度，第三个项目第一次采样会被拒。

### 5.2 资金故事不闭合

- 创建/调度/`task_pipeline` 的 autopilot：`allow_pool=False`  
- Overview 预估默认按池报价  
- 只有 `POST .../sample` 做预算预留。正常收尾时 `_funded_engine_context` 的 `finally` 会 `record_usage`；无有效调用则预留标 `released`（`api/worker/tasks.py:316-355`，`api/billing/platform_pool.py:251-257`）。计量连续失败才写入 outbox，预留进入 `review`（`platform_pool.py:304-307`）。**不是所有失败任务都会泄漏额度**；风险是数据库持续故障、outbox 长期对不上时，`review` 预留一直占预算，`pause_on_budget_exceeded` 默认 true 可能误暂停项目  
- 套餐满员时 `check_project_creation` 在归档复用之前执行，同 slug 无法重新激活  

### 5.3 Worker

- `_job_status` 已捕获 `BaseException` 并回写失败（`api/worker/tasks.py:561`）；`_reclaim_stale_jobs` 会回收超过 2 小时仍 `queued`/`running` 的 Job（`tasks.py:376`）。硬超时本身不是「任务永远卡死」。  
- **P1 可靠性/成本**：`time_limit=3600` + `reject_on_worker_lost` 会让 broker 重投同一任务；认领把状态打回 `queued` 并刷新 `started_at`，2 小时回收对反复重投可能够不着。没有明确 `attempt` 上限、退避和告警，长采样可能整管线重跑再烧 BYOK / 平台池。应补 attempt 上限 + 退避 + 告警，不要按 P0 致命缺陷排期。  
- 调度不看 `Tenant.status == "active"`，禁用租户仍 cycle  
- `quota_blocked` 不推进 `schedule_next_run_at`（测试还锁死了这个行为），Beat 每 60s 空转  
- `_engine_keys` 吞 DB 错误返回 `{}`，`inject_keys({})` 会抹掉进程内全部引擎环境变量；verify/deliver 会在「无 Key」状态下跑完  

### 5.4 其它

- 并发创建同 slug 撞 `uq_projects_tenant_slug` 变成 500，只映射了 `uq_jobs_project_active`  
- Retry 的 `ValueError`（缺 `archive_id` 等）被报成 503 worker_unavailable  
- `GET /billing/usage` 每次 UPSERT  
- 双 Tab 同时 refresh 会把另一方判成 reuse，整家会话被踢  
- API 进程 `_CONTEXT_LOCK` 包住整个引擎调用，下载重建会堵住同副本上其他租户的工单写入  

---

## 6. 已经值得保留的设计

- 采样模式有统一后端（`sampling_modes.py`）和 badge；有样本时 Overview / Engines 会标。不要拆掉。  
- Autopilot 有成本确认，方向对，应推广到所有烧 Key 的动作。  
- 交付 readiness（customer-ready / review）和 facts 审批门禁，适合代理商。  
- 任务认领、试用创建检查、usage outbox、refresh family、Key finally 恢复、CI 先测试再部署：相对上次审查明显补强。  
- 无构建 SPA + 自托管字体，匹配「单节点可演示」。不要为了组件库重写前端。  
- `report_quality` 在样本不足、平台不足时拒绝全球结论（20 样本 / 2 平台），诚实边界的后端已经在了。  
- `preserve_manual_tickets` 让用户自建工单能熬过再跑 Autopilot。

---

## 7. 优化建议（按对成交和留存的影响）

### P0 — 让第一次成功跑通

1. 修正接入开关；创建前跑 preflight（注意 301/HTTPS 跳转不要误判未就绪）。  
2. 没有采样能力不要假装在测 AI。两步：URL →「配一把 Key / 开池」或「只出站点审计」。  
3. Overview 消费 `report_quality`，做成可点击缺口清单；修正错误 route。  
4. 工单矩阵/详情对齐 `priority`/`effort`/`why`；用 `/playbook`。  
5. 实现 `pages.applicable:*`，否则不要宣传自动验收。  
6. 本轮采样成功才写 provenance；Rerun Autopilot 与创建路径同一套成功定义。  
7. 接入成功与客户包门禁解耦。  
8. 采样回放、题目标题、竞品名按文本转义（防 UI 注入，不是已确认 XSS）。

### P1 — 让闭环可执行

9. 验收工作台：单票判定、证据、reopen 原因；manual 确认。  
10. Blueprint 页；Gaps 改名。  
11. 题库 CRUD + 拓词确认 + 工单问题选择器。  
12. 引擎表展示未测/失败/引用份额；Sample 预估+缺 Key 跳转。  
13. 竞品候选确认 + 提及份额。  
14. 下载打已有包；生成打开 telemetry。  
15. 账单展示终身/当月/每项目剩余次数。  
16. 任务结束不要整页 remount 编辑器。  
17. Celery 重投加 attempt 上限、退避和告警（硬超时是成本/可靠性风险，不是任务永不回收）。  
18. 预算：关注 `review` 预留的对账超时，而不是假设所有失败任务都泄漏额度。

### P2 — 代理商交付与收口

19. 收导航，P1/P2 降到 Settings / Agency。  
20. 人工采样表导入。  
21. 趋势旁注：单轮是观察值，连续两轮同向才标趋势（PRD §9，未落地）。  
22. Delivery 与 Visibility Report 拆开。  
23. 落地页、PRD §5.1、`tasks.md` 与实现对齐：英语优先、5 个可配引擎、Starter/Pro/Agency 美元价。不要再写未实现的中英日切换。  
24. 调度跳过禁用租户；quota_blocked 推进 next_run 并展示原因。  
25. Key 加载失败就失败任务，禁止 `inject_keys({})`。

---

## 8. 建议落地顺序

| 阶段 | 目标 | 验收 |
|---|---|---|
| 本周 | 接入字段、preflight、工单矩阵/详情、Overview 清单、采样转义、verify checker、采样 provenance | 无 Key / 有 Key / 勾选跳过采样 三条路径都不翻车；工单不再全进 Deprioritize；页面工单 verify 能自动通过或明确标人工 |
| 下周 | 验收工作台、题库编辑、问题选择器、Sample 预估、引擎未测行、交付不 409 | Demo：改一票技术工单 → verify 看到通过；Offsite 能选题创建；未配引擎显示 Unmeasured |
| 再一周 | Blueprint、竞品份额、收导航、试用额度展示、调度收口、Celery attempt 上限、outbox `review` 对账告警 | 代理商能在产品里指着渠道地图和竞品表讲交付，而不只打开 zip |

---

## 9. 问题索引

严重度：`bug` = 正确性/信任/钱；`suggestion` = 功能设计；`nit` = 小体验。

### Bug

| # | 文件 | 一句话 |
|---|---|---|
| 1 | `web/app/views/onboarding.js:94` | 跳过采样勾选发送 `skip_llm` |
| 2 | `api/projects/router.py:724` | 无 Key 静默跳过推理和采样，无引导 |
| 3 | `web/app/views/plan.js:35` | 2×2 全进 Deprioritize |
| 4 | `web/app/views/plan.js:233` | 详情读 `desc`，备注数组被字符串化 |
| 5 | `web/app/views/plan.js:303` | Offsite 要隐藏的问题 ID |
| 6 | `api/adapters/action_scope.py:239` + `engine/scripts/verify.py:201` | `pages.applicable:*` 未知，自动验收失效 |
| 7 | `api/worker/tasks.py:641` | 先记采样再检查，旧报告冒充本轮 |
| 8 | `api/worker/tasks.py:152` | Rerun Autopilot 不要求本轮样本 |
| 9 | `api/worker/tasks.py:638` | 交付门禁失败整次接入失败 |
| 10 | `api/projects/router.py:1648` | 下载重建失败 409，不给旧包 |
| 11 | `api/billing/limits.py:120` | 试用终身限额 vs 当月展示 |
| 12 | `api/billing/platform_pool.py:304` | 计量失败时预留进 `review`；DB/outbox 长期对不上才占额度，不是所有失败都泄漏 |
| 13 | `api/worker/celery_app.py:20` | **P1**：硬超时重投刷新 `started_at`，缺 attempt 上限，可能重复采样烧费用 |
| 14 | `api/projects/router.py:699` | 满额无法重新激活归档项目 |
| 15 | `api/worker/tasks.py:743` | 调度忽略禁用租户 |
| 16 | `api/worker/tasks.py:787` | quota_blocked 空转 |
| 17 | `api/worker/tasks.py:260` | Key 加载失败变成空注入 |
| 18 | `engine/scripts/sample.py:809` | `searched` 缺省用目录旗标 |
| 19 | `web/app/views/engines.js:78` | 未测引擎消失；`rank===0` 当未测 |
| 20 | `web/index.html:446` | 落地页引擎/联网口径不诚实 |
| 21 | `web/app/views/overview.js:46` | get 失败无限骨架 |
| 22 | `web/app/app.js:577` | 任务结束 remount 冲掉编辑器 |
| 23 | `web/app/views/siteaudit.js:179` | 重审无反馈 |
| 24 | `web/app/views/engines.js:163` | 回放为不受信任 HTML/UI 注入（已经过 `setSafeHtml`，非已确认 XSS） |
| 25 | `api/i18n/messages/en.json` `publishing.tip_body` | 教把密钥写进 URL |

### Suggestion

| # | 文件 | 一句话 |
|---|---|---|
| 26 | `web/app/views/overview.js:36` | 不用 `report_quality` |
| 27 | `api/adapters/report_quality.py:60` | 下一步 route 指错页 |
| 28 | `web/app/views/verify.js:32` | 无单票 before/after、无人工确认 |
| 29 | `web/app/app.js:32` | 无 Blueprint；Gaps 是 framing |
| 30 | `web/app/views/onboarding.js:100` | preflight 未调用 |
| 31 | `web/app/views/questions.js:73` | 题库只增；拓词/导入无 UI |
| 32 | `web/app/views/competitors.js:64` | 无发现确认、无提及份额 |
| 33 | `web/app/app.js:12` | 24 视图把 P1/P2 当 P0 |
| 34 | `web/app/views/engine-settings.js:10` | 仅 5 引擎；平台池/预算无 UI |
| 35 | `web/app/views/report.js:166` | 生成交付无 telemetry |
| 36 | `web/app/components/empty.js:15` | 空态按钮竞态 |
| 37 | `api/projects/router.py:1116` | Retry ValueError 报 503 |
| 38 | `api/main.py:131` | 同 slug 唯一约束变 500 |
| 39 | `api/adapters/preflight.py:69` | 301 当站点未就绪 |
| 40 | `api/adapters/engine.py:33` | API 进程全局锁包住整段引擎 |

### Nit

| # | 文件 | 一句话 |
|---|---|---|
| 41 | `web/app/i18n.js:6` | 仅 en；tasks.md 仍写中英日 |
| 42 | `web/app/app.js:552` | 进度 0 显示 45% |
| 43 | `api/adapters/delivery.py:808` | CSV「受影响页面」写的是数量 |
| 44 | `api/auth/router.py:171` | 注册 409 可枚举邮箱 |
| 45 | `api/auth/router.py:316` | 双 Tab refresh 互踢 |
| 46 | `api/billing/limits.py:20` | GET usage 带写 |
| 47 | `web/app/views/plan.js:51` | 写死「13 张标准工单」 |

---

## 10. 结论

CiteAura 作为引擎包装已经超过「30 天 MVP」的模块清单。作为可售产品，默认路径还不成立：

- 接入会走错开关、跳过引导  
- 报告页不是报告  
- 工单矩阵是错的  
- 自动验收对页面工单不工作  
- 交付门禁能把一次本来成功的审计判失败  

先把 **接入 → 可见性 → 工单 → 验收** 四段接到同一套数据契约上，再谈白标、外联和发布。那才是 PRD 里「填一个域名，自动出报告 + 工单 + 验收 + 交付包」这句话。

---

## 附录 A：复核后收窄的表述

| # | 首版问题 | 修订后 |
|---|---|---|
| 1 | 「工作树干净，无未提交改动」未标时间 | 代码审查时 HEAD `fe0decc` 工作树干净；本文件写入后为未跟踪文件。见文首检查时间。 |
| 2 | 易被读成创建项目缺少出网/SSRF 校验 | `create_project` 已 `validate_outbound_url()`（`router.py:694`）。缺口是完整 preflight（可达性、TLS、首页）和平台池采样能力识别。 |
| 3 | 「失败任务不释放预留，空跑也能暂停项目」过宽 | `finally` 会计量；无有效调用标 `released`。连续计量失败才进 `review`。泄漏场景是 DB/outbox 长期对不上，不是所有失败。 |
| 4 | 采样回放易被读成已确认 XSS | 内容经 `setSafeHtml()`，脚本与危险 URL 被清。定性为不受信任 HTML/UI 注入；仍应统一转义，但直接脚本执行未被源码证明。 |
| 5 | Celery 硬超时写得像任务永不回收 | 已捕获 `BaseException`，并回收超期 queued/running。broker 重投刷新 `started_at` 且无 attempt 上限，属 P1 可靠性/成本，应补上限、退避和告警。 |
