# CiteAura CrowdReply 对标优化最终执行计划

> 版本 2026-08-28 Final · 本文件取代 v3/v4 作为执行合同
> 价格：Starter $79 / Pro $199 / Agency $499 / Enterprise Custom
> 定位：证据型 GEO 诊断、执行、复测和交付；不做代发、托管号、点赞、上票、自动发布或排名/提及保证

## 1. 最终产品形态

本计划不把 CrowdReply 复制成第二套产品，而是把“引用来源情报”嵌入 CiteAura 现有闭环：

`诊断 → AI 可见度测量 → 引用/内容机会 → 站内资产 → 工单 → 验收复测 → 交付`

### 页面职责（硬约束）

| 页面 | 唯一职责 | 不负责 |
|---|---|---|
| Overview | 展示 KPI、下一步和引用来源摘要 | 不承载完整引用分析 |
| Channels | 唯一的引用来源分析入口：域名、占比、证据、建议资产 | 不创建外部发布动作 |
| Engines | 展示原始问题、回答、模型和引用回放 | 不做机会管理 |
| Plan | 管理 finding、content opportunity、offsite action 和验收条件 | 不重新计算 citation |
| Assets | 生成/审核 FAQ、实体定义、比较页、`llms.txt` 等站内资产 | 不自动发布 |
| Verify | 以同口径 cohort 复测 before/after | 不保证提升 |
| Outreach | 管理已确认的第三方证据和人工联系记录 | 不等同于 citation intelligence |
| Entities | 管理官方/目录/媒体实体一致性人工清单 | 不抓取或自动修改第三方平台 |

不得新增独立 `#/citations` 产品入口。P1-1 的功能全部并入现有 `channels`；如未来数据规模确实需要拆页，必须先有产品评审和迁移方案。

## 2. 不可变约束

- 不修改 `engine/scripts/*.py` 公共接口；SaaS 逻辑只放 `api/adapters/`、`api/projects/`、`web/`。
- 文件系统是管线 SSOT：采样、机会、实体清单均位于 `work/<tenant>/<slug>/`，不写入 Postgres。
- 采样必须标记 `api_parametric_knowledge`、`api_search_grounded` 或 `manual_product_surface`。
- `diagnostic_ready`、`visibility_ready`、`implementation_ready` 始终独立。
- 未测显示 `Unmeasured`，不显示伪造的 `0%`。
- 不引入 credits、外链商城、自动发布和效果保证。

## 3. 阶段总览

| 阶段 | 内容 | 依赖 | 完成门槛 |
|---|---|---|---|
| P0-0 | 统一 citation adapter、shadow 比对和契约测试 | 无 | 新旧 Channels 结果一致 |
| P0-1 | Hero 价值主张 | 无 | 公开页响应式验收 |
| P0-2 | 事实一致的定价矩阵 | 套餐能力核对 | 价格/schema/文案一致 |
| P0-3 | Overview 引用摘要卡 | P0-0 | 隔离、失败降级、证据追溯 |
| P1-1 | 增强 Channels 为 Citation Intelligence | P0-0/P0-3 | 不新增路由，回放和资产建议闭环 |
| P1-2 | Plan 内 Content Opportunities | P0-0 | 稳定 ID、证据、幂等工单 |
| P1-3 | Entities 人工复核清单 | P0-0/P1-1 | canonical 文件和租户隔离 |
| P2 | Authority Footprint / Listening Lite 评估 | 真实客户数据 | 不承诺上线 |

P0-0 预计至少 1.5 个工作日，包含 shadow 比对、fixture 一致性校验和旧逻辑回归保留。P0-1 与 P0-2 可并行；P0-0 完成前，P0-3 和 P1-1 可以在独立分支编写，但不得合入 `main` 或进入生产构建。P1-1 完成前不得增加新的 Citation 导航入口。

## 4. P0-0：唯一 Citation 数据契约

