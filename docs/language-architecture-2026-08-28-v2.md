# CiteAura 多语言改造计划 v2

> 日期：2026-08-28  
> 状态：实施设计  
> 范围：项目语言策略、AI 采样语言、报告与交付包语言、用户界面语言  
> 原则：不修改 `engine/` 的既有公共接口；不提供不可控的“AI 回答语言”设置。

## 1. 决策摘要

当前问题不是缺少几个翻译文件，而是把不同语言概念混在了 `market` 和 UI locale 中。

采用以下模型：

```text
用户 UI 语言        = user.locale
报告/交付语言        = effective_report_locale
采样/提示词语言      = derived_sampling_locales
目标站语言           = observed/configured site_locales
AI 实际回答语言      = 运行时检测结果，不可配置
```

用户不设置“AI 回答语言”。系统只根据采样语言生成问题，并把该语言作为回答检测基准。

## 2. 目标与非目标

### 目标

- 中文用户分析英文网站时，可以使用中文界面并收到中文报告。
- 日本客户可以收到日文报告，而不改变既有全球市场采样口径。
- 报告、工单、验收包中的模板文案和分析内容不再出现无说明的中英混排。
- 交付语言修改只影响未来生成的交付包，不改写历史快照，不自动触发 LLM 调用。
- 租户可以设置默认报告语言，项目可以覆盖该默认值。
- 为未来的日文、法文等受众采样保留扩展空间。

### 非目标

- 不承诺控制模型实际回答语言。
- 不把浏览器语言作为项目交付语言的唯一来源。
- 不在第一阶段重做所有历史样本或历史交付包。
- 不将 SaaS 租户、计费或认证逻辑引入 `engine/`。
- 不把 `market` 立即替换成 locale；保留 `cn/global/both` 作为平台和报告聚合兼容维度。

## 3. 语言概念和权威来源

### 3.1 用户界面语言

`user.locale` 是用户个人偏好，只控制 SPA、管理页和公共页面的界面文案。

优先级：

```text
用户显式选择 > 已保存 user.locale > 浏览器 Accept-Language > en
```

UI locale 不自动覆盖项目的报告语言。

### 3.2 报告和交付语言

增加租户默认值和项目级可选覆盖：

```text
effective_report_locale =
    project.report_locale
    or tenant.default_report_locale
    or "en"
```

`NULL` 表示项目继承租户默认值，不要把继承结果直接写回项目列。

支持 locale 继续复用 `api/i18n/locales.py`：

```text
en, zh, ja, ko, es, fr, de
```

第一阶段正式交付只承诺 `en`、`zh`；第二阶段加入 `ja`；其余语言必须逐个完成 catalog 和快照测试后再开放。

### 3.3 采样/提示词语言

第一阶段由现有 `market` 推导，不向普通用户暴露独立的提示词设置：

```text
market=cn      -> sampling_locales=["zh"]
market=global  -> sampling_locales=["en"]
market=both    -> sampling_locales=["zh", "en"]
```

设置页只读显示推导结果，名称使用“当前采样语言”或“评估受众语言”。

未来如需日语受众采样，增加：

```json
"sampling_locales": ["ja"]
```

但每种语言必须作为独立 cohort 统计，不能与其他语言混成一个 mention rate。

### 3.4 目标站语言

`site_locales` 描述官网实际内容语言，不等于用户语言，也不等于采样语言。

来源优先级：

```text
抓取检测结果 > 用户确认/修正 > 旧 market 推导
```

支持多选，并同时保存配置值与观测值，报告中区分“配置语言”和“实际检测语言”。

### 3.5 AI 实际回答语言

这是采样结果字段，不是项目设置：

```json
{
  "prompt_locale": "en",
  "answer_locale": "zh",
  "language_status": "unexpected"
}
```

`language_status`：

```text
matched | mixed | unexpected | undetermined
```

不匹配的原始回答保留，不自动翻译后再计入正常样本。

## 4. 数据合同

### 4.1 Tenant

新增可空字段：

```python
default_report_locale = Column(String(8), nullable=True)
```

可选 CheckConstraint 必须与 `SUPPORTED_LOCALES` 同步；如果数据库约束难以跨版本维护，则由 API schema 和运行时校验负责，CI 验证枚举一致性。

