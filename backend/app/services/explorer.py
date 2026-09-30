"""Bounded unified Tender Explorer read model."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import and_, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

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
from app.models.base import MembershipState
from app.models.tenancy import Membership, Organization, OrganizationPursuit
from app.schemas.explorer import (
    ExplorerCounts,
    ExplorerProfileMatch,
    ExplorerPursuitSummary,
    ExplorerRecommendationSummary,
    ExplorerTenderItem,
    ExplorerTenderListResponse,
    ExplorerTenderSummary,
    ExplorerView,
    RecommendationAvailability,
)
from app.services.profile_match import (
    ProfileTargets,
    profile_match_condition,
    profile_targets,
    tender_profile_match,
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


def _profile_match_order(statement, sort_value: str | None):
    """"Matches your profile" is ordered by deadline, soonest first (D1-08).

    ``best_match`` is accepted for older clients and means the same; there is no score.
    """
    normalized = (sort_value or "deadline_soonest").strip().casefold().replace("-", "_")
    if normalized in {"", "default", "best_match"}:
        normalized = "deadline_soonest"
    return _apply_tender_sort(statement, normalized)


def _profile_match_scope(targets: ProfileTargets, reference_time: datetime | None):
    """Visible tenders with at least one profile match whose deadline has not passed."""
    now = reference_time or datetime.now(timezone.utc)
    return and_(
        customer_visible_tender_condition(Tender),
        profile_match_condition(targets),
        or_(Tender.deadline.is_(None), Tender.deadline >= now),
    )


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
    engagement: OrganizationPursuit | None,
) -> ExplorerPursuitSummary | None:
    if engagement is None or engagement.legacy_engagement_id is None:
        return None
    return ExplorerPursuitSummary(
        engagement_id=engagement.legacy_engagement_id,
        status=engagement.stage,
        allowed_actions=list(allowed_actions_for_status(engagement.stage)),
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


async def owned_profile_targets(
    db: AsyncSession,
    *,
    user_id: UUID,
) -> tuple[UUID | None, ProfileTargets]:
    """The viewer's single CompanyProfile id and its normalized targets, in one read."""
    row = (
        await db.execute(
            select(
                CompanyProfile.id,
                CompanyProfile.target_countries,
                CompanyProfile.target_regions,
                CompanyProfile.target_services,
            ).where(CompanyProfile.user_id == user_id)
        )
    ).first()
    if row is None:
        return None, ProfileTargets()
    return row[0], profile_targets(row[1], row[2], row[3])


