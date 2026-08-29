"""Canonical customer API for the engagement-backed My Tenders surface."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_approved_pilot_access
from app.core.security import authenticated_dependency
from app.db.session import get_db
from app.models.all_models import Proposal, TenderEngagement, User
from app.models.base import TenderEngagementStatus, TenderStatus
from app.models.company import CompanyProfile
from app.schemas.engagement import (
    MyTenderListItem,
    MyTendersListResponse,
    SaveToMyTendersResponse,
    TenderEngagementActionRequest,
    TenderEngagementActionResponse,
    TenderEngagementSummary,
    TenderScopedEngagementResponse,
)
from app.services.my_tenders import MyTendersQuery, get_owned_my_tender_item, list_my_tenders
from app.services.tender_engagements import (
    ACTION_CORRECT_TO_LOST,
    ACTION_CORRECT_TO_PREPARING,
    ACTION_CORRECT_TO_SUBMITTED,
    ACTION_CORRECT_TO_WON,
    ACTION_DISMISS,
    ACTION_EVALUATE,
    ACTION_MARK_SUBMITTED,
    ACTION_RECORD_LOST,
    ACTION_RECORD_WON,
    TenderEngagementNotFoundError,
    TenderEngagementTenderNotFoundError,
    TenderEngagementTransitionError,
    allowed_actions_for_status,
    correct_tender_engagement_status,
    dismiss,
    evaluate,
    get_tender_engagement,
    mark_lost,
    mark_submitted,
    mark_won,
    save_tender_to_my_tenders,
)


router = APIRouter(
    dependencies=[
        authenticated_dependency(),
        Depends(require_approved_pilot_access),
    ]
)

StatusFilter = Literal[
    "ACTIVE",
    "ALL",
    "SAVED",
    "EVALUATING",
    "PREPARING",
    "SUBMITTED",
    "WON",
    "LOST",
    "DISMISSED",
]
SortOption = Literal["recently_updated", "recently_added", "deadline_soonest"]
SourceFilter = Literal["uzex", "world_bank", "adb", "giz", "ebrd"]


async def _owned_profile_id(
    db: AsyncSession,
    current_user: User,
) -> UUID:
    profile_id = await db.scalar(
        select(CompanyProfile.id).where(CompanyProfile.user_id == current_user.id)
    )
    if profile_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company profile not found",
        )
    return profile_id


def _summary(engagement) -> TenderEngagementSummary:
    return TenderEngagementSummary(
        engagement_id=engagement.id,
        tender_id=engagement.tender_id,
        engagement_status=engagement.status,
        engagement_origin=engagement.origin,
        engagement_created_at=engagement.created_at,
        engagement_updated_at=engagement.updated_at,
        status_changed_at=engagement.status_changed_at,
        allowed_actions=list(allowed_actions_for_status(engagement.status)),
    )


@router.get("/my-tenders", response_model=MyTendersListResponse)
async def get_my_tenders(
    engagement_status: StatusFilter = Query(default="ACTIVE", alias="status"),
    source: SourceFilter | None = Query(default=None),
    tender_status: TenderStatus | None = Query(default=None),
    search: str | None = Query(default=None, max_length=200),
    sort_by: SortOption = Query(default="recently_updated", alias="sort"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MyTendersListResponse:
    profile_id = await _owned_profile_id(db, current_user)
    return await list_my_tenders(
        db,
        user_id=current_user.id,
        company_profile_id=profile_id,
        query=MyTendersQuery(
            status=engagement_status,
            source_system=source,
            tender_status=tender_status,
            search=search.strip() if search and search.strip() else None,
            sort=sort_by,
            offset=offset,
            limit=limit,
        ),
    )


@router.get("/my-tenders/{engagement_id}", response_model=MyTenderListItem)
async def get_my_tender(
    engagement_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MyTenderListItem:
    profile_id = await _owned_profile_id(db, current_user)
    item = await get_owned_my_tender_item(
        db,
        engagement_id=engagement_id,
        user_id=current_user.id,
        company_profile_id=profile_id,
    )
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="My Tender not found",
        )
    return item


@router.get(
    "/tenders/{tender_id}/engagement",
    response_model=TenderScopedEngagementResponse,
)
async def get_tender_engagement_for_current_user(
    tender_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TenderScopedEngagementResponse:
    profile_id = await _owned_profile_id(db, current_user)
    engagement = await get_tender_engagement(
        db,
        user_id=current_user.id,
        company_profile_id=profile_id,
        tender_id=tender_id,
    )
    proposal_id = await db.scalar(
        select(Proposal.id)
        .where(
            Proposal.user_id == current_user.id,
            Proposal.tender_id == tender_id,
        )
        .order_by(Proposal.created_at.asc(), Proposal.id.asc())
        .limit(1)
    )
    return TenderScopedEngagementResponse(
        engagement=_summary(engagement) if engagement else None,
        proposal_id=proposal_id,
    )


@router.post(
    "/tenders/{tender_id}/engagement",
    response_model=SaveToMyTendersResponse,
)
async def save_tender_for_current_user(
    tender_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SaveToMyTendersResponse:
    profile_id = await _owned_profile_id(db, current_user)
    try:
        result = await save_tender_to_my_tenders(
            db,
            user_id=current_user.id,
            company_profile_id=profile_id,
            tender_id=tender_id,
        )
    except TenderEngagementTenderNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tender not found",
        ) from exc
    except TenderEngagementTransitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    return SaveToMyTendersResponse(
        engagement=_summary(result.engagement),
        created=result.created,
        reengaged=result.reengaged,
    )


EngagementAction = Literal[
    "evaluate",
    "mark-submitted",
    "mark-won",
    "mark-lost",
    "dismiss",
    "correct-to-preparing",
    "correct-to-submitted",
    "correct-to-won",
    "correct-to-lost",
]


@router.post(
    "/my-tenders/{engagement_id}/actions/{action}",
    response_model=TenderEngagementActionResponse,
)
async def apply_tender_engagement_action(
    engagement_id: UUID,
    action: EngagementAction,
    command: TenderEngagementActionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TenderEngagementActionResponse:
    """Apply one explicit, tenant-scoped lifecycle command."""
    profile_id = await _owned_profile_id(db, current_user)
    owned_tender_id = await db.scalar(
        select(TenderEngagement.tender_id).where(
            TenderEngagement.id == engagement_id,
            TenderEngagement.user_id == current_user.id,
            TenderEngagement.company_profile_id == profile_id,
        )
    )
    if owned_tender_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="My Tender not found",
        )

    scope = {
        "user_id": current_user.id,
        "company_profile_id": profile_id,
        "tender_id": owned_tender_id,
        "expected_status": command.expected_status,
    }
    normal_commands: dict[str, Callable[..., Awaitable]] = {
        "evaluate": evaluate,
        "mark-submitted": mark_submitted,
        "mark-won": mark_won,
        "mark-lost": mark_lost,
        "dismiss": dismiss,
    }
    correction_targets = {
        "correct-to-preparing": TenderEngagementStatus.PREPARING,
        "correct-to-submitted": TenderEngagementStatus.SUBMITTED,
        "correct-to-won": TenderEngagementStatus.WON,
        "correct-to-lost": TenderEngagementStatus.LOST,
    }
    expected_contract = {
        "evaluate": ACTION_EVALUATE,
        "mark-submitted": ACTION_MARK_SUBMITTED,
        "mark-won": ACTION_RECORD_WON,
        "mark-lost": ACTION_RECORD_LOST,
        "dismiss": ACTION_DISMISS,
        "correct-to-preparing": ACTION_CORRECT_TO_PREPARING,
        "correct-to-submitted": ACTION_CORRECT_TO_SUBMITTED,
        "correct-to-won": ACTION_CORRECT_TO_WON,
        "correct-to-lost": ACTION_CORRECT_TO_LOST,
    }
    if expected_contract[action] not in allowed_actions_for_status(command.expected_status):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Action is not available from {command.expected_status.value}",
        )
    try:
        if action in normal_commands:
            engagement = await normal_commands[action](db, **scope)
        else:
            engagement = await correct_tender_engagement_status(
                db,
                status=correction_targets[action],
                **scope,
            )
    except TenderEngagementNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="My Tender not found",
        ) from exc
    except TenderEngagementTransitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    return TenderEngagementActionResponse(engagement=_summary(engagement))
