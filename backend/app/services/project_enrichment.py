"""Project enrichment merge, role reconciliation, and bounded queue claiming."""

from __future__ import annotations

import hashlib
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, case, exists, func, not_, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.all_models import Project, ProjectRoleAssignment, TenderProject
from app.services.world_bank_projects import WorldBankProjectSnapshot


logger = logging.getLogger(__name__)
WORLD_BANK_PROJECT_FRESHNESS = timedelta(days=7)
PROJECT_ENRICHMENT_ACTIVE_LEASE = timedelta(minutes=30)
WORLD_BANK_ENRICHMENT_BATCH_SIZE = 50
WORLD_BANK_AUTODRAIN_BATCH_SIZE = max(
    1,
    min(
        int(os.getenv("WORLD_BANK_AUTODRAIN_BATCH_SIZE", "25")),
        30,
        WORLD_BANK_ENRICHMENT_BATCH_SIZE,
    ),
)
WORLD_BANK_ENRICHMENT_RETRY_BACKOFF = timedelta(
    seconds=max(
        60,
        int(os.getenv("WORLD_BANK_ENRICHMENT_RETRY_BACKOFF_SECONDS", "900")),
    )
)
WORLD_BANK_ENRICHMENT_STATUS_PRIORITY = {
    "never_attempted": 0,
    "stale": 1,
    "partial": 2,
    "source_unavailable": 3,
    "queued": 4,
    "running": 4,
    "failed": 5,
}


@dataclass(frozen=True)
class ProjectEnrichmentResult:
    project_id: UUID
    status: str
    roles_created: int
    roles_updated: int
    roles_ended: int


@dataclass(frozen=True)
class ProjectEnrichmentDispatchResult:
    claimed: int
    enqueued: int
    dispatch_failed: int
    eligible_found: int = 0
    skipped_active_lease: int = 0
    duration_ms: int = 0


@dataclass(frozen=True)
class WorldBankProjectBacklogSnapshot:
    total_world_bank_projects: int
    fresh_success: int
    partial: int
    never_attempted: int
    eligible_now: int
    queued: int
    running: int
    retry_wait: int
    failed_terminal: int
    stale: int
    expired_lease: int
    active_lease: int


def effective_project_enrichment_status(
    project: Project,
    *,
    now: datetime | None = None,
) -> str:
    """Expose successful data older than the freshness window as stale."""
    observed_at = now or datetime.now(timezone.utc)
    if (
        project.enrichment_status == "successful"
        and project.last_enriched_at is not None
        and project.last_enriched_at < observed_at - WORLD_BANK_PROJECT_FRESHNESS
    ):
        return "stale"
    return project.enrichment_status


