"""Canonical creation and lifecycle rules for tender engagements."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.all_models import CompanyProfile, Tender, TenderEngagement
from app.models.base import TenderEngagementOrigin, TenderEngagementStatus


class TenderEngagementError(RuntimeError):
    """Base error for the canonical engagement service."""


class TenderEngagementOwnershipError(TenderEngagementError):
    """The profile does not belong to the supplied user."""


class TenderEngagementTenderNotFoundError(TenderEngagementError):
    """The canonical tender does not exist."""


class TenderEngagementNotFoundError(TenderEngagementError):
    """No owned engagement exists for the requested identity."""


class TenderEngagementTransitionError(TenderEngagementError):
    """The requested lifecycle transition is not allowed."""


NORMAL_TRANSITIONS: dict[TenderEngagementStatus, frozenset[TenderEngagementStatus]] = {
    TenderEngagementStatus.SAVED: frozenset(
        {
            TenderEngagementStatus.EVALUATING,
            TenderEngagementStatus.PREPARING,
            TenderEngagementStatus.DISMISSED,
        }
    ),
    TenderEngagementStatus.EVALUATING: frozenset(
        {
            TenderEngagementStatus.SAVED,
            TenderEngagementStatus.PREPARING,
            TenderEngagementStatus.DISMISSED,
        }
    ),
    TenderEngagementStatus.PREPARING: frozenset(
        {
            TenderEngagementStatus.SAVED,
            TenderEngagementStatus.EVALUATING,
            TenderEngagementStatus.SUBMITTED,
            TenderEngagementStatus.DISMISSED,
        }
    ),
    TenderEngagementStatus.SUBMITTED: frozenset(
        {
            TenderEngagementStatus.WON,
            TenderEngagementStatus.LOST,
        }
    ),
    TenderEngagementStatus.WON: frozenset(),
    TenderEngagementStatus.LOST: frozenset(),
    TenderEngagementStatus.DISMISSED: frozenset(
        {
            TenderEngagementStatus.SAVED,
            TenderEngagementStatus.EVALUATING,
            TenderEngagementStatus.PREPARING,
        }
    ),
}

# Corrections are deliberately separate from normal lifecycle commands. They
# repair a recorded submission/outcome; they do not infer one from other data.
CORRECTION_TRANSITIONS: dict[
    TenderEngagementStatus,
    frozenset[TenderEngagementStatus],
] = {
    TenderEngagementStatus.SUBMITTED: frozenset(
        {TenderEngagementStatus.PREPARING}
    ),
    TenderEngagementStatus.WON: frozenset(
        {TenderEngagementStatus.SUBMITTED, TenderEngagementStatus.LOST}
    ),
    TenderEngagementStatus.LOST: frozenset(
        {TenderEngagementStatus.SUBMITTED, TenderEngagementStatus.WON}
    ),
}

CREATABLE_STATUSES = frozenset(
    {
        TenderEngagementStatus.SAVED,
        TenderEngagementStatus.EVALUATING,
        TenderEngagementStatus.PREPARING,
    }
)


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
    """Return the shared customer command contract for a canonical state."""
    return {
        TenderEngagementStatus.SAVED: (
            ACTION_EVALUATE,
            ACTION_PREPARE_BID,
            ACTION_DISMISS,
        ),
        TenderEngagementStatus.EVALUATING: (
            ACTION_PREPARE_BID,
            ACTION_DISMISS,
        ),
        TenderEngagementStatus.PREPARING: (
            ACTION_MARK_SUBMITTED,
            ACTION_DISMISS,
        ),
        TenderEngagementStatus.SUBMITTED: (
            ACTION_RECORD_WON,
            ACTION_RECORD_LOST,
            ACTION_CORRECT_TO_PREPARING,
        ),
        TenderEngagementStatus.WON: (
            ACTION_CORRECT_TO_SUBMITTED,
            ACTION_CORRECT_TO_LOST,
        ),
        TenderEngagementStatus.LOST: (
            ACTION_CORRECT_TO_SUBMITTED,
            ACTION_CORRECT_TO_WON,
        ),
        TenderEngagementStatus.DISMISSED: (
            ACTION_SAVE,
            ACTION_EVALUATE,
            ACTION_PREPARE_BID,
        ),
    }[status]


@dataclass(frozen=True)
class TenderEngagementResolution:
    engagement: TenderEngagement
    created: bool


@dataclass(frozen=True)
class SaveTenderEngagementResult:
    engagement: TenderEngagement
    created: bool
    reengaged: bool


def transition_is_allowed(
    current: TenderEngagementStatus,
    target: TenderEngagementStatus,
    *,
    correction: bool = False,
) -> bool:
    """Return whether an explicit lifecycle command may make this transition."""
    matrix = CORRECTION_TRANSITIONS if correction else NORMAL_TRANSITIONS
    return target in matrix.get(current, frozenset())


async def _require_valid_scope(
    db: AsyncSession,
    *,
    user_id: UUID,
    company_profile_id: UUID,
    tender_id: UUID,
) -> None:
    profile_id = await db.scalar(
        select(CompanyProfile.id).where(
            CompanyProfile.id == company_profile_id,
            CompanyProfile.user_id == user_id,
        )
    )
    if profile_id is None:
        raise TenderEngagementOwnershipError(
            "company profile is not owned by the authenticated user"
        )

    canonical_tender_id = await db.scalar(
        select(Tender.id).where(Tender.id == tender_id)
    )
    if canonical_tender_id is None:
        raise TenderEngagementTenderNotFoundError("tender not found")


async def get_tender_engagement(
    db: AsyncSession,
    *,
    user_id: UUID,
    company_profile_id: UUID,
    tender_id: UUID,
) -> TenderEngagement | None:
    """Read one engagement only through its complete canonical owner scope."""
    return await db.scalar(
        select(TenderEngagement).where(
            TenderEngagement.user_id == user_id,
            TenderEngagement.company_profile_id == company_profile_id,
            TenderEngagement.tender_id == tender_id,
        )
    )


async def get_or_create_tender_engagement(
    db: AsyncSession,
    *,
    user_id: UUID,
    company_profile_id: UUID,
    tender_id: UUID,
    status: TenderEngagementStatus,
    origin: TenderEngagementOrigin,
) -> TenderEngagementResolution:
    """Create once with PostgreSQL conflict handling; never mutate an existing row.

    The caller owns the transaction and must commit or roll it back. The unique
    constraint plus ``ON CONFLICT DO NOTHING`` makes concurrent creation an
    expected, reusable result instead of an integrity-error response.
    """
    if status not in CREATABLE_STATUSES:
        raise TenderEngagementTransitionError(
            f"{status.value} is not a valid initial engagement status"
        )
    if origin == TenderEngagementOrigin.LEGACY_PROPOSAL:
        raise TenderEngagementTransitionError(
            "LEGACY_PROPOSAL origin is reserved for an approved reconciliation"
        )

    await _require_valid_scope(
        db,
        user_id=user_id,
        company_profile_id=company_profile_id,
        tender_id=tender_id,
    )

    engagement_id = uuid4()
    inserted_id = await db.scalar(
        pg_insert(TenderEngagement)
        .values(
            id=engagement_id,
            user_id=user_id,
            company_profile_id=company_profile_id,
            tender_id=tender_id,
            status=status,
            origin=origin,
        )
        .on_conflict_do_nothing(
            constraint="uq_tender_engagements_owner_tender"
        )
        .returning(TenderEngagement.id)
    )
    engagement = await get_tender_engagement(
        db,
        user_id=user_id,
        company_profile_id=company_profile_id,
        tender_id=tender_id,
    )
    if engagement is None:  # Defensive: the insert/select must be atomic here.
        raise TenderEngagementError("engagement resolution failed")
    return TenderEngagementResolution(
        engagement=engagement,
        created=inserted_id == engagement_id,
    )


async def save_tender_to_my_tenders(
    db: AsyncSession,
    *,
    user_id: UUID,
    company_profile_id: UUID,
    tender_id: UUID,
) -> SaveTenderEngagementResult:
    """Apply the explicit Save command without downgrading a higher state."""
    resolution = await get_or_create_tender_engagement(
        db,
        user_id=user_id,
        company_profile_id=company_profile_id,
        tender_id=tender_id,
        status=TenderEngagementStatus.SAVED,
        origin=TenderEngagementOrigin.MANUAL_SAVE,
    )
    if resolution.created:
        return SaveTenderEngagementResult(
            engagement=resolution.engagement,
            created=True,
            reengaged=False,
        )
    if resolution.engagement.status != TenderEngagementStatus.DISMISSED:
        return SaveTenderEngagementResult(
            engagement=resolution.engagement,
            created=False,
            reengaged=False,
        )

    try:
        engagement = await set_tender_engagement_status(
            db,
            user_id=user_id,
            company_profile_id=company_profile_id,
            tender_id=tender_id,
            status=TenderEngagementStatus.SAVED,
        )
        reengaged = True
    except TenderEngagementTransitionError:
        # A concurrent Save may have completed the same re-engagement while this
        # transaction waited for the row lock. Re-read and accept only SAVED.
        engagement = await get_tender_engagement(
            db,
            user_id=user_id,
            company_profile_id=company_profile_id,
            tender_id=tender_id,
        )
        if engagement is None or engagement.status != TenderEngagementStatus.SAVED:
            raise
        reengaged = False
    return SaveTenderEngagementResult(
        engagement=engagement,
        created=False,
        reengaged=reengaged,
    )


async def set_tender_engagement_status(
    db: AsyncSession,
    *,
    user_id: UUID,
    company_profile_id: UUID,
    tender_id: UUID,
    status: TenderEngagementStatus,
    correction: bool = False,
    expected_status: TenderEngagementStatus | None = None,
) -> TenderEngagement:
    """Lock, authorize, validate, and mutate one engagement in caller transaction."""
    engagement = await db.scalar(
        select(TenderEngagement)
        .where(
            TenderEngagement.user_id == user_id,
            TenderEngagement.company_profile_id == company_profile_id,
            TenderEngagement.tender_id == tender_id,
        )
        .with_for_update()
    )
    if engagement is None:
        raise TenderEngagementNotFoundError("engagement not found or access denied")
    if expected_status is not None and engagement.status != expected_status:
        raise TenderEngagementTransitionError(
            "stale engagement status: "
            f"expected {expected_status.value}, found {engagement.status.value}"
        )
    if not transition_is_allowed(engagement.status, status, correction=correction):
        command = "correction" if correction else "transition"
        raise TenderEngagementTransitionError(
            f"invalid engagement {command}: {engagement.status.value} -> {status.value}"
        )

    changed_at = datetime.now(timezone.utc)
    engagement.status = status
    engagement.status_changed_at = changed_at
    engagement.updated_at = changed_at
    await db.flush()
    return engagement


async def mark_submitted(db: AsyncSession, **scope: UUID) -> TenderEngagement:
    return await set_tender_engagement_status(
        db, status=TenderEngagementStatus.SUBMITTED, **scope
    )


async def save(db: AsyncSession, **scope: UUID) -> TenderEngagement:
    return await set_tender_engagement_status(
        db, status=TenderEngagementStatus.SAVED, **scope
    )


async def evaluate(db: AsyncSession, **scope: UUID) -> TenderEngagement:
    return await set_tender_engagement_status(
        db, status=TenderEngagementStatus.EVALUATING, **scope
    )


async def prepare(db: AsyncSession, **scope: UUID) -> TenderEngagement:
    return await set_tender_engagement_status(
        db, status=TenderEngagementStatus.PREPARING, **scope
    )


async def mark_won(db: AsyncSession, **scope: UUID) -> TenderEngagement:
    return await set_tender_engagement_status(
        db, status=TenderEngagementStatus.WON, **scope
    )


async def mark_lost(db: AsyncSession, **scope: UUID) -> TenderEngagement:
    return await set_tender_engagement_status(
        db, status=TenderEngagementStatus.LOST, **scope
    )


async def dismiss(db: AsyncSession, **scope: UUID) -> TenderEngagement:
    return await set_tender_engagement_status(
        db, status=TenderEngagementStatus.DISMISSED, **scope
    )


async def correct_tender_engagement_status(
    db: AsyncSession,
    *,
    status: TenderEngagementStatus,
    **scope: UUID,
) -> TenderEngagement:
    return await set_tender_engagement_status(
        db,
        status=status,
        correction=True,
        **scope,
    )
