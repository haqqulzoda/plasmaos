"""Bounded Celery execution for World Bank Project enrichment."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.core.celery_app import celery_app
from app.db.session import AsyncSessionLocal, engine
from app.models.all_models import Project
from app.services.project_enrichment import (
    PROJECT_ENRICHMENT_ACTIVE_LEASE,
    WORLD_BANK_PROJECT_FRESHNESS,
    apply_world_bank_project_snapshot,
    mark_project_enrichment_failure,
)
from app.services.world_bank_projects import (
    WorldBankProjectSourceError,
    WorldBankProjectsClient,
    normalize_world_bank_project_record,
)


async def _execute_world_bank_project_enrichment(
    project_id: UUID,
    *,
    client: WorldBankProjectsClient | None = None,
) -> dict[str, Any]:
    """Fetch outside a transaction, then atomically merge one known Project."""
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Project).where(Project.id == project_id).with_for_update()
        )
        project = result.scalar_one_or_none()
        if project is None:
            return {
                "status": "failed",
                "failure_class": "project_not_found",
                "retryable": False,
                "project_id": str(project_id),
            }
        if project.source_system != "world_bank":
            return {
                "status": "failed",
                "failure_class": "unsupported_source",
                "retryable": False,
                "project_id": str(project_id),
            }
        if (
            project.enrichment_status == "successful"
            and project.last_enriched_at is not None
            and project.last_enriched_at >= now - WORLD_BANK_PROJECT_FRESHNESS
        ):
            return {
                "status": "successful",
                "reused": True,
                "retryable": False,
                "project_id": str(project_id),
            }
        if (
            project.enrichment_status == "running"
            and project.enrichment_last_attempted_at is not None
            and project.enrichment_last_attempted_at
            >= now - PROJECT_ENRICHMENT_ACTIVE_LEASE
        ):
            return {
                "status": "running",
                "reused": True,
                "retryable": False,
                "project_id": str(project_id),
            }
        external_project_id = project.external_project_id
        project.enrichment_status = "running"
        project.enrichment_last_attempted_at = now
        project.enrichment_failure_class = None
        await db.commit()

        source_client = client or WorldBankProjectsClient()
        try:
            record = await source_client.fetch_project(external_project_id)
            snapshot = normalize_world_bank_project_record(
                external_project_id,
                record,
                retrieved_at=datetime.now(timezone.utc),
            )
            merged = await apply_world_bank_project_snapshot(
                db,
                project_id=project_id,
                snapshot=snapshot,
            )
            await db.commit()
            return {
                "status": merged.status,
                "failure_class": None,
                "retryable": False,
                "project_id": str(project_id),
                "roles_created": merged.roles_created,
                "roles_updated": merged.roles_updated,
                "roles_ended": merged.roles_ended,
            }
        except WorldBankProjectSourceError as exc:
            await db.rollback()
            await mark_project_enrichment_failure(
                db,
                project_id=project_id,
                status=exc.status,
                failure_class=exc.failure_class,
            )
            await db.commit()
            return {
                "status": exc.status,
                "failure_class": exc.failure_class,
                "retryable": exc.retryable,
                "project_id": str(project_id),
            }
        except Exception as exc:
            await db.rollback()
            await mark_project_enrichment_failure(
                db,
                project_id=project_id,
                status="failed",
                failure_class=type(exc).__name__,
            )
            await db.commit()
            return {
                "status": "failed",
                "failure_class": type(exc).__name__,
                "retryable": False,
                "project_id": str(project_id),
            }


@celery_app.task(
    name="app.workers.project_enrichment_tasks.enrich_world_bank_project",
    bind=True,
    max_retries=3,
    rate_limit="30/m",
    soft_time_limit=60,
    time_limit=90,
)
def enrich_world_bank_project_task(self: Any, project_id: str) -> dict[str, Any]:
    """Retry only classified transient official-source failures."""

    async def run_and_dispose() -> dict[str, Any]:
        try:
            return await _execute_world_bank_project_enrichment(UUID(project_id))
        finally:
            await engine.dispose()

    result = asyncio.run(run_and_dispose())
    if result.get("retryable"):
        countdown = min(300, 30 * (2 ** int(self.request.retries or 0)))
        raise self.retry(
            exc=RuntimeError(str(result.get("failure_class") or "retryable_failure")),
            countdown=countdown,
        )
    return result
