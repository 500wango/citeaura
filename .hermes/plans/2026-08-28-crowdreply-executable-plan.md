# CiteAura CrowdReply 对标可执行优化计划

> 版本 2026-08-28 v3 · 定价已定 $79/$199/$499 · 通用行业 · 不做代发
> 适用：任何做营销需要 GEO 的行业（不限 SaaS）
> 硬约束：不做托管号代发/点赞/上票；不引入按条 credits；文件 SSOT 在 work/<tenant>/<slug>/；所有采样模式必须标注；不做自动发布；不承诺排名/提及

---

## 0. 执行总览

| 阶段 | 目标 | 工期 | 是否阻塞发布 | 回归要求 |
|---|---|---|---|---|
| P0 | 落地页+定价转化+控制台引用源情报卡 纯前端+轻后端 | 3-4 天 | 可独立上线 | engine 全绿 + api 全绿 + 浏览器 /app 验收 |
| P1 | 白帽 Citation Intelligence 独立视图 + 机会矩阵升级 + 通用站外清单 | 7-10 天 | 依赖 P0 | 同上 + 租户隔离 + 文件产物校验 |
| P2 | Authority Footprint / Listening Lite 评估项 | 按需 | 不承诺 | 有真实数据再开 |

**分支策略**：每个 Task 独立分支 `feat/<task-id>`，Commit 格式 `feat(module): 描述`，每完成一 Task 必须 `cd engine && python3 -m unittest discover -s tests` 全绿 + `make test` 全绿才能合。

**禁止事项**：任何 Task 不得修改 `engine/scripts/*.py` 公共接口；SaaS 逻辑只在 `api/adapters/`、`api/projects/`、`web/`；不得 hardcode 密钥；不得把管线产物写入 PG。

**术语解释**：
- **Citation 聚合**：把一次采样中所有 AI 回答底下带的引用链接（citations）捞出来，按域名分组计数，排 Top 5。用于回答“这个品类 AI 最爱引哪些域名，而我没被引”。数据源是 `work/<tenant>/<slug>/samples/*.jsonl` 每条的 `citations` 字段，不调外部 API。MVP 先实时计算，不落盘缓存。
- **站外 8 平台**：本计划 P1-3 的通用版为 6 固定 + 2 动态，任何行业通用（见 P1-3 定义）。

---

## 1. P0 详细任务（编码代理可直接执行）

### Task P0-1 落地页 Hero 重构

**背景**：CrowdReply 首屏一句话 `Track rankings, monitor cited conversations and place your brand where it matters.` + 三指标卡，对比 CiteAura 现有 Hero 偏技术长句，转化弱。

**输入**：`web/index.html` 现有 hero（含 scanner、证据链、radar/tickets/compare/assets 四 tab）
**输出**：新 Hero 双行价值主张 + 单一 Visibility Score 卡 + 信任状占位

**改动文件**：
- `web/index.html` — hero-copy-block 内：
  - 保持 `.hero-eyebrow` 不动
  - 替换 `#hero-title` 文案为：`Track your AI search visibility. Build the assets AI actually cites.`
  - 在 `h1` 下新增 `p.hero-value-prop` 文案：`Other tools tell you where you're missing. CiteAura builds what's missing — and proves it with traceable evidence.`
  - 保留现有 `p.hero-evidence-chain`，在其下方新增 `div.hero-score-preview` 卡（复用 console-frame 样式，展示 3 指标：Top citation sources / Competitor outrank / Citation gap count，静态示例数据，不调 API）
  - 在 `hero-trust-row` 下新增 `div.hero-trusted-by` 占位（灰色 logo 块，文案 `Trusted by teams building GEO workflows`，先占位不上真实 logo）
- `web/assets/styles/landing.css` — 新增 `.hero-value-prop`, `.hero-score-preview`, `.hero-trusted-by` 样式，复用 `tokens.css` 的 `--brand/--line/--muted`，保持 Space Grotesk + OKLCH Teal
- `api/i18n/messages/en.json` — 新增 `landing.hero_title_new`, `landing.hero_value_prop`, `landing.hero_score_sources`, `landing.hero_score_outrank`, `landing.hero_score_gaps`
- `api/i18n/messages/zh.json`（如存在）— 同步新增

**文案定稿**：
- 主标题：`Track your AI search visibility. Build the assets AI actually cites.`
- 副标题：`Other tools tell you where you're missing. CiteAura builds what's missing — and proves it.`
- 不承诺排名/提及，保留 FAQ 的诚实边界文案

