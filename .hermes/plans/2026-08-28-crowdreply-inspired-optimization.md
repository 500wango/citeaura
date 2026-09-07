# CiteAura 对标 CrowdReply 优化计划

> 版本 2026-08-28 · 状态 待审核 · 不执行代发
> 决策边界：CrowdReply 的核心价值在托管号代发（Engagement Engine），CiteAura 明确不碰代发；本计划只学它的包装、定价、情报层，履约层坚持白帽资产沉淀。

---

## 1. 结论先行

- CrowdReply 不是技术神仙，是叙事神仙：把灰产 Reddit 代发包装成 `AI Search Visibility + Engagement Engine`，订阅+credits 双重收费，$99/$299/$499 锚点已成赛道标准。
- 对 CiteAura **0% 参考**的是托管号代发，**100% 参考**的是 GTM/定价/落地页结构，**60% 参考**的是功能形态（可见度追踪、引用源情报、Listening）。
- CiteAura 的机会不是去抢 Reddit 声量租赁，而是做它的反面：**CiteAura 帮你在站内建 AI 愿意引用的护城河，CrowdReply 帮你在站外买提及；站外的随时被删，站内的才是资产。** 两者互补，但后者才符合 `work/<tenant>/<slug>/ 文件 SSOT + BYOK + 交付包` 的长期价值。

---

## 2. 差距诊断（CiteAura 现状 vs CrowdReply）

| 维度 | CrowdReply 做法 | CiteAura 现状 | 差距 |
|---|---|---|---|
| Hero 叙事 | `Track rankings, monitor cited conversations and place your brand where it matters.` 三段式价值一句话讲清 | Hero 是 `Find out why AI overlooks your brand — and get the exact fixes` + 证据链 `AI answer → gap → change → verify → re-test`，偏技术诚实，但缺少一句老板能转发的价值主张 | 缺一句对外销售话术 |
| 可视化 | AI Visibility Score + Top citation sources + Competitor outrank 放在首屏 | Overview 有 mention_rate/grade/tickets/engines 四个 KPI，但没有单一 Visibility Score；Engines 矩阵在二级页 | 首屏冲击力弱 |
| 引用源情报 | Citation Source Intelligence：哪些域名被 AI 引用、竞品在哪而你不在 | 有 `metrics/citations` 和 `engine` 采样，但没有聚合到「这个品类 AI 最爱引用的 20 个域名」视图 | 客户看不懂该去哪里发力 |
| Listening | Ranked Threads / New Threads / Alerts / Single Search，实时发现新对话 | 只有 `questions` 题库和 `gaps`，没有对站外讨论的监听入口 | 缺少站外信号 |
| 资产交易 | 40k 外链媒体商城，加入购物车即下单 | `assets` 只有 llms.txt/JSON-LD/snippets/drafts，偏技术资产 | 缺少「可交易的权威度」叙事 |
| 定价呈现 | 对比表极度详细：prompts/keywords/models/platforms/credits/团队人数全部横向对比，Most Popular 锚定 Growth | pricing.html 只有 4 行文字描述，无对比矩阵，无 Most Popular，无 Top-up 说明 | 转化率吃亏 |
| 信任状 | 4.9 分 + 5000+ brands + 3 个具名 case + ROAS/$1M 数字 | 只有技术可信度（可追溯证据、采样模式标注），缺客户证言和 ROI 数字 | 冷启动信任不足 |

---

## 3. 优化目标与硬约束

**目标：** 不碰代发的前提下，把 CrowdReply 已验证的“情报→行动→验证”闭环，用白帽资产形态在 CiteAura 内跑通，并把转化率短板补齐。

**硬约束（违反即不批）：**
1. 不引入托管号、代发、点赞、上票等站外代操作；所有站外建议仅为清单+人工复核队列。
2. 保持 `engine/` 公共接口兼容，SaaS 逻辑留在 `api/adapters/`。
3. 文件 SSOT 不动：产物仍在 `work/<tenant>/<slug>/`，DB 只存计划/目标/元数据。
4. 采样诚实：每个引擎必须标注 `API·参数化知识 / API·联网检索 / 人工·产品端`，不暗示 API 结果等于网页端。
5. 不承诺排名/提及/流量。