### 4.2 Project

新增可空字段：

```python
report_locale = Column(String(8), nullable=True)
```

`NULL` 表示继承租户默认值。不要使用数据库默认 `zh`，避免意外改变历史英文项目。

### 4.3 geo.json

项目文件系统配置增加可选块：

```json
{
  "language_policy": {
    "site_locales": ["en"],
    "sampling_locales": ["en"],
    "policy_version": 1
  }
}
```

`report_locale` 的权威值来自 DB，交付任务开始时解析 effective value；只有明确的项目配置保存入口才同步文件，不能由 `with_tenant_context()` 隐式写 `geo.json`。

### 4.4 Question

保留既有 `market` 字段，增加可选 `locale`：

```json
{
  "id": "q101",
  "market": "global",
  "locale": "en",
  "text": "Which ...?"
}
```

旧问题兼容推导：

```text
market=cn      -> zh
market=global  -> en
market=both    -> 项目 sampling_locales 的对应 cohort
```

引擎公共函数继续接受旧结构，locale 只作为可选元数据。

### 4.5 Sample row

JSONL 样本增加：

```json
{
  "prompt_locale": "en",
  "answer_locale": "en",
  "language_status": "matched"
}
```

这三个字段必须随 `run_id` 保存，不能在报告阶段重新猜测。

## 5. 当前代码边界

### SaaS 正式交付

必须优先改造：

- `api/adapters/delivery_package.py`
- `api/adapters/delivery_common.py`
- `api/adapters/delivery_documents.py`
- `api/adapters/delivery_generated_assets.py`
- `api/adapters/delivery_language.py`
- `api/adapters/localization.py`

`engine/scripts/deliver.py` 是 standalone/legacy 交付入口，不承载 SaaS 租户语言逻辑。若要增强它，只能作为独立兼容工作，不应被当作 SaaS 交付修复的主路径。

### 采样和问题生成

重点模块：

- `engine/scripts/bootstrap.py`
- `engine/scripts/sample.py`
- `api/adapters/global_scope.py`
- `api/adapters/measurement.py`

### 用户界面和 API

重点模块：

- `api/models.py`
- `api/projects/schemas.py`
- 项目配置/设置路由
- `web/app/views/project-settings.js`
- `web/app/api.js`
- `api/i18n/messages/*.json`

## 6. 文本来源分类

交付包内容必须先按来源分类，不能统一套翻译：

| 类型 | 典型来源 | 处理方式 |
|---|---|---|
| Chrome | 文档标题、表头、状态、固定说明 | locale catalog，缺 key 阻止正式交付 |
| Generated Content | LLM 生成的 why/action/acceptance、分析段落 | 在生成调用中传入 report locale，或明确重新生成 |
| Deterministic Content | 引擎固定分析和模板段落 | 按 locale 使用结构化模板 |
| Evidence Content | 品牌名、URL、引用、官网原文、用户输入 | 保留原文，记录 source locale，不强行翻译 |

### 重要约束

测量型 LLM 调用和交付型 LLM 调用必须分开：

```text
测量型调用：sampling_locale
交付内容调用：report_locale
```

不能为了生成日文报告而改变已经完成的英文采样问题，否则会破坏历史指标的可比性。

## 7. 分阶段实施

### Phase 0：盘点和契约冻结

1. 枚举 SaaS 交付所有文件和字段，标注 Chrome、Generated、Deterministic、Evidence 来源。
2. 确认所有正式下载路径都经过 `api/adapters/delivery_package.py`。
3. 列出当前英文硬编码、现有 `localize_ticket()` 字段和所有交付测试快照。
4. 冻结 `report_locale`、`site_locales`、`sampling_locales` 的命名和默认规则。
5. 明确旧项目 effective locale 为 `en`，不做批量数据重写。

验收：形成字段清单；每个交付字段都有 owner 和语言处理方式。

### Phase 1：中文/英文交付闭环

