# CrowdReply 对标改造交付记录

日期：2026-08-28

## API 与数据契约

- `GET /api/v1/projects/{id}/citation-sources`：读取当前租户最新稳定 JSONL run，返回 `measured | unmeasured`、`run_id`、UTC `sampled_at`、引用总数、域名、证据、warning 和未测原因。
- `POST /api/v1/projects/{id}/citation-sources/tickets`：按 `run_id + domain` 幂等创建 citation ticket，写入 `tasks.json`。
- `GET/PUT /api/v1/projects/{id}/entities` 与 restore API：只写 `offsite_entities.json` 和 tombstone sidecar，不写 Postgres，不访问第三方 URL。
- Content Opportunity 使用 `hash(question_id + gap_type + suggested_page_type)` 稳定 ID，按问题和采样模式形成 cohort。

## 状态与统计

- 只统计 `ok=true`、`search_enabled=true` 且 citations 为列表的记录。
- URL hostname 小写并移除 `www.`；同一 canonical URL 去重；每域最多保留 3 条证据。
- 不完整、正在追加、超大、超行数或 run ID 非法的文件不会进入聚合。
- 参数化知识不产生联网引用；无有效引用显示 `Unmeasured`，不显示伪造的 `0%`。

## 发布和回滚

- 总开关：`CITATION_INTELLIGENCE_V1`。
- 独立开关：`CITATION_API_V1`、`CITATION_CHANNELS_V1`、`CITATION_OVERVIEW_V1`。
- Shadow：`CITATION_SHADOW_MODE`；新旧域名计数差异写入 `shadow_mismatch` warning 和服务日志。
- 回滚只关闭对应开关；不得删除 samples、tasks、entities 或 delivery 产物。

## 验证证据

- Engine：`248 tests OK, 2 skipped`。
- API：`483 passed, 3 warnings`，包含 citation/entity/shadow/idempotency fixture。
- 浏览器截图：`.hermes/evidence/crowdreply-final/home-390.png`、`home-1024.png`、`home-1440.png`、`pricing-375.png`、`pricing-768.png`。
- 10,000 行 citation fixture 本机 20 次聚合：p95 `107.08ms`、max `108.68ms`，低于 300ms 预算，因此未启用短 TTL 缓存；文件仍为 SSOT。
- Python compile、JavaScript parse 和 `git diff --check` 通过。

## 外部运行项

- 真实 provider citation：`not measured`，当前任务没有授权 provider 凭据，未使用 mock 冒充生产事实。
- 生产 shadow 连续 24 小时观察：`not measured`，需要部署后经过真实时间窗口。
- P2 Authority Footprint / Listening Lite：`not approved`，缺少真实客户采用和引用来源数据，不进入生产范围。
