# CiteAura × Google Search Console：获客钩子方案（待审核）

> 日期：2026-10-29（v2，替换同日 v1 的 9 周“证据层”方案）
> 状态：草案，等待决策（见 §8）
> 背景：[SEO Stack 竞品拆解](../reports/seo-stack-teardown.html)
> 前提：产品目前没有客户。v1 按“已有代理商客户、有流量”设计，大部分内容属于提前做，已移到 §9 保留。

## 1. 要做什么

做一个 2–3 周能上线的功能，帮助拿到首批客户：

> 连接 Google Search Console → 自动挑出你在 Google 上展示量最高的 20 个非品牌查询 → 采样这些查询在 AI 回答里的表现 → 报告告诉你：“这些用户真实在搜的问题，AI 回答里有没有你，被推荐的是谁”

这个功能回答的问题和现有的问题库不同。现有问题库来自 bootstrap 推导和模板，是“我们猜用户会问什么”；GSC 查询是“用户确实在搜什么”。把真实需求和 AI 可见性放在同一张表里，SEO Stack 做不到，因为它的 AI Visibility 和 GSC 数据是两个分开的模块。

### 非目标

- 不做 GSC 存档、搜索数据浏览器、Winners & Losers、日期对比、导出。GSC 自带这些功能，对获客没有帮助。
- GA4 已按 §9 的最小设计落地为 AI 引荐流量（2026-10-30）；效果实验扩展和异常提醒仍不做。没有客户就没有数据和观察期，这两项仍做不出结果。
- 不长期保存 Google 凭据（见 §3.1）。
- 证据层永不接入百度数据源。引擎中现有的百度采样、拓词和渠道蓝图不在本方案范围内。
- 不改 `engine/`。

## 2. 用户流程

```
落地页 / 公开审计结果页
  CTA：“看看 AI 回答里有没有你的真实搜索流量”
        │
        ▼
注册（现有 Trial，14 天）→ 创建项目（现有 onboarding）
        │
        ▼
【新】onboarding 可选步骤：连接 Search Console
  ├─ 跳过 → 现有流程不变
  └─ 连接 → Google 授权（只读）→ 自动匹配项目域名对应的 GSC 属性
        │
        ▼
【新】候选列表：近 90 天展示量最高的非品牌查询，最多 20 条
  每条显示：查询原文、建议的 prompt 写法、Google 展示量 / 点击 / 平均排名
  用户勾选、可编辑 → 加入问题库（source = gsc）
        │
        ▼
首次采样（现有流程，Trial 现有限额）
        │
        ▼
【新】报告“真实需求”一节：每个 GSC 来源问题的 Google 需求数据 + 各引擎是否提及你、提及了哪些竞品
```

关键设计：连接 GSC 放在**首次采样之前**。这时项目还没有基线，加入新问题不会触发问题集版本变化带来的“不可比”判定（`api/adapters/measurement.py:712`）。已有基线的项目从问题视图导入时，复用现有的版本变化提示。

另一个入口：问题视图（`web/app/views/questions.js`）现有的 “Research prompts” 旁边加一个 “从 Search Console 导入”，服务已跳过 onboarding 步骤的用户。

## 3. 技术设计

### 3.1 授权：一次性读取，不存 refresh token

- OAuth 2.0 授权码流程 + PKCE，`state` 参数绑定当前用户和项目，防 CSRF。
- 只申请 `https://www.googleapis.com/auth/webmasters.readonly`。
- 不申请 `access_type=offline`。拿到 access token 后立即完成两次 API 调用（列属性、拉查询），然后丢弃 token，不落库、不写日志。
- 好处：
  - 不需要 `IntegrationCredential` 新类型，也不涉及凭据表的唯一约束
  - 没有长期凭据，泄露面最小
  - 用户想刷新数据时重新授权一次即可，每次只需几秒
- 以后做存档时再加 refresh token（见 §9）。

新增配置（环境变量，按 AGENTS.md 约定写进 `.env.example`）：`GOOGLE_OAUTH_CLIENT_ID`、`GOOGLE_OAUTH_CLIENT_SECRET`。未配置时前端隐藏入口，不报错。

### 3.2 拉取与筛选

**属性匹配**：调用 `sites.list`，按以下顺序匹配项目域名：`sc-domain:<域名>` → `https://<域名>/` → `https://www.<域名>/` → `http://` 变体。只有一个匹配就自动选中；多个匹配或没有匹配时让用户选，或者提示“该 Google 账号没有这个站点的权限”。权限级别为 `siteUnverifiedUser` 的属性不列出。

**查询**：一次 `searchanalytics.query` 调用：

| 参数 | 值 |
|---|---|
| 日期范围 | 结束日为 T-3（避开未定稿数据），往前 90 天 |
| dimensions | `query` |
| type | `web` |
| rowLimit | 25,000 |
| dataState | `final` |

