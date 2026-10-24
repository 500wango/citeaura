# CiteAura UI 实施报告

日期：2026-10-24
依据：`docs/CITEAURA_UI_SPEC.md`
审计：`docs/design/UI_IMPLEMENTATION_AUDIT.md`

## 1. 实施结论

本轮按现有 Vanilla ES Modules SPA 与静态 CSS 完成 Precision SaaS 基础层、应用壳、30/30 个工作台视图、九处权限门禁与报告打印改造。剩余 6 个视图（认证三页、onboarding、gaps、branding）已补完，不再存在“未改造路由”。未引入 React、Tailwind、组件框架、图表库、构建步骤或前端测试框架；未修改 `/api/v1/` 契约、trial 天数、套餐 entitlement、引擎计算、租户隔离与 RBAC 后端校验。

统一后的视觉基线：

- 品牌蓝 `#2563eb`，浅色 canvas/surface/border 与深色语义映射均来自 `tokens.css`。
- Geist 为正文/展示字体，JetBrains Mono 用于 ID、URL、时间与代码。
- 工作台为 64px rail + 184px subnav（合计 248px），64px header；移动端为可聚焦抽屉。
- 细边框、低阴影、40px 标准按钮、36px 小按钮、tabular numerals。
- 营销页不再覆盖全局 token，也不再强制深色。

## 2. 业务语义保留

| 语义 | 实现 |
|---|---|
| `Unmeasured` | `mention_rate === null`、无合格样本、无观测的 engine/citation 均显示 `Unmeasured`；不渲染假 0% |
| Cohort | Overview 显示 question set、providers、sampling mode、window、eligible samples；不可比时显示原因 |
| Sampling modes | 继续使用 `API · Model knowledge`、`API · Web-grounded retrieval`、`Manual · Product surface`，不合并趋势 |
| Technical verify | Verify 页明确标注 `Technical check only`，不把 pass 映射为 AI impact |
| Job 互斥 | Overview、Engines、Verify、Report 的 queued/running 任务按钮禁用并显示原因；服务端冲突仍是最终判断 |
| RBAC | `/me` 的 `role` 进入 `AppState`/`ctx.role`；Viewer 在业务视图只读，Owner-only 设置（团队、计费、BYOK、归档、SMTP、发布凭据）禁用并解释原因；后端仍是最终鉴权 |
| Delivery readiness | 无 report_quality 时显示 `Readiness not evaluated`，不再声称所有检查通过 |
| Median rank | 表头改为 `Median position`，计算仍使用后端 `median_rank` |
| Citation sources | knowledge/manual 无 URL 时显示 `No source URLs for this mode`，不补造来源 |
| Trial | 统一按 `api/billing/plans.py` 的 `TRIAL_DAYS = 14` 展示，未改计费逻辑 |
| Scheduled monitoring | Pricing 按 `PLAN_FEATURES` 同步为 Starter/Pro/Agency 均支持 |

## 3. 修改文件

### 3.1 Foundations / Shell

| 文件 | 变更 |
|---|---|
| `web/assets/styles/tokens.css` | 替换为 Precision 语义 token、深色主题、字体/间距/圆角/布局常量；保留旧变量别名，并补齐 `--brand`、`--danger`、`--text-muted`、`--accent-contrast`、`--r-2xl`、`--r-full`、`--sh-xs`、`--sh-xl` |
| `web/assets/styles/base.css` | 自托管 Geist、统一标题/正文/数字排版 |
| `web/assets/styles/components.css` | 按钮、输入、卡片、tag、表格、KPI、Unmeasured/segmented 状态 |
| `web/assets/styles/app.css` | 移除玻璃拟态/霓虹主题覆盖；统一 rail/subnav/header；新增 rail hover/focus tooltip、移动抽屉、cohort bar、job note、read-only note、移动端 header 收缩 |
| `web/app/app.js` | 保存 `/me` role；展示当前 track/view 与角色；rail 链接补充 `data-rail-label`、`aria-label`、`aria-current`；移动端导航抽屉、焦点陷阱、Esc/背景关闭、滚动锁定 |
| `web/app/components/kpi.js` | 支持 `state`、`meta`、`title` 与 unmeasured 样式 |
| `web/assets/theme-init.js` | `theme-color` 跟随 light/dark token（`#f8fafc` / `#0b1220`） |
| `web/assets/styles/landing.css` | 删除遗留的霓虹/深色硬编码覆盖块（含 `#9df22f`），避免压过 Precision token |

### 3.2 Workspace 重点视图

