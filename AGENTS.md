# CiteAura — Codex 开发指令

## 项目一句话

基于开源 GEO 引擎（`engine/`）构建多租户 SaaS：用户填一个域名 → 自动出 AI 可见性报告 + 工单 + 验收 + 交付包。

## 目录结构

```
citeaura/
├── engine/                  # 允许修复 `engine/` 的通用缺陷，但不得引入租户、计费、认证等 SaaS 专属逻辑
│   ├── scripts/             # 核心 Python 模块（20 个 .py）
│   ├── tests/               # 229 个测试（必须保持全绿）
│   └── references/          # 方法论数据
├── api/                     # FastAPI 后端（新建）
│   ├── main.py              # 应用入口
│   ├── config.py            # 配置（env vars）
│   ├── auth/                # JWT 注册/登录
│   ├── projects/            # 项目 CRUD + 异步任务触发
│   ├── billing/             # 计费（试用限额 + Stripe）
│   ├── worker/              # Celery 任务定义
│   └── adapters/            # 引擎适配层（die→raise, tenant隔离, key注入）
├── web/                     # 前端（统一设计系统 SPA 与落地页）
│   ├── index.html           # 官网落地页
│   ├── app/                 # 统一 SPA 应用（ES Modules，挂载 /app）
│   │   ├── index.html       # SPA 入口
│   │   ├── app.js           # 核心路由器与状态中心
│   │   ├── api.js           # 强类型 API 客户端（~90 个端点，401 自动刷新）
│   │   ├── i18n.js          # 多语言引擎
│   │   ├── components/      # 通用 UI 组件原语
│   │   └── views/           # 24 个业务视图与 5 个认证视图
│   └── assets/              # 共享样式（tokens, base, components, app）、自托管字体与图标
├── docker-compose.yml       # Postgres + Redis + API + Worker
├── requirements.txt         # Python 依赖
├── .env.example             # 环境变量模板
├── PRD.md                   # 产品需求文档 v2.0
├── AGENTS.md                # 本文件
└── tasks.md                 # 执行任务清单
```

## 硬约束（违反即失败）

#1. **保持引擎公共接口兼容**。SaaS 定制逻辑继续放在 `api/adapters/`。
2. SaaS 层通过 `import` 调用 `engine/scripts/` 模块。
3. **文件系统是管线 SSOT**。Postgres 只存 auth/billing/project-index/job-meta。管线产物（audit.json, tasks.json, metrics/, delivery/）在磁盘 `work/<tenant>/<slug>/`。
4. **BYOK 优先**。用户自带 API Key，加密存储，运行时注入 `os.environ`。
5. **产品名统一 CiteAura**。统一官网为 `citeaura.com`。
6. **引擎测试必须保持全绿**：`cd engine && python3 -m unittest discover -s tests`。
7. **采样模式必须标注**。UI/API 返回时标明 "API·参数化知识" 或 "API·联网检索" 或 "人工·产品端"。
8. **数据真实与下钻溯源**。所有示例指标必须明确标注为 Demo/合成基准；所有真实指标必须能够下钻到样本（Prompt/Query）、来源（模型/版本）、采样模式和时间戳。

## 适配层要做的 5 件事

`api/adapters/` 是 SaaS 与引擎之间的胶水层：

| # | 问题 | 解法 |
|---|------|------|
| 1 | `geolib.die()` 调用 `sys.exit(1)` | 通过 `geolib.scoped_runtime` 的 ContextVar 注入 `raise GeoEngineError(msg)` |
| 2 | `geolib.project_dir(slug)` 无租户隔离 | 通过 `geolib.scoped_paths` 的 ContextVar 包装租户工作目录 |
| 3 | API Key 在 `.env` 全局环境变量 | 从 DB 解密 → `os.environ` 注入 → 调引擎 → 恢复 |
| 4 | `jobs.py` 用子进程 | 替换为 Celery task，保留 action 白名单逻辑 |
| 5 | `geolib.ROOT` 指向 engine/ | 运行时通过 `geolib.scoped_paths` 设置 ContextVar，不修改进程全局路径 |

## 技术栈

- **后端**：Python 3.12 + FastAPI + SQLAlchemy + Alembic
- **任务队列**：Celery + Redis
- **数据库**：PostgreSQL 15
- **认证**：JWT（access + refresh token）
- **加密**：AES-256-GCM（API Key 加密）
- **前端**：统一 SPA 架构（Vanilla JS ES Modules + 原生 CSS，自托管字体与图标，无构建步骤）
- **部署**：Docker Compose（单节点）

## 编码规范

- Python：遵循 engine/ 风格——无 type hints 强制、docstring 中文、`# noqa` 注释解释原因
- 文件头：不写 copyright，不写 author
- 命名：snake_case 函数/变量，PascalCase 类
- API 路由：`/api/v1/` 前缀
- 错误码：HTTP 标准状态码 + JSON body `{"error": "msg"}`
- 配置：全部走环境变量，`.env` 文件本地开发用
- 密钥：**绝不** hardcode，绝不 commit `.env`

## 引擎调用示例

```python
import sys
sys.path.insert(0, "/path/to/engine/scripts")

from api.adapters.engine import with_tenant_context

# 在 Celery task 中：
@celery.task
def run_bootstrap(tenant_id: str, project_slug: str):
    with with_tenant_context(tenant_id, project_slug):
        import bootstrap
        bootstrap.run(project_slug)
```

`with_tenant_context` 负责：设置租户路径和运行时钩子的 ContextVar → 注入 Key → yield → 恢复。

## 数据模型

```sql
-- 核心表
tenants (id, name, plan, trial_ends_at, created_at)
users (id, email, password_hash, created_at)
memberships (tenant_id, user_id, role)  -- role: owner/editor/viewer
projects (id, tenant_id, slug, url, market, status, created_at)
api_keys (id, tenant_id, engine_code, encrypted_value, created_at)
jobs (id, project_id, action, status, started_at, finished_at, error)
subscriptions (tenant_id, plan, started_at, expires_at)
usage_counters (tenant_id, month, sample_runs, projects_active)
```

管线产物不入 DB。`projects.slug` 对应 `work/<tenant.name>/<slug>/`。

## 测试命令

```bash
# 引擎测试（必须全绿）
cd engine && python3 -m unittest discover -s tests

# API 测试
cd api && pytest tests/ -v

# 全部
make test
```

## 不做的事

- 不做移动端
- 不做自动发布（只生成资产和交付包）
- 不做微信/WordPress 发布集成（P1）
- 不写代码注释解释"这是从哪里来的"或"为什么正确"——只写约束
