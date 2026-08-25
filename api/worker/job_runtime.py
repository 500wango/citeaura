"""Celery Job 的运行时基础设施，不包含具体业务动作。"""

from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone

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
    """回收超过 Celery 最大执行窗口仍活跃的任务，避免项目永久占用。"""
    cutoff = now - timedelta(seconds=config.stale_running_job_timeout_seconds())
    stale_running = db.query(Job).filter(
        Job.status == "running",
        Job.started_at.isnot(None),
        Job.started_at < cutoff,
    ).all()
    stale_queued = db.query(Job).filter(
        Job.status == "queued",
        Job.created_at < cutoff,
        Job.celery_task_id.is_(None),
    ).all()
    reclaimed = 0
    for job in stale_running + stale_queued:
        project = db.get(Project, job.project_id)
        job.status = "failed"
        job.stage = "failed"
        job.finished_at = now
        job.error = "worker_lost_or_timeout"
        release_reservation(job)
        if project is not None and project.status not in ("archived",):
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
