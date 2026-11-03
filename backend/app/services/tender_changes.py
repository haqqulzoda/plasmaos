"""Tender-change alerts.

When a source refresh changes a tender's deadline, its notice (an amendment) or its
documents, every active pursuit of that tender with a completed analysis gets one
``TENDER_CHANGED`` outbox event per active member: the inbox item and, by the member's
analysis e-mail preference, an e-mail (the existing outbox publisher does both). The
change is recorded so analysis reads can say, passively, that the run predates it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import MembershipState, PursuitOrigin, TenderEngagementStatus
from app.models.pursuit_analysis import AnalysisRun
from app.models.tenancy import Membership, OrganizationPursuit
from app.models.tender_changes import TenderChange
from app.services.notifications import stage_system_outbox

CHANGE_KINDS = ("DEADLINE", "AMENDMENT", "DOCUMENT")
# Source-owned fields whose change means the published notice was amended. Bookkeeping
# (metadata, scrape status, URLs, taxonomy) is not an amendment.
AMENDMENT_FIELDS = frozenset({
    "title", "description", "budget", "currency", "buyer", "procurement_method", "procurement_category", "notice_type",
})
CLOSED_STAGES = (TenderEngagementStatus.WON, TenderEngagementStatus.LOST, TenderEngagementStatus.DISMISSED)


def change_kinds_for_fields(changed_fields: Iterable[str]) -> set[str]:
    fields = set(changed_fields)
    kinds = set()
    if "deadline" in fields:
        kinds.add("DEADLINE")
    if fields & AMENDMENT_FIELDS:
        kinds.add("AMENDMENT")
    return kinds


async def record_tender_changes(db: AsyncSession, changes: Mapping[UUID, Iterable[str]]) -> int:
    """Record changes of pursued, analyzed tenders and stage the alerts; caller commits.

    Tenders nobody pursues with a completed analysis record nothing. Returns the number
    of staged outbox events.
    """
    wanted = {tender_id: sorted(set(kinds) & set(CHANGE_KINDS)) for tender_id, kinds in changes.items()}
    wanted = {tender_id: kinds for tender_id, kinds in wanted.items() if kinds}
    if not wanted:
        return 0
    analyzed = select(AnalysisRun.id).where(
        AnalysisRun.pursuit_id == OrganizationPursuit.id, AnalysisRun.status == "COMPLETED"
    ).exists()
    pursuits = (
        await db.execute(
            select(OrganizationPursuit.id, OrganizationPursuit.organization_id, OrganizationPursuit.source_tender_id)
            .where(
                OrganizationPursuit.source_tender_id.in_(wanted),
                OrganizationPursuit.origin == PursuitOrigin.SOURCE,
                OrganizationPursuit.archived_at.is_(None),
                OrganizationPursuit.stage.not_in(CLOSED_STAGES),
                analyzed,
            )
            .order_by(OrganizationPursuit.id)
        )
    ).all()
    if not pursuits:
        return 0
    recorded: dict[UUID, TenderChange] = {}
    for tender_id in sorted({row.source_tender_id for row in pursuits}):
        recorded[tender_id] = TenderChange(tender_id=tender_id, change_kinds=wanted[tender_id])
        db.add(recorded[tender_id])
    await db.flush()
    members = (
        await db.execute(
            select(Membership.organization_id, Membership.user_id)
            .where(
                Membership.organization_id.in_({row.organization_id for row in pursuits}),
                Membership.state == MembershipState.ACTIVE,
            )
            .order_by(Membership.user_id)
        )
    ).all()
    staged = 0
    for pursuit in pursuits:
        change = recorded[pursuit.source_tender_id]
        for member in members:
            if member.organization_id != pursuit.organization_id:
                continue
            await stage_system_outbox(
                db, user_id=member.user_id, event_type="TENDER_CHANGED",
                payload={
                    "organization_id": str(pursuit.organization_id), "pursuit_id": str(pursuit.id),
                    "tender_id": str(pursuit.source_tender_id), "tender_change_id": str(change.id),
                    "change_kinds": list(change.change_kinds),
                },
                dedupe_key=f"tender-change:{change.id}:{pursuit.id}:{member.user_id}",
            )
            staged += 1
    return staged


async def tender_changes_since(db: AsyncSession, *, pursuit_id: UUID, since: datetime) -> list[str]:
    """Passive: the kinds of source changes to the pursuit's tender after ``since``."""
    rows = (
        await db.scalars(
            select(TenderChange.change_kinds)
            .join(OrganizationPursuit, OrganizationPursuit.source_tender_id == TenderChange.tender_id)
            .where(OrganizationPursuit.id == pursuit_id, TenderChange.detected_at > since)
        )
    ).all()
    present = {kind for kinds in rows for kind in kinds}
    return [kind for kind in CHANGE_KINDS if kind in present]
