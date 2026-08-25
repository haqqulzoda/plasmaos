"""Durable background execution for source-wide tender refresh jobs."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from time import monotonic
from typing import Any
from uuid import UUID

from app.core.celery_app import celery_app
from app.db.session import AsyncSessionLocal, engine
from app.models.all_models import SourceRefreshJob
from app.services.tender_sources.diagnostics import (
    connector_failure_details,
    safe_failure_message,
)

logger = logging.getLogger(__name__)

TERMINAL_SOURCE_REFRESH_STATUSES = {
    "completed",
    "partial",
    "source_unavailable",
    "failed",
}
SOURCE_LABELS = {
    "uzex": "UzEx",
    "world_bank": "World Bank",
    "adb": "ADB",
    "giz": "GIZ",
    "ebrd": "EBRD",
}


def _result_count(result: Any, *names: str) -> int:
    for name in names:
        value = getattr(result, name, None)
        if value is not None:
            return int(value or 0)
    return 0


async def _execute_source_refresh(source_system: str, job_id: UUID) -> dict[str, Any]:
    """Execute one idempotent source job and persist its terminal state."""
    # Import before the first ORM query. Besides providing orchestration, the API
    # module loads the complete model registry used by all_models relationships.
    # The import remains lazy to avoid a module cycle during API/task startup.
    from app.api.endpoints.tenders import (
        _normalized_source_result,
        _run_source_refresh,
    )

    started = monotonic()
    async with AsyncSessionLocal() as db:
        job = await db.get(SourceRefreshJob, job_id)
        if job is None:
            raise ValueError("Source refresh job not found")
        if job.source_system != source_system:
            job.status = "failed"
            job.failed_count = 1
            job.message = "Refresh failed during dispatch validation."
            job.completed_at = datetime.now(timezone.utc)
            await db.commit()
            raise ValueError("Source refresh job/source mismatch")
        if job.status in TERMINAL_SOURCE_REFRESH_STATUSES:
            return {
                "status": job.status,
                "source_system": source_system,
                "job_id": str(job_id),
                "reused": True,
            }

        job.status = "running"
        job.started_at = job.started_at or datetime.now(timezone.utc)
        job.message = "Refreshing."
        await db.commit()

        result: Any | None = None
        failure_class: str | None = None
        retryable: bool | None = None
        fallback_used = False
        failure_stage: str | None = None
        try:
            result = await _run_source_refresh(source_system, db)
            final_status, created, updated, failed, result_message = (
                _normalized_source_result(result)
            )
            failure_class = getattr(result, "failure_class", None)
            failure_stage = getattr(result, "failure_stage", None)
            retryable = getattr(result, "retryable", None)
            fallback_used = bool(getattr(result, "fallback_used", False))
        except Exception as exc:
            await db.rollback()
            details = connector_failure_details(exc)
            final_status = details.status
            created, updated, failed = 0, 0, 1
            failure_class = details.failure_class
            failure_stage = "worker_execution"
            retryable = details.retryable
            result_message = safe_failure_message(
                SOURCE_LABELS.get(source_system, source_system),
                "worker execution",
                exc,
            )
            logger.exception(
                "source_refresh_worker_exception source_system=%s job_id=%s "
                "stage=worker_execution failure_class=%s http_status=%s retryable=%s",
                source_system,
                job_id,
                details.failure_class,
                details.http_status,
                str(details.retryable).lower(),
            )

        refreshed_job = await db.get(SourceRefreshJob, job_id)
        if refreshed_job is None:
            raise RuntimeError("Source refresh job disappeared")
        refreshed_job.status = final_status
        refreshed_job.created_count = created
        refreshed_job.updated_count = updated
        refreshed_job.failed_count = failed
        refreshed_job.fetched_count = _result_count(result, "fetched_count", "fetched")
        refreshed_job.skipped_count = _result_count(result, "skipped_count", "skipped")
        refreshed_job.rejected_count = _result_count(result, "rejected_count") or (
            refreshed_job.skipped_count + failed
        )
        refreshed_job.fallback_used = fallback_used
        refreshed_job.skip_reasons = dict(getattr(result, "skip_reasons", {}) or {})
        refreshed_job.failure_class = failure_class
        refreshed_job.failure_stage = failure_stage
        refreshed_job.retryable = retryable
        refreshed_job.elapsed_ms = getattr(result, "elapsed_ms", None)
        refreshed_job.source_newest_published_at = getattr(
            result,
            "source_newest_published_at",
            None,
        )
        refreshed_job.source_oldest_published_at = getattr(
            result,
            "source_oldest_published_at",
            None,
        )
        refreshed_job.execution_health = getattr(result, "execution_health", None)
        refreshed_job.freshness_health = getattr(result, "freshness_health", None)
        refreshed_job.coverage_health = getattr(result, "coverage_health", None)
        refreshed_job.message = result_message
        refreshed_job.completed_at = datetime.now(timezone.utc)
        await db.commit()

        fetched = refreshed_job.fetched_count
        skipped = refreshed_job.skipped_count
        persisted = created + updated
        rejected = skipped + failed
        accepted = max(0, fetched - rejected) if fetched else persisted
        elapsed_ms = int((monotonic() - started) * 1000)
        logger.info(
            "source_refresh_summary source_system=%s job_id=%s stage=complete "
            "status=%s failure_class=%s retryable=%s rows_fetched=%s "
            "rows_accepted=%s rows_rejected=%s rows_persisted=%s "
            "fallback_used=%s elapsed_ms=%s",
            source_system,
            job_id,
            final_status,
            failure_class,
            retryable,
            fetched,
            accepted,
            rejected,
            persisted,
            str(fallback_used).lower(),
            elapsed_ms,
        )
        return {
            "status": final_status,
            "source_system": source_system,
            "job_id": str(job_id),
            "rows_fetched": fetched,
            "rows_accepted": accepted,
            "rows_rejected": rejected,
            "rows_persisted": persisted,
            "fallback_used": fallback_used,
            "elapsed_ms": elapsed_ms,
        }


@celery_app.task(name="app.workers.source_refresh_tasks.refresh_tender_source", bind=True)
def refresh_tender_source(self: Any, source_system: str, job_id: str) -> dict[str, Any]:
    """Celery entrypoint for a source refresh job."""
    async def run_and_dispose() -> dict[str, Any]:
        try:
            return await _execute_source_refresh(source_system, UUID(job_id))
        finally:
            await engine.dispose()

    return asyncio.run(run_and_dispose())
