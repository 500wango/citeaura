"""Celery Job 的运行时基础设施，不包含具体业务动作。"""

from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from api.db import SessionLocal
from api.models import Job, Project
from api.adapters.sampling_control import release_reservation
from api import config


def as_utc(value):
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def next_scheduled_run(scheduled_for, interval_days, now):
    """保持原有节奏，并跳过服务停机期间错过的周期。"""
    next_run = as_utc(scheduled_for) + timedelta(days=interval_days)
    while next_run <= now:
        next_run += timedelta(days=interval_days)
    return next_run


def reclaim_stale_jobs(db, now):
    """回收超过最大执行窗口仍活跃的任务，避免项目永久占用。

    queued 也必须回收：broker 丢消息时 Job 会带着 celery_task_id 永久停在
    queued（派发后立刻回写 task id），而 uq_jobs_project_active 会让该项目之后
    任何新任务都插入失败，retry 又要求 status="failed"，用户侧无法自救。
    """
    cutoff = now - timedelta(seconds=config.stale_running_job_timeout_seconds())
    last_seen = func.coalesce(Job.heartbeat_at, Job.started_at, Job.created_at)
    stale = db.query(Job).filter(
        Job.status.in_(("queued", "running")),
        last_seen < cutoff,
    ).all()
    reclaimed = 0
    for job in stale:
        # 条件更新：SELECT 与 COMMIT 之间已完成的 Job 不能被覆写成 failed。
        claimed = db.query(Job).filter(
            Job.id == job.id,
            Job.status == job.status,
            func.coalesce(Job.heartbeat_at, Job.started_at, Job.created_at) < cutoff,
        ).update(
            {
                Job.status: "failed",
                Job.stage: "failed",
                Job.finished_at: now,
                Job.error: "worker_lost_or_timeout",
            },
            synchronize_session=False,
        )
        db.expire(job)
        if claimed != 1:
            continue
        release_reservation(job)
        if job.project_id is not None:
            newer_active = db.query(Job.id).filter(
                Job.id != job.id,
                Job.project_id == job.project_id,
                Job.status.in_(("queued", "running")),
            ).first()
            project = db.get(Project, job.project_id)
            if newer_active is None and project is not None and project.status not in ("archived",):
                project.status = "failed"
        reclaimed += 1
    if reclaimed:
        db.commit()
    return reclaimed


@contextmanager
def capture_task_output(log_path, logger):
    """把引擎 print 输出写入当前 Job 日志。"""
    if log_path is None:
        yield
        return
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handle = log_path.open("a", encoding="utf-8", buffering=1)
    except OSError as exc:
        logger.error("Unable to capture job output in %s: %s", log_path, exc)
        yield
        return
    with handle:
        with redirect_stdout(handle), redirect_stderr(handle):
            yield


def append_job_event(log_path, message, logger):
    if log_path is None:
        return False
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"[citeaura] {message}\n")
    except OSError as exc:
        logger.error("Unable to append job event in %s: %s", log_path, exc)
        return False
    return True


def database_connection_lost(exc):
    if exc.connection_invalidated:
        return True
    message = str(getattr(exc, "orig", exc)).lower()
    return any(marker in message for marker in (
        "connection has been closed",
        "connection is closed",
        "connection already closed",
        "closed the connection unexpectedly",
        "closed unexpectedly",
        "connection reset",
        "server closed the connection",
        "terminating connection",
    ))


def job_transaction(operation, logger, retries=2, session_factory=None):
    """用短会话更新 Job；断开的数据库连接可安全重放。"""
    retries = max(1, int(retries))
    session_factory = session_factory or SessionLocal
    for attempt in range(retries):
        db = session_factory()
        try:
            result = operation(db)
            db.commit()
            return result
        except DBAPIError as exc:
            try:
                db.rollback()
            except SQLAlchemyError:
                pass
            if attempt + 1 < retries and database_connection_lost(exc):
                logger.warning("job status database connection lost; retrying with a fresh session")
                continue
            raise
        except SQLAlchemyError:
            db.rollback()
            raise
        finally:
            db.close()
