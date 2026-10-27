"""Celery 应用配置。"""

from celery import Celery

from api import config

REDIS_URL = config.redis_url()

# 首次诊断会抓取站点并完成全量采样；实测一次 420 请求的诊断约需 70 分钟，
# 短任务的 59 分钟软超时会在引擎完成前把 Job 判失败。
LONG_RUNNING_TASKS = (
    "citeaura.bootstrap",
    "citeaura.sample",
    "citeaura.cycle",
    "citeaura.pipeline",
    "citeaura.deliver",
)

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
    task_annotations={
        name: {
            "soft_time_limit": config.long_task_soft_time_limit_seconds(),
            "time_limit": config.long_task_time_limit_seconds(),
        }
        for name in LONG_RUNNING_TASKS
    },
    worker_pool="prefork",
    # 隔离模式下每个任务会再起一个引擎子进程，默认 4 个并发槽位。
    worker_concurrency=config.worker_concurrency(),
    # 长任务必须一个 worker 只预取一个：默认的 4 会让 4 个租户的项目互相排队。
    worker_prefetch_multiplier=1,
    # Redis broker 的可见性超时必须大于长任务硬超时，否则任务被硬杀后会
    # 被重投并在原执行仍在跑的情况下重复执行（重复采样=重复付费）。
    broker_transport_options={
        "visibility_timeout": max(10_800, config.long_task_time_limit_seconds() + 600),
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