新增 `api/adapters/citation_sources.py`，并迁移现有 `channels` 数据调用到该 adapter。Overview、Channels、offsite 派生项均只能消费这一实现。

`aggregate(project_slug)` 只读取当前租户下 `samples/*.jsonl` 的最新完整 run，不跨 run 合并；返回 `run_id`、`sampled_at`、`status`、`total_citations`、`domains`、`warnings` 和 `unmeasured_reason`。

统计规则：只计 `ok=true` 且 `search_enabled=true`、citations 为列表的记录；URL 规范化为小写 hostname 并去除 `www.`；同一 URL 去重；每域最多保留 3 个 evidence URL；坏行跳过并计入 warning；无有效引用返回 `unmeasured`。

路由 `GET /api/v1/projects/{id}/citation-sources` 必须通过 `project_for_user` 和 `with_tenant_read_context`。新增 measured、unmeasured、坏行、跨租户和重复请求稳定性测试。

**硬门槛**：迁移后的 Channels 与迁移前 fixture 的域名、计数、share、证据数量一致后，才允许合并 P0-3。CI 必须继续运行旧 Channels 聚合测试；在 feature flag 和旧逻辑移除前，旧测试不得删除或降级为非阻塞。shadow 差异、旧测试失败或 fixture 不稳定时，P0-3/P1-1 的合并检查必须失败。

## 5. P0-1：Hero

在 `web/index.html` 保留现有 evidence chain，增加以下价值表达：

`Track your AI search visibility. Build the assets AI actually cites.`

副标题强调“发现缺口、生成站内资产、用可追溯证据验证”，增加静态 score preview 和信任占位；不出现排名、提及或客户 logo 承诺。390/1024/1440 宽度无溢出，canonical、`/llms.txt` 和现有 SEO 结构不变。

## 6. P0-2：定价矩阵

重构 `web/pricing.html` 为横向对比表，保留 `$79/$199/$499`、OfferCatalog、canonical 和 OG 标签。只展示当前代码真实支持的：active projects、BYOK-first、采样模式标签、审计、工单、验收、交付包、白标、API/MCP、Enterprise SSO。

不得写模型数量、团队人数或固定 ticket 额度，除非 `api/billing/plans.py`、限制逻辑和测试先实现。试用统一写 14-day Starter trial；FAQ 明确计划不保证 AI mentions 或 rankings。375px 仅要求横向滚动，不得破版。

## 7. P0-3：Overview 摘要卡

在现有 KPI 与 visibility plan 之间新增 Citation Source Intelligence 摘要，调用 P0-0 API，展示 Top 5 域、type、share、evidence_count、run 时间，并链接到 `#/channels`。无数据显示 `Unmeasured · Run a sample`；请求失败不得阻断 Overview。

## 8. P1-1：Channels 增强，不新增视图

扩展现有 `web/app/views/channels.js`：

- 顶部显示 run、total citations、measured domains 和未测原因。
- 表格增加 Suggested asset 和 Action。
- 按 share 降序、domain 升序稳定排序，最多 Top 20。
- `community` → FAQ/事实块；`editorial` → 比较矩阵/`llms.txt`；`knowledge` → Schema/entity definition；`review` → review schema/testimonial block。
- Action 仅有 View evidence 和 Create ticket；创建工单带 domain、run_id、建议资产和证据链接。
- 参数化-only 样本明确显示不产生联网引用。

浏览器验收只检查 `#/channels` 有/无数据不白屏、能够跳 Engines 回放和 Plan 工单；不引入 `#/citations`。

## 9. P1-2：Plan 内 Content Opportunities

扩展现有 `brand_opportunities.assess()`，机会 ID 固定为 `hash(question_id + gap_type + suggested_page_type)`，排序和输出字段稳定。每条必须关联真实 question 或 sample；无样本为 `not_covered` / `待验证`。

字段：`question`、`question_id`、`evidence_count`、`gap_type`、`suggested_page_type`、`acceptance_criteria`、`evidence`。Acceptance 只要求同问题、同采样模式、可比较 cohort 的复测，并记录 `improved / unchanged / regressed / unmeasured`，不要求提升。

