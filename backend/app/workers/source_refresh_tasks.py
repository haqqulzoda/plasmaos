"""Durable background execution for source-wide tender refresh jobs."""

from __future__ import annotations

import asyncio
import logging
from time import monotonic
from typing import Any
from uuid import UUID, uuid4

from app.core.celery_app import celery_app
from app.db.session import AsyncSessionLocal, engine
from app.models.all_models import SourceRefreshJob
from app.services.source_refresh_jobs import (
    SourceRefreshClaimStatus,
    claim_source_refresh_job,
    complete_source_refresh_job,
    renew_source_refresh_lease,
    source_refresh_heartbeat_seconds,
)
from app.services.tender_sources.diagnostics import (
    connector_failure_details,
    safe_failure_message,
)

logger = logging.getLogger(__name__)

def _result_count(result: Any, *names: str) -> int:
    for name in names:
        value = getattr(result, name, None)
        if value is not None:
            return int(value or 0)
    return 0


async def _execute_source_refresh(source_system: str, job_id: UUID) -> dict[str, Any]:
    """Execute one job only while this delivery owns its renewable lease."""
    # Lazy import avoids the API/task module cycle while retaining the existing
    # worker-only connector executors.
    from app.api.endpoints.tenders import _run_source_refresh
    from app.services.source_registry import (
        SourceExecutionResult,
        adapt_execution_result,
        get_source_definition,
    )

    attempt_id = uuid4()
    started = monotonic()
    async with AsyncSessionLocal() as claim_db:
        claim = await claim_source_refresh_job(
            claim_db,
            job_id=job_id,
            source_system=source_system,
            lease_owner=attempt_id,
        )
    if claim.status == SourceRefreshClaimStatus.MISSING:
        raise ValueError("Source refresh job not found")
    if claim.status == SourceRefreshClaimStatus.SOURCE_MISMATCH:
        raise ValueError("Source refresh job/source mismatch")
    if claim.status == SourceRefreshClaimStatus.TERMINAL:
        return {
            "status": claim.job_status,
            "source_system": source_system,
            "job_id": str(job_id),
            "reused": True,
        }
    if claim.status == SourceRefreshClaimStatus.BUSY:
        return {
            "status": "running",
            "source_system": source_system,
            "job_id": str(job_id),
            "reused": True,
            "lease_busy": True,
        }

    stop_heartbeat = asyncio.Event()
    lease_lost = asyncio.Event()

    async def heartbeat() -> None:
        cadence = source_refresh_heartbeat_seconds()
        while not stop_heartbeat.is_set():
            try:
                await asyncio.wait_for(stop_heartbeat.wait(), timeout=cadence)
                return
            except asyncio.TimeoutError:
                pass
            try:
                async with AsyncSessionLocal() as heartbeat_db:
                    renewed = await renew_source_refresh_lease(
                        heartbeat_db,
                        job_id=job_id,
                        lease_owner=attempt_id,
                    )
            except Exception:
                logger.exception(
                    "source_refresh_heartbeat_failed source_system=%s job_id=%s "
                    "attempt_id=%s",
                    source_system,
                    job_id,
                    attempt_id,
                )
                renewed = False
            if not renewed:
                lease_lost.set()
                return

    async def execute() -> Any:
        async with AsyncSessionLocal() as execution_db:
            job = await execution_db.get(SourceRefreshJob, job_id)
            if job is None:
                raise ValueError("Source refresh job disappeared")
            try:
                raw_result = await _run_source_refresh(
                    source_system, execution_db,
                    options=dict(getattr(job, "options_json", {}) or {}),
                )
                if isinstance(raw_result, SourceExecutionResult):
                    return raw_result
                return adapt_execution_result(source_system, raw_result)
            except BaseException:
                await execution_db.rollback()
                raise

    result: Any | None = None
    failure_class: str | None = None
    failure_stage: str | None = None
    retryable: bool | None = None
    fallback_used = False
    heartbeat_task = asyncio.create_task(heartbeat())
    execution_task = asyncio.create_task(execute())
    try:
        done, _pending = await asyncio.wait(
            {execution_task, heartbeat_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if heartbeat_task in done and lease_lost.is_set() and not execution_task.done():
            execution_task.cancel()
            await asyncio.gather(execution_task, return_exceptions=True)
        else:
            result = await execution_task
    except Exception as exc:
        details = connector_failure_details(exc)
        final_status = details.status
        created, updated, failed = 0, 0, 1
        failure_class = details.failure_class
        failure_stage = "worker_execution"
        retryable = details.retryable
        result_message = safe_failure_message(
            get_source_definition(source_system).display_name,
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
    else:
        if not lease_lost.is_set():
            final_status = result.status
            created = result.created_count
            updated = result.updated_count
            failed = result.failed_count
            result_message = result.message
            failure_class = getattr(result, "failure_class", None)
            failure_stage = getattr(result, "failure_stage", None)
            retryable = getattr(result, "retryable", None)
            fallback_used = bool(getattr(result, "fallback_used", False))
    finally:
        stop_heartbeat.set()
        await asyncio.gather(heartbeat_task, return_exceptions=True)

    if lease_lost.is_set():
        logger.warning(
            "source_refresh_lease_lost source_system=%s job_id=%s attempt_id=%s",
            source_system,
            job_id,
            attempt_id,
        )
        return {
            "status": "superseded",
            "source_system": source_system,
            "job_id": str(job_id),
            "reused": True,
        }

    fetched = _result_count(result, "fetched_count", "fetched")
    skipped = _result_count(result, "skipped_count", "skipped")
    unchanged = _result_count(result, "unchanged_count", "unchanged")
    rejected = (
        _result_count(result, "rejected_count")
        if result is not None and hasattr(result, "rejected_count")
        else skipped + failed
    )
    documents_discovered = _result_count(
        result,
        "documents_discovered_count",
        "attachment_count",
        "attachments_discovered",
    )
    documents_queued = _result_count(result, "documents_queued_count")
    terminal_values = {
        "created_count": created,
        "updated_count": updated,
        "unchanged_count": unchanged,
        "fetched_count": fetched,
        "skipped_count": skipped,
        "rejected_count": rejected,
        "failed_count": failed,
        "documents_discovered_count": documents_discovered,
        "documents_queued_count": documents_queued,
        "fallback_used": fallback_used,
        "skip_reasons": dict(getattr(result, "skip_reasons", {}) or {}),
        "failure_class": failure_class,
        "failure_stage": failure_stage,
        "retryable": retryable,
        "elapsed_ms": (
            getattr(result, "elapsed_ms", None)
            if getattr(result, "elapsed_ms", None) is not None
            else int((monotonic() - started) * 1000)
        ),
        "fetch_elapsed_ms": getattr(result, "fetch_elapsed_ms", None),
        "normalize_elapsed_ms": getattr(result, "normalize_elapsed_ms", None),
        "persist_elapsed_ms": getattr(result, "persist_elapsed_ms", None),
        "document_dispatch_elapsed_ms": getattr(result, "document_dispatch_elapsed_ms", None),
        "http_request_count": getattr(result, "http_request_count", None),
        "http_retry_count": getattr(result, "http_retry_count", None),
        "http_failure_count": getattr(result, "http_failure_count", None),
        "source_newest_published_at": getattr(
            result, "source_newest_published_at", None
        ),
        "source_oldest_published_at": getattr(
            result, "source_oldest_published_at", None
        ),
        "execution_health": getattr(result, "execution_health", None),
        "freshness_health": getattr(result, "freshness_health", None),
        "coverage_health": getattr(result, "coverage_health", None),
        "message": result_message,
    }
    async with AsyncSessionLocal() as terminal_db:
        terminal_written = await complete_source_refresh_job(
            terminal_db,
            job_id=job_id,
            lease_owner=attempt_id,
            terminal_status=final_status,
            result_values=terminal_values,
        )
    if not terminal_written:
        return {
            "status": "superseded",
            "source_system": source_system,
            "job_id": str(job_id),
            "reused": True,
        }

    persisted = created + updated
    accepted = max(0, fetched - rejected) if fetched else persisted + unchanged
    elapsed_ms = int((monotonic() - started) * 1000)
    logger.info(
        "source_refresh_summary source_system=%s job_id=%s attempt_id=%s "
        "stage=complete status=%s failure_class=%s retryable=%s rows_fetched=%s "
        "rows_accepted=%s rows_rejected=%s rows_persisted=%s "
        "rows_unchanged=%s documents_discovered=%s documents_queued=%s "
        "fallback_used=%s elapsed_ms=%s",
        source_system,
        job_id,
        attempt_id,
        final_status,
        failure_class,
        retryable,
        fetched,
        accepted,
        rejected,
        persisted,
        unchanged,
        documents_discovered,
        documents_queued,
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
        "rows_unchanged": unchanged,
        "documents_discovered": documents_discovered,
        "documents_queued": documents_queued,
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
