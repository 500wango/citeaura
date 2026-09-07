# Bugfix Design Document

## Overview

`api/worker/worker_pipeline.py` 的 `_prepare_delivery_measurement` 在写入 gap-fill job 日志时调用 `json.dumps(...)`，但该模块命名空间内没有 `json`。该缺陷在提交 `2acf9af`（split delivery project and worker domains）把代码从 `api/worker/tasks.py` 拆出时引入，`import json` 被留在了原模块。

本设计涵盖四件事：主缺陷修复（一行 stdlib 导入）、该路径的回归覆盖、防止同类缺陷复发的守卫、以及 4 处死变量清理。全部改动落在 `api/`，不触碰 `engine/`。

## Glossary

| 术语 | 含义 |
|---|---|
| 补采路径 / gap-fill | 交付任务发现证据不足时，自动补齐采样样本的分支，即 `needs_sampling` 为真的代码路径 |
| 星号导入回填 | 模块 A 执行 `from B import *` 后，B 的模块级名字进入 A 的命名空间，使 A 中未显式导入的 stdlib 名字得以解析 |
| 提供方 / 消费方 | 提供方是被星号导入的模块（如 `worker_pipeline`）；消费方是执行星号导入的模块（如 `tasks`） |
| facade | `_task_facade()` 返回 `api.worker.tasks` 模块对象，`worker_pipeline` 借它反向访问协作者 |
| 冻结 baseline | 当前已存在、运行时仍可解析的星号导入回填依赖清单，守卫允许其存在但不允许新增 |

## Bug Details

### 触发条件

```
isBugCondition(交付任务):
    project_dir/geo.json 存在
    AND state.active_cohorts 非空
    AND state.needs_sampling 为真
    AND job_id is not None
    => worker_pipeline.py:88 求值 json.dumps(...) 时抛 NameError
```

`job_id is None` 时跳过日志写入，缺陷不显现；`needs_sampling` 为假时不进入该分支。二者共同解释了为什么缺陷能通过全部现有测试。

### 崩溃点

- `worker_pipeline.py:88` — `delivery evidence gap-fill` 事件（首个触发点）
- `worker_pipeline.py:134` — `delivery evidence gap-fill complete` 事件（须先越过 88 行才可达）

### 业务影响

崩溃发生在 `_reserve_delivery_gap_sampling` 预留采样预算、且 `sample.run(...)` 已执行付费采样**之后**。租户真实消耗 API 额度与平台代付成本，最终只得到失败的交付任务且无交付包产出。这不是日志瑕疵。

### 为什么星号导入救不了它

实测：

```
tasks._prepare_delivery_measurement is worker_pipeline 的同一函数对象 : True
func.__globals__ is worker_pipeline.__dict__                        : True
'json' in func.__globals__                                          : False
'json' in vars(tasks)                                               : True
```

Python 函数解析全局名只查其**定义所在模块**的 `__dict__`。`tasks.py:153` 的 `from api.worker.worker_pipeline import *` 复制的是同一函数对象，`tasks.py:3` 自己的 `import json` 无法回填。

`json` 当前**不在** `worker_pipeline.__all__` 中——`__all__` 在 line 200 由 `globals()` 推导，`json` 从未被导入故从未进入。

## Expected Behavior

对应 bugfix.md 的 2.1–2.6：补采分支成功序列化并写出两条日志事件、交付包正常产出、回归测试真实执行两处 `json.dumps`、守卫拦截新增违规、4 处死变量移除后行为不变。

## Hypothesized Root Cause

模块拆分时移动了函数体但未同步移动其依赖的 stdlib 导入。消费方 `tasks.py` 保留了 `import json` 这一事实掩盖了问题——静态阅读时 `json` 看似"在上下文里可用"，而实际绑定语义与之相反。

该模块是仓库内唯一"提供星号导出而非消费"的模块，因此是唯一暴露的模块。其余 6 个消费方模块存在同类未导入依赖，但被上游回填，运行时可解析。

## Correctness Properties

### Property 1: 缺陷被修复

**Validates: Requirements 2.1, 2.2, 2.3**

对任意满足 `isBugCondition` 的输入，`_prepare_delivery_measurement` 不得抛出 `NameError`，且必须在 `job_log_path(...)` 指向的文件写出两条事件：
- `delivery evidence gap-fill` + JSON，含 `platform_count` / `question_count` / `repeat` / `cohort_changed`
- `delivery evidence gap-fill complete` + JSON，含 `ready` / `measured_platform_count`

### Property 2: 既有行为不回归

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8**

