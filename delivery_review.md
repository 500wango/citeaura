# CiteAura 交付包代码审查

审查基线：`190a4ee`。范围包括交付包生成与校验、Worker 完成状态、下载与公开分享、平台池计量、报告页展示，以及现有交付包。本文区分当前代码缺陷与旧包遗留；本轮未修改产品代码。

## 结论

“交付还有一堆错误”不是单一渲染问题。根因集中在四处：交付包没有不可变版本标识；读请求会重建历史包；生成、校验和计量使用了不一致的数据口径；交付失败没有进入持久化 Job 状态。它们会造成历史证据被改写、不完整包被发送、失败样本进入结论、任务假成功及平台调用漏记。

## 高优先级问题

### 1. 新构建默认覆盖最近的历史日期包

- 位置：`api/adapters/delivery_package.py:655-705`
- `ensure_delivery_contract()` 未显式传入目录时先调用 `_latest_delivery()`；只有完全没有旧包时才使用当天日期。
- 因此 2026-09-20 触发构建时，若最新目录是 `2026-08-27`，新内容会写回 `2026-08-27`，不会创建 `2026-09-20`。
- 影响：包名、交付日期和内容生成时间失真，历史快照被覆盖。
- 修复方向：默认构建必须创建新的不可变 `pack_id`；日期只用于展示，不能作为唯一版本标识。

### 2. 下载和公开分享 GET 会重写历史快照

- 位置：`api/projects/delivery_routes.py:140-160`、`api/projects/delivery_routes.py:216-230`、`api/projects/public.py:338-356`
- 现有包校验失败后，读请求直接调用 `ensure_delivery_contract(project.slug, directory)`，使用当前 `audit.json`、`tasks.json`、样本和资产覆盖原日期目录。
- `delivery_routes.py` 的注释称已发布包是 immutable snapshot，实际行为相反；匿名公开下载也能触发写入和重建。
- 影响：客户先前收到的内容会静默变化，审计链和验收证据不可追溯。
- 修复方向：GET 只读；迁移或重建必须是显式、已认证的写操作，并生成新版本。

### 3. 当前校验器接受缺少 07/08 证据目录的旧包

- 位置：`api/adapters/delivery_common.py:187-203`；对照当前生成门禁 `api/adapters/delivery_package.py:174-190`
- 校验器只检查 01-06、CSV 和 `assets/index.json`，之后信任旧包内的 `quality_gate.status == passed`。
- 当前生成合同还要求 `07-Evidence/raw-ai-answers.jsonl`、`raw-ai-answers.html`、`citation-evidence.csv`，以及 `08-Before-After/visibility-delta.md`、`.html`。
- 已检查的旧包缺少这些文件，但仍被判为有效。
- 版本边界：缺目录本身来自旧版本 `af57aa61`；当前缺陷是校验器仍接受它们，并允许进入下载和发送路径。
- 修复方向：引入 `contract_version`，按对应合同逐项复核，不信任包内自报的历史布尔值。

### 4. 失败样本进入原始证据和前后对比计算

- 位置：`api/adapters/delivery_evidence.py:22-29`、`:141-177`；相关口径 `api/adapters/delivery_common.py:673-706`
- `_rows()` 过滤市场和问题身份，但不要求 `row["ok"]` 为真；HTTP 429 等失败记录仍会导出，并参与 cohort 对齐和比率计算。
- 已复现：一条成功、一条 `HTTP 429` 失败时，导出两条记录且 `comparable=True`。
- `report_quality.assess()` 会过滤失败样本，所以同一交付包内会出现彼此冲突的样本数量。
- 修复方向：所有测量、证据导出和 before/after 统一使用同一个“成功且属于当前 cohort”的过滤器。

### 5. 交付失败后 Job 仍显示 done，Project 仍显示 ready

- 位置：`api/worker/tasks.py:110-121`、`:251-262`、`:474-502`；`api/worker/worker_job_lifecycle.py:164-177`；`api/projects/jobs.py:23-62`
- `_safe_delivery_contract()` 捕获所有异常并返回字符串；没有异常逃逸时，Job 生命周期按成功结束。
- `delivery_error` 只存在于 Celery 返回值，Job 模型和 API 不保存也不展示它。
- 影响：用户看到 100% complete，随后才在下载或分享时发现无包、旧包或无效包。
- 修复方向：承诺生成交付包的动作应在交付失败时失败；若保留部分成功，必须持久化并展示明确的 `partial` 状态。

### 6. 嵌套平台池计量会漏记同一 Job 的早期调用

- 位置：`api/worker/tasks.py:403-409`；`api/worker/worker_pipeline.py:60-72`；`api/billing/platform_pool.py:136-149`、`:157-213`；`api/models.py:454-460`
- 整条管线已有外层 meter，交付 gap-fill 又开启内层 meter；ContextVar 被内层临时替换。
- 内层先按唯一键 `(job_id, engine_code)` 入账，外层随后写早期调用时触发 `ON CONFLICT DO NOTHING`，导致早期调用丢失。
- `api/adapters/sampling_control.py:354-366` 还会覆盖同一 Job 的预留值，而不是累加。
- 修复方向：同一 Job 复用一个 meter 并统一结算；或为阶段设置独立幂等键后原子汇总。

