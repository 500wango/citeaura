# CiteAura 全库中文字符审查报告

- 审查目标：确保代码中除注释外没有任何中文字符（汉字/CJK 表意字符）。
- 审查范围：仓库全部文本文件（`api/`、`web/`、`engine/`、`scripts/`、`docs/`、根目录配置与文档）。
- 审查方式：全文件逐一读取扫描（本环境 shell 不可用，无法运行 `grep`/`pytest`/`unittest`，全部为只读文件工具手工核对）。
- 规则定义：
  - **注释（允许保留中文）**：Python `#` 注释、三引号 docstring；JS `//`、`/* */`、JSDoc `*`；HTML `<!-- -->`；CSS `/* */`；ini/env 的 `#`、`;` 行。
  - **代码（违规）**：字符串字面量、f-string、正则、标识符、HTML 可见文本/属性等。
  - **数据文件**：i18n 翻译 JSON 按用户决定「视为代码 → 清除」（已执行）。
  - **只读区域**：`engine/`（AGENTS.md 硬约束 #1，禁止修改）——仅报告不处理。

## 1. 结论摘要

| 区域 | 代码中文（违规） | 注释中文（允许） | 处理 |
|---|---|---|---|
| `engine/`（只读） | 约 2000+（scripts）+ 约 138（tests）+ 约 1350（README/SKILL/references 数据文档） | 约 300 | 仅报告 |
| `api/`（.py） | 约 195（含适配层 162 + 路由/任务 32 + locales 1） | 约 240 | 仅报告 |
| `api/tests/` | 约 61 | 4 | 仅报告 |
| `web/` | 29（telemetry-modal.js）+ 3（badge.js 转义 unicode，无字面汉字） | 0 | 仅报告 |
| `scripts/` | 2 | 5 | 仅报告 |
| `api/i18n/messages/*.json` | 23（en）+ 475（zh）+ 约 410（ja，日文汉字） | 0 | **已清除** |
| 文档 `.md` / `.env` 注释 | 非代码 / 注释 | — | 仅报告 |

按用户决定：**除 i18n 数据文件已清除外，所有代码一律不改，只出报告**；AGENTS.md #7 采样模式中文标签保持现状不动。

---

## 2. 已执行变更（i18n 数据文件，按用户决定「视为代码 → 清除」）

| 文件 | 原内容 | 现内容 |
|---|---|---|
| `api/i18n/messages/zh.json` | 475 行中文翻译 | `{}` |
| `api/i18n/messages/ja.json` | 约 410 行日文（含日文汉字） | `{}` |
| `api/i18n/messages/en.json` | 删除 23 条中文 key → 英文映射（原第 446–468 行） | 保留全部英文条目 |

**影响与后续（重要）**：
1. `zh`/`ja` 界面语言回退到英文（`api/i18n/catalog.py resolve()` 的 locale → en → id 回退逻辑仍可工作，`SUPPORTED_LOCALES` 未动）。
2. `api/tests/test_i18n.py`（断言 `resolve("nav.cta", "zh") == "免费试用"` 等）与 `api/tests/test_landing.py`（断言 `zh` 落地页含「免费试用」）**将失败**——按「不改代码」未同步修改测试，需后续处理。
3. `api/adapters/localization.py` 的中文消息 id（`TASK_IDS`/`FIELD_IDS`）在 en.json 中已无映射，`localize_ticket()` 产出的 `title_en`/`package_en` 等将回退显示中文 id 本身。建议后续把 `TASK_IDS`/`FIELD_IDS` 迁移为英文 key（属代码改动，本次未做）。
4. 如需恢复：`git checkout -- api/i18n/messages/`。

---

## 3. `api/` 代码中文字符明细（仅报告）

按性质分为三类：

### 3.1 采样模式标签（AGENTS.md 硬约束 #7 规定，保持现状）
`API·参数化知识` / `API·联网检索` / `人工·产品端`

- `api/adapters/measurement.py:12-14`（常量定义）
- `api/adapters/framing.py:90-91`（`_sampling_mode()` 返回）
- `api/adapters/sampling_control.py:86`
- `api/billing/platform_pool.py:63`
- `api/settings/router.py:116,125`
- `api/projects/router.py:469,1079,1083`
- 测试镜像：`test_acceptance_script.py:15`、`test_framing.py:85-86`、`test_platform_pool.py:117`、`test_product_optimizations.py:22`、`test_projects.py:206,214`、`test_workflow_acceptance.py:38`、`test_workspace.py:192`
- `scripts/acceptance.py:26`、`scripts/workflow_acceptance.py:17`
- 前端 `web/app/components/badge.js:10,13,16` 用转义 unicode `\u53c2\u6570`(参数)/`\u8054\u7f51`(联网)/`\u4eba\u5de5`(人工) 匹配中文模式值，渲染英文标签。

