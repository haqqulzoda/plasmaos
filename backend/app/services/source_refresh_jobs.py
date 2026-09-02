"""Durable source refresh job lifecycle, option, and lease authority."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Mapping
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.all_models import SourceRefreshJob
from app.services.source_registry import (
    validate_source_refresh_options as _validate_registry_options,
)
from app.services.tender_sources.keys import normalize_source_system


SOURCE_REFRESH_TRIGGER_CUSTOMER = "customer"
SOURCE_REFRESH_TRIGGER_OPERATOR = "operator"
SOURCE_REFRESH_TRIGGER_SCHEDULED = "scheduled"
SOURCE_REFRESH_TRIGGER_KINDS = frozenset(
    {
        SOURCE_REFRESH_TRIGGER_CUSTOMER,
        SOURCE_REFRESH_TRIGGER_OPERATOR,
        SOURCE_REFRESH_TRIGGER_SCHEDULED,
    }
)
TERMINAL_SOURCE_REFRESH_STATUSES = frozenset(
    {"completed", "partial", "source_unavailable", "failed"}
)

DEFAULT_SOURCE_REFRESH_LEASE_SECONDS = 180
DEFAULT_SOURCE_REFRESH_HEARTBEAT_SECONDS = 30
DEFAULT_QUEUED_REPUBLISH_SECONDS = 60


def _positive_seconds(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def source_refresh_lease_seconds() -> int:
    return _positive_seconds(
        "SOURCE_REFRESH_LEASE_SECONDS",
        DEFAULT_SOURCE_REFRESH_LEASE_SECONDS,
    )


def source_refresh_heartbeat_seconds() -> int:
    configured = _positive_seconds(
        "SOURCE_REFRESH_HEARTBEAT_SECONDS",
        DEFAULT_SOURCE_REFRESH_HEARTBEAT_SECONDS,
    )
    return min(configured, max(1, source_refresh_lease_seconds() // 2))


def queued_republish_seconds() -> int:
    return _positive_seconds(
        "SOURCE_REFRESH_QUEUED_REPUBLISH_SECONDS",
        DEFAULT_QUEUED_REPUBLISH_SECONDS,
    )


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def validate_trigger_kind(trigger_kind: str) -> str:
    normalized = str(trigger_kind or "").strip().casefold()
    if normalized not in SOURCE_REFRESH_TRIGGER_KINDS:
        raise ValueError(f"unsupported source refresh trigger_kind: {trigger_kind!r}")
    return normalized


def _bounded_int(
    options: Mapping[str, Any],
    name: str,
    *,
    minimum: int,
    maximum: int,
) -> int | None:
    if name not in options:
        return None
    value = options[name]
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    parsed = int(value)
    if not minimum <= parsed <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return parsed


def _strict_bool(options: Mapping[str, Any], name: str) -> bool | None:
    if name not in options:
        return None
    value = options[name]
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a boolean")
    return value


def validate_source_refresh_options(
    source_system: str,
    options: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Compatibility entrypoint delegated to the capability registry."""
    return _validate_registry_options(source_system, options)


class SourceRefreshClaimStatus(str, Enum):
    CLAIMED = "claimed"
    RENEWED = "renewed"
    BUSY = "busy"
    TERMINAL = "terminal"
    MISSING = "missing"
    SOURCE_MISMATCH = "source_mismatch"


@dataclass(frozen=True)
class SourceRefreshClaim:
    status: SourceRefreshClaimStatus
    job_status: str | None = None
    previous_owner: UUID | None = None

    @property
    def may_execute(self) -> bool:
        return self.status in {
            SourceRefreshClaimStatus.CLAIMED,
            SourceRefreshClaimStatus.RENEWED,
        }


def lease_is_valid(job: SourceRefreshJob, *, now: datetime | None = None) -> bool:
    comparison = as_utc(now) or utc_now()
    expiry = as_utc(getattr(job, "lease_expires_at", None))
    return (
        job.status == "running"
        and getattr(job, "lease_owner", None) is not None
        and expiry is not None
        and expiry > comparison
    )


def active_job_needs_republish(
    job: SourceRefreshJob,
    *,
    now: datetime | None = None,
) -> bool:
    comparison = as_utc(now) or utc_now()
    if job.status == "queued":
        created = as_utc(job.created_at) or comparison
        return created <= comparison - timedelta(seconds=queued_republish_seconds())
    if job.status != "running":
        return False
    expiry = as_utc(getattr(job, "lease_expires_at", None))
    if expiry is not None:
        return expiry <= comparison
    # Historical RUNNING jobs have no lease. Give very recent legacy executions
    # one lease window before request-time recovery republishes their job.
    updated = as_utc(job.updated_at) or comparison
    return updated <= comparison - timedelta(seconds=source_refresh_lease_seconds())