以下路径行为逐条不变：无 active cohort 返回诊断态（3.1）、缺 `geo.json` 返回 `None`（3.2）、`needs_sampling` 为假时跳过补采（3.3）、`job_id` 为空时不写日志但完成流程（3.4）、证据仍不足时抛 `delivery_evidence_incomplete`（3.5）、预算超限抛 `delivery_sampling_budget_exceeded`（3.6）、`tasks.py` 星号导入解析全部导出名（3.7）、其余 16 处消费方依赖保持可解析（3.8）。

## Fix Implementation

### 1. 主缺陷

`api/worker/worker_pipeline.py` 新增模块级 `import json`，置于 line 3 `from types import SimpleNamespace` 之前（`import X` 先于 `from X import`）。同目录 `worker_funding.py`、`worker_job_lifecycle.py`、`tasks.py` 均在 line 3 放 `import json`，风格一致。

副作用已验证无害：`__all__` 由 `globals()` 推导，修复后仅新增 `['json']`；`tasks.py` 已有 `import json`，重绑定指向同一 stdlib 模块对象，星号导出零名字冲突。

### 2. `__all__` 不予收紧（本 spec 明确排除）

`worker_pipeline`、`worker_funding`、`tasks` 末尾都是 `__all__ = tuple(name for name in globals() if not name.startswith("__"))`，会无差别导出模块级 stdlib 名字。不在本 spec 收紧的理由：星号导出与本缺陷的因果链无关（缺陷源于函数 `__globals__` 绑定，与导出无关），收紧不改变修复效果，反而会让"修复是否生效"的判定失焦。记为后续独立任务。

### 3. 死变量清理（严格锚定 4 个坐标）

| 文件 | 函数 | 变量 | 行 |
|---|---|---|---|
| `api/adapters/product_insights.py` | `_prompt_explorer()` | `samples` | 133 |
| `api/adapters/publishing.py` | `overview()` | `market` | 171 |
| `api/adapters/site_signals.py` | `_repair_static_page()` | `current_text` | 163 |
| `api/adapters/delivery_generated_assets.py` | `_copy_other_assets()` | `content_ids` | 754 |

四处均为整行删除，右值皆为纯读取（`config.get` / `page.get` / 集合推导 / `int(...)`），无副作用，删除行为中性。

**禁止 F841 全量清扫。** 以下同名或紧邻变量是活变量，误删会破坏功能：

- `product_insights.py::_cell()::samples`（L91，读于 L93/96/97）— 与 L133 同名
- `publishing.py::overview()::current`（L179，读于嵌套推导式内 L187）— 会骗过 naive 扫描
- `site_signals.py::_repair_static_page()::current_words`（L164，读于 L165/168/169）— 与待删的 `current_text` 紧邻且同前缀，连带误删风险最高

### 4. 防复发守卫

新建独立测试文件（不并入 `test_baseline.py`，后者是引擎日志转译 baseline，名字相近易误判）。

检测机制以 `symtable` 作用域链为主：只取真正退化为模块全局查找的名字（`is_global()` 且非 `is_declared_global()`、排除 `is_free()` / `is_local()` / `is_parameter()`、跳过 module 与 class 作用域），再与模块级导入/赋值绑定比对。stdlib 清单用 `sys.stdlib_module_names`（Python 3.12），不硬编码。

不以运行时 `vars(module)` 为主判据：它只能确认名字"当前可解析"，无法区分"自己导入"与"被上游回填"，而后者正是本缺陷逃逸的原因。

早期 AST 粗扫得出的 44 处含大量假阳性（函数局部变量遮蔽 stdlib 同名模块，如 `settings/router.py:111` 的 `code`、`billing/router.py` 的循环变量 `code`、`auth/router.py` 的 `email`）。symtable 作用域分析后真实违规为 17 处 / 7 模块，减去本次修复对象即冻结 baseline **16 处 / 6 模块**：

```
api/adapters/delivery_documents.py        -> csv, io, re
api/adapters/delivery_generated_assets.py -> html, json, re, shutil
api/adapters/delivery_package.py          -> re
api/projects/delivery_routes.py           -> datetime, re, tempfile, zipfile
api/projects/lifecycle_routes.py          -> datetime, json
api/projects/sampling_routes.py           -> datetime, re
```

`html` 是真违规（`delivery_generated_assets.py` L525/532/533/548 调用 `html.escape`，靠上游回填），也是硬编码 stdlib 清单会漏掉的一条。

白名单粒度为 模块+名字 级（16 条维护成本可接受）。拆两个测试：

- `test_no_new_star_import_backfill_reliance` — baseline 之外的新增违规使测试失败（不许扩张）
- `test_backfill_baseline_shrinks_only` — 白名单条目若已修复仍留在名单中则报错要求删除（只许收缩，保证单调递减）

