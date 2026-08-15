# CiteAura 产品需求文档 PRD

> **版本**：v2.0  
> **定位**：面向出海企业与代理商的 Generative Engine Optimization (GEO) SaaS 交付平台
> **底层引擎**：开源 GEO 引擎（去品牌化，纯净单机版）
> **产品形态**：多租户 Web SaaS（FastAPI + Postgres + Redis + Celery + Docker）
> **产品目录**：`~/project/citeaura`
> **开发指令**：`AGENTS.md`
> **官网参考竞品**：https://www.higeo.ai/  
> **对比文档**：`higeo-vs-disvorai-comparison.md`  
> **约束**：**所有开发工作基于开源版二次开发**，禁止从零重写核心 GEO 管线；在其之上加多租户 SaaS、商业包装与 HiGEO 级体验。

---

## 0. 给实现者的硬约束

1. **开源代码已引入** `engine/`，180+ 项确定性测试全绿。SaaS 层须**调用或包装**现有模块。
2. **不要**用全新 stack 重写 sample/audit/plan/verify 逻辑，除非有测试证明行为等价且 PR 明确说明。  
3. SaaS 层（账号、计费、多租户、调度、API 网关）可新建，但须**直接 import** 现有 Python 模块（`geolib`、`sample`、`audit`、`tasks`、`verify`、`deliver` 等）。  
4. **SSOT 决策**：文件系统为管线 SSOT（`work/<tenant>/<slug>/`），Postgres 只存索引、元数据和账务。管线产物以 JSON/JSONL 文件为准，DB 存衍生视图，不双写。  
5. 指标诚实：未测显示 unmeasured，不伪造引擎覆盖。  
6. 中文优先文案可配置；引擎矩阵统一展示，不按国内/海外分类。
7. **API 采样 ≠ 用户端体验**：UI 中每个引擎必须标注采样模式（API·参数化知识 / API·联网检索 / 人工·产品端），不允许暗示 API 结果等同于用户在网页/App 上看到的答案。

---

## 1. 代码审查核心发现

### 1.1 开源已有能力（比 PRD v1.1 预估更强）

| 能力 | 实现位置 | 成熟度 | SaaS 可直接复用 |
|------|----------|--------|----------------|
| 域名一键建项 | `geo.py init / new` | 生产级 | ✓ |
| 官网抓取 + 正文抽取 | `crawl.py` + `geolib.py` | 生产级，含去重/限速/编码 | ✓ |
| LLM 自动推导品牌事实/竞品/问题库 | `bootstrap.py` | 生产级，含编造防线 | ✓ |
| 6 维页面体检（可计算分数） | `audit.py` | 生产级，每条规则可追溯到论文 | ✓ |
| 多引擎 API 采样（10+ 引擎） | `sample.py` | 生产级，并发+重试+增量落盘 | ✓ |
| 人工/浏览器采样导入 | `sample.py sheet/import` | 完整 | ✓ |
| 答案解析（提及/排名/引用/负面检测） | `sample.py analyze_answer` | 精细，含边界策略 | ✓ |
| 品牌认知 vs 可见性分离 | `sample.py aggregate` | 已实现 | ✓ |
| 结构化工单生成（含验收标准） | `tasks.py` | 生产级 | ✓ |
| 自动验收（16+ 种 checker 表达式） | `verify.py` | 生产级，含回归 reopen | ✓ |
| 客户交付包（6 份文档 + assets） | `deliver.py` | 生产级 | ✓ |
| 三份交付物（诊断/优化/执行）| `deliverables.py` | 完整 | ✓ |
| 资产生成（llms.txt/JSON-LD/片段/大纲/AI初稿） | `generate.py` | 完整 | ✓ |
| 编造检测（lint） | `generate.py lint_all` | 完整 | ✓ |
| 发布渠道（GitHub/WordPress/微信草稿/Webhook） | `publish.py` | 完整，强制人工确认 | ✓ |
| 建设蓝图（渠道覆盖+内容承接） | `blueprint.py` | 完整 | ✓ |
| 拓词（百度下拉/Google suggest） | `expand.py` | 完整 | ✓ |
| 后台任务管理（子进程隔离、日志、并发保护） | `jobs.py` | 生产级 | ✓ |
| 可观测看板（单页应用 + REST API） | `dashboard.py` + `ui.html` | 功能完整，2342 行前端 | 可嵌入 |
| 健康分（五项加权 GEO 分数） | `analytics.py` | 完整 | ✓ |
| 项目级文件锁 | `geolib.py project_lock` | 跨进程安全 | ✓ |
| 报告生成（HTML+MD） | `report.py` | 完整 | ✓ |

