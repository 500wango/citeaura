# CiteAura UI 实施审计

日期：2026-10-24
依据：`docs/CITEAURA_UI_SPEC.md`、仓库运行时代码

## 1. 实际技术栈

| 层 | 实际实现 | 证据 |
|---|---|---|
| 营销站 | 静态 HTML + 原生 CSS/JS，无构建步骤 | `web/index.html`、`web/pricing.html`、`web/docs.html`、`web/sample-report.html` |
| 应用 | Vanilla JS ES Modules SPA，hash 路由 | `web/app/index.html`、`web/app/app.js` |
| 样式 | 原生 CSS + 语义变量 | `web/assets/styles/{tokens,base,components,app,home,landing,seo-pages}.css` |
| 字体 | 自托管 Geist / Space Grotesk / JetBrains Mono | `web/assets/fonts/` |
| i18n | 客户端按 key 加载 7 种语言 | `web/app/i18n.js`、`api/i18n/messages/*.json` |
| 主题 | `data-theme` + `localStorage.utheme` + 系统偏好 | `web/assets/theme-init.js` |
| 后端 | FastAPI，静态挂载 `/site-assets`、`/app-assets` | `api/main.py` |
| 测试 | Python unittest/pytest + 静态前端契约测试；无 JS test runner、无 lint/typecheck/build 脚本 | `api/tests/test_ui.py`、`api/tests/test_landing.py`、`Makefile` |
| CI | `make test` 后才部署 | `.github/workflows/deploy-production.yml` |

结论：不得引入 React/Tailwind/组件框架或新的 JS 测试基础设施。UI 变更必须以现有 CSS 变量、ES Modules 和 Python 契约测试完成。

## 2. 路由与页面映射

### 2.1 应用内路由（`web/app/app.js` 的 `TRACKS` / `VIEW_LOADERS`）

| 目标分组 | 现有路由 | 视图文件 | 备注 |
|---|---|---|---|
| Overview | `#/overview` | `views/overview.js` | 真实 project/report/tickets/jobs |
| Measure | `#/engines` | `views/engines.js` | Visibility Matrix、raw answer replay |
| Measure | `#/channels` | `views/channels.js` | Citation Sources，仅 web-grounded URL |
| Measure | `#/competitors` | `views/competitors.js` | Competitor benchmark |
| Diagnose | `#/siteaudit` | `views/siteaudit.js` | Site-wide audit |
| Diagnose | `#/gaps` | `views/gaps.js` | Model perception |
| Diagnose | `#/questions` | `views/questions.js` | Target questions / cohort 输入 |
| Diagnose | `#/facts` | `views/facts.js` | Brand facts |
| Diagnose | `#/blueprint` | `views/blueprint.js` | Channel blueprint |
| Execute | `#/plan` | `views/plan.js` | Action tickets、2×2、plan controls |
| Execute | `#/workbench` | `views/workbench.js` | Interactive workbench |
| Execute | `#/assets` | `views/assets.js` | Assets & templates |
| Verify & Deliver | `#/verify` | `views/verify.js` | Closed-loop technical verification |
| Verify & Deliver | `#/report` | `views/report.js` | Delivery packs |
| Settings | `#/project-settings`、`#/engine-settings`、`#/automation`、`#/team`、`#/billing`、`#/branding`、`#/outreach`、`#/entities`、`#/publishing`、`#/archive` | `views/*.js` | 保持 RBAC 与现有写操作 |
| Auth | `#/login`、`#/register`、`#/forgot-password`、`#/reset-password`、`#/invite` | `views/auth-*.js` | 保留真实注册/邀请流程 |
| Unknown | 任意未知 hash | `app.js#renderNotFoundView` | 显式 404，不静默回退 |

### 2.2 营销与报告路由

| URL | 文件 | 目标 |
|---|---|---|
| `/` | `web/index.html` + `home.css` | Editorial SaaS 首页，真实产品截图 |
| `/pricing` | `web/pricing.html` + `seo-pages.css` | 套餐、trial、BYOK 边界 |
| `/docs` | `web/docs.html`（inline CSS） | 方法论文档、锚点、搜索 |
| `/for-brands`、`/for-agencies` | 同名 HTML | 受众页 |
| `/sample-report` | `web/sample-report.html` | Demo 报告与浏览器打印 |
| `/methodology` | `web/methodology.html` | 证据方法 |

## 3. 可复用组件与落点

