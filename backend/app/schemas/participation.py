"""W6 private participation write commands and safe projections."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


SOURCE_PATTERN = r"^(DIRECT_EMAIL|CALL|MEETING|SIGNED_DOCUMENT|OPERATOR_RECORDED|CUSTOMER_RECORDED|OTHER)$"


class ParticipationStartRequest(BaseModel):
    shortlist_decision_id: UUID


class AvailabilityFactCreateRequest(BaseModel):
    status: str = Field(pattern=r"^(UNKNOWN|TENTATIVE|AVAILABLE|PARTIALLY_AVAILABLE|UNAVAILABLE)$")
    window_start: date | None = None
    window_end: date | None = None
    effort_percent: Decimal | None = Field(default=None, ge=0, le=100)
    capacity_description: str | None = Field(default=None, max_length=2000)
    location_travel_constraints: str | None = Field(default=None, max_length=2000)
    confirmation_source: str = Field(pattern=SOURCE_PATTERN)
    observed_at: datetime
    valid_until: datetime | None = None
    supporting_document_version_id: UUID | None = None
    note: str | None = Field(default=None, max_length=2000)
    supersedes_fact_id: UUID | None = None

    @model_validator(mode="after")
    def validate_semantics(self):
        if (self.window_start is None) != (self.window_end is None):
            raise ValueError("availability window requires both start and end dates")
        if self.window_start and self.window_end and self.window_end < self.window_start:
            raise ValueError("availability window end cannot precede its start")
        if self.status in {"TENTATIVE", "AVAILABLE", "PARTIALLY_AVAILABLE"}:
            if self.valid_until is None:
                raise ValueError("positive availability requires a valid-until timestamp")
            if self.valid_until <= self.observed_at:
                raise ValueError("availability valid-until must follow the observation")
        return self


class InterestFactCreateRequest(BaseModel):
    status: str = Field(pattern=r"^(UNKNOWN|INTERESTED|CONDITIONAL|DECLINED)$")
    confirmation_source: str = Field(pattern=SOURCE_PATTERN)
    observed_at: datetime
    valid_until: datetime | None = None
    conditions: str | None = Field(default=None, max_length=4000)
    supporting_document_version_id: UUID | None = None
    note: str | None = Field(default=None, max_length=2000)
    supersedes_fact_id: UUID | None = None

    @model_validator(mode="after")
    def validate_semantics(self):
        if self.status == "CONDITIONAL" and not (self.conditions or "").strip():
            raise ValueError("conditional interest requires conditions")
        if self.valid_until is not None and self.valid_until <= self.observed_at:
            raise ValueError("interest valid-until must follow the observation")
        return self


class ParticipationDecisionCreateRequest(BaseModel):
    state: str = Field(pattern=r"^(UNCONFIRMED|TENTATIVE|CONFIRMED|DECLINED|WITHDRAWN)$")
    confirmation_source: str = Field(pattern=SOURCE_PATTERN)
    observed_at: datetime
    reconfirm_by: datetime | None = None
    conditions_summary: str | None = Field(default=None, max_length=4000)
    reason: str | None = Field(default=None, max_length=4000)
    supporting_document_version_id: UUID | None = None

    @model_validator(mode="after")
    def validate_semantics(self):
        if self.state in {"TENTATIVE", "CONFIRMED"}:
            if self.reconfirm_by is None:
                raise ValueError("tentative and confirmed participation require reconfirm-by")
            if self.reconfirm_by <= self.observed_at:
                raise ValueError("reconfirm-by must follow the recorded observation")
        if self.state in {"DECLINED", "WITHDRAWN"} and not (self.reason or "").strip():
            raise ValueError("decline and withdrawal require a reason")
        return self


class AvailabilityFactResponse(BaseModel):
    fact_id: UUID
    status: str
    effective_status: str
    is_expired: bool
    window_start: date | None = None
    window_end: date | None = None
    effort_percent: Decimal | None = None
    capacity_description: str | None = None
    location_travel_constraints: str | None = None
    confirmation_source: str
    observed_at: datetime
    valid_until: datetime | None = None
    supporting_document_version_id: UUID | None = None
    supersedes_fact_id: UUID | None = None
    actor_membership_id: UUID
    created_at: datetime


class InterestFactResponse(BaseModel):
    fact_id: UUID
    status: str
    effective_status: str
    is_expired: bool
    confirmation_source: str
    observed_at: datetime
    valid_until: datetime | None = None
    conditions: str | None = None
    supporting_document_version_id: UUID | None = None
    supersedes_fact_id: UUID | None = None
    actor_membership_id: UUID
    created_at: datetime


class ParticipationDecisionResponse(BaseModel):
    decision_id: UUID
    state: str
    effective_state: str
    needs_reconfirmation: bool
    confirmation_source: str
    observed_at: datetime
    reconfirm_by: datetime | None = None
    conditions_summary: str | None = None
    reason: str | None = None
    supporting_document_version_id: UUID | None = None
    supersedes_decision_id: UUID | None = None
    actor_membership_id: UUID
    created_at: datetime


class ParticipationHistoryEvent(BaseModel):
    event_kind: str
    event_id: UUID
    recorded_state: str
    confirmation_source: str
    observed_at: datetime
    actor_membership_id: UUID
    supersedes_id: UUID | None = None
    created_at: datetime


class CandidateParticipationResponse(BaseModel):
    participation_record_id: UUID
    organization_id: UUID
    pursuit_id: UUID
    candidate_match_id: UUID
    shortlist_decision_id: UUID
    effective_shortlist_decision_id: UUID | None = None
    effective_shortlist_state: str | None = None
    candidate_search_run_id: UUID
    analysis_run_id: UUID
    gap_id: UUID
    candidate_kind: str
    candidate_id: UUID
    candidate_name: str
    proposed_contribution: str
    w5_qualification_state: str
    w5_candidate_evidence_state: str
    w5_strongest_evidence: list[Any] = Field(default_factory=list)
    w5_missing_or_weak_evidence: list[Any] = Field(default_factory=list)
    assignment_dates: str | None = None
    assignment_window_coverage: str
    latest_availability: AvailabilityFactResponse | None = None
    latest_interest: InterestFactResponse | None = None
    latest_participation: ParticipationDecisionResponse | None = None
    upstream_stale: bool
    upstream_stale_reason: str | None = None
    same_candidate_record_ids: list[UUID] = Field(default_factory=list)
    history: list[ParticipationHistoryEvent] = Field(default_factory=list)
    created_by_membership_id: UUID
    created_at: datetime
