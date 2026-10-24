---
title: "CiteAura · Precision SaaS UI/UX 实施规格"
version: "1.0"
date: "2026-10-24"
status: "Ready for Codex repository implementation"
owner: "CiteAura"
implementation_language: "Adapt to the existing repository"
---

# CiteAura · Precision SaaS UI/UX 实施规格

> **实施目标**：在不破坏现有业务功能、API、计费、权限、数据语义及 SEO 的前提下，为 CiteAura 营销官网、登录后工作台和诊断/交付报告建立一套统一的 **Evidence-Driven Precision SaaS** 界面系统。
>
> **Codex 使用方式**：将此文件放到仓库根目录（推荐 `docs/design/CITEAURA_UI_SPEC.md`），把第 1 章的指令粘贴给 Codex。具体代码路径、路由、技术栈、数据结构必须以实际仓库为准；本文中的目录与类型仅为目标架构，不得当作已经存在的事实。

## 0. 状态与优先级约定

- **[KNOWN]**：已从 CiteAura 公开网站/文档确认的产品行为；无法证明它与代码仓库当前版本完全一致。
- **[SPEC]**：本次改版必须执行的产品/UI 规范。
- **[PROPOSED]**：目标设计或示例类型；实现前须适配现有技术栈。
- **P0**：业务正确性、关键体验或视觉基础；不满足不能发布。
- **P1**：高价值功能页面与统一设计；应在本轮完成。
- **P2**：增强体验；资源有限时可延后。
- **禁止**：为满足 UI 而伪造测量结果、重写业务计算口径、虚构后端字段或新增不能正常运行的按钮。

---

# 1. 直接交给 Codex 的执行指令

以下为可直接复制到 Codex 的主任务。**不要跳过先审计代码的步骤**。

```text
你是 CiteAura 代码仓库中的资深前端工程师 / Design Systems Engineer。
你的任务是按仓库根目录 docs/design/CITEAURA_UI_SPEC.md（或我提供的同名文件）实施统一的 Precision SaaS UI，而不是另起一个无法接入真实业务的静态样板。

工作方法：
1. 首先检查仓库：README、package scripts、路由、前端框架、现有组件、样式系统、i18n、主题、认证/租户、API 调用、report/print/export、测试和 CI；列出实际文件路径及受影响页面。不要假设项目使用 React、Next.js、Tailwind、shadcn/ui 或任何特定库。
2. 在仓库内创建 docs/design/UI_IMPLEMENTATION_AUDIT.md：记录现状、现有路由到目标页面的映射、已有可复用组件、风险、明确不改动的接口和实现批次。若发现文档与运行时代码冲突，以代码的业务行为为准，并记录差异。
3. 在不改变核心业务的条件下实施：先 design tokens / primitives，再导航布局、营销页面、工作台重点模块，最后报告预览与打印。小批次、可审查地提交；如已有 git 工作区改动，不覆盖或删除用户代码。
4. 保留现有注册、登录、项目切换、计费、BYOK、采样任务、ticket、verification、delivery、权限和多语言流程；不要更改后端契约或计算定义。如确实需要新增接口，先记录必要性与兼容方案，不得默默引入破坏性变更。
5. 任何新 UI 元素必须连接现有真实状态和操作。若实际数据/能力尚不存在，展示诚实的空状态或暂不显示该模块；禁止在真实页面注入示例指标、伪造趋势、假链接或无功能按钮。Mock 仅限组件预览、Storybook、测试夹具和明确标注的官方 demo 页面。
6. 每个批次运行仓库现有 lint / typecheck / unit / build / E2E（按实际可用命令）；修复本批引入的问题。为高风险语义添加测试，包括 Unmeasured、采样模式、cohort 可比性、任务互斥、权限和报告导出。
7. 不要直接改计费/试用天数。先查唯一真实配置源，统一首页、Pricing、Docs、CTA 和应用内文案；若业务配置与公开页面矛盾，只按真实配置同步展示，不自行决定 7 天或 14 天。
8. 实施时遵守本规格全部 P0、P1 验收标准。结束后在 docs/design/UI_IMPLEMENTATION_REPORT.md 写清：改了哪些文件、完成/未完成范围、测试命令与结果、手动核对项、截图路径、潜在兼容风险以及后续事项。
9. 若完整范围较大，分成能独立运行的提交/PR 顺序执行，不为“完成全部 UI”牺牲生产稳定性。遇到缺失数据可选择有据可查的降级呈现，并在报告中说明。

现在开始先审计仓库，然后实现，不要先写脱离代码的纯设计提案。
```

**Codex 第一条交付**：`UI_IMPLEMENTATION_AUDIT.md`，包含真实技术栈、路由图、设计系统落点、现有业务约束、测试命令及拆分计划。**Codex 最终交付**：可运行代码、自动化测试与 `UI_IMPLEMENTATION_REPORT.md`。

---

# 2. 目标与范围

## 2.1 总体方向

**[SPEC] 视觉定位**：`Evidence-Driven Precision SaaS`，即浅色精密工作台、可信数据展示、可追溯证据与克制的技术品牌语言。

- 官网：**Editorial SaaS**（大标题、清晰叙事、真实产品预览、明确转化路径）。
- 工作台：**Operational SaaS**（高信息密度、紧凑但可读、操作优先、状态可追溯）。
- 报告：**Auditable Reporting**（适合客户阅读、打印、归档、复核）。
- 三者共享颜色 Token、排版规则、状态语义、图表规范和证据组件。

