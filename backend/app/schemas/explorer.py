"""Explicit customer-safe schemas for the unified Tender Explorer."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.base import TenderEngagementStatus, TenderStatus
from app.schemas.tender import TenderTruthFields


class ExplorerView(str, Enum):
    ALL = "all"
    RECOMMENDED = "recommended"
    DISMISSED = "dismissed"


class RecommendationAvailability(str, Enum):
    AVAILABLE = "AVAILABLE"
    PROFILE_REQUIRED = "PROFILE_REQUIRED"


class ExplorerTenderSummary(TenderTruthFields):
    id: UUID
    external_id: str
    source_system: str
    canonical_source_key: str
    source_url: str | None = None
    title: str
    summary: str | None = Field(default=None, max_length=240)
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
    notice_type: str | None = None
    created_at: datetime = Field(description="Immutable first durable insertion time in Plasma.")
    is_new: bool = Field(description="True only inside the server-authoritative 24-hour discovery window.")
    new_until: datetime = Field(description="UTC instant when the Tender stops being New.")


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


class ExplorerProfileMatch(BaseModel):
    """Deterministic facts about why a tender matches the viewer's company profile (D1-08)."""

    country: str | None = Field(default=None, description="The profile target country found in the tender's country.")
    services: list[str] = Field(default_factory=list, description="Profile target services found in the tender.")


class ExplorerTenderItem(BaseModel):
    tender: ExplorerTenderSummary
    # Stored Hunter recommendations are no longer surfaced on the all/recommended views
    # (D1-08); the field stays for the dismissed view and API compatibility.
    recommendation: ExplorerRecommendationSummary | None = None
    pursuit: ExplorerPursuitSummary | None = None
    profile_match: ExplorerProfileMatch | None = None


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
    server_time: datetime = Field(description="Single UTC reference used for all newness values in this response.")


class RecommendationCommandResponse(BaseModel):
    status: str
    recommendation: ExplorerRecommendationSummary
