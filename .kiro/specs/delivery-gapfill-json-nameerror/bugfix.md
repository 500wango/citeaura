# Bugfix Requirements Document

## Introduction

交付任务的「证据补采」路径存在一个顶层 `NameError`。`api/worker/worker_pipeline.py` 在写入 gap-fill job 日志时调用 `json.dumps(...)`，但该模块自身命名空间没有 `json`。该代码在提交 `2acf9af`（split delivery project and worker domains）从 `api/worker/tasks.py` 拆出时，`import json` 被留在了原模块。

`tasks.py` 通过 `from api.worker.worker_pipeline import *` 复制了函数引用，但 Python 函数解析全局名只查其**定义所在模块**的 `__dict__`，因此星号导入无法回填该名字，从任何入口调用都会失败。

业务影响不是日志瑕疵：崩溃发生在采样预算预留与 `sample.run(...)` 付费采样**执行完成之后**。租户已真实消耗 API 额度与平台代付成本，最终却只拿到一个失败的交付任务，且不产出交付包。

该路径在 `api/tests/` 中零覆盖，这也是引擎 248 测试与 API 454 测试全绿却让缺陷发车的原因。同类脆弱性还有系统性面：另有 16 处（分布于 6 个模块）使用了自身未导入的标准库名字，目前因作为星号导入的**消费方**而被上游模块回填，尚可正常解析；`worker_pipeline` 是唯一的**提供方**，故单独暴露。该数字由 `symtable` 作用域链分析得出，早期 AST 粗扫的 44 处含大量假阳性（函数局部变量遮蔽 stdlib 同名模块），不作为 baseline。ruff 当前 1058 条 `F405` 噪声使这类问题事前不可见。

本 spec 范围：主缺陷修复、该路径回归覆盖、防复发守卫、4 处 F841 死变量清理。全部改动落在 `api/`，不触碰 `engine/`。

已知项、另行处理（不并入本 spec）：`api/settings/crypto.py` 的 `decrypt_key` 在 `InvalidTag` 时回退 `aad=None`，削弱租户/引擎绑定，涉及历史密文迁移决策。为 16 处消费方补齐显式导入亦作为后续独立任务。

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN 交付任务进入证据补采分支（`needs_sampling` 为真且 `job_id` 非空）THEN the system 在写入 `delivery evidence gap-fill` 日志事件时抛出 `NameError: name 'json' is not defined`，交付任务以失败终止

1.2 WHEN 该 `NameError` 抛出 THEN the system 已完成采样预算预留并已执行付费采样，租户额度与平台代付成本被真实消耗，但不产出任何交付包

1.3 WHEN 补采完成后需写入 `delivery evidence gap-fill complete` 日志事件 THEN the system 以同样方式抛出 `NameError`（实际执行中因先在 1.1 处崩溃而不可达）

1.4 WHEN 运行 API 测试套件 THEN the system 不执行该补采分支的任何一行，顶层 `NameError` 不被任何测试捕获

1.5 WHEN 某模块作为星号导出提供方使用了自身命名空间中不存在的标准库名字 THEN the system 无静态或测试守卫拦截，缺陷仅在运行时暴露

1.6 WHEN 执行到 `api/adapters/publishing.py` 的 `market`、`api/adapters/site_signals.py` 的 `current_text`、`api/adapters/delivery_generated_assets.py` 的 `content_ids`、`api/adapters/product_insights.py` 的 `samples` 赋值处 THEN the system 计算并绑定了此后从不被读取的局部变量

### Expected Behavior (Correct)

2.1 WHEN 交付任务进入证据补采分支（`needs_sampling` 为真且 `job_id` 非空）THEN the system SHALL 成功序列化并写入 `delivery evidence gap-fill` 日志事件，不抛出 `NameError`，并继续执行补采流程

2.2 WHEN 补采成功且证据补齐 THEN the system SHALL 完成交付包产出，使已消耗的采样预算转化为交付物

2.3 WHEN 补采完成后需写入 `delivery evidence gap-fill complete` 日志事件 THEN the system SHALL 成功序列化并写入该事件，包含 `ready` 与 `measured_platform_count` 字段

2.4 WHEN 运行 API 测试套件 THEN the system SHALL 包含覆盖「`needs_sampling` 为真且携带 `job_id`」补采分支的回归测试，该测试 SHALL 真实执行两处 `json.dumps` 调用并断言两条 job 日志事件均已写出

2.5 WHEN 某模块使用了自身命名空间中不存在的标准库名字 THEN the system SHALL 由守卫测试失败拦截；该守卫 SHALL 以经 `symtable` 作用域分析确认的当前 16 处消费方（6 个模块，模块+名字级粒度）为冻结 baseline 白名单，白名单只允许收缩不允许扩张，baseline 之外的新增违规 SHALL 使测试失败

2.6 WHEN 1.6 所列四处死变量被移除 THEN the system SHALL 保持所在函数的返回值与副作用完全不变

### Unchanged Behavior (Regression Prevention)

3.1 WHEN 交付项目无 active funded cohort THEN the system SHALL CONTINUE TO 作为诊断型交付返回有效结果，不要求 API 资金

3.2 WHEN 项目目录缺少 `geo.json` THEN the system SHALL CONTINUE TO 返回 `None` 并走引擎独立渲染路径

3.3 WHEN `needs_sampling` 为假 THEN the system SHALL CONTINUE TO 跳过补采、直接校验 `ready` 并返回证据状态

3.4 WHEN `job_id` 为空 THEN the system SHALL CONTINUE TO 跳过 job 日志写入并完成补采流程

3.5 WHEN 补采后证据仍不完整 THEN the system SHALL CONTINUE TO 抛出 `delivery_evidence_incomplete` 并附缺口数量

3.6 WHEN 采样预算超限 THEN the system SHALL CONTINUE TO 抛出 `delivery_sampling_budget_exceeded`

3.7 WHEN `tasks.py` 星号导入 `worker_pipeline` THEN the system SHALL CONTINUE TO 正常解析全部导出名字；`json` 经 `__all__` 重复绑定到同一模块对象，等价且不遮蔽任何名字

3.8 WHEN 其余 16 处消费型星号导入依赖被加载 THEN the system SHALL CONTINUE TO 正常解析其使用的标准库名字，本 spec 不强制为其补齐显式导入

3.9 WHEN 运行 `cd engine && python3 -m unittest discover -s tests` THEN the system SHALL CONTINUE TO 248 测试通过（含 2 skip）

3.10 WHEN 运行 `python3 -m pytest api/tests -v` THEN the system SHALL CONTINUE TO 全部通过，且总数不低于 454

3.11 WHEN 本次修复完成 THEN the system SHALL CONTINUE TO 保持 `engine/` 不含租户、计费、认证等 SaaS 专属逻辑，全部改动落在 `api/`

3.12 WHEN 死变量所在函数被调用 THEN the system SHALL CONTINUE TO 执行原有周边逻辑，清理不伴随任何邻近行为调整