| 现有组件 | 路径 | 本次处理 |
|---|---|---|
| `renderKpis` | `web/app/components/kpi.js` | 扩展 `state`、`meta`、`title`，支持 Unmeasured 与分母 |
| `samplingModeBadge` / `statusPill` / `gradeBadge` | `web/app/components/badge.js` | 保留文本语义，统一视觉 |
| `renderEmpty` | `web/app/components/empty.js` | 统一空状态样式 |
| `openModal` / `confirmModal` | `web/app/components/modal.js` | 保留焦点管理与 pending 行为 |
| `openModal({ drawer: true })` | `web/app/components/modal.js` | 新增右侧 drawer 形态；沿用原焦点陷阱、Esc、背景关闭与焦点恢复，不引入第二套 modal |
| `openEvidenceDrawer` | `web/app/components/evidence-drawer.js` | 从真实 sample replay 渲染 Prompt、原始回答、citations、模型/版本、采样模式、请求 ID、延迟、重试、检索证据与用量 |
| `renderTabs` / `renderTable` / `renderSkeleton` | `web/app/components/*` | 使用统一 primitive token |
| App shell | `web/app/app.js#renderAppShell` | 重设导航尺寸、焦点、移动端抽屉、角色展示 |
| i18n strings | `api/i18n/messages/*.json` | 只补新增界面 key |

## 4. 真实数据与不可改动的接口

- 不修改任何 `/api/v1/` 契约、支付、trial 计算、租户隔离、BYOK 注入、任务白名单。
- trial 唯一真实源：`api/billing/plans.py` 的 `TRIAL_DAYS = 14` 与 `PLANS["trial"]`（3 projects / 3 sample runs）。公开页必须同步为 14 天。
- 套餐能力真实源：`PLANS` 与 `PLAN_FEATURES`（scheduled monitoring 包含 starter/pro/agency；white-label 仅 agency）。
- `Unmeasured` 语义：`report.mention_rate === null` 或 `engine.sample_count === 0` 时必须是 `Unmeasured`，不能显示 0%。
- `mention_rate` 分母：`report.sample_count` / `quality.measurement_quality.current`，品牌名出现在问题中的样本由后端排除。
- `engines.median_rank` 实为中位数，现有表头 `Avg Rank` 需改为 Median position，不改变计算。
- `citation_share` 只来自 web-grounded 返回的 URL；knowledge / manual 不生成 source URL。
- `verify` 只表示技术检查；AI 可见性变化必须另采样。
- 同一项目只允许一个活动 job；前端禁用需以服务端 409 为准。
- 报告 PDF 为新增只读端点 `GET /api/v1/projects/{project_id}/deliveries/{delivery_date}/pdf?document=01-Audit-Report`，复用 `validate_existing_delivery_contract` 与既有租户/登录校验；不修改原有 delivery、ZIP、分享与 Markdown 读取契约。渲染实现为 `api/adapters/pdf.py`（ReportLab + Pillow），不引入 Chromium/wkhtmltopdf。
- PDF 页眉/页脚读取 `api/adapters/branding.py` 的既有白标配置；无可用 logo 时降级为文字品牌，不伪造客户品牌。

## 5. 审计发现与差异

1. `tokens.css` 注释为 Signal Green，实际主色为橘红 `#fe551b`；`app.css` 末尾另有硬编码深色霓虹绿主题，覆盖 `data-theme`，导致工作台与营销站割裂。这是本次 P0 首要修复点。
2. `web/index.html` 虽声明 `data-theme="dark"`，但 `theme-init.js` 会按系统/存储主题覆盖；首页 `home.css` 又自行定义一套 `:root`。需要统一到 Precision token。
3. trial 文案冲突：首页/Pricing 为 14 天，`docs.html`、`terms.html`、`llms.txt` 仍为 7 天。以 `TRIAL_DAYS = 14` 为准。
4. Pricing 表把 Starter 的 scheduled monitoring 写为 `—`，后端 `PLAN_FEATURES` 包含 Starter。按后端同步展示。
5. Overview 在未测量时显示 `[DEMO · SYNTHETIC BASELINE]`，容易被理解为演示数据；应改为明确的 `Unmeasured` / 配置原因。
6. Overview 的运行按钮只禁用了 Autopilot；Fill Sample Gaps、Verify 在活动 job 时仍可点击。
7. `/app` 报告页没有打印样式；`/sample-report` 已有打印样式但缺少 A4 page、表头重复与长 URL 换行。
8. `engines.js` 表头写 `Avg Rank`，实际为 `median_rank`；Docs 已解释该差异。
9. `/me` 返回 `role`，但 SPA 的 `AppState.initSession` 丢弃了它；Viewer 无法在 UI 上看到只读状态（后端仍鉴权）。
10. 无前端 lint/typecheck/build；验收依赖 Python 契约测试、ES Module 解析测试和手动浏览器检查。

## 6. 实施批次

