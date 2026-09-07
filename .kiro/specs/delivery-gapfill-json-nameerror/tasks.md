# Implementation Plan

## Overview

修复 `api/worker/worker_pipeline.py` 交付补采路径的 `NameError`（模块使用 `json.dumps` 但未导入 `json`），补齐该路径的回归覆盖，加装防复发守卫，并清理 4 处死变量。

红/绿次序是硬结构：任务 1、2 先在**未修复**代码上建立反例与基线（任务 1 必须 FAIL，任务 2 必须 PASS），任务 3.1 才落修复，3.2/3.3 重跑同一批测试验证转绿且无回归。

全部改动落在 `api/`，不触碰 `engine/`。

## Tasks

- [ ] 1. 写补采分支探索测试（修复前，必须失败）

  - **Property 1: Bug Condition** - 补采分支 `json` 未导入导致 NameError
  - **CRITICAL**: 该测试必须在未修复代码上 FAIL，失败本身是缺陷存在的证据
  - **DO NOT** 在此任务中修改 `worker_pipeline.py`，也不得为了让测试变绿而改测试断言
  - **NOTE**: 该测试同时编码了期望行为，任务 3.2 复用它验证修复
  - **GOAL**: 取得 `NameError: name 'json' is not defined` 反例，落在 `api/worker/worker_pipeline.py:88`

  新建文件 `api/tests/test_worker_pipeline.py`（`api/tests/` 现有 53 个文件中无 worker pipeline 测试，`test_worker.py` / `test_worker_funding.py` 覆盖的是别的面）。

  被测入口固定为 `worker_pipeline._prepare_delivery_measurement`，**不得**改为经 `tasks._prepare_delivery_measurement` 调用：两者是同一函数对象，但只有前者指向缺陷现场所在模块，经 `tasks` 调用无法区分修复是否生效。

  夹具（沿用 `api/tests/test_adapters.py:167` 等既有风格）：
  - `monkeypatch.setattr(engine_adapter, "WORK_ROOT", tmp_path / "work")`
  - `with_tenant_context(tenant_id, project_slug)` 进入租户上下文
  - `geolib.write_json` 造 `geo.json`（含 `platforms`、`market`），使 `project_dir/geo.json` 存在
  - `job_id` 传非空正整数（`job_log_path` 对 `job_id <= 0` 抛 `ValueError`）

  **stub 两层落点（照此表执行，落错层会 AttributeError）**：

  | 落点 | 协作者 | 原因 |
  |---|---|---|
  | `monkeypatch.setattr(tasks, ...)` | `_append_job_event`、`_require_sampling_output`、`_engine_custom_providers`、`_funded_engine_context`、`_tenant_record` | 经 `_task_facade()` 解析，该函数返回 `api.worker.tasks` 模块对象；打在 `worker_pipeline` 上不生效 |
  | `monkeypatch.setattr(worker_pipeline, ...)` | `geolib`、`measurement`、`global_scope`、`job_log_path`、`_reserve_delivery_gap_sampling` | 从 `worker_pipeline.__dict__` 直接解析 |
  | `monkeypatch.setitem(sys.modules, "sample", ...)` | `sample` | 函数体内 `import sample` |

  `measurement` 用逐属性 patch（`delivery_question_evidence`、`record_sampling`），**不要**整模块替换为 `SimpleNamespace`：`repeat` 取自 `measurement.MIN_QUESTION_SAMPLES`（实值 3），整模块替换会让断言里的 `"repeat": 3` 失去意义。

  `_append_job_event` **必须用真实现**（`tasks._append_job_event` → `job_runtime.append_job_event`，纯文件追加，不碰 DB），不得用 spy 替代：`json.dumps` 在调用发生前于 caller frame 求值，stub 掉日志写入会掩盖缺陷，造成假覆盖。

  驱动补采分支：
  - `delivery_question_evidence` 首次返回 `{"active_cohorts": [...], "needs_sampling": True, "target_platforms": [2 个], "target_question_ids": [2 个], "cohort_changed": True}`
  - 第二次返回 `{"active_cohorts": [...], "ready": True, "measured_platforms": [2 个]}`，避开 `delivery_evidence_incomplete`
  - `_reserve_delivery_gap_sampling` stub 为返回预留估算，`sample.run` stub 为返回成功结果，`_require_sampling_output` stub 为直通

  断言 `job_log_path(...)` 指向的文件含两行，并解析 `[citeaura] <event> ` 之后的 JSON 段校验字段：

  ```
  [citeaura] delivery evidence gap-fill {"cohort_changed": true, "platform_count": 2, "question_count": 2, "repeat": 3}
  [citeaura] delivery evidence gap-fill complete {"measured_platform_count": 2, "ready": true}
  ```

  - 在未修复代码上运行：`python3 -m pytest api/tests/test_worker_pipeline.py -v`
  - **EXPECTED OUTCOME**: FAIL，`NameError: name 'json' is not defined`
  - 记录反例：崩溃点 `worker_pipeline.py:88`（`delivery evidence gap-fill` 事件）；`worker_pipeline.py:134`（complete 事件）须先越过 88 行才可达，故本轮不可观测
  - 测试写完、跑过、失败已记录即可勾选本任务
  - _Requirements: 1.1, 1.3, 1.4, 2.4_