**[SPEC] 不采用**：全屏霓虹渐变、重度玻璃拟态、依赖酷炫动效代替内容的 AI landing page、严重压缩对比度的灰白文字、缺少分母的“大数字”仪表盘。

## 2.2 实施范围

| 区域 | 页面/工作流 | 优先级 | 完成定义 |
|---|---|---:|---|
| Foundations | Tokens、字体、间距、图标、交互状态、主题 | P0 | 所有新界面复用语义 Token，不散落硬编码色值 |
| Global Marketing | Header、Footer、CTA、移动导航、语言切换 | P0 | 路径有效；权限与语言行为不退化 |
| Home | Hero、实际产品预览、Measure→Diagnose→Verify、定价入口 | P1 | 首页完成统一视觉和真实跳转 |
| Solutions | For Brands、For Agencies | P1 | 面向不同受众的重点模块与 CTA |
| Pricing | 统一试用/价格呈现、BYOK 边界、套餐比较 | P0 | 文案与真实配置一致；不改计费逻辑 |
| Docs / Methodology | 可读排版、导航、代码块、术语链接 | P1 | 保留原 URL、SEO 和内容语义 |
| Workspace Shell | 项目切换、侧边栏、顶栏、响应式导航 | P0 | 真实角色与现有路由保持兼容 |
| Overview | KPI、cohort 元信息、任务、进度、空状态 | P0 | 全部读取真实数据，展示分母与来源 |
| Monitor | Visibility Matrix、Citation Sources、回答证据 | P1 | 不混合采样模式，不伪造来源 |
| Diagnostics | Site-wide Audit、问题集、品牌事实 | P1 | 技术诊断与 AI 观察区分 |
| Execution | Action Tickets、Assets、证据联动 | P1 | 状态变更和验收逻辑保留 |
| Verify & Deliver | 验证结果、交付包、可用状态 | P1 | 保留技术验证和可见性重采样区别 |
| Reports | Sample Report、报告预览、打印样式、白标 | P1 | 打印无截断且保留证据边界 |
| Polish | 深色模式、微动效、复杂移动图表 | P2 | 不影响主流程、支持 reduced motion |

## 2.3 不在本轮范围

- 不重写后端采样、SEO/GEO 诊断、ticket 自动生成或计费算法。
- 不新增 AI 模型供应商、改造 BYOK 密钥处理或更改消费者权限。
- 不改变租户数据隔离策略、报告生成文件格式及现有 ZIP 合约（除非现有前端仅需 CSS/布局升级）。
- 不将所有旧路由强行改名。导航文案可优化，但历史深链、分享 URL 和书签必须继续工作。
- 不宣称通过技术审计就能保证 AI 提及、引用或排名。

---

# 3. 产品事实与必须保留的业务语义

以下事实来自 2026-10-24 核验的公开页面；**实际代码仍需二次确认**。

1. **[KNOWN]** CiteAura 的主流程为站点爬取/测量、诊断、工程任务、技术验证与客户交付；初始诊断可在未配置采样条件时运行。来源：`https://citeaura.com/docs`。
2. **[KNOWN]** 三类采样模式：`API · Model knowledge`、`API · Web-grounded retrieval`、`Manual · Product surface`；不得在 UI 中混合标成单一来源。来源：`https://citeaura.com/docs`。
3. **[KNOWN]** Mention rate 的基数是**成功且符合条件的回答**；包含品牌名的问题不能作为该指标的普通分母。Citation sources 仅来自返回 URL 的联网采样。来源：`https://citeaura.com/docs`。
4. **[KNOWN]** `Unmeasured` 表示没有可用合格观察值，**不是 0%**；问题集、供应商、采样模式与市场变化会影响前后可比性。来源：`https://citeaura.com/docs`。
5. **[KNOWN]** `Closed-Loop Verify` 会重新爬取与运行技术验收，但不自动采集新的 AI 回答；可见性变化需单独重新采样。来源：`https://citeaura.com/docs`。
6. **[KNOWN]** 同一项目通常只允许一个活动 job；Queued/Running 阶段启动新任务可能冲突。来源：`https://citeaura.com/docs`。
7. **[KNOWN]** 示例报告明确声明 synthetic/demo，并包含技术检查、AI 样本、工程工单和交付状态。来源：`https://citeaura.com/sample-report`。
8. **[KNOWN]** 首页公开文案为 **14-day trial**，Pricing 和 Docs 公开文案为 **7-day trial**，存在跨页不一致。来源：`https://citeaura.com/`、`https://citeaura.com/pricing`、`https://citeaura.com/docs`。

### 3.1 不可违反的数据规则（P0）

- `null` / 无 qualifying observations → **Unmeasured / —**，不得渲染 `0%`、零柱形或零趋势。
- 技术检查通过 → **Technical check passed**，不得自动显示 **AI impact confirmed**。
- 只有可比 cohort（问题集版本、model/provider、mode、市场/时间定义）才允许默认直接画前后趋势；不可比时显示 **Not directly comparable** 和具体原因。
- `Citation share` 以**抓取到的来源 URL 样本**为基础，不表述为整个互联网的份额。
- 现有报表中的 `Avg Rank` 若业务上为**中位数**，只可修改表头/解释，不可为了“名副其实”悄悄改成算术平均。
- 原始证据 `questionId`、`runId`、`modelId`、`mode`、`sourceUrls`、`observedAt` 等若现有数据提供，必须可以通过交互到达。
- 未返回的字段不得由 UI 自动补写。示例数据仅可用于明确标识为 demo 的页面或测试环境。
- 所有可能触发账单、外部 API 花费或敏感写操作的按钮，继续遵守现有权限、确认与配额规则。

