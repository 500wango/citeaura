# CiteAura 多语言架构诊断与改进方案（v2）

> v2 修正：根据人工复核修正了交付路径、数据模型、默认值和校验策略的错误。

## 问题本质

产品现在是一个语言拼盘：

```
中文用户 → 中文 UI → 中文提问 → 英文报告 → 英文交付包 → 中文目标站
日本用户 → 日文 UI → ??? → 英文报告 → 英文交付包 → 日文目标站
```

根因是 **产品只有一个 `market` 概念，混用了三件不同的事**：

| 概念 | 控制什么 | 当前字段 |
|------|---------|---------|
| **目标市场**（哪些 AI 引擎需要优化） | 采样平台分组 | `project.market` = cn / global / both |
| **受众提问语言**（测量哪个语言市场的可见性） | 采样问题语言 | ❌ 锁死在 market 上 |
| **报告展示语言**（用户/客户看什么语言） | 报告、工单、交付包 | ❌ 不存在 |

---

## 5 个语言层的现状

### Layer 1: UI Locale（前端界面语言）

| 项目 | 现状 |
|------|------|
| 支持语言 | 7 种：zh, en, ja, ko, es, fr, de |
| 检测机制 | URL `lang` → `localStorage.ulang` → `navigator.languages` → 默认 `en` |
| 消息目录 | `api/i18n/messages/{locale}.json`（7 文件，完整覆盖） |
| 公共落地页 | `api/i18n/messages/public/zh.json`（⚠️ 只有中文） |

**问题**：
- `localizeRenderedText()` 用反向查表做文本替换（`web/app/i18n.js` L167），极其脆弱
- 公共落地页 i18n 只有中文目录

### Layer 2: 提示词语言（LLM 输入）

| 项目 | 现状 |
|------|------|
| 问题生成 | `engine/scripts/bootstrap.py` L159：`market=cn` → 中文，`market=global` → 英文 |
| 系统提示 | 全英文硬编码，依赖 LLM 理解 market 指令 |

**问题**：
- 采样语言锁死在 market 上——日本用户做 global 优化只能用英文问题
- 无法测量"日语用户如何向 ChatGPT 询问该品牌"

### Layer 3: AI 回答语言（LLM 输出）

采样回答跟随问题语言，本身没有问题。

### Layer 4: 报告 & 交付包语言（核心痛点 🔴）

SaaS 正式交付走的是适配层，不是引擎 legacy 路径：

| 交付路径 | 文件 |
|---------|------|
| **SaaS 正式交付** | `api/adapters/delivery_package.py`、`delivery_common.py`、`delivery_documents.py`、`delivery_generated_assets.py` |
| **Standalone legacy** | `engine/scripts/deliver.py`（独立引擎用） |

两条路径都硬编码英文。SaaS 交付包中的文档标题、表头、状态标签、市场标签全部英文。

语言门禁 `api/adapters/delivery_language.py` 当前用 Han 字符正则检测非英文内容——这个规则对中文交付不适用、对日文会误判合法汉字、对法/德/西语无法仅靠字符集判断。

### Layer 5: 目标站语言

爬虫/审计层自动检测页面语言，是纯事实度量，本身没问题。

---

## 解决方案

### 核心设计：`language_policy` 对象

不用单一 `content_locale` 字段，而是引入结构化的语言策略，为未来多语言采样留出扩展点：

```json
{
  "language_policy": {
    "report_locale": "ja",
    "sampling_locales": ["en"],
    "site_locales": ["ja"],
    "version": 1
  }
}
```

| 字段 | 控制什么 | 第一阶段实现 |
|------|---------|-------------|
| `report_locale` | 交付包、报告、工单的展示语言 | ✅ 完整实现 en/zh/ja |
| `sampling_locales` | 受众提问语言 | 从 `market` 推导，不改变当前行为 |
| `site_locales` | 官网实际语言 | 自动检测 + 人工确认 |
| UI locale | 前端界面语言 | 留在用户偏好/浏览器，不放项目配置 |

真实场景：

| 用户 | market | report_locale | sampling_locales | 含义 |
|------|--------|--------------|-----------------|------|
| 中国品牌出海 | both | zh | [zh, en] | 国内+海外采样，中文报告 |
| 日本企业 | global | ja | [en]（从 market 推导） | 英文市场采样，日文报告 |
| 外企中国团队 | cn | en | [zh]（从 market 推导） | 国内采样，英文报告 |
| 未来：日本站日语采样 | global | ja | [ja]（手动指定） | 日语采样，日文报告 |

### 分层改动

#### Phase 1: 交付包本地化（解决核心痛点）

**1.1 数据模型**

```python
# api/models.py — Project 表新增
report_locale = Column(String(8), nullable=True)
# NULL = 按迁移推导（旧项目 → en）；显式保存后以项目配置为准
```

默认值规则（单一来源，无矛盾）：
- 旧项目缺失值 → 按当前行为推导为 `en`
- 新项目 → 从创建时用户的 UI locale 继承
- 显式保存后 → 以项目配置为准
- 引擎读取 → `cfg.get("report_locale") or "en"`（统一 fallback）

**1.2 交付文案目录**

在 `api/adapters/` 下新建（SaaS 专属，不放 engine/）：

```
api/adapters/delivery_i18n/
  en.json     # 英文（从当前硬编码提取）
  zh.json     # 中文
  ja.json     # 日文
```

**1.3 改造目标文件（SaaS 交付路径）**