1. 增加 `Tenant.default_report_locale` 和 `Project.report_locale` migration。
2. 增加项目语言策略解析器，集中实现继承和旧数据 fallback。
3. 将 SaaS 交付模板从 `api/adapters/*` 中提取到 delivery catalog。
4. 先完成 `en`、`zh` 两套 catalog，包含 01–06 文档、README、HTML、CSV、状态和验收文案。
5. 交付构建入口接收 effective report locale。
6. 重新设计语言门禁：不再全局使用“出现 Han 就判英文违规”。
7. 交付包 manifest 写入 `report_locale`、`translation_status` 和 `source_run_id`。

阶段限制必须在 UI 和文档明确：

```text
Phase 1 只保证模板和固定分析文案本地化；历史 LLM 内容可能仍需重新生成。
```

### Phase 2：Generated Content 语言闭环

1. 审计 `tasks.json`、策略文档、报告摘要中每个生成字段的真实来源。
2. 对交付型 LLM 调用增加 `report_locale` 语言约束和结构化输出合同。
3. 生成结果保存 `content_locale`、`generation_method`、`translation_status`。
4. 对确定性分析改为 locale 模板，不使用 LLM 翻译可以确定生成的状态和数字。
5. 对无法可靠翻译的证据字段保留原文并显示来源语言。
6. 报告页显示 Content 是否完整本地化，禁止用中文表头掩盖英文正文。

### Phase 3：租户默认、项目覆盖和设置体验

1. 租户设置增加默认报告语言。
2. 项目设置增加“报告/交付语言”覆盖项。
3. 新项目继承租户默认值；项目级 `NULL` 保持继承。
4. 语言修改后显示：

```text
语言设置将在下次生成交付包时生效；不会自动重跑采样或调用模型。
```

5. 若下次生成发现缺少目标语言 Content，明确提示可能需要 LLM 调用和费用确认。
6. 设置页只读显示当前采样语言及其来源：`market-derived`。

### Phase 4：日文交付

1. 完成日文 Chrome catalog。
2. 完成日文确定性分析模板。
3. 完成日文交付快照和 HTML `lang=ja`。
4. 改造语言门禁，允许日文合法使用汉字。
5. 验证日文品牌事实、引用、URL 和用户输入的原文保留规则。
6. 只有当 Generated Content 能满足完整性门槛后，才把 `ja` 标记为正式可用。

### Phase 5：多语言采样扩展

1. 将 `sampling_locales` 从 market 推导结果升级为可选 cohort 配置。
2. 问题生成器按 locale 生成问题，并保留 market 作为平台统计维度。
3. provider 路由增加语言能力声明；不支持的组合在 UI 中解释为 unavailable。
4. 每种语言独立计算 mention rate、rank、citation 和样本量。
5. 报告同时展示采样语言与交付语言，避免把中文报告误解为中文采样。

## 8. 交付包生命周期

### 修改报告语言

修改 `report_locale` 时：

- 不修改已有交付目录；
- 不修改已有 `source_run_id`；
- 不自动重跑采样；
- 不自动调用 LLM；
- 下次点击生成交付包时才使用新语言。

### 重新生成策略

生成时按以下顺序处理：

1. 读取已有分析和事实快照；
2. 尝试使用目标语言的确定性模板/已缓存 Content；
3. 若缺少交付语言 Content，返回可解释的 `translation_required`；
4. 用户明确确认后，才执行交付型 LLM 生成；
5. 成功后生成新的交付目录和新的 manifest。

不允许把“重新渲染模板”和“重新采样 AI”合并成一个隐式动作。

## 9. API 设计

### 项目配置响应

```json
{
  "language_policy": {
    "report_locale": "zh",
    "report_locale_source": "tenant_default",
    "site_locales": ["en"],
    "observed_site_locales": ["en"],
    "sampling_locales": ["en"],
    "sampling_locale_source": "market_derived"
  }
}
```

### PATCH 行为

- 只允许 editor/owner 修改项目报告语言和目标站语言确认值；
- viewer 只读；
- 非法 locale 返回 `422`；
- `report_locale: null` 表示恢复租户继承；
- 保存成功不创建 Job，不消耗模型配额。

### 交付响应

```json
{
  "report_locale": "ja",
  "translation_status": "complete",
  "content_status": "complete",
  "source_run_id": "run-...",
  "requires_llm_generation": false
}
```

## 10. 前端体验

项目设置只展示三个项目级语言概念：