| 文件 | 变更 |
|---|---|
| `web/app/views/overview.js` | 新增 Measurement cohort bar、eligible denominator、KPI 证据说明、活动 job notice；移除 `[DEMO · SYNTHETIC BASELINE]` 与未测量的 WAF/Schema 伪健康项；任务按钮互斥 |
| `web/app/views/engines.js` | `Median position`；真实呈现代理/模式/未测量；knowledge/manual 无来源提示；活动 job 与 Viewer 写操作禁用；修正 question readiness 胶囊与 `[object Object]` question set |
| `web/app/views/plan.js` | Viewer 只读提示；创建 ticket、保存 plan、opportunity ticket、ticket 编辑与 modal 保存按角色收起/禁用 |
| `web/app/views/verify.js` | `Technical check only` 标识；活动 job/Viewer 禁止重复验证；pending/disabled 状态 |
| `web/app/views/report.js` | 真实 Readiness checklist；无评估数据时诚实降级；活动 job/Viewer 禁止构建包；保留原 ZIP/download/send 合约 |
| `web/app/views/auth-login.js` | CTA fallback 文案同步 14 天 |
| `web/app/views/auth-register.js` | 注册页 CTA 文案同步 14 天 |
| `web/app/views/channels.js` | 活动 job/Viewer 阻止引用采样、引用 ticket 与外部证据创建；无总量时显示 `Unmeasured`，不渲染假 `0.0%` |
| `web/app/views/siteaudit.js` | 活动 job/Viewer 禁用重跑；`null` 分数不再附 `/ 100`；补充只读/运行中提示 |
| `web/app/views/assets.js` | 活动 job/Viewer 禁用生成、保存与 fill-question-gap 提案；编辑器只读；生成中 pending |
| `web/app/views/competitors.js` | Viewer 不可增删竞品；空状态 CTA 对 Viewer 隐藏 |
| `web/app/views/questions.js` | Viewer 不可新增、研究、编辑、删除；只读提示；`Unmeasured` 本地化 |
| `web/app/views/facts.js` | Viewer 不可保存/批准；textarea 只读 |
| `web/app/views/blueprint.js` | 活动 job/Viewer 禁用重建 |
| `web/app/views/plan.js` | Viewer 同时禁用 phase/review 字段，而不只是 ticket 操作 |
| `web/app/views/team.js` | 仅 Owner 可邀请、撤销邀请、移除成员；非 Owner 显示原因并禁用操作 |
| `web/app/views/billing.js` | 仅 Owner 可结账、取消订阅；非 Owner 保留只读套餐与用量展示 |
| `web/app/views/engine-settings.js` | 仅 Owner 可配置/测试/删除 BYOK Key、自定义 provider 与 API token；Viewer 只读 |
| `web/app/views/archive.js` | 仅 Owner 可创建/恢复快照；空状态 CTA 对非 Owner 隐藏 |
| `web/app/views/outreach.js` | SMTP 配置仅 Owner；Viewer 不可创建/发送 pitch；草稿操作保持 Editor 语义 |
| `web/app/views/publishing.js` | 发布目标凭据仅 Owner；Viewer 不可创建 GitHub PR；刷新只读状态仍可用 |
| `web/app/views/project-settings.js` | Viewer 只读 URL/市场/语言；归档仅 Owner；后端 `require_editor`/`require_owner` 不变 |
| `web/app/views/automation.js` | Viewer 不可保存 schedule；输入禁用并显示只读原因 |
| `web/app/views/entities.js` | Viewer 不可保存、删除或恢复实体；字段只读 |
| `web/app/views/workbench.js` | 无成功样本时提及计数显示 `Unmeasured`，不再渲染 `0/0` |
| `web/app/views/auth-forgot.js` | 统一 auth shell、标题层级、表单间距与内联错误状态；保留 forgot-password API 与成功跳转 |
| `web/app/views/auth-reset.js` | 统一 auth shell；缺 token/密码不一致显示 `role="alert"` 内联错误；保留 token 校验与 reset API |
| `web/app/views/auth-invite.js` | 统一 auth shell；修复非法邀请 `detail` 对象渲染成 `[object Object]`；保留 preview、邮箱锁定与 register/login/accept 顺序 |
| `web/app/views/auth-register.js` | 14 天 fallback 与英文目录同步；客户类型字段 i18n 化；保留注册、归因与 invite token 流程 |
| `web/app/views/onboarding.js` | 定义 `.wizard-card`；响应式两列/375 单列；模式卡使用真实选中态；预检结果与 sampling-not-configured 提示本地化 |
| `web/app/views/gaps.js` | 按 `status` 区分 no samples / 未提及 / 无描述词 / 加载失败；缺失 share 显示 `Unmeasured`；证据显示采样模式、时间与 sample denominator |
| `web/app/views/branding.js` | 区分套餐不可用与 Owner-only；真实 logo 预览、保存 pending 与重置（`branding.delete()`）；保留 Agency entitlement 与 512 KB 校验 |
| `web/app/views/plan.js` | 受影响问题复选框改用 `data-influenced-question`，避免 sanitizer 移除 `name` 后丢失选择 |