---

# 4. Design Tokens（直接可实施）

## 4.1 字体

**[SPEC]** 英文优先 `Geist`（仓库若已有合规的 Inter/系统字体则沿用），中文优先 `Noto Sans SC`，fallback `-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`；数据数字启用 tabular numbers；代码/ID 使用现有 monospace 字体。

| Token | Desktop | 用途 |
|---|---|---|
| `display` | 56px / 1.12 / 700 | 首页 Hero；移动端降为 36px |
| `h1` | 36px / 1.22 / 700 | 顶级页面标题 |
| `h2` | 28px / 1.29 / 650 | 章节标题 |
| `h3` | 20px / 1.4 / 600 | 卡片/模块标题 |
| `body-lg` | 16px / 1.625 / 400 | 营销/报告正文 |
| `body` | 14px / 1.57 / 400 | 工作台正文 |
| `caption` | 12px / 1.5 / 400 | 标签/次级说明 |
| `metric` | 30px / 1.2 / 650 | 主要 KPI |

- 工作台 14px 可用于紧凑表格，但不把整站正文压缩到 12px。
- 内容层级优先通过字号、字重和留白区分，不大量增加颜色。
- 数值、时间、比率采用一致的 `font-variant-numeric: tabular-nums`。

## 4.2 颜色与语义变量

**[SPEC]** 以如下 CSS 为**目标值**，项目若使用 Tailwind、CSS-in-JS、Sass 等，转换为同义的主题 Token。务必先检查对比度，必要时微调辅助色。

```css
:root {
  color-scheme: light;
  --ca-brand-600: #2563eb;
  --ca-brand-700: #1d4ed8;
  --ca-graphite: #0b1220;
  --ca-canvas: #f8fafc;
  --ca-surface: #ffffff;
  --ca-surface-subtle: #f1f5f9;
  --ca-border: #e2e8f0;
  --ca-border-strong: #cbd5e1;
  --ca-text-primary: #0b1220;
  --ca-text-secondary: #475569;
  --ca-text-muted: #64748b;
  --ca-focus: #2563eb;
  --ca-success: #0f766e;
  --ca-warning: #b45309;
  --ca-danger: #b91c1c;
  --ca-radius-xs: 4px;
  --ca-radius-sm: 8px;
  --ca-radius-card: 12px;
  --ca-space-1: 4px;
  --ca-space-2: 8px;
  --ca-space-3: 12px;
  --ca-space-4: 16px;
  --ca-space-5: 20px;
  --ca-space-6: 24px;
  --ca-space-8: 32px;
  --ca-space-12: 48px;
  --ca-shadow-raised: 0 8px 24px rgba(11,18,32,.07);
  --ca-marketing-max: 1200px;
  --ca-workspace-max: 1600px;
  --ca-sidebar-width: 248px;
  --ca-sidebar-compact: 64px;
  --ca-header-height: 64px;
}
```

- 80% 中性背景、15% 深色信息、5% 蓝/语义强调是**视觉指导**，不是要精确计算面积。
- 蓝色表示可操作/选中；青绿色限于明确的成功状态；黄色为复核；红色为错误/关键风险。
- 新增颜色先在主题表中注册；禁止在不同页面创造多个语义相同但值不同的“品牌蓝”。
- 默认先完成浅色模式。已有深色模式应维护可读性；新增深色主题为 P2。

## 4.3 布局、形状与动效

| 对象 | Desktop | Mobile / 备注 |
|---|---|---|
| 官网主体 | `max-width:1200px`，左右 padding 24–32px | 16–20px |
| 工作台主体 | `max-width:1600px`，随视口伸缩 | 单列，必要时子区域横向滚动 |
| 左侧导航 | 248px，折叠 64px | 抽屉式导航 |
| 顶部导航 | 64px 高 | 保留当前项目、主要任务入口 |
| 输入框/标准按钮 | 40px 高，radius 8px | 主要触控区建议 ≥44px |
| 小按钮 | 36px 高 | 避免窄屏密集排列 |
| 卡片 | radius 10–12px，padding 20–24px | 16px |
| 证据 Drawer | 宽 440–520px，可滚动 | 全屏/底部 Sheet |
| 桌面表格行 | 44–52px | 可隐藏非关键列；数据表局部滚动 |
| 动效 | 120–180ms 色彩/位移/透明度 | 尊重 `prefers-reduced-motion` |

**[SPEC]** 优先 1px 边框，而不是重阴影或玻璃效果。交互必须有 `:focus-visible`、hover、loading、disabled 和可理解的失败提示。

---

# 5. 共用组件合同（Component Contracts）

> **实现原则**：先搜索现有仓库组件；能扩展则扩展，避免平行造轮子。以下属性是组件的“语义合同”，不是必须强制使用 TypeScript/React 的硬性条件。

## 5.1 基础组件（P0）