### 1.2 开源的架构特点（影响 SaaS 化方案）

1. **文件系统为中心**：所有状态在 `work/<slug>/` 下的 JSON/JSONL 文件中，无数据库依赖。  
2. **跨进程锁**：`geolib.project_lock()` 用 `fcntl.flock` 实现，**仅限单机**；分布式部署需替换为 Redis/PG 锁。  
3. **并发模型**：`sample.py` 用 `ThreadPoolExecutor`，平台间并发、平台内串行，设计合理。  
4. **LLM 调用链**：`sample.pick_llm()` 按 `deepseek → glm → doubao → openai → gemini` 优先级选最便宜的可用引擎。  
5. **每项目单任务**：`jobs.py` 限制同一 slug 同时只有一个后台任务（`_running` dict），天然防并发踩踏。  
6. **配置备份机制**：`save_config` 每次写入前备份，保留最近 10 份——多租户下需考虑存储膨胀。  
7. **`sys.exit` 调用**：`geolib.die()` 直接 `sys.exit(1)`，SaaS 包装时需替换为抛异常。

### 1.3 SaaS 化关键风险

| 风险 | 严重性 | 缓解方案 |
|------|--------|----------|
| `fcntl.flock` 仅限单机 | 高 | MVP 单节点部署；P1 引入 Redis 分布式锁 |
| `sys.exit` 导致 worker 进程退出 | 高 | 包装层 monkey-patch `die()` 为 raise |
| 环境变量管理 API Keys | 中 | 改为 per-tenant encrypted store，运行时注入 |
| `work/` 磁盘空间线性增长 | 中 | 对象存储归档 + 保留策略 |
| 无速率限制 | 中 | API 网关层加 rate limiter |
| 现有 UI 绑定 `localhost` | 低 | 前端重做；后端 API 可复用 |

### 1.4 引擎采样真实能力（修正 PRD v1.1 预期）

开源 `sample.py` 已支持的引擎及实际采样模式：

| 引擎 | API 可用 | 联网 | 采样代表性 |
|------|---------|------|-----------|
| DeepSeek | ✓ | ✗ | 参数化知识，≠网页端 |
| 智谱 GLM | ✓ | ✗ | 参数化知识，≠清言网页 |
| 豆包(方舟) | ✓ | ✓* | *需开通内容插件，否则降级 |
| Kimi | ✓ | ✗ | 参数化知识 |
| MiniMax | ✓ | ✗ | 参数化知识 |
| 纳米AI | ✗ | — | 仅人工采样 |
| 百度AI搜索 | ✗ | — | 仅人工采样 |
| Gemini | ✓ | ✗ | 无 grounding，≠AI Overview |
| OpenAI/ChatGPT | ✓ | ✗ | ≠ChatGPT网页Search |
| Claude | ✓ | ✗ | ≠Claude网页Web Search |
| Grok | ✓ | ✗ | ≠X内嵌Grok |
| Perplexity | ✓ | ✓ | 原生联网+citations，最高证据等级 |

**结论**：大部分引擎 API 采样的是"模型参数化知识中是否认识这个品牌"，而非"用户在产品端搜索时 AI 会不会推荐你"。仅 Perplexity 和开通了内容插件的豆包方舟能测到联网搜索行为。产品 UI 必须明确区分这两种信号。

---

## 2. 目标与非目标

### 2.1 目标（MVP 30 天可演示）

- 用户注册 → 只填**域名** → 自动 bootstrap → 看到 Visibility Report + Playbook  
- 可将 Playbook 项转为**工单**，执行后**自动验证**  
- 一键导出**客户交付包**  
- 所有项目统一覆盖全部已配置引擎，不提供国内/海外引擎范围选择
- 计费：强制 BYOK（用户自带 API Key）为默认模式；平台 Key 池为可选增值

### 2.2 非目标（MVP 不做）

