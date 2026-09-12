# Docs 与产品实现一致性检查

检查日期：2026-09-12。范围：公开 `/docs`、该页使用的七种主语言目录及中法公共译文。依据为当前工作区实现，未使用产品规划代替已实现功能，未操作生产账户或调用真实模型、SMTP、GitHub。

## 已修正

| 问题 | 当前实现与文档修正 | 依据 |
|---|---|---|
| 成本与工期被写成固定事实 | 移除“API 成本低于 Starter 月费 1%”和固定 30／60 天窗口；改为模型费用独立、取决于供应商、模型与调用量。试用准确表述为新工作区 7 天试用。 | `api/billing/plans.py`、`api/projects/lifecycle_routes.py:project_preflight` |
| 初始流程未说明采样前提 | 自动排队初始诊断；只有采样权限和配置允许时才运行 AI 采样，否则保留未测量状态。 | `api/projects/lifecycle_routes.py:create_project` |
| 内置供应商数量过时 | 由六家更新为十家，补充 GLM、Doubao、Kimi、MiniMax，并说明项目市场与配置会影响可用范围。 | `web/app/views/engine-settings.js:AVAILABLE_ENGINES`、`api/adapters/engine.py:ENGINE_KEY_ENV`、`engine/scripts/sample.py:PROVIDERS` |
| 密钥配置入口及权限不准确 | 自定义入口为实际按钮 `Add Provider`；密钥由工作区所有者管理。 | `web/app/views/engine-settings.js`、`api/settings/router.py` |
| 密钥生命周期承诺过强 | 密钥在引擎操作上下文中使用，而非仅在单个网络调用时存在；删除配置不取消已运行任务，也不在供应商侧撤销凭据。 | `api/adapters/engine.py:with_tenant_context`、`api/settings/router.py:delete_key` |
| 提及率缺少分母限制 | 排除问题本身含品牌名称的样本；矩阵按供应商与采样模式分组。 | `api/projects/reporting.py:engine_rows_by_mode` |
| 排名统计被描述为平均数 | 文档说明矩阵使用记录位次的中位位置，缺失保持未测量；明确现有界面仍标为 `Avg Rank`。未改业务计算或界面标签。 | `api/projects/reporting.py:engine_rows_by_mode`、`web/app/views/engines.js` |
| 外联与发布描述停留在“草稿” | 说明配置 SMTP 后可经人工确认发送；GitHub 支持选择已批准资产、创建分支和 PR，不自动合并或部署。两个入口均在 Settings。 | `api/outreach/router.py`、`web/app/views/publishing.js`、`api/publishing/router.py` |
| 验收状态与 AI 复采混淆 | 区分 pass／fail／manual 与工单重新打开；验收重新抓取和审计，使用已有指标，不采集新 AI 回答。 | `engine/scripts/verify.py:run`、`web/app/views/verify.js` |
| 交付按钮、生成条件与成果就绪度不准确 | 使用当前 `Build Diagnostic Pack` 标签；区分审核包、诊断包和实施包；诊断包不以完成实施、验收为前提，模板不会因导出而自动可部署。FAQ 和 JSON-LD 同步。 | `web/app/views/report.js`、`api/projects/delivery_routes.py` |
| 白标入口与套餐条件遗漏 | 改为 Settings → White-Label Branding，并说明 Agency／Enterprise 所有者可配置。 | `web/app/app.js:TRACKS`、`api/branding/router.py` |
| 自动监测周期遗漏每日选项 | 改为 1／7／14／30 天，验收仍单独触发。 | `web/app/views/automation.js`、`api/projects/schemas.py:ScheduleRequest` |
| 快照恢复被误解为完整回滚 | 说明需要配置备份存储和所有者权限；恢复合并快照文件，可确认覆盖同路径，快照外文件保留。 | `api/archive/router.py`、`api/adapters/archive.py:restore_archive` |
| 无法执行命令仅归因于并发任务 | 补充角色、有效试用或订阅及用量限制。 | `api/auth/deps.py`、`api/billing/limits.py`、`api/projects/sampling_routes.py` |
| 中文译文额外夸大能力 | 去除“固定 13 个工单”“不可篡改证据”“已评估高权重域名”等缺乏实现依据的承诺。 | `web/app/views/plan.js`、`api/adapters/citation_sources.py`、项目文件存储实现 |

## 核对后保留

- 同一项目仅允许一个排队或运行中的任务；任务有独立状态和日志。
- 三类采样模式保持区分；Citation Sources 只聚合成功、启用搜索且实际返回引用 URL 的样本，不代表全网份额。
- 自定义端点使用 HTTPS；服务端连接测试成功后才保存配置；密钥使用 AES-256-GCM 加密，读取接口返回脱敏标识。
- 目标问题、品牌事实、技术审计、工单、证据工作台、资产、团队角色与 OIDC 控制均有对应实现。
- `/llms.txt` 可用性不代表被模型采用；产品不保证 AI 提及、引用或排名。

## 验证与边界

- Landing／i18n／UI 现有测试：82 项通过，1 条既有依赖弃用警告；未新增测试框架或业务测试。
- Chromium 检查七种语言的实际 DOM 与目录值一致；英法切换、手机与桌面无横向溢出或页面异常；服务端 HTML、文档锚点、FAQ JSON-LD 一致性通过。
- 本次只修文档及该页译文；没有扩展产品功能、修改统计计算或触发生产部署。
- 供应商控制台的开户步骤不是本次产品实现核对的实测范围；生产服务配置与真实外部调用结果需另行验证。