### 3.3 报告打印

| 文件 | 变更 |
|---|---|
| `web/assets/styles/app-print.css` | 新增：A4、白底、隐藏导航/工具栏、表格重复表头、长 URL 换行、卡片避免分页截断 |
| `web/app/index.html` | 以 `media="print"` 加载 `app-print.css` |
| `web/sample-report.html` | 增加 `@page`、表头重复、URL 换行、打印白底与分页保护；保留 Demo 标识 |

### 3.4 营销页与公开文案

| 文件 | 变更 |
|---|---|
| `web/assets/styles/home.css` | 去掉自建 `:root` 橙/黑主题，改为 `.home-page` 派生 `--signal`；标题 56px / 移动 36px；移除漂移光晕、grain、按钮位移；减少 hover 抬升 |
| `web/assets/landing.js` | 修复总是强制深色主题的 bug（无本地偏好时回退 light）；主题色同步 token |
| `web/index.html` | theme-color 同步；保留真实 CTA 与产品截图 |
| `web/pricing.html` | Starter scheduled monitoring 由 `—` 改为 `Yes` |
| `web/docs.html` | trial 7 → 14 days；median 说明同步 |
| `web/terms.html` | 7-day → 14-day trial |
| `web/llms.txt` | Starter trial 7 → 14 days |
| `web/for-brands.html` / `web/for-agencies.html` / `web/methodology.html` / `web/sample-report.html` | theme-color、打印与公开文案同步 |

### 3.5 i18n

`api/i18n/messages/{en,zh,ja,ko,es,fr,de}.json` 均补充同一组新增 key：

- nav：`nav.menu`、`nav.current_view`、`nav.primary`
- cohort/KPI：`overview.cohort_*`、`overview.kpi_denominator`、`overview.kpi_mention_detail`、`overview.evidence_checks`
- engines：`engines.no_source_urls`；`engines.col_avg_rank` 值改为中位数语义
- tickets/verify/report：`plan.viewer_read_only`、`verify.technical_only`、`report.readiness_*`
- auth/onboarding/gaps/branding：`auth.segment_*`、`onboard.preflight_title`、`onboard.sampling_not_configured`、`gaps.status_*`、`gaps.sampled_at`、`branding.plan_required`、`branding.owner_required`、`branding.reset_*`
- trial：`landing.per_14_days`

结构保持 7 个 locale 完全同 key、同 placeholder。

### 3.6 测试

| 文件 | 变更 |
|---|---|
| `api/tests/test_landing.py` | llms trial 断言 7 → 14 days |
| `api/tests/test_ui.py` | 新增 2 个最小契约测试：证据语义/任务互斥/Viewer/Owner-only 门禁/打印；公开 trial 文案与计费 SSOT、Pricing entitlement 同步 |

### 3.7 Evidence Drawer 与服务端 PDF

| 文件 | 变更 |
|---|---|
| `web/app/components/evidence-drawer.js` | 新增证据 drawer：Prompt、原始回答、citations、run/question ID、模型、市场、采样模式、请求 ID、延迟、重试、轮次、检索证据、brand-in-question 与 usage |
| `web/app/components/modal.js` | 新增 `drawer`/`panelClass` 选项，复用原焦点陷阱、Esc、背景关闭与焦点恢复 |
| `web/app/views/engines.js` | 原始回答改为摘要；新增 `Inspect evidence`，用 `data-evidence-index` 绑定真实 sample |
| `web/assets/styles/components.css` | 右侧 540px drawer、证据卡、citation 列表、runtime grid 与移动端底部 sheet |
| `api/adapters/pdf.py` | Markdown → A4 PDF；支持标题、段落、列表、代码、表格、链接；按文档主语言选择 Helvetica 或内置 CJK CID 字体（中文 `STSong-Light`、日文 `HeiseiMin-W3`、韩文 `HYSMyeongJo-Medium`）；页眉/页脚读取既有 branding，白标 logo 失败时降级 |
| `api/projects/delivery_routes.py` | 新增只读端点 `GET /api/v1/projects/{project_id}/deliveries/{delivery_date}/pdf?document=01-Audit-Report`，支持 `01`–`06` 与 `index`，复用 delivery 合约校验 |
| `web/app/api.js` | 新增 `getDeliveryPdfUrl(id, date, document)` |
| `web/app/views/report.js` | 最新报告卡与历史表拆出 `View HTML` / `PDF` 真实链接 |
| `requirements.txt`、`requirements.lock` | 新增 `reportlab`、`pillow` 固定版本 |
| `api/tests/test_delivery_documents.py` | 覆盖 CJK 字体选择、中文 Markdown 实际渲染与 delivery 缺失采样模式文案 |

