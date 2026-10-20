# 第三方许可证核查

## 引擎

- `engine/` 来自 CiteAura 自研开源 GEO 引擎，仓库内 `engine/LICENSE` 为 MIT。
- MIT 允许商业使用、修改与再分发；SaaS 层通过 `import` 调用 `engine/scripts/`，未修改许可证文本。
- `engine/` 内不包含租户、计费、认证等 SaaS 逻辑；这些逻辑全部位于 `api/`。

## Python 依赖

主要运行时依赖（FastAPI、SQLAlchemy、Alembic、Celery、Requests、BeautifulSoup、lxml、PyYAML、cryptography、Stripe SDK）均为 MIT / BSD / Apache-2.0 系许可证，允许闭源 SaaS 使用。发布前由 CI 的依赖审计复核；新增依赖必须在 `requirements.txt` 与 `requirements.lock` 中同时出现。

## 前端与字体

- 前端不使用框架运行时，无构建步骤。
- 自托管字体与图标的许可证记录在 `web/assets/` 对应目录；发布前不得引入无授权字体。
- 未引入任何需要署名展示的第三方 UI 组件。

## 内容与数据

- `engine/references/` 的方法论数据由项目维护，随 MIT 许可证分发。
- 演示指标必须标注 Demo/合成基准；生产指标必须可下钻到 Prompt、来源模型与版本、采样模式和时间戳。

## 结论

当前依赖组合可用于商业闭源 SaaS。若未来引入 GPL/AGPL 依赖，必须在此文档记录隔离方式或替换决定。
