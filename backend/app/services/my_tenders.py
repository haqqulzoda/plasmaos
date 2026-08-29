"""Bounded, tenant-scoped read model for My Tenders."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy import Select, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.all_models import Project, Tender, TenderProject
from app.models.base import TenderEngagementStatus, TenderStatus
from app.models.engagement import TenderEngagement
from app.schemas.engagement import (
    MyTenderListItem,
    MyTenderStatusCounts,
    MyTendersListResponse,
)
from app.services.tender_engagements import allowed_actions_for_status


MyTendersStatusFilter = Literal[
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
MyTendersSort = Literal[
    "recently_updated",
    "recently_added",
    "deadline_soonest",
]


@dataclass(frozen=True)
class MyTendersQuery:
    status: MyTendersStatusFilter = "ACTIVE"
    source_system: str | None = None
    tender_status: TenderStatus | None = None
    search: str | None = None
    sort: MyTendersSort = "recently_updated"
    offset: int = 0
    limit: int = 25


def _escaped_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _base_list_statement(
    *,
    user_id: UUID,
    company_profile_id: UUID,
    query: MyTendersQuery,
) -> Select:
    statement = (
        select(TenderEngagement, Tender, Project)
        .join(Tender, Tender.id == TenderEngagement.tender_id)
        .outerjoin(TenderProject, TenderProject.tender_id == Tender.id)
        .outerjoin(Project, Project.id == TenderProject.project_id)
        .where(
            TenderEngagement.user_id == user_id,
            TenderEngagement.company_profile_id == company_profile_id,
        )
    )
    if query.status == "ACTIVE":
        statement = statement.where(
            TenderEngagement.status != TenderEngagementStatus.DISMISSED
        )
    elif query.status != "ALL":
        statement = statement.where(
            TenderEngagement.status == TenderEngagementStatus(query.status)
        )
    if query.source_system:
        statement = statement.where(Tender.source_system == query.source_system)
    if query.tender_status:
        statement = statement.where(Tender.status == query.tender_status)
    if query.search:
        pattern = f"%{_escaped_like(query.search.strip())}%"
        statement = statement.where(
            or_(
                Tender.title.ilike(pattern, escape="\\"),
                Tender.buyer.ilike(pattern, escape="\\"),
            )
        )
    return statement


def _ordered(statement: Select, sort: MyTendersSort) -> Select:
    if sort == "recently_added":
        return statement.order_by(
            TenderEngagement.created_at.desc(),
            TenderEngagement.id.desc(),
        )
    if sort == "deadline_soonest":
        return statement.order_by(
            case((Tender.deadline.is_(None), 1), else_=0),
            Tender.deadline.asc(),
            TenderEngagement.id.desc(),
        )
    return statement.order_by(
        TenderEngagement.status_changed_at.desc(),
        TenderEngagement.id.desc(),
    )


def _item(
    engagement: TenderEngagement,
    tender: Tender,
    project: Project | None,
) -> MyTenderListItem:
    estimated_value = float(tender.budget) if tender.budget and tender.budget > 0 else None
    return MyTenderListItem(
        engagement_id=engagement.id,
        tender_id=tender.id,
        engagement_status=engagement.status,
        engagement_origin=engagement.origin,
        engagement_created_at=engagement.created_at,
        engagement_updated_at=engagement.updated_at,
        status_changed_at=engagement.status_changed_at,
        allowed_actions=list(allowed_actions_for_status(engagement.status)),
        tender_title=tender.title,
        buyer=tender.buyer,
        source_system=tender.source_system,
        tender_status=tender.status,
        deadline=tender.deadline,
        estimated_value=estimated_value,
        currency=tender.currency if estimated_value is not None else None,
        notice_type=tender.notice_type,
        procurement_method=tender.procurement_method,
        country=tender.country,
        region=tender.region,
        project_external_id=project.external_project_id if project else None,
        project_name=project.name if project else None,
        project_source_system=project.source_system if project else None,
        project_enrichment_status=project.enrichment_status if project else None,
    )


async def list_my_tenders(
    db: AsyncSession,
    *,
    user_id: UUID,
    company_profile_id: UUID,
    query: MyTendersQuery,
) -> MyTendersListResponse:
    """Execute three fixed queries regardless of page size; no per-row loads."""
    base = _base_list_statement(
        user_id=user_id,
        company_profile_id=company_profile_id,
        query=query,
    )
    page_rows = (
        await db.execute(
            _ordered(base, query.sort).offset(query.offset).limit(query.limit)
        )
    ).all()
    total = int(
        await db.scalar(
            select(func.count()).select_from(base.order_by(None).subquery())
        )
        or 0
    )
    count_rows = (
        await db.execute(
            select(TenderEngagement.status, func.count(TenderEngagement.id))
            .where(
                TenderEngagement.user_id == user_id,
                TenderEngagement.company_profile_id == company_profile_id,
            )
            .group_by(TenderEngagement.status)
        )
    ).all()
    raw_counts = {status: int(rows) for status, rows in count_rows}
    dismissed = raw_counts.get(TenderEngagementStatus.DISMISSED, 0)
    all_rows = sum(raw_counts.values())
    counts = MyTenderStatusCounts(
        all=all_rows,
        active=all_rows - dismissed,
        saved=raw_counts.get(TenderEngagementStatus.SAVED, 0),
        evaluating=raw_counts.get(TenderEngagementStatus.EVALUATING, 0),
        preparing=raw_counts.get(TenderEngagementStatus.PREPARING, 0),
        submitted=raw_counts.get(TenderEngagementStatus.SUBMITTED, 0),
        won=raw_counts.get(TenderEngagementStatus.WON, 0),
        lost=raw_counts.get(TenderEngagementStatus.LOST, 0),
        dismissed=dismissed,
    )
    return MyTendersListResponse(
        items=[_item(engagement, tender, project) for engagement, tender, project in page_rows],
        total=total,
        limit=query.limit,
        offset=query.offset,
        counts=counts,
    )


async def get_owned_my_tender_item(
    db: AsyncSession,
    *,
    engagement_id: UUID,
    user_id: UUID,
    company_profile_id: UUID,
) -> MyTenderListItem | None:
    row = (
        await db.execute(
            select(TenderEngagement, Tender, Project)
            .join(Tender, Tender.id == TenderEngagement.tender_id)
            .outerjoin(TenderProject, TenderProject.tender_id == Tender.id)
            .outerjoin(Project, Project.id == TenderProject.project_id)
            .where(
                TenderEngagement.id == engagement_id,
                TenderEngagement.user_id == user_id,
                TenderEngagement.company_profile_id == company_profile_id,
            )
        )
    ).one_or_none()
    return _item(*row) if row else None