- 保证 AI 一定提及品牌  
- 覆盖「所有」助手却不点名（禁止虚报）  
- 替用户全自动发布到全网无确认  
- 从零重写采样/审计算法  
- 微信公众号发布集成（P1）  
- WordPress 发布集成（P1）  
- 词云 framing（P1，非核心路径）  
- 竞品自动发现可视化（P1，逻辑已有）
- 传统 SEO 数据集成（Google Search Console、Semrush、TabAPI）；不纳入 GEO 核心评分与工作流

---

## 3. 用户与场景

### 3.1 角色

| 角色 | 诉求 | 付费点 |
|------|------|--------|
| **GEO 代理/咨询** | 多客户、交付包、可汇报 | Delivery / 多项目 |
| **品牌增长/SEO** | 自助 scan + 内部执行 | Pro 订阅 |
| **内容运营** | 工单、workbench、渠道清单 | 执行模块 |
| **管理员** | 成员、权限、账单、API Key 池 | Enterprise |

### 3.2 核心用户旅程

```
1. Enter domain only → 系统创建项目（geo.py init 等价）
2. System crawls + bootstrap → 品牌事实/竞品/问题库（带"待确认"标记）
3. Sample engines → Brand Visibility Report（分引擎提及率/排名/引用，raw answer 回放）
4. Playbook + Tickets → 用户转为工单并执行
5. Auto-verify → before/after 比较
6. One-click delivery package → 下载 zip
7. Schedule 7/14/30 day re-run
```

---

## 4. 信息架构（产品模块）

```
App
├── Auth / Billing / Team
├── Projects
│   ├── Overview（健康分、一句话结论）
│   ├── Engines（分引擎提及/引用、raw answer 回放、采样模式标注）
│   ├── Questions（题库、诊断类型、编辑）
│   ├── Competitors（从 sample 答案中解析）
│   ├── Diagnosis（Site audit / Gaps / Blueprint 建设地图）
│   ├── Playbook（Facts/Content/Tech/Off-site，impact×effort）
│   ├── Tickets（结构化 + 验收 + 回归重开）
│   ├── Assets（llms.txt、JSON-LD、snippets、drafts + lint 结果）
│   ├── Verification（任务级 before-after + 验收历史）
│   └── Delivery（客户包下载）
├── Settings（API Keys、调度、成员）
└── Public Marketing — 后置
```

---

## 5. 功能需求（按优先级）

### 5.1 P0 — Must（MVP 核心路径）

#### F-P0-01 Domain-only Onboarding

- **包装**：`geo.py init` + `crawl.run()` + `bootstrap.run()`
- **输入**：URL；系统固定使用全引擎范围
- **系统**：爬取 → LLM 推导 brand/topics/questions（含编造防线）
- **UI**：首屏只需一个 URL 输入框；高级设置折叠
- **验收**：新用户 3 分钟内进入「扫描中/已出报告」状态

#### F-P0-02 引擎采样与 Visibility Report

- **包装**：`sample.run()` + `analytics.py`
- **默认引擎**：取 `sample.PROVIDERS` 中用户配了 Key 的引擎
- **指标**：mention rate、rank、citation share；每条可打开 raw answer
- **采样模式标注**：每个引擎旁边显示「API·参数化知识」或「API·联网检索」或「人工·产品端」
- **验收**：样本项目能出分引擎表 + raw 回放 + 采样模式说明

#### F-P0-03 自动问题集

- **包装**：`bootstrap.question_bank()` + `expand.run()`
- 生成约 20–40 题（取决于语言覆盖），七组分类
- 用户可编辑；拓词结果需确认后入库
- 问题保留内部语言路由标签，但不作为产品层的引擎分类或筛选项

#### F-P0-04 站点审计 + Gap + 建设地图

- **包装**：`audit.run()` + `blueprint.build()`
- 6 维 audit（可抓取性/长度/结构/可抽取块/权威信号/对题性）
- 渠道建设地图：19 渠道优先级 + 覆盖度
- 所有引擎统一展示；语言与来源维度仅作为内部统计元数据

#### F-P0-05 Playbook + 结构化工单

- **包装**：`tasks.build()` → 自动从 audit + metrics + benchmark 生成
- 四类：实体消歧 / 页面技术 / 内容矩阵 / 外部证据 / 知识库 / 监测闭环
- 每条工单：why / action / owner / effort(S/M/L) / acceptance criteria
- 支持手动创建 offsite 工单（url + ask_text + 影响问题）
- 一键创建 + 状态管理