- [ ] 2. 写保持性属性测试（修复前，必须通过）

  - **Property 2: Preservation** - 非补采路径与错误路径行为不变
  - **IMPORTANT**: 遵循 observation-first：先在**未修复**代码上跑出实际输出，再把观测结果写成断言
  - 全部落在同一新文件 `api/tests/test_worker_pipeline.py`，共 6 条，复用任务 1 的夹具与上面那张 stub 落点表

  逐条覆盖（括号内为 `isBugCondition` 为假的原因）：

  1. `3.1` 无 active funded cohort（`active_cohorts` 为空）→ 返回该 state 本身，作为诊断型交付有效，不要求 API 资金，不进入补采
  2. `3.2` 项目目录缺 `geo.json` → 返回 `None`，走引擎独立渲染路径；断言 `delivery_question_evidence` 未被调用
  3. `3.3` `needs_sampling` 为假 → 跳过补采，直接校验 `ready` 并返回证据状态；断言 `sample.run` 未被调用、日志文件未创建
  4. `3.4` `job_id` 为 `None` → 补采流程照常完成，但不写 job 日志；断言 `_append_job_event` 零调用（此条即缺陷此前逃逸的两个原因之一）
  5. `3.5` 补采后 `ready` 仍为假、`evidence.gaps` 有缺口 → 抛 `RuntimeError`；实测文案为 `delivery_evidence_incomplete:2 question(s), 3 provider/mode sample(s) missing`，用 `pytest.raises(RuntimeError, match="delivery_evidence_incomplete")` 断言前缀与缺口数量
  6. `3.6` 预算超限 → 把 `worker_pipeline._reserve_delivery_gap_sampling` stub 为抛 `RuntimeError("delivery_sampling_budget_exceeded:<code>")`，断言异常向外传播且 `sample.run` **零调用**（保住"预算校验先于付费采样"的次序保证）

  注：第 5 条与 `api/tests/test_delivery_adapter.py:1133` 已有的 `delivery_evidence_incomplete` 断言不重复——那条走 delivery adapter 的 `GeoEngineError`，这条走 worker pipeline 的 `RuntimeError`。

  - 在未修复代码上运行：`python3 -m pytest api/tests/test_worker_pipeline.py -v`
  - **EXPECTED OUTCOME**: 6 条保持性测试全 PASS（确立待保持的基线），任务 1 那条仍 FAIL
  - 测试写完、跑过、在未修复代码上通过即可勾选本任务
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

