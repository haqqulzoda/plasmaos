"""Unified Tender Explorer and canonical Recommendation commands."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_approved_pilot_access, require_explorer_access
from app.core.security import authenticated_dependency
from app.db.session import get_db
from app.models.all_models import User
from app.schemas.explorer import (
    ExplorerTenderListResponse,
    ExplorerView,
    RecommendationCommandResponse,
)
from app.services.explorer import (
    ExplorerQuery,
    list_explorer_tenders,
    recommendation_summary,
)
from app.services.recommendations import (
    RecommendationNotFoundError,
    dismiss_recommendation,
    restore_recommendation,
)


router = APIRouter(dependencies=[authenticated_dependency()])


@router.get(
    "/explorer/tenders",
    response_model=ExplorerTenderListResponse,
)
async def get_explorer_tenders(
    view: ExplorerView = Query(default=ExplorerView.ALL),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    source: str | None = Query(default=None),
    source_system: str | None = Query(default=None),
    q: str | None = Query(default=None, max_length=200),
    region: list[str] | None = Query(default=None),
    country: str | None = Query(default=None),
    countries: list[str] | None = Query(default=None),
    service: str | None = Query(default=None),
    services: list[str] | None = Query(default=None),
    tender_status: str | None = Query(default=None, alias="status"),
    deadline_status: str | None = Query(default=None),
    deadline_from: datetime | None = Query(default=None),
    deadline_to: datetime | None = Query(default=None),
    price_min: float | None = Query(default=None, ge=0),
    price_max: float | None = Query(default=None, ge=0),
    document_status: str | None = Query(default=None),
    category: str | None = Query(default=None),
    sort: str | None = Query(default=None),
    new_only: bool = Query(
        default=False,
        description="Return only Tenders first persisted by Plasma in the last 24 hours.",
    ),
    current_user: User = Depends(require_explorer_access),
    db: AsyncSession = Depends(get_db),
) -> ExplorerTenderListResponse:
    """Return one filtered universe with a nullable owned advisory overlay."""
    return await list_explorer_tenders(
        db,
        user_id=current_user.id,
        query=ExplorerQuery(
            view=view,
            source=source,
            source_system=source_system,
            q=q,
            region=region,
            country=country,
            countries=countries,
            service=service,
            services=services,
            tender_status=tender_status,
            deadline_status=deadline_status,
            deadline_from=deadline_from,
            deadline_to=deadline_to,
            price_min=price_min,
            price_max=price_max,
            document_status=document_status,
            category=category,
            sort=sort,
            new_only=new_only,
            limit=limit,
            offset=offset,
        ),
    )


async def _recommendation_command(
    *,
    recommendation_id: UUID,
    current_user: User,
    db: AsyncSession,
    restore: bool,
) -> RecommendationCommandResponse:
    command = restore_recommendation if restore else dismiss_recommendation
    try:
        recommendation = await command(
            db,
            recommendation_id=recommendation_id,
            user_id=current_user.id,
        )
    except RecommendationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recommendation not found or access denied.",
        ) from exc
    summary = recommendation_summary(recommendation)
    assert summary is not None
    return RecommendationCommandResponse(
        status="restored" if restore else "dismissed",
        recommendation=summary,
    )


@router.post(
    "/recommendations/{recommendation_id}/dismiss",
    response_model=RecommendationCommandResponse,
)
async def dismiss_owned_recommendation(
    recommendation_id: UUID,
    current_user: User = Depends(require_approved_pilot_access),
    db: AsyncSession = Depends(get_db),
) -> RecommendationCommandResponse:
    return await _recommendation_command(
        recommendation_id=recommendation_id,
        current_user=current_user,
        db=db,
        restore=False,
    )


@router.post(
    "/recommendations/{recommendation_id}/restore",
    response_model=RecommendationCommandResponse,
)
async def restore_owned_recommendation(
    recommendation_id: UUID,
    current_user: User = Depends(require_approved_pilot_access),
    db: AsyncSession = Depends(get_db),
) -> RecommendationCommandResponse:
    return await _recommendation_command(
        recommendation_id=recommendation_id,
        current_user=current_user,
        db=db,
        restore=True,
    )
