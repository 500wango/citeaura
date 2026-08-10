# CiteAura UI 重构方案

## 决策（已确认）

- **范围**：落地页 + 应用内 UI，统一为一套设计系统
- **路线**：新建独立前端 `web/app/`，直连 `/api/v1`，淘汰 `engine/scripts/ui.html` 嵌入 + `api/ui.py` 补丁层
- **技术栈**：Vanilla（原生 ES Modules，无构建步骤），FastAPI 静态伺服
- **重构重点**：视觉风格

## 现状核心问题

1. **落地页**：字体声明了从未加载；主题切换失效（找不存在的 `meta[name=theme-color]`）；滚动渐显是空操作；暗色变量重复声明；6 个 logo 文件职责重叠
2. **应用 UI**：补丁叠补丁——引擎 ui.html（暗紫）之上叠加 `PRODUCT_UI_STYLE`（700 行 `!important` 覆盖，靛蓝）、`FETCH_ADAPTER`（700 行 fetch 猴子补丁）、`UI_EXTENSION`（重写 `renderSide`、包装视图、中文字符串当 i18n key）；登录框有两套打架的样式
3. **割裂**：落地页浅色 / 应用暗色，两套视觉语言、两套 i18n 实现

## 设计方向

**概念**：「精密测量仪器」——CiteAura 的卖点是测量严谨性，视觉应传达精确、可信、克制，而不是 AI SaaS 常见的炫技感。

### 色彩（OKLCH 调色）
- **主色：深青碧 teal**（约 `oklch(0.55 0.11 195)`）。理由：避开 AI SaaS 泛滥的 indigo/violet（现状正是这套），teal 传达精确与可信，中英日市场都不撞色
- **用量**：Whisper 级——近中性暖调画布（chroma < 0.02），主色只出现在关键动作、当前态、数据强调（60-30-10）
- **状态色**：good/warn/bad 微调至与主色同明度族；数据可视化给一套以主色为锚的 5–7 色色盲安全色板
- **双主题**：一套 token 定义 light + dark。落地页默认浅色，应用默认跟随系统；手动切换持久化（localStorage + 正确的 `meta[name=theme-color]`）
- Logo 检查：现有 logo 若与新主色冲突，重绘为单色 mark，用 CSS mask 着色（图标已是 mask 方案）

### 字体（这次真正加载）
- Display：**Space Grotesk**（几何技术感，契合测量定位）
- 正文/UI：系统字体栈（PingFang SC / Noto Sans JP / Segoe UI），零延迟且 CJK 质量好
- 数据/数字：**JetBrains Mono** + `tabular-nums`
- 全部 woff2 **自托管**到 `web/assets/fonts/`（`font-display:swap`，unicode-range 子集），不依赖 CDN

### 排版与布局
- 字阶比例 ≥ 1.3，正文 measure 60–76ch；应用正文 13.5–14px，数据表 12.5px
- 间距只取 4/16/36 三档（1-4-9 节奏）；落地页 section 垂直留白 ≥ 96px
- 落地页（Decide/Brand 注册）：首屏 = 价值主张 h1 + 真实产品截图证据（现在 h1 只有品牌名）；保留三采样模式标注（硬约束 #7）；模块化分区，避免"卡片堆"
- 应用（Operate/Monitor 注册）：保留现有 6 模块轨道 IA（概览/监测/诊断/执行/交付/管理——结构是对的），重建为原生组件；提高密度、明确层级

### 交互与动效
- 每个组件覆盖 9 态（idle/hover/active/focus/loading/empty/error/disabled/overflow）
- `:focus-visible` 全局 2px 主色环；触摸目标 ≥ 44px
- 动效：150–250ms、expo-out、只动 transform/opacity、 stagger 20ms±5；`prefers-reduced-motion` 完整支持
- 文案：按钮一个动词、错误给恢复路径、空状态教用户下一步、句首大写、无感叹号

## 目标架构

```
web/
├── index.html                  # 落地页（重写）
├── app/
│   ├── index.html              # SPA 外壳（含 #view 挂载点、noscript）
│   ├── app.js                  # 启动、hash 路由、全局 store、任务轮询
│   ├── api.js                  # 类型化 /api/v1 客户端（取代 FETCH_ADAPTER）
│   ├── i18n.js                 # 统一目录加载（点号 key，t() 函数）
│   ├── views/                  # 每视图一个 ES module（24 个）
│   └── components/             # modal/toast/table/tabs/seg/kpi/empty/skeleton
└── assets/
    ├── fonts/                  # 自托管 woff2
    └── styles/
        ├── tokens.css          # 色彩/间距/字体/圆角/阴影 token（light+dark）
        ├── base.css            # reset、排版、focus、滚动条
        ├── components.css      # 按钮/卡片/表格/表单/标签/modal/toast
        ├── landing.css         # 落地页专用
        └── app.css             # 应用外壳 + 视图专用
```