再调用一次不带 dimensions 的总量查询，用来计算匿名缺口（总点击减去各查询点击之和）。

按配额文档，一次 90 天的单维度查询 load 很低，远在每站点 1,200 QPM 之内，不需要排队或限速。

**筛选规则**（确定性规则，不调 LLM）：

1. 排除品牌词：命中 `brand_identity` 里的品牌名或别名的查询排除。
2. 排除过短的查询：少于 2 个词（中文按少于 4 个字）的查询排除。
3. 优先挑意图明确的查询：包含疑问词或比较词的排在前面（how / what / which / best / vs / alternative / review / price，以及“怎么 / 什么 / 哪个 / 推荐 / 对比 / 区别 / 价格”等；其他语言按 `question_language` 扩展）。
4. 剩下的按展示量降序，取前 20 条。

**Prompt 写法**：
- 本身是问句的查询，原样使用。
- 其他查询给一个模板改写，例如 “best crm small team” 改写为 “What is the best CRM for a small team?”。模板沿用 `prompt_research.INTENTS` 的意图分类。
- 两种写法都显示，用户可以编辑后再加入。不调用 LLM，所以 GSC 数据只会以“用户选中并采样的 prompt”这一种形式发给 AI 引擎。

### 3.3 落盘

符合硬约束 #3：快照是管线产物，放在文件系统，不进 Postgres。

```
work/<tenant>/<slug>/searchdata/gsc_snapshot.json
```

内容：
- `property`：属性 ID
- `window`：起止日期
- `fetched_at`：拉取时间
- `data_state`：`final`
- `totals`：总点击、总展示
- `anonymous_click_share`：匿名缺口比例
- `rows`：前 200 条查询（只保留筛选和展示需要的部分，不存全量）
- `candidates`：最终候选，带筛选原因

每次重新授权拉取会覆盖这份快照；旧快照移到 `searchdata/history/`，带时间戳。用户可以在项目设置里一键删除 `searchdata/` 目录。

### 3.4 问题库与报告

- 加入问题库时，问题记录 `source: "gsc"`，并附带 `gsc` 元数据：查询原文、展示量、点击、平均排名、快照的 `fetched_at`。复用现有 `workspace.addQuestions` 接口，只扩展允许的字段。
- 报告视图（`web/app/views/report.js`）新增“真实需求”一节，只在项目里有 GSC 来源问题时显示。每行一个问题：

| 列 | 来源 |
|---|---|
| 查询 / prompt | 问题库 |
| Google 展示量、点击、平均排名（近 90 天） | GSC 快照，标注 `GSC·第一方` 和拉取时间 |
| 各引擎是否提及 | 采样结果，标注采样模式 |
| AI 回答中出现的竞品 | 采样结果 |

- 顶部给一句汇总，例如：“在你 Google 展示量最高的 12 个问题里，AI 回答提到你的有 3 个。”
- 顶部同时显示匿名缺口说明，例如：“Google 隐藏了 31% 的点击对应的查询，列表只覆盖可见部分。”
- 这一节不并入现有的五项 GEO 健康分（`engine/scripts/analytics.py`），第一方数据和采样指标分开展示。
- 满足硬约束 #8：每个数字都能对应到查询、属性、时间窗和拉取时间。

### 3.5 数据量少的情况

GSC 账号绑定的是站点，与 `market` 字段无关，`market=cn` 的项目一样可以连接。数据量取决于站点有多少 Google 访客，面向中国大陆的站点会比较少。

- 候选少于 5 条时，显示实际条数，并说明“近 90 天 Google 展示量较低，可以先用现有问题研究补充”。
- 0 条时显示空状态，提示跳过这一步，不阻断后续流程。
- citeaura.com 自己就是低数据量的例子：2026-09-14 记录的 28 天数据只有 500 次展示、0 次点击（`docs/seo-gsc-28d-2026-09-14.md`）。dogfood 时按低数据量路径验收，再另找一个高流量的测试站验收正常路径。

## 4. 改动清单

