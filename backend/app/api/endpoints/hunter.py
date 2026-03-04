"""
Plasma AI - Hunter Feed Endpoints

API for autonomous Tender Recommendations: fetch the personalised feed
and dismiss individual recommendations.
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.api.deps import get_current_user
from app.core.security import authenticated_dependency
from app.db.session import get_db
from app.models.all_models import User
from app.models.audit import TenderRecommendation
from app.models.company import CompanyProfile

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[authenticated_dependency()])


# ── Response schemas ────────────────────────────────────────────


class HunterTenderPayload(BaseModel):
    id: str
    title: str
    budget: float
    currency: str
    deadline: str | None

    class Config:
        from_attributes = True


class HunterRecommendationPayload(BaseModel):
    id: str
    match_score: int
    strategic_rationale: str
    created_at: str
    tender: HunterTenderPayload

    class Config:
        from_attributes = True


class DismissResponse(BaseModel):
    status: str
    message: str


# ── Routes ──────────────────────────────────────────────────────


@router.get("", response_model=list[HunterRecommendationPayload])
@router.get("/", response_model=list[HunterRecommendationPayload], include_in_schema=False)
async def list_recommendations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Fetch all non-dismissed TenderRecommendation records for the
    current user, ordered by match_score descending.
    """
    # Resolve the user's company profile
    profile_result = await db.execute(
        select(CompanyProfile.id).where(
            CompanyProfile.user_id == current_user.id
        )
    )
    profile_id = profile_result.scalar_one_or_none()

    if profile_id is None:
        return []

    # Fetch non-dismissed recommendations with eager-loaded tender
    stmt = (
        select(TenderRecommendation)
        .options(joinedload(TenderRecommendation.tender))
        .where(
            TenderRecommendation.company_profile_id == profile_id,
            TenderRecommendation.is_dismissed == False,  # noqa: E712
        )
        .order_by(TenderRecommendation.match_score.desc())
    )
    result = await db.execute(stmt)
    recommendations = result.scalars().unique().all()

    # Serialise
    payload: list[dict] = []
    for rec in recommendations:
        tender = rec.tender
        payload.append(
            {
                "id": str(rec.id),
                "match_score": rec.match_score,
                "strategic_rationale": rec.strategic_rationale,
                "created_at": rec.created_at.isoformat() if rec.created_at else "",
                "tender": {
                    "id": str(tender.id),
                    "title": tender.title,
                    "budget": tender.budget,
                    "currency": tender.currency,
                    "deadline": (
                        tender.deadline.isoformat() if tender.deadline else None
                    ),
                },
            }
        )

    return payload


@router.post(
    "/{recommendation_id}/dismiss",
    response_model=DismissResponse,
)
async def dismiss_recommendation(
    recommendation_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Set is_dismissed = True for a specific recommendation.
    Ownership is verified through company_profile → user_id.
    """
    stmt = (
        select(TenderRecommendation)
        .join(CompanyProfile)
        .where(
            TenderRecommendation.id == recommendation_id,
            CompanyProfile.user_id == current_user.id,
        )
    )
    result = await db.execute(stmt)
    rec = result.scalar_one_or_none()

    if rec is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recommendation not found or access denied.",
        )

    rec.is_dismissed = True
    await db.flush()

    return {"status": "ok", "message": "Recommendation dismissed."}
