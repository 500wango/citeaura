# Code Review — `2debf66` fix: complete profile channel contract

**审查范围**: `api/adapters/global_scope.py` + `api/tests/test_global_scope.py`
**审查重点**: 功能设计正确性、逻辑合理性（非风格）
**日期**: 2026-08-14

---

## 结论摘要

这个 commit 修的问题是**真实存在**的（修复前引擎渲染会 `KeyError: 'forms'`），但补的是「展示契约」，没补「度量契约」，且合并顺序反了。

| # | 问题 | 严重度 | 类型 |
|---|------|--------|------|
| 1 | 新画像渠道的 `covered` 结构性恒为 `False` | 高 | 逻辑缺陷 |
| 2 | 合并顺序 `{**defaults, **previous}` 让引擎旧值覆盖新默认值 | 高 | 逻辑缺陷 |
| 3 | `CHANNEL_FIELD_DEFAULTS` 的 `forms`/`domains` 是共享可变对象 | 中 | 隐患 |
| 4 | 新测试未走真实生产路径 | 中 | 测试覆盖 |

---

## 复现确认：修复动机成立

修复前 `_profile_channels` 只产出 6 个键，而引擎渲染函数直接下标取值：

```
pre-commit channel keys: ['covered', 'id', 'market', 'name', 'priority', 'strategy_profile']
engine deliver.py would raise KeyError: 'forms'
```

具体崩溃点：
- `engine/scripts/deliver.py:327` — `c['forms']`、`c['volume']`、`c['cadence']`、`c['owner']`
- `engine/scripts/deliverables.py:147` — `c['forms'][:2]`、`c['cadence']`

所以补齐字段是对的。**22 个策略渠道 id 与 `CHANNEL_FIELD_DEFAULTS` 完全对齐**，无遗漏、无冗余。

---

## 问题一：新渠道的 `covered` 结构性恒为 `False`（最严重）

**位置**: `api/adapters/global_scope.py:331`

```python
"covered": bool(previous.get("covered")),
```

`covered` 只从 `previous` 取值，而 `previous` 来自引擎写入的 `blueprint.json`。引擎 `engine/scripts/blueprint.py:222-227` 只为自己硬编码的 8 个全球 id 计算覆盖，17 个新画像 id 在引擎里根本不存在，取不到 `previous`，因此永远 `False`。

实测 manufacturer 画像（已有 G2 引用证据的情况下）：

```
P0 official_en       covered=False
P1 b2b_marketplaces  covered=False  domains=['alibaba.com', ...]
P1 certification     covered=False  domains=[]
coverage: channel_covered=0, channel_rate=0.0, p0p1_covered=0/6
```

**连锁后果**：
- `engine/scripts/analytics.py:84` — `channel_covered / channel_total` 是健康分的 channel 子项，恒为 0 会系统性压低分数。
- `api/adapters/delivery.py:808` 和 `engine/scripts/deliver.py:306` — 对每个客户输出「Channel coverage 0/8」。

**更根本的问题**: `domains` 字段现在是**装饰性的**——22 个渠道里 14 个是 `[]`，就算把覆盖检测接上也判不出来。字段填了、看起来完整，但不可用。

**建议**: 要么在 normalize 层读 metrics 的 `top_cited_domains`，复用引擎 `covered()` 的域名后缀匹配逻辑（`engine/scripts/blueprint.py:222-227`，后缀匹配用 `geolib.same_site` 的 netloc 归一），真正实现对有 `domains` 的渠道的覆盖检测；要么对无 `domains` 的渠道明确标注「人工确认」状态，而不是让它显示成 `Gap`。

---

## 问题二：合并顺序让引擎旧值压掉新默认值

**位置**: `api/adapters/global_scope.py:324-326`

```python
rows.append({
    **defaults,
    **previous,   # ← previous 优先级更高，问题在这里
    "id": channel_id,
    "name": name,
    "priority": priority,
    "market": "global",
    "covered": bool(previous.get("covered")),
    "strategy_profile": profile["id"],
})
```

对 `official_en`、`wikipedia`、`review`、`youtube`、`linkedin` 这 5 个与引擎重叠的 id，引擎硬编码值会覆盖新写的画像默认值。publisher 画像实测：

```
-- official_en | Primary Publication and Content Archive
   why: Global AI citations are dominated by English (82.90%–95.07%)...
   forms: ['Native English product/pricing/comparison pages', 'English FAQ', 'llms.en.txt']
```

渠道名说「主要出版物与内容归档」，资产形态却说「产品/定价/对比页」——同一行表格里自相矛盾。新写的 publisher 版 `official_en` 默认值被丢弃了。

