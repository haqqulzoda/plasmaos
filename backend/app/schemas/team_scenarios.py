"""W7 team scenario commands and organization-private projections."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class TeamScenarioCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    participation_record_ids: list[UUID] = Field(default_factory=list, max_length=100)

    @field_validator("title")
    @classmethod
    def nonblank_title(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("title must not be blank")
        return value

    @model_validator(mode="after")
    def unique_records(self):
        if len(set(self.participation_record_ids)) != len(self.participation_record_ids):
            raise ValueError("participation records must be unique")
        return self


class TeamScenarioRevisionCreateRequest(BaseModel):
    participation_record_ids: list[UUID] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def unique_records(self):
        if len(set(self.participation_record_ids)) != len(self.participation_record_ids):
            raise ValueError("participation records must be unique")
        return self


class TeamScenarioDecisionCreateRequest(BaseModel):
    decision: str = Field(pattern=r"^(PREFERRED|REJECTED|APPROVED_FOR_PROPOSAL)$")
    reason: str = Field(min_length=3, max_length=4000)
    explicit_confirmation: bool = False

    @field_validator("reason")
    @classmethod
    def nonblank_reason(cls, value: str) -> str:
        if len(value.strip()) < 3:
            raise ValueError("reason must contain at least three non-whitespace characters")
        return value


class ScenarioContributionResponse(BaseModel):
    contribution_id: UUID
    candidate_match_id: UUID
    participation_record_id: UUID
    gap_id: UUID
    requirement_id: UUID | None = None
    position_id: UUID | None = None
    shortlist_decision_id: UUID
    shortlist_decision_state: str
    proposed_contribution: str
    contribution_rule: str
    qualification_state: str
    candidate_evidence_state: str
    evidence_identities: list[Any] = Field(default_factory=list)
    strongest_evidence: list[Any] = Field(default_factory=list)
    availability_fact_id: UUID | None = None
    availability_recorded_state: str | None = None
    availability_effective_state: str | None = None
    availability_window_start: date | None = None
    availability_window_end: date | None = None
    availability_effort_percent: Decimal | None = None
    availability_capacity: str | None = None
    availability_valid_until: datetime | None = None
    interest_fact_id: UUID | None = None
    interest_recorded_state: str | None = None
    interest_effective_state: str | None = None
    interest_conditions: str | None = None
    participation_decision_id: UUID | None = None
    participation_recorded_state: str | None = None
    participation_effective_state: str | None = None
    confirmation_source: str | None = None
    confirmation_observed_at: datetime | None = None
    reconfirm_by: datetime | None = None
    confirmation_conditions: str | None = None
    assignment_dates: str | None = None
    assignment_window_result: str
    upstream_stale: bool


class ScenarioParticipantResponse(BaseModel):
    participant_id: UUID
    participant_type: str
    candidate_id: UUID
    display_name: str
    contributions: list[ScenarioContributionResponse] = Field(default_factory=list)


class ScenarioGapAssessmentResponse(BaseModel):
    gap_assessment_id: UUID
    gap_id: UUID
    requirement_id: UUID | None = None
    position_id: UUID | None = None
    review_assertion_id: UUID | None = None
    w4_coverage_state: str
    w4_review_state: str
    resolution_category: str
    state: str
    is_current_stage: bool
    is_blocking: bool
    rationale_code: str


class ScenarioIssueResponse(BaseModel):
    issue_id: UUID
    issue_code: str
    severity: str
    gap_id: UUID | None = None
    participant_id: UUID | None = None
    contribution_id: UUID | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class TeamScenarioDecisionResponse(BaseModel):
    decision_id: UUID
    revision_id: UUID
    decision: str
    reason: str
    explicit_confirmation: bool
    actor_membership_id: UUID
    created_at: datetime


class TeamScenarioRevisionResponse(BaseModel):
    revision_id: UUID
    version_number: int
    analysis_run_id: UUID
    analysis_pack_id: UUID
    selection_sha256: str
    assessment_schema_version: str
    assessment_state: str
    current_assessment_state: str
    scenario_current: bool
    stale_reasons: list[str] = Field(default_factory=list)
    gap_count: int
    covered_gap_count: int
    unresolved_gap_count: int
    participant_count: int
    confirmed_participant_count: int
    issue_count: int
    blocking_issue_count: int
    unresolved_later_stage_count: int
    source_provenance_count: int
    private_provenance_count: int
    participants: list[ScenarioParticipantResponse] = Field(default_factory=list)
    gap_assessments: list[ScenarioGapAssessmentResponse] = Field(default_factory=list)
    issues: list[ScenarioIssueResponse] = Field(default_factory=list)
    decisions: list[TeamScenarioDecisionResponse] = Field(default_factory=list)
    created_by_membership_id: UUID
    created_at: datetime


class TeamScenarioResponse(BaseModel):
    scenario_id: UUID
    organization_id: UUID
    pursuit_id: UUID
    lead_organization_id: UUID
    title: str
    archived_at: datetime | None = None
    latest_revision: TeamScenarioRevisionResponse | None = None
    revisions: list[TeamScenarioRevisionResponse] = Field(default_factory=list)
    created_by_membership_id: UUID
    created_at: datetime


class ProposalHandoffResponse(BaseModel):
    scenario_id: UUID
    revision_id: UUID
    approval_decision_id: UUID
    analysis_run_id: UUID
    analysis_pack_id: UUID
    scenario_current: bool
    assessment_state: str
    gap_assessments: list[ScenarioGapAssessmentResponse]
    participants: list[ScenarioParticipantResponse]
    unresolved_later_stage_count: int
    source_provenance_count: int
    private_provenance_count: int
