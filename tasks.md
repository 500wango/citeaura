# CiteAura 开发任务清单

每条任务有明确的输入、输出和验收标准。按顺序执行，后一条依赖前一条。

---

## Phase 1: 基础骨架（W1）

### Task 1.1: 项目初始化

**输入**：空的 `api/` 目录  
**输出**：可运行的 FastAPI 项目骨架  

- 创建 `api/main.py`（FastAPI app，含 health check `/api/v1/health`）
- 创建 `requirements.txt`（fastapi, uvicorn, sqlalchemy, alembic, celery, redis, pyjwt, cryptography, psycopg2-binary, pydantic, python-dotenv）
- 创建 `docker-compose.yml`（postgres:15, redis:7, api service, worker service）
- 创建 `.env.example`（DATABASE_URL, REDIS_URL, JWT_SECRET, AES_KEY）
- 创建 `Makefile`（targets: dev, test, migrate, worker）

**验收**：`docker-compose up` 后 `curl localhost:8000/api/v1/health` 返回 `{"status":"ok"}`

---

### Task 1.2: 数据库 + Alembic

**输入**：Task 1.1 完成  
**输出**：数据模型 + 初始迁移  

- 创建 `api/db.py`（engine, SessionLocal, Base）
- 创建 `api/models.py`（Tenant, User, Membership, Project, ApiKey, Job, Subscription, UsageCounter）
- 配置 Alembic（`alembic.ini` + `api/migrations/`）
- 生成并应用初始迁移

**验收**：`alembic upgrade head` 成功，表结构与 AGENTS.md 数据模型一致

---

### Task 1.3: Auth 模块

**输入**：Task 1.2 完成  
**输出**：注册/登录/鉴权  

- 创建 `api/auth/router.py`：
  - `POST /api/v1/auth/register` → 创建 user + 默认 tenant（7天试用）+ membership(owner)
  - `POST /api/v1/auth/login` → 返回 JWT access_token + refresh_token
  - `GET /api/v1/me` → 当前用户信息 + tenant
- 创建 `api/auth/deps.py`：`get_current_user` 依赖（JWT 验证）
- 创建 `api/auth/security.py`：密码 hash（bcrypt）、JWT 签发/验证

**验收**：注册 → 登录 → 用 token 访问 /me → 返回用户信息

---

### Task 1.4: 适配层

**输入**：Task 1.1 完成  
**输出**：`api/adapters/` 使引擎模块可在 worker 中安全调用  

- 创建 `api/adapters/__init__.py`
- 创建 `api/adapters/engine.py`：
  - `patch_die()`：monkey-patch `geolib.die` → raise `GeoEngineError`
  - `patch_paths(tenant_slug, project_slug)`：设置 `geolib.WORK = WORK_ROOT / tenant_slug`
  - `inject_keys(keys: dict)`：临时注入 `os.environ`，用完恢复
  - `with_tenant_context(tenant_id, project_slug)` context manager：组合以上三步
- 创建 `api/adapters/exceptions.py`：`GeoEngineError(message)`

**验收**：
```python
with with_tenant_context("test-tenant", "example"):
    import geolib as G
    assert "test-tenant" in str(G.WORK)
    try:
        G.die("test error")
    except GeoEngineError:
        pass  # 不会 sys.exit
```

---

### Task 1.5: Celery Worker + 第一个任务

**输入**：Task 1.4 完成  
**输出**：异步任务可执行 bootstrap 流程  

- 创建 `api/worker/celery_app.py`（Celery 实例，broker=redis）
- 创建 `api/worker/tasks.py`：
  - `task_bootstrap(tenant_id, project_slug, skip_llm=False)`
  - `task_sample(tenant_id, project_slug, limit=None)`
  - `task_cycle(tenant_id, project_slug)`
  - `task_verify(tenant_id, project_slug)`
  - `task_deliver(tenant_id, project_slug)`