在现有 `plan` 增加 Opportunities tab。Create ticket 必须写入 question_id、证据摘要和验收条件；相同机会重复点击应复用或拒绝，不得产生重复工单。

## 10. P1-3：Entities 人工清单

新增 `offsite_entities.py`、项目路由和 `entities` 视图。文件固定为 `work/<tenant>/<slug>/offsite_entities.json`，写入使用项目锁。

后端返回完整 canonical list：固定 6 项（official site、Wikipedia/Wikidata、LinkedIn、X、Facebook/Instagram、Google Business）使用固定 ID；citation 派生媒体/目录项使用规范化域名 hash；custom 使用明确 `platform=custom`。每项包含 `id`、platform、url、status、evidence_url、reviewer_note、updated_at、source。

仅当项目从未手动保存过 `offsite_entities.json`（不存在文件且没有保存标记）时，首次读取才显示固定 6 项和最多 2 个 pending 动态项；一旦用户保存过，即使保存结果为空，也不得再次自动预填。动态项被删除后写入 tombstone，citation 聚合不得绕过该 tombstone 重新生成同一项；只有用户主动恢复或清除 tombstone 后才可重新出现。首次保存写入完整列表。状态仅允许 `pending`、`consistent`、`needs_fix`。前端明确“人工复核、无自动发布”，编辑不发起第三方请求。

## 11. 测试、发布和回滚

每项必须有 API 成功/空数据/坏产物/权限/跨租户/幂等测试；文件测试确认不写 Postgres、路径不越租户、重复运行不重复追加。

每次任务完成运行：

```bash
cd engine && python3 -m unittest discover -s tests
cd api && pytest tests/ -q
python3 -m compileall -q api
git diff --check
```

受影响页面在 390、768、1280/1440 宽度验收；有数据和空数据均不白屏。任何真实 provider 不可用时标记未测，不用 mock 伪造通过。

发布前保留现有 Channels、Plan 和 Outreach 路径；新 adapter 出现异常时，UI 显示 Unmeasured 并保留原始样本回放，不删除 last-known-good 产物。CI 卡点必须验证旧 Channels 测试仍存在且为阻塞检查，直到 feature flag 关闭并完成旧逻辑移除。

## 12. 交付记录

每个 PR/提交记录改动文件、API 契约、统计口径、状态定义、测试结果、DOM/截图证据、未完成项和回滚方式。所有汇总数字必须能回链 `run_id`、文件路径或 evidence URL。

## 13. 运行时、迁移和数据完整性

### 13.1 Run 完整性判据

`citation_sources.aggregate()` 只接受满足以下条件的 run：文件名包含合法 `run_id`；文件 mtime 已稳定至少 2 秒；文件中至少有一条终止记录或对应 job 状态为 `succeeded`；读取过程中 inode、size 和 mtime 前后不变。否则跳过该文件，继续寻找最近一个满足条件的 run。

若没有完整 run，返回 `status=unmeasured`。不跨 run 合并，不读取正在追加的文件。单行 JSON 解析失败只跳过该行并增加 `warnings`；若有效行数为零则仍为 `unmeasured`。

### 13.2 Shadow migration

P0-0 先保留现有 Channels 聚合逻辑，新增 adapter 以 shadow mode 对同一 fixture 和生产只读样本进行比对。连续通过 API 契约测试，且域名、计数、share、证据数量差异为零后，才切换 Channels、CSV、Overview 到新 adapter。切换保留一个可配置的旧逻辑回退开关和至少一个部署周期的日志。

### 13.3 正式 API schema

`GET /api/v1/projects/{id}/citation-sources` 的字段固定为：