def _reset_attempt_state(job: SourceRefreshJob) -> None:
    for field_name in (
        "created_count",
        "updated_count",
        "unchanged_count",
        "fetched_count",
        "skipped_count",
        "rejected_count",
        "failed_count",
        "documents_discovered_count",
        "documents_queued_count",
    ):
        setattr(job, field_name, 0)
    job.fallback_used = False
    job.skip_reasons = {}
    job.failure_class = None
    job.failure_stage = None
    job.retryable = None
    job.elapsed_ms = None
    job.fetch_elapsed_ms = None
    job.normalize_elapsed_ms = None
    job.persist_elapsed_ms = None
    job.document_dispatch_elapsed_ms = None
    job.http_request_count = None
    job.http_retry_count = None
    job.http_failure_count = None
    job.source_newest_published_at = None
    job.source_oldest_published_at = None
    job.execution_health = None
    job.freshness_health = None
    job.coverage_health = None
    job.completed_at = None


async def claim_source_refresh_job(
    db: AsyncSession,
    *,
    job_id: UUID,
    source_system: str,
    lease_owner: UUID,
    now: datetime | None = None,
    lease_seconds: int | None = None,
) -> SourceRefreshClaim:
    """Atomically claim or renew one job under a row lock."""
    comparison = as_utc(now) or utc_now()
    duration = lease_seconds or source_refresh_lease_seconds()
    if isinstance(db, AsyncSession):
        result = await db.execute(
            select(SourceRefreshJob)
            .where(SourceRefreshJob.id == job_id)
            .with_for_update()
        )
        job = result.scalar_one_or_none()
    else:  # isolated compatibility for historical lightweight unit-test sessions
        job = await db.get(SourceRefreshJob, job_id)
    if job is None:
        return SourceRefreshClaim(SourceRefreshClaimStatus.MISSING)
    if job.source_system != normalize_source_system(source_system):
        return SourceRefreshClaim(
            SourceRefreshClaimStatus.SOURCE_MISMATCH,
            job_status=job.status,
        )
    if job.status in TERMINAL_SOURCE_REFRESH_STATUSES:
        return SourceRefreshClaim(
            SourceRefreshClaimStatus.TERMINAL,
            job_status=job.status,
        )

    previous_owner = getattr(job, "lease_owner", None)
    expiry = as_utc(getattr(job, "lease_expires_at", None))
    if job.status == "running" and previous_owner == lease_owner and expiry and expiry > comparison:
        job.heartbeat_at = comparison
        job.lease_expires_at = comparison + timedelta(seconds=duration)
        await db.commit()
        return SourceRefreshClaim(
            SourceRefreshClaimStatus.RENEWED,
            job_status=job.status,
            previous_owner=previous_owner,
        )
    if job.status == "running" and expiry is not None and expiry > comparison:
        busy_status = job.status
        await db.rollback()
        return SourceRefreshClaim(
            SourceRefreshClaimStatus.BUSY,
            job_status=busy_status,
            previous_owner=previous_owner,
        )

    _reset_attempt_state(job)
    job.status = "running"
    job.started_at = job.started_at or comparison
    job.lease_owner = lease_owner
    job.heartbeat_at = comparison
    job.lease_expires_at = comparison + timedelta(seconds=duration)
    job.message = "Refreshing."
    await db.commit()
    return SourceRefreshClaim(
        SourceRefreshClaimStatus.CLAIMED,
        job_status=job.status,
        previous_owner=previous_owner,
    )


async def renew_source_refresh_lease(
    db: AsyncSession,
    *,
    job_id: UUID,
    lease_owner: UUID,
    now: datetime | None = None,
    lease_seconds: int | None = None,
) -> bool:
    """Renew only a still-valid lease owned by this execution attempt."""
    comparison = as_utc(now) or utc_now()
    duration = lease_seconds or source_refresh_lease_seconds()
    if not isinstance(db, AsyncSession):
        job = await db.get(SourceRefreshJob, job_id)
        if (
            job is None
            or job.status != "running"
            or job.lease_owner != lease_owner
            or not lease_is_valid(job, now=comparison)
        ):
            return False
        job.heartbeat_at = comparison
        job.lease_expires_at = comparison + timedelta(seconds=duration)
        await db.commit()
        return True
    statement = (
        update(SourceRefreshJob)
        .where(
            SourceRefreshJob.id == job_id,
            SourceRefreshJob.status == "running",
            SourceRefreshJob.lease_owner == lease_owner,
            SourceRefreshJob.lease_expires_at > comparison,
        )
        .values(
            heartbeat_at=comparison,
            lease_expires_at=comparison + timedelta(seconds=duration),
        )
        .returning(SourceRefreshJob.id)
    )
    renewed = (await db.execute(statement)).scalar_one_or_none() is not None
    if renewed:
        await db.commit()
    else:
        await db.rollback()
    return renewed


