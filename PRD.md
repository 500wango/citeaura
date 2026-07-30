# DisvorAI（基于 GeoLook 开源二次开发）产品需求文档 PRD

> **版本**：v1.1  
> **日期**：2026-07-30  
> **状态**：可交付 AI 编程助手实现  
> **产品目录**：`~/project/disvorai`  
> **开源基线**：https://github.com/aigclink/geolook（MIT，fork 来源 aigclink/geolook；用户 fork：500wango/geolook）  
> **官网参考竞品**：https://www.higeo.ai/  
> **对比文档**：`~/project/geolook-saas/higeo-vs-geolook-comparison.md`  
> **约束**：**所有开发工作基于开源版二次开发**，禁止从零重写核心 GEO 管线；在其之上加多租户 SaaS、商业包装与 HiGEO 级体验。

---

## 0. 给实现者的硬约束

1. **Fork / 引入** `aigclink/geolook`（或 `500wango/geolook`）代码与 `scripts/`、`references/`、测试，作为业务内核。  
2. **不要**用全新 stack 重写 sample/audit/plan/verify 逻辑，除非有测试证明行为等价且 PR 明确说明。  
3. SaaS 层（账号、计费、多租户、调度、API 网关）可新建，但须 **调用或包装** 现有 CLI/模块（`geo.py`、`sample.py`、`audit.py`、`tasks.py`、`verify.py`、`deliver.py` 等）。  
4. 数据默认落在 per-tenant 的 `work/<tenant>/<slug>/`（或等价 DB + 对象存储镜像）；保留 JSON/Markdown 可导出。  
5. 指标诚实：未测显示 unmeasured，不伪造引擎覆盖。  
6. 中文优先文案可配置；引擎矩阵保留 CN 一等公民。

---

## 1. 背景与问题

### 1.1 GEO 定义

GEO = **Generative Engine Optimization**：让 ChatGPT / Perplexity / Gemini / DeepSeek / 豆包等在回答用户问题时 **主动提及并引用你的品牌**。不是 IP 地理位置，也不是传统 SEO 排名工具。

### 1.2 用户痛点

| 痛点 | 开源已解决部分 | 仍缺（SaaS 要补） |
|------|----------------|-------------------|
| AI 从不提及品牌 | 多引擎采样 + 提及/排名/引用 | 零配置上手、云端持续扫 |
| 不知道为什么 | 6 维审计 + gap + 渠道图 | Impact×Effort 可读 Playbook |
| 建议落不了地 | 工单 + 验收标准 | 团队协作、状态同步 |
| 做完有没有用 | 自动 verify + before/after | 定时 re-scan、趋势 |
| 代理交付痛苦 | 一键交付包 | 多客户项目、白标、计费 |
| 自托管无账号 | 刻意设计 | 多租户、权限、账单 |

### 1.3 竞品一句话

| 产品 | 定位 |
|------|------|
| **HiGEO** | 云端监控 + 优先级 Playbook；$99/月；3 引擎；**不写内容、不闭环验收** |
| **Peec / Scrunch / AthenaHQ / Goodie 等** | 多为 AI 可见性 **监控** SaaS |
| **GeoLook 开源** | 自托管 **端到端实施**；无 SaaS |
| **本产品 DisvorAI** | 开源闭环为内核 + HiGEO 级体验壳 + 交付/CN/验证护城河 |

### 1.4 产品一句话卖点

> 多数工具停在 playbook；**DisvorAI 把 playbook 变成可验收工单、内容与客户交付包，并支持中文引擎。**  
> （对标：HiGEO 告诉你做什么；我们基于 GeoLook 让你做完并能证明做完。）

---

## 2. 目标与非目标

### 2.1 目标（MVP 30 天可演示）

- 用户注册 → 只填 **域名** → 自动 bootstrap → 看到 Visibility Report + Playbook  
- 可将 Playbook 项转为 **工单**，执行后 **自动验证**  
- 一键导出 **客户交付包**（HTML/CSV/报告）  
- 支持市场：`cn` / `global` / `both`  
- 计费：至少一种订阅（对标 $99 单档可先做）+ 14 天试用模型（可配置）

### 2.2 非目标（MVP 不做）