---

## 4. 优化方案（分三期，P0 必做）

### P0 — 落地页与定价转化（1 周，不碰后端）

**P0-1 落地页 Hero 重构（对标 CrowdReply 首屏）**
- 标题改为双行：`Track your AI search visibility. Build the assets AI actually cites.`
- 副标题保留证据链，但增加一句销售话术：`Other tools tell you where you're missing. CiteAura builds what's missing — and proves it.`
- 在 Hero 右侧 console 增加 `Visibility Score` 单一分数卡（复用现有 analytics 加权分，不新增算法），下方三指标：Top citation sources / Competitor outrank / Citation gap count。
- 增加 `Trusted by` 占位区（先用设计稿占位，上线后替换为真实客户 logo+数字）。
- 文件：`web/index.html` sections 1-2, `web/assets/styles/landing.css`

**P0-2 定价页对比矩阵（直接抄 CrowdReply 表格形态）**
- 将当前 4 行文字表改为横向对比矩阵：行 = AI Search Visibility & Tracking / Citation Intelligence / Audit & Tickets / Assets & Delivery / Platform & Team，列 = Starter $79 / Pro $199 / Agency $499 / Enterprise Custom。
- 增加 Most Popular 徽标在 Pro 上；增加 `Need more projects? Top up` 文案复用现有 usage_counters 逻辑（不新增 credits 概念，仅表达容量）。
- 增加 FAQ：`What's included in trial? / Do credits roll over? / Can I upgrade anytime?` 对齐 CrowdReply 的 FAQ 结构。
- 文件：`web/pricing.html`, `web/assets/styles/seo-pages.css`

**P0-3 控制台 Overview 补一屏「引用源情报」卡**
- 在 `web/app/views/overview.js` 的 Engines 矩阵上方增加 `Citation Source Intelligence` 卡：Top 5 被引域名（从 `metrics/*.json` 的 citations 聚合算，不调外部 API）、你的覆盖率、竞品覆盖对比。无数据时显示 `Unmeasured · Run sample to populate`，不显示 0%。
- 复用 `readiness` 卡样式，不新增组件。
- 文件：`web/app/views/overview.js`, `api/readiness.py` 仅加聚合函数，不新增表

**验收 P0：**
- 落地页首屏 5 秒内能回答“这是干什么的、跟 CrowdReply 有什么不同、怎么证明有效”。
- 定价页对比矩阵与 CrowdReply 信息密度对齐，但价格保持 CiteAura 现有 $79/$199/$499。
- Overview 单分数+引用源卡在有/无采样数据时均表现诚实。

### P1 — 白帽情报层（2-3 周，需前后端）

**P1-1 Citation Source Intelligence 独立视图（白帽版）**
- 新视图 `web/app/views/citations.js`（或复用 `gaps.js` 扩展）：按品类聚合 AI 回答中出现的高频引用域名、类型（Reddit/媒体/百科/官网）、你的品牌是否出现在该域、建议动作（站内资产/站外清单项，不含代发）。
- 后端：`api/adapters/citation_readiness.py` 增加聚合器，从 `sample` 原始回答的 citations 字段提取域名，计数+去重；结果写 `work/<tenant>/<slug>/citation_sources.json`，DB 不新增表。
- 前端：表格列 = Domain | Type | Citation share | You vs Competitors | Suggested asset | Evidence。Suggested asset 仅指向已有的 llms.txt/FAQ/对比矩阵等资产类型。
- 对标 CrowdReply 的 `See which domains AI models cite for your category. Find gaps where competitors appear and you don't.` 但动作是建资产，不是买外链。

