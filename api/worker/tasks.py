"""引擎异步任务。"""

from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy.exc import SQLAlchemyError

from api.adapters.engine import job_log_path, load_tenant_keys, with_tenant_context
from api.adapters.workspace import preserve_manual_tickets
from api.db import SessionLocal
from api.models import Job, Project, Tenant
from api.worker.celery_app import celery_app


PIPELINE_ACTIONS = {
    "crawl": {"label": "抓取站点", "args": ["--max-pages"]},
    "audit": {"label": "页面体检", "args": []},
    "sample": {"label": "AI 答案采样", "args": ["--limit", "--repeat", "--platforms"]},
    "bootstrap": {"label": "自动推导底座", "args": ["--skip-llm"]},
    "deliverables": {"label": "出三份交付物", "args": []},
    "plan": {"label": "生成工单", "args": []},
    "expand": {"label": "拓词扩题", "args": ["--no-llm"]},
    "blueprint": {"label": "生成建设蓝图", "args": []},
    "generate": {"label": "生成资产", "args": ["--asset", "--draft", "--draft-limit"]},
    "lint": {"label": "初稿风险检查", "args": []},
    "report": {"label": "生成报告", "args": []},
    "verify": {"label": "自动验收", "args": ["--no-recrawl"]},
    "deliver": {"label": "打包交付", "args": []},
    "sample-sheet": {"label": "导出人工采样表", "args": []},
    "autopilot": {"label": "全自动引导", "args": ["--no-sample", "--limit", "--skip-llm"]},
    "serve": {
        "label": "跑完整周期",
        "args": ["--max-pages", "--limit", "--no-sample", "--draft", "--draft-limit"],
    },
}

_ACTION_METHODS = {
    "crawl": "cmd_crawl",
    "audit": "cmd_audit",
    "sample": "cmd_sample",
    "bootstrap": "cmd_bootstrap",
    "deliverables": "cmd_deliverables",
    "plan": "cmd_plan",
    "expand": "cmd_expand",
    "blueprint": "cmd_blueprint",
    "generate": "cmd_generate",
    "lint": "cmd_lint",
    "report": "cmd_report",
    "verify": "cmd_verify",
    "deliver": "cmd_deliver",
    "sample-sheet": "cmd_sheet",
    "autopilot": "cmd_autopilot",
    "serve": "cmd_serve",
}

_ACTION_DEFAULTS = {
    "crawl": {"max_pages": None},
    "audit": {},
    "sample": {"limit": None, "repeat": 1, "platforms": None},
    "bootstrap": {"skip_llm": False},
    "deliverables": {},
    "plan": {},
    "expand": {"no_llm": False},
    "blueprint": {},
    "generate": {"asset": None, "draft": False, "draft_limit": None},
    "lint": {},
    "report": {},
    "verify": {"no_recrawl": False},
    "deliver": {},
    "sample-sheet": {},
    "autopilot": {"no_sample": False, "limit": None, "skip_llm": False},
    "serve": {"max_pages": None, "limit": None, "no_sample": False, "draft": False, "draft_limit": None},
}

_INTEGER_LIMITS = {
    "--max-pages": (1, 1000),
    "--limit": (1, 1000),
    "--repeat": (1, 10),
    "--draft-limit": (1, 100),
}
_FLAG_ARGS = {"--no-recrawl", "--draft", "--no-sample", "--skip-llm", "--no-llm"}
_CSV_ARGS = {"--platforms", "--asset"}


def _action_namespace(action, params=None):
    """按引擎动作白名单清洗参数，并转换为 geo.cmd_* 所需对象。"""
    if action not in PIPELINE_ACTIONS:
        raise ValueError(f"unsupported pipeline action: {action}")
    values = dict(_ACTION_DEFAULTS[action])
    allowed = set(PIPELINE_ACTIONS[action]["args"])
    for raw_name, value in (params or {}).items():
        flag = str(raw_name)
        if not flag.startswith("--"):
            flag = "--" + flag.replace("_", "-")
        if flag not in allowed:
            continue
        name = flag[2:].replace("-", "_")
        if flag in _FLAG_ARGS:
            values[name] = value is True
        elif value in (None, "", []):
            continue
        elif flag in _INTEGER_LIMITS:
            number = int(value)
            minimum, maximum = _INTEGER_LIMITS[flag]
            if not minimum <= number <= maximum:
                raise ValueError(f"{flag} must be between {minimum} and {maximum}")
            values[name] = number
        elif flag in _CSV_ARGS:
            values[name] = ",".join(str(item) for item in value) if isinstance(value, list) else str(value)
    return SimpleNamespace(**values)


def _run_pipeline_action(action, project_slug, params=None):
    import geo

    method = getattr(geo, _ACTION_METHODS[action])
    args = _action_namespace(action, params)
    args.slug = project_slug
    method(args)
    return {"status": "done", "action": action, "project_slug": project_slug}


def _tenant_record(db, tenant_id):
    """按数据库 id 或租户名称查找租户。"""
    try:
        return db.get(Tenant, int(tenant_id))
    except (TypeError, ValueError):
        return db.query(Tenant).filter(Tenant.name == str(tenant_id)).first()


def _find_job(db, tenant_id, project_slug, action, job_id):
    """定位 API 预创建的 Job，兼容 worker 直接调用。"""
    tenant = _tenant_record(db, tenant_id)
    if tenant is None:
        return None
    project = db.query(Project).filter(
        Project.tenant_id == tenant.id,
        Project.slug == project_slug,
    ).first()
    if project is None:
        return None
    if job_id is not None:
        try:
            job_id = int(job_id)
        except (TypeError, ValueError):
            return None
        return db.query(Job).filter(
            Job.id == job_id,
            Job.project_id == project.id,
            Job.action == action,
        ).first()
    return (
        db.query(Job)
        .filter(Job.project_id == project.id, Job.action == action, Job.status.in_(("queued", "running")))
        .order_by(Job.id.desc())
        .first()
    )


