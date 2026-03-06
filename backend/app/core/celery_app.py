"""
Celery application configuration for asynchronous background jobs.
"""

from __future__ import annotations

import os

from celery import Celery
from celery.schedules import crontab
from kombu import Queue


default_redis_url = "redis://redis:6379/0"
broker_url = os.getenv("CELERY_BROKER_URL") or default_redis_url
result_backend = os.getenv("CELERY_RESULT_BACKEND") or default_redis_url

celery_app = Celery(
    "plasmaos",
    broker=broker_url,
    backend=result_backend,
    include=[
        "app.workers.tender_tasks",
        "app.workers.hunter_tasks",
    ],
)

celery_app.conf.update(
    task_track_started=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_max_tasks_per_child=int(os.getenv("CELERY_WORKER_MAX_TASKS_PER_CHILD", "10")),
    beat_schedule={
        "run-hunter-sweep-every-30-minutes": {
            "task": "app.workers.hunter_tasks.run_hunter_sweep",
            "schedule": crontab(minute="*/30"),
        },
    },
)

celery_app.conf.task_queues = (
    Queue("celery", routing_key="celery"),
    Queue("ai_fast_queue", routing_key="ai_fast_queue"),
    Queue("heavy_dl_queue", routing_key="heavy_dl_queue"),
)

celery_app.conf.task_routes = {
    "app.workers.tender_tasks.*": {"queue": "heavy_dl_queue"},
    "app.workers.hunter_tasks.*": {"queue": "ai_fast_queue"},
}
