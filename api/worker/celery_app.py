"""Celery 应用配置。"""

from celery import Celery

from api import config

REDIS_URL = config.redis_url()

celery_app = Celery(
    "citeaura",
    broker=REDIS_URL,
    backend=config.celery_result_backend(),
    include=["api.worker.tasks"],
)
celery_app.conf.update(
    task_track_started=True,
    task_ignore_result=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_time_limit=3600,
    task_soft_time_limit=3540,
    worker_pool="prefork",
    # 隔离模式下每个任务会再起一个引擎子进程，默认 4 个并发槽位。
    worker_concurrency=config.worker_concurrency(),
    # 长任务必须一个 worker 只预取一个：默认的 4 会让 4 个租户的项目互相排队。
    worker_prefetch_multiplier=1,
    # Redis broker 的默认可见性超时也是 3600s，与硬超时相等；任务被硬杀后会被
    # 重投并在原执行仍在跑的情况下重复执行（重复采样=重复付费）。留一倍余量。
    broker_transport_options={
        "visibility_timeout": 7200,
        "socket_connect_timeout": 5,
        "socket_timeout": 30,
    },
    result_expires=3600,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    beat_schedule={
        "dispatch-due-project-schedules": {
            "task": "citeaura.dispatch_schedules",
            "schedule": 60.0,
        },
        "reconcile-platform-usage": {
            "task": "citeaura.reconcile_platform_usage",
            "schedule": 60.0,
        },
        "cleanup-expired-projects": {
            "task": "citeaura.cleanup_expired_projects",
            "schedule": 86400.0,
        },
    },
)