def project_role_assignment_key(
    *,
    external_project_id: str,
    source_system: str,
    native_role: str,
    display_name: str,
    source_person_id: str | None,
) -> str:
    """Hash exact authoritative assignment fields; no fuzzy person identity."""
    person_identity = (
        f"source_person_id:{source_person_id}"
        if source_person_id
        else f"display_name:{display_name}"
    )
    material = "\0".join(
        (
            source_system,
            external_project_id,
            native_role,
            person_identity,
        )
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _valid_role_provenance(provenance: dict[str, Any]) -> bool:
    required = {
        "source_system",
        "source_endpoint",
        "external_project_id",
        "source_field",
        "source_value",
        "retrieved_at",
    }
    return required.issubset(provenance) and all(
        provenance.get(field) not in (None, "") for field in required
    )


async def _upsert_role_assignment(
    db: AsyncSession,
    *,
    project: Project,
    snapshot: WorldBankProjectSnapshot,
    role: Any,
) -> tuple[ProjectRoleAssignment, bool]:
    if not _valid_role_provenance(role.provenance):
        raise ValueError("Project role assignment lacks required authoritative provenance")
    assignment_key = project_role_assignment_key(
        external_project_id=project.external_project_id,
        source_system="world_bank",
        native_role=role.native_role,
        display_name=role.display_name,
        source_person_id=role.source_person_id,
    )
    assignment_id = uuid4()
    statement = (
        insert(ProjectRoleAssignment)
        .values(
            id=assignment_id,
            project_id=project.id,
            source_system="world_bank",
            assignment_key=assignment_key,
            source_person_id=role.source_person_id,
            display_name=role.display_name,
            native_role=role.native_role,
            canonical_role=role.canonical_role,
            email=role.email,
            phone=role.phone,
            source_url=snapshot.source_url,
            source_document_id=role.source_document_id,
            provenance=role.provenance,
            is_current=True,
            first_observed_at=snapshot.retrieved_at,
            last_observed_at=snapshot.retrieved_at,
            ended_at=None,
        )
        .on_conflict_do_nothing(constraint="uq_project_role_assignments_identity")
        .returning(ProjectRoleAssignment.id)
    )
    inserted_id = (await db.execute(statement)).scalar_one_or_none()
    result = await db.execute(
        select(ProjectRoleAssignment)
        .where(
            ProjectRoleAssignment.project_id == project.id,
            ProjectRoleAssignment.source_system == "world_bank",
            ProjectRoleAssignment.assignment_key == assignment_key,
        )
        .with_for_update()
    )
    assignment = result.scalar_one()
    assignment.last_observed_at = snapshot.retrieved_at
    assignment.is_current = True
    assignment.ended_at = None
    assignment.display_name = role.display_name
    assignment.native_role = role.native_role
    assignment.canonical_role = role.canonical_role
    assignment.source_person_id = role.source_person_id
    assignment.email = role.email
    assignment.phone = role.phone
    assignment.source_url = snapshot.source_url
    assignment.source_document_id = role.source_document_id
    assignment.provenance = role.provenance
    return assignment, inserted_id is not None


async def apply_world_bank_project_snapshot(
    db: AsyncSession,
    *,
    project_id: UUID,
    snapshot: WorldBankProjectSnapshot,
) -> ProjectEnrichmentResult:
    """Conservatively merge metadata and reconcile authoritative role history."""
    result = await db.execute(
        select(Project).where(Project.id == project_id).with_for_update()
    )
    project = result.scalar_one()
    if project.source_system != "world_bank":
        raise ValueError("World Bank enrichment cannot mutate a non-World Bank Project")
    if project.external_project_id != snapshot.external_project_id:
        raise ValueError("World Bank enrichment snapshot identity mismatch")

    for field_name in (
        "name",
        "country",
        "region",
        "project_status",
        "borrower",
        "implementing_agencies",
        "source_url",
    ):
        value = getattr(snapshot, field_name)
        if value not in (None, "", []):
            setattr(project, field_name, value)
    if snapshot.approval_date is not None:
        project.approval_date = snapshot.approval_date
    if snapshot.closing_date is not None:
        project.closing_date = snapshot.closing_date

    existing_provenance = dict(project.raw_provenance or {})
    existing_provenance["world_bank_project_enrichment"] = {
        "source_system": "world_bank",
        "source_endpoint": "https://search.worldbank.org/api/v2/projects",
        "external_project_id": snapshot.external_project_id,
        "source_url": snapshot.source_url,
        "retrieved_at": snapshot.retrieved_at.isoformat(),
        "source_update_time": (
            snapshot.source_updated_at.isoformat()
            if snapshot.source_updated_at is not None
            else None
        ),
        "fields_obtained": list(snapshot.fields_obtained),
        "fields_missing": list(snapshot.fields_missing),
        "raw_record": snapshot.raw_record,
    }
    project.raw_provenance = existing_provenance
    project.last_enriched_at = snapshot.retrieved_at
    project.enrichment_source_updated_at = snapshot.source_updated_at
    project.enrichment_fields_obtained = list(snapshot.fields_obtained)
    project.enrichment_fields_missing = list(snapshot.fields_missing)

    current_result = await db.execute(
        select(ProjectRoleAssignment)
        .where(
            ProjectRoleAssignment.project_id == project.id,
            ProjectRoleAssignment.source_system == "world_bank",
            ProjectRoleAssignment.is_current.is_(True),
        )
        .with_for_update()
    )
    current_assignments = current_result.scalars().all()
    observed_keys: set[str] = set()
    roles_created = 0
    roles_updated = 0
    for role in snapshot.roles:
        assignment, created = await _upsert_role_assignment(
            db,
            project=project,
            snapshot=snapshot,
            role=role,
        )
        observed_keys.add(assignment.assignment_key)
        roles_created += int(created)
        roles_updated += int(not created)

    roles_ended = 0
    if snapshot.roles_complete:
        for assignment in current_assignments:
            if assignment.assignment_key in observed_keys:
                continue
            assignment.is_current = False
            assignment.ended_at = snapshot.retrieved_at
            roles_ended += 1

    project.enrichment_status = (
        "successful" if snapshot.roles_complete else "partial"
    )
    project.enrichment_failure_class = (
        None if snapshot.roles_complete else "leadership_roster_incomplete"
    )
    return ProjectEnrichmentResult(
        project_id=project.id,
        status=project.enrichment_status,
        roles_created=roles_created,
        roles_updated=roles_updated,
        roles_ended=roles_ended,
    )


async def mark_project_enrichment_failure(
    db: AsyncSession,
    *,
    project_id: UUID,
    status: str,
    failure_class: str,
) -> None:
    result = await db.execute(
        select(Project).where(Project.id == project_id).with_for_update()
    )
    project = result.scalar_one_or_none()
    if project is None:
        return
    project.enrichment_status = status
    project.enrichment_failure_class = failure_class[:100]


def _world_bank_enrichment_predicates(
    observed_at: datetime,
) -> dict[str, Any]:
    """Return the single SQL eligibility contract shared by claims and metrics."""
    stale_before = observed_at - WORLD_BANK_PROJECT_FRESHNESS
    active_after = observed_at - PROJECT_ENRICHMENT_ACTIVE_LEASE
    retry_after = observed_at - WORLD_BANK_ENRICHMENT_RETRY_BACKOFF
    linked = exists(
        select(TenderProject.id).where(TenderProject.project_id == Project.id)
    )
    never_attempted = Project.enrichment_status == "never_attempted"
    stale_due = or_(
        Project.enrichment_status == "stale",
        and_(
            Project.enrichment_status.in_(("successful", "partial")),
            or_(
                Project.last_enriched_at.is_(None),
                Project.last_enriched_at < stale_before,
            ),
        ),
    )
    retryable_failure = or_(
        Project.enrichment_status == "source_unavailable",
        and_(
            Project.enrichment_status == "failed",
            Project.enrichment_failure_class == "dispatch_failure",
        ),
    )
    retry_due = and_(
        retryable_failure,
        or_(
            Project.enrichment_last_attempted_at.is_(None),
            Project.enrichment_last_attempted_at < retry_after,
        ),
    )
    retry_wait = and_(
        retryable_failure,
        Project.enrichment_last_attempted_at.is_not(None),
        Project.enrichment_last_attempted_at >= retry_after,
    )
    active_lease = and_(
        Project.enrichment_status.in_(("queued", "running")),
        Project.enrichment_last_attempted_at.is_not(None),
        Project.enrichment_last_attempted_at >= active_after,
    )
    expired_lease = and_(
        Project.enrichment_status.in_(("queued", "running")),
        or_(
            Project.enrichment_last_attempted_at.is_(None),
            Project.enrichment_last_attempted_at < active_after,
        ),
    )
    eligible = and_(
        linked,
        or_(never_attempted, stale_due, retry_due, expired_lease),
        not_(active_lease),
    )
    return {
        "linked": linked,
        "never_attempted": never_attempted,
        "stale_due": stale_due,
        "retryable_failure": retryable_failure,
        "retry_due": retry_due,
        "retry_wait": retry_wait,
        "active_lease": active_lease,
        "expired_lease": expired_lease,
        "eligible": eligible,
        "fresh_success": and_(
            Project.enrichment_status == "successful",
            Project.last_enriched_at.is_not(None),
            Project.last_enriched_at >= stale_before,
        ),
        "failed_terminal": and_(
            Project.enrichment_status == "failed",
            or_(
                Project.enrichment_failure_class.is_(None),
                Project.enrichment_failure_class != "dispatch_failure",
            ),
        ),
    }


async def world_bank_project_backlog_snapshot(
    db: AsyncSession,
    *,
    now: datetime | None = None,
) -> WorldBankProjectBacklogSnapshot:
    """Return read-only aggregate backlog diagnostics without Project data."""
    observed_at = now or datetime.now(timezone.utc)
    predicates = _world_bank_enrichment_predicates(observed_at)
    count = func.count(Project.id)
    row = (
        await db.execute(
            select(
                count.label("total_world_bank_projects"),
                count.filter(predicates["fresh_success"]).label("fresh_success"),
                count.filter(Project.enrichment_status == "partial").label("partial"),
                count.filter(predicates["never_attempted"]).label("never_attempted"),
                count.filter(predicates["eligible"]).label("eligible_now"),
                count.filter(Project.enrichment_status == "queued").label("queued"),
                count.filter(Project.enrichment_status == "running").label("running"),
                count.filter(predicates["retry_wait"]).label("retry_wait"),
                count.filter(predicates["failed_terminal"]).label("failed_terminal"),
                count.filter(predicates["stale_due"]).label("stale"),
                count.filter(predicates["expired_lease"]).label("expired_lease"),
                count.filter(
                    and_(predicates["linked"], predicates["active_lease"])
                ).label("active_lease"),
            ).where(Project.source_system == "world_bank")
        )
    ).one()
    return WorldBankProjectBacklogSnapshot(
        **{
            field: int(getattr(row, field) or 0)
            for field in WorldBankProjectBacklogSnapshot.__dataclass_fields__
        }
    )


async def claim_world_bank_projects_for_enrichment(
    db: AsyncSession,
    *,
    now: datetime | None = None,
    limit: int = WORLD_BANK_ENRICHMENT_BATCH_SIZE,
) -> list[UUID]:
    """Atomically coalesce linked new/stale Projects into one bounded batch."""
    observed_at = now or datetime.now(timezone.utc)
    predicates = _world_bank_enrichment_predicates(observed_at)
    result = await db.execute(
        select(Project)
        .where(
            Project.source_system == "world_bank",
            predicates["eligible"],
        )
        .order_by(
            case(
                (predicates["never_attempted"], 0),
                (predicates["stale_due"], 1),
                (predicates["retry_due"], 2),
                (predicates["expired_lease"], 3),
                else_=4,
            ),
            Project.last_enriched_at.asc().nullsfirst(),
            Project.created_at,
            Project.id,
        )
        .limit(max(1, min(int(limit), WORLD_BANK_ENRICHMENT_BATCH_SIZE)))
        .with_for_update(skip_locked=True)
    )
    projects = result.scalars().all()
    for project in projects:
        project.enrichment_status = "queued"
        project.enrichment_last_attempted_at = observed_at
        project.enrichment_failure_class = None
    return [project.id for project in projects]


async def enqueue_world_bank_project_enrichment_batch(
    db: AsyncSession,
    *,
    limit: int = WORLD_BANK_ENRICHMENT_BATCH_SIZE,
    now: datetime | None = None,
) -> ProjectEnrichmentDispatchResult:
    """Claim, commit, then publish a bounded batch without blocking on HTTP."""
    from app.workers.project_enrichment_tasks import enrich_world_bank_project_task

    observed_at = now or datetime.now(timezone.utc)
    started_at = time.monotonic()
    before = await world_bank_project_backlog_snapshot(db, now=observed_at)
    project_ids = await claim_world_bank_projects_for_enrichment(
        db,
        limit=limit,
        now=observed_at,
    )
    await db.commit()
    enqueued = 0
    failed_ids: list[UUID] = []
    for project_id in project_ids:
        try:
            enrich_world_bank_project_task.apply_async(
                args=[str(project_id)],
                queue="celery",
                routing_key="celery",
                retry=True,
                retry_policy={
                    "max_retries": 3,
                    "interval_start": 0,
                    "interval_step": 0.2,
                    "interval_max": 1,
                },
            )
            enqueued += 1
        except Exception:
            failed_ids.append(project_id)
            logger.exception(
                "world_bank_project_enrichment_dispatch_failed project_id=%s",
                project_id,
            )
    for project_id in failed_ids:
        await mark_project_enrichment_failure(
            db,
            project_id=project_id,
            status="failed",
            failure_class="dispatch_failure",
        )
    if failed_ids:
        await db.commit()
    result = ProjectEnrichmentDispatchResult(
        claimed=len(project_ids),
        enqueued=enqueued,
        dispatch_failed=len(failed_ids),
        eligible_found=before.eligible_now,
        skipped_active_lease=before.active_lease,
        duration_ms=max(0, round((time.monotonic() - started_at) * 1000)),
    )
    logger.info(
        "world_bank_project_enrichment_dispatch "
        "eligible_found=%s claimed=%s dispatched=%s skipped_active_lease=%s "
        "dispatch_failures=%s duration_ms=%s",
        result.eligible_found,
        result.claimed,
        result.enqueued,
        result.skipped_active_lease,
        result.dispatch_failed,
        result.duration_ms,
    )
    return result
