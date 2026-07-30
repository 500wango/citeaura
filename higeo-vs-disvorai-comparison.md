# HiGEO vs DisvorAI（开源）对比与可借鉴点

> 更新：2026-07-30  
> 来源：https://www.higeo.ai/ 、https://github.com/aigclink/disvorai 、https://disvorai.cc  
> 用途：为 ForgeGeo / DisvorAI SaaS 二次开发提供产品参考

---

## 1. 一句话定位

| 产品 | 定位 |
|------|------|
| **HiGEO** | 精简云端 GEO：**监控 + 优先级 Playbook**。输入域名 → 扫 3 引擎 → 给你要做什么。**不写内容、不交付工单闭环**。 |
| **DisvorAI 开源** | 端到端 **实施平台**：现状 → 诊断 → 策略 → 工单 → 资产 → 执行 → **自动验证 → 客户交付包**。自托管、无账号。 |
| **我们的 SaaS 方向** | 以开源闭环为内核，吸收 HiGEO 的 **上手体验 / 商业包装 / 站外引用颗粒度 / 诚实叙事**，做成 **可交付的多租户 GEO 实施 SaaS**。 |

---

## 2. 功能对照表

| 维度 | HiGEO | DisvorAI 开源 | 谁更强 | SaaS 该怎么做 |
|------|-------|--------------|--------|---------------|
| 上手 | 只输域名，自动推断品牌/话题/约 100 题 | 向导 + CLI；事实/题库需人工校对 | **HiGEO** | 必须学：零配置 onboarding |
| 引擎覆盖 | **3 个且点名**：ChatGPT(browsing)、Perplexity、Google AI Overviews | **15 引擎矩阵**（含 CN：Doubao/DeepSeek/Kimi/GLM…）+ 手动 sheet | **DisvorAI 广度**；HiGEO 诚实 | 默认 3 全球核心 + CN 包可开关 |
| 问题集 | ~100 买家问题，可编辑 | 7 类问题库 + 百度/Google 联想扩展 | 各有千秋 | 自动生成 + 可编辑 + 需求词挖掘 |
| 监控指标 | 提及率、引用率、原始答案、词云 | 提及/排名/引用份额、样本回放、诊断类型 | **DisvorAI 更细** | 两者都要；词云学 HiGEO |
| 竞品 | **答案里自动发现**，无需预填 | 有竞品表 + 最强引擎 | **HiGEO 更省事** | 默认自动发现 + 可锁定名单 |
| 行动输出 | **Impact×Effort 排序的 Playbook**（Facts / Content / Tech / Off-site） | 结构化工单 + 验收标准 + 进度条 + 回归重开 | **DisvorAI 更深** | Playbook UI 学 HiGEO，底层用工单模型 |
| 站外引用 | **到具体 URL/帖子 + 精确 ask**（加入 listicle / 回帖） | 19 渠道地图 + 权重，粒度偏渠道 | **HiGEO 更可执行** | 必须学：page-level off-site tickets |
| 内容生产 | **明确不做**：只给 brief | **Workbench + AI 草稿 + 可引用性预检 + 发布清单** | **DisvorAI** | 保留 workbench（差异化） |
| 技术修复 | schema 等建议 | 6 维站点审计 + 点到工单 | **DisvorAI** | 保留并接到 playbook |
| 品牌事实 | LLM-ready facts + sample schema | 事实库 → llms.txt / JSON-LD 生成 | **DisvorAI 更深** | 事实库 + /facts 页模板（学 HiGEO 包装） |
| 验证闭环 | 可 re-scan 看趋势；无程序化验收 | **自动 verify + 回归重开工单 + before/after** | **DisvorAI** | 核心护城河，必须保留 |
| 交付物 | Brand Visibility Report + playbook | 诊断报告/策略/计划/CSV/客户包 | **DisvorAI 更适合代理** | 一键客户交付包 = 代理卖点 |
| 多市场 | markets/languages 高级设置 | CN / Global / Both 一等公民 | **DisvorAI CN** | 中文引擎+渠道是中国市场壁垒 |
| 协作/账号 | 完整 SaaS 账号 | **无**（127.0.0.1、无 auth） | **HiGEO** | 多租户/角色必做 |
| 定价 | **$99/月 单档**，14 天试用无卡 | 免费；自付采样 API | HiGEO 商业化清晰 | 可抄单档或 Starter/Pro，先简单 |
| 叙事诚实 | 不写内容、不保证上榜、不虚报引擎 | 不造假指标、未测显示 unmeasured | 都好 | **必须抄诚实边界** |
| 增长内容 | 7 行业 GEO guides | 方法论文档 + references 语料 | **HiGEO GTM** | 行业指南 + 样本报告 SEO |
| 部署 | 云 SaaS | 自托管 Python 3 依赖 | — | 云 SaaS + 可选私有化 |

---

## 3. HiGEO 最值得抄的 10 点（按优先级）

### P0 — 直接影响转化与留存
1. **Domain-only onboarding**  
   爬站推断 brand / description / topics / questions，禁止首屏填一堆表。  
2. **Playbook = Impact × Effort 排序**  
   四类动作：Facts / Content / Technical / Off-site；带 P1/P2 与状态。  
3. **站外引用到「具体页 + 具体 ask」**  
   比「去做知乎/Reddit」可执行一个数量级；工单文案直接可派给运营。  
4. **原始答案可点开**  
   每个数字背后有 raw answer；建立信任、方便代理给客户看。  
5. **竞品从答案自动浮现**  
   零配置；可选「锁定竞品」作为高级能力。