async def _filtered_counts(
    db: AsyncSession,
    *,
    profile_id: UUID | None,
    query: ExplorerQuery,
    targets: ProfileTargets = ProfileTargets(),
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
        # "Matches your profile" (D1-08): a deterministic count, not stored recommendations.
        active_count = (
            literal(0)
            if targets.empty
            else _filtered(
                select(func.count(Tender.id)).where(_profile_match_scope(targets, query.reference_time)),
                query,
            ).scalar_subquery()
        )
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
    organization_id = (
        select(Organization.id)
        .join(Membership, Membership.organization_id == Organization.id)
        .where(
            Organization.legacy_company_profile_id == profile_id,
            Membership.user_id == user_id,
            Membership.state == MembershipState.ACTIVE,
        )
        .scalar_subquery()
    )
    return and_(
        OrganizationPursuit.source_tender_id == Tender.id,
        OrganizationPursuit.organization_id == organization_id,
    )


async def _page_rows(
    db: AsyncSession,
    *,
    user_id: UUID,
    profile_id: UUID | None,
    query: ExplorerQuery,
    targets: ProfileTargets = ProfileTargets(),
) -> list[tuple[Tender, TenderRecommendation | None, OrganizationPursuit | None]]:
    if query.view != ExplorerView.ALL and profile_id is None:
        return []
    if query.view == ExplorerView.RECOMMENDED:
        if targets.empty:
            return []
        statement = (
            select(Tender, OrganizationPursuit).options(defer(Tender.compiled_master_text, raiseload=True))
            .outerjoin(OrganizationPursuit, _owned_engagement_join(user_id=user_id, profile_id=profile_id))
            .where(_profile_match_scope(targets, query.reference_time))
        )
        statement = _profile_match_order(_filtered(statement, query), query.sort)
        rows = (await db.execute(statement.offset(query.offset).limit(query.limit))).all()
        return [(tender, None, engagement) for tender, engagement in rows]

    if query.view == ExplorerView.ALL and profile_id is None:
        statement = _filtered(
            select(Tender).options(defer(Tender.compiled_master_text, raiseload=True)).where(customer_visible_tender_condition(Tender)),
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
            select(Tender, TenderRecommendation, OrganizationPursuit).options(defer(Tender.compiled_master_text, raiseload=True))
            .outerjoin(TenderRecommendation, recommendation_join)
            .outerjoin(OrganizationPursuit, engagement_join)
            .where(customer_visible_tender_condition(Tender))
        )
        statement = _all_order(_filtered(statement, query), query.sort)
    else:
        dismissed = query.view == ExplorerView.DISMISSED
        statement = (
            select(Tender, TenderRecommendation, OrganizationPursuit).options(defer(Tender.compiled_master_text, raiseload=True))
            .select_from(TenderRecommendation)
            .join(Tender, Tender.id == TenderRecommendation.tender_id)
            .outerjoin(OrganizationPursuit, engagement_join)
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


def _bounded_tender_summary(value: str | None) -> str | None:
    """Project only a short, normalized excerpt of canonical Tender description."""
    description = " ".join((value or "").split())
    return (description[:237] + "…") if len(description) > 240 else (description or None)


async def list_explorer_tenders(
    db: AsyncSession,
    *,
    user_id: UUID,
    query: ExplorerQuery,
) -> ExplorerTenderListResponse:
    """Run fixed-count SQL reads and bounded response-only composition."""
    server_time = datetime.now(timezone.utc)
    query = replace(query, reference_time=server_time)
    profile_id, targets = await owned_profile_targets(db, user_id=user_id)
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
    counts = await _filtered_counts(db, profile_id=profile_id, query=query, targets=targets)
    rows = await _page_rows(
        db,
        user_id=user_id,
        profile_id=profile_id,
        query=query,
        targets=targets,
    )
    summaries = await _batched_tender_summaries(
        db=db,
        tender_ids=[tender.id for tender, _recommendation, _engagement in rows],
    )

    items: list[ExplorerTenderItem] = []
    for tender, recommendation, engagement in rows:
        serialized = _serialize_tender(tender, summary=summaries.get(tender.id))
        newness = tender_newness(serialized.created_at, server_time=server_time)
        matched_country, matched_services = (
            (None, []) if targets.empty else tender_profile_match(tender, targets)
        )
        items.append(
            ExplorerTenderItem(
                tender=ExplorerTenderSummary(
                    id=serialized.id,
                    external_id=serialized.external_id,
                    source_system=serialized.source_system,
                    canonical_source_key=serialized.canonical_source_key,
                    source_url=serialized.source_url,
                    title=serialized.title,
                    summary=_bounded_tender_summary(tender.description),
                    buyer=serialized.buyer,
                    budget=serialized.budget,
                    currency=serialized.currency,
                    deadline=serialized.deadline,
                    publication_date=serialized.publication_date,
                    country=serialized.country,
                    region=serialized.region,
                    sector=serialized.sector,
                    status=serialized.status,
                    source_status=serialized.source_status,
                    status_reason=serialized.status_reason,
                    deadline_time_basis=serialized.deadline_time_basis,
                    deadline_timezone=serialized.deadline_timezone,
                    deadline_published_local=serialized.deadline_published_local,
                    deadline_effective_at=serialized.deadline_effective_at,
                    category=serialized.category,
                    document_status=serialized.document_status,
                    document_count=serialized.document_count,
                    notice_type=serialized.notice_type,
                    created_at=newness.created_at,
                    is_new=newness.is_new,
                    new_until=newness.new_until,
                ),
                # Stored recommendations (numeric score, generated rationale) are only
                # returned on the dismissed view; they are not surfaced elsewhere (D1-08).
                recommendation=(
                    recommendation_summary(recommendation) if query.view == ExplorerView.DISMISSED else None
                ),
                pursuit=_pursuit_summary(engagement),
                profile_match=(
                    ExplorerProfileMatch(country=matched_country, services=matched_services)
                    if matched_country or matched_services
                    else None
                ),
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