而 `name`、`priority`、`market` 放在 `**previous` 之后，是画像值胜出的——所以当前行为是「名字按画像走、描述按引擎走」，这不像是**有意**的设计。

**关键事实**: `**previous` 通常是为了保住用户编辑，但经全面搜索确认（HTTP 路由 / 后端代码 / 前端 `web/` 目录），**没有任何蓝图渠道字段的用户写入路径**。`api/projects/router.py:432` 的 `channels` 是引用域名统计（另一个概念），全仓只有 `global_scope.py:331` 写 `covered`。既然 `previous` 纯粹是引擎输出，这个优先级没换来任何东西。

**建议**: 改成只把明确要继承的字段（`covered` 及未来可能的用户字段）从 `previous` 白名单取出，其余以 `defaults` 为准。例如：

```python
inherited = {key: previous.get(key) for key in ("covered",) if previous.get(key) is not None}
rows.append({**defaults, **inherited, "id": ..., "name": name, ...})
```

**附带问题**: `previous` 还会带进引擎的 `fits`（中国市场时代的意图映射，`engine/scripts/blueprint.py:235`）和 `national`/`position`/`platforms`。全球渠道这三个值是 `None`，所以 `delivery.py:833-838` 不会渲染出假证据；但 5 个重叠 id 有 `fits`、17 个新 id 没有，schema 不一致。

---

## 问题三：默认值是共享可变对象

**位置**: `api/adapters/global_scope.py:318` + `325`

```python
defaults = CHANNEL_FIELD_DEFAULTS.get(channel_id, {...})
rows.append({**defaults, ...})
```

`**defaults` 是浅拷贝，`forms`/`domains` 这些 list 仍是模块级常量的同一个引用。实测：

```
forms shared identity: True | is module constant: True
```

每次 normalize 产出的 `forms`/`domains` 都是同一个 list 的别名。当前只写 JSON 所以没暴露，但任何下游就地修改（`channel["forms"].append(...)`）会污染整个进程的常量。

**建议**: `defaults = deepcopy(CHANNEL_FIELD_DEFAULTS.get(channel_id, {...}))`。文件顶部已 `from copy import deepcopy`，零成本。

---

## 问题四：新测试未走真实生产路径

**位置**: `api/tests/test_global_scope.py:118`

```python
blueprint = global_scope.normalize_blueprint_data({}, profile=profile)
```

传入的 blueprint 是 `{}`，`previous` 恒为空，只测到了默认值分支，恰好**绕过了生产中一定会发生的合并**（引擎先写 `blueprint.json`，normalize 再 merge）。它防的回归（引擎渲染 `KeyError`）也没在出问题的那一层验证。

**建议**: 拿 `engine/scripts/blueprint.CHANNELS_GLOBAL` 形状的数据喂进去，并断言 `_build_map_markdown`（`api/adapters/delivery.py:781`）或引擎渲染函数能跑通。这样才能覆盖「引擎旧值 + 画像默认值」的真实合并路径。

---

## 次要发现

1. **死条目**: `GLOBAL_CHANNEL_NAMES`（`global_scope.py:28`）里的 `reddit`/`devsite`/`media_en` 已无任何画像引用（已确认六个画像策略中均无这三个 id）；而 `normalize_blueprint_data:431` 的重命名对画像路径是无效操作，因为 `_profile_channels` 随后会用策略的 `name` 覆盖它。

2. **Reddit 被移除**: Reddit / Hacker News 在引擎全球集里是 P1，现在六个画像一个都没有；`developer_community` 的 domains 也只有 github/dev.to/stackoverflow。如果是**有意**的产品决策没问题，但值得确认——Reddit 在全球 AI 引用来源里权重不低（`engine/scripts/blueprint.py:120` 描述为 "Perplexity 和 Google AI Overviews 重点引用"）。

3. **排版不一致**: 新默认值用 ASCII 连字符（`2-4 posts/month`），引擎用 en dash（`2–4`），会在同一张交付表格里混排。

---

## 修复建议（按优先级）

1. **修合并顺序 + deepcopy**（小、低风险，先做）——问题二、三。
2. **单独处理画像渠道的覆盖检测**（需要决定无域名渠道的语义）——问题一。
3. **改进测试走真实路径**——问题四。
4. **清理死条目 / 确认 Reddit 移除 / 统一排版**——次要项。

（用户已确认：本次只修合并顺序 + 共享可变对象，覆盖检测语义留待后续单独讨论。）
