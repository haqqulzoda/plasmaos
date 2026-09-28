"""Dedicated durable worker and recovery dispatcher for private documents."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import logging
from uuid import UUID

from sqlalchemy import or_, select

from app.core.celery_app import celery_app
from app.db.session import AsyncSessionLocal, engine
from app.models.base import DocumentProcessingState
from app.models.private_documents import DocumentProcessingJob
from app.services.private_documents import process_document_job


logger = logging.getLogger(__name__)


async def _process(job_id: UUID):
    try:
        async with AsyncSessionLocal() as db:
            return await process_document_job(db, job_id)
    finally:
        await engine.dispose()


@celery_app.task(
    bind=True,
    name="app.workers.private_document_tasks.process_private_document",
    max_retries=2,
    acks_late=True,
)
def process_private_document(self, job_id: str):
    try:
        return asyncio.run(_process(UUID(job_id)))
    except Exception as exc:
        logger.warning(
            "private_document_worker_retry job_id=%s error_type=%s",
            job_id,
            type(exc).__name__,
        )
        raise self.retry(countdown=30) from None


def dispatch_job_ids(job_ids: list[UUID] | tuple[UUID, ...]) -> int:
    """Best-effort broker publication after commit; Beat owns recovery."""
    published = 0
    for job_id in job_ids:
        try:
            process_private_document.apply_async(
                args=[str(job_id)],
                queue="private_documents",
                routing_key="private_documents",
            )
            published += 1
        except Exception as exc:
            logger.warning(
                "private_document_dispatch_deferred job_id=%s error_type=%s",
                job_id,
                type(exc).__name__,
            )
    return published


async def dispatch_pending_private_documents() -> dict[str, int]:
    """Lease committed or abandoned work; failed publication expires for retry."""
    now = datetime.now(timezone.utc)
    try:
        async with AsyncSessionLocal() as db:
            jobs = list(
                (
                    await db.scalars(
                        select(DocumentProcessingJob)
                        .where(
                            DocumentProcessingJob.next_dispatch_at <= now,
                            or_(
                                DocumentProcessingJob.state == DocumentProcessingState.QUEUED,
                                (
                                    DocumentProcessingJob.state.in_(
                                        [
                                            DocumentProcessingState.CHECKING,
                                            DocumentProcessingState.EXTRACTING,
                                        ]
                                    )
                                    & (
                                        DocumentProcessingJob.lease_until.is_(None)
                                        | (DocumentProcessingJob.lease_until <= now)
                                    )
                                ),
                            ),
                        )
                        .order_by(DocumentProcessingJob.next_dispatch_at, DocumentProcessingJob.id)
                        .limit(25)
                        .with_for_update(skip_locked=True)
                    )
                ).all()
            )
            for job in jobs:
                job.state = DocumentProcessingState.QUEUED
                job.dispatch_attempt_count += 1
                job.next_dispatch_at = now + timedelta(seconds=60)
                job.lease_until = None
            ids = [job.id for job in jobs]
            await db.commit()
        published = dispatch_job_ids(ids)
        return {"leased": len(ids), "published": published}
    finally:
        await engine.dispose()


@celery_app.task(name="app.workers.private_document_tasks.dispatch_private_documents")
def dispatch_private_documents():
    return asyncio.run(dispatch_pending_private_documents())