守卫验收标准：撤掉 `import json` 后守卫必须失败，因为 `worker_pipeline.json` 不在白名单内。

## Testing Strategy

### 回归测试（对应 2.4）

新建 worker pipeline 测试文件（`api/tests/` 现有 53 项中无 worker/pipeline 相关文件）。入口选 `worker_pipeline._prepare_delivery_measurement` 而非经 `tasks` 调用：前者是函数定义所在模块，即缺陷现场；经 `tasks` 调用的是同一函数对象，无法区分修复是否生效。

夹具沿用既有风格：`monkeypatch.setattr(engine_adapter, "WORK_ROOT", tmp_path / "work")` + `with_tenant_context` + `geolib.write_json/write_jsonl` 造 `geo.json` / `samples` / `metrics`。

**stub 必须分两层落点**，这是实施阶段最大的坑：

| 落点 | 协作者 | 原因 |
|---|---|---|
| 打在 `tasks` 上 | `_append_job_event`、`_require_sampling_output`、`_engine_custom_providers`、`_funded_engine_context`、`_tenant_record` | 经 `_task_facade()` 解析；打在 `worker_pipeline` 上会 `AttributeError` |
| 打在 `worker_pipeline` 上 | `geolib`、`measurement`、`global_scope`、`job_log_path`、`_reserve_delivery_gap_sampling` | 从其 `__dict__` 直接解析 |
| `monkeypatch.setitem(sys.modules, ...)` | `sample` | 函数体内 `import sample` |

`_append_job_event` 必须用**真实现**写入 tmp 日志文件并断言文件内容，不得用 spy 替代：`json.dumps` 在调用前于 caller frame 求值，stub 掉日志写入会掩盖缺陷，造成假覆盖。

驱动分支：首次 `delivery_question_evidence` 返回 `needs_sampling=True`（2 个 funded provider 但样本不足，或 `cohort_changed`），第二次返回 `ready=True` 以避开 `delivery_evidence_incomplete`；`job_id` 传非空值。

断言日志文件含两行，并解析 JSON 段校验字段。实测修复后实际内容：

```
[citeaura] delivery evidence gap-fill {"cohort_changed": true, "platform_count": 2, "question_count": 2, "repeat": 3}
[citeaura] delivery evidence gap-fill complete {"measured_platform_count": 2, "ready": true}
```

保持性测试覆盖 3.1 / 3.2 / 3.3 / 3.4 / 3.5，其中 3.5 实测报错文案为 `delivery_evidence_incomplete:2 question(s), 3 provider/mode sample(s) missing`。

### 红/绿验证

夹具已原型验证：
- **未修复**：探索测试 FAIL（`NameError: name 'json' is not defined`），5 条保持性测试 PASS
- **已修复**：6 条全 PASS，两条事件如实写出

### 守卫测试

三条验收场景已原型验证：A 未修复 → FAIL；B 已修复 → PASS；C 白名单条目已修好仍留名单 → FAIL。

## 验证命令

```bash
# 引擎测试（硬约束，必须全绿）
cd engine && python3 -m unittest discover -s tests
# 期望：Ran 248 tests ... OK (skipped=2)

# API 测试
python3 -m pytest api/tests -v
# 期望：全部通过，总数由 454 上升（新增预计 +8～9 条）

# 单独跑新增回归与守卫
python3 -m pytest api/tests/<新增worker测试文件> -v
python3 -m pytest api/tests/<新增守卫测试文件> -v
```

环境无 `ruff`（`No module named ruff`），故守卫不得依赖 ruff，全部逻辑基于 `symtable` + `sys.stdlib_module_names` 自证。

## 修复前后对照

| 维度 | 修复前 | 修复后 |
|---|---|---|
| 补采分支（`needs_sampling` 真 + `job_id` 非空） | `worker_pipeline.py:88` 抛 `NameError`，交付失败 | 两条日志事件正常写出，交付包产出 |
| 已消耗的采样预算 | 预算与付费采样已消耗，无交付物 | 转化为交付物 |
| `'json' in worker_pipeline.__dict__` | `False` | `True` |
| `worker_pipeline.__all__` | 不含 `json` | 新增 `json`（仅此一个，零冲突） |
| 该路径测试覆盖 | `_prepare_delivery_measurement` / `gap-fill` 零匹配 | 6 条测试（1 探索 + 5 保持性） |
| 同类缺陷可检测性 | 无守卫，仅运行时暴露；ruff 1058 条 F405 噪声掩盖 | 守卫拦截新增违规，baseline 单调递减 |
| 死变量 | 4 处 | 0 处（3 处活变量陷阱明确保留） |
