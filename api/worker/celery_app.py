"""Celery 应用配置。"""

from celery import Celery

from api import config

REDIS_URL = config.redis_url()

celery_app = Celery(
    "disvorai",
    broker=REDIS_URL,
    backend=config.celery_result_backend(),
    include=["api.worker.tasks"],
)
celery_app.conf.update(
    task_track_started=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
)