- `Button`：`variant=primary|secondary|ghost|danger`、`size=sm|md|lg`、loading/disabled/icon；所有有副作用的按钮显示 pending 状态并阻止重复提交。
- `Card`：标题、说明、action、children、loading/empty/error；保持统一边框、背景、内边距。
- `Input` / `Select` / `Search`：关联 label、helper text、error、required；键盘可用。
- `Tabs` / `SegmentedControl`：选中状态可辨别；Url/tab state 依照现有深链规则。
- `DataTable`：排序、筛选、分页、空状态、可访问表头；不能在客户端“排序假数据”。
- `Badge`：`neutral|info|success|warning|danger`，状态必须同时显示文案，不只用颜色。
- `Drawer`：焦点管理、Esc 关闭、关闭后焦点返回触发控件；窄屏替换为 full-screen sheet。
- `Dialog`：破坏性操作二次确认，确认过程中禁用重复提交。
- `EmptyState` / `ErrorState` / `LoadingSkeleton`：所有异步模块强制覆盖这三类状态。
- `PageHeader`：面包屑/标题、次级说明、顶级 CTA、次要操作，应用全站一致。

## 5.2 业务组件（P0/P1）

| 组件 | 输入（绑定现有真实数据） | 显示/交互合同 | 禁止行为 |
|---|---|---|---|
| `MetricCard` | value、unit、count、scope、status、trend、asOf | 数值、样本/范围、计算说明入口 | 无数据时显示 0 |
| `CohortSummaryBar` | questionSet、providers、mode、market、window、eligibleCount | 可见的比较边界；可定位筛选 | 混合 incompatible cohort |
| `EvidenceModeBadge` | 现有 mode 枚举 | 三类清楚可辨的来源文本 | 统一写成 AI |
| `EvidenceDrawer` | 原始 observation + source refs | prompt、raw answer、model、mode、time、URLs、ticket link | 根据汇总数据编造原始回答 |
| `FindingCard` | finding id、severity、pages、evidence、acceptance | 观察→证据→建议→验收 | 暗示技术修复证明提升引用 |
| `TicketDetail` | ticket、owner、status、evidence、check | 可编辑字段遵守现有角色；写入用现有操作 | 绕过审核/权限状态 |
| `VerificationResult` | checker result、time、run id、reason | Technical pass/fail/review 独立于 AI effect | Pass 自动映射为 impact |
| `JobStatus` | status、stage、progress、error、retryAllowed | 顶栏入口+详情面板 | 允许运行中的重复冲突任务 |
| `ReportReadiness` | 实际 export/approval 状态 | 是否可交付、阻塞项及边界 | “已打包”默认为“已验证” |

### 5.3 语义类型草案（按实际 API 映射，不重写后端）

```ts
// Illustrative view-model only. Do not change API contracts to match this example.
type MeasurementState = 'measured' | 'unmeasured' | 'limited' | 'failed';
type EvidenceMode = 'api_knowledge' | 'api_web_grounded' | 'manual_product_surface';
type TechnicalCheckStatus = 'pass' | 'fail' | 'review' | 'not_run';
type JobState = 'queued' | 'running' | 'done' | 'failed';

interface MetricViewModel {
  label: string;
  state: MeasurementState;
  value: number | null;             // null when unmeasured; 0 is real 0
  formattedValue?: string;          // output of existing business formatter
  eligibleSampleCount?: number | null;
  denominatorLabel?: string;
  definition?: string;
  cohortId?: string;
  asOf?: string;
  comparableToPrior?: boolean;
  comparabilityReason?: string;
}

interface EvidenceViewModel {
  id: string;
  questionId?: string;
  runId?: string;
  provider?: string;
  modelId?: string;
  mode?: EvidenceMode;
  observedAt?: string;
  prompt?: string;
  rawAnswer?: string;
  sourceUrls?: string[];
  ticketIds?: string[];
}
```

**[SPEC]** `MetricCard` 展示规则：`state='unmeasured'` 或 `value === null` 时输出 `—` + `Unmeasured`，并解释缺少什么；仅当已有合格样本且值确实为零时显示 `0%`。错误状态不得转成零。`comparabilityReason` 存在时图表上清楚标注，不画暗示可直接比较的增长箭头。

---

# 6. 营销官网详细实现

**[SPEC]** 首先复用现有 URL、页面内容、SEO 元数据和语言体系，再升级视觉。以下是目标模块顺序，不要求重写已经正确的营销文案。

## 6.1 Global Header / Footer（P0）

- 桌面 Header：Logo；Product（Overview/How It Works/Features）、Solutions（Brands/Agencies）、Resources（Docs/Guides/Methodology/Sample Report）、Pricing；Sign In；主 CTA。
- 移动 Header：Logo、主 CTA（空间允许时）、菜单；菜单展开可键盘操作且防止背景页面滚动。
- Sticky 行为：滚动时保持低对比细边框，可收紧内边距，但不遮挡锚点。
- 现有语言选择、登录/注册/试用链接全部保留真实目标；外链明确行为。
- Footer：产品说明、重要入口、隐私/条款、版权；链接不出现 404。
- **P0**：首页/Pricing/Docs/应用内试用时长由**同一业务配置**派生文案。若静态公开 Docs 不能动态获取，则用构建时配置或内容检查防止漂移。

## 6.2 Homepage（P1）

推荐模块结构：

1. **Hero**：保留现有主定位 `Track your AI visibility. Know what to fix.`；一句副标题；Primary CTA `Start free trial`（或与有效 trial 配置匹配）；Secondary CTA `View a sample report`。
2. **真实工作台预览**：现有的实际产品界面截图；标注 `Demo · Illustrative workspace data`。不要用 AI 生成的虚假 dashboard 伪称真实产品。
3. **三个支柱**：`Measure → Diagnose → Verify`，分别说明测量、诊断与独立验证；不要把 Execute 消失，可在第二块下呈现 ticket 工作流。
4. **Evidence Walkthrough**：展示从 AI answer → source citation → finding → ticket → checker 的关联样例，可用官网已有明确 demo 内容。
5. **Measurement Boundaries**：解释三种采样模式、样本限制和 Unmeasured。
6. **For Brands / For Agencies**：两个受众卡片，使用现有准确的能力描述与入口。
7. **Sample Report Preview**：报告缩略/摘要，点击进入真实 `/sample-report`。
8. **Pricing / FAQ**：复用计费事实，不克隆第二份难以同步的数据。
9. **Final CTA**：一个主行动和可选低门槛免费审计入口。