### 3.8 i18n 与营销截图

| 文件 | 变更 |
|---|---|
| `api/i18n/messages/{en,zh,ja,ko,es,fr,de}.json` | 补齐 198 个界面 key（174 个 `t()` key + 24 个可见状态/默认值），7 locale 同 key、同 placeholder；覆盖 overview/plan/publishing/siteaudit/facts/questions/engine settings/channels/outreach/auth 等 |
| `web/app/views/*.js` | 去除主要硬编码英文与模板 fallback 混用；`engines.js` 的产品名（ChatGPT Search、Google AI Overviews 等）作为产品标识保留 |
| `web/assets/product-overview-real-v2.webp` | 用 `overview-desktop.png` 生成，1440×1000 |
| `web/assets/product-tickets-real-v2.webp` | 用 `tickets-desktop.png` 生成，1440×1000 |
| `web/assets/product-delivery-real-v2.webp`、`product-assets-clay.webp` | 用 `report-desktop.png` 生成，1440×1000 |
| `web/assets/product-audit-clay.webp` | 用 `report-desktop.png` 生成；公开页 alt/caption 改为实际展示的 visibility report，不再声称 site audit |
| `web/index.html`、`web/for-brands.html`、`web/for-agencies.html`、`web/ai-visibility-audit.html` | 同步图片尺寸声明与 alt/caption |

## 4. 完成范围

### P0

- [x] 单一颜色/字体/间距/状态 token；移除 app.css 硬编码霓虹主题
- [x] 营销页不再覆盖全局主题，修复强制深色
- [x] 应用壳、项目切换、移动导航、键盘焦点与角色展示
- [x] Overview cohort、KPI 分母、Unmeasured、任务互斥
- [x] Technical verify 与 AI impact 分离
- [x] Viewer 只读 UI 与 Owner-only 设置门禁；后端鉴权仍是最终判断
- [x] trial 14 天在首页/Pricing/Docs/Terms/llms 同步
- [x] Pricing scheduled monitoring 与后端 `PLAN_FEATURES` 同步
- [x] 报告打印 A4、表头重复、长 URL 换行、无水平裁切
- [x] 375 / 1440 关键页面手动核对

### P1

- [x] Monitor 中位排名、来源缺失诚实呈现、采样模式分组保留
- [x] Tickets readiness/只读/真实 ticket 操作保留
- [x] Delivery readiness checklist 与真实 report_quality 绑定
- [x] Sample report 与应用报告打印样式
- [x] Marketing 首页视觉层统一、真实 CTA 与产品截图保留
- [x] 新增 UI 文案 7 locale 同步
- [x] 现有路由、hash deep link、登录/注册/邀请流程未改
- [x] 认证三页、onboarding、gaps、branding 完成统一视觉与真实状态/错误状态
- [x] 30/30 工作台视图有明确实施落点，无未改造路由

### P2 / 未完成

- [x] `web/app/views/` 30/30 视图已覆盖；本轮最后 6 个为 `auth-forgot`、`auth-invite`、`auth-reset`、`onboarding`、`gaps`、`branding`
- [x] 现有视图中的界面英文标签已 i18n 化；产品名/模型名与后端返回的业务限制说明保持原文；`literal.*` 仅保留合法业务值（`7-day` 分享链接、`Weekly (7 Days)`）
- [ ] 未引入 E2E/视觉回归测试基础设施；仓库当前无 Playwright/Cypress 配置
- [x] 服务端 PDF 导出已实现；浏览器打印仍保留
- [x] 白标页已有真实 logo 预览与重置操作；entitlement 仍由后端 `WHITE_LABEL_PLANS` 决定，未扩展套餐能力
- [x] 旧的无引用 `literal.*` 试用文案已清理到只剩合法业务值；当前页面不再引用旧试用 key
- [x] Evidence Drawer 已重做，数据来自真实 sample replay，不再直接铺开整段原始回答
- [x] 营销页产品图已替换为当前工作台真实截图（1440×1000），未注入指标或伪造客户结果

## 5. 测试与验证

### 5.1 自动化