#### F-P0-06 自动验证 + 回归重开

- **包装**：`verify.run()`
- 16+ 种 checker 表达式，自动判定通过/未达标
- 通过的工单自动标 done；回归的自动 reopen
- 保留 progress 快照（before/after）
- **验收矩阵**：

| 工单类型 | 验收方式 | 说明 |
|----------|----------|------|
| 页面技术 (SPA/JSON-LD/sitemap) | 自动：重抓判定 | 100% 可自动化 |
| 内容矩阵 (长度/抽取块/标题) | 自动：重抓判定 | 100% 可自动化 |
| 外部证据 (榜单/平台) | 半自动：采样中出现目标域名 | 依赖下一轮采样 |
| 提及率/引用率目标 | 半自动：metrics 聚合 | 依赖下一轮采样 |
| 实体消歧/百科/一句话定义 | 人工确认 | UI 提供确认按钮 |
| Offsite (联系外站加入) | 人工确认 | 无法自动判定 |

#### F-P0-07 资产生成

- **包装**：`generate.run()`
- 产出：llms.txt（中英）、JSON-LD、HTML 片段、内容大纲
- AI 初稿（可选）+ 编造风险 lint
- **不含**：发布动作（MVP 只下载）

#### F-P0-08 客户交付包

- **包装**：`deliver.run()`
- 输出：6 份文档 + assets 目录，zip 下载
- 包含诊断报告、执行方案、工单表(CSV+HTML)、验收表、初稿风险清单、建设地图

#### F-P0-09 多租户与项目

- Tenant → Members(role) → Projects
- 每 project 对应 `work/<tenant_slug>/<project_slug>/`
- **文件系统隔离**：不同 tenant 的 work 目录互不可见
- 项目列表、健康分总览

#### F-P0-10 用户 API Key 管理（BYOK）

- 用户在 Settings 中配置各引擎 API Key
- Key 加密存储（AES-256-GCM），运行时解密注入环境变量
- 缺 Key 的引擎在采样时跳过（已有逻辑），UI 引导设置
- **平台 Key 池为后期增值**，MVP 不提供

#### F-P0-11 计费（MVP 简版）

- 单档 Pro：¥199/月（或 $29/月，配置化）
- 14 天全功能试用，**试用期限额**：3 个项目、每项目 2 次采样
- 计量：projects 数 × 每月 sample runs
- 不强制绑卡（试用可无卡）

#### F-P0-12 诚实边界

- 点名覆盖引擎列表 + 采样模式
- 不保证上榜/提及
- "API 采样反映模型记忆，非用户端实时搜索结果"
- 采样有噪声；趋势需多轮

---

### 5.2 P1 — Should（30–60 天）

| 编号 | 功能 | 说明 |
|------|------|------|
| P1-01 | 调度 | 7/14/30 天自动 re-run cycle |
| P1-02 | 竞品自动发现可视化 | 逻辑已有（`confirm_competitors`），加 UI |
| P1-03 | 词云 framing | 从 raw answer 提取品牌描述词 |
| P1-04 | 发布集成 | GitHub/WordPress/微信草稿（代码已有） |
| P1-05 | 团队邀请 | owner/editor/viewer 角色 |
| P1-06 | 手动 sampling sheet 导入 | 代码已有，加 UI |
| P1-07 | 白标交付 PDF 页眉 | deliver 模板化 |
| P1-08 | 平台 Key 池 | 平台代付采样费用，按量计费 |
| P1-09 | 分布式锁 | Redis 锁替换 fcntl，支持多节点 |
| P1-10 | Impact×Effort 可视排序 | Playbook 二维矩阵视图 |

### 5.3 P2 — Later

- SSO / SOC2  
- 自动外链 outreach 发送（高风险，需人工）  
- 移动 App  
- 年付折扣  
- 对象存储归档

---

## 6. 开源能力映射（经代码审查确认）

