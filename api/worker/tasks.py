"""引擎异步任务。"""

from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy.exc import SQLAlchemyError

from api.adapters.engine import load_tenant_keys, with_tenant_context
from api.db import SessionLocal
from api.models import Job, Project, Tenant
from api.worker.celery_app import celery_app


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
def _job_status(tenant_id, project_slug, action, job_id=None):
    """把 Job 标为 running/done/failed；DB 不可用时不阻断直接 worker 调用。"""
    db = SessionLocal()
    job = None
    try:
        try:
            job = _find_job(db, tenant_id, project_slug, action, job_id)
            if job is not None:
                job.status = "running"
                job.started_at = datetime.now(timezone.utc)
                job.error = None
                db.commit()
        except SQLAlchemyError:
            db.rollback()
            job = None

        try:
            yield
        except Exception as exc:
            if job is not None:
                job.status = "failed"
                job.finished_at = datetime.now(timezone.utc)
                job.error = f"{type(exc).__name__}: {exc}"
                try:
                    db.commit()
                except SQLAlchemyError:
                    db.rollback()
            raise
        else:
            if job is not None:
                job.status = "done"
                job.finished_at = datetime.now(timezone.utc)
                job.error = None
                try:
                    db.commit()
                except SQLAlchemyError:
                    db.rollback()
    finally:
        db.close()


@celery_app.task(name="disvorai.bootstrap")
def task_bootstrap(tenant_id: str, project_slug: str, skip_llm: bool = False, job_id=None):
    """执行官网底座自动推导。"""
    import bootstrap

    with _job_status(tenant_id, project_slug, "bootstrap", job_id):
        with with_tenant_context(str(tenant_id), project_slug, keys=_engine_keys(tenant_id)):
            return bootstrap.run(project_slug, skip_llm=skip_llm)


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
