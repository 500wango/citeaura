# CiteAura 易懂性开发计划

日期：2026-09-06

## 目标

在不改变引擎公共接口和核心数据来源的前提下，完成一条非专业用户可独立使用的路径：

`Overview 结论 → Finding 详情 → Ticket 执行 → Verification 验收 → Before/After 进展`

首轮只使用现有报告、工单、审计、采样和验收数据；数据不足时明确显示 `unmeasured`、`needs review` 或 `not comparable`。

## 不做

- 不新增模型、采样平台、自动发布或移动端。
- 不重写 `engine/` 公共接口。
- 不引入新的前端框架、状态管理库或独立数据副本。
- 不新增预测 ROI、因果归因或自动决策规则。
- 不为当前改动建立大规模端到端测试体系。

## 开发原则

- 优先复用现有 `report_quality`、`tickets`、`visibility_plan` 和 verification 数据。
- 业务结论由后端提供结构化字段，前端负责展示；不在模板中解析长文案推断状态。
- 一个 finding 使用稳定 ID 关联 ticket、证据和验收记录。
- 状态只允许事实可证明的迁移：`observed → planned → in_progress → website_verified → remeasured`。
- 结论旁始终显示证据范围：样本数、平台/模型、采样模式、时间和可比性。

## 阶段与交付物

### D0：真实流程基线与字段盘点

**工作：**

- 选一个已有真实项目，完整走一遍 Overview、Report、Plan、Tickets、Verify。
- 记录每个需要人工解释的断点，以及对应的现有 API 字段。
- 建立字段映射表：finding、ticket、URL、question/prompt、evidence、acceptance、verification、baseline。

**涉及文件：**只读 `web/app/views/overview.js`、`plan.js`、`report.js`、相关 API 路由和适配器。

**完成条件：** 确认至少一个最高优先级问题可以用现有数据贯通；无法贯通的字段列为明确缺口，不先加兼容层。

### D1：后端提供用户结论模型

**工作：**

- 在现有 report/quality 响应中增加最小结构化 `user_summary`：`headline`、`why_it_matters`、`recommended_action`、`evidence_scope`、`limitations`、`next_route`。
- 增加 `primary_finding`，引用既有 finding/ticket ID，不复制完整证据。
- 增加明确的 `progress_state`，区分网站整改、验收和 AI 复测。
- 缺数据时返回状态和原因，不填充合成数字。

**涉及文件：**优先 `api/projects/reporting.py`、现有 report quality/visibility plan 适配器及对应 schema；不改 engine。

**验证：**新增或更新最多 2 个 API 测试：完整证据路径、无样本路径。现有 API 回归测试必须保持通过。

### D2：Overview 首屏改为单一结论和动作

**工作：**

- 在 `web/app/views/overview.js` 顶部渲染 `user_summary`。
- 将四个 KPI 降为证据卡片，补充业务解释和范围信息。
- 只保留一个主要 CTA；其他动作降为次级入口。
- 将诊断、可见度、实施和复测状态合并为一条进度链。
- 首屏保留 Demo/合成基准、未测量和待审核提示。

**涉及文件：**`web/app/views/overview.js`、对应 i18n catalog、必要的 `app.css`。

**验证：**更新 UI 契约测试，覆盖已测量和未测量两个状态；检查 1440px、768px、390px 无溢出和文字截断。

### D3：Finding、Ticket、Verification 详情贯通

**工作：**

- 在现有 Plan 或 Ticket 视图增加 finding 摘要、相关 URL/Prompt、证据展开和验收条件。
- 所有入口使用稳定 ID 跳转同一详情位置，避免三套重复模板。
- 将状态文案固定为“修改完成”“网站验收通过”“AI 结果已复测”，禁止用一个 `done` 覆盖三者。
- 失败、待审核、未测量使用统一状态组件。

**涉及文件：**`web/app/views/plan.js`、相关 ticket/verification view 和共享组件；优先复用现有 API。

**验证：**增加一个主路径 UI/API 测试，确认 finding 能定位到 ticket 和 acceptance；补一个失败/未测量状态断言即可。

### D4：进展和交付叙事

**工作：**

- 在 Report 页面将“现状、最重要发现、建议先做的三件事、证据限制”置于正文开头。
- 复用现有 before/after 数据，仅在键集合可比时显示变化。
- 把原始回答、引用和技术元数据放入可展开附录。
- 交付包继续分开标注 `diagnostic_ready`、`visibility_ready`、`implementation_ready`。

**涉及文件：**`web/app/views/report.js`、报告渲染适配器、现有交付测试。

**验证：**运行相关 delivery/report 测试；检查无可比周期时不会生成趋势或因果措辞。

### D5：真实用户验收与收敛

**工作：**

- 邀请 5 位目标用户，其中老板和营销人员都要覆盖。
- 每人独立完成：说出当前发现、打开最高优先级 ticket、找到证据、说明验收方式。
- 记录完成时间、误解点和需要口头解释的句子。
- 同一概念被两名以上用户误解时，优先改信息层级和文案；不立即增加功能。

**通过条件：** 至少 4/5 用户在 2 分钟内复述发现和下一步，至少 4/5 用户能独立找到对应证据和验收方式。

## 推荐实施顺序

1. D0 字段盘点
2. D1 后端结构化结论
3. D2 Overview 首屏
4. D3 详情贯通
5. D4 报告和交付
6. D5 用户验收

每阶段完成后运行对应测试和 `git diff --check`，确认后再进入下一阶段。

## 停止与回退

- 如果 D0 发现现有数据无法支持主要结论，先补最小数据来源或显示未测量，不在前端猜测。
- 如果 D2 后用户仍无法说出下一步，暂停 D3/D4，重新审查结论模型和信息层级。
- 如果 D5 无法达到通过条件，停止推广扩张，重新选择目标场景或调整产品承诺。

## 最终验收

- 老板能看懂现状、优先事项和进展边界。
- 营销人员能找到具体页面、证据、修改动作和验收方式。
- 技术人员可展开原始样本、引用、平台/模型、采样模式和时间戳。
- 普通用户输出不把红色状态、Demo 数据或诊断就绪误读为错误、真实结果或已发布。
- API、前端 UI、交付和引擎相关现有测试保持通过。
