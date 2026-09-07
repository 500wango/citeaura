# CiteAura CrowdReply 对标优化执行计划

> 版本 2026-08-28 v4 · 基于 v3 修订
> 定价：Starter $79 / Pro $199 / Agency $499 / Enterprise Custom
> 定位：通用行业 GEO 工作流；不做代发、托管号、点赞、上票、自动发布或排名/提及保证

## 0. 这版的核心调整

v3 的产品方向保留，但执行顺序和数据合同调整为：

1. 先统一引用聚合口径，再扩展 UI，避免现有 `channels` 与新 Citation 视图出现两套数字。
2. 只把当前后端真实执行的套餐能力写进价格矩阵；未实现能力不得伪装成额度。
3. 机会和站外实体使用稳定 ID、稳定排序和文件 SSOT，幂等性可测试、可恢复。
4. 验收只验证“同口径复测、证据变化和状态”，不要求 mention/citation 必然提升。
5. 继续区分 `diagnostic_ready`、`visibility_ready`、`implementation_ready`，不能用单一状态表达增长结果。

## 1. 不可变约束

- 不修改 `engine/scripts/*.py` 公共接口；SaaS 逻辑只放在 `api/adapters/`、`api/projects/`、`web/`。
- 文件系统是管线 SSOT：产物位于 `work/<tenant>/<slug>/`，不把采样、机会或实体清单写入 Postgres。
- 所有采样结果标记 `api_parametric_knowledge`、`api_search_grounded` 或 `manual_product_surface`。
- 不引入按条 credits，不新增外链商城，不自动发布或自动联系第三方。
- 未测数据显示 `Unmeasured`，不得显示伪造的 `0%`。
- 每个任务完成后运行 Engine 全量测试、API 全量测试、语法检查和受影响页面浏览器验收。

## 2. 统一数据契约（P0-0，所有后续任务的前置）

### 2.1 Citation aggregation

新增 `api/adapters/citation_sources.py`，但它是唯一引用聚合实现；现有 `channels`、Overview 卡和 P1 Citation 视图均消费它。

`aggregate(project_slug)` 读取当前租户上下文内 `samples/*.jsonl`，选择最新完整 run：优先按文件名中的 `run_id` 稳定排序，并返回该 run 的 `run_id`；不跨 run 合并。

统计规则：

- 只统计 `ok == true` 且 `citations` 为列表的记录。
- 只有真实 URL 计入；`urlparse().hostname` 小写并去除前缀 `www.`。
- 每个 URL 去重；域名计数按去重后的 URL 记录次数累计。
- `search_enabled == false` 的参数化回答可以保留在样本中，但不计入 citation 总数。
- 每域保留最多 3 个去重 `evidence_urls`，结果带 `evidence_count`。
- 解析坏行不导致 500；返回 `warnings` 数量。目录不存在、无完整有效记录或总引用数为 0 时返回 `status=unmeasured`。
- 返回 `status`、`run_id`、`sampled_at`、`total_citations`、`domains`、`unmeasured_reason`、`warnings`。

域类型启发式固定为 `community`、`knowledge`、`review`、`editorial`，未知域默认 `editorial`。该分类只用于建议资产，不表示域名权威等级。

### 2.2 现有能力边界

- 复用现有 `channels` 视图，不再创建第二个同名数据源；P0 卡可链接到 `#/channels`，P1 独立视图再提供更深的行动列。
- `brand_opportunities.assess()` 继续从问题库、事实库和有效样本派生，不调用 LLM，不自动写内容。
- 套餐事实以 `api/billing/plans.py` 和实际限制代码为准：当前可确认的是项目数、BYOK/平台池资格、白标和 SSO；模型数量、团队人数、固定 ticket 数不得写成已提供额度。
- 试用文案统一为现有的 14-day Starter trial；不得出现 7-day trial。

## 3. 阶段与依赖

