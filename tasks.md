# CiteAura 开发任务清单

每条任务有明确的输入、输出和验收标准。按顺序执行，后一条依赖前一条。

---

## Phase 1: 基础骨架（W1）

### Task 1.1: 项目初始化

**输入**：空的 `api/` 目录  
**输出**：可运行的 FastAPI 项目骨架  

- 创建 `api/main.py`（FastAPI app，含 health check `/api/v1/health`）
- 创建 `requirements.txt`（fastapi, uvicorn, sqlalchemy, alembic, celery, redis, pyjwt, cryptography, psycopg2-binary, pydantic, python-dotenv）
- 创建 `docker-compose.yml`（postgres:15, redis:7, api service, worker service）
- 创建 `.env.example`（DATABASE_URL, REDIS_URL, JWT_SECRET, AES_KEY）
- 创建 `Makefile`（targets: dev, test, migrate, worker）

**验收**：`docker-compose up` 后 `curl localhost:8000/api/v1/health` 返回 `{"status":"ok"}`

---

### Task 1.2: 数据库 + Alembic

**输入**：Task 1.1 完成  
**输出**：数据模型 + 初始迁移  

- 创建 `api/db.py`（engine, SessionLocal, Base）
- 创建 `api/models.py`（Tenant, User, Membership, Project, ApiKey, Job, Subscription, UsageCounter）
- 配置 Alembic（`alembic.ini` + `api/migrations/`）
- 生成并应用初始迁移

**验收**：`alembic upgrade head` 成功，表结构与 AGENTS.md 数据模型一致

---

### Task 1.3: Auth 模块

**输入**：Task 1.2 完成  
**输出**：注册/登录/鉴权  

- 创建 `api/auth/router.py`：
  - `POST /api/v1/auth/register` → 创建 user + 默认 tenant（14天试用）+ membership(owner)
  - `POST /api/v1/auth/login` → 返回 JWT access_token + refresh_token
  - `GET /api/v1/me` → 当前用户信息 + tenant
- 创建 `api/auth/deps.py`：`get_current_user` 依赖（JWT 验证）
- 创建 `api/auth/security.py`：密码 hash（bcrypt）、JWT 签发/验证

**验收**：注册 → 登录 → 用 token 访问 /me → 返回用户信息

---

### Task 1.4: 适配层

**输入**：Task 1.1 完成  
**输出**：`api/adapters/` 使引擎模块可在 worker 中安全调用  

- 创建 `api/adapters/__init__.py`
- 创建 `api/adapters/engine.py`：
  - `patch_die()`：monkey-patch `geolib.die` → raise `GeoEngineError`
  - `patch_paths(tenant_slug, project_slug)`：设置 `geolib.WORK = WORK_ROOT / tenant_slug`
  - `inject_keys(keys: dict)`：临时注入 `os.environ`，用完恢复
  - `with_tenant_context(tenant_id, project_slug)` context manager：组合以上三步
- 创建 `api/adapters/exceptions.py`：`GeoEngineError(message)`

**验收**：
```python
with with_tenant_context("test-tenant", "example"):
    import geolib as G
    assert "test-tenant" in str(G.WORK)
    try:
        G.die("test error")
    except GeoEngineError:
        pass  # 不会 sys.exit
```

---

### Task 1.5: Celery Worker + 第一个任务

**输入**：Task 1.4 完成  
**输出**：异步任务可执行 bootstrap 流程  

- 创建 `api/worker/celery_app.py`（Celery 实例，broker=redis）
- 创建 `api/worker/tasks.py`：
  - `task_bootstrap(tenant_id, project_slug, skip_llm=False)`
  - `task_sample(tenant_id, project_slug, limit=None)`
  - `task_cycle(tenant_id, project_slug)`
  - `task_verify(tenant_id, project_slug)`
  - `task_deliver(tenant_id, project_slug)`
- 每个 task 内部：`with with_tenant_context(...)` → import 对应模块 → 调用 run()
- Job 状态回写 DB（started_at, finished_at, status, error）

**验收**：Celery worker 启动无报错；`task_bootstrap.delay("t1", "test")` 投递成功并在 worker 中执行（可用 `--skip-llm` 跳过 LLM 调用）

---

### Task 1.6: Project CRUD + Bootstrap 流程

**输入**：Task 1.3 + 1.5 完成  
**输出**：创建项目自动触发 bootstrap  

- 创建 `api/projects/router.py`：
  - `POST /api/v1/projects` { url } → 创建 DB 记录（全引擎范围）→ 调引擎 `geo.cmd_init()` → 触发 Celery `task_bootstrap` → 返回 `{project_id, job_id}`
  - `GET /api/v1/projects` → 列表（当前 tenant）
  - `GET /api/v1/projects/:id` → 详情（复用 `dashboard.project()` 逻辑）
  - `GET /api/v1/projects/:id/jobs` → 任务历史
  - `GET /api/v1/projects/:id/jobs/:jid` → 任务状态 + 日志
- 租户隔离：所有查询过滤 `tenant_id = current_user.tenant_id`

**验收**：`POST /projects {url: "https://example.com"}` → 返回 project + job_id → 轮询 job 状态变为 done → `GET /projects/:id` 返回品牌信息和问题库

---

## Phase 2: 核心功能（W2）

### Task 2.1: API Key 管理