- `status`: `measured | unmeasured`
- `run_id`: string 或 null
- `sampled_at`: ISO-8601 UTC string 或 null
- `total_citations`: integer >= 0
- `domains`: array，每项为 `{domain: string, type: enum, count: integer >= 1, share: number 0..1, evidence_urls: string[], evidence_count: integer >= 0}`
- `warnings`: string[]，不包含密钥、原始回答或凭据
- `unmeasured_reason`: string 或 null

错误格式继续使用项目统一的 `{"error": "msg"}`；无数据和部分坏行仍返回 HTTP 200。跨租户统一 404。

## 14. 机会和实体的确定性规则

### 14.1 Opportunity 统计门槛

- `not_covered`：同一问题至少有 3 条有效回答，且品牌未被提及；少于 3 条只能是 `unmeasured`。
- `low_mention`：至少 5 条同口径有效回答，mention rate > 0 且低于项目目标；没有目标时不生成该类型。
- `conflict`：至少 2 条有效回答与已批准事实存在相反断言，并保留两条证据。
- 失败行、参数化-only 行和不同采样模式不得混入同一比较分母。

机会 ID、排序、`evidence_count` 和 `acceptance_criteria` 在相同输入下必须完全稳定。重复创建同一机会时复用已有 ticket 或返回 409，不追加重复任务。

### 14.2 Entity 生命周期

固定 6 项使用不可变 ID；动态项使用规范化域名 hash。用户删除动态项后写入 tombstone，后续自动派生不得在 30 天内重新生成同一项，除非用户主动恢复。用户修改的 URL、状态和备注不得被下一次 citation 聚合覆盖。

后端拒绝非 HTTP(S) 协议、userinfo、内网地址、超长 URL 和控制字符；保存只写文件，不向 URL 发起请求。

## 15. 性能、发布和回滚

- Citation 聚合只扫描最新候选文件及必要的前一个文件，单项目文件大小和行数设上限；超过上限返回 warning 并保持可用结果。
- 目标：API p95 < 300ms（不含数据库鉴权），Overview 不因卡片请求失败超过 1 秒；超过预算时启用基于 `run_id + mtime` 的短 TTL 只读缓存，缓存不得成为 SSOT。
- 增加 feature flag `citation_intelligence_v1`，默认对内部租户开启；API、Overview 卡、Channels 增强分别可独立关闭。
- 发布顺序：adapter shadow → API → Channels → Overview → Opportunities → Entities。每一步观察 24 小时关键错误和数据差异。
- 回滚只关闭 feature flag 或恢复旧聚合器，不删除 JSONL、tickets 或 last-known-good 交付产物。

## 16. 产品验证和可访问性

上线后记录：Overview → Channels 点击率、Channels → ticket 转化率、opportunity → ticket 转化率、ticket 完成率、Verify 启动率、首份报告到首张工单耗时和 7/30 日复访率。指标只衡量采用和闭环，不作为提及/排名承诺。

所有新增文案使用 i18n key，至少覆盖 `en`、`zh`，其他 locale 使用英文 fallback；不得在视图中散落新硬编码文案。表格支持键盘、`caption`/列标题语义、窄屏横向滚动和明确的空/未测状态。

## 17. 任务责任和完成合同

每个任务必须在开始时登记 owner、输入 fixture、改动文件、依赖、预计测试文件和回滚开关；结束时必须提交 API schema、样本路径、测试结果、DOM/截图证据和未完成项。任何依赖真实 provider 的验收都标记为 `not measured`，不得以 mock 代替生产事实。

## 18. 变更记录

- Final：取消独立 `#/citations`，将 Citation Intelligence 完整并入 `channels`；补充最终页面职责表、adapter 迁移门槛、数据一致性门槛和回滚要求。
- Final completeness pass：补齐 run 完整性、shadow migration、正式 schema、性能预算、机会最小样本、实体首次保存开关与 tombstone、feature flag、上线指标、i18n、可访问性、责任登记和逐步回滚。P0-0 最少 1.5 天；旧 Channels 测试在 flag 移除前保持 CI 阻塞。该文件为唯一执行合同，取代 v3/v4。
