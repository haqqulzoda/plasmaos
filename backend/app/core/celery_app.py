"""
Celery application configuration for asynchronous background jobs.
"""

from __future__ import annotations

import logging
import os
from datetime import timedelta

from celery import Celery
from celery.schedules import crontab
from celery.signals import beat_init, task_prerun, worker_ready
from kombu import Queue

from app.core.release import public_release_metadata
from app.services.source_refresh_schedule import (
    build_beat_schedule,
    configured_source_refresh_schedule,
    schedule_tick_seconds,
)

logger = logging.getLogger(__name__)


default_redis_url = "redis://127.0.0.1:6379/0"
broker_url = os.getenv("CELERY_BROKER_URL") or default_redis_url
result_backend = os.getenv("CELERY_RESULT_BACKEND") or default_redis_url
world_bank_autodrain_interval_seconds = max(
    60,
    int(os.getenv("WORLD_BANK_AUTODRAIN_INTERVAL_SECONDS", "60")),
)

celery_app = Celery(
    "plasmaos",
    broker=broker_url,
    backend=result_backend,
    include=[
        "app.workers.tender_tasks",
        "app.workers.source_refresh_tasks",
        "app.workers.project_enrichment_tasks",
        "app.workers.hunter_tasks",
        "app.workers.communications_tasks",
        "app.workers.private_document_tasks",
        "app.workers.pursuit_analysis_tasks",
        "app.workers.cv_extraction_tasks",
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
        "publish-committed-notifications": {"task": "app.workers.communications_tasks.publish_notifications", "schedule": timedelta(seconds=10)},
        "dispatch-durable-broadcasts": {"task": "app.workers.communications_tasks.dispatch_broadcasts", "schedule": timedelta(seconds=10)},
        "dispatch-private-document-work": {
            "task": "app.workers.private_document_tasks.dispatch_private_documents",
            "schedule": timedelta(seconds=10),
        },
        "dispatch-pursuit-analysis-work": {
            "task": "app.workers.pursuit_analysis_tasks.dispatch_pursuit_analysis",
            "schedule": timedelta(seconds=10),
        },
        # R3 Task 4: SMTP e-mail (no-op while SMTP_HOST/SMTP_FROM are unset).
        "send-email-notifications": {
            "task": "app.workers.communications_tasks.send_emails",
            "schedule": timedelta(seconds=30),
        },
        # 08:00 Asia/Tashkent (UTC+5, no daylight saving) = 03:00 UTC.
        "stage-daily-opportunity-digests": {
            "task": "app.workers.communications_tasks.stage_daily_digests",
            "schedule": crontab(hour=3, minute=0),
        },
        # R3: CV draft extraction recovery (the document job also publishes directly).
        "dispatch-cv-extraction-work": {
            "task": "app.workers.cv_extraction_tasks.dispatch_cv_extraction",
            "schedule": timedelta(seconds=30),
        },
        "run-hunter-sweep-every-30-minutes": {
            "task": "app.workers.hunter_tasks.run_hunter_sweep",
            "schedule": crontab(minute="*/30"),
        },
        "dispatch-world-bank-project-enrichment-backlog": {
            "task": (
                "app.workers.project_enrichment_tasks."
                "dispatch_world_bank_project_enrichment_backlog"
            ),
            "schedule": timedelta(seconds=world_bank_autodrain_interval_seconds),
            "options": {
                "queue": "celery",
                "routing_key": "celery",
                "expires": world_bank_autodrain_interval_seconds,
            },
        },
    },
)

# Scheduled source refresh (D1-04): one entry per source in SOURCE_REFRESH_SCHEDULE.
# A malformed schedule raises here, so worker, Beat and API all fail at startup.
celery_app.conf.beat_schedule.update(
    build_beat_schedule(
        configured_source_refresh_schedule(),
        tick_seconds=schedule_tick_seconds(),
    )
)

celery_app.conf.task_queues = (
    Queue("celery", routing_key="celery"),
    Queue("ai_fast_queue", routing_key="ai_fast_queue"),
    Queue("heavy_dl_queue", routing_key="heavy_dl_queue"),
    Queue("private_documents", routing_key="private_documents"),
    Queue("pursuit_analysis", routing_key="pursuit_analysis"),
)

celery_app.conf.task_routes = {
    "app.workers.private_document_tasks.*": {
        "queue": "private_documents",
        "routing_key": "private_documents",
    },
    "app.workers.pursuit_analysis_tasks.*": {
        "queue": "pursuit_analysis",
        "routing_key": "pursuit_analysis",
    },
    "app.workers.cv_extraction_tasks.extract_cv_draft": {
        "queue": "pursuit_analysis",
        "routing_key": "pursuit_analysis",
    },
    "app.workers.source_refresh_tasks.refresh_tender_source": {
        "queue": "celery",
        "routing_key": "celery",
    },
    "app.workers.project_enrichment_tasks.enrich_world_bank_project": {
        "queue": "celery",
        "routing_key": "celery",
    },
    (
        "app.workers.project_enrichment_tasks."
        "dispatch_world_bank_project_enrichment_backlog"
    ): {
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
    "app.workers.tender_tasks.enrich_adb_document": {
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


# ---- Beat liveness (smoke.sh) ----------------------------------------------------------------------
# Beat dispatches publish_notifications every 10 s. When a worker starts it, the time is written to
# Redis, so "Beat dispatched and a worker received it" is directly observable without reading
# container logs. scripts/ops/smoke.sh fails when the timestamp is missing or 60 s old or more.
BEAT_HEARTBEAT_KEY = "plasma:beat:heartbeat"
BEAT_HEARTBEAT_TASK = "app.workers.communications_tasks.publish_notifications"
BEAT_HEARTBEAT_TTL_SECONDS = 3600


def record_beat_heartbeat(client=None, now: float | None = None) -> bool:
    """Write the receipt time of a Beat-dispatched task; never raises (liveness is best-effort)."""
    import time

    try:
        if client is None:
            from redis import Redis

            client = Redis.from_url(broker_url, socket_connect_timeout=2, socket_timeout=2)
        client.set(BEAT_HEARTBEAT_KEY, int(now if now is not None else time.time()), ex=BEAT_HEARTBEAT_TTL_SECONDS)
        return True
    except Exception:  # noqa: BLE001 - a liveness write must never fail the task
        logger.warning("beat_heartbeat_write_failed", exc_info=True)
        return False


@task_prerun.connect
def beat_heartbeat_on_receipt(sender=None, **_: object) -> None:
    if getattr(sender, "name", None) == BEAT_HEARTBEAT_TASK:
        record_beat_heartbeat()
