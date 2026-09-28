"""Legacy Engagement API adapter backed by canonical OrganizationPursuit."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import TenderEngagementOrigin, TenderEngagementStatus
from app.models.tenancy import OrganizationPursuit
from app.services.organization_context import OrganizationAccessDeniedError, resolve_legacy_profile_context
from app.services.pursuit_lifecycle import CORRECTION_TRANSITIONS, NORMAL_TRANSITIONS, transition_is_allowed
from app.services.pursuits import PursuitNotFoundError, PursuitTransitionError, get_or_create_source_pursuit, get_source_pursuit, reopen_pursuit, transition_pursuit


class TenderEngagementError(RuntimeError):
    pass


class TenderEngagementOwnershipError(TenderEngagementError):
    pass


class TenderEngagementTenderNotFoundError(TenderEngagementError):
    pass


class TenderEngagementNotFoundError(TenderEngagementError):
    pass


class TenderEngagementTransitionError(TenderEngagementError):
    pass


CREATABLE_STATUSES = frozenset({TenderEngagementStatus.SAVED, TenderEngagementStatus.EVALUATING, TenderEngagementStatus.PREPARING})

ACTION_SAVE = "SAVE"
ACTION_EVALUATE = "EVALUATE"
ACTION_PREPARE_BID = "PREPARE_BID"
ACTION_MARK_SUBMITTED = "MARK_SUBMITTED"
ACTION_RECORD_WON = "RECORD_WON"
ACTION_RECORD_LOST = "RECORD_LOST"
ACTION_DISMISS = "DISMISS"
ACTION_CORRECT_TO_PREPARING = "CORRECT_TO_PREPARING"
ACTION_CORRECT_TO_SUBMITTED = "CORRECT_TO_SUBMITTED"
ACTION_CORRECT_TO_WON = "CORRECT_TO_WON"
ACTION_CORRECT_TO_LOST = "CORRECT_TO_LOST"


def allowed_actions_for_status(status: TenderEngagementStatus) -> tuple[str, ...]:
    return {
        TenderEngagementStatus.SAVED: (ACTION_EVALUATE, ACTION_PREPARE_BID, ACTION_DISMISS),
        TenderEngagementStatus.EVALUATING: (ACTION_PREPARE_BID, ACTION_DISMISS),
        TenderEngagementStatus.PREPARING: (ACTION_MARK_SUBMITTED, ACTION_DISMISS),
        TenderEngagementStatus.SUBMITTED: (ACTION_RECORD_WON, ACTION_RECORD_LOST, ACTION_CORRECT_TO_PREPARING),
        TenderEngagementStatus.WON: (ACTION_CORRECT_TO_SUBMITTED, ACTION_CORRECT_TO_LOST),
        TenderEngagementStatus.LOST: (ACTION_CORRECT_TO_SUBMITTED, ACTION_CORRECT_TO_WON),
        TenderEngagementStatus.DISMISSED: (ACTION_SAVE, ACTION_EVALUATE, ACTION_PREPARE_BID),
    }[status]


@dataclass(frozen=True)
class LegacyEngagementView:
    """Preserve the legacy response contract without treating its UUID as a pursuit ID."""

    id: UUID
    tender_id: UUID
    status: TenderEngagementStatus
    origin: TenderEngagementOrigin
    created_at: datetime
    updated_at: datetime
    status_changed_at: datetime
    pursuit_id: UUID


def legacy_engagement_view(pursuit: OrganizationPursuit) -> LegacyEngagementView:
    if pursuit.legacy_engagement_id is None or pursuit.source_tender_id is None:
        raise TenderEngagementError("source pursuit lacks legacy compatibility identity")
    return LegacyEngagementView(
        id=pursuit.legacy_engagement_id,
        tender_id=pursuit.source_tender_id,
        status=pursuit.stage,
        origin=pursuit.legacy_origin or TenderEngagementOrigin.OTHER_EXPLICIT_USER_ACTION,
        created_at=pursuit.created_at,
        updated_at=pursuit.updated_at,
        status_changed_at=pursuit.stage_changed_at,
        pursuit_id=pursuit.id,
    )


@dataclass(frozen=True)
class TenderEngagementResolution:
    engagement: LegacyEngagementView
    created: bool


@dataclass(frozen=True)
class SaveTenderEngagementResult:
    engagement: LegacyEngagementView
    created: bool
    reengaged: bool


async def _context(db: AsyncSession, *, user_id: UUID, company_profile_id: UUID):
    try:
        return await resolve_legacy_profile_context(
            db, user_id=user_id, company_profile_id=company_profile_id
        )
    except OrganizationAccessDeniedError as exc:
        raise TenderEngagementOwnershipError(
            "company profile is not available through an active membership"
        ) from exc


async def get_tender_engagement(
    db: AsyncSession, *, user_id: UUID, company_profile_id: UUID, tender_id: UUID
) -> LegacyEngagementView | None:
    context = await _context(db, user_id=user_id, company_profile_id=company_profile_id)
    pursuit = await get_source_pursuit(
        db, organization_id=context.organization.id, tender_id=tender_id
    )
    return legacy_engagement_view(pursuit) if pursuit else None


async def get_or_create_tender_engagement(
    db: AsyncSession,
    *,
    user_id: UUID,
    company_profile_id: UUID,
    tender_id: UUID,
    status: TenderEngagementStatus,
    origin: TenderEngagementOrigin,
) -> TenderEngagementResolution:
    if status not in CREATABLE_STATUSES:
        raise TenderEngagementTransitionError(f"{status.value} is not a valid initial engagement status")
    if origin == TenderEngagementOrigin.LEGACY_PROPOSAL:
        raise TenderEngagementTransitionError("LEGACY_PROPOSAL origin is reserved for reconciliation")
    context = await _context(db, user_id=user_id, company_profile_id=company_profile_id)
    try:
        result = await get_or_create_source_pursuit(
            db,
            organization_id=context.organization.id,
            actor_user_id=user_id,
            actor_membership_id=context.membership.id,
            tender_id=tender_id,
            stage=status,
            legacy_origin=origin,
        )
    except PursuitNotFoundError as exc:
        raise TenderEngagementTenderNotFoundError("tender not found") from exc
    return TenderEngagementResolution(
        engagement=legacy_engagement_view(result.pursuit), created=result.created
    )


async def save_tender_to_my_tenders(
    db: AsyncSession, *, user_id: UUID, company_profile_id: UUID, tender_id: UUID
) -> SaveTenderEngagementResult:
    resolution = await get_or_create_tender_engagement(
        db, user_id=user_id, company_profile_id=company_profile_id,
        tender_id=tender_id, status=TenderEngagementStatus.SAVED,
        origin=TenderEngagementOrigin.MANUAL_SAVE,
    )
    if resolution.created or resolution.engagement.status != TenderEngagementStatus.DISMISSED:
        return SaveTenderEngagementResult(
            engagement=resolution.engagement, created=resolution.created, reengaged=False
        )
    engagement = await set_tender_engagement_status(
        db, user_id=user_id, company_profile_id=company_profile_id,
        tender_id=tender_id, status=TenderEngagementStatus.SAVED,
        expected_status=TenderEngagementStatus.DISMISSED,
    )
    return SaveTenderEngagementResult(engagement=engagement, created=False, reengaged=True)


async def set_tender_engagement_status(
    db: AsyncSession,
    *,
    user_id: UUID,
    company_profile_id: UUID,
    tender_id: UUID,
    status: TenderEngagementStatus,
    correction: bool = False,
    expected_status: TenderEngagementStatus | None = None,
) -> LegacyEngagementView:
    context = await _context(db, user_id=user_id, company_profile_id=company_profile_id)
    pursuit = await get_source_pursuit(
        db, organization_id=context.organization.id, tender_id=tender_id
    )
    if pursuit is None:
        raise TenderEngagementNotFoundError("engagement not found or access denied")
    try:
        if pursuit.stage in {TenderEngagementStatus.WON, TenderEngagementStatus.LOST} and status in {
            TenderEngagementStatus.SAVED, TenderEngagementStatus.EVALUATING, TenderEngagementStatus.PREPARING,
        }:
            changed = await reopen_pursuit(
                db, pursuit_id=pursuit.id, organization_id=context.organization.id,
                actor_user_id=user_id, actor_membership_id=context.membership.id,
                destination=status, expected_stage=expected_status,
                reason="Legacy compatibility reopen command",
            )
        else:
            changed = await transition_pursuit(
                db, pursuit_id=pursuit.id, organization_id=context.organization.id,
                actor_user_id=user_id, actor_membership_id=context.membership.id,
                stage=status, expected_stage=expected_status, correction=correction,
            )
    except PursuitNotFoundError as exc:
        raise TenderEngagementNotFoundError("engagement not found or access denied") from exc
    except PursuitTransitionError as exc:
        raise TenderEngagementTransitionError(str(exc)) from exc
    return legacy_engagement_view(changed)


async def mark_submitted(db: AsyncSession, **scope: UUID) -> LegacyEngagementView:
    return await set_tender_engagement_status(db, status=TenderEngagementStatus.SUBMITTED, **scope)


async def save(db: AsyncSession, **scope: UUID) -> LegacyEngagementView:
    return await set_tender_engagement_status(db, status=TenderEngagementStatus.SAVED, **scope)


async def evaluate(db: AsyncSession, **scope: UUID) -> LegacyEngagementView:
    return await set_tender_engagement_status(db, status=TenderEngagementStatus.EVALUATING, **scope)


async def prepare(db: AsyncSession, **scope: UUID) -> LegacyEngagementView:
    return await set_tender_engagement_status(db, status=TenderEngagementStatus.PREPARING, **scope)


async def mark_won(db: AsyncSession, **scope: UUID) -> LegacyEngagementView:
    return await set_tender_engagement_status(db, status=TenderEngagementStatus.WON, **scope)


async def mark_lost(db: AsyncSession, **scope: UUID) -> LegacyEngagementView:
    return await set_tender_engagement_status(db, status=TenderEngagementStatus.LOST, **scope)


async def dismiss(db: AsyncSession, **scope: UUID) -> LegacyEngagementView:
    return await set_tender_engagement_status(db, status=TenderEngagementStatus.DISMISSED, **scope)


async def correct_tender_engagement_status(
    db: AsyncSession, *, status: TenderEngagementStatus, **scope: UUID
) -> LegacyEngagementView:
    return await set_tender_engagement_status(db, status=status, correction=True, **scope)