### P1 — 商业与包装
6. **单档定价 + 无卡 14 天全功能试用**  
   降低决策成本；FAQ 写清「试用结束不会自动扣款」。  
7. **诚实 scope**  
   引擎点名、写清不写内容、不保证 mention；比吹 15 引擎但 5 个要手填更可信。  
8. **行业 Guides 作为获客漏斗**  
   B2B SaaS / 电商 / fintech / 代理 / 房产 / 律所 / 医疗 — 与产品同标准。  
9. **词云「AI 如何描述你」**  
   营销向可视化，利于截图传播与销售。  
10. **价值叙事：vs 代理 vs 自建**  
    定价页把「否则要花多少」算清楚（代理 retainer / 自建 API 管线）。

### 不必抄 / 慎抄
- **只覆盖 3 引擎、不做内容生成**：那是他们的边界；我们有开源 workbench，应做成可选模块，而不是砍掉。  
- **永久无免费 scan**：可学「试用即全功能」；是否完全无 free tier 看获客成本。  
- **月付唯一**：可先 monly，年付折扣后置。

---

## 4. DisvorAI 开源必须保留的优势（相对 HiGEO 的护城河）

1. **端到端闭环**：工单 → 资产 → 发布 → **程序化验证 → 回归重开**  
2. **客户交付包**（代理/咨询刚需）：报告 + 策略 + CSV + 验收表  
3. **CN 引擎 + CN 渠道**（百科/榜单/微信/头条等 citation 权重）  
4. **Content workbench + 可引用性预检 + fabrication lint**  
5. **可复现指标与「数字从哪来」面板**（不黑箱打分）  
6. **数据可私有化**（代理/大客户合规）  
7. **实证 references**（方法层可讲清，利于信任与 SEO）

---

## 5. 产品缝隙（我们该占的位置）

```
                    监控深度
                      ↑
         Peec/Scrunch |  HiGEO（监控+Playbook）
                      |
    ──────────────────┼──────────────────→ 落地深度
                      |
         DisvorAI OSS  |  ★ ForgeGeo SaaS
         （全闭环自托管）|  （云端闭环 + HiGEO体验
                      |   + 交付包 + CN）
```

**一句话卖点建议**：  
「HiGEO 告诉你该做什么；$99 级竞品多数停在 playbook。我们基于开源全流程，**把 playbook 变成可验收工单、内容与交付包，并支持中文引擎。**」

---

## 6. 建议吸收进 PRD 的具体功能增量

| 来自 HiGEO | 落到开源二次开发 |
|------------|------------------|
| Domain-only setup | `new`/`bootstrap` 默认「只填 URL」；高级字段折叠 |
| ~100 buyer questions 自动生成 | 增强 bootstrap 问题生成 UX；一键接受/编辑 |
| Impact/Effort playbook UI | 工单列表默认按 impact/effort 排序；四类型标签 |
| Off-site page-level asks | 新 ticket 类型 `offsite`：url、ask_text、influenced_questions[] |
| Word cloud framing | Overview 增加 framing 词云，点击跳 raw sample |
| Auto competitors from answers | sample 解析后写 competitors，无需预配置 |
| Sample report + method 页 | 公开 `/method`、`/sample-report` 营销页 |
| 单档 $99 叙事 | 定价页先 1 档 Pro；代理版另开 Delivery 附加 |
| 行业 guides | 内容站 7 行业 GEO 指南（可后置） |
| 明确不保证上榜 | 法务/FAQ/产品文案固定边界 |

| 开源已有、HiGEO 弱 | 强化为付费差异化 |
|--------------------|-------------------|
| Auto-verify + reopen | Dashboard「验收」主路径 |
| Deliverables package | 一键客户 ZIP/HTML |
| CN engines/channels | 市场开关 `cn`/`global`/`both` |
| Workbench + publish | Pro+ 功能；Starter 可只 playbook |
| llms.txt / JSON-LD 生成 | 与 HiGEO「facts+schema」合并包装 |

---

## 7. 定价与包装参考（不必照搬）

| | HiGEO | 建议我们 |
|--|-------|----------|
| 结构 | 单档 $99 | 可 **Pro $99–149** 对标全球；**CN 代理 Delivery** 另售或更高档 |
| 试用 | 14 天全功能无卡 | 强烈建议同样 |
| 对标话术 | vs 代理 / vs 自建 | 再加 **vs 纯监控 GEO**、**vs 开源自托管运维成本** |

注意：HiGEO 法律实体 DT Global Ventures Ltd（伦敦），偏全球英文市场；我们若做 CN，引擎与支付（微信/支付宝）是增量，不是简单镜像。

---

## 8. 结论

- **HiGEO** = 优秀的 **GEO 产品化教科书**：零配置、Playbook、站外颗粒度、诚实叙事、单档定价、内容获客。  
- **DisvorAI** = 更强的 **实施与验证引擎** + **CN** + **代理交付**，缺的是 SaaS 体验与商业包装。  
- **最好做法**：二次开发时 **内核用 DisvorAI 闭环**，**壳与关键路径学 HiGEO**；差异化钉死在 **可验证工单 + 交付包 + 中文矩阵 + 可选内容工作台**，避免做成第三个「只看排名的 $99 监控工具」。

---

## 9. 下一步（产品）

1. 把本文 P0 五项写进 PRD「Must-have from HiGEO」  
2. 样板客户旅程对齐 HiGEO 三步：Domain → Scan → Report+Playbook，再延伸 Ticket→Verify→Deliver  
3. 公开页：Method + Sample Report + GEO vs SEO（抄其内容策略，不抄文案）  
4. 品牌仍建议避开 GeoForge/GEOforge 冲突；产品名与竞品叙事分开