Hero 视觉：浅色背景；大标题 56px（移动 36px）；正文 16–18px；主 CTA 实色品牌蓝；产品界面放在大容器中，截图可放大查看；不使用重动画。

**验收**：Hero 首屏无横向溢出，CTA 路径有效，截图 `alt` 有意义，FAQ 结构与页面 SEO 不退化，示例数据始终保留 demo 标识。

## 6.3 For Brands / For Agencies（P1）

- **Brands**：强调公共站点证据、结构化品牌事实、采样范围、Site Audit 和可执行行动；关联 `Run a free technical audit`。
- **Agencies**：强调多客户隔离、工单、审批/复核、白标交付；关联 `View a sample report`。
- 页面组件可共用 `SolutionHero` / `WorkflowSteps` / `FeaturePreview` / `FAQ`，但内容不要单纯替换标题。
- 沿用现有实际截图；若资源不存在，使用简洁的 HTML 示意并明确 `Illustration`，不得伪称后台实测。

## 6.4 Pricing（P0/P1）

- 从现有套餐配置读取套餐名称、价格、active projects、BYOK、scheduled monitoring、白标及 trial 条件。**没有可验证配置源时，不改价格，只修正视觉和标注冲突待定**。
- 套餐比较：高亮推荐方案须基于现有商业策略；不可随意把旧套餐写为“最受欢迎”。
- 每个套餐 CTA 都与真实结算/注册流程一致。
- 明确 provider 模型调用成本与平台订阅费用分离，以及不保证 AI 提及/排名。
- 价格显示在不同语言、货币、月/年切换中保持一致，若现有产品未支持某切换，则不要假造。

## 6.5 Docs / Methodology（P1）

- 内容栏宽度 720–800px；左侧目录、右侧锚点（如果现有）；小屏折叠为顶部/抽屉目录。
- 代码块支持横向滚动、复制按钮；表格局部滚动，不造成整页横向溢出。
- 锚点保留；标题语义从 H1 到 H3 正确递进；保持既有 canonical、JSON-LD、OG、meta 等 SEO 资产。
- 重要术语（sampling mode、cohort、citation share、unmeasured）链接到已有文档定义。

---

# 7. 登录后 Workspace 详细实现

## 7.1 App Shell 与路由映射（P0）

**[SPEC]** 视觉上按业务流程聚合导航，但不假定或强制改写原 URL：

| 目标分组 | 目标导航项 | 与现有功能对应 |
|---|---|---|
| Main | Overview | 当前项目概览、job 信息 |
| Measure | Visibility Matrix、Citation Sources、Competitor Benchmark | Monitor 下的现有视图 |
| Diagnose | Site-wide Audit、Perception Gaps、Target Questions、Brand Facts | Diagnostics 下的现有视图 |
| Execute | Action Tickets、Evidence Workbench、Assets & Templates | Execution 下的现有视图 |
| Verify & Deliver | Closed-Loop Verify、Client Delivery Packs | 现有 Verify / Delivery |
| Settings | Brand、Model Keys、Schedule、Team、Billing、Branding 等 | 既有设置及角色规则 |

- 折叠侧栏时仍能通过 tooltip 或 `aria-label` 区分图标。
- 当前项目入口始终可达，切换租户/项目后所有查询自动按现有逻辑更新，绝不残留上个项目的敏感数据。
- 顶栏：当前位置/项目、重要任务状态、帮助、账户；新增 Jobs 入口只读取现有任务状态。
- 隐藏或禁用没有权限的动作，遵守现有 RBAC；不能仅靠前端隐藏代替后端鉴权。
- 项目相关深链、浏览器前进后退以及直接刷新后保持正常。

## 7.2 Overview（P0）

从上到下：

**A. PageHeader**：`Brand Overview`、项目/站点、last sampled、主操作（根据当前权限与任务状态使用 `Run Sampling` / `Fill Sample Gaps` 等**真实可用动作**）。

**B. `CohortSummaryBar`**：清楚显示 question-set version、provider、sampling mode、time window、eligible sample count；无可用数据则显示为何未测量。

**C. KPI 组**（若现有 API 能提供）：`Mention Rate`、`Citation metric`（使用实际口径）、`Audit Checks / Score`、`Open Tickets`。每个指标有数字/状态、分母或范围、详情入口；不要凭空构造 audit score。

**D. 内容主体**：左侧 Visibility Trend（仅可比数据）；右侧 Next Actions（真实 ticket）；下方 Recent Jobs / Verification Activity（现有数据）。

**E. 数据状态**：没有 provider 配置 → 呈现配置入口；没有成功采样 → `Unmeasured`；正在跑任务 → 任务进度而非旧数据冒充最新。

**验收**：指标详情可追溯，基数显示正确，所有 CTA 可执行或诚实禁用，时间戳按一致时区逻辑格式化。

## 7.3 Monitor：Visibility Matrix & Citation Sources（P1）

