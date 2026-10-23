"""P2 partner finder API shapes. Public award notice data only: no contact fields anywhere."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class GapFeaturesResponse(BaseModel):
    category: Literal["PARTNER_FIRM", "EXPERT"]
    basis: Literal["PARTNER_FIRM_RULE", "LOCAL_PRESENCE", "EXPERIENCE", "EXPERT"]
    summary: str
    keywords: list[str] = Field(default_factory=list)
    sectors: list[str] = Field(default_factory=list)
    country: str | None = None
    procurement_group: str
    presence: Literal["LOCAL", "FOREIGN", "ANY"]


class PartnerGapItem(BaseModel):
    gap_id: UUID
    requirement_id: UUID | None = None
    position_id: UUID | None = None
    coverage_state: str
    review_state: str
    resolution_category: str
    distinction: str | None = None
    missing_contribution: str
    features: GapFeaturesResponse


class AwardItem(BaseModel):
    title: str
    project_name: str | None = None
    lender: str
    lender_label: str
    country: str | None = None
    year: int | None = None
    notice_id: str
    notice_url: str
    procurement_group: str | None = None
    joint_venture: bool = False


class RequestRef(BaseModel):
    request_id: UUID
    status: str


class PartnerSuggestion(BaseModel):
    rank: int
    firm_key: str
    firm_name: str
    firm_country: str | None = None
    presence: Literal["LOCAL", "FOREIGN", "UNKNOWN"]
    presence_matches_gap: bool
    match_strength: Literal["STRONG", "MODERATE"]
    in_procurement_category: bool
    same_country: bool
    matched_terms: list[str] = Field(default_factory=list)
    matched_sectors: list[str] = Field(default_factory=list)
    similar_award_count: int
    latest_award_year: int | None = None
    best_relevance: float
    awards: list[AwardItem] = Field(default_factory=list)
    source_label: str
    request: RequestRef | None = None


class PartnerSuggestionsResponse(BaseModel):
    analysis_run_id: UUID
    gap_id: UUID
    gap: GapFeaturesResponse
    ranking_version: str
    source_label: str
    jv_rule_check: bool
    awards_considered: int
    suggestions: list[PartnerSuggestion] = Field(default_factory=list)


class ExpertSuggestion(BaseModel):
    rank: int
    expert_id: UUID
    display_name: str
    scope: str
    qualification_state: str
    rationale: str
    missing_or_weak_evidence: list[str] = Field(default_factory=list)


class ExpertSuggestionsResponse(BaseModel):
    analysis_run_id: UUID
    gap_id: UUID
    gap: GapFeaturesResponse
    experts: list[ExpertSuggestion] = Field(default_factory=list)
    sourcing_request: RequestRef | None = None


class PartnerRequestEventResponse(BaseModel):
    from_status: str | None = None
    to_status: str
    message: str | None = None
    at: datetime


class PartnerRequestResponse(BaseModel):
    request_id: UUID
    pursuit_id: UUID
    analysis_run_id: UUID
    gap_id: UUID
    kind: Literal["INTRODUCTION", "EXPERT_SOURCING"]
    gap_category: str
    gap_summary: str
    firm_key: str | None = None
    firm_name: str | None = None
    firm_country: str | None = None
    awards: list[AwardItem] = Field(default_factory=list)
    source_label: str | None = None
    note: str | None = None
    status: str
    status_changed_at: datetime
    created_at: datetime
    requester_membership_id: UUID
    history: list[PartnerRequestEventResponse] = Field(default_factory=list)


class PartnerGapsResponse(BaseModel):
    analysis_run_id: UUID | None = None
    inputs_changed: bool = False
    gaps: list[PartnerGapItem] = Field(default_factory=list)
    requests: list[PartnerRequestResponse] = Field(default_factory=list)


class PartnerRequestCreate(BaseModel):
    analysis_run_id: UUID
    gap_id: UUID
    kind: Literal["INTRODUCTION", "EXPERT_SOURCING"]
    firm_key: str | None = Field(default=None, max_length=700)
    note: str | None = Field(default=None, max_length=2000)


class AdminPartnerRequestResponse(PartnerRequestResponse):
    organization_id: UUID | None = None
    organization_name: str | None = None
    requester_name: str | None = None
    requester_email: str | None = None
    tender_reference: str | None = None
    tender_title: str | None = None
    tender_url: str | None = None
    next_statuses: list[str] = Field(default_factory=list)


class PartnerRequestStatusChange(BaseModel):
    status: Literal["CONTACTED", "ACCEPTED", "DECLINED", "INTRODUCED"]
    message: str | None = Field(default=None, max_length=2000)


class ProspectiveMemberCreate(BaseModel):
    partner_request_id: UUID


class ProspectiveTarget(BaseModel):
    gap_id: UUID
    analysis_run_id: UUID
    gap_summary: str


class ProspectiveMemberResponse(BaseModel):
    prospective_member_id: UUID
    partner_request_id: UUID
    display_name: str
    firm_country: str | None = None
    request_status: str
    confirmation: Literal["NOT_YET_CONFIRMED"] = "NOT_YET_CONFIRMED"
    targets: list[ProspectiveTarget] = Field(default_factory=list)
    # Gaps of the scenario's latest revision this member would close if it joins (open, current-stage).
    would_close_gap_ids: list[UUID] = Field(default_factory=list)
    awards: list[AwardItem] = Field(default_factory=list)
    source_label: str
    added_at: datetime
