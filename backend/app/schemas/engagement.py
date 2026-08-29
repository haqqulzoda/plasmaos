"""Customer-safe schemas for the canonical My Tenders surface."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.base import (
    TenderEngagementOrigin,
    TenderEngagementStatus,
    TenderStatus,
)


class TenderEngagementSummary(BaseModel):
    engagement_id: UUID
    tender_id: UUID
    engagement_status: TenderEngagementStatus
    engagement_origin: TenderEngagementOrigin
    engagement_created_at: datetime
    engagement_updated_at: datetime
    status_changed_at: datetime
    allowed_actions: list[str] = Field(default_factory=list)


class MyTenderListItem(TenderEngagementSummary):
    tender_title: str
    buyer: str | None = None
    source_system: str
    tender_status: TenderStatus
    deadline: datetime | None = None
    estimated_value: float | None = None
    currency: str | None = None
    notice_type: str | None = None
    procurement_method: str | None = None
    country: str | None = None
    region: str | None = None
    project_external_id: str | None = None
    project_name: str | None = None
    project_source_system: str | None = None
    project_enrichment_status: str | None = None


class MyTenderStatusCounts(BaseModel):
    all: int = 0
    active: int = 0
    saved: int = 0
    evaluating: int = 0
    preparing: int = 0
    submitted: int = 0
    won: int = 0
    lost: int = 0
    dismissed: int = 0


class MyTendersListResponse(BaseModel):
    items: list[MyTenderListItem] = Field(default_factory=list)
    total: int
    limit: int
    offset: int
    counts: MyTenderStatusCounts


class TenderScopedEngagementResponse(BaseModel):
    engagement: TenderEngagementSummary | None = None
    proposal_id: UUID | None = None


class TenderEngagementActionRequest(BaseModel):
    expected_status: TenderEngagementStatus


class TenderEngagementActionResponse(BaseModel):
    engagement: TenderEngagementSummary


class SaveToMyTendersResponse(BaseModel):
    engagement: TenderEngagementSummary
    created: bool
    reengaged: bool