- 筛选：provider/model、sampling mode、question set、时间范围、status；默认按现有产品可比性约束组合。
- Matrix：支持列的明确含义；`rank` 如为 median，应在说明里写 `Median reported position`；不显示误导的平均值。
- 每个带 observation 的单元格可打开 `EvidenceDrawer`，展示 exact prompt、raw answer、brand match、model、mode、run time、sources。
- Citation Sources：仅显示联网检索返回的 URLs；参数知识模式没有链接时显示 `No source URLs for this mode`，不显示虚构的域名 share。
- 对来源可使用安全的外链 `rel="noopener noreferrer"`，处理恶意 HTML/超长 URL；不要将原始模型返回内容直接解释为可信 HTML。
- 避免图表中混合不同 mode 后产生不加说明的“总趋势”。

## 7.4 Diagnostics：Site Audit / Inputs（P1）

- 审计首页：检查组、适用项、pass/fail/review/skipped、page-level findings、重新审计入口。
- `FindingCard` 固定区块顺序：`Observation → Evidence → Impact/Scope → Recommended Action → Acceptance Criteria`。
- 点击问题查看来源 URL、爬取时间、检查器、证据；能创建/打开关联 Ticket 时接真实 handler。
- Target Questions、Brand Fact Library 维持编辑和审核语义；修改问题集后，后续 trend UI 要说明 cohort 已变化。
- `llms.txt` 检查通过仅显示文件可达/格式满足检查；不能显示“已被所有 AI 搜索引擎采用”。

## 7.5 Execution：Tickets / Assets（P1）

- 主区域：可筛选的 Tickets 表格（priority、type、owner、status、last changed、evidence count）+ 详情 Drawer/Panel。
- Ticket Detail：标题、目标 URL、问题说明、证据、建议改动、验收条件、负责人、实际执行状态、验证历史。
- 只有现有权限允许的角色可编辑；所有写入走原有 API、pending/error/undo（已有时）流程。
- Assets：提供审阅状态、来源证据、下载/编辑操作；默认文案始终强调生成资产要人工审核。
- 新视觉不得隐去 Pending Review、In Verification、Regression 等既有状态。

## 7.6 Verify / Delivery（P1）

- **Verify Changes**：展示 run timestamp、技术 checker、pass/fail/review、失败原因、关联合同/工单及可触发的复测。
- 若要评估 AI answer 效果，按钮必须调到**真实单独采样流程**，不能把技术 Verify 伪装成效果测量。
- **Client Delivery Packs**：构建前显示 `Readiness Checklist`：最近数据、未审查资产、未测量 provider、失败/待复核技术检查、报告版本。
- 按现有状态生成/下载 ZIP 或现有报告格式；没有白标权限不能显示可用的白标配置。
- 下载列表展示生成时间、对应 project/run 和 readiness 分类；老交付包不得被伪装为最新状态。

## 7.7 Job 状态（P0）

`queued`、`running`、`done`、`failed` 使用完整文案 + 图标，支持查看阶段、错误消息与已有重试操作。对会导致冲突的新任务按钮：禁用并用 tooltip/辅助说明解释 `A project job is already running`；仍要正确处理服务端 409/类似冲突返回，不假设前端判断无竞态。

---

# 8. 诊断报告与打印导出（P1）

## 8.1 三层阅读结构

- **Executive**：负责人快速阅读的一页/几页摘要，包含范围、关键发现、风险及前三条建议。
- **Diagnostic**：详细方法、可见性样本、技术审计、原始证据、限制。
- **Implementation**：Ticket、负责人、验收条件、技术验证、交付状态。

如当前只有一种真实报告生成方式，**先用不同章节风格表达三层结构**，不要擅自加三个无后端支持的下载按钮。多模板导出为可选后续功能。

## 8.2 页面内容顺序

1. Cover：CiteAura/白标 Logo、客户/项目、网站、报告类型、测量范围、日期、版本、demo 标志（若适用）。
2. Executive Summary：关键发现（不是空泛承诺）、可执行优先级、限制概述。
3. Scope & Methodology：provider、model、mode、question-set version、时间、合格样本数、未测量项。
4. Visibility Baseline：仅展示可解释且有样本的数据；清楚标注每个比例的分母。
5. Citation & Competitive Evidence：来源和相应原始 observation，必要时只摘要并提供证据索引。
6. Technical Audit：按检查类别、URL、状态、适用范围归组。
7. Evidence Detail：Evidence ID、prompt、raw answer 摘录（有长度限制可溯源）、source URLs、run metadata。
8. Action Plan：工单编号、影响、优先级、负责人、建议行动和验收条件。
9. Verification & Delivery：technical pass/fail/manual review，与 AI effect observation 分开。
10. Appendix：指标定义、来源索引、报告构建时间、未完成/不可用数据。

## 8.3 Finding Card（打印/屏幕共用）

统一字段顺序：

`Finding ID` → `Priority` → `Title` → `Observation` → `Evidence/Source` → `Affected Pages` → `Recommended Action` → `Acceptance Criteria` → `Verification State` → `Limitations`。

不要求所有字段都存在；缺失时显示正确状态，而不是占位 lorem ipsum 或假 ID。

## 8.4 Print CSS 合同

```css
@media print {
  @page { size: A4 portrait; margin: 16mm 18mm; }
  body { background: #fff !important; color: #0b1220 !important; }
  .no-print, [data-ui="nav"], [data-ui="toolbar"] { display: none !important; }
  .report-section, .finding-card { break-inside: avoid; }
  thead { display: table-header-group; }
  a { color: inherit; text-decoration: underline; }
}
```