## 中优先级问题

### 7. 交付列表暴露临时、备份和不完整目录

- 位置：`api/projects/delivery_routes.py:95-125`
- 列表返回 `delivery/` 下所有目录，不检查正式命名、合同完整性或发布状态。
- `.delivery-english-*`、`.YYYY-MM-DD.backup` 和不完整日期目录均可能显示；下载端只接受严格日期，因而产生 400/404/409。
- 修复方向：列表仅返回已发布且通过最小 manifest 校验的正式包。

### 8. 公开分享可在重建后发送 `review_required` 包

- 位置：`api/projects/delivery_routes.py:216-233`、`api/projects/public.py:338-356`
- 创建 token 前会检查 sendability；公开下载重建后没有再次拒绝 `review_required`。
- 分享记录又只绑定日期而非具体内容，因此旧 token 可能指向后来生成的待复核包。
- 修复方向：share 绑定不可变包，并在公开下载时校验该包的可发送状态。

### 9. SMTP 失败会提交有效 token，但错误响应不返回 URL

- 位置：`api/projects/delivery_routes.py:233-254`、`web/app/views/report.js:275-280`
- 邮件失败后服务端仍 `commit()` share，却返回不含 URL 的 502；前端尝试读取永远不存在的 `err.data.url`。
- 重试会继续生成新的有效 bearer token。
- 修复方向：选择单一事务语义：失败时撤销 share，或返回明确的部分成功响应和 URL。

### 10. 剪贴板失败仍提示已复制并关闭弹窗

- 位置：`web/app/views/report.js:262-274`、`web/app/components/modal.js:98-104`
- `navigator.clipboard.writeText()` 的异常被吞掉，界面仍显示 `Client link created and copied`，随后关闭含 URL 的弹窗。
- 修复方向：按复制结果展示状态；失败时保留可选中的 URL。

### 11. 顶部资产数量累计所有历史包

- 位置：`web/app/views/report.js:49-55`、`:95-123`
- “Pack snapshot / Asset readiness” 对所有历史 delivery 的 `asset_summary` 求和，重复版本会持续放大数字。
- 修复方向：快照只显示最新正式包；若展示历史累计，必须明确说明统计口径。

### 12. Backlog 文案隐藏真实阻塞原因

- 位置：`web/app/views/report.js:155-171`
- 只要 `implementation_backlog` 非空，前端就统一显示 `0 outlines remain implementation backlog`，丢弃事实审核、采样不足和资产待复核等真实原因。
- 修复方向：直接展示后端原因，并分别汇总 template、review、measurement 和 fact approval。

## 容易引起歧义或误导的表述

1. `customer_ready`：`api/adapters/delivery_assets.py:74-90` 只要求抓取页数至少为 1，并不证明采样充分、事实已审批或实施资产可发布。建议改为 `diagnostic_documents_ready` 等可验证的窄状态。
2. `diagnostic final pack` / `client-ready diagnostic pack`：包内仍可能有 templates、`needs_review` 资产和未完成测量，普通用户会理解为整个 ZIP 已最终验收。
3. `Build New Delivery Pack`：当前行为会覆盖最近历史目录，既不一定是“new”，也不一定使用当天日期。
4. `Delivery Pack Archives`：名称暗示不可变存档，但当前下载和重建会改写内容。
5. `View / PDF`：实际只打开 HTML，没有 PDF 文件或 PDF 导出动作。
6. `Client link created and copied`：链接创建与剪贴板复制是两个独立结果，当前文案在复制失败时仍宣称成功。
7. 样本数量：旧报告同时出现 `Only 12 valid samples`、`Successful samples: 18`、`Prompt Explorer: 16 of 34` 等数字，却没有解释“原始回执、成功样本、当前市场 cohort、逐问题证据”之间的口径差异。

## 版本边界

- 当前生成器已写入 07/08 目录，不能把“新包仍不生成证据目录”列为当前缺陷。
- 已检查旧包的 `source_revision` 为 `af57aa61b8bb`。当前 HEAD 后续包含市场 cohort、统一证据流、overview 补采和品牌验证探针修复。
- 当前仍存在的缺陷是旧包校验过宽、读请求原地重建，以及上述口径和状态问题。

## 验证

执行：

```text
pytest -q api/tests/test_delivery_adapter.py api/tests/test_delivery_assets.py api/tests/test_delivery_share.py api/tests/test_product_optimizations.py api/tests/test_worker.py api/tests/test_projects.py
```

结果：`109 passed, 1 warning`。

绿灯不能证明快照语义正确：`api/tests/test_projects.py:523-558` 明确把“下载旧包时重建”写成预期行为，测试实际固化了缺陷。本轮未新增测试，也未修改产品实现。

## 建议修复顺序

1. 停止 GET、下载和公开分享重建历史目录；默认构建创建新的不可变版本。
2. 对齐当前合同校验并过滤失败样本，先恢复交付内容可信度。
3. 让交付失败进入持久化 Job 状态，修复嵌套计量和预算预留。
4. 收紧列表、分享和 SMTP/剪贴板错误状态。
5. 最后统一 readiness、final、archive、PDF 和样本口径文案。