- `PUT /api/v1/settings/keys` { engine_code, key_value } → AES-256-GCM 加密存到 DB
- `GET /api/v1/settings/keys` → 返回已配引擎列表（不返回明文，只返回 engine_code + masked）
- `DELETE /api/v1/settings/keys/:engine_code`
- 适配层 `inject_keys` 从 DB 解密并注入

**验收**：配了 DEEPSEEK_API_KEY 后，sample 任务能成功调用 DeepSeek

---

### Task 2.2: Sample + Report API

- `POST /api/v1/projects/:id/sample` { limit?, platforms? } → 触发 Celery task → 返回 job_id
- `GET /api/v1/projects/:id/report` → 返回最新 report 数据（从 metrics/*.json 读）
- `GET /api/v1/projects/:id/engines` → 分引擎指标（mention_rate, rank, citations）
- `GET /api/v1/projects/:id/samples/:date` → 原始答案列表（raw answer 回放）

**验收**：配了至少一个 Key → sample 完成 → report 返回分引擎 mention_rate

---

### Task 2.3: Tickets + Verify API

- `GET /api/v1/projects/:id/tickets` → 工单列表（从 tasks.json 读）
- `PATCH /api/v1/projects/:id/tickets/:tid` { status, note } → 调 `tasks.set_status()`
- `POST /api/v1/projects/:id/verify` → 触发 Celery task → 返回 job_id
- `GET /api/v1/projects/:id/verify/history` → 验收历史列表

**验收**：verify 完成后，之前标 todo 的技术工单若条件满足自动变 done；手动改 done 再 verify 可回归 reopen

---

### Task 2.4: Delivery API

- `POST /api/v1/projects/:id/deliver` → 触发 Celery task → 返回 job_id
- `GET /api/v1/projects/:id/deliveries` → 交付历史（日期列表）
- `GET /api/v1/projects/:id/deliveries/:date` → 下载 zip

**验收**：deliver 完成后，下载 zip 包含 index.html + 01~06 文档 + assets/

---

## Phase 3: 计费 + 部署（W3-W4）

### Task 3.1: 试用限额

- 中间件检查：试用期内 projects ≤ 3，sample_runs ≤ 2/project
- 超限时 API 返回 `403 {"error": "trial_limit_exceeded", "detail": "..."}`
- `GET /api/v1/billing/usage` → 当前用量

**验收**：试用用户第 4 个项目创建失败；第 3 次 sample 被拒

---

### Task 3.2: 订阅骨架

- `POST /api/v1/billing/subscribe` { plan } → 升级 tenant.plan
- `GET /api/v1/billing/plans` → 可用套餐列表
- 升级后限额放开
- 支付集成（Stripe 或支付宝）可先 mock，只要接口协议对

**验收**：subscribe 后 plan 变为 pro，限额放开

---

### Task 3.3: Docker 生产部署

- `Dockerfile`（multi-stage：api + worker）
- `docker-compose.prod.yml`（加 nginx 反代 + HTTPS）
- `scripts/deploy.sh`（一键部署到 VPS）
- `.env.production.example`

**验收**：`docker-compose -f docker-compose.prod.yml up` 在全新 VPS 上可跑通完整 demo 流程

---

## Phase 4: 前端（统一 SPA 与落地页重构）

### Task 4.1: 落地页与设计系统重构

- 落地页 `web/index.html`：Space Grotesk + OKLCH Teal 主色 + 4/16/36 节奏
- 自托管字体与图标：`web/assets/fonts/`、`web/assets/icons/`（零外部 CDN 依赖）
- 三种采样方式明确标注（API·参数化知识 / API·联网检索 / 人工·产品端）
- 多语言切换与中英日三语目录同步（`api/i18n/messages/`）

### Task 4.2: 统一 SPA 架构与 6 轨道导航

- 创建 `web/app/` 原生 ES Modules SPA 架构（挂载 `/app`，零构建步骤）
- 6 轨道全局导航（概览 / 监测 / 诊断 / 执行 / 交付 / 管理）
- 24 个业务视图与 5 个认证视图（登录、注册、找回密码、重置密码、接受邀请）
- 组件库原语（Toast, Modal, Badge, KPI, Table, Tabs, Empty, Skeleton）

### Task 4.3: 强类型 API 客户端与多语言引擎

- `web/app/api.js` 统一封装 ~90 个 API 端点，支持凭证鉴权与 401 自动刷新
- `web/app/i18n.js` 多语言解析引擎，支持点路径 key 解析与 en 兜底

### Task 4.4: 闭环验证与清退旧注入

- 清退 `api/ui.py` 中 3300+ 行旧 monkey-patch，瘦身为标准 SPA 静态伺服与 `/files` 交付下载
- 更新 `api/tests/test_ui.py`，完整 API 与 engine 回归测试保持 100% 通过

**验收**：浏览器打开 `/app` 呈现现代化精密仪器级 GEO 控制台，所有测试全绿通过

---

## 执行注意事项

1. 每完成一个 Task，运行 `cd engine && python3 -m unittest discover -s tests` 确保引擎测试不被破坏
2. 每个 Task 独立提交，commit message 格式：`feat(module): 描述`
3. 引擎通用缺陷可在 `engine/` 修复；租户、计费、认证等 SaaS 专属逻辑必须留在 `api/adapters/`
4. 所有异步操作返回 `job_id`，前端通过轮询 `/jobs/:jid` 获取进度
5. 错误处理：引擎的 `GeoEngineError` 在 API 层转为 HTTP 400/500 + JSON body