### 3.2 引擎契约/解析字符串（功能必需，删除会失效，建议记为豁免）
引擎（`engine/`，只读）产出物为中文，SaaS 层必须用中文匹配：

- `api/adapters/framing.py:10-21`（`_ZH_RELATIONS`：被普遍认为是/通常被认为是/被描述为/被认为是/被视为/定位为/是一家/是一个/是一款/是一种/作为/是——匹配真实采样回答里的中文品牌陈述）、`:41-46`（`_GENERIC` 中文词）、`:54`（剥离 一家/一个/一款/一种）、`:74-75`（正则内联中文）
- `api/adapters/log_translator.py:6-37`（32 条中文引擎日志 → 英文 UI 的翻译模式）
- `api/adapters/delivery.py:12-17`（交付物清单名：诊断报告/执行方案/工单表/验收表/初稿风险清单/建设地图）、`:29-34`（中文交付文件名 `2-GEO优化方案.*`、`02-执行方案`）、`:40-44`（AI 初稿风险文案、`05-初稿风险清单.md`）、`:49-53`（`05-初稿风险清单.html` 表头「待核实项/高风险」）
- `api/adapters/localization.py:7-32`（`TASK_IDS`/`FIELD_IDS` 中文 id——引擎 tasks.json 的标题/包名/负责人字段值，作为消息 key）
- `api/adapters/ticket_workflow.py:149`（`result.get("verdict") == "未达标"`——匹配引擎 verify 输出）
- `web/app/components/telemetry-modal.js:52-80`（29 条客户端引擎日志翻译模式，与 log_translator.py 同源）

### 3.3 SaaS 自产、返回给 UI 的中文（产品文案级，建议后续译为英文）
- `api/adapters/measurement.py:102-160`（趋势/可比性文案：还没有采样数据/暂无趋势/仅一期数据/口径不可比/样本不足/值得关注/正常波动/统计变化不等于优化归因…）
- `api/adapters/preflight.py:54-101`（预检项与修复建议：DNS 可解析/为域名配置公网 A/AAAA/CNAME 记录…）
- `api/adapters/report_quality.py:34-77`（报告质量问题与行动项：尚未形成站点审计/重新运行抓取站点和页面体检/检查 WAF、限流、登录墙…）
- `api/adapters/workspace.py:50,207`（默认分组「推荐」「场景」）、`:370-387`（外部证据工单：推动 {hostname} 页面补充品牌信息…）、`60天`、`owner: 市场`
- `api/adapters/outreach.py:95-102`（外链联络邮件模板：您好/关于更新…上的…信息/谢谢）
- `api/auth/password_reset.py:33-37`（重置密码邮件：重置你的 CiteAura 密码/我们收到了你的密码重置请求…）
- `api/adapters/publishing.py:199`、`api/publishing/router.py:151`（发布渠道错误文案）
- `api/projects/router.py:304-307`（工单默认值：该行动优先级较高，建议本周完成/按工单执行/GEO顾问/完成后重新运行验收）、`:482`（BYOK 费用说明）
- `api/worker/tasks.py:28-44`（动作标签：抓取站点/页面体检/AI 答案采样/自动推导底座/出三份交付物/生成工单/拓词扩题/生成建设蓝图/生成资产/初稿风险检查/生成报告/自动验收/打包交付/导出人工采样表/全自动引导/跑完整周期）
- `api/i18n/locales.py:6`（`LOCALE_LABELS = {"en": "EN", "zh": "中", "ja": "日"}` 中的「中」）

### 3.4 测试 fixture 中文（镜像上述字符串，未改）
- `test_branding.py:155,176,190`（01-诊断报告/03-工单表/04-验收表/06-建设地图 文件名断言）
- `test_delivery_adapter.py:13,31,42`（同上 + 本期未生成 AI 初稿 + 06-建设地图）
- `test_framing.py:57,59,79`（中文采样回答 fixture：CiteAura 是一款专业的 AI 可见性分析平台…）
- `test_i18n.py:29,34-35,41-43,46`（免费试用/统一一句话定义…）
- `test_landing.py:52,67-69`（免费试用/保证上首页/保证提及/已通过 SOC 2）
- `test_product_optimizations.py:41,49,102,104,106-107,130,169,188`（值得关注/问题集版本/页面技术/开发/知识库/内容/未达标/中文问题/BYOK 费用…）
- `test_projects.py:148,181,236,241,246,395-396`（ChatGPT 网页版/内容矩阵/页面技术/预算测试一/预算测试二）
- `test_publishing.py:189,205`（文件不可用：/发布渠道请求失败…）
- `test_workspace.py:71,77-79,88,91,97,118,136,210,258,263,270-271`（推荐/页面技术/开发/30天/Example 价格？/1-GEO诊断报告.html/被说错/q001-成稿.md…）

---

## 4. `web/` 明细（仅报告）