- 以上选择器须映射实际组件；不应通过全局 `body` print 规则破坏其他可打印路由。
- 每页重要标题尽量与首段同行；表格可跨页，重复表头。需要长表时优先允许行换行，不把整张表当作不可分页大块。
- 避免水平裁切；URL 可换行；图表导出保留轴标签/图例；纯黑白打印仍能通过文字判断状态。
- `Print / Export PDF` 延续现有行为；如果现有是浏览器打印，则先实现可打印 CSS，不擅自引入服务端 PDF 系统。
- 白标：只覆盖允许定制的 Logo、客户标识、封面主色/联系信息，保留数据与证据边界；若产品权限不足，维持受限状态。

---

# 9. 响应式、无障碍与性能（P0）

## 9.1 断点行为

- `>=1440px`：完整侧栏、多列 dashboard、官网内容居中。
- `1024–1439px`：侧栏可折叠，关键视图自适应。
- `768–1023px`：指标卡 2 列；复杂表格局部滚动；证据 Drawer 可用。
- `<768px`：官网单列；工作台导航抽屉；指标单/双列按实际宽度；抽屉改为全屏 Sheet。**整页不得横向溢出**（明确的表格内部横向滚动除外）。

断点以现有项目系统为准，可用等效值，不要求重写全站媒体查询。

## 9.2 Accessibility 验收

- 目标 WCAG 2.2 AA；普通文本对比度至少 4.5:1，重要界面图形/大字号文本至少 3:1（按适用规则）。
- 鼠标、触控、键盘都能完成项目切换、筛选、打开证据、处理 ticket、导出报告。
- 键盘 Tab 顺序合理，抽屉/弹窗有焦点管理，Escape 可以关闭非阻塞浮层。
- 图表存在文本摘要或可读数据表；状态有文字，不只依靠色彩。
- 所有图片有合适的 `alt`；装饰图可使用空 alt；表格标题和表头可被屏幕阅读器识别。
- `prefers-reduced-motion` 时去除非必要动画；错误提示在字段附近并可理解。

## 9.3 性能与可维护性

- 避免一次加载全部 evidence 详情；复杂列表采用现有分页/虚拟列表策略。
- 稳定 layout，给截图/图表分配尺寸避免 CLS；保留图片资源优化、字体加载和 SEO 性能。
- 不为单次界面更新引入大型新依赖；先检查现有 icon/theme/chart 方案。
- 每个颜色与间距通过 Token 维护，除了语义例外不散落 magic numbers。

---

# 10. 测试方案与验收矩阵

## 10.1 必需的自动化/手工场景

| ID | 场景 | 通过条件 | 级别 |
|---|---|---|---|
| ACC-01 | 未配置 provider、无观测 | Mention Rate 显示 `Unmeasured`，不显示 `0%` | P0 |
| ACC-02 | 有合格样本但无 mention | 显示真实 `0%` 以及 eligible denominator | P0 |
| ACC-03 | knowledge mode 无来源 URLs | Citation Sources 不创造 source URL，也不显示虚假 share | P0 |
| ACC-04 | 改变 question-set/mode | 趋势比较有不可比标注，不展示误导性差值 | P0 |
| ACC-05 | Technical Verify pass | 显示技术通过，但 AI impact 仍独立 | P0 |
| ACC-06 | 项目 job running | 新 job 按钮禁用并解释原因；服务端冲突能处理 | P0 |
| ACC-07 | Viewer 角色打开 Ticket | 不允许绕过权限进行修改 | P0 |
| ACC-08 | 切换项目/租户 | 不残留上一项目的敏感数据 | P0 |
| ACC-09 | Pricing/trial | 首页、Pricing、Docs 与真实试用配置一致 | P0 |
| ACC-10 | demo/official report | Synthetic 结果保留显著 Demo 标识 | P0 |
| ACC-11 | 宽度 375/768/1280/1440 | 核心页面无不可控横向溢出、遮挡 | P0 |
| ACC-12 | 键盘导航 | 主要交互、菜单、Drawer、Dialog 均可用 | P0 |
| ACC-13 | `/sample-report` 打印 | A4 内容完整，表格/卡片无裁切 | P1 |
| ACC-14 | i18n 切换 | 新增 UI 字符串支持仓库现有语言策略 | P1 |
| ACC-15 | 原登录/订阅/下载流程 | 端到端功能不退化 | P0 |
| ACC-16 | 首页 CTA、导航、锚点 | 指向真实页面，不出现死链 | P1 |

**[SPEC]** 用真实 API fixture / 仓库已有 mock 构造上述测试，所有虚构样本仅存测试目录或 Storybook；不要把表格中的测试值硬编码进生产页面。

## 10.2 需要保留或增加的测试类型

1. `typecheck / lint / production build`（按仓库实际 scripts）。
2. 组件单测：`MetricCard`、`EvidenceModeBadge`、`JobStatus`、`ReportReadiness`。
3. 集成测试：项目切换与权限、ticket 更新、采样按钮任务互斥、Evidence Drawer、report readiness。
4. 浏览器 E2E/视觉测试（有 Playwright/Cypress 则复用）：首页、Pricing、Dashboard、Monitor、Audit、Ticket、Report。
5. 打印视觉测试：至少报告封面、含长 URL 证据卡、跨页表格、白标头部。
6. 响应式截图：375、768、1280、1440 宽度，支持仓库现有快照存放规范。

---

# 11. 分批实施顺序（Codex 执行清单）

## PR-00 — 代码与产品审计（P0）

