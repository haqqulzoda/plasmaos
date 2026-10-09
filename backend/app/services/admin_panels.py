"""R3 Task 5: read-only admin/operator panels for sources, analysis runs and organizations.

Every read is passive and returns ids, states, codes, counts and timings only: no
document text, findings, prompts, failure messages or customer content. The only
command is an analysis retry, which goes through the customer's explicit re-run path
(create_analysis_run with the same document selection) on behalf of the requester.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import MembershipState
from app.models.company import CompanyProfile
from app.models.pursuit_analysis import AnalysisPackItem, AnalysisRun
from app.models.tenancy import Membership, Organization, OrganizationPursuit
from app.services.source_refresh_activity import source_refresh_status
from app.services.source_refresh_schedule import configured_source_refresh_schedule

# The marker scripts/demo/seed_demo.py writes at the start of a demo company's notes.
DEMO_PROFILE_MARKER = "[plasma-demo-seed]"
STUCK_GRACE = timedelta(minutes=5)
QUEUED_STUCK_AFTER = timedelta(minutes=15)
LONG_RUN_AFTER = timedelta(minutes=10)
RUN_KINDS = ("failed", "stuck", "long")


class AdminPanelError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


# ---- sources ----------------------------------------------------------------------------------------

async def source_panel(db: AsyncSession, *, now: datetime | None = None) -> list[dict[str, Any]]:
    """Per visible source: last attempt/success, status, new/updated counts, next run, stale."""
    now = now or datetime.now(timezone.utc)
    schedule = configured_source_refresh_schedule()
    rows = []
    for item in await source_refresh_status(db):
        latest = item.latest_terminal
        last_attempt = _utc(item.active_job.queued_at) if item.active_job else (_utc(latest.completed_at) if latest else None)
        cadence = schedule.get(item.source_system)
        next_run = None
        if cadence is not None:
            next_run = now if last_attempt is None else max(now, last_attempt + cadence)
        rows.append({
            "source_system": item.source_system,
            "display_name": item.display_name,
            "status": item.active_job.status if item.active_job else (latest.status if latest else "never_run"),
            "running": item.active_job is not None,
            "last_attempt_at": last_attempt,
            "last_success_at": item.last_success_at,
            "last_success_partial": item.last_success_partial,
            "new_count": latest.created_count if latest and latest.counts_authoritative else None,
            "updated_count": latest.updated_count if latest and latest.counts_authoritative else None,
            "failed_count": latest.failed_count if latest else None,
            "terminal_reason": latest.terminal_reason if latest else None,
            "scheduled_cadence_seconds": item.scheduled_cadence_seconds,
            "next_scheduled_run_at": next_run,
            "stale": item.stale,
            "can_run_now": item.can_refresh and item.active_job is None,
        })
    return rows


# ---- analysis runs ----------------------------------------------------------------------------------

def _run_flags(run: AnalysisRun, now: datetime) -> dict[str, bool]:
    started = _utc(run.started_at)
    lease = _utc(run.lease_until)
    created = _utc(run.created_at)
    stuck = (
        run.status == "RUNNING" and (lease is None or lease + STUCK_GRACE < now)
    ) or (
        run.status == "QUEUED" and created is not None and created + QUEUED_STUCK_AFTER < now
        and run.attempt_count >= run.max_attempts
    ) or (run.status == "RUNNING" and run.attempt_count >= run.max_attempts and lease is not None and lease < now)
    end = _utc(run.completed_at) or now
    long = started is not None and end - started > LONG_RUN_AFTER
    return {"failed": run.status == "FAILED", "stuck": bool(stuck), "long": bool(long)}


def _run_row(run: AnalysisRun, organization_name: str | None, now: datetime) -> dict[str, Any]:
    flags = _run_flags(run, now)
    diagnostics = run.extraction_diagnostics or {}
    started, completed = _utc(run.started_at), _utc(run.completed_at)
    latency = None
    if started is not None:
        latency = int(((completed or now) - started).total_seconds() * 1000)
    return {
        "analysis_run_id": run.id,
        "organization_id": run.organization_id,
        "organization_name": organization_name,
        "pursuit_id": run.pursuit_id,
        "status": run.status,
        "stage": run.failure_stage or ("RUNNING" if run.status == "RUNNING" else run.status),
        "failure_code": diagnostics.get("failure_code") or diagnostics.get("error_type") if run.status == "FAILED" else None,
        "model_name": run.model_name,
        "pipeline_version": run.pipeline_version,
        "attempt_count": run.attempt_count,
        "max_attempts": run.max_attempts,
        "created_at": run.created_at,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "latency_ms": latency,
        "stuck": flags["stuck"],
        "long": flags["long"],
        "retry_allowed": flags["failed"] or flags["stuck"],
    }


async def analysis_run_panel(
    db: AsyncSession, *, kinds: tuple[str, ...] = RUN_KINDS, limit: int = 100, now: datetime | None = None
) -> list[dict[str, Any]]:
    """Failed, stuck and long runs across organizations, newest first."""
    now = now or datetime.now(timezone.utc)
    conditions = []
    if "failed" in kinds:
        conditions.append(AnalysisRun.status == "FAILED")
    if "stuck" in kinds:
        conditions.append(and_(AnalysisRun.status == "RUNNING", or_(
            AnalysisRun.lease_until.is_(None), AnalysisRun.lease_until < now - STUCK_GRACE,
        )))
        conditions.append(and_(
            AnalysisRun.status == "QUEUED", AnalysisRun.created_at < now - QUEUED_STUCK_AFTER,
            AnalysisRun.attempt_count >= AnalysisRun.max_attempts,
        ))
    if "long" in kinds:
        conditions.append(and_(
            AnalysisRun.started_at.is_not(None),
            func.coalesce(AnalysisRun.completed_at, now) - AnalysisRun.started_at > LONG_RUN_AFTER,
        ))
    if not conditions:
        return []
    rows = (
        await db.execute(
            select(AnalysisRun, Organization.display_name)
            .join(Organization, Organization.id == AnalysisRun.organization_id)
            .where(or_(*conditions))
            .order_by(AnalysisRun.created_at.desc(), AnalysisRun.id.desc())
            .limit(max(1, min(limit, 500)))
        )
    ).all()
    return [_run_row(run, name, now) for run, name in rows]


async def retry_analysis_run(db: AsyncSession, *, run_id: UUID, now: datetime | None = None) -> AnalysisRun:
    """A new run with the failed/stuck run's documents and language, for the same requester.

    Uses create_analysis_run, the same explicit path as the customer's re-run: the
    selection is revalidated against the current candidate and a new sealed run is
    queued. The original run is never changed.
    """
    from app.schemas.tenancy import PursuitAnalysisStartRequest
    from app.services.private_documents import build_analysis_pack_candidate
    from app.services.pursuit_analysis import AnalysisAdmissionError, create_analysis_run

    now = now or datetime.now(timezone.utc)
    run = await db.get(AnalysisRun, run_id)
    if run is None:
        raise AdminPanelError("NOT_FOUND", "Analysis run not found")
    if not (_run_flags(run, now)["failed"] or _run_flags(run, now)["stuck"]):
        raise AdminPanelError("NOT_RETRYABLE", "Only a failed or stuck run can be retried")
    requester = await db.scalar(
        select(Membership).where(
            Membership.id == run.requested_by_membership_id, Membership.state == MembershipState.ACTIVE,
        )
    )
    if requester is None:
        raise AdminPanelError("REQUESTER_INACTIVE", "The person who started this run is no longer an active member")
    items = list((await db.scalars(select(AnalysisPackItem).where(AnalysisPackItem.pack_id == run.pack_id))).all())
    candidate = await build_analysis_pack_candidate(db, organization_id=run.organization_id, pursuit_id=run.pursuit_id)
    ready_source = {item.tender_document_id for item in candidate.source_documents if item.parse_ready}
    ready_private = {item.document_version_id for item in candidate.private_versions if item.parse_ready}
    source = sorted({item.tender_document_id for item in items if item.tender_document_id in ready_source}, key=str)
    private = sorted({item.document_version_id for item in items if item.document_version_id in ready_private}, key=str)
    if not source and not private:
        raise AdminPanelError("DOCUMENTS_UNAVAILABLE", "The run's documents are no longer available")
    try:
        started = await create_analysis_run(
            db, organization_id=run.organization_id, pursuit_id=run.pursuit_id,
            membership_id=requester.id,
            request=PursuitAnalysisStartRequest(
                candidate_sha256=candidate.candidate_sha256, analysis_language=run.analysis_language,
                source_document_ids=source, private_version_ids=private,
            ),
        )
    except AnalysisAdmissionError as exc:
        raise AdminPanelError("NOT_ADMISSIBLE", str(exc)) from exc
    created = await db.get(AnalysisRun, started.analysis_run_id)
    if created is None:
        raise AdminPanelError("RETRY_FAILED", "The new run could not be read back")
    return created


# ---- organizations ----------------------------------------------------------------------------------

async def organization_panel(db: AsyncSession, *, limit: int = 500) -> list[dict[str, Any]]:
    """Organizations with active members, pursuits, last activity and the demo-seed flag."""
    members = (
        select(Membership.organization_id, func.count(Membership.id).label("members"))
        .where(Membership.state == MembershipState.ACTIVE)
        .group_by(Membership.organization_id)
        .subquery()
    )
    pursuits = (
        select(
            OrganizationPursuit.organization_id,
            func.count(OrganizationPursuit.id).label("pursuits"),
            func.max(OrganizationPursuit.updated_at).label("pursuit_activity"),
        )
        .group_by(OrganizationPursuit.organization_id)
        .subquery()
    )
    runs = (
        select(AnalysisRun.organization_id, func.max(AnalysisRun.created_at).label("run_activity"))
        .group_by(AnalysisRun.organization_id)
        .subquery()
    )
    rows = (
        await db.execute(
            select(
                Organization.id, Organization.display_name, Organization.created_at,
                CompanyProfile.approval_status, CompanyProfile.pilot_status, CompanyProfile.notes,
                func.coalesce(members.c.members, 0), func.coalesce(pursuits.c.pursuits, 0),
                pursuits.c.pursuit_activity, runs.c.run_activity,
            )
            .join(CompanyProfile, CompanyProfile.id == Organization.legacy_company_profile_id)
            .outerjoin(members, members.c.organization_id == Organization.id)
            .outerjoin(pursuits, pursuits.c.organization_id == Organization.id)
            .outerjoin(runs, runs.c.organization_id == Organization.id)
            .order_by(Organization.created_at.desc(), Organization.id)
            .limit(max(1, min(limit, 2000)))
        )
    ).all()
    result = []
    for (organization_id, name, created_at, approval, pilot, notes, member_count, pursuit_count,
         pursuit_activity, run_activity) in rows:
        activity = [value for value in (pursuit_activity, run_activity) if value is not None]
        result.append({
            "organization_id": organization_id,
            "display_name": name,
            "approval_status": approval,
            "pilot_status": pilot,
            "members_count": int(member_count),
            "pursuits_count": int(pursuit_count),
            "last_activity_at": max(activity) if activity else None,
            "created_at": created_at,
            "demo": (notes or "").startswith(DEMO_PROFILE_MARKER),
        })
    return result