| 命令 | 结果 |
|---|---|
| `python3 -m pytest api/tests -q` | **620 passed**, 5 warnings, 106.26s |
| `cd engine && python3 -m unittest discover -s tests` | **OK**, 2 skipped |
| `python3 -m pytest api/tests/test_ui.py api/tests/test_i18n.py -q` | **55 passed**, 2.18s |
| `python3 -m pytest api/tests/test_landing.py -q` | **34 passed**, 2.09s |
| `python3 -m pytest api/tests/test_delivery_documents.py api/tests/test_projects.py::test_delivery_pdf_renders_the_selected_markdown_document -q` | **5 passed**（CJK 字体选择、中文 Markdown、PDF `%PDF-`、`application/pdf`、source revision header） |
| `node --check` 全部改动 JS + `landing.js` + `theme-init.js` | pass |
| `test_frontend_view_modules_parse_as_es_modules` | pass（所有 view 作为 ES module 导入） |
| `git diff --check` | pass |

仓库没有前端 lint、typecheck、build、E2E 脚本；未新增测试框架。

### 5.2 手动浏览器核对

使用本地临时 SQLite（`/tmp/ca-ui-Ye5KWO/ui.sqlite`）、真实 FastAPI 路由与 Playwright/Chrome 核对，并在最终 CSS 与 i18n 修改后重新生成全部截图与 PDF：

- 1440：Home（light/dark）、Pricing、Docs、Sample report、Overview、Visibility Matrix、Tickets、Verify、Delivery
- 375：Home、Overview、移动导航抽屉、Visibility Matrix
- 打印：`report-print.pdf`、`sample-report-print.pdf`
- 活动 job 场景：Overview/Engines 的 Sample/Verify 按钮禁用并显示原因
- 空数据场景与有数据场景分别核对：空 workspace 显示 Unmeasured / Readiness not evaluated；临时 fixture 的 2 问题 × 2 引擎样本显示各采样模式独立指标、4 个合格样本与可打开的证据
- 认证页：忘记密码、重置密码、非法邀请三页在 1440 下核对标题、表单、错误文案与返回登录入口
- Onboarding：1440/375 核对字段、模式卡、预检容器；点击 Full baseline 后选中态与提交 payload 的 `no_sample` 同步
- Gaps：无样本时显示 no samples；临时测试夹具验证 `ready` 表格、share denominator、采样模式 badge 与证据问题
- Branding：trial 套餐显示 Agency 限制；临时切换 Agency 后核对可编辑态、重置与保存按钮；截图后恢复 trial
- 深色首页已确认使用 Precision 深色 token，无 `#9df22f` 霓虹残留
- 使用临时 SQLite 增加 Viewer membership，逐页核对 Team、Billing、BYOK、Archive、Outreach、Publishing、Project Settings、Automation、Entities 的按钮禁用与只读提示
- 左侧 rail：1440 light/dark 下悬停与键盘聚焦图标均显示对应功能区名称；`aria-label`、`aria-current` 与 tooltip 文案一致
- Evidence Drawer：用临时 fixture 写入 2 个问题 × 2 个引擎（search / parametric）的真实 replay 行与 metrics，核对 Prompt、原始回答、citations、模型、采样模式、运行 ID、请求 ID、延迟、重试与 usage；1440 drawer 与 375 底部 sheet 均已截图
- 服务端 PDF：英文 delivery 5 页；中文 delivery 2 页，使用 `pdftoppm` 实际渲染检查中文、日文、韩文字体无方框，`·` 已替换为 ` - ` 以规避 CID 字体缺字

本地验证数据来自临时 SQLite 与 `https://example.com` 的空工作区，仅用于截图，不在生产页面注入。

## 6. 截图与打印样例

目录：`docs/design/screenshots/`