| 开源模块 | 行数 | SaaS 功能 | 包装方式 |
|----------|------|-----------|----------|
| `geolib.py` | 354 | 共用基础（路径/配置/HTTP/正文抽取）| 直接 import |
| `geo.py` | 598 | CLI 入口（init/new/cycle/serve 等） | API 层调同名函数 |
| `crawl.py` | ~150 | 站点抓取 | `crawl.run(slug)` |
| `bootstrap.py` | 335 | LLM 自动推导品牌/竞品/问题 | `bootstrap.run(slug)` |
| `audit.py` | 286 | 6 维页面体检 | `audit.run(slug)` |
| `sample.py` | 716 | 多引擎采样 + 答案解析 + 聚合 | `sample.run(slug)` |
| `tasks.py` | 349 | 工单生成 + 状态管理 | `tasks.build(slug)` / `tasks.set_status()` |
| `verify.py` | 228 | 自动验收（16+ checker） | `verify.run(slug)` |
| `deliver.py` | 393 | 客户交付包 | `deliver.run(slug)` |
| `deliverables.py` | 302 | 三份正式交付物 | `deliverables.run(slug)` |
| `generate.py` | ~300 | 资产生成 + lint | `generate.run(slug)` / `generate.lint_all(slug)` |
| `publish.py` | ~120 | 发布渠道（4 种） | `publish.publish(slug, platform, path, title)` |
| `blueprint.py` | 284 | 建设蓝图 | `blueprint.build(slug)` |
| `expand.py` | 299 | 拓词（下拉词 + LLM 转问句）| `expand.run(slug)` |
| `analytics.py` | ~140 | 健康分 + 派生指标 | 直接 import |
| `report.py` | 407 | 报告生成（HTML+MD） | `report.run(slug)` |
| `jobs.py` | 245 | 后台任务管理 | 需适配为异步任务队列 |
| `dashboard.py` | 607 | REST API + WebSocket | API 可复用 |
| `ui.html` | 2342 | 单页前端（暗色主题） | MVP 嵌入；后期重做 |
| `benchmark.py` | ~200 | 国内信源对标 | `benchmark.compare(domains)` |
| `references/` | 6 files | 方法论/渠道/权重数据 | 保留不动 |
| **tests/** | 200+ tests | 全部通过 | 保持绿灯 |

**二次开发原则**：SaaS API `POST /projects/:id/cycle` 内部等价于 `geo.py cycle`。每个 API 端点对应一个开源模块的 `run()` 调用。

---

## 7. 成本模型

### 7.1 单次采样成本估算

| 引擎 | 模型 | 输入/输出价格 | 单题成本（约 200 token 输入 + 800 token 输出） |
|------|------|--------------|----------------------------------------------|
| DeepSeek | deepseek-v4-flash | ¥0.5/1M in, ¥2/1M out | ¥0.0018 |
| GLM | glm-4-flash | ¥0.1/1M in, ¥0.1/1M out | ¥0.0001 |
| 豆包 | doubao-seed-1-6 | ¥0.3/1M in, ¥0.6/1M out | ¥0.0005 |
| Kimi | kimi-k2 | ¥1/1M in, ¥2/1M out | ¥0.0018 |
| OpenAI | gpt-4o-mini | $0.15/1M in, $0.6/1M out | $0.0006 |
| Perplexity | sonar | $1/1M in, $1/1M out | $0.001 |

### 7.2 每项目每周期成本（BYOK 模式）

- 默认 30 题 × 8 引擎 × 1 轮 = 240 次调用
- 总成本约 ¥0.5–2 / 项目 / 采样周期（用户自付）
- Bootstrap（一次）：1 次 LLM 调用 ≈ ¥0.01

### 7.3 平台成本（如提供 Key 池）

- 按 ¥0.5/次（含利润）向用户收费
- 10 个项目/月 × 4 周期 × 240 次 = 9600 次 → 平台成本约 ¥20，收入 ¥4800
- **结论**：BYOK 模式 MVP 零 LLM 成本；Key 池模式利润健康

---

## 8. 技术架构

### 8.1 MVP 架构（单节点）

```
[Next.js/React Web] → [FastAPI Gateway]
                          ↓
                  [BullMQ/RQ Job Queue (Redis)]
                          ↓
                  [Python Worker: import engine/scripts/*]
                          ↓
               [Filesystem: work/<tenant>/<slug>/]
               [Postgres: auth/billing/project-index/job-meta]
               [Redis: session/lock/queue]
```

- **短期 MVP**：FastAPI + Celery/RQ worker + 现有 `ui.html` 嵌入，单 VPS 部署
- **中期**：Next.js 前端重做，worker 仍调 Python 管线

### 8.2 关键适配点

1. **`geolib.die()` → raise GeoException**：SaaS worker 中不能 sys.exit  
2. **环境变量 → 运行时注入**：从加密 store 解密 Key，注入 `os.environ` 后调模块  
3. **`project_dir(slug)` → `project_dir(tenant, slug)`**：加 tenant 前缀  
4. **`jobs.py` → Celery/RQ**：复用白名单和日志机制，替换子进程为任务队列  
5. **`dashboard.py` API → FastAPI 路由**：dashboard 里的 `list_projects()`、`project()` 等函数可直接复用

### 8.3 数据模型（逻辑）

```text
Tenant(id, name, plan, trial_ends_at)
User(id, email, password_hash, ...)
Membership(tenant_id, user_id, role)
Project(id, tenant_id, slug, url, market, status, created_at)
  → 对应 work/<tenant_slug>/<slug>/geo.json
ApiKey(id, tenant_id, engine_code, encrypted_value)
Job(id, project_id, action, status, started_at, finished_at, log_path)
Subscription(tenant_id, plan, started_at, expires_at)
UsageCounter(tenant_id, month, sample_runs, projects_active)
```

管线产物（audit.json, tasks.json, metrics/*.json, delivery/*）全在文件系统，不入 DB。

### 8.4 API 草图（MVP）

```text
POST   /auth/register | /auth/login
GET    /me

POST   /projects                     { url }          → 触发 init+crawl+bootstrap job
GET    /projects
GET    /projects/:id                 → 复用 dashboard.project()
GET    /projects/:id/status          → 复用 geo.py status 逻辑

POST   /projects/:id/sample          → 返回 job_id（异步）
GET    /projects/:id/report
GET    /projects/:id/playbook
GET    /projects/:id/tickets
PATCH  /projects/:id/tickets/:tid    { status, note }

POST   /projects/:id/verify          → 返回 job_id（异步）
POST   /projects/:id/deliver         → 返回 download URL
GET    /projects/:id/delivery/:date  → zip 下载

POST   /projects/:id/schedule        { interval_days }
GET    /projects/:id/jobs            → 复用 jobs.recent()
GET    /projects/:id/jobs/:jid/log   → 复用 jobs.tail()

PUT    /settings/keys                { engine, encrypted_key }
GET    /settings/keys                → 列出已配引擎（不返回明文）

GET    /billing/usage
POST   /billing/subscribe
```

所有 POST 操作返回 `{ job_id }` 供前端轮询进度。

---

## 9. UX 要点

- **空状态**：只一个 URL 输入框 + "开始分析"按钮
- **采样模式透明**：每个引擎名旁标 `API·参数化知识` 或 `API·联网检索` 或 `人工·产品端`
- **数字旁注**：「单轮波动是观察值；连续两轮同向才标趋势」
- **工单详情**：显示 why / action / acceptance 三段式，不需要用户理解代码
- **验收历史**：时间线展示 before → after（progress_first vs progress）
- **错误引导**：引擎 Key 缺失时引导设置，不装死

---

## 10. 定价

| 方案 | 价格 | 包含 |
|------|------|------|
| Trial | 14 天免费 | 3 项目，每项目 2 次采样，BYOK |
| Starter | $79/月 (年付 $63/月) | 3 活跃项目，完整体检，行动工单与自动验收 |
| Pro | $199/月 (年付 $159/月) | 10 活跃项目，无限采样（BYOK），定时追踪与自动告警 |
| Agency | $499/月 (年付 $399/月) | 30 活跃项目，全白标交付报告，团队权限，优先队列 |
| Enterprise | 定制 | 私有化部署，OIDC SSO，数据保留与专属 SLA |

试用限额：3 projects × 2 runs × 30 questions × 8 engines = 1440 次调用（用户自付 Key）

---

## 11. MVP 里程碑（30 天）

| 周 | 交付 |
|----|------|
| W1 | 适配层：`die()→raise`、tenant 前缀、Key 注入；FastAPI 骨架；Auth + Project CRUD；调通 bootstrap 流程 |
| W2 | Sample 异步化（Celery/RQ）；Report API + 前端嵌入现有 ui.html；基础 Playbook 展示 |
| W3 | Tickets + Verify API；验收历史展示；Delivery zip 下载 |
| W4 | 计费骨架（Stripe/支付宝）；试用限额；诚实文案；Demo 部署 |

**Demo 脚本**：输入一真实站点 → 出报告 → 转 1 个 technical + 1 个 offsite 工单 → verify → 下载 delivery zip。

---

## 12. 测试与验收

### 12.1 继承开源测试

保持 `tests/test_*.py` 全绿，每次 CI 跑完整引擎测试。

### 12.2 新增 SaaS 测试

- 租户 A 不能读租户 B 的 project
- `die()` 在 worker 中抛异常而非退出进程
- API Key 加密存储、运行时解密正确
- Job 队列任务正确路由到 worker
- 试用限额到达后拒绝新采样
- Playbook 排序稳定
- Delivery 包文件清单非空

### 12.3 产品验收清单

- [ ] 新用户只填 URL，3 分钟内看到报告
- [ ] 分引擎表每个引擎标注采样模式
- [ ] 工单可自动验收、回归可 reopen
- [ ] 交付包 zip 含完整 6 份文档
- [ ] 无「保证上首页」「覆盖所有 AI」类宣传
- [ ] 未配 Key 的引擎显示「未测」不显示 0%

---

## 13. 风险与缓解

| 风险 | 缓解 |
|------|------|
| 采样 API 成本高 | MVP 强制 BYOK；试用有限额 |
| 答案随机性 | 多问聚合、repeat、文案降级承诺 |
| 开源快速演进 | upstream 在 engine/，定期 git pull + rebase |
| 品牌/功能撞车 | 产品名 CiteAura；卖点钉死闭环+多引擎+交付 |
| 安全暴露 | 所有 API 需 JWT 认证；work 目录 per-tenant 隔离；Key AES 加密 |
| fcntl 仅单机 | MVP 单节点 + P1 Redis 锁 |
| `sys.exit` 在 worker 中 | W1 第一件事适配 |

---

## 14. 品牌与目录说明

- 工作区文件夹：**citeaura**
- 开源代码位于：`engine/`（已去品牌化，作为 git 子目录）
- 商业产品名：**CiteAura**（官网：`citeaura.com`）
- 避免使用已冲突品牌：GeoForge / GEOforge

---

## 附录 A — 开源代码审查总结

**代码质量**：高。模块化清晰（每个文件一个职责），180+ 项确定性测试覆盖核心契约，注释充分解释 why not just what，错误处理到位（单引擎失败不崩全管线）。

**设计亮点**：
- `sample.py` 的品牌认知 vs 可见性分离防止假阳性
- `verify.py` 的 checker DSL 使验收规则声明式且可扩展
- `bootstrap.py` 的编造防线（只从官网正文抽取，标"待确认"）
- `jobs.py` 的并发保护（每项目单任务 + 孤儿回收）
- `deliver.py` 的口径一致性检查（验收日期对齐体检日期）

**SaaS 化需要改的**：
1. `geolib.die()` → raise（5 处调用）
2. `project_dir()` → 加 tenant 前缀
3. API Key 从 `.env` → 加密 store + 运行时注入
4. `jobs.py` 子进程模型 → Celery/RQ 任务队列
5. `fcntl.flock` → Redis 锁（P1）

## 附录 B — PRD v1.1 → v2.0 变更摘要

| 变更项 | v1.1 | v2.0 | 原因 |
|--------|------|------|------|
| P0 数量 | 14 项 | 12 项 | 词云/竞品可视化/发布集成降至 P1 |
| SSOT | 模糊("或等价 DB") | 文件系统 SSOT，DB 只存索引 | 避免双写 |
| BYOK | P1 | P0 必选 | 成本模型验证后发现 MVP 无法承担代付 |
| 采样模式标注 | 无 | P0 强制 | 代码审查发现 API≠用户端 |
| 验收方式矩阵 | 一句话 | 按类型展开 | offsite 无法自动验收需明确 |
| 成本模型 | 无 | 新增第 7 节 | 验证定价可行性 |
| 技术适配点 | 未列 | 5 项明确清单 | 代码审查发现的必改项 |
| 架构 | "建议形态" | 明确决策（FastAPI + Celery + 单节点） | 降低 MVP 复杂度 |

---

**文档结束。** 实现时以本 PRD 为唯一产品真源；与开源 README 冲突时，**管线行为以开源+测试为准，产品壳与商业规则以本 PRD 为准**。
