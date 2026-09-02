"""Customer-safe source catalog, status snapshot, and terminal activity reads."""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Mapping
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.all_models import SourceRefreshJob
from app.schemas.source_refresh import (
    SourceCatalogItem,
    SourceRefreshActiveJob,
    SourceRefreshActivityEvent,
    SourceRefreshActivityResponse,
    SourceRefreshStatusItem,
    SourceRefreshTerminalSummary,
)
from app.services.source_refresh_jobs import TERMINAL_SOURCE_REFRESH_STATUSES
from app.services.source_registry import SOURCE_REGISTRY, SourceDefinition


ACTIVE_STATUSES = frozenset({"queued", "running"})
TERMINAL_STATUSES = tuple(sorted(TERMINAL_SOURCE_REFRESH_STATUSES))
MAX_ACTIVITY_LIMIT = 100
DEFAULT_ACTIVITY_LIMIT = 25
MAX_CURSOR_LENGTH = 512


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def encode_activity_cursor(completed_at: datetime | None, job_id: UUID | None) -> str:
    payload = (
        {"v": 1, "completed_at": _utc(completed_at).isoformat(), "job_id": str(job_id)}
        if completed_at is not None and job_id is not None
        else {"v": 1, "completed_at": None, "job_id": None}
    )
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_activity_cursor(cursor: str) -> tuple[datetime | None, UUID | None]:
    if len(cursor) > MAX_CURSOR_LENGTH:
        raise HTTPException(status_code=422, detail="Invalid activity cursor")
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.b64decode(padded, altchars=b"-_", validate=True))
        if payload.get("v") != 1:
            raise ValueError
        completed_raw, job_raw = payload.get("completed_at"), payload.get("job_id")
        if completed_raw is None and job_raw is None:
            return None, None
        if not isinstance(completed_raw, str) or not isinstance(job_raw, str):
            raise ValueError
        completed_at = datetime.fromisoformat(completed_raw)
        if completed_at.tzinfo is None:
            raise ValueError
        return _utc(completed_at), UUID(job_raw)
    except (ValueError, TypeError, KeyError, UnicodeDecodeError, binascii.Error, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail="Invalid activity cursor") from exc


def customer_source_definitions(
    registry: Mapping[str, SourceDefinition] = SOURCE_REGISTRY,
) -> tuple[SourceDefinition, ...]:
    return tuple(
        definition
        for _key, definition in sorted(registry.items())
        if definition.customer_visible
    )


def source_catalog(
    registry: Mapping[str, SourceDefinition] = SOURCE_REGISTRY,
) -> list[SourceCatalogItem]:
    return [
        SourceCatalogItem(
            source_system=definition.key,
            display_name=definition.display_name,
            refresh_enabled=definition.refresh_enabled,
            can_refresh=definition.refresh_enabled,
        )
        for definition in customer_source_definitions(registry)
    ]


def counters_authoritative(job: SourceRefreshJob) -> bool:
    return job.trigger_kind is not None


def _terminal_reason(job: SourceRefreshJob) -> str:
    defaults = {
        "completed": "Refresh completed.",
        "partial": "Refresh completed with issues.",
        "source_unavailable": "Source is temporarily unavailable.",
        "failed": "Refresh failed.",
    }
    return defaults.get(job.status, "Refresh finished.")


def terminal_summary(job: SourceRefreshJob) -> SourceRefreshTerminalSummary:
    if job.status not in TERMINAL_SOURCE_REFRESH_STATUSES or job.completed_at is None:
        raise ValueError("terminal summary requires a completed terminal job")
    degraded = bool(
        job.fallback_used
        or job.status != "completed"
        or (job.execution_health not in (None, "PASS"))
        or (job.coverage_health not in (None, "COMPLETE"))
    )
    return SourceRefreshTerminalSummary(
        job_id=job.id,
        status=job.status,
        completed_at=_utc(job.completed_at),
        fetched_count=int(job.fetched_count or 0),
        created_count=int(job.created_count or 0),
        updated_count=int(job.updated_count or 0),
        unchanged_count=int(job.unchanged_count or 0),
        skipped_count=int(job.skipped_count or 0),
        failed_count=int(job.failed_count or 0),
        documents_discovered_count=int(job.documents_discovered_count or 0),
        documents_queued_count=int(job.documents_queued_count or 0),
        counts_authoritative=counters_authoritative(job),
        fallback_used=bool(job.fallback_used),
        degraded=degraded,
        terminal_reason=_terminal_reason(job),
    )


def activity_event(job: SourceRefreshJob, definition: SourceDefinition) -> SourceRefreshActivityEvent:
    return SourceRefreshActivityEvent(
        **terminal_summary(job).model_dump(),
        source_system=definition.key,
        source_display_name=definition.display_name,
    )


def _status_ranked_query(visible_keys: tuple[str, ...]):
    ranked = select(
        SourceRefreshJob.id.label("job_id"),
        SourceRefreshJob.source_system,
        SourceRefreshJob.status,
        SourceRefreshJob.trigger_kind,
        func.row_number().over(
            partition_by=(SourceRefreshJob.source_system, SourceRefreshJob.status),
            order_by=(
                func.coalesce(SourceRefreshJob.completed_at, SourceRefreshJob.created_at).desc(),
                SourceRefreshJob.id.desc(),
            ),
        ).label("status_rank"),
    ).where(SourceRefreshJob.source_system.in_(visible_keys)).subquery()
    return (
        select(SourceRefreshJob, ranked)
        .join(ranked, ranked.c.job_id == SourceRefreshJob.id)
        .where(ranked.c.status_rank == 1)
    )