**验收**：
- 浏览器打开 `/` 首屏 5 秒内能回答“这是干什么的、跟代发工具有什么不同、怎么证明有效”
- `web/index.html` 无布局错位，`curl /llms.txt` 仍可达
- `cd engine && python3 -m unittest discover -s tests` 全绿（此 Task 不动 engine）

---

### Task P0-2 定价页对比矩阵

**背景**：CrowdReply 定价页是横向对比矩阵（prompts/models/keywords/platforms/credits/团队人数），Most Popular 锚在 Growth；CiteAura 现有 `web/pricing.html` 只有 4 行文字描述，无对比、无锚点，转化吃亏。

**输入**：`web/pricing.html` 现有 seo-table（4 列 Plan/Monthly price/Best for/Included capacity）
**输出**：横向对比矩阵 + Most Popular 徽标 + FAQ 扩充，价格保持 $79/$199/$499

**改动文件**：
- `web/pricing.html` — 重构 `section#plans-title` 内表格：
  - 表头：`Feature | Starter $79 | Pro $199 · Most Popular | Agency $499 | Enterprise Custom`
  - 行分组（复用 `seo-table` 样式，加 `tbody` 分组标题行）：
    - Group: AI Search Visibility — `Active projects (3/10/30/Custom) | Prompts tracked (问卷数，显示 Unmeasured until sampled) | Models (Choose 2/4/All/Custom) | Sampling modes labeled`
    - Group: Citation Intelligence — `Citation source table (P0 仅占位 Ready in P1) | Competitor outrank view`
    - Group: Audit & Tickets — `6-dim audit | 13 tickets | Verify & timeline | Before/after progress`
    - Group: Assets & Delivery — `llms.txt/JSON-LD/snippets/drafts | Delivery pack zip | White-label header (Agency+)`
    - Group: Platform & Team — `Team members (2/Unlimited/Unlimited/Custom) | API/MCP access | SSO (Enterprise)`
  - 在 Pro 列头加 `<span class="pricing-badge-most">Most Popular</span>`
  - 保留价格 $79/$199/$499 不变，不引入 credits
  - 在 `Plans` 下新增 `p.seo-meta`：`All plans are BYOK-first. Model API costs are billed by your provider.`
  - FAQ 区新增 3 条（复用 `seo-faq details`）：
    - `What's included in the 7-day trial?` — `Full platform access except Engagement-style auto-posting which CiteAura never does.`
    - `Can I top up if I run out of projects?` — `Upgrade plan or archive a project to free a slot.`
    - `Do plans guarantee AI mentions?` — `No. Plans provide workflow and evidence.`
- `web/assets/styles/seo-pages.css` — 新增 `.pricing-badge-most`, `.seo-table-group-head` 样式，复用现有 `seo-table` 边框，不引入新颜色
- `api/i18n/messages/en.json` — 新增 pricing 矩阵相关 key

**验收**：
- 定价页信息密度与 CrowdReply 对齐，但价格保持 $79/$199/$499
- 表格在 1280/768/375 宽度下横向可滚动不破版
- Schema.org OfferCatalog 的 price 仍为 79/199/499
- `/pricing` 的 canonical / og 标签不变

---

### Task P0-3 控制台 Overview 引用源情报卡

**背景**：CrowdReply 的 Citation Source Intelligence 是核心卖点；CiteAura 的 Overview 只有 mention_rate/grade/tickets/engines 四 KPI，缺“AI 在哪里引别人而没引我”的情报。

**输入**：现有 `web/app/views/overview.js`（已加载 report/engines/tickets/visibilityPlan）+ `engine` samples 产物
**输出**：Overview 顶部新增 Citation Source Intelligence 卡（Top 5 被引域），数据源为 Citation 聚合（实时计算）

**改动文件**：