- [ ] 查明框架、路由、前端包、全局主题、组件位置、i18n、测试与报告实现。
- [ ] 输出实际路线图 `UI_IMPLEMENTATION_AUDIT.md`。
- [ ] 检查 trial 配置唯一数据源与各页面不一致文案。
- [ ] 建立现有关键路由/业务的基线测试，记录当前通过情况。

## PR-01 — Foundations（P0）

- [ ] 增加/迁移 semantic tokens，保留旧变量的兼容映射。
- [ ] 升级 Button、Card、Input、Tabs、Badge、Empty/Error/Loading、PageHeader。
- [ ] 保证 focus、颜色对比度和 loading/disabled 一致。
- [ ] 建立组件预览（若仓库有现成工具则复用，无则最小可运行组件测试）。

## PR-02 — Workspace Shell & Overview（P0）

- [ ] 升级顶栏、侧栏、项目切换、Jobs 可见性。
- [ ] Overview 加入 cohort 和可追溯 KPI，绑定现有真实数据。
- [ ] 处理 no data、in progress、API error、权限不足状态。
- [ ] 路由、权限、租户与现有写操作回归测试。

## PR-03 — Evidence / Diagnosis / Execution（P1）

- [ ] 完善 Matrix/Citation 页面筛选及证据 Drawer。
- [ ] 统一 FindingCard、TicketDetail、VerificationResult。
- [ ] 保留原始答案、采样方式、技术验证与可见性观察的分离。
- [ ] 覆盖 ACC-01 至 ACC-08 的关键回归测试。

## PR-04 — Report & Delivery（P1）

- [ ] 统一 sample report 与应用 report preview 的视觉规范。
- [ ] 加入范围/方法/证据/验收/限制章节格式。
- [ ] 完成 A4 print 样式，验证长 URL、长表、分页。
- [ ] 白标内容遵守现有 entitlement；交付包仍按原格式导出。

## PR-05 — Marketing Alignment（P1）

- [ ] Header / Footer / Home / Brands / Agencies / Pricing / Docs 统一视觉语言。
- [ ] 保持 CTA、注册、SEO、已有公开内容与合法说明。
- [ ] 修复 trial 文案冲突（只依据真实配置，不修改账单逻辑）。
- [ ] 检查 375/768/1280/1440 响应式。

## PR-06 — QA & Handoff（P0/P1）

- [ ] 完整运行测试和 build，汇总命令及结果。
- [ ] 生成关键页面对比截图和报告打印示例（存入仓库约定位置）。
- [ ] 修复测试中暴露的交互、可访问性和布局缺陷。
- [ ] 完成 `UI_IMPLEMENTATION_REPORT.md`，列明实际变更、剩余缺口、发布风险和回滚点。

**提交策略**：每个 PR 结束后均应保持项目能 build 和正常使用；文案、布局和组件重构不得与无关后端迁移混成单次大改。

---

# 12. 完成定义（Definition of Done）

整轮改造只有在以下事项全部满足时，才标记 `Done`：

- [ ] 官网、工作台、报告使用统一品牌颜色、字体、间距和组件样式。
- [ ] UI 绑定真实业务数据，演示数据只出现在明确 demo 环境。
- [ ] Unmeasured、sampling mode、cohort、technical verification 的数据语义保留。
- [ ] 主要功能、导航、权限、登录、试用/计费、采样、ticket、导出未回归。
- [ ] 实际 trial 时长在官网、Pricing、Docs 和应用内一致。
- [ ] 页面覆盖 Desktop/Tablet/Mobile 主流宽度。
- [ ] 组件加载、空、错误、权限不足和任务冲突状态有明确呈现。
- [ ] 报告打印清晰完整，保留 evidence/limitation 和演示标签。
- [ ] 所有新增 UI 文案遵守项目现有 i18n 机制。
- [ ] 测试结果记录于实现报告，失败和未完成项清楚列出。

---

# 13. 交付模板：Codex 最终应提交什么

```text
docs/design/
  CITEAURA_UI_SPEC.md             # 本规格（或现有同名文件）
  UI_IMPLEMENTATION_AUDIT.md      # 代码现状、实际映射与分批计划
  UI_IMPLEMENTATION_REPORT.md     # 变更总结、测试结果、风险与截图位置

[existing frontend source]        # 对真实组件与页面的修改
[existing tests]                  # 新增/更新的业务语义和视觉回归测试
```

`UI_IMPLEMENTATION_REPORT.md` 至少包含：

1. 实际技术栈/路由/组件落点。
2. 每个 PR 对应修改文件及理由。
3. 已完成 P0/P1/P2 与未完成事项（不得全部勾选但代码未落地）。
4. lint、typecheck、test、build、E2E 运行结果；不能运行时说明阻塞。
5. 关键视图截图：Home、Overview、Evidence、Ticket、Report Print、Mobile。
6. trial 配置真实来源及最终显示值。
7. 安全和兼容性注意事项、回滚方式。

---

# 14. 已核验的参考页面（非代码仓库事实）

- 首页：<https://citeaura.com/>
- 定价：<https://citeaura.com/pricing>
- 品牌方案：<https://citeaura.com/for-brands>
- Agency 方案：<https://citeaura.com/for-agencies>
- 产品文档：<https://citeaura.com/docs>
- 示例诊断报告：<https://citeaura.com/sample-report>

**结语（实施原则）**：网站负责解释价值，工作台负责推动真实任务，报告负责交付可复核证据。任何视觉选择若削弱样本边界、改变指标含义或破坏现有业务流程，都必须让位于数据正确性和功能稳定性。