| 批次 | 范围 | 文件 |
|---|---|---|
| B0 审计 | 本文件 | `docs/design/UI_IMPLEMENTATION_AUDIT.md` |
| B1 Foundations | 语义 token、字体、按钮/卡片/输入/表格/tag、移除硬编码主题 | `tokens.css`、`base.css`、`components.css`、`app.css` |
| B2 Shell | 248px 导航、移动端抽屉、项目切换、角色、job 状态 | `app.js`、`app.css` |
| B3 Overview | cohort bar、KPI 分母、Unmeasured 状态、任务互斥 | `overview.js`、`kpi.js` |
| B4 Evidence/Execution | Median 表头、Viewer 只读、验证语义保持 | `engines.js`、`plan.js`、`verify.js`、i18n |
| B5 Report | 应用报告打印、sample report A4、长 URL、表头重复 | `report.js`、`app-print.css`、`sample-report.html` |
| B6 Marketing | 首页/定价/Docs 视觉统一、trial 与套餐能力同步 | `index.html`、`home.css`、`pricing.html`、`docs.html`、`terms.html`、`llms.txt` |
| B7 Verification | 合同测试、响应式/打印手动核对、实施报告 | `api/tests/test_ui.py`、报告 |
| B8 Completion | 认证三页、onboarding、gaps、branding、表单选中语义、7 locale 文案与截图 | `auth-*.js`、`onboarding.js`、`gaps.js`、`branding.js`、`plan.js`、`app.css`、i18n |

## 7. 明确非目标

- 不重写 engine 采样、诊断、ticket 生成、报告 ZIP 合约。
- 不新增后端字段或虚构报告章节。
- 不引入前端框架、图表库或构建链。
- 不改支付金额、trial 天数、套餐 entitlement。
- 不为所有历史页面补测试；只锁本次高风险语义。

## 8. 实施后更新（2026-10-24）

- 上述第 3、8、9 项已修复：公开 trial 全部同步 `TRIAL_DAYS = 14`；`Median position` 取代 `Avg Rank`；`/me` 的 role 已进入 `AppState.role` / `ctx.role`，业务视图与 Owner-only 设置均按角色禁用。
- 新增 `app-print.css`，营销页不再定义平行 `:root`，`landing.css` 的旧霓虹深色覆盖块已删除。
- 实际覆盖 30/30 个工作台视图；本轮补齐 `auth-forgot`、`auth-invite`、`auth-reset`、`onboarding`、`gaps`、`branding`，无未改造路由。
- 初始化 onboarding 与 plan 复选框改用 data 属性选择，避免 `safe-html.js` 移除 `name` 后表单选择失效；未放宽 sanitizer。
- 详细完成度、测试和截图见 `UI_IMPLEMENTATION_REPORT.md`。

### 8.1 第二批增量（2026-10-24）

- Engines 的 raw answer 从整段直出改为可复核摘要，并新增 `Inspect evidence` 右侧 drawer；所有字段来自 `project_samples` 的真实回放数据。knowledge/manual 模式没有 URL 时显示 `No source URLs for this mode`。
- 新增服务端 PDF：`GET /api/v1/projects/{project_id}/deliveries/{delivery_date}/pdf?document=01-Audit-Report`，支持 `01`–`06` 与 `index`；Report 页同时保留 `View HTML` 与 `PDF` 两个真实链接。
- 补齐 198 个原先只存在于前端 fallback 或直接硬编码的界面 key（174 个 `t()` key + 24 个可见状态/默认值），7 个 locale 的 key 与 `{placeholder}` 完全一致；未翻译的 `literal.*` 仅保留合法业务值（如 `7-day` 分享链接和 `Weekly (7 Days)`）。
- 营销页产品图改为当前工作台真实截图：Overview、Action Tickets、Delivery/Pack；删除了旧版宽幅界面图造成的尺寸声明漂移，alt/caption 与实际页面一致。
- 服务端 PDF 已按文档主语言选择 Unicode CID 字体：中文 `STSong-Light`、日文 `HeiseiMin-W3`、韩文 `HYSMyeongJo-Medium`，英文保持 Helvetica；用真实中文 delivery 渲染检查，`·` 等 CID 缺字符号在渲染前替换。
- Evidence Drawer 已用临时 fixture 的真实 sample replay 截图（1440 drawer、375 sheet）；fixture 只存在于 `/tmp/ca-ui-Ye5KWO`，未写入生产页面或仓库样例数据。
- 本轮不改 `/api/v1/` 既有契约、计费、trial、引擎计算或权限判定；PDF 是新增只读能力，旧客户端可继续使用原 Download/ZIP 端点。