| 位置 | 改动 |
|---|---|
| `api/searchdata/`（新建） | `oauth.py`：授权 URL、回调、PKCE、`state` 校验；`gsc.py`：属性匹配、查询拉取、匿名缺口计算；`candidates.py`：筛选规则与 prompt 改写；`router.py`：`/api/v1/projects/{id}/searchdata/...` 路由 |
| `api/config.py`、`.env.example` | Google OAuth Client 配置；未配置时功能关闭 |
| `api/main.py` | 挂载新路由 |
| 问题库写入（`workspace.addQuestions` 对应的后端） | 允许 `source: "gsc"` 和 `gsc` 元数据字段 |
| `web/app/api.js` | 新增 4 个端点：开始授权、属性列表、拉取候选、删除快照 |
| `web/app/views/onboarding.js` | 可选步骤“连接 Search Console” |
| `web/app/views/questions.js` | “从 Search Console 导入”入口和候选列表 |
| `web/app/views/report.js` | “真实需求”一节 |
| `web/app/views/project-settings.js` | 显示已连接的属性和拉取时间；删除快照按钮 |
| `api/i18n/messages/*.json` | 7 种语言的新文案 |
| `web/privacy.html` | Google 用户数据章节（见 §5） |
| 落地页、公开审计结果页 | CTA 文案和入口 |
| `api/product_events.py` 调用点 | 埋点（见 §6） |
| 依赖 | 不新增。HTTP 调用用现有的 `requests`，不引入 Google SDK |

权限：连接、拉取、删除需要 editor 及以上角色（`require_editor`）；viewer 可以看报告里的“真实需求”一节。

## 5. Google OAuth 验证与合规

- `webmasters.readonly` 预计属于 sensitive scope，需要应用验证，预计不需要 CASA 安全评估。**提交前在 Cloud Console 的 OAuth 同意屏幕上确认分类。**
- 验证通过前，应用处于“测试”状态：最多 100 个测试用户，用户会看到“Google 尚未验证此应用”的警告页。零客户阶段 100 个用户够用，但警告会降低转化，所以验证和开发同时提交。
- 需要准备的材料：
  - `citeaura.com` 在 Search Console 中的域名所有权验证（已有，`sc-domain:citeaura.com`）
  - 隐私政策新增 Google 用户数据章节：读取哪些数据（查询词及其展示量、点击、排名），用途，存储位置（`work/` 下的项目目录），保留期（直到用户删除快照或删除项目），删除方式；声明遵守 Google API Services User Data Policy 的 Limited Use 要求
  - 演示视频：授权 → 候选列表 → 加入问题库 → 报告
  - scope 用途说明
- 产品侧的合规要求：
  - 数据只用于向该用户提供功能，不用于训练模型，不转售，不跨租户使用
  - 发给 AI 引擎的只有用户选中并采样的 prompt 文本，不发送展示量、点击等数据，也不发送账号信息
  - 用户可以随时删除快照

## 6. 成功指标

零客户阶段只看漏斗，不看收入。埋点用现有的 `record_product_event`：

| 事件 | 含义 |
|---|---|
| `gsc_connect_started` | 点击连接 |
| `gsc_connect_completed` | 授权成功并匹配到属性 |
| `gsc_candidates_shown` | 候选列表展示，记录候选条数 |
| `gsc_questions_added` | 加入问题库，记录条数 |
| `gsc_report_viewed` | 查看“真实需求”一节 |

上线 4 周后评估：

- 连接完成率（completed / started）。如果明显偏低，主要原因可能是“未经验证的应用”警告，要先推进 Google 验证。
- 连接 GSC 的用户和没连接的用户相比，完成首次采样的比例是否更高。
- 有没有用户因为这个功能付费或主动联系。

在这之前不定具体阈值。现在没有任何基线数据，定出来的数字没有依据。

## 7. 里程碑

假设 1 名全栈开发。

| 时间 | 内容 | 出口标准 |
|---|---|---|
| 第 1 周 | 在 Cloud Console 建 OAuth Client，确认 scope 分类并提交验证；更新隐私政策；`api/searchdata/` 的授权、属性匹配、拉取、筛选；单元测试 | 用 citeaura.com 的 GSC 属性完成授权并返回候选（低数据量路径） |
| 第 2 周 | onboarding 步骤、问题视图入口、候选列表、加入问题库；报告“真实需求”一节；项目设置里的删除 | 一个高流量测试站完成“连接 → 选题 → 采样 → 报告”全流程 |
| 第 3 周 | 7 种语言文案；落地页与公开审计 CTA；埋点；浏览器验收；部署上线 | 线上可用，测试用户名单已开放 |

第 3 周可以根据进度压缩到第 2 周末。Google 验证是否通过不影响上线，只影响警告页是否出现。

## 8. 需要你决策的问题

| 编号 | 问题 | 选项 | 建议 |
|---|---|---|---|
| D1 | 首次采样的费用谁出 | A. 用户自带 Key（现状）；B. 连接 GSC 的 Trial 用户由平台 Key 池免费送一次小规模采样（例如 20 题 × 2 个引擎） | **B**。没有 Key 的用户在这一步就会流失，这一次的成本可以按 `PLATFORM_POOL_PRICES_CNY_FEN` 预先估算。需要你确认预算上限 |
| D2 | 这个钩子是否也做成免注册的公开工具 | A. 只在注册后可用；B. 落地页上免注册就能连 GSC 看候选列表，看报告再注册 | **A 起步**。B 的转化可能更高，但需要处理匿名会话和 `PublicAudit` 式的交接逻辑，等 A 有数据后再评估 |
| D3 | 外联时怎么用这个钩子 | 只做产品内功能 / 同时准备外联话术和演示报告 | 建议同时准备。零客户阶段的瓶颈主要在获客渠道，可以结合现有的 `docs/linkedin-outreach-50.md` |