- `web/app/components/telemetry-modal.js:52-80`：**唯一含字面汉字的文件**，29 行全部为 `CLIENT_LOG_TRANSLATIONS` 中文引擎日志匹配正则（引擎契约类，见 3.2）。
- `web/app/components/badge.js:10,13,16`：转义 unicode 中文（渲染为「参数/联网/人工」，配合采样模式值匹配；文件本身无字面汉字）。
- 其余 67 个文本文件 **0 汉字**，但存在历史清除残留：多处注释被删成空洞（如 `app/views/overview.js:2` ` *  (Overview)`、`index.html` 注释区、`assets/styles/*.css` 头部注释 `/* ----------  ---------- */` 等）。建议后续清理空洞（属注释，不影响规则）。

## 5. `scripts/` 明细（仅报告）

- `scripts/acceptance.py:26`、`scripts/workflow_acceptance.py:17`：采样模式中文标签（AGENTS.md #7，保持现状）。
- 注释/docstring 中文 5 行（允许）。

## 6. `engine/`（只读，仅报告；AGENTS.md 硬约束 #1 禁止修改）

引擎为中文产品，代码中文字符规模最大，全部为「代码」类命中：

| 文件 | 代码命中约 | 文件 | 代码命中约 |
|---|---|---|---|
| scripts/analytics.py | 18 | scripts/deliver.py | 176 |
| scripts/audit.py | 47 | scripts/deliverables.py | 138 |
| scripts/benchmark.py | 28 | scripts/expand.py | 34 |
| scripts/blueprint.py | 118 | scripts/generate.py | 130 |
| scripts/bootstrap.py | 88 | scripts/geo.py | 46 |
| scripts/crawl.py | 1 | scripts/geolib.py | 6 |
| scripts/dashboard.py | 24 | scripts/jobs.py | 24 |
| scripts/publish.py | 19 | scripts/report.py | 136 |
| scripts/sample.py | 30 | scripts/tasks.py | 129 |
| scripts/verify.py | 24 | scripts/ui.html | 约 700（引擎自带中文管理 UI，含 UI_D 中/日文案） |

- 内容性质：工单/交付物中文标题与文案、中文正则（`[一-鿿]`、stop 词）、AI prompt（中文）、帮助文案、`.jobs/*.json` 运行产物（约 105 个，含「页面体检」等中文 label）。
- 数据文档：`README.zh-CN.md`（约 230 行）、`README.ja.md`（约 200 行，日文汉字）、`SKILL.md`（约 250 行）、`references/*.md`（cn-platforms/cn-source-ranking/content-patterns/global-platforms/method/sources，合计约 670 行）。
- `engine/tests/`：约 138 行中文 fixture/断言。

> 引擎测试必须保持全绿（AGENTS.md 硬约束 #6）——本环境无法运行验证；本次未触碰 `engine/` 任何文件。

## 7. 注释中文（允许，仅供参考）

- `api/` 各模块 docstring 与 `#` 注释约 240 行（如 `catalog.py`「多语言消息目录：locale 平等，en 为缺失回退。」、`main.py` 8 行、`projects/router.py` 40 行、`worker/tasks.py` 21 行等）。
- `engine/` 注释/docstring 约 300 行；`scripts/` 5 行；`.env.example`/`.env.production.example` 各 2 行 `#` 注释。
- 这些是规则允许的「注释中文」，未做任何处理。

## 8. 文档与其他（非代码，未计）

- `PRD.md`、`tasks.md`、`AGENTS.md`、`docs/*.md`、`higeo-vs-disvorai-comparison.md`：产品文档，中文内容属文档而非代码；如需一并清除请另行指示。
- `work/`、`dump.rdb`、`.venv/`、`.git/`：运行产物/依赖，未计。
- `.env`（本地密钥文件，gitignore）：未读取。

## 9. 建议（本次未执行，仅列项）

1. 把 3.3 节「SaaS 自产中文文案」译为英文（涉及约 12 个适配层/路由/任务文件 + 对应测试断言），使 API 返回给英文 UI 的内容完全英文化。
2. 把 `localization.py` 的 `TASK_IDS`/`FIELD_IDS` 迁移为英文消息 id，并同步 en.json 与引擎侧约定（引擎只读，需在适配层做映射）。
3. 清理 `web/` 注释空洞与 `badge.js` 转义 unicode（改用英文关键词匹配）。
4. 决定 `engine/` 的中文是否允许（只读约束下无法在代码层消除；只能通过适配层翻译或接受）。
5. `test_i18n.py`/`test_landing.py` 等依赖中文目录的断言需在后续代码改动时同步更新。

## 10. 验证说明

- 本环境 shell 完全不可用（`bwrap: setting up uid map: Permission denied`），无法运行 `cd engine && python3 -m unittest discover -s tests`、`cd api && pytest tests/ -v` 或任何自动正则扫描；本报告基于全文件人工读取核对。
- 请在正常环境运行 `make test` 验证本次 i18n 清除对测试的影响（预期 `test_i18n.py`、`test_landing.py` 失败，见第 2 节）。