**P1-2 Content Opportunity 升级为可交付矩阵（复用 brand_opportunities）**
- 现有 `api/adapters/brand_opportunities.py` + `web/app/views/plan.js` 已有机会生成，将输出升级为 `问题 → 证据 → 建议页面类型 → 验收条件` 四列矩阵，与 CrowdReply 的 `Best CRM for startups 2.3k Visitors/mo` 列表形态对齐，但 visitors/mo 换成 `AI 提及缺口 + 证据数`。
- 不自动写内容，只给大纲和验收标准，呼应 PRD 的“不自动发布”。

**P1-3 站外实体清单（人工复核队列，白帽版 Listening）**
- 新增 `Off-site Entity Checklist`：第三方品牌信息一致性清单（官网/百科/行业目录/社媒主页），状态 = 待核实/已一致/需修正，每项关联证据 URL 和复核人。
- 形态对标 CrowdReply 的 Social Listening，但不做实时爬 Reddit，仅做清单+复核，避免平台风险和合规风险。对应 tasks.md Phase 5.6 的前置要求。
- 文件：`web/app/views/channels.js` 或新建 `web/app/views/entities.js`，`api/projects/brand_opportunity_routes.py` 扩展

**验收 P1：**
- 任意项目跑一轮 sample 后，citation 视图能列出 Top 引用域且每行可追溯到原始回答证据。
- 每个机会至少关联一个真实问题或采样证据，无证据显示“待验证”。
- 站外清单无自动发帖/上票入口，全部为人工复核。

### P2 — 可选增强（评估后再做，不在本期承诺）

**P2-1 Backlinks Marketplace 的白帽替代：权威度资产包**
- 不做外链商城，仅在 `assets` 增加 `Authority Footprint` 说明页：解释 AI 为何引用有外链背书的源，并给出白帽外链建设清单（媒体投稿/目录提交/合作伙伴页），每项为工单而非一键购买。避免 CrowdReply 的“买外链”合规风险。

**P2-2 Listening Lite（需评估成本）**
- 仅在用户主动触发 Single Search 时，对 Reddit/Quora 做关键词检索并展示结果，不做常驻监控和自动 Alerts，避免持续爬虫成本和平台对抗。需先评估检索来源的稳定性再决定是否做。

**P2-3 客户证言与 ROI 包装**
- 在落地页增加 Case Study 占位，待有真实客户数据后再填充，不伪造 $1M 这类数字。先用方法论和可验证证据链建立信任。

---

## 5. 不做清单（明确拒绝）

- 不做托管号代发、代评论、代发帖、点赞/投票提升。
- 不做按条计费的 credits 消耗品；计费仍按项目数/月，与现有 `subscriptions / usage_counters` 对齐。
- 不把目录/外链/发帖数量作为核心成功指标。
- 不接入 GSC/GA4 做归因直到完成 Phase 5.6 的低敏字段与归因窗口定义。
- 不重写 `sample/audit/verify/deliver` 核心管线。

---

## 6. 实施顺序与发布闸门

1. **P0 先行**（1 周）：落地页+定价+Overview 单分数卡，纯前端，可独立上线 A/B。
2. **P1 串联**（2-3 周）：先做 P1-1 citation 聚合（数据基础），再做 P1-2 机会矩阵，最后做 P1-3 站外清单。
3. **P2 评估**（按需）：需真实客户数据后再决定是否做 P2-1/P2-2。
4. 每个阶段必须通过：`engine` 全量回归、`api/tests` 回归、文件产物校验、租户隔离测试、浏览器流程验收。

---

## 7. 交付物与审核点

- 交付物：本计划文档 + 三个阶段的 PR（每阶段独立分支）。
- 请你审核：
  1. 是否接受 P0 的 Hero 文案方向（`Build the assets AI actually cites` vs 现有证据链叙事）？
  2. 是否接受定价页改为对比矩阵但保持 $79/$199/$499 不变，还是要对齐 CrowdReply 的 $99/$299/$499？
  3. P1-1 citation 视图是否值得投入（需解析 citations 字段，工作量约 2-3 天）？
  4. 是否现在就做 P1-3 站外清单，还是等有客户再做？

> 通过后我按 P0 → P1 顺序开工，每完成一期提审一次。