```text
目标站语言：英文
当前采样语言：英文（由目标市场自动推导）
报告与交付语言：中文
```

不展示“AI 回答语言”。在采样结果或报告中显示：

```text
回答语言匹配：18 / 20
混合语言：1
语言异常：1
```

UI locale 仍在个人账户/全局偏好中设置，不写入项目语言策略。

## 11. 翻译目录维护

每个 delivery locale 文件必须满足：

- key 集合与 `en.json` 完全一致；
- 占位符集合一致；
- 无空翻译；
- 不允许把英文原文静默复制到非英文 locale；
- 文档模板快照通过；
- HTML/Markdown 结构检查通过。

CI 需要新增：

```text
check_delivery_catalog_keys
check_delivery_catalog_placeholders
check_delivery_locale_snapshots
```

正式交付缺 key 时阻止生成；内部预览可以显示，但必须标记 `translation_status=incomplete`。

## 12. 测试矩阵

### 配置和迁移

- 旧项目没有 locale 时仍生成英文包；
- 租户默认能被新项目继承；
- 项目覆盖和恢复继承正确；
- UI locale 不改变项目 report locale；
- 非法 locale 返回 422。

### 采样

- `market=cn` 继续选择中文问题；
- `market=global` 继续选择英文问题；
- `market=both` 分开中文/英文 cohort；
- 每条样本写入 prompt/answer locale；
- 模型返回混合语言时标记 `mixed`；
- 语言异常不改变原始回答内容。

### 交付

- 中文、英文、日文三套模板快照；
- Chrome 与 Content 分别验证；
- 品牌名、URL、引用、用户输入保留原文；
- 日文汉字不被误判为英文门禁违规；
- 缺翻译 key 阻止正式交付；
- 语言修改不重跑采样；
- 历史交付包保持不可变；
- 交付 manifest 记录语言和源 run。

### 端到端场景

```text
中文 UI + 英文网站 + 英文采样 + 中文交付
日文 UI + 日文网站 + 英文采样 + 日文交付
英文 UI + 中文网站 + 中文采样 + 英文交付
中文 UI + 英文/日文网站 + 中文/英文独立采样 + 中文交付
```

## 13. 风险与控制

| 风险 | 控制 |
|---|---|
| 模型不遵守回答语言 | 只检测实际语言，不作强制承诺 |
| 中文报告内混入英文 Content | 记录 Content 状态，缺失时阻止正式交付或要求确认 |
| 日文汉字被误判 | locale-aware 校验和字段白名单 |
| 翻译 catalog 漂移 | CI key/placeholder/快照门禁 |
| 改语言导致历史报告变化 | 历史包不可变，新语言生成新目录 |
| 语言修改意外消耗 Key | 设置保存不创建 Job，LLM 生成需显式确认 |
| 引擎接口被 SaaS 语言逻辑污染 | locale 由 SaaS 配置传入，引擎只读取可选配置 |
| 多语言采样指标混算 | 每个 sampling locale 独立 cohort 和指标 |

## 14. 完成标准

本次改造只有满足以下条件才算完成：

1. 中文项目可以生成正文、工单和验收内容均为中文的交付包；
2. 日文项目可以生成正文、工单和验收内容均为日文的交付包；
3. 英文采样和中文/日文交付可以同时存在，且报告明确显示两者语言不同；
4. AI 实际回答语言被记录，不被伪装成可控设置；
5. 旧项目、旧样本、旧交付包不被重写；
6. 所有新语言通过 catalog、内容完整性、交付快照和端到端测试；
7. 正式 SaaS 交付路径和 standalone legacy 路径没有互相污染。

## 15. 推荐首批实现顺序

```text
1. 修正实际 SaaS 交付入口和字段清单
2. report_locale：租户默认 + 项目覆盖
3. en/zh Chrome 与确定性 Content 交付
4. 语言修改生命周期和历史包不可变
5. 采样语言只读展示与 answer language 检测
6. ja 交付完整闭环
7. sampling_locales 多 cohort 扩展
8. 其他语言和公共落地页补全
```

最小可交付结果应是：

```text
中文 UI + 英文网站 + 英文采样 + 中文完整交付包
```

而不是只把英文表头翻译成中文。