- 每个 task 内部：`with with_tenant_context(...)` → import 对应模块 → 调用 run()
- Job 状态回写 DB（started_at, finished_at, status, error）

**验收**：Celery worker 启动无报错；`task_bootstrap.delay("t1", "test")` 投递成功并在 worker 中执行（可用 `--skip-llm` 跳过 LLM 调用）

---

### Task 1.6: Project CRUD + Bootstrap 流程

**输入**：Task 1.3 + 1.5 完成  
**输出**：创建项目自动触发 bootstrap  

- 创建 `api/projects/router.py`：
  - `POST /api/v1/projects` { url } → 创建 DB 记录（全引擎范围）→ 调引擎 `geo.cmd_init()` → 触发 Celery `task_bootstrap` → 返回 `{project_id, job_id}`
  - `GET /api/v1/projects` → 列表（当前 tenant）
  - `GET /api/v1/projects/:id` → 详情（复用 `dashboard.project()` 逻辑）
  - `GET /api/v1/projects/:id/jobs` → 任务历史
  - `GET /api/v1/projects/:id/jobs/:jid` → 任务状态 + 日志
- 租户隔离：所有查询过滤 `tenant_id = current_user.tenant_id`

**验收**：`POST /projects {url: "https://example.com"}` → 返回 project + job_id → 轮询 job 状态变为 done → `GET /projects/:id` 返回品牌信息和问题库

---

## Phase 2: 核心功能（W2）

### Task 2.1: API Key 管理

- `PUT /api/v1/settings/keys` { engine_code, key_value } → AES-256-GCM 加密存到 DB
- `GET /api/v1/settings/keys` → 返回已配引擎列表（不返回明文，只返回 engine_code + masked）
- `DELETE /api/v1/settings/keys/:engine_code`
- 适配层 `inject_keys` 从 DB 解密并注入

**验收**：配了 DEEPSEEK_API_KEY 后，sample 任务能成功调用 DeepSeek

---

### Task 2.2: Sample + Report API

