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
    },
)