| 文件 | 改动 |
|------|------|
| `api/adapters/delivery_common.py` | 加载 `report_locale` 对应的消息目录 |
| `api/adapters/delivery_documents.py` | 文档标题、表头、状态标签从消息目录读取 |
| `api/adapters/delivery_package.py` | 概览页、交付物清单本地化 |
| `api/adapters/delivery_generated_assets.py` | 资产描述本地化 |
| `api/adapters/delivery_language.py` | 校验策略改为三类检查（见下文） |

Standalone legacy 路径 `engine/scripts/deliver.py` **不做 SaaS locale 改动**，保持当前英文行为。

**1.4 `report_locale` 写入 geo.json 的时机**

不在 `with_tenant_context` 中写入。语言策略属于项目配置同步，应在明确的配置保存入口写入：

- 项目创建时 → `geo.json` 写入 `report_locale`
- 项目设置保存时 → 同步更新 `geo.json`
- 引擎运行时 → 只读 `cfg.get("report_locale")`，不写入

**1.5 语言校验改造**

当前 `delivery_language.py` 的 Han 字符检测不能简单改成"按 locale 检查"。改为三类校验：

| 类别 | 检查内容 | 缺失时行为 |
|------|---------|-----------|
| 模板翻译完整性 | 消息目录中 `report_locale` 的所有 key 是否有翻译 | **阻止该语言交付** |
| fallback 泄漏 | 最终文本中是否混入了英文 fallback 占位符 | **阻止并报错** |
| 原文白名单 | 品牌名、URL、引用、用户输入字段 | 允许保留原文 |

交付包元数据应包含：
```json
{
  "locale": "ja",
  "translation_status": "complete"
}
```

**不做静默 fallback**——找不到 locale 文件时报错，不降级为英文，避免半日文半英文的"四不像"包。

#### Phase 2: 采样语言解耦（预留扩展点）

第一阶段 `sampling_locales` 继续从 `market` 推导，不改变采样行为：

```python
# 推导逻辑
def default_sampling_locales(market):
    return {"cn": ["zh"], "global": ["en"], "both": ["zh", "en"]}[market]
```

数据模型预留 `sampling_locales` 字段，未来支持：
- 日本用户手动指定 `sampling_locales: ["ja"]` → 用日语问题采样 global 平台
- 多语言站指定 `sampling_locales: ["zh", "en", "ja"]` → 三语采样

#### Phase 3: UI i18n 加固

- `localizeRenderedText` 反向文本替换 → 逐步迁移为显式 `t("key")` 调用
- 公共落地页 i18n 目录补全（目前只有 `public/zh.json`）

---

## 不需要改动的层

| 层 | 原因 |
|---|------|
| 采样问题语言 | 第一阶段继续由 market 推导，第二阶段通过 sampling_locales 解耦 |
| AI 回答语言 | 跟随问题语言 |
| 爬虫/审计语言检测 | 纯事实度量 |

---

## 实施优先级

| 阶段 | 内容 | 工作量 | 影响 |
|------|------|--------|------|
| **P0** | 新增 `report_locale` 字段 + migration | 小 | 基础设施 |
| **P0** | 提取 `api/adapters/delivery_*.py` 硬编码为 en.json + zh.json | 中 | **直接解决中文用户核心痛点** |
| **P0** | 改造 `delivery_language.py` 为三类校验 | 中 | 保证翻译完整性 |
| **P1** | 补 ja.json 交付文案 | 小 | 解决日本用户痛点 |
| **P1** | 项目创建/设置写入 `report_locale` 到 geo.json | 小 | 打通数据流 |
| **P1** | 项目设置 UI 增加报告语言选择器 | 小 | 用户可控 |
| **P2** | 预留 `sampling_locales` 字段 | 小 | 为多语言采样留扩展点 |
| **P2** | 公共落地页 i18n 补全 | 小 | 非中文用户官网体验 |
| **P3** | `localizeRenderedText` → 显式 `t()` 迁移 | 大 | 长期维护质量 |
| **P3** | 实现 `sampling_locales` 手动指定 | 大 | 日文/法文等语言采样 |

---

## 引擎接口约束

按照 AGENTS.md 要求：
- **引擎内部**：只读 `cfg.get("report_locale")`，不引入 SaaS 逻辑
- **SaaS 层**：在项目创建/保存时同步到 `geo.json`，不在 `with_tenant_context` 中写入
- **引擎测试**：不受影响，缺失 `report_locale` 时默认 `en`（保持当前行为）
- **standalone legacy**：`engine/scripts/deliver.py` 保持现状，不做 SaaS locale 改动

---

## v1 → v2 修正记录

| 原方案错误 | 修正 |
|-----------|------|
| 交付改造指向 `engine/scripts/deliver.py` | 实际 SaaS 交付走 `api/adapters/delivery_*.py`，legacy 路径不做 SaaS 改动 |
| 单一 `content_locale` 字段 | 改为 `language_policy` 结构，包含 `report_locale`、`sampling_locales`、`site_locales` |
| `with_tenant_context` 写 geo.json | 改为在项目创建/保存入口明确写入，运行时只读 |
| DB 默认 zh、引擎默认 en 矛盾 | 统一规则：旧项目 NULL → 推导 en；新项目 → 继承用户 locale；显式保存后以配置为准 |
| 找不到 locale 文件时 fallback 到 en.json | 交付包不做静默 fallback，缺翻译则阻止交付 |
| `_contains_disallowed_english` 简单改名 | 改为三类校验：模板完整性 + fallback 泄漏 + 原文白名单 |