- `POST /api/v1/projects/:id/sample` { limit?, platforms? } → 触发 Celery task → 返回 job_id
- `GET /api/v1/projects/:id/report` → 返回最新 report 数据（从 metrics/*.json 读）
- `GET /api/v1/projects/:id/engines` → 分引擎指标（mention_rate, rank, citations）
- `GET /api/v1/projects/:id/samples/:date` → 原始答案列表（raw answer 回放）

**验收**：配了至少一个 Key → sample 完成 → report 返回分引擎 mention_rate

---

### Task 2.3: Tickets + Verify API

- `GET /api/v1/projects/:id/tickets` → 工单列表（从 tasks.json 读）
- `PATCH /api/v1/projects/:id/tickets/:tid` { status, note } → 调 `tasks.set_status()`
- `POST /api/v1/projects/:id/verify` → 触发 Celery task → 返回 job_id
- `GET /api/v1/projects/:id/verify/history` → 验收历史列表

**验收**：verify 完成后，之前标 todo 的技术工单若条件满足自动变 done；手动改 done 再 verify 可回归 reopen

---

### Task 2.4: Delivery API

- `POST /api/v1/projects/:id/deliver` → 触发 Celery task → 返回 job_id
- `GET /api/v1/projects/:id/deliveries` → 交付历史（日期列表）
- `GET /api/v1/projects/:id/deliveries/:date` → 下载 zip

**验收**：deliver 完成后，下载 zip 包含 index.html + 01~06 文档 + assets/

---

## Phase 3: 计费 + 部署（W3-W4）

### Task 3.1: 试用限额

- 中间件检查：试用期内 projects ≤ 3，sample_runs ≤ 2/project
- 超限时 API 返回 `403 {"error": "trial_limit_exceeded", "detail": "..."}`
- `GET /api/v1/billing/usage` → 当前用量

**验收**：试用用户第 4 个项目创建失败；第 3 次 sample 被拒

---

### Task 3.2: 订阅骨架

- `POST /api/v1/billing/subscribe` { plan } → 升级 tenant.plan
- `GET /api/v1/billing/plans` → 可用套餐列表
- 升级后限额放开
- 支付集成（Stripe 或支付宝）可先 mock，只要接口协议对

**验收**：subscribe 后 plan 变为 pro，限额放开

---

### Task 3.3: Docker 生产部署

- `Dockerfile`（multi-stage：api + worker）
- `docker-compose.prod.yml`（加 nginx 反代 + HTTPS）
- `scripts/deploy.sh`（一键部署到 VPS）
- `.env.production.example`

**验收**：`docker-compose -f docker-compose.prod.yml up` 在全新 VPS 上可跑通完整 demo 流程

---

## Phase 4: 前端（统一 SPA 与落地页重构）

### Task 4.1: 落地页与设计系统重构

- 落地页 `web/index.html`：Space Grotesk + OKLCH Teal 主色 + 4/16/36 节奏
- 自托管字体与图标：`web/assets/fonts/`、`web/assets/icons/`（零外部 CDN 依赖）
- 三种采样方式明确标注（API·参数化知识 / API·联网检索 / 人工·产品端）
- 英语产品文案与目录（`api/i18n/messages/en.json`）；其他语言尚未作为产品开关交付

### Task 4.2: 统一 SPA 架构与 6 轨道导航

- 创建 `web/app/` 原生 ES Modules SPA 架构（挂载 `/app`，零构建步骤）
- 6 轨道全局导航（概览 / 监测 / 诊断 / 执行 / 交付 / 管理）
- 24 个业务视图与 5 个认证视图（登录、注册、找回密码、重置密码、接受邀请）
- 组件库原语（Toast, Modal, Badge, KPI, Table, Tabs, Empty, Skeleton）

### Task 4.3: 强类型 API 客户端与多语言引擎

- `web/app/api.js` 统一封装 ~90 个 API 端点，支持凭证鉴权与 401 自动刷新
- `web/app/i18n.js` 多语言解析引擎，支持点路径 key 解析与 en 兜底

### Task 4.4: 闭环验证与清退旧注入

- 清退 `api/ui.py` 中 3300+ 行旧 monkey-patch，瘦身为标准 SPA 静态伺服与 `/files` 交付下载
- 更新 `api/tests/test_ui.py`，完整 API 与 engine 回归测试保持 100% 通过

**验收**：浏览器打开 `/app` 呈现现代化精密仪器级 GEO 控制台，所有测试全绿通过

---

## 执行注意事项

1. 每完成一个 Task，运行 `cd engine && python3 -m unittest discover -s tests` 确保引擎测试不被破坏
2. 每个 Task 独立提交，commit message 格式：`feat(module): 描述`
3. 引擎通用缺陷可在 `engine/` 修复；租户、计费、认证等 SaaS 专属逻辑必须留在 `api/adapters/`
4. 所有异步操作返回 `job_id`，前端通过轮询 `/jobs/:jid` 获取进度
5. 错误处理：引擎的 `GeoEngineError` 在 API 层转为 HTTP 400/500 + JSON body

---

## Phase 5: AI Visibility Operating Plan（Semrush playbook 融合）

目标：把现有的事实库、站点审计、AI 采样、工单、验收和交付包串成一条有目标、有阶段、有证据的持续运营流程。此阶段不新增泛化的 AI 写作器，也不承诺排名、流量或收入增长。

### Task 5.1: 统一基线与目标合同（P0）

**状态：已完成（2026-08-27）**

**输入**：现有 report、engines、samples、facts、siteaudit、verify history

**输出**：项目级 `visibility_plan` 元数据和基线快照

- 新增计划字段：`status`、`current_phase`、`started_at`、`next_review_at`、`goals[]`
- 目标类型限定为：`mention_rate`、`citation_rate`、`accuracy`、`crawler_access`、`ticket_completion`
- 每个目标必须记录指标定义、目标值、基线值、样本量、采样模式和测量时间
- DB 只保存计划/目标/周期元数据；详细样本、证据和历史快照继续写入 `work/<tenant>/<slug>/`
- API：`GET/PUT /projects/:id/visibility-plan`、`POST /projects/:id/visibility-plan/baseline`
- 前端：在 `overview` 增加目标卡和阶段进度，在 `report` 增加基线对比

**验收**：无样本时显示 `未测` 而不是 `0`；不同采样模式不可直接混算；同一基线重复提交具备幂等性。

### Task 5.2: Citation Readiness 诊断（P0）

**状态：已完成（2026-08-27）**

- 汇总现有 `siteaudit`、facts、schema、抓取和采样证据，生成分项 readiness：`crawlability`、`extractability`、`answerability`、`fact_consistency`、`citation_evidence`
- 每个分项必须关联证据文件、URL、检查时间和修复建议
- 诊断结果映射为现有 tickets，复用优先级、状态、verify 和 timeline
- API：`GET /projects/:id/citation-readiness`
- 前端：新增 `readiness` 视图或嵌入 `siteaudit`，不要再造第二套工单系统

**验收**：每个扣分项可追溯到证据；重复运行不会生成重复工单；验证后能自动更新状态。

### Task 5.3: AI Crawler 与页面提取检查（P0）

**状态：已完成（2026-08-28）**

- 检查 robots.txt、llms.txt、noindex、canonical、HTTP 状态、关键页面可提取文本和 schema
- 区分“不可抓取”“可抓取但不可提取”“可提取但缺少可引用答案”
- 将检查纳入 preflight/siteaudit，不依赖 LLM Key
- 增加采样/检查来源标签：`人工·产品端` 或对应 API 模式

**验收**：同一 URL 的 DNS/HTTP 检查复用现有网络保护；失败结果包含明确原因，不把网络错误解释为 AI 不提及。

### Task 5.4: 品牌事实冲突与内容机会（P1）

**状态：已完成（2026-08-27）**

- 从原始 AI 回答提取品牌描述，与 `Brand Fact Library` 比较
- 输出冲突类型：错误、过时、无来源、互相矛盾，并生成事实修正工单
- 从真实问题库、低引用问题和竞品差距生成内容机会
- 内容机会只输出问题、证据、建议页面类型和验收条件，不自动发布内容
- 前端复用 `facts`、`gaps`、`questions` 和 `blueprint` 视图

**验收**：每条机会至少关联一个真实问题或采样证据；缺少证据时显示“待验证”。

### Task 5.5: 六阶段运营时间线与周期复测（P1）

**状态：已完成（2026-08-28）**

- 阶段：基线、抓取与技术、页面可引用性、内容、站外实体、复测
- 每阶段包含目标、建议工单、完成条件、下一次复测日期
- 复测沿用现有 automation、sample、verify 和 job monitor
- 报告增加前后对比、变更记录、样本量和未归因声明

**验收**：用户可以从一个计划进入工单、触发复测、查看变化并生成交付包；任何阶段都可暂停，不影响现有手动流程。

### Task 5.6: 站外实体与结果归因（P2）

**状态：已完成代码合同与审核 UI（2026-08-28）；真实 GSC/GA4 拉取需客户授权后启用**

- 先做第三方品牌信息一致性清单和人工复核队列，再评估外部数据源连接器
- 接入 GSC/GA4 前先定义低敏字段、归因窗口和“相关但不等于因果”的文案
- 不把目录数量、外链数量或论坛发帖数量作为核心成功指标

**验收**：站外建议均有来源、相关性和审核状态；结果报表明确标注无法归因的部分。

### 实施顺序与发布闸门

1. 先完成 5.1，建立数据合同和基线快照。
2. 再完成 5.2、5.3，把诊断转成可验收工单。
3. 完成 5.4、5.5，形成内容机会和周期运营闭环。
4. 最后评估 5.6，必须先有真实客户数据再扩展归因和站外连接器。

每个 Task 必须通过 API/Engine 全量回归、文件系统产物校验、租户隔离测试和至少一个浏览器流程验收；不得修改 `engine/` 公共接口。

---

## Phase 6: Search Console 真实需求钩子

目标：用户连接 Google Search Console 后，把近 90 天 Google 展示量最高的非品牌查询转成 AI 采样问题，报告并列展示 Google 需求与 AI 可见性。方案见 `docs/gsc-ga4-evidence-layer-plan.md`（v2）。不改 `engine/`，不保存 Google 凭据，证据层永不接入百度。

### Task 6.1: OAuth 一次性授权（P0）

**状态：已完成代码与测试（2026-10-30）；真实 Google 授权待 OAuth Client 配置后验收**

- `api/searchdata/oauth.py`：授权 URL（PKCE S256 + 签名 `state`，绑定用户、租户、项目，10 分钟有效）、回调换 token
- 只申请 `webmasters.readonly`，不申请 offline access；access token 只在回调请求内使用，不落库、不写日志
- 配置 `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET`；未配置时接口返回 `gsc_not_configured`，前端隐藏入口

**验收**：`state` 篡改、过期、跨用户使用、PKCE 校验失败、用户拒绝授权都返回明确错误；token 不出现在数据库、日志和快照中。

### Task 6.2: 属性匹配与查询拉取（P0）

**状态：已完成代码与测试（2026-10-30）；真实 Google 授权待 OAuth Client 配置后验收**

- `api/searchdata/gsc.py`：`sites.list` 按 `sc-domain:` → `https://` → `https://www.` → `http://` 匹配项目域名；排除 `siteUnverifiedUser`
- 多个匹配或无匹配时返回可选属性列表，由用户选择后用同一 token 拉取（token 仅缓存在服务端短期会话内，5 分钟过期，不写磁盘）
- `searchanalytics.query`：结束日 T-3，往前 90 天，`dimensions=["query"]`，`type=web`，`dataState=final`，`rowLimit=25000`；另取不分维度的总量计算匿名缺口

**验收**：domain 属性、URL 前缀属性、www 变体、无匹配、多个匹配均有测试；HTTP 错误映射为 `gsc_permission_denied` / `gsc_upstream_error`。

### Task 6.3: 候选筛选与快照落盘（P0）

**状态：已完成代码与测试（2026-10-30）；真实 Google 授权待 OAuth Client 配置后验收**

- `api/searchdata/candidates.py`：排除品牌词（品牌名、别名、域名标签）；排除过短查询；意图词优先；按展示量取前 20；问句原样使用，其他查询给模板改写
- 快照写入 `work/<tenant>/<slug>/searchdata/gsc_snapshot.json`，旧快照移入 `searchdata/history/`；只保留前 200 条查询
- 读取与删除接口；删除需要 editor 角色

**验收**：品牌词排除、短查询排除、意图排序、不足 20 条、0 条、匿名缺口（含总量为 0）都有测试；跨租户读取和删除被拒绝。

### Task 6.4: 问题库接入（P0）

**状态：已完成代码与测试（2026-10-30）；真实 Google 授权待 OAuth Client 配置后验收**

- 加入问题库时 `source: "gsc"`，附 `gsc` 元数据（查询原文、展示量、点击、平均排名、快照时间）
- 接口拒绝客户端伪造 `gsc` 元数据：服务端按快照中的查询回填
- 问题视图新增“从 Search Console 导入”卡片：候选列表、编辑、勾选加入；已有基线时提示新问题会开始新的可比周期

**验收**：加入后的问题带服务端回填的元数据；不在快照中的查询被拒绝；已在问题库中的不重复加入。

### Task 6.5: Onboarding 与报告（P0）

**状态：已完成代码与测试（2026-10-30）；真实 Google 授权待 OAuth Client 配置后验收**

- onboarding 选择“仅审计”创建项目后，若 GSC 已配置，提示“连接 Search Console 获取真实搜索问题”（可跳过）；已选完整基线的项目从问题视图手动导入
- 报告视图新增“真实需求”一节：每个 GSC 来源问题的 Google 展示量、点击、排名（标注 `GSC·第一方`、属性、拉取时间），以及最近一次采样中各引擎是否提及、提及的竞品（标注采样模式）
- 顶部汇总“在 N 个 Google 高展示问题里，AI 回答提到你的有 M 个”，以及匿名缺口说明；不并入 GEO 健康分

**验收**：没有 GSC 来源问题时不显示该节；数据少于 5 条与 0 条的提示正确；每个数字可对应到查询、属性、时间窗和拉取时间。

### Task 6.6: 合规、文案与埋点（P0）

**状态：已完成（2026-10-30）；Google OAuth 验证尚未提交**

- 隐私政策新增 Google 用户数据章节（Limited Use 声明、读取范围、保留与删除）
- 7 种语言文案；埋点 `gsc_connect_started`、`gsc_connect_completed`、`gsc_candidates_shown`、`gsc_questions_added`、`gsc_report_viewed`
- `.env.example` 新增 Google OAuth 配置

**验收**：i18n 全量测试通过；埋点事件进入白名单且不携带查询原文。

### Task 6.7: GA4 AI 引荐流量（P0）

**状态：已完成代码与测试（2026-10-30）；Consent screen scope 与 Analytics API 待线上验收**

- 复用同一个 Google OAuth Client 与回调地址，新增 `analytics.readonly`；state 带 flow，按 `gsc` / `ga4` 分流
- Analytics Admin API 列出属性，按 web stream `defaultUri` 匹配项目域名；exact 自动选中，parent 与多匹配交给用户选择
- Data API 拉 28 天 `sessionSource` 的 sessions / totalUsers / keyEvents，服务端按版本化 AI 域名表聚合；另拉全站 sessions 作分母
- 快照写到 `work/<tenant>/<slug>/searchdata/ga4_snapshot.json`，保留 5 份历史；GSC 与 GA4 删除互不影响
- 报告新增“AI 引荐流量”区块，标注 `GA4·第一方`、属性、窗口、抓取时间、域名表版本；不并入 GEO 健康分
- 项目设置新增连接 / 刷新 / 删除卡片；隐私政策新增 2.6 节并同步 6 个语言版本

**验收**：单匹配、多匹配、无属性、拒绝授权、scope 未授予、限流与跨租户路径均有测试；token 不出现在文件、日志、Redis；删除 GA4 后 GSC 快照仍在。

### Task 6.8: 运行中任务可取消（P0）

**状态：已完成代码与测试（2026-10-30）；浏览器与真实 worker 验收待跑**

- Job 新增终态 `canceled` 与 `cancel_requested_at` 标记列（迁移 `0045_job_cancel_request`）
- `POST /api/v1/projects/{id}/jobs/{job_id}/cancel`：排队中直接落终态并释放项目；运行中只写标记，由 worker 在 1 秒内自行停下
- 引擎子进程类任务终止整个进程组；交付包在 staging 内的阶段与产物检查点退出，正式交付包与历史包不受影响
- 取消后预算预留释放、项目回到 `ready`、可立即重试；陈旧回收器把已请求取消的失联任务落成 `canceled` 而不是 `failed`
- 顶栏进度胶囊新增停止按钮，日志弹窗新增取消入口与「已取消」状态；7 语言文案

**验收**：取消交付包构建后没有半个包落盘；取消采样后没有残留 `job_runner` 进程；取消后能立即重新入队；viewer 无法取消。

### Phase 6 发布闸门

1. 引擎测试全绿、API 全量测试通过
2. 用 citeaura.com 的 GSC 属性完成低数据量路径的浏览器验收
3. Google OAuth 同意屏幕确认 scope 分类后再提交验证；验证结果不阻塞上线
