"""Canonical, tenant-owned Recommendation command service."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import TenderRecommendation
from app.models.company import CompanyProfile


class RecommendationNotFoundError(RuntimeError):
    """The requested Recommendation is absent or outside the owner scope."""


async def _set_recommendation_dismissed(
    db: AsyncSession,
    *,
    recommendation_id: UUID,
    user_id: UUID,
    dismissed: bool,
) -> TenderRecommendation:
    """Lock and mutate only ``is_dismissed`` on one owned canonical row."""
    recommendation = await db.scalar(
        select(TenderRecommendation)
        .join(
            CompanyProfile,
            CompanyProfile.id == TenderRecommendation.company_profile_id,
        )
        .where(
            TenderRecommendation.id == recommendation_id,
            CompanyProfile.user_id == user_id,
        )
        .with_for_update()
    )
    if recommendation is None:
        raise RecommendationNotFoundError(
            "recommendation not found or access denied"
        )
    if recommendation.is_dismissed != dismissed:
        recommendation.is_dismissed = dismissed
        await db.flush()
    return recommendation


async def dismiss_recommendation(
    db: AsyncSession,
    *,
    recommendation_id: UUID,
    user_id: UUID,
) -> TenderRecommendation:
    """Idempotently dismiss an owned Recommendation without regeneration."""
    return await _set_recommendation_dismissed(
        db,
        recommendation_id=recommendation_id,
        user_id=user_id,
        dismissed=True,
    )


async def restore_recommendation(
    db: AsyncSession,
    *,
    recommendation_id: UUID,
    user_id: UUID,
) -> TenderRecommendation:
    """Idempotently restore the same owned Recommendation row."""
    return await _set_recommendation_dismissed(
        db,
        recommendation_id=recommendation_id,
        user_id=user_id,
        dismissed=False,
    )