1. **后端聚合（不新增表，不落盘，实时计算）**
   - `api/adapters/citation_sources.py` 新建：
     ```python
     def aggregate(project_slug) -> dict:
         # 只读 work/<tenant>/<slug>/samples/*.jsonl 的 latest（按文件名排序取最后）
         # 对每条 row：取 row.citations (list[str|{url}])，提取域名（urlparse hostname，去 www. 前缀，小写）
         # 计数：domain -> {count, evidence_urls: [url, ...][:3]}
         # 计算 share = count / total_citations
         # type 启发式：reddit.com→community, wikipedia.org→knowledge, yelp/tripadvisor/g2/capterra/trustpilot→review, 其余→editorial
         # 返回 {status: "measured"|"unmeasured", total_citations: int, domains: [{domain, type, count, share, evidence_count}], unmeasured_reason?: str}
         # 无 sample 或 total=0 时 status=unmeasured, domains=[], unmeasured_reason="No citations collected yet. Run a sample."
         # 异常：目录不存在/JSON 解析失败 → unmeasured，不抛 500
     ```
   - `api/projects/citation_sources_routes.py` 新建：
     ```python
     router = APIRouter(tags=["citation-sources"])
     @router.get("/{project_id}/citation-sources")
     def get_citation_sources(project_id: int, current_user=Depends(get_current_user), db=Depends(get_db)):
         project = project_for_user(db, current_user, project_id)
         tenant = db.get(Tenant, project.tenant_id)
         with with_tenant_read_context(tenant, project.slug):
             return citation_sources.aggregate(project.slug)
     ```
   - `api/main.py` — 注册 `citation_sources_routes.router`，前缀 `/api/v1/projects`，放在 `citation_readiness` 路由附近
   - 不写 `citation_sources.json`，每次请求实时算；若后续性能需要再加缓存（不在本 Task）

2. **前端**
   - `web/app/views/overview.js` — 在 `renderKpis(kpiData)` 下、`visibility_plan` 卡上新增：
     ```js
     let citationSources = null;
     try { citationSources = await projects.getCitationSources(projectId).catch(()=>null); } catch {}
     // 卡片：标题 Citation Source Intelligence，副标题 Where AI pulls its answers for your category
     // 有数据：表格 Domain | Type pill | Share | Evidence 链接数，Top 5 + "View all in Engines →" 链接到 #/citations（P1-1 预留）或 #/engines
     // 无数据：显示 Unmeasured · Run sample to populate，不显示 0%
     // 每行 domain 旁显示 type pill（community/editorial/review/knowledge 四色，复用 tag 样式）
     ```
   - `web/app/api.js` — `projects` 命名空间新增：
     ```js
     getCitationSources: (id) => request(`/api/v1/projects/${encodeURIComponent(id)}/citation-sources`),
     ```

**API 契约**：
- `GET /api/v1/projects/{id}/citation-sources` → `{status: "measured"|"unmeasured", total_citations: int, domains: [{domain, type, count, share, evidence_count}], unmeasured_reason?: string}`
- 401 未登录，404 项目不存在/无权访问，200 即使无数据也返回 unmeasured（不抛 500）
- 租户隔离：通过 `project_for_user` 校验，跨租户 404

**验收**：
- 无 sample 的项目显示 Unmeasured，不显示 0%
- 有 sample 的项目 Top 5 域名可追溯到 `samples/*.jsonl` 的 citations 字段，share = count/total，证据数一致
- 同一 tenant 不可见另一 tenant 的 citation 数据（隔离测试）
- `api/tests/test_citation_sources.py` 新增 3 用例：unmeasured / measured / tenant_isolation
- `cd engine && python3 -m unittest discover -s tests` 全绿

---

## 2. P1 详细任务（白帽情报层，通用行业）

### Task P1-1 Citation Source Intelligence 独立视图

**目标**：把 P0-3 的卡升级为独立视图，对标 CrowdReply 的 `See which domains AI models cite for your category. Find gaps where competitors appear and you don't.`，但动作为建站内资产而非买外链。

**改动文件**：
- `web/app/views/citations.js` 新建（独立视图，路由 `#/citations`）：
  - 布局：顶部 `status bar`（total_citations / measured domains / unmeasured_reason）+ 主表格
  - 表格列：Domain | Type | Citation share | Evidence samples | Suggested asset | Action
  - Suggested asset 映射（白帽，不含代发，通用行业）：
    - community (reddit/quora) → `FAQ answer page + community-facing fact block`（跳 workbench）
    - editorial (blog/media) → `Comparison matrix + llms.txt`（跳 assets）
    - knowledge (wikipedia/wikidata) → `Schema.org + entity definition`（跳 facts）
    - review (g2/capterra/yelp/点评类) → `Review schema + testimonial block`
  - Action 列仅为 `View evidence`（打开 engines 样回答回放锚点）+ `Create ticket`（跳 plan 带 domain 参数），无代发按钮
  - 空状态：`No citations collected yet. Run a sample to see where AI pulls its answers.`
  - 排序：按 share 降序，Top 20，分页或滚动
- `web/app/app.js` — 注册路由 `citations: () => import('./views/citations.js')`，在 6 轨道导航的 `诊断` 轨道下加 `Citations` 入口（与 siteaudit 平级，不新增轨道，icon 用 link）
- `web/app/i18n.js` + `api/i18n/messages/en.json` — 新增 `citations.*` key
- 后端复用 `api/adapters/citation_sources.py` 的聚合逻辑，增加 `suggested_asset` 字段的映射函数 `suggested_asset_for_type(type) -> {label, route}`