- [ ] 3. 修复补采分支 `json` 未导入

  - [ ] 3.1 为 `worker_pipeline.py` 补上模块级 `import json`

    - 编辑 `api/worker/worker_pipeline.py`，在 line 3 的 `from types import SimpleNamespace` **之前**插入 `import json`（`import X` 先于 `from X import`）
    - 与同目录 `worker_funding.py`、`worker_job_lifecycle.py`、`tasks.py` 一致：三者均在 line 3 放 `import json`
    - 不加注释解释来历
    - 插入后原 88 / 134 两处 `json.dumps` 整体下移一行，这是唯一的位移影响，不改任何逻辑行
    - 不动 `__all__`（line 200 的 `tuple(name for name in globals() ...)`）：修复后它仅新增 `'json'`；`tasks.py` 已有自己的 `import json`，星号导入重绑定指向同一 stdlib 模块对象，零名字冲突
    - 本 spec 明确**不**收紧 `__all__`（`worker_pipeline` / `worker_funding` / `tasks` 三处的 `globals()` 推导导出），收紧与本缺陷因果链无关且会让"修复是否生效"失焦，记为后续独立任务
    - _Bug_Condition: isBugCondition(交付任务) = geo.json 存在 AND active_cohorts 非空 AND needs_sampling 为真 AND job_id is not None_
    - _Expected_Behavior: 补采分支不抛 NameError，且在 job_log_path 写出 `delivery evidence gap-fill`（含 platform_count / question_count / repeat / cohort_changed）与 `delivery evidence gap-fill complete`（含 ready / measured_platform_count）两条事件_
    - _Preservation: design.md Correctness Properties 的 Property 2 全部条款_
    - _Requirements: 2.1, 2.2, 2.3_

  - [ ] 3.2 验证探索测试转为通过

    - **Property 1: Expected Behavior** - 补采分支两条 gap-fill 日志事件正常写出
    - **IMPORTANT**: 重跑任务 1 写的**同一个**测试，不得新写测试
    - 该测试已编码期望行为，它通过即证明期望行为被满足
    - `python3 -m pytest api/tests/test_worker_pipeline.py -v`
    - **EXPECTED OUTCOME**: PASS；日志文件两行如实写出，两处 `json.dumps` 真实执行
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [ ] 3.3 验证保持性测试仍全部通过

    - **Property 2: Preservation** - 非补采路径与错误路径行为不变
    - **IMPORTANT**: 重跑任务 2 写的**同一批**测试，不得新写测试
    - 额外断言星号导入未被破坏：`import api.worker.tasks` 成功，`tasks._prepare_delivery_measurement is worker_pipeline._prepare_delivery_measurement` 为真
    - **EXPECTED OUTCOME**: 6 条全 PASS，无回归
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7_

- [ ] 4. 加防复发守卫测试

  新建独立文件 `api/tests/test_import_hygiene.py`。**不要**并入 `api/tests/test_baseline.py`——后者是引擎日志转译 baseline，名字相近易误判归属。

  检测机制（环境无 `ruff`，实测 `No module named ruff`，故不得依赖 ruff；全部逻辑基于 `symtable` + `sys.stdlib_module_names` 自证）：
  - 扫描 `api/**/*.py`，跳过 `api/tests/` 与 `__pycache__`
  - 用 `symtable.symtable(src, path, "exec")` 递归遍历作用域树，只取 `get_type() == "function"` 的作用域（跳过 module 与 class 作用域）
  - 只收真正退化为模块全局查找的名字：`is_global()` 且 `not is_declared_global()` 且 `not is_local()` 且 `not is_parameter()` 且 `not is_free()`
  - 与模块级绑定比对：`ast` 取模块级 `Import` / `ImportFrom` 的 `asname or name.split(".")[0]`，加模块级 `Assign` 的 `Name` 目标，加模块级 `FunctionDef` / `AsyncFunctionDef` / `ClassDef` 名
  - stdlib 清单用 `sys.stdlib_module_names`（Python 3.12），**不硬编码**——硬编码会漏掉 `html`，而 `delivery_generated_assets.py` L525/532/533/548 的 `html.escape` 正是靠上游回填的真违规

  不以运行时 `vars(module)` 为主判据：它只能确认名字"当前可解析"，无法区分"自己导入"与"被上游星号导入回填"，而后者正是本缺陷逃逸的机制。

  早期 AST 粗扫的 44 处含大量假阳性（函数局部变量遮蔽 stdlib 同名模块，如 `settings/router.py:111` 的 `code`、`billing/router.py` 的循环变量 `code`、`auth/router.py` 的 `email`），**不作为 baseline**。symtable 作用域分析后真实违规 17 处 / 7 模块，减去本次修复对象即冻结 baseline 16 处 / 6 模块：

  ```
  api/adapters/delivery_documents.py        -> csv, io, re
  api/adapters/delivery_generated_assets.py -> html, json, re, shutil
  api/adapters/delivery_package.py          -> re
  api/projects/delivery_routes.py           -> datetime, re, tempfile, zipfile
  api/projects/lifecycle_routes.py          -> datetime, json
  api/projects/sampling_routes.py           -> datetime, re
  ```

  白名单粒度为 模块+名字 级（16 条维护成本可接受）。写两个测试函数：

  - `test_no_new_star_import_backfill_reliance` — baseline 之外的新增违规使测试失败（只禁扩张）
  - `test_backfill_baseline_shrinks_only` — 白名单条目若已修复仍留在名单中则报错要求删除（保证单调递减）

  守卫自身的三条验收场景，逐条实跑确认：
  - A 撤掉任务 3.1 的 `import json` → 守卫必须 FAIL，因为 `worker_pipeline -> json` 不在白名单内（这是守卫有效性的判定标准，验完记得把 `import json` 加回去）
  - B 保留修复 → 守卫 PASS，实测 16 处 / 6 模块
  - C 把某个已修好的名字留在白名单 → `test_backfill_baseline_shrinks_only` FAIL

  本 spec 不为这 16 处消费方补齐显式导入，它们运行时可正常解析，记为后续独立任务。

  - _Requirements: 1.5, 2.5, 3.8_