- 保证 AI 一定提及品牌  
- 覆盖「所有」助手却不点名（禁止虚报）  
- 替用户全自动发布到全网无确认  
- 从零重写采样/审计算法  
- 电影解说/视频解说类方向（与产品无关，禁止塞进 roadmap）

---

## 3. 用户与场景

### 3.1 角色

| 角色 | 诉求 | 付费点 |
|------|------|--------|
| **GEO 代理/咨询** | 多客户、交付包、可汇报 | Delivery / 多项目 |
| **品牌增长/SEO** | 自助 scan + 内部执行 | Pro 订阅 |
| **内容运营** | 工单、workbench、渠道清单 | 执行模块 |
| **管理员** | 成员、权限、账单、API Key 池 | Enterprise |

### 3.2 核心用户旅程（对齐 HiGEO 三步再延伸）

```
1. Enter domain only
2. System crawls + infers brand/topics/questions (~50–100)
3. Sample engines → Brand Visibility Report + Playbook (impact×effort)
4. [DisvorAI+] Convert to tickets → Workbench/assets → Publish (confirm)
5. Auto-verify + next sample round → before/after
6. One-click client delivery package
7. Schedule 7/14/30 day re-run
```

---

## 4. 信息架构（产品模块）

```
App
├── Auth / Billing / Team
├── Projects
│   ├── Overview（健康分、一句话结论、词云 framing）
│   ├── Engines（分引擎提及/引用、raw answer 回放）
│   ├── Questions（题库、诊断类型、编辑）
│   ├── Competitors（答案自动发现 + 可锁定）
│   ├── Diagnosis（Site audit / Gaps / Channels）
│   ├── Playbook（Facts/Content/Tech/Off-site，impact×effort）
│   ├── Tickets（结构化 + 验收 + 回归重开）
│   ├── Workbench（话题池、草稿、可引用性、发布清单）
│   ├── Assets（llms.txt、JSON-LD、snippets、DEPLOY）
│   ├── Verification（任务级/问题级 before-after）
│   └── Delivery（客户包、报告）
├── Settings（引擎 Keys、市场、调度、成员）
└── Public Marketing（Method、Sample Report、Guides）— 可后置
```

---

## 5. 功能需求（按优先级）

### 5.1 P0 — Must（含 HiGEO 合并项 + 开源护城河）

#### F-P0-01 Domain-only Onboarding（学 HiGEO）

- **输入**：URL + market（默认 both 或用户选 cn/global/both）  
- **系统**：爬取 → 推断 brand name / short description / topics / seed questions  
- **UI**：首屏禁止强制填竞品列表、大量手工字段；高级设置折叠  
- **验收**：新用户 3 分钟内进入「扫描中/已出报告」状态  

#### F-P0-02 引擎采样与 Visibility Report

- **包装开源** `sample` / analytics  
- **默认引擎策略**：  
  - Global 核心可配置为 ChatGPT / Perplexity / AI Overviews 等（能自动化的 API 优先）  
  - CN 包：DeepSeek / 豆包 / Kimi / GLM 等（开源矩阵保留）  
  - **UI 必须点名实际覆盖引擎**，与 HiGEO 同样诚实  
- **指标**：mention rate、rank、citation share；每条可打开 **raw answer**  
- **词云 framing**（学 HiGEO）：AI 描述品牌用词，点击跳到来源答案  
- **验收**：样本项目能出分引擎表 + raw 回放  

#### F-P0-03 自动问题集

- 生成约 50–100 买家问题（可配置数量）  
- 用户可一键接受或编辑  
- 开源 keyword mining（百度 suggest / Google autocomplete）作为「候选扩展」，**加入题库需确认**（保持开源纪律）  
- 诊断类型：suspected-negative > competitor-dominated > absent > low-ranked  

#### F-P0-04 竞品自动发现（学 HiGEO）

- 从采样答案解析竞品及 share of AI voice  
- 无需预填；支持「锁定竞品」高级选项  
- 与开源 Competitors 页合并  

#### F-P0-05 Playbook（Impact × Effort）（学 HiGEO）

四类：

| type | 含义 | 与开源映射 |
|------|------|------------|
| `facts` | 要发布的 LLM-ready 事实 | brand facts / /facts 页 |
| `content` | 要写的页面/文章 brief | workbench topics |
| `technical` | 站点技术修复 | audit → ticket |
| `offsite` | 站外引用争取 | **新增强化** |