**验收**：
- 任意项目跑一轮 sample 后，citations 视图列出 Top 引用域且每行可追溯到原始回答证据（点击 View evidence 跳 engines 回放）
- 无自动发帖/上票入口，全部为资产建议
- 文件产物校验：聚合结果与 `samples/*.jsonl` 一致，不写入 PG
- 浏览器：`#/citations` 在有/无数据时均不白屏

---

### Task P1-2 Content Opportunity 矩阵升级

**目标**：把现有 brand_opportunities 的散列表升级为四列可交付矩阵，对标 CrowdReply 的列表形态，但 visitors 换成 `AI 提及缺口 + 证据数`。

**改动文件**：
- `api/adapters/brand_opportunities.py` — 扩展 `assess()` 返回：
  ```python
  {
    "status": "measured"|"unmeasured",
    "opportunities": [
      {
        "id": "opp_001",
        "question": str,
        "question_id": str,
        "evidence_count": int,        # 来自 answers 的对比
        "gap_type": "not_covered"|"low_mention"|"conflict",
        "suggested_page_type": "FAQ or answer page" | "Comparison matrix" | "Entity definition",
        "acceptance_criteria": "After publishing, re-sample this question via API·Model knowledge and expect mention_rate uplift; verify via verify job.",
        "evidence": [{"source": "question_bank"|"sample", "excerpt": str}]
      }
    ],
    "conflicts": [...]  # 保留现有
  }
  ```
  - 每个 opportunity 必须至少关联一个真实 question 或 sample 证据，无证据时 `gap_type=not_covered` 且 evidence 为空时前端显示“待验证”
  - 不自动写内容，不调 LLM

- `web/app/views/plan.js` — 复用现有 plan 视图增加 `Opportunities` tab（与 Matrix/Table 并列，不新增视图以避免第二套工单系统）：
  - Tab 切换：Matrix | Table | Opportunities
  - Opportunities 表格列：Question | Gap type pill | Evidence count | Suggested page type | Acceptance | Action
  - Action：`Create ticket`（复用 `projects.createTicket`，带 question_id 到 influenced_questions）+ `View evidence`
  - 空状态：`No opportunities yet. Add questions or run a sample.`
  - 数据源：`projects.getBrandOpportunities(projectId)` 已有，无需新增 API

- `web/app/api.js` — 已有 `getBrandOpportunities`，无需新增

**验收**：
- 每条 opportunity 至少关联一个真实问题或采样证据，缺少证据显示“待验证”不伪造
- 从 opportunity 创建的 ticket 自动带 `influenced_questions` 和 `acceptance_criteria` 到备注
- 不生成重复 opportunity（幂等：重复 assess 返回相同列表，不新增文件）
- `api/tests/test_brand_opportunities.py` 补充 gap_type / acceptance 断言

---

### Task P1-3 站外实体清单（人工复核队列，通用行业）

**目标**：白帽版 Listening — 不做实时爬 Reddit，仅做第三方品牌信息一致性清单，任何行业通用，全部人工复核。

**平台定义（6 固定 + 2 动态，任何行业适用）**：
- 固定 6：Official Site（官网）| Wikipedia/Wikidata | LinkedIn Company Page | X (Twitter) | Facebook/Instagram | Google Business Profile
- 动态 2：
  - 行业目录/点评站（可自选输入，placeholder 提示：SaaS 填 G2/Capterra，电商填 Shopify/Amazon，本地服务填 Yelp/大众点评）
  - 媒体/百科提及（从 P0-3 的 Citation 聚合 Top 域自动带入前 3 个 editorial 域作为待核实项，状态 pending）

**改动文件**：
- `api/adapters/offsite_entities.py` 新建：
  ```python
  FIXED_PLATFORMS = ["official_site", "wikipedia", "linkedin", "x", "facebook_instagram", "google_business"]
  DYNAMIC_PLATFORMS = ["industry_directory", "media_mention"]  # 允许 custom 域名

  def list_entities(project_slug) -> list:
      # 读 work/<tenant>/<slug>/offsite_entities.json (若不存在返回 [])
      # 每项 {id, platform, domain_or_url, url, status: "pending"|"consistent"|"needs_fix", evidence_url, reviewer_note, updated_at}
      # 若文件为空且存在 citation_sources 聚合结果，自动预填 2 个动态项（pending，需人工确认）

  def save_entities(project_slug, entities: list):
      # 写 work/<tenant>/<slug>/offsite_entities.json，需 geolib.project_lock
      # 校验：每项 platform 非空，url 为 http(s) 或域名，status 枚举，非空
  ```