def _engine_keys(tenant_id):
    """读取租户 Key；直接调用任务且没有数据库时降级为空集合。"""
    db = SessionLocal()
    try:
        return load_tenant_keys(db, tenant_id)
    except SQLAlchemyError:
        db.rollback()
        return {}
    finally:
        db.close()


@contextmanager
def _capture_task_output(log_path):
    """把引擎 print 输出写入当前 Job 日志。"""
    if log_path is None:
        yield
        return
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8", buffering=1) as handle:
        with redirect_stdout(handle), redirect_stderr(handle):
            yield


def _append_job_event(log_path, message):
    if log_path is None:
        return
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(f"[disvorai] {message}\n")


@contextmanager
def _job_status(tenant_id, project_slug, action, job_id=None):
    """把 Job 标为 running/done/failed；DB 不可用时不阻断直接 worker 调用。"""
    db = SessionLocal()
    job = None
    project = None
    log_path = None
    try:
        try:
            job = _find_job(db, tenant_id, project_slug, action, job_id)
            if job is not None:
                project = db.get(Project, job.project_id)
                tenant = db.get(Tenant, project.tenant_id) if project is not None else None
                if tenant is not None:
                    log_path = job_log_path(tenant.name, project.slug, job.id)
                    job.log_path = str(log_path)
                job.status = "running"
                job.started_at = datetime.now(timezone.utc)
                job.error = None
                db.commit()
        except SQLAlchemyError:
            db.rollback()
            job = None
            project = None

        try:
            _append_job_event(log_path, f"{action} started")
            with _capture_task_output(log_path):
                yield
        except Exception as exc:
            _append_job_event(log_path, f"{action} failed: {type(exc).__name__}: {exc}")
            if job is not None:
                job.status = "failed"
                job.finished_at = datetime.now(timezone.utc)
                job.error = f"{type(exc).__name__}: {exc}"
                if project is not None:
                    project.status = "failed"
                try:
                    db.commit()
                except SQLAlchemyError:
                    db.rollback()
            raise
        else:
            _append_job_event(log_path, f"{action} done")
            if job is not None:
                job.status = "done"
                job.finished_at = datetime.now(timezone.utc)
                job.error = None
                if project is not None:
                    project.status = "ready"
                try:
                    db.commit()
                except SQLAlchemyError:
                    db.rollback()
    finally:
        db.close()


@celery_app.task(name="disvorai.bootstrap")
def task_bootstrap(
    tenant_id: str,
    project_slug: str,
    skip_llm: bool = False,
    no_sample: bool = False,
    job_action: str = "bootstrap",
    job_id=None,
):
    """执行新项目的完整自动引导。"""
    import geo

    args = SimpleNamespace(slug=project_slug, skip_llm=skip_llm, no_sample=no_sample, limit=None)
    with _job_status(tenant_id, project_slug, job_action, job_id):
        with with_tenant_context(str(tenant_id), project_slug, keys=_engine_keys(tenant_id)):
            with preserve_manual_tickets(project_slug):
                geo.cmd_autopilot(args)
            return {"status": "done", "action": job_action, "project_slug": project_slug}


@celery_app.task(name="disvorai.sample")
def task_sample(
    tenant_id: str,
    project_slug: str,
    limit: int | None = None,
    platforms: list[str] | None = None,
    job_id=None,
):
    """执行 API 采样和指标聚合。"""
    import sample

    with _job_status(tenant_id, project_slug, "sample", job_id):
        with with_tenant_context(str(tenant_id), project_slug, keys=_engine_keys(tenant_id)):
            return sample.run(project_slug, platforms=platforms, limit=limit)


@celery_app.task(name="disvorai.cycle")
def task_cycle(tenant_id: str, project_slug: str, job_id=None):
    """执行抓取、体检、采样和报告周期。"""
    import geo

    args = SimpleNamespace(slug=project_slug, max_pages=None, limit=None)
    with _job_status(tenant_id, project_slug, "cycle", job_id):
        with with_tenant_context(str(tenant_id), project_slug, keys=_engine_keys(tenant_id)):
            geo.cmd_cycle(args)
            return {"status": "done", "project_slug": project_slug}


@celery_app.task(name="disvorai.verify")
def task_verify(tenant_id: str, project_slug: str, job_id=None):
    """执行工单自动验收。"""
    import verify

    with _job_status(tenant_id, project_slug, "verify", job_id):
        with with_tenant_context(str(tenant_id), project_slug, keys=_engine_keys(tenant_id)):
            return verify.run(project_slug)


@celery_app.task(name="disvorai.deliver")
def task_deliver(tenant_id: str, project_slug: str, job_id=None):
    """生成客户交付包。"""
    import deliver

    with _job_status(tenant_id, project_slug, "deliver", job_id):
        with with_tenant_context(str(tenant_id), project_slug, keys=_engine_keys(tenant_id)):
            return str(deliver.run(project_slug))


@celery_app.task(name="disvorai.pipeline")
def task_pipeline(tenant_id: str, project_slug: str, action: str, params=None, job_id=None):
    """执行经过白名单校验的完整引擎动作。"""
    with _job_status(tenant_id, project_slug, action, job_id):
        with with_tenant_context(str(tenant_id), project_slug, keys=_engine_keys(tenant_id)):
            if action in ("plan", "autopilot", "serve"):
                with preserve_manual_tickets(project_slug):
                    return _run_pipeline_action(action, project_slug, params)
            return _run_pipeline_action(action, project_slug, params)