v1 的 D1–D7 已全部失效：自带 OAuth Client、存储方案、视图位置、Free 存档档、实验门槛和国内数据源，都推迟到 §9 再定，其中百度数据源永不接入。

## 9. 有首批客户之后（推迟，保留思路）

以下内容来自 v1，等有付费客户且对方明确提出需求时再排期。重新启用前，需要先用真实客户数据核实每一项的前提。

| 能力 | 前提 | v1 中的设计要点 |
|---|---|---|
| GSC 每日同步与长期存档 | 客户希望持续追踪，不只看一次 | 存 refresh token；每天拉 T-3 到 T-1，`dataState=all`；首次回填约 16 个月；Parquet 按月分区 + 嵌入式 DuckDB 查询；同步用独立的锁，不占 `project_lock`；备份快照排除存档目录 |
| 多 Google 账号（边缘情况） | 有客户确实遇到 | 常规做法是一个 Google 账号管多个属性，代理商也通常让客户把代理商账号加为属性用户，所以默认一个租户一个账号、每个项目绑定其中一个属性即可。只有客户坚持不授权给代理商账号时才需要多账号，届时再把 `IntegrationCredential` 唯一约束改为 `tenant_id + provider + account_email` |
| 搜索数据视图 | 客户要求在 CiteAura 内看 GSC 数据 | 无 1,000 行限制、正则筛选、Winners & Losers、Striking distance，可以从机会一键建单（参照 `/brand-opportunities/tickets`） |
| 需求加权提及率 | 已有一批 GSC 来源问题和多期采样 | 按展示量加权的提及率，只用于排序和展示，不并入健康分 |
| GA4 与 AI 引荐流量 | 客户配置了 GA4 | **已实现（2026-10-30）**：`analytics.readonly`；AI 来源域名表带版本号；连接时检查 key events 是否配置；一次性读取，不存 refresh token |
| 搜索数据实验 | 客户流量足够，且有已部署的工单 | 实验 spec 升到 version 3，新增 `search_outcomes` 子对象，独立状态和 28 天窗口；目标组取工单的 `affected` 页面；流量不足时返回 `inconclusive`，原因 `insufficient_volume` |
| 异常提醒与 Slack | 客户要求持续监控 | 挂在同步任务之后，不复用只在采样后触发的 `regression_alerts` 入口 |
| 交付包证据章节 | 代理商客户要向他们的客户交付 | 先确认 GSC 原始查询能不能通过交付包的语言校验（`delivery_evidence._english`） |
| 导出到用户自己的存储、Looker Studio、URL 索引状态 | 有明确的客户需求 | — |

## 10. 测试与验收

- 引擎测试保持全绿：`cd engine && python3 -m unittest discover -s tests`（本方案不改 `engine/`）。
- API 测试（Google API 全部用录制的响应夹具，CI 不访问真实 Google）：
  - OAuth：`state` 不匹配、PKCE 校验失败、用户拒绝授权、token 交换失败，都要返回明确错误
  - 授权完成后 token 不出现在数据库、日志和快照文件中
  - 属性匹配：domain 属性、URL 前缀属性、www 变体、无匹配、多个匹配、`siteUnverifiedUser`
  - 筛选：品牌词排除、短查询排除、意图词排序、不足 20 条、0 条
  - 匿名缺口：总量与查询之和的计算，包括总量为 0 的情况
  - 租户隔离：A 租户不能读取或删除 B 租户的 `searchdata/`
  - 权限：viewer 调用连接或删除接口返回 403
  - 未配置 `GOOGLE_OAUTH_CLIENT_ID` 时，相关接口返回明确的 `not_configured`，前端隐藏入口
- 浏览器验收：注册 → 创建项目 → 连接 GSC → 选择候选 → 首次采样 → 报告中的“真实需求”一节；另验收低数据量路径和跳过路径。
- 数据真实性检查：报告中每个 Google 数字都标注 `GSC·第一方`、属性和拉取时间；每个 AI 结果都标注采样模式。

## 参考

- [Search Console API Usage Limits](https://developers.google.com/webmaster-tools/limits)
- [Search Analytics API: Getting all your data](https://developers.google.com/webmaster-tools/v1/how-tos/all-your-data)
- [Sensitive scope verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/sensitive-scope-verification)
- [OAuth 2.0 Scopes for Google APIs](https://developers.google.com/identity/protocols/oauth2/scopes)
