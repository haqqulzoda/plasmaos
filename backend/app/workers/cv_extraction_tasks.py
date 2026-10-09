"""R3 Task 3: CV draft extraction on the pursuit analysis (model) queue."""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from app.core.celery_app import celery_app
from app.db.session import AsyncSessionLocal, engine
from app.services.cv_library import due_cv_draft_ids, process_cv_draft


logger = logging.getLogger(__name__)


def dispatch_cv_draft_ids(draft_ids: list[UUID] | list[str] | tuple[UUID, ...]) -> int:
    """Best-effort publish; the committed draft row and the Beat sweep remain recovery authority."""
    published = 0
    for draft_id in draft_ids:
        try:
            extract_cv_draft.apply_async(args=[str(draft_id)], queue="pursuit_analysis", routing_key="pursuit_analysis")
            published += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("cv_draft_publish_deferred draft_id=%s error=%s", draft_id, type(exc).__name__)
    return published


@celery_app.task(name="app.workers.cv_extraction_tasks.extract_cv_draft", max_retries=0, acks_late=True)
def extract_cv_draft(draft_id: str) -> str:
    async def execute() -> str:
        try:
            async with AsyncSessionLocal() as db:
                return await process_cv_draft(db, UUID(draft_id))
        finally:
            await engine.dispose()

    return asyncio.run(execute())


@celery_app.task(name="app.workers.cv_extraction_tasks.dispatch_cv_extraction")
def dispatch_cv_extraction() -> int:
    async def due() -> list[UUID]:
        try:
            async with AsyncSessionLocal() as db:
                return await due_cv_draft_ids(db)
        finally:
            await engine.dispose()

    draft_ids = asyncio.run(due())
    return dispatch_cv_draft_ids(draft_ids)
