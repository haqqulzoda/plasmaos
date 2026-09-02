"""Bounded unified Tender Explorer read model."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import and_, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.endpoints.tenders import (
    _apply_tender_sort,
    _batched_tender_summaries,
    _serialize_tender,
    apply_explorer_tender_filters,
    resolve_filesystem_document_filter_tender_ids,
)
from app.core.tender_newness import tender_newness
from app.models.all_models import Tender
from app.models.audit import TenderRecommendation
from app.models.company import CompanyProfile
from app.models.engagement import TenderEngagement
from app.schemas.explorer import (
    ExplorerCounts,
    ExplorerPursuitSummary,
    ExplorerRecommendationSummary,
    ExplorerTenderItem,
    ExplorerTenderListResponse,
    ExplorerTenderSummary,
    ExplorerView,
    RecommendationAvailability,
)
from app.services.tender_engagements import allowed_actions_for_status
from app.services.tender_sources.uzex_scope import customer_visible_tender_condition


@dataclass(frozen=True)
class ExplorerQuery:
    view: ExplorerView = ExplorerView.ALL
    source: str | None = None
    source_system: str | None = None
    q: str | None = None
    region: list[str] | None = None
    country: str | None = None
    countries: list[str] | None = None
    service: str | None = None
    services: list[str] | None = None
    tender_status: str | None = None
    deadline_status: str | None = None
    deadline_from: datetime | None = None
    deadline_to: datetime | None = None
    price_min: float | None = None
    price_max: float | None = None
    document_status: str | None = None
    document_tender_ids: tuple[UUID, ...] | None = None
    category: str | None = None
    sort: str | None = None
    limit: int = 25
    offset: int = 0
    new_only: bool = False
    reference_time: datetime | None = None


def _filtered(statement, query: ExplorerQuery):
    return apply_explorer_tender_filters(
        statement,
        source=query.source,
        source_system=query.source_system,
        q=query.q,
        region=query.region,
        country=query.country,
        countries=query.countries,
        service=query.service,
        services=query.services,
        tender_status=query.tender_status,
        deadline_status=query.deadline_status,
        deadline_from=query.deadline_from,
        deadline_to=query.deadline_to,
        price_min=query.price_min,
        price_max=query.price_max,
        document_status=query.document_status,
        document_tender_ids=query.document_tender_ids,
        category=query.category,
        new_only=query.new_only,
        newness_reference_time=query.reference_time,
    )[0]


def _recommendation_order(statement, sort_value: str | None):
    normalized = (sort_value or "best_match").strip().casefold().replace("-", "_")
    if normalized in {"", "default", "best_match"}:
        return statement.order_by(
            TenderRecommendation.match_score.desc(),
            TenderRecommendation.created_at.desc(),
            TenderRecommendation.id.asc(),
        )
    return _apply_tender_sort(statement, normalized)


def _all_order(statement, sort_value: str | None):
    normalized = (sort_value or "newest").strip().casefold().replace("-", "_")
    if normalized == "best_match":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="best_match is supported only for recommended or dismissed view",
        )
    return _apply_tender_sort(statement, normalized)


def recommendation_summary(
    recommendation: TenderRecommendation | None,
) -> ExplorerRecommendationSummary | None:
    if recommendation is None:
        return None
    rationale = recommendation.strategic_rationale or ""
    return ExplorerRecommendationSummary(
        recommendation_id=recommendation.id,
        match_score=recommendation.match_score,
        rationale_summary=rationale[:280],
        is_dismissed=recommendation.is_dismissed,
        created_at=recommendation.created_at,
    )


def _pursuit_summary(
    engagement: TenderEngagement | None,
) -> ExplorerPursuitSummary | None:
    if engagement is None:
        return None
    return ExplorerPursuitSummary(
        engagement_id=engagement.id,
        status=engagement.status,
        allowed_actions=list(allowed_actions_for_status(engagement.status)),
    )


async def resolve_owned_profile_id(
    db: AsyncSession,
    *,
    user_id: UUID,
) -> UUID | None:
    """Resolve the schema-enforced single CompanyProfile for this exact user."""
    return await db.scalar(
        select(CompanyProfile.id).where(CompanyProfile.user_id == user_id)
    )


async def _filtered_counts(
    db: AsyncSession,
    *,
    profile_id: UUID | None,
    query: ExplorerQuery,
) -> ExplorerCounts:
    all_count = _filtered(
        select(func.count(Tender.id)).where(
            customer_visible_tender_condition(Tender)
        ),
        query,
    ).scalar_subquery()

    if profile_id is None:
        row = (
            await db.execute(
                select(
                    all_count.label("all_tenders"),
                    literal(0).label("active_recommendations"),
                    literal(0).label("dismissed_recommendations"),
                )
            )
        ).one()
    else:
        active_count = _filtered(
            select(func.count(TenderRecommendation.id))
            .select_from(TenderRecommendation)
            .join(Tender, Tender.id == TenderRecommendation.tender_id)
            .where(
                TenderRecommendation.company_profile_id == profile_id,
                TenderRecommendation.is_dismissed.is_(False),
                customer_visible_tender_condition(Tender),
            ),
            query,
        ).scalar_subquery()
        dismissed_count = _filtered(
            select(func.count(TenderRecommendation.id))
            .select_from(TenderRecommendation)
            .join(Tender, Tender.id == TenderRecommendation.tender_id)
            .where(
                TenderRecommendation.company_profile_id == profile_id,
                TenderRecommendation.is_dismissed.is_(True),
                customer_visible_tender_condition(Tender),
            ),
            query,
        ).scalar_subquery()
        row = (
            await db.execute(
                select(
                    all_count.label("all_tenders"),
                    active_count.label("active_recommendations"),
                    dismissed_count.label("dismissed_recommendations"),
                )
            )
        ).one()

    return ExplorerCounts(
        all_tenders=int(row.all_tenders or 0),
        active_recommendations=int(row.active_recommendations or 0),
        dismissed_recommendations=int(row.dismissed_recommendations or 0),
    )


def _owned_engagement_join(*, user_id: UUID, profile_id: UUID):
    return and_(
        TenderEngagement.tender_id == Tender.id,
        TenderEngagement.user_id == user_id,
        TenderEngagement.company_profile_id == profile_id,
    )


async def _page_rows(
    db: AsyncSession,
    *,
    user_id: UUID,
    profile_id: UUID | None,
    query: ExplorerQuery,
) -> list[tuple[Tender, TenderRecommendation | None, TenderEngagement | None]]:
    if query.view != ExplorerView.ALL and profile_id is None:
        return []

    if query.view == ExplorerView.ALL and profile_id is None:
        statement = _filtered(
            select(Tender).where(customer_visible_tender_condition(Tender)),
            query,
        )
        tenders = (
            await db.execute(
                _all_order(statement, query.sort)
                .offset(query.offset)
                .limit(query.limit)
            )
        ).scalars().all()
        return [(tender, None, None) for tender in tenders]

    assert profile_id is not None
    recommendation_join = and_(
        TenderRecommendation.tender_id == Tender.id,
        TenderRecommendation.company_profile_id == profile_id,
    )
    engagement_join = _owned_engagement_join(
        user_id=user_id,
        profile_id=profile_id,
    )
    if query.view == ExplorerView.ALL:
        statement = (
            select(Tender, TenderRecommendation, TenderEngagement)
            .outerjoin(TenderRecommendation, recommendation_join)
            .outerjoin(TenderEngagement, engagement_join)
            .where(customer_visible_tender_condition(Tender))
        )
        statement = _all_order(_filtered(statement, query), query.sort)
    else:
        dismissed = query.view == ExplorerView.DISMISSED
        statement = (
            select(Tender, TenderRecommendation, TenderEngagement)
            .select_from(TenderRecommendation)
            .join(Tender, Tender.id == TenderRecommendation.tender_id)
            .outerjoin(TenderEngagement, engagement_join)
            .where(
                TenderRecommendation.company_profile_id == profile_id,
                TenderRecommendation.is_dismissed.is_(dismissed),
                customer_visible_tender_condition(Tender),
            )
        )
        statement = _recommendation_order(_filtered(statement, query), query.sort)

    return (
        await db.execute(
            statement.offset(query.offset).limit(query.limit)
        )
    ).all()


async def list_explorer_tenders(
    db: AsyncSession,
    *,
    user_id: UUID,
    query: ExplorerQuery,
) -> ExplorerTenderListResponse:
    """Run fixed-count SQL reads and bounded response-only composition."""
    server_time = datetime.now(timezone.utc)
    query = replace(query, reference_time=server_time)
    profile_id = await resolve_owned_profile_id(db, user_id=user_id)
    document_tender_ids = await resolve_filesystem_document_filter_tender_ids(
        db=db,
        document_status=query.document_status,
    )
    if document_tender_ids is not None:
        query = replace(query, document_tender_ids=document_tender_ids)
    availability = (
        RecommendationAvailability.AVAILABLE
        if profile_id is not None
        else RecommendationAvailability.PROFILE_REQUIRED
    )
    counts = await _filtered_counts(db, profile_id=profile_id, query=query)
    rows = await _page_rows(
        db,
        user_id=user_id,
        profile_id=profile_id,
        query=query,
    )
    summaries = await _batched_tender_summaries(
        db=db,
        tender_ids=[tender.id for tender, _recommendation, _engagement in rows],
    )

    items: list[ExplorerTenderItem] = []
    for tender, recommendation, engagement in rows:
        serialized = _serialize_tender(tender, summary=summaries.get(tender.id))
        newness = tender_newness(serialized.created_at, server_time=server_time)
        items.append(
            ExplorerTenderItem(
                tender=ExplorerTenderSummary(
                    id=serialized.id,
                    external_id=serialized.external_id,
                    source_system=serialized.source_system,
                    canonical_source_key=serialized.canonical_source_key,
                    source_url=serialized.source_url,
                    title=serialized.title,
                    buyer=serialized.buyer,
                    budget=serialized.budget,
                    currency=serialized.currency,
                    deadline=serialized.deadline,
                    publication_date=serialized.publication_date,
                    country=serialized.country,
                    region=serialized.region,
                    sector=serialized.sector,
                    status=serialized.status,
                    category=serialized.category,
                    document_status=serialized.document_status,
                    document_count=serialized.document_count,
                    created_at=newness.created_at,
                    is_new=newness.is_new,
                    new_until=newness.new_until,
                ),
                recommendation=recommendation_summary(recommendation),
                pursuit=_pursuit_summary(engagement),
            )
        )

    total = {
        ExplorerView.ALL: counts.all_tenders,
        ExplorerView.RECOMMENDED: counts.active_recommendations,
        ExplorerView.DISMISSED: counts.dismissed_recommendations,
    }[query.view]
    return ExplorerTenderListResponse(
        view=query.view,
        items=items,
        total=total,
        limit=query.limit,
        offset=query.offset,
        counts=counts,
        recommendation_availability=availability,
        server_time=server_time,
    )


__all__ = [
    "ExplorerQuery",
    "list_explorer_tenders",
    "recommendation_summary",
    "resolve_owned_profile_id",
]
