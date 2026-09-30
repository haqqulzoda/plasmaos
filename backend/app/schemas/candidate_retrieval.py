"""W5 request and safe response contracts for candidate authorities."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


EvidenceState = str


class FirmCreateRequest(BaseModel):
    scope: str = Field(pattern=r"^(ORGANIZATION_PRIVATE|NETWORK_SHARED)$")
    canonical_name: str = Field(min_length=2, max_length=500)
    display_name: str = Field(min_length=2, max_length=500)
    legal_name: str | None = Field(default=None, max_length=500)
    country: str | None = Field(default=None, max_length=150)
    regions: list[str] = Field(default_factory=list, max_length=50)
    services: list[str] = Field(default_factory=list, max_length=50)
    capabilities: list[str] = Field(default_factory=list, max_length=100)
    sectors: list[str] = Field(default_factory=list, max_length=50)
    source_type: str = Field(default="MANUAL", pattern=r"^(MANUAL|EXPLICIT_IMPORT)$")
    source_provenance: dict[str, Any] = Field(default_factory=dict)
    evidence_state: str = Field(pattern=r"^(VERIFIED|REVIEWED|UNVERIFIED|EVIDENCE_MISSING)$")
    network_permission_basis: str | None = Field(default=None, max_length=4000)
    private_notes: str | None = Field(default=None, max_length=10000)


class FirmUpdateRequest(BaseModel):
    canonical_name: str | None = Field(default=None, min_length=2, max_length=500)
    display_name: str | None = Field(default=None, min_length=2, max_length=500)
    legal_name: str | None = Field(default=None, max_length=500)
    country: str | None = Field(default=None, max_length=150)
    regions: list[str] | None = Field(default=None, max_length=50)
    services: list[str] | None = Field(default=None, max_length=50)
    capabilities: list[str] | None = Field(default=None, max_length=100)
    sectors: list[str] | None = Field(default=None, max_length=50)
    source_provenance: dict[str, Any] | None = None
    evidence_state: str | None = Field(default=None, pattern=r"^(VERIFIED|REVIEWED|UNVERIFIED|EVIDENCE_MISSING)$")
    network_permission_basis: str | None = Field(default=None, max_length=4000)
    private_notes: str | None = Field(default=None, max_length=10000)


class SelfFirmUpsertRequest(BaseModel):
    """The organization's own firm. Every field is optional: an omitted field keeps
    its stored value, and on first save takes the default (display_name: the
    organization name). Scope and network fields do not apply to a self firm."""

    model_config = ConfigDict(extra="forbid")

    canonical_name: str | None = Field(default=None, min_length=2, max_length=500)
    display_name: str | None = Field(default=None, min_length=2, max_length=500)
    legal_name: str | None = Field(default=None, max_length=500)
    country: str | None = Field(default=None, max_length=150)
    regions: list[str] | None = Field(default=None, max_length=50)
    services: list[str] | None = Field(default=None, max_length=50)
    capabilities: list[str] | None = Field(default=None, max_length=100)
    sectors: list[str] | None = Field(default=None, max_length=50)
    source_type: str | None = Field(default=None, pattern=r"^(MANUAL|EXPLICIT_IMPORT)$")
    source_provenance: dict[str, Any] | None = None
    evidence_state: str | None = Field(default=None, pattern=r"^(VERIFIED|REVIEWED|UNVERIFIED|EVIDENCE_MISSING)$")
    private_notes: str | None = Field(default=None, max_length=10000)


class ProjectReferenceCreateRequest(BaseModel):
    project_name: str = Field(min_length=2, max_length=700)
    client_name: str | None = Field(default=None, max_length=500)
    country: str | None = Field(default=None, max_length=150)
    service: str | None = Field(default=None, max_length=300)
    sector: str | None = Field(default=None, max_length=300)
    role: str = Field(pattern=r"^(LEAD|JV_MEMBER|CONSORTIUM_MEMBER|SUBCONSULTANT|SUBCONTRACTOR|OTHER|UNKNOWN)$")
    contract_share_percent: Decimal | None = Field(default=None, ge=0, le=100)
    contract_value: Decimal | None = Field(default=None, ge=0)
    contract_currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    value_basis: str = Field(pattern=r"^(FIRM_SHARE|CONSORTIUM_TOTAL|CONTRACT_TOTAL|UNKNOWN)$")
    start_date: date | None = None
    completion_date: date | None = None
    completion_state: str = Field(pattern=r"^(COMPLETED|ONGOING|NOT_COMPLETED|UNKNOWN)$")
    relevant_scope: str | None = Field(default=None, max_length=10000)
    evidence_provenance: dict[str, Any] = Field(default_factory=dict)
    evidence_state: str = Field(pattern=r"^(VERIFIED|REVIEWED|UNVERIFIED|EVIDENCE_MISSING)$")

    @model_validator(mode="after")
    def validate_value_truth(self):
        if (self.contract_value is None) != (self.contract_currency is None):
            raise ValueError("contract value and currency must be provided together")
        if self.contract_value is not None and self.value_basis == "UNKNOWN":
            raise ValueError("a proven value requires an explicit value basis")
        if self.start_date and self.completion_date and self.completion_date < self.start_date:
            raise ValueError("completion date cannot precede start date")
        return self


class ProjectReferenceUpdateRequest(BaseModel):
    """Changed fields only. The result must satisfy ProjectReferenceCreateRequest."""

    model_config = ConfigDict(extra="forbid")

    project_name: str | None = Field(default=None, min_length=2, max_length=700)
    client_name: str | None = Field(default=None, max_length=500)
    country: str | None = Field(default=None, max_length=150)
    service: str | None = Field(default=None, max_length=300)
    sector: str | None = Field(default=None, max_length=300)
    role: str | None = Field(
        default=None, pattern=r"^(LEAD|JV_MEMBER|CONSORTIUM_MEMBER|SUBCONSULTANT|SUBCONTRACTOR|OTHER|UNKNOWN)$"
    )
    contract_share_percent: Decimal | None = Field(default=None, ge=0, le=100)
    contract_value: Decimal | None = Field(default=None, ge=0)
    contract_currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    value_basis: str | None = Field(default=None, pattern=r"^(FIRM_SHARE|CONSORTIUM_TOTAL|CONTRACT_TOTAL|UNKNOWN)$")
    start_date: date | None = None
    completion_date: date | None = None
    completion_state: str | None = Field(default=None, pattern=r"^(COMPLETED|ONGOING|NOT_COMPLETED|UNKNOWN)$")
    relevant_scope: str | None = Field(default=None, max_length=10000)
    evidence_provenance: dict[str, Any] | None = None
    evidence_state: str | None = Field(default=None, pattern=r"^(VERIFIED|REVIEWED|UNVERIFIED|EVIDENCE_MISSING)$")


class ProjectReferenceResponse(BaseModel):
    reference_id: UUID
    firm_id: UUID
    project_name: str
    client_name: str | None = None
    country: str | None = None
    service: str | None = None
    sector: str | None = None
    role: str
    contract_share_percent: Decimal | None = None
    contract_value: Decimal | None = None
    contract_currency: str | None = None
    value_basis: str
    start_date: date | None = None
    completion_date: date | None = None
    completion_state: str
    relevant_scope: str | None = None
    evidence_provenance: dict[str, Any]
    evidence_state: str
    # METADATA_ONLY: a recorded claim. FILE_BACKED: the provenance names a document.
    evidence_basis: str = "METADATA_ONLY"
    # Set when this row replaced an edited reference; the replaced row is archived.
    supersedes_reference_id: UUID | None = None
    archived_at: datetime | None = None
    created_at: datetime


class FirmResponse(BaseModel):
    firm_id: UUID
    # True only for the organization's own firm (GET/PUT /candidates/self-firm).
    is_self_firm: bool = False
    scope: str
    canonical_name: str
    display_name: str
    legal_name: str | None = None
    country: str | None = None
    regions: list[Any]
    services: list[Any]
    capabilities: list[Any]
    sectors: list[Any]
    source_type: str
    source_provenance: dict[str, Any]
    evidence_state: str
    project_references: list[ProjectReferenceResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ExpertCreateRequest(BaseModel):
    scope: str = Field(pattern=r"^(ORGANIZATION_PRIVATE|NETWORK_SHARED)$")
    display_name: str = Field(min_length=2, max_length=500)
    qualifications: list[str] = Field(default_factory=list, max_length=100)
    languages: list[str] = Field(default_factory=list, max_length=50)
    specializations: list[str] = Field(default_factory=list, max_length=100)
    consent_state: str = Field(pattern=r"^(NOT_REQUIRED_PRIVATE|EXPLICIT_CONSENT|CONTRACTUAL_BASIS|WITHDRAWN|UNKNOWN)$")
    network_permission_basis: str | None = Field(default=None, max_length=4000)
    evidence_state: str = Field(pattern=r"^(VERIFIED|REVIEWED|UNVERIFIED|EVIDENCE_MISSING)$")
    source_provenance: dict[str, Any] = Field(default_factory=dict)
    private_notes: str | None = Field(default=None, max_length=10000)


class ExpertUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=2, max_length=500)
    qualifications: list[str] | None = Field(default=None, max_length=100)
    languages: list[str] | None = Field(default=None, max_length=50)
    specializations: list[str] | None = Field(default=None, max_length=100)
    consent_state: str | None = Field(default=None, pattern=r"^(NOT_REQUIRED_PRIVATE|EXPLICIT_CONSENT|CONTRACTUAL_BASIS|WITHDRAWN|UNKNOWN)$")
    network_permission_basis: str | None = Field(default=None, max_length=4000)
    evidence_state: str | None = Field(default=None, pattern=r"^(VERIFIED|REVIEWED|UNVERIFIED|EVIDENCE_MISSING)$")
    source_provenance: dict[str, Any] | None = None
    private_notes: str | None = Field(default=None, max_length=10000)


class CVVersionCreateRequest(BaseModel):
    education: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    qualifications: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    certifications: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    assignments: list[dict[str, Any]] = Field(default_factory=list, max_length=250)
    languages: list[dict[str, Any]] = Field(default_factory=list, max_length=50)
    evidence_provenance: dict[str, Any] = Field(default_factory=dict)
    evidence_state: str = Field(pattern=r"^(VERIFIED|REVIEWED|UNVERIFIED|EVIDENCE_MISSING)$")


class CVVersionResponse(BaseModel):
    cv_version_id: UUID
    expert_id: UUID
    version_number: int
    education: list[Any]
    qualifications: list[Any]
    certifications: list[Any]
    assignments: list[Any]
    languages: list[Any]
    evidence_provenance: dict[str, Any]
    evidence_state: str
    structured_sha256: str
    created_at: datetime


class ExpertResponse(BaseModel):
    expert_id: UUID
    scope: str
    display_name: str
    qualifications: list[Any]
    languages: list[Any]
    specializations: list[Any]
    consent_state: str
    evidence_state: str
    source_provenance: dict[str, Any]
    cv_versions: list[CVVersionResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class CandidateLibraryResponse(BaseModel):
    # The organization's own firm; never listed in ``firms``.
    self_firm: FirmResponse | None = None
    firms: list[FirmResponse] = Field(default_factory=list)
    experts: list[ExpertResponse] = Field(default_factory=list)


class CandidateSearchRequest(BaseModel):
    analysis_run_id: UUID
    gap_id: UUID
    result_limit: int = Field(default=10, ge=1, le=20)


class CandidateReviewRequest(BaseModel):
    decision: str = Field(pattern=r"^(SHORTLISTED|REJECTED|MORE_EVIDENCE_REQUESTED|IRRELEVANT|CONTRIBUTION_CORRECTED)$")
    corrected_contribution: str | None = Field(default=None, min_length=3, max_length=4000)
    reason: str = Field(min_length=3, max_length=4000)

    @model_validator(mode="after")
    def validate_correction(self):
        if self.decision == "CONTRIBUTION_CORRECTED" and not self.corrected_contribution:
            raise ValueError("corrected contribution is required")
        if self.decision != "CONTRIBUTION_CORRECTED" and self.corrected_contribution is not None:
            raise ValueError("corrected contribution is only valid for a correction decision")
        return self


class CandidateReviewResponse(BaseModel):
    decision_id: UUID
    candidate_search_run_id: UUID
    candidate_match_id: UUID
    decision: str
    corrected_contribution: str | None = None
    reason: str
    actor_membership_id: UUID
    created_at: datetime


class CandidateMatchResponse(BaseModel):
    candidate_match_id: UUID
    gap_id: UUID
    candidate_kind: str
    candidate_id: UUID
    candidate_name: str
    candidate_scope: str
    candidate_evidence_state: str
    proposed_contribution: str
    strongest_evidence: list[Any]
    relevant_evidence: list[Any]
    missing_or_weak_evidence: list[Any]
    qualification_state: str
    rationale: str
    provenance: dict[str, Any]
    retrieval_rank: int
    latest_review: CandidateReviewResponse | None = None


class CandidateSearchRunResponse(BaseModel):
    candidate_search_run_id: UUID
    organization_id: UUID
    pursuit_id: UUID
    analysis_run_id: UUID
    gap_id: UUID
    target_kind: str
    requirement_id: UUID | None = None
    position_id: UUID | None = None
    review_assertion_id: UUID
    effective_coverage_state: str
    effective_review_state: str
    resolution_category: str
    contribution_rule: str
    search_version: str
    search_parameters: dict[str, Any]
    result_limit: int
    status: str
    created_at: datetime
    completed_at: datetime
    is_stale: bool
    stale_reason: str | None = None
    matches: list[CandidateMatchResponse] = Field(default_factory=list)