async def source_refresh_status(
    db: AsyncSession,
    registry: Mapping[str, SourceDefinition] = SOURCE_REGISTRY,
) -> list[SourceRefreshStatusItem]:
    definitions = customer_source_definitions(registry)
    visible_keys = tuple(item.key for item in definitions)
    rows = (await db.execute(_status_ranked_query(visible_keys))).all() if visible_keys else []
    active: dict[str, SourceRefreshJob] = {}
    terminal: dict[str, SourceRefreshJob] = {}
    clean: dict[str, SourceRefreshJob] = {}
    partial: dict[str, SourceRefreshJob] = {}
    failure: dict[str, SourceRefreshJob] = {}
    high_water: SourceRefreshJob | None = None
    for row in rows:
        job = row[0]
        if job.status in ACTIVE_STATUSES:
            previous = active.get(job.source_system)
            if previous is None or (job.created_at, job.id) > (previous.created_at, previous.id):
                active[job.source_system] = job
        if job.status in TERMINAL_SOURCE_REFRESH_STATUSES and job.completed_at is not None:
            previous = terminal.get(job.source_system)
            if previous is None or (job.completed_at, job.id) > (previous.completed_at, previous.id):
                terminal[job.source_system] = job
            if counters_authoritative(job) and (
                high_water is None or (job.completed_at, job.id) > (high_water.completed_at, high_water.id)
            ):
                high_water = job
        if job.status == "completed" and job.completed_at is not None:
            clean[job.source_system] = job
        if job.status == "partial" and job.completed_at is not None:
            partial[job.source_system] = job
        if job.status in {"failed", "source_unavailable"} and job.completed_at is not None:
            previous = failure.get(job.source_system)
            if previous is None or (job.completed_at, job.id) > (previous.completed_at, previous.id):
                failure[job.source_system] = job
    cursor = encode_activity_cursor(
        high_water.completed_at if high_water else None,
        high_water.id if high_water else None,
    )
    return [
        SourceRefreshStatusItem(
            source_system=definition.key,
            display_name=definition.display_name,
            refresh_enabled=definition.refresh_enabled,
            can_refresh=definition.refresh_enabled,
            active_job=(
                SourceRefreshActiveJob(
                    job_id=active[definition.key].id,
                    status=active[definition.key].status,
                    queued_at=_utc(active[definition.key].created_at),
                    started_at=(
                        _utc(active[definition.key].started_at)
                        if active[definition.key].started_at is not None else None
                    ),
                    heartbeat_at=(
                        _utc(active[definition.key].heartbeat_at)
                        if active[definition.key].heartbeat_at is not None else None
                    ),
                ) if definition.key in active else None
            ),
            latest_terminal=terminal_summary(terminal[definition.key]) if definition.key in terminal else None,
            last_clean_completed=terminal_summary(clean[definition.key]) if definition.key in clean else None,
            last_partial=terminal_summary(partial[definition.key]) if definition.key in partial else None,
            last_failure=terminal_summary(failure[definition.key]) if definition.key in failure else None,
            activity_cursor=cursor,
        )
        for definition in definitions
    ]


async def source_refresh_activity(
    db: AsyncSession,
    *,
    cursor: str | None,
    limit: int = DEFAULT_ACTIVITY_LIMIT,
    registry: Mapping[str, SourceDefinition] = SOURCE_REGISTRY,
) -> SourceRefreshActivityResponse:
    if not 1 <= limit <= MAX_ACTIVITY_LIMIT:
        raise HTTPException(status_code=422, detail="Activity limit must be between 1 and 100")
    definitions = {item.key: item for item in customer_source_definitions(registry)}
    completed_at, job_id = decode_activity_cursor(cursor) if cursor else (None, None)
    statement = select(SourceRefreshJob).where(
        SourceRefreshJob.source_system.in_(tuple(definitions)),
        SourceRefreshJob.status.in_(TERMINAL_STATUSES),
        SourceRefreshJob.completed_at.is_not(None),
        SourceRefreshJob.trigger_kind.is_not(None),
    )
    if completed_at is not None and job_id is not None:
        statement = statement.where(tuple_(SourceRefreshJob.completed_at, SourceRefreshJob.id) > (completed_at, job_id))
    jobs = (
        await db.execute(
            statement.order_by(SourceRefreshJob.completed_at.asc(), SourceRefreshJob.id.asc()).limit(limit + 1)
        )
    ).scalars().all()
    page, has_more = jobs[:limit], len(jobs) > limit
    if page:
        next_cursor = encode_activity_cursor(page[-1].completed_at, page[-1].id)
    else:
        next_cursor = cursor or encode_activity_cursor(None, None)
    return SourceRefreshActivityResponse(
        events=[activity_event(job, definitions[job.source_system]) for job in page],
        next_cursor=next_cursor,
        has_more=has_more,
    )