- 每条：title、rationale、impact(0-100)、effort(0-100)、priority(P0/P1/P2)、status  
- 默认排序：impact/effort 降序（或 impact 高且 effort 低优先）  
- **一键「转为工单」**  

#### F-P0-06 Off-site 工单颗粒度（学 HiGEO，开源弱项补齐）

工单/playbook 项字段：

```text
type: offsite
url: https://...
ask_text: "请将我品牌加入该 listicle，作为 X/Y 的替代"
influenced_questions: [q_id...]
mention_you: bool
mention_competitors: [names]
channel: reddit|zhihu|listicle|baike|wechat|...
```

- 验收：代理可直接把 `ask_text` 派给运营  

#### F-P0-07 站点审计 + Gap + 渠道图（开源已有）

- 6 维 audit：robots / sitemap / llms.txt / accessibility / language / extraction blocks  
- 点击缺失 → 对应 technical 工单  
- 19 渠道地图 + 权重（references/）保留  
- CN/Global 分开度量  

#### F-P0-08 结构化工单 + 自动验证（开源护城河）

- 字段：rationale / owner / effort / window / acceptance criteria  
- 进度：first-measured → current → target  
- `verify`：重爬 + 规则判定；回归自动 reopen  
- 验收：演示项目中可验证类工单能自动变 done/reopen  

#### F-P0-09 Brand Facts + Deploy Assets（开源 + HiGEO 包装）

- 事实库 SSOT → 生成 llms.txt、JSON-LD、HTML snippets、DEPLOY.md  
- 提供「/facts 页」LLM-ready 事实列表（学 HiGEO 表述）  
- 未知标 unconfirmed，禁止一本正经瞎编（开源 lint 保留）  

#### F-P0-10 Content Workbench（开源差异化，HiGEO 明确不做）

- 话题池：未提及 + 无内容优先  
- AI 草稿 + 可引用性预检 + fabrication-risk lint  
- 分发 checklist 对齐目标渠道  
- 发布：GitHub / WordPress draft / 微信公众号草稿 / webhook — **必须人工确认**  

#### F-P0-11 Delivery 客户包（开源护城河）

- 一键：诊断报告、策略、执行计划、ticket CSV、验收表、HTML  
- 代理场景：按 project + date 打包下载  
- 验收：与开源 `deliver` / `deliverables` 行为对齐并云端可下  

#### F-P0-12 多租户与项目

- Tenant → Members(role) → Projects  
- 每 project 对应开源 `work/<slug>/` 语义  
- 多品牌切换  

#### F-P0-13 计费（MVP 可简）

- 建议先 **单档 Pro**（对标 HiGEO $99 或国内定价 99–299 元，配置化）  
- 14 天全功能试用、**不强制绑卡**（若支付栈暂不支持，文档标明后续）  
- 计量：projects 数、每月 sample runs / question×engine 次数  
- FAQ 文案：不保证 mention；不写「覆盖所有 AI」  

#### F-P0-14 诚实边界与法务文案（学 HiGEO）

产品内固定：

- 点名引擎列表  
- 不保证上榜/提及  
- 采样有噪声；趋势需多轮  
- 不替代律师/医疗建议等（若行业模板涉及）  

---

### 5.2 P1 — Should（30–60 天）

- 调度：7/14/30 天 full cycle / light loop（开源 operations）  
- 团队：邀请、角色（owner/editor/viewer）  
- 手动 sampling sheet 导入导出（开源已有）  
- 白标交付 PDF 页眉页脚  
- 公开 Method + Sample Report 营销页  
- 行业 Guides（B2B SaaS/电商/fintech/代理/房产/律所/医疗）— 内容运营可后置  
- 用户自带 API Key + 平台 Key 池（成本隔离）  
- 年付折扣  

### 5.3 P2 — Later

- SSO / SOC2  
- 与 Semrush/Search Console 集成  
- 自动外链 outreach 发送（高风险，需人工）  
- 移动 App  

---

## 6. 开源能力映射（实现索引）