| 文件 | 内容 |
|---|---|
| `home-light-desktop.png` | 首页 light，1440 |
| `home-dark-desktop.png` | 首页 dark，1440 |
| `home-mobile-375.png` | 首页移动端 |
| `pricing-desktop.png` | Pricing |
| `docs-desktop.png` | Docs |
| `sample-report-desktop.png` | Sample report（保留 Demo 标识） |
| `overview-desktop.png` | Overview，活动 job + Unmeasured |
| `overview-mobile-375.png` | Overview 移动端 |
| `overview-mobile-nav-375.png` | 移动导航抽屉 |
| `engines-desktop.png` | Visibility Matrix |
| `engines-mobile-375.png` | Visibility Matrix 移动端 |
| `rail-labels-desktop.png` | 左侧 rail 常驻显示图标与功能区文字，不再依赖 hover |
| `i18n-picker-7-desktop.png` | 公开页语言菜单完整显示 7 个 locale |
| `i18n-docs-ja-desktop.png` | 切换日语后的 Docs 页面 |
| `tickets-desktop.png` | Action Tickets |
| `verify-desktop.png` | Closed-Loop Verify |
| `report-desktop.png` | Client Delivery Packs |
| `auth-forgot-desktop.png` | 忘记密码 |
| `auth-reset-desktop.png` | 设置新密码 |
| `auth-invite-invalid-desktop.png` | 非法邀请 |
| `onboarding-desktop.png` | Onboarding + 模式选择 |
| `onboarding-mobile-375.png` | Onboarding 移动端单列 |
| `gaps-desktop.png` | 无样本的诚实空状态 |
| `branding-unavailable-desktop.png` | trial 套餐白标限制 |
| `branding-editable-desktop.png` | 临时 Agency 夹具可编辑态（截图后恢复 trial） |
| `evidence-drawer-desktop.png` | Visibility Matrix 真实 sample evidence drawer，1440 |
| `evidence-drawer-mobile-375.png` | Evidence drawer 移动端底部 sheet，375 |
| `report-print.pdf` | 应用报告 A4 打印（2 页） |
| `sample-report-print.pdf` | Sample report A4 打印（3 页） |
| `delivery-pdf-sample.pdf` | 服务端 PDF 样例，英文 delivery Markdown，5 页 |
| `delivery-pdf-cjk-sample.pdf` | 服务端 PDF 中文 delivery 样例，2 页 |

截图使用本地 fixture 的 `zh` locale，原因是浏览器/存储已选择中文；同一页面可通过语言切换显示 7 个 locale。Evidence Drawer 的 DOM/字段/URL 过滤由 `api/tests/test_ui.py` 静态契约覆盖，运行时回放字段由 `project_samples` 提供。

## 7. 兼容风险

1. **Token 重映射**：旧页面仍使用 legacy 变量别名，颜色/间距会整体变化；已保留 `--page/--surface/--ink/--accent` 等别名，但未逐页截图的历史页面仍可能有视觉差异。
2. **角色默认值**：`AppState.role` 初始为 `viewer`，`/me` 返回后覆盖。短暂加载期会隐藏写操作，属于安全侧降级。
3. **活动 job 判断**：前端以 `queued/running` 禁用按钮；服务端 409 仍为最终权威，未改用前端判断替代后端。
4. **打印样式全局生效**：`app-print.css` 会隐藏所有 app 路由的导航/工具栏；这是有意的打印契约，屏幕样式不受影响。
5. **主题修复**：营销页此前始终深色是代码 bug；修复后跟随系统/本地存储。依赖“永远深色”的截图或外部素材可能需要重新生成。
6. **未改接口**：没有新增后端字段、迁移、计费或权限逻辑；回滚不涉及数据库。
7. **DOM sanitizer 与表单控件**：`safe-html.js` 会移除 `input/select/textarea` 的 `name` 以防止 DOM clobbering。原有 onboarding radio 与 plan influenced-question checkbox 依赖 `name` 选择器，选择可能失效；本轮改用 `data-onboard-mode`、`data-influenced-question`，并增加 Exclusive 选中逻辑，未放宽 sanitizer。
8. **新增 PDF 依赖**：`reportlab>=4.1,<5` 与 `pillow>=10,<12` 进入运行时依赖；若生产镜像未重建，PDF 端点会因缺包失败，其余 delivery/ZIP 功能不受影响。未引入系统级 Chromium/wkhtmltopdf。
9. **PDF 字体**：英文使用 Helvetica；中文/日文/韩文使用 ReportLab 内置 Unicode CID 字体，不依赖系统字体。CID 字符集不含 `·` 等少数符号，已在渲染前替换；若未来加入 emoji 或繁体扩展字，需要重新验证覆盖范围。
10. **截图时点与语言**：截图来自 2026-10-24 的当前工作台与营销页，使用本地 `zh` locale（同一页面支持 7 locale 切换）。截图中的 fixture 数据仅存在于 `/tmp` 临时工作区，未进入生产页面。未用静态样张替代真实页面。

## 8. 回滚点

- 纯前端回滚：还原 `web/app/**`、`web/assets/styles/**`、公开 HTML/CSS 与 i18n 文件。
- 打印回滚：移除 `web/assets/styles/app-print.css` 及 `web/app/index.html` 中的 print link；删除 `web/sample-report.html` 内新增的 `@page`/表头规则。
- 测试回滚：还原 `api/tests/test_ui.py` 新增的两个测试与 `test_landing.py` 的 trial 断言。
- 无数据库迁移、无 API 契约变更、无 trial/套餐配置变更。

## 9. 后续建议