- `api/projects/offsite_entities_routes.py` 新建：
  ```python
  @router.get("/{project_id}/offsite-entities")
  def list_offsite_entities(project_id: int, current_user=Depends(...), db=Depends(...)):
      project = project_for_user(db, current_user, project_id)
      tenant = db.get(Tenant, project.tenant_id)
      with with_tenant_read_context(tenant, project.slug):
          return {"entities": offsite_entities.list_entities(project.slug)}

  @router.put("/{project_id}/offsite-entities")
  def put_offsite_entities(project_id: int, body: {entities: list}, ...):
      # 校验每项 platform/url/status，status 枚举
      # 租户隔离 via project_for_user
      # 写文件后返回 {"entities": saved}
  ```
- `api/main.py` — 注册路由，前缀 `/api/v1/projects`
- `web/app/views/entities.js` 新建：
  - 顶部提示条：`All off-site suggestions require human review. No auto-posting.`（黄色 warning 样式）
  - 表格：Platform | URL/Domain | Status pill | Evidence | Reviewer note | Action (Edit)
  - 固定 6 行预填（即使空也显示 pending），动态 2 行可 Add custom
  - 空状态：`No off-site entities tracked yet. Add your official profiles to start the checklist.`
  - 编辑用 modal，字段：platform select（含 custom 选项触发文本输入）、url input、status select、evidence_url、note
  - 预填的 media_mention 行标注 `Suggested from citation sources · needs review`
- `web/app/api.js` — 新增：
  ```js
  getOffsiteEntities: (id) => request(`/api/v1/projects/${encodeURIComponent(id)}/offsite-entities`).then(d=>d.entities||[]),
  saveOffsiteEntities: (id, entities) => request(`/api/v1/projects/${encodeURIComponent(id)}/offsite-entities`, {method:'PUT', body:{entities}}),
  ```
- `web/app/app.js` — 注册路由 `#/entities`，入口放在 `执行` 轨道（与 plan 同组），icon 用 globe

**验收**：
- 所有站外建议均有来源、平台、审核状态，无自动发帖入口
- 文件在 `work/<tenant>/<slug>/offsite_entities.json`，DB 不新增表
- 固定 6 + 动态 2 在新项目上可见，动态项可增删
- 租户隔离：A tenant 不可见 B tenant 的清单（`api/tests/test_offsite_entities.py` 3 用例：empty / put_and_list / isolation）
- 浏览器：`#/entities` 在有/无数据时均不白屏

---

## 3. P2 评估项（不承诺，占位）

- **P2-1 Authority Footprint 说明页**：在 `assets` 增加只读说明，不做外链商城。需真实客户数据后再决定是否做白帽外链清单工单。
- **P2-2 Listening Lite**：仅 Single Search 触发的检索，不做常驻监控。需评估检索来源稳定性与成本后再开。

---

## 4. 编码代理执行指令

1. 按 P0-1 → P0-2 → P0-3 → P1-1 → P1-2 → P1-3 顺序执行，每完成一 Task 独立分支 `feat/p0-1-hero` 等并提交 `feat(module): 描述`。
2. 每个 Task 开始前先 `git status` 确认分支干净、`read_file` 确认目标文件当前内容再 patch，禁止用 stale 内容 patch。
3. 每个 Task 完成后必须：
   - `cd engine && python3 -m unittest discover -s tests` 全绿
   - `make test` 或 `cd api && pytest tests/ -q` 全绿
   - 浏览器验收：`/`, `/pricing`, `/app#/overview`, `/app#/citations`, `/app#/entities` 对应页面不白屏、关键文案可见
   - 文件产物校验：`work/<tenant>/<slug>/offsite_entities.json` 租户隔离（自动化测试覆盖）
4. 任何失败不得用 mock 数据伪造通过，直接报告阻塞原因。
5. 每完成一 Task 在 PR 描述中贴：改动文件清单 + API 契约 + 浏览器截图/DOM 断言 + 测试结果。

---

## 5. 交付物

- 6 个 PR：P0×3 + P1×3，每 PR 含代码 + 测试 + 浏览器验收
- 本计划 v3 为执行合同，后续变更需追加 `## 变更记录` 并重新审核

> 审核通过后编码代理从 P0-1 开工，每完成一 Task 提审一次。