- [ ] 5. 清理 4 处死变量（严格锚定坐标）

  逐个整行删除，四处右值皆为纯读取（`config.get` / `page.get` / 集合推导 / `int(...)`），无副作用，删除行为中性：

  | 文件 | 函数 | 变量 | 行 | 删除范围 |
  |---|---|---|---|---|
  | `api/adapters/product_insights.py` | `_prompt_explorer()` | `samples` | 133 | 单行 |
  | `api/adapters/publishing.py` | `overview()` | `market` | 171 | 单行 |
  | `api/adapters/site_signals.py` | `_repair_static_page()` | `current_text` | 163 | 单行 |
  | `api/adapters/delivery_generated_assets.py` | `_copy_other_assets()` | `content_ids` | 754 | 754 起的整个集合推导块（含闭合括号） |

  **禁止 F841 全量清扫。** 以下三处是活变量，误删会破坏功能：

  - `product_insights.py::_cell()::samples`（L91，读于 L93/96/97 的 `wilson_interval` 与 `rate`）— 与待删的 L133 完全同名，只按名字搜必踩
  - `publishing.py::overview()::current`（L179，读于 L185 与 L198）— 在推导式/嵌套表达式里被读，会骗过 naive 扫描
  - `site_signals.py::_repair_static_page()::current_words`（L164，读于 L165 的早退判断与 L168 的 `word_count` 比较）— 与待删的 `current_text`（L163）紧邻且同前缀，连带误删风险最高

  删除后逐个跑对应既有测试确认返回值与副作用不变：

  ```bash
  python3 -m pytest api/tests/test_product_optimizations.py api/tests/test_publishing.py api/tests/test_site_signals.py api/tests/test_generated_assets.py api/tests/test_delivery_assets.py -v
  ```

  清理不伴随任何邻近行为调整，不加注释。

  - _Requirements: 1.6, 2.6, 3.12_

- [ ] 6. Checkpoint - 全套测试通过

  ```bash
  # 引擎测试（硬约束，必须全绿）
  cd engine && python3 -m unittest discover -s tests
  # 期望：Ran 248 tests ... OK (skipped=2)

  # API 测试
  python3 -m pytest api/tests -v
  # 期望：全部通过；基数实测 454，本 spec 新增 9 条（1 探索 + 6 保持性 + 2 守卫），期望 463

  # 单独复跑本次新增
  python3 -m pytest api/tests/test_worker_pipeline.py api/tests/test_import_hygiene.py -v
  ```

  - 确认全部改动落在 `api/`，`git diff --name-only` 不含 `engine/` 任何路径
  - 确认未向 `engine/` 引入租户、计费、认证等 SaaS 专属逻辑
  - 清理验证过程中产生的临时文件
  - 有疑问先问用户，不要自行放宽断言
  - _Requirements: 3.9, 3.10, 3.11_

## Notes

- **环境无 `ruff`**（实测 `No module named ruff`），守卫不得依赖 ruff，全部逻辑基于 `symtable` + `sys.stdlib_module_names` 自证。
- **stub 两层落点**是实施阶段最大的坑：经 `_task_facade()` 解析的协作者必须打在 `tasks` 模块上，从 `worker_pipeline.__dict__` 直接解析的必须打在 `worker_pipeline` 上，`sample` 只能走 `sys.modules`。完整表格见任务 1。
- **禁止 F841 全量清扫**：`_cell()::samples`（L91）、`overview()::current`（L179）、`_repair_static_page()::current_words`（L164）三处是活变量，与待删目标同名或紧邻，误删会破坏功能。
- **任务 4 场景 A 验完须把 `import json` 加回去**，否则任务 6 的 checkpoint 会大面积失败且原因难查。
- **本 spec 明确排除**：`__all__` 收紧（与本缺陷因果链无关）、为 16 处消费方补齐显式导入、`api/settings/crypto.py` 的 `decrypt_key` AAD 回退（涉及历史密文迁移决策）。三者均记为后续独立任务。
- 验证基线：引擎 248 通过（含 2 skip）、API 454 通过；本 spec 新增 9 条，API 总数期望 463。
