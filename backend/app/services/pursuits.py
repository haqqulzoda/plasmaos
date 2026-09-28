"""Canonical OrganizationPursuit commands and compatibility projections."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.all_models import Tender
from app.models.base import (
    MembershipState,
    PursuitOrigin,
    TenderEngagementOrigin,
    TenderEngagementStatus,
)
from app.models.tenancy import Membership, OrganizationPursuit, PursuitLifecycleEvent
from app.services.pursuit_lifecycle import transition_is_allowed


class PursuitError(RuntimeError):
    pass


class PursuitNotFoundError(PursuitError):
    pass


class PursuitTransitionError(PursuitError):
    pass


class PursuitOwnershipError(PursuitError):
    pass


@dataclass(frozen=True)
class PursuitResolution:
    pursuit: OrganizationPursuit
    created: bool


CREATABLE_STAGES = frozenset(
    {
        TenderEngagementStatus.SAVED,
        TenderEngagementStatus.EVALUATING,
        TenderEngagementStatus.PREPARING,
    }
)


async def _active_membership(
    db: AsyncSession, *, organization_id: UUID, membership_id: UUID
) -> Membership:
    membership = await db.scalar(
        select(Membership).where(
            Membership.id == membership_id,
            Membership.organization_id == organization_id,
            Membership.state == MembershipState.ACTIVE,
        )
    )
    if membership is None:
        raise PursuitOwnershipError("active membership in pursuit organization required")
    return membership


async def get_source_pursuit(
    db: AsyncSession, *, organization_id: UUID, tender_id: UUID
) -> OrganizationPursuit | None:
    return await db.scalar(
        select(OrganizationPursuit).where(
            OrganizationPursuit.organization_id == organization_id,
            OrganizationPursuit.source_tender_id == tender_id,
            OrganizationPursuit.origin == PursuitOrigin.SOURCE,
        )
    )


async def get_or_create_source_pursuit(
    db: AsyncSession,
    *,
    organization_id: UUID,
    actor_user_id: UUID,
    actor_membership_id: UUID,
    tender_id: UUID,
    stage: TenderEngagementStatus,
    legacy_origin: TenderEngagementOrigin,
) -> PursuitResolution:
    if stage not in CREATABLE_STAGES:
        raise PursuitTransitionError(f"{stage.value} is not a valid initial pursuit stage")
    membership = await _active_membership(
        db, organization_id=organization_id, membership_id=actor_membership_id
    )
    if await db.scalar(select(Tender.id).where(Tender.id == tender_id)) is None:
        raise PursuitNotFoundError("source Tender not found")
    pursuit_id = uuid4()
    legacy_engagement_id = uuid4()
    while legacy_engagement_id == pursuit_id:
        legacy_engagement_id = uuid4()
    inserted_id = await db.scalar(
        pg_insert(OrganizationPursuit)
        .values(
            id=pursuit_id,
            organization_id=organization_id,
            source_tender_id=tender_id,
            origin=PursuitOrigin.SOURCE,
            legacy_engagement_id=legacy_engagement_id,
            legacy_origin=legacy_origin,
            owner_membership_id=membership.id,
            stage=stage,
        )
        .on_conflict_do_nothing(
            index_elements=[
                OrganizationPursuit.organization_id,
                OrganizationPursuit.source_tender_id,
            ],
            index_where=text("origin = 'SOURCE'"),
        )
        .returning(OrganizationPursuit.id)
    )
    pursuit = await get_source_pursuit(
        db, organization_id=organization_id, tender_id=tender_id
    )
    if pursuit is None:
        raise PursuitError("source pursuit resolution failed")
    if inserted_id == pursuit_id:
        db.add(
            PursuitLifecycleEvent(
                pursuit_id=pursuit.id,
                actor_user_id=actor_user_id,
                actor_membership_id=actor_membership_id,
                previous_stage=None,
                new_stage=stage,
                action="CREATE",
            )
        )
        await db.flush()
    return PursuitResolution(pursuit=pursuit, created=inserted_id == pursuit_id)


async def create_upload_pursuit(
    db: AsyncSession,
    *,
    organization_id: UUID,
    actor_user_id: UUID,
    actor_membership_id: UUID,
) -> OrganizationPursuit:
    """Create an organization-private pursuit with no shared Tender identity."""
    membership = await _active_membership(
        db, organization_id=organization_id, membership_id=actor_membership_id
    )
    pursuit = OrganizationPursuit(
        organization_id=organization_id,
        source_tender_id=None,
        origin=PursuitOrigin.UPLOAD,
        legacy_engagement_id=None,
        legacy_origin=None,
        owner_membership_id=membership.id,
        stage=TenderEngagementStatus.SAVED,
    )
    db.add(pursuit)
    await db.flush()
    db.add(
        PursuitLifecycleEvent(
            pursuit_id=pursuit.id,
            actor_user_id=actor_user_id,
            actor_membership_id=actor_membership_id,
            previous_stage=None,
            new_stage=pursuit.stage,
            action="CREATE",
            reason="Private document upload intake",
        )
    )
    await db.flush()
    return pursuit


async def get_owned_pursuit(
    db: AsyncSession,
    *,
    pursuit_id: UUID,
    organization_id: UUID,
) -> OrganizationPursuit | None:
    return await db.scalar(
        select(OrganizationPursuit).where(
            OrganizationPursuit.id == pursuit_id,
            OrganizationPursuit.organization_id == organization_id,
        )
    )


async def get_owned_pursuit_by_legacy_id(
    db: AsyncSession,
    *,
    legacy_engagement_id: UUID,
    organization_id: UUID,
) -> OrganizationPursuit | None:
    return await db.scalar(
        select(OrganizationPursuit).where(
            OrganizationPursuit.legacy_engagement_id == legacy_engagement_id,
            OrganizationPursuit.organization_id == organization_id,
        )
    )


async def transition_pursuit(
    db: AsyncSession,
    *,
    pursuit_id: UUID,
    organization_id: UUID,
    actor_user_id: UUID,
    actor_membership_id: UUID,
    stage: TenderEngagementStatus,
    expected_stage: TenderEngagementStatus | None = None,
    correction: bool = False,
    reason: str | None = None,
) -> OrganizationPursuit:
    await _active_membership(
        db, organization_id=organization_id, membership_id=actor_membership_id
    )
    pursuit = await db.scalar(
        select(OrganizationPursuit)
        .where(
            OrganizationPursuit.id == pursuit_id,
            OrganizationPursuit.organization_id == organization_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if pursuit is None:
        raise PursuitNotFoundError("pursuit not found")
    if expected_stage is not None and pursuit.stage != expected_stage:
        raise PursuitTransitionError(
            f"stale pursuit stage: expected {expected_stage.value}, found {pursuit.stage.value}"
        )
    if pursuit.archived_at is not None:
        raise PursuitTransitionError("archived pursuit requires explicit reopen")
    reopening = pursuit.stage in {
        TenderEngagementStatus.WON,
        TenderEngagementStatus.LOST,
    } and stage in {
        TenderEngagementStatus.SAVED,
        TenderEngagementStatus.EVALUATING,
        TenderEngagementStatus.PREPARING,
    }
    if reopening:
        raise PursuitTransitionError("closed pursuit requires explicit reopen")
    if not transition_is_allowed(pursuit.stage, stage, correction=correction):
        raise PursuitTransitionError(
            f"invalid pursuit transition: {pursuit.stage.value} -> {stage.value}"
        )
    previous = pursuit.stage
    now = datetime.now(timezone.utc)
    pursuit.stage = stage
    pursuit.stage_changed_at = now
    pursuit.updated_at = now
    db.add(
        PursuitLifecycleEvent(
            pursuit_id=pursuit.id,
            actor_user_id=actor_user_id,
            actor_membership_id=actor_membership_id,
            previous_stage=previous,
            new_stage=stage,
            action="CORRECT" if correction else "TRANSITION",
            reason=reason,
        )
    )
    await db.flush()
    return pursuit


async def reopen_pursuit(
    db: AsyncSession,
    *,
    pursuit_id: UUID,
    organization_id: UUID,
    actor_user_id: UUID,
    actor_membership_id: UUID,
    destination: TenderEngagementStatus,
    expected_stage: TenderEngagementStatus | None = None,
    reason: str | None = None,
) -> OrganizationPursuit:
    if destination not in {
        TenderEngagementStatus.SAVED,
        TenderEngagementStatus.EVALUATING,
        TenderEngagementStatus.PREPARING,
    }:
        raise PursuitTransitionError("reopen destination must be an active stage")
    await _active_membership(
        db, organization_id=organization_id, membership_id=actor_membership_id
    )
    pursuit = await db.scalar(
        select(OrganizationPursuit)
        .where(
            OrganizationPursuit.id == pursuit_id,
            OrganizationPursuit.organization_id == organization_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if pursuit is None:
        raise PursuitNotFoundError("pursuit not found")
    if expected_stage is not None and pursuit.stage != expected_stage:
        raise PursuitTransitionError(
            f"stale pursuit stage: expected {expected_stage.value}, found {pursuit.stage.value}"
        )
    if pursuit.stage not in {TenderEngagementStatus.WON, TenderEngagementStatus.LOST} and pursuit.archived_at is None:
        raise PursuitTransitionError("only closed or archived pursuits can be reopened")
    previous = pursuit.stage
    now = datetime.now(timezone.utc)
    pursuit.stage = destination
    pursuit.archived_at = None
    pursuit.stage_changed_at = now
    pursuit.updated_at = now
    db.add(
        PursuitLifecycleEvent(
            pursuit_id=pursuit.id,
            actor_user_id=actor_user_id,
            actor_membership_id=actor_membership_id,
            previous_stage=previous,
            new_stage=destination,
            action="REOPEN",
            reason=reason,
        )
    )
    await db.flush()
    return pursuit


async def assign_pursuit_owner(
    db: AsyncSession,
    *,
    pursuit_id: UUID,
    organization_id: UUID,
    actor_membership_id: UUID,
    owner_membership_id: UUID | None,
) -> OrganizationPursuit:
    actor = await _active_membership(
        db, organization_id=organization_id, membership_id=actor_membership_id
    )
    if owner_membership_id is not None:
        await _active_membership(
            db, organization_id=organization_id, membership_id=owner_membership_id
        )
    pursuit = await db.scalar(
        select(OrganizationPursuit)
        .where(
            OrganizationPursuit.id == pursuit_id,
            OrganizationPursuit.organization_id == organization_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if pursuit is None:
        raise PursuitNotFoundError("pursuit not found")
    if actor.role.value != "OWNER" and actor.id != pursuit.owner_membership_id:
        raise PursuitOwnershipError("only an OWNER or current pursuit owner may reassign")
    pursuit.owner_membership_id = owner_membership_id
    pursuit.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return pursuit
