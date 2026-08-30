"""Explicit customer-safe schemas for the unified Tender Explorer."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.base import TenderEngagementStatus, TenderStatus


class ExplorerView(str, Enum):
    ALL = "all"
    RECOMMENDED = "recommended"
    DISMISSED = "dismissed"


class RecommendationAvailability(str, Enum):
    AVAILABLE = "AVAILABLE"
    PROFILE_REQUIRED = "PROFILE_REQUIRED"


class ExplorerTenderSummary(BaseModel):
    id: UUID
    external_id: str
    source_system: str
    canonical_source_key: str
    source_url: str | None = None
    title: str
    buyer: str | None = None
    budget: float
    currency: str
    deadline: datetime | None = None
    publication_date: datetime | None = None
    country: str | None = None
    region: str | None = None
    sector: str | None = None
    status: TenderStatus
    category: str
    document_status: str
    document_count: int = 0
    created_at: datetime


class ExplorerRecommendationSummary(BaseModel):
    recommendation_id: UUID
    match_score: int = Field(ge=0, le=100)
    rationale_summary: str = Field(max_length=280)
    is_dismissed: bool
    created_at: datetime


class ExplorerPursuitSummary(BaseModel):
    engagement_id: UUID
    status: TenderEngagementStatus
    allowed_actions: list[str] = Field(default_factory=list)


class ExplorerTenderItem(BaseModel):
    tender: ExplorerTenderSummary
    recommendation: ExplorerRecommendationSummary | None = None
    pursuit: ExplorerPursuitSummary | None = None


class ExplorerCounts(BaseModel):
    all_tenders: int = 0
    active_recommendations: int = 0
    dismissed_recommendations: int = 0


class ExplorerTenderListResponse(BaseModel):
    view: ExplorerView
    items: list[ExplorerTenderItem] = Field(default_factory=list)
    total: int
    limit: int
    offset: int
    counts: ExplorerCounts
    recommendation_availability: RecommendationAvailability


class RecommendationCommandResponse(BaseModel):
    status: str
    recommendation: ExplorerRecommendationSummary