1. 视图已 30/30 覆盖；后续只做深度 polish：清理旧硬编码英文、统一剩余空状态文案、补强 API 失败降级。
2. 若引入浏览器测试，优先补 Overview 空状态、Viewer ticket、活动 job 互斥与 375 宽度；不要复制本轮的手动截图脚本为正式测试。
3. 服务端 PDF 已落地并覆盖英/中/日/韩字体；后续只需在新增特殊符号或 emoji 时补充字体回退测试。
4. 定期用 `TRIAL_DAYS`/`PLAN_FEATURES` 驱动的契约测试防止公开文案再次漂移。

## 10. 2026-10-24 增量：7 locale 对齐与 rail 可读性

### 10.1 语言选择器

- 公开营销站的 `web/assets/landing.js` 原先把 `LOCALES` 限制为 `['en', 'fr']`，与后端 `SUPPORTED_LOCALES = ("en", "zh", "ja", "ko", "es", "fr", "de")` 和 SPA `web/app/i18n.js` 不一致。现已统一为 7 个 locale，隐藏的 `site-locale` select 同步补齐 7 个 option。
- 同步修改 `web/index.html`、`web/docs.html`、`web/blog/index.html` 及 9 个含语言选择器的博客正文页，避免无 JS 或辅助技术读取到旧的 2 项列表。
- 新增完整公开页目录：`api/i18n/messages/public/{ja,ko,es,de}.json`，每个目录 221 个当前公开页实际引用的 key；`zh`/`fr` 保留已有的更多 key。加上既有产品目录后，所有非英文 locale 的缺失 key 为 0。
- 修正 `zh`/`fr` 的存量漂移：`public.g2.sec1_h2`、`public.landing.models_count`、`public.landing.models_aria`，以及法语缺失的 `public.meta.g3_*`、`g4_*`、`g5_*`。
- 产品目录 `api/i18n/messages/{en,zh,ja,ko,es,fr,de}.json` 仍保持 2574 个相同 key；本次检查未发现 placeholder 不一致、空值或 `[[missing:` 标记。

### 10.2 控制台 rail

- `--rail-w` 由 64px 调整为 92px，`rail-btn` 改为图标在上、文字在下的常驻布局。用户无需 hover 或读屏即可识别概览、监测、诊断、执行、交付、设置。
- 保留现有 `aria-label`、`aria-current`、键盘焦点与移动端抽屉；移动端仍使用完整文字导航。

### 10.3 验证

| 命令 | 结果 |
|---|---|
| `python3 -m pytest api/tests -q` | **620 passed**, 5 warnings, 106.26s |
| `python3 -m pytest api/tests/test_landing.py -q` | **34 passed** |
| `python3 -m pytest api/tests/test_i18n.py -q` | **21 passed** |
| `cd engine && python3 -m unittest discover -s tests` | **290 tests OK**, 2 skipped |
| `node --check web/assets/landing.js` | pass |
| `git diff --check` | pass |

浏览器核对（本地临时 SQLite + FastAPI + Chrome）：

- 1440 控制台 rail 常驻显示 6 个功能区中文标签，当前项同时有选中背景和左侧指示条。
- 公开页语言菜单显示 `English / 简体中文 / 日本語 / 한국어 / Español / Français / Deutsch`。
- 选择日语后 `<html lang="ja">`、标题和 Docs H1 均为日语；截图见 `docs/design/screenshots/i18n-picker-7-desktop.png`、`i18n-docs-ja-desktop.png`。

### 10.4 剩余风险

- key 完整性、占位符一致性和空值已自动校验；日语、韩语、西班牙语、德语的语义质量仍需母语者做一次编辑审校，这属于文案质量风险，不是缺 key 或运行时回退。
- 长博客正文仍保留英文原文，语言选择器只切换已提供目录的页面框架与导航文案；未把未翻译的长文伪造成已本地化内容。

## 11. 2026-10-24 增量：营销产品截图与七语言一致

### 11.1 根因与范围

- 营销首页仍引用固定中文 WebP：`product-overview-real-v2.webp`、`product-tickets-real-v2.webp`、`product-delivery-real-v2.webp`。`landing.js` 只切换文案，没有图片选择逻辑，因此切换到任何语言都显示中文截图。
- SEO 页 `for-brands`、`for-agencies`、`ai-visibility-audit` 同样引用固定中文图；这些页面本身没有语言选择器，保持英文页，但产品图改为英文版本，避免英文页面配中文截图。

### 11.2 实施内容