| 阶段 | 目标 | 预计工期 | 依赖 | 发布门槛 |
|---|---|---:|---|---|
| P0-0 | 引用聚合契约、共享 adapter、回归测试 | 1 天 | 无 | Engine/API 全绿 |
| P0-1 | Hero 价值主张重构 | 1-2 天 | 无 | 公开页浏览器验收 |
| P0-2 | 事实一致的定价对比矩阵 | 1-2 天 | 套餐能力核对 | 价格/schema/响应式验收 |
| P0-3 | Overview 引用情报卡 | 1-2 天 | P0-0 | 租户隔离与数据追溯 |
| P1-1 | Citation Intelligence 独立视图 | 3-4 天 | P0-0、P0-3 | 有/无数据均不白屏 |
| P1-2 | Content Opportunity 矩阵 | 3-4 天 | P0-0 | 稳定 ID、证据和工单闭环 |
| P1-3 | 站外实体人工复核队列 | 4-5 天 | P0-0、P1-1 | 文件 SSOT、固定 6 + 动态项 |
| P2 | Authority Footprint / Listening Lite 评估 | 按需 | 真实客户数据 | 不承诺上线 |

P0-1 与 P0-2 可并行；P0-3 之后的所有引用功能必须复用 P0-0。每个任务可独立提交，但不强制物理分支；若使用分支，命名为 `feat/<task-id>`，提交格式 `feat(module): description`。

## 4. P0 任务定义

### P0-0 统一 Citation Sources

改动：`api/adapters/citation_sources.py`、现有 channels 数据调用点、`api/projects/` 路由、`api/tests/test_citation_sources.py`。

输出：`GET /api/v1/projects/{id}/citation-sources`，通过 `project_for_user` 和 `with_tenant_read_context` 完成租户隔离；无数据返回 200 + `unmeasured`。

完成定义：

- measured fixture 的 `share == count / total_citations`，域名、证据 URL 和 run_id 可追溯。
- 缺目录、坏 JSONL、参数化-only 样本不会 500 或伪造数据。
- 同一项目重复请求结果稳定；跨租户返回 404。
- 现有 `channels` 与新 API 的统计口径有一组契约测试，避免双重实现。

### P0-1 Hero

在 `web/index.html` 增加价值主张、静态 score preview 和信任占位；使用现有 token 和字体，不新增外部图片、真实客户 logo 或效果承诺。保留现有证据链和 FAQ 边界文案。

验收：首屏能在 5 秒内说明“测量 AI 可见度、生成可被引用的资产、用证据验证”，390/1024/1440 宽度无溢出，`/llms.txt` 和 canonical 不变。

### P0-2 定价矩阵

重构 `web/pricing.html`，保留 `$79/$199/$499` 和现有 OfferCatalog。矩阵只列已实现或明确标为 `Coming later` 的能力：active projects、BYOK-first、采样模式标签、审计/工单/验收、交付包、白标、API/MCP、Enterprise SSO。

不得写 `Choose 2/4/All models`、`2 team members` 或固定 `13 tickets`，除非对应的后端限制和测试先完成。FAQ 统一使用 14 天试用，并明确“不保证 AI mentions 或 rankings”。

验收：1280/768/375 可横向滚动；schema 价格仍为 79/199/499；canonical、OG 和试用时长文案与 API/套餐配置一致。

### P0-3 Overview 情报卡

在 `web/app/views/overview.js` 加载 P0-0 API，并在现有 KPI 与 visibility plan 之间展示 Top 5 域。已有数据时显示 type、share、evidence_count、run 时间和 `#/channels` 入口；无数据只显示 `Unmeasured` 与运行 sample 的动作。

前端请求失败不得阻断 Overview 主视图；卡片失败显示可重试的轻量状态。API 客户端增加强类型方法和测试。

## 5. P1 任务定义

### P1-1 Citation Intelligence 视图

