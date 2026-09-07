# CiteAura 代码精简分析报告（修正版）

> **分析日期**：2026-08-27
> **修正日期**：2026-08-27（根据人工复核修正误判）

---

## 修正说明

原报告将 `scripts/acceptance.py` 和 `scripts/workflow_acceptance.py` 误判为"无任何引用的死代码"。
实际情况：

- **`scripts/acceptance.py`**：[production-runbook.md L26](file:///home/michael/project/citeaura/docs/production-runbook.md#L26) 明确要求部署后执行，属于运维/验收入口脚本，不通过 Python import 调用。**不是死代码。**
- **`scripts/workflow_acceptance.py`**：[test_workflow_acceptance.py L4](file:///home/michael/project/citeaura/api/tests/test_workflow_acceptance.py#L4) 直接 import 了 `AcceptanceError`、`_delivery_contract`、`run_workflow`；[production-runbook.md L127](file:///home/michael/project/citeaura/docs/production-runbook.md#L127) 引用了完整执行命令。删除会破坏测试和生产验收流程。**不是死代码。**

原报告将约 612 行标记为"零风险可删除"的结论 **不成立**。

> **方法论教训**：仅凭 `grep import` 判断脚本文件是否为死代码是不充分的。运维脚本、CLI 入口、测试 fixture 都可能以非 import 方式被引用（文档、shell 调用、测试导入）。

---

## 经修正的分类

### ❌ 不可删除

| 文件 | 原因 |
|------|------|
| `scripts/acceptance.py` | 生产 runbook 部署验收入口 |
| `scripts/workflow_acceptance.py` | 测试直接 import + 生产 runbook 引用 |

### ⚠️ 疑似未使用，候选清理（需逐项确认）

| 文件 | 行数 | 说明 |
|------|------|------|
| `web/app/components/skeleton.js` | 15 | 无 ES import 发现，但应确认无外部页面/旧入口手工引用 |
| `web/app/components/table.js` | 62 | 同上；且可能是为未来 view 重构预留 |
| `web/app/components/tabs.js` | 36 | 同上 |
| `api/worker/tasks.py` L96-103 死变量 | 10 | 已迁移到 `worker_pipeline.py`，删除前应跑 Worker 定向测试 |

### ⚠️ 需逐项证明后再清理

| 项目 | 说明 |
|------|------|
| `api.js` 中 12 个方法 | ES Module 的动态访问（`api[ns][method]`）、测试、未来入口都需排除后才能删 |

### ✅ 有价值的重构（非紧急，需谨慎）

| 项目 | 收益 | 风险 |
|------|------|------|
| `_error()` × 12 提取到 `api/errors.py` | 统一错误契约 | 低：签名差异需统一（`detail` 参数等） |
| `_tenant()` × 6 提取为依赖 | 减少重复 | **中**：各模块对不存在租户的错误码、权限语义不完全相同，强行统一可能改变 API 行为 |
| `_tenant_project()` × 3 复用 `project_for_user` | 减少重复 | **中**：需确认参数、权限语义、返回类型完全一致才安全 |

### 📋 可选维护项（独立优先级）

| 项目 | 说明 |
|------|------|
| Auth views 提取共享 layout | 减少 ~75 行模板重复 |
| Worker `_task_facade()` 循环依赖 | 提取 `worker_utils.py` 降低认知复杂度 |
| Dockerfile 单阶段简化 | 当前多阶段无实际收益 |
| Compose 默认值去重 | 消除与 `config.py` 的双重默认值 |

---

## 修正后的实际可安全精简量

| 类别 | 原报告估算 | 修正后估算 |
|------|-----------|-----------|
| 可直接删除的死代码 | ~612 行 | ~10 行（tasks.py 死变量，需测试确认） |
| 候选清理（需确认） | — | ~113 行（3 个前端组件）|
| 重构精简（需谨慎验证） | ~95 行 | 同上，但需逐个验证 API 行为不变 |