| 文件 / 目录 | 变更 |
|---|---|
| `web/assets/product-{overview,tickets,delivery}-{en,zh,ja,ko,es,fr,de}.webp` | 21 张 1440×1000 真实工作台截图；每种语言使用对应界面语言、真实 i18n 文案与临时 fixture 数据 |
| `web/assets/landing.js` | 新增 `applyProductShots()`；按当前 locale 将 `[data-product-shot]` 的 `src` 或 `href` 切到 `/site-assets/product-<shot>-<locale>.webp` |
| `web/index.html` | Overview、Tickets、Delivery 图与查看链接加入 `data-product-shot`，默认英文资源 |
| `web/for-brands.html`、`web/for-agencies.html`、`web/ai-visibility-audit.html` | 产品图改为英文 delivery 截图，移除固定中文 `*-clay.webp` 引用 |
| `web/app/components/badge.js` | 新增 `samplingModeLabel()`；采样模式徽标复用同一份本地化标签；To Do / In Progress / Done 等状态标签走 i18n |
| `web/app/i18n.js` | 新增 `translateBackendLabel()`、`issueText()`、`ticketField()`；本地化后端基线标签、质量问题、工单语言字段 |
| `web/app/views/overview.js`、`report.js`、`plan.js`、`engines.js`、`competitors.js`、`assets.js` | 清除截图中的中文采样模式、英文基线标签、英文质量问题和英文工单字段 |
| `api/i18n/messages/{en,zh,ja,ko,es,fr,de}.json` | 7 个目录各新增 31 个 key；覆盖摘要理由、代表性/有限/单轮基线、12 类报告质量问题及动作 |
| `api/adapters/localization.py` | `localize_ticket()` 保留任务中已提供的 `*_<locale>` 字段，不再用英文回退覆盖 |
| `api/tests/test_landing.py` | 更新当前产品图断言；校验 21 张 locale 资源可访问，且 `landing.js` 含 `data-product-shot` 契约 |

截图中的工单、域名、样本数与引用仅存在于 `/tmp/ca-shots` 临时 SQLite / 工作目录，未写入仓库样例数据，也未注入生产页面。首页仍保留既有 “Demo · Actual product interface with illustrative workspace data” 免责声明。

### 11.3 验证

| 命令 | 结果 |
|---|---|
| `python3 -m pytest api/tests -q` | **621 passed**, 5 warnings |
| `python3 -m pytest api/tests/test_landing.py api/tests/test_i18n.py -q` | **56 passed** |
| `cd engine && python3 -m unittest discover -s tests` | **290 tests OK**, 2 skipped |
| `node --check web/assets/landing.js` + 8 个改动 JS 文件 | pass |
| `git diff --check` | pass |

浏览器核对（本地 FastAPI + Chrome，1440×1000）：

- 首页依次切换 `en / zh / ja / ko / es / fr / de`，`[data-product-shot]` 的图片与查看链接均切换为对应语言资源；`<html lang>` 分别为 `en / zh-CN / ja / ko / es / fr / de`。
- 日语、法语、韩语 Overview / Action Tickets / Delivery 截图中不再出现中文采样模式、中文 KPI 或中文按钮；日期输入使用显式 `2026-11-07`，避免原生占位符回退。
- SEO 页无语言选择器，保持英文页面与英文产品图，不再出现中文截图。

### 11.4 截图路径

| 文件 | 说明 |
|---|---|
| `docs/design/screenshots/marketing-home-overview-en.png` | 英文首页 Brand Overview 区块 |
| `docs/design/screenshots/marketing-home-overview-ja.png` | 日语首页 Brand Overview 区块 |
| `docs/design/screenshots/marketing-home-overview-fr.png` | 法语首页 Brand Overview 区块 |
| `docs/design/screenshots/marketing-home-product-en.png` | 英文首页 Tickets / Delivery 区块 |
| `docs/design/screenshots/marketing-home-product-ja.png` | 日语首页 Tickets / Delivery 区块 |
| `docs/design/screenshots/marketing-home-product-fr.png` | 法语首页 Tickets / Delivery 区块 |

### 11.5 兼容风险与后续

- 21 张截图是静态资产；工作台可见文案或布局再次变化时需要重新生成，否则会与产品界面漂移。生成脚本未进入仓库，临时 fixture 仅在 `/tmp`。
- 真实项目的工单业务内容可能仍以英文或用户输入语言出现；本轮只保证界面标签、标准状态、基线标签、质量问题与摘要走 i18n，不翻译用户/引擎内容。
- 旧版 `product-*-real-v2.webp` 与 `*-clay.webp` 保留用于兼容外部引用和 `scripts/acceptance.py`，当前营销 HTML 已不再引用。
- 回滚：还原上述 HTML / JS / i18n / localization 文件，并删除 21 张 `product-{overview,tickets,delivery}-<locale>.webp`；无数据库、计费或 API 契约变更。