新增 `web/app/views/citations.js` 和 `#/citations` 路由，但数据仍来自 P0-0。表格列为 Domain、Type、Share、Evidence samples、Suggested asset、Action；最多 Top 20，按 share 降序、domain 升序稳定排序。

Action 仅允许 `View evidence` 和 `Create ticket`。Suggested asset 是白帽建议，不是外链购买或自动发布指令。无数据状态必须说明“Run a sample”；参数化-only 结果不得伪装为联网引用。

完成定义：点击证据能跳现有 engines 回放；创建工单带 domain、run_id 和建议资产，但不改变原始采样文件。

### P1-2 Content Opportunities

扩展 `brand_opportunities.assess()`，每条机会使用稳定 ID：`hash(question_id + gap_type + suggested_page_type)`。同一输入重复 assess 必须返回相同 ID、排序和字段。

字段包括 `question`、`question_id`、`evidence_count`、`gap_type`、`suggested_page_type`、`acceptance_criteria`、`evidence`。机会最少关联一个真实 question 或 sample；没有样本时为 `not_covered` / `待验证`，不能伪造证据。

Acceptance criteria 改为可观察状态：完成同一问题、同一采样模式和可比 cohort 的复测，记录 `improved`、`unchanged`、`regressed` 或 `unmeasured`；不要求 mention_rate 或 citation 必然上升。

在 `plan` 增加 Opportunities tab。创建 ticket 时写入 question_id、gap_type、证据摘要和上述验收条件；重复点击同一机会应复用或拒绝重复 ticket，不能无限追加。

### P1-3 Off-site Entities

新增 `api/adapters/offsite_entities.py`、路由、`web/app/views/entities.js`。文件为 `work/<tenant>/<slug>/offsite_entities.json`，通过项目锁写入。

后端返回完整 canonical 清单：固定 6 项使用固定 ID；动态项使用规范化域名 hash。首次读取时生成固定 6 项和最多 2 个 citation-derived pending 项，首次保存即写完整列表。固定平台、动态平台和 `custom` 平台使用明确枚举；URL 只接受 `http(s)` 或规范域名。

每项字段：`id`、`platform`、`domain_or_url`、`url`、`status`、`evidence_url`、`reviewer_note`、`updated_at`、`source`。状态只允许 `pending`、`consistent`、`needs_fix`。保存采用替换式 canonical list，保留未知字段时不改变安全边界。

前端显示固定 6 + 动态项，所有建议加“人工复核、无自动发布”提示；编辑只改清单和状态，不触发第三方请求。

## 6. 测试与发布门槛

每个任务至少包含：

- API：成功、空数据、坏产物、权限/跨租户、幂等和错误状态测试。
- 文件：路径位于当前租户项目目录；不写 Postgres；重复运行不生成重复实体或机会。
- UI：`node --check`，受影响页面在 390/768/1280 或 1440 宽度验收；有数据和空数据均不白屏。
- 回归：`cd engine && python3 -m unittest discover -s tests`；`cd api && pytest tests/ -q`；`python3 -m compileall -q api`；`git diff --check`。

P0 合并前必须通过 P0-0 契约测试；P1 合并前必须通过租户隔离、文件产物和浏览器验收。任何失败不得用 mock 数据掩盖；需要真实 provider 的场景标记为未测并保留下一步。

## 7. 交付记录

每个 PR/提交必须包含：改动文件、API 响应契约、状态/口径说明、测试命令与结果、浏览器 DOM 或截图证据、未完成项。生成的证据必须带 `run_id` 或 `source`，不得只贴汇总数字。

## 8. 变更记录

- v4：统一引用聚合为单一 adapter；补充完整样本和坏产物规则；删除未实现的套餐承诺；将 7-day trial 修正为 14-day；为 opportunity/entity 增加稳定 ID 和 canonical list；将验收从“必须提升”改为可观察的复测状态；明确三类 readiness 不互相替代。