| 开源模块（约） | SaaS 功能 |
|----------------|-----------|
| `scripts/geo.py` | CLI 兼容入口 / job runner |
| `bootstrap.py` / `crawl.py` | Onboarding、推断 |
| `sample.py` | 引擎采样、sheet |
| `audit.py` | 站点审计 |
| `analytics.py` | 指标、词云可加在其上 |
| `tasks.py` / `plan` | 工单、playbook 映射 |
| `generate.py` / `lint` | 资产与草稿质检 |
| `verify.py` | 自动验收 |
| `deliver.py` / `deliverables.py` / `report.py` | 交付与报告 |
| `publish.py` | 受控发布 |
| `jobs.py` | 后台任务 |
| `dashboard.py` + `ui.html` | 可先嵌入再替换为现代前端 |
| `references/` | 方法与渠道权重，禁止丢掉 |

**二次开发原则**：SaaS API 一层 `POST /projects/:id/cycle` 内部调用与 `geo.py cycle` 等价流水线。

---

## 7. 非功能需求

| 类别 | 要求 |
|------|------|
| 安全 | 租户隔离；`.env`/Keys 加密；默认不公网暴露无鉴权的开源 UI |
| 隐私 | 原始答案与客户站点数据按租户隔离；可删除导出 |
| 性能 | 单 project 全量采样异步队列；UI 不阻塞 |
| 可观测 | job 状态、失败原因、token/API 费用日志 |
| 合规 | 文案诚实；GDPR 删除权（P1） |
| 国际化 | UI i18n：zh-CN / en；市场 cn/global |
| 可靠性 | 采样失败单引擎降级，不整单失败吞掉 |

---

## 8. 技术架构建议（可调整，但须满足第 0 节）

### 8.1 推荐形态

```
[Next.js Web] → [API Gateway / Nest 或 FastAPI]
                    ↓
            [Job Queue: Redis/BullMQ 或 RQ]
                    ↓
            [GeoLook Worker：复用 scripts/*]
                    ↓
         [Object store: work 快照] + [Postgres：账号/项目/账单/job 元数据]
```

- **短期**：FastAPI 包一层 + 原 `ui.html` 增强，加速 MVP  
- **中期**：Next.js 重做壳，worker 仍调 Python 开源管线  

### 8.2 数据模型（逻辑）

```text
Tenant(id, name, plan, trial_ends_at)
User(id, email, ...)
Membership(tenant_id, user_id, role)
Project(id, tenant_id, slug, url, market, brand_json, status)
EngineConfig(project_id, engine_id, enabled, model_pin)
Question(id, project_id, text, category, diagnosis_type)
SampleRun(id, project_id, started_at, status)
SampleAnswer(run_id, question_id, engine_id, raw_text, mentioned, cited, rank, ...)
Competitor(project_id, name, share, source=auto|manual)
PlaybookItem(id, project_id, type, title, impact, effort, status, payload_json)
Ticket(id, playbook_item_id?, acceptance, owner, state, metrics_json)
Fact(id, project_id, key, value, confirmed)
Asset(id, project_id, kind, path_or_blob)
Delivery(id, project_id, created_at, files[])
Job(id, type, payload, status, error)
Subscription / UsageCounter
```

Offsite payload 示例见 F-P0-06。

### 8.3 API 草图（MVP）

```text
POST   /auth/register|login
GET    /me
POST   /projects                 { url, market }
GET    /projects/:id
POST   /projects/:id/bootstrap
POST   /projects/:id/sample
GET    /projects/:id/report
GET    /projects/:id/playbook
POST   /projects/:id/playbook/:itemId/to-ticket
GET    /projects/:id/tickets
POST   /projects/:id/verify
POST   /projects/:id/deliver
POST   /projects/:id/schedule
GET    /projects/:id/samples/:answerId   # raw
```

---

## 9. UX 与文案要点（学 HiGEO）

- Hero 级产品句：See how AI talks about your brand. **Then ship the work and prove it.**  
- 定价页：One plan / 或清晰两档；写清 vs 代理 / vs 自建 / vs 纯监控  
- 空状态：引导「只输入域名」  
- 错误：引擎 Key 缺失时引导手动 sheet 或设置 Key，不装死  
- 数字旁：「单轮波动是观察值；连续两轮同向才标趋势」（开源 FAQ 精神）  

---

## 10. 定价与包装（配置，非写死代码）