- **原生 ES Modules**（`<script type="module">`），无构建；`api/main.py` 增加 `app.mount("/app", StaticFiles(html=True))`
- **api.js**：fetch 封装——cookie 会话头、401→refresh→重试一次、错误规整 `{error}`；每个路由一个具名方法，URL 集中定义（对照 `api/*/router.py` ~90 个端点，无后端改动）
- **i18n 统一**：废弃 `UI_D` 中文 key 字典和落地页独立加载器；视图全部用点号 key，三语目录 `api/i18n/messages/{en,zh,ja}.json` 扩充（落地页 key 已有范式）；落地页与应用共用 `/i18n/{locale}.json`（顺带修掉 `api/landing.py` 每次请求清缓存重读磁盘的 bug）
- **认证**：SPA 内置独立登录/注册/找回密码视图（复用 `/api/v1/auth/*`），取代注入式 modal；保留 OIDC 入口和邀请/重置 token 流程
- **引擎边界**：`engine/` 零修改，引擎测试保持全绿

## 分阶段实施

**Phase 0 · 设计基础**
- 写 `.commandcode/design/brief.md`（/design setup 格式：名称/类别/用户/任务/工件/证据/拒绝项）
- 落地 `tokens.css` + `base.css` + `components.css`，字体自托管
- 清理 `web/assets/` logo 冗余（保留一套：mark.svg + logo.svg）

**Phase 1 · 落地页重建**
- 重写 `web/index.html` + `landing.css` + `landing.js`：修掉字体加载、主题切换、滚动渐显、meta 翻译 4 个现存 bug
- 新首屏：价值主张 h1 + 实测证据截图；补齐 ja 产品截图；价格区加货币本地化说明
- 验证 6 视口 × 2 主题 × 3 语言

**Phase 2 · 应用地基**
- `app/index.html` / `app.js` / `api.js` / `i18n.js` / 组件库
- 认证流 + 轨道导航外壳 + 项目切换器 + 任务轮询（`jobs` 端点）

**Phase 3 · 核心视图 P0**
- onboarding（新建品牌）、overview、engines、questions、plan（工单）、report（交付下载）
- 这 6 个视图覆盖主工作流，可用于内测

**Phase 4 · 其余视图 P1**
- competitors、siteaudit、gaps、channels、facts、workbench、assets、outreach、verify、publishing、branding、project-settings、automation、archive、engine-settings、integrations、team、billing、security（18 个）

**Phase 5 · 切换与清退**
- 新 SPA 挂 `/app/v2` 并行验证 → 达标后 `/app` 指向新 SPA，旧版移到 `/app/legacy` 保留一个迭代
- 清退 `api/ui.py` 中的 `FETCH_ADAPTER` / `UI_EXTENSION` / 三段注入样式（文件从 ~3400 行瘦身到只剩静态伺服 + `/files`）
- 同步更新 `AGENTS.md`（"不做前端重写"一条已过期）与 `tasks.md`

## 受影响文件

**新建**：`web/app/**`、`web/assets/styles/{tokens,base,components,landing,app}.css`、`web/assets/fonts/`
**重写**：`web/index.html`、`web/assets/landing.js`
**修改**：`api/main.py`（挂载）、`api/landing.py`（缓存 bug）、`api/i18n/messages/*.json`（扩 key）、`api/ui.py`（Phase 5 瘦身）、`AGENTS.md`、`tasks.md`
**测试更新**：`api/tests/test_ui.py`（断言旧注入 HTML，需重写为 SPA 冒烟）、`api/tests/test_landing.py`
**不动**：`engine/` 全部、`api/*/router.py`（API 面已完整）

## 验证

1. `cd engine && python3 -m unittest discover -s tests` — 全绿
2. `cd api && pytest tests/ -v` — 全绿（含更新后的 UI/landing 测试）
3. i18n key 奇偶校验脚本：三语 JSON key 集合必须一致
4. 视觉验收：起本地服务，用浏览器逐路由截图（6 视口 320/375/768/1024/1440/2560 × 2 主题 × 3 语言）；过 squint test（每屏 3 个重点可辨）；对比度 ≥ 4.5:1（正文）/ 3:1（大字与控件）
5. 功能回归：主链路手工走查——注册→建品牌→bootstrap→采样→工单→交付下载；任务轮询、401 刷新、邀请/重置流程
6. 性能：首屏无阻塞字体（swap）、路由级视图懒加载（动态 import）、Lighthouse 性能/可访问性 ≥ 90

## 风险与对策

- **24 视图重建量大** → 分 P0/P1 两批，`/app/legacy` 兜底，随时可回退
- **旧 UI 承载隐式行为**（如 fetch 补丁里的 engines/framing 聚合）→ 重写 api.js 时逐端点对照 `FETCH_ADAPTER` 的翻译表，确保等价调用 v1
- **i18n 迁移漏 key** → key 奇偶校验脚本 + 视图渲染时缺 key 报错（开发模式）
- **设计走样** → Phase 0 先出 brief + tokens，落地页先行定调，应用沿用同一系统
