"""
Celery application configuration for asynchronous background jobs.
"""

from __future__ import annotations

import logging
import os

from celery import Celery
from celery.schedules import crontab
from celery.signals import beat_init, worker_ready
from kombu import Queue

from app.core.release import public_release_metadata

logger = logging.getLogger(__name__)


default_redis_url = "redis://127.0.0.1:6379/0"
broker_url = os.getenv("CELERY_BROKER_URL") or default_redis_url
result_backend = os.getenv("CELERY_RESULT_BACKEND") or default_redis_url

celery_app = Celery(
    "plasmaos",
    broker=broker_url,
    backend=result_backend,
    include=[
        "app.workers.tender_tasks",
        "app.workers.source_refresh_tasks",
        "app.workers.project_enrichment_tasks",
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
    task_publish_retry=True,
    task_publish_retry_policy={
        "max_retries": 3,
        "interval_start": 0,
        "interval_step": 0.2,
        "interval_max": 1,
    },
    broker_connection_retry_on_startup=True,
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
    "app.workers.source_refresh_tasks.refresh_tender_source": {
        "queue": "celery",
        "routing_key": "celery",
    },
    "app.workers.project_enrichment_tasks.enrich_world_bank_project": {
        "queue": "celery",
        "routing_key": "celery",
    },
    "app.workers.tender_tasks.hydrate_giz_documents": {
        "queue": "heavy_dl_queue",
        "routing_key": "heavy_dl_queue",
    },
    "app.workers.tender_tasks.process_tender_docs": {
        "queue": "heavy_dl_queue",
        "routing_key": "heavy_dl_queue",
    },
    "app.workers.tender_tasks.*": {
        "queue": "heavy_dl_queue",
        "routing_key": "heavy_dl_queue",
    },
    "app.workers.hunter_tasks.*": {"queue": "ai_fast_queue"},
}


def _log_release_identity(component: str) -> None:
    payload = public_release_metadata()
    payload["component"] = component
    logger.info("plasma_release_identity %s", payload)


@worker_ready.connect
def log_worker_release_identity(**_: object) -> None:
    _log_release_identity("celery_worker")


@beat_init.connect
def log_beat_release_identity(**_: object) -> None:
    _log_release_identity("celery_beat")