| 方案 | 建议 | 包含 |
|------|------|------|
| Trial | 14 天全功能 | 同 Pro |
| Pro | $99 或 ¥99–299/月 | 3–10 projects、月采样额度、playbook+tickets+verify、基础 delivery |
| Agency | 更高 | 多客户、白标、更多 runs、优先队列 |
| Enterprise | 定制 | 私有化、SSO、合同 SLA |

**计量建议**：`questions × engines × runs / month`，超限排队或升级。

---

## 11. MVP 里程碑（30 天）

| 周 | 交付 |
|----|------|
| W1 | 引入开源仓库；租户/项目；domain onboarding 调通 bootstrap+crawl |
| W2 | sample 异步化；Report + raw answer + 基础 playbook 映射 |
| W3 | tickets + verify；offsite 字段；facts/assets |
| W4 | delivery 下载；试用/订阅骨架；打磨诚实文案与 demo 数据 |

**Demo 脚本**：输入一真实站点 → 出报告 → 转 1 个 technical + 1 个 offsite 工单 → verify → 下载 delivery zip。

---

## 12. 测试与验收

### 12.1 继承开源测试

运行并保持绿灯：`tests/test_*.py`（analytics/audit/bootstrap/crawl/deliver/geolib/jobs/sample/tasks/report…）。

### 12.2 新增 SaaS 测试

- 租户 A 不能读租户 B 的 project  
- onboarding 仅 URL 可创建 project  
- playbook 排序稳定  
- offsite ticket 含 url+ask_text  
- verify 失败 reopen  
- delivery 包文件清单非空  

### 12.3 产品验收清单（PO）

- [ ] 与 HiGEO 对比：上手同样「只填域名」  
- [ ] 比 HiGEO 多：工单验证、交付包、CN 市场  
- [ ] 引擎列表与真实采样一致  
- [ ] 无「保证上首页」类宣传  

---

## 13. 风险与缓解

| 风险 | 缓解 |
|------|------|
| 采样 API 成本高 | 用户自带 Key；额度；手动 sheet |
| 答案随机性 | 多问聚合、repeat、文案降级承诺 |
| 开源快速演进 | 跟踪 upstream；子模块或定期 merge |
| 与 GEOforge/HiGEO 品牌/功能撞车 | 产品名 DisvorAI；卖点钉死闭环+CN+交付 |
| 开源无 auth 误暴露 | 禁止裸绑 0.0.0.0；强制网关鉴权 |

---

## 14. 品牌与目录说明

- 工作区文件夹：**disvorai**（本 PRD 所在）  
- 开源项目名仍为 GeoLook；商业产品名以 **DisvorAI** 为准（可配置 white-label）  
- 避免使用已冲突品牌：GeoForge / GEOforge / getgeoforge 等  

---

## 15. 附录 A — HiGEO 合并项检查表

| # | 来源 | 状态 |
|---|------|------|
| 1 | Domain-only onboarding | P0 |
| 2 | Impact×Effort playbook 四类 | P0 |
| 3 | Off-site 到 URL+ask | P0 |
| 4 | Raw answer 可点 | P0 |
| 5 | 竞品自动发现 | P0 |
| 6 | Framing 词云 | P0 |
| 7 | 单档价+试用叙事 | P0 文案/计费 |
| 8 | 诚实 scope | P0 |
| 9 | 行业 Guides | P1 内容 |
| 10 | vs 代理/自建 价值叙事 | 营销页 P1 |

## 附录 B — 开源护城河检查表

| # | 能力 | 状态 |
|---|------|------|
| 1 | 端到端 tickets→verify→reopen | P0 |
| 2 | 客户 delivery 包 | P0 |
| 3 | CN 引擎与渠道 | P0 |
| 4 | Workbench + lint | P0 |
| 5 | 可复现指标 / unmeasured | P0 |
| 6 | 私有化路径 | P1/P2 |

## 附录 C — 参考链接

- 开源：https://github.com/aigclink/geolook  
- Demo：https://geolook.cc/  
- HiGEO：https://www.higeo.ai/  
- 对比：`/home/michael/project/geolook-saas/higeo-vs-geolook-comparison.md`  

---

**文档结束。** 实现时以本 PRD 为唯一产品真源；与开源 README 冲突时，**管线行为以开源+测试为准，产品壳与商业规则以本 PRD 为准**。