TERMINAL_RESULT_FIELDS = frozenset(
    {
        "created_count",
        "updated_count",
        "unchanged_count",
        "fetched_count",
        "skipped_count",
        "rejected_count",
        "failed_count",
        "documents_discovered_count",
        "documents_queued_count",
        "fallback_used",
        "skip_reasons",
        "failure_class",
        "failure_stage",
        "retryable",
        "elapsed_ms",
        "fetch_elapsed_ms",
        "normalize_elapsed_ms",
        "persist_elapsed_ms",
        "document_dispatch_elapsed_ms",
        "http_request_count",
        "http_retry_count",
        "http_failure_count",
        "source_newest_published_at",
        "source_oldest_published_at",
        "execution_health",
        "freshness_health",
        "coverage_health",
        "message",
    }
)


async def complete_source_refresh_job(
    db: AsyncSession,
    *,
    job_id: UUID,
    lease_owner: UUID,
    terminal_status: str,
    result_values: Mapping[str, Any],
    now: datetime | None = None,
) -> bool:
    """Write terminal state only while this attempt owns a valid lease."""
    if terminal_status not in TERMINAL_SOURCE_REFRESH_STATUSES:
        raise ValueError(f"invalid terminal source refresh status: {terminal_status!r}")
    unexpected = sorted(set(result_values) - TERMINAL_RESULT_FIELDS)
    if unexpected:
        raise ValueError(f"unsupported terminal result field(s): {', '.join(unexpected)}")
    comparison = as_utc(now) or utc_now()
    values = dict(result_values)
    values.update(
        {
            "status": terminal_status,
            "completed_at": comparison,
            "lease_owner": None,
            "lease_expires_at": None,
        }
    )
    if not isinstance(db, AsyncSession):
        job = await db.get(SourceRefreshJob, job_id)
        if (
            job is None
            or job.status != "running"
            or job.lease_owner != lease_owner
            or not lease_is_valid(job, now=comparison)
        ):
            return False
        for field_name, value in values.items():
            setattr(job, field_name, value)
        await db.commit()
        return True
    statement = (
        update(SourceRefreshJob)
        .where(
            SourceRefreshJob.id == job_id,
            SourceRefreshJob.status == "running",
            SourceRefreshJob.lease_owner == lease_owner,
            SourceRefreshJob.lease_expires_at > comparison,
        )
        .values(**values)
        .returning(SourceRefreshJob.id)
    )
    completed = (await db.execute(statement)).scalar_one_or_none() is not None
    if completed:
        await db.commit()
    else:
        await db.rollback()
    return completed


async def fail_queued_source_refresh_publish(
    db: AsyncSession,
    *,
    job_id: UUID,
    failure_class: str,
    message: str,
    now: datetime | None = None,
) -> bool:
    """Make a committed-but-unpublished queued job explicitly terminal."""
    comparison = as_utc(now) or utc_now()
    if not isinstance(db, AsyncSession):
        job = await db.get(SourceRefreshJob, job_id)
        if job is None or job.status != "queued":
            return False
        job.status = "failed"
        job.failed_count = 1
        job.failure_stage = "dispatch"
        job.failure_class = failure_class[:100]
        job.retryable = True
        job.message = message
        job.completed_at = comparison
        await db.commit()
        return True
    statement = (
        update(SourceRefreshJob)
        .where(
            SourceRefreshJob.id == job_id,
            SourceRefreshJob.status == "queued",
        )
        .values(
            status="failed",
            failed_count=1,
            failure_stage="dispatch",
            failure_class=failure_class[:100],
            retryable=True,
            message=message,
            completed_at=comparison,
        )
        .returning(SourceRefreshJob.id)
    )
    failed = (await db.execute(statement)).scalar_one_or_none() is not None
    if failed:
        await db.commit()
    else:
        await db.rollback()
    return failed
