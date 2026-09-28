"""Dedicated durable W4 pursuit analysis queue."""

from __future__ import annotations

import asyncio
import logging
import socket
from uuid import UUID

from app.core.celery_app import celery_app
from app.db.session import AsyncSessionLocal, engine
from app.services.pursuit_analysis import due_analysis_run_ids, process_analysis_run, renew_analysis_lease


logger = logging.getLogger(__name__)


def dispatch_run_ids(run_ids: list[UUID] | tuple[UUID, ...]) -> None:
    """Best-effort publish; the committed database job remains recovery authority."""
    for run_id in run_ids:
        try:
            analyze_pursuit.apply_async(args=[str(run_id)], queue="pursuit_analysis")
        except Exception as exc:  # broker recovery is handled by the beat sweep
            logger.warning("pursuit_analysis_publish_deferred run_id=%s error=%s", run_id, type(exc).__name__)


@celery_app.task(name="app.workers.pursuit_analysis_tasks.analyze_pursuit", bind=True, max_retries=0)
def analyze_pursuit(self, run_id: str) -> None:
    worker_id = f"{socket.gethostname()}:{self.request.id or 'direct'}"

    async def execute() -> None:
        try:
            run_uuid = UUID(run_id)
            stopped = asyncio.Event()

            async def heartbeat() -> None:
                while not stopped.is_set():
                    try:
                        await asyncio.wait_for(stopped.wait(), timeout=60)
                    except TimeoutError:
                        async with AsyncSessionLocal() as heartbeat_db:
                            if not await renew_analysis_lease(
                                heartbeat_db, run_uuid, worker_id=worker_id
                            ):
                                return

            pulse = asyncio.create_task(heartbeat())
            try:
                async with AsyncSessionLocal() as db:
                    await process_analysis_run(db, run_uuid, worker_id=worker_id)
            finally:
                stopped.set()
                await pulse
        finally:
            # Each Celery task creates a new event loop with asyncio.run().
            # Do not retain asyncpg pooled connections bound to the closed loop.
            await engine.dispose()

    asyncio.run(execute())


@celery_app.task(name="app.workers.pursuit_analysis_tasks.dispatch_pursuit_analysis")
def dispatch_pursuit_analysis() -> int:
    async def due() -> list[UUID]:
        try:
            async with AsyncSessionLocal() as db:
                return await due_analysis_run_ids(db)
        finally:
            await engine.dispose()

    run_ids = asyncio.run(due())
    dispatch_run_ids(run_ids)
    return len(run_ids)
