"""API contracts for organization membership and pursuit ownership."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.base import (
    DocumentProcessingState,
    MembershipRole,
    MembershipState,
    PrivateDocumentRole,
    PursuitOrigin,
    TenderEngagementStatus,
)


class OrganizationSummary(BaseModel):
    organization_id: UUID
    legacy_company_profile_id: UUID
    display_name: str | None = None
    membership_id: UUID
    membership_role: MembershipRole
    membership_state: MembershipState


class MembershipResponse(BaseModel):
    membership_id: UUID
    organization_id: UUID
    user_id: UUID
    role: MembershipRole
    state: MembershipState
    created_at: datetime
    updated_at: datetime
    activated_at: datetime | None = None
    revoked_at: datetime | None = None


class MembershipInvitationRequest(BaseModel):
    user_id: UUID


class MembershipRoleRequest(BaseModel):
    role: MembershipRole


class MembershipRevokeRequest(BaseModel):
    transfer_to_membership_id: UUID | None = None


class PursuitResponse(BaseModel):
    pursuit_id: UUID
    organization_id: UUID
    source_tender_id: UUID | None = None
    origin: PursuitOrigin
    legacy_engagement_id: UUID | None = None
    owner_membership_id: UUID | None = None
    stage: TenderEngagementStatus
    internal_target_at: datetime | None = None
    archived_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    stage_changed_at: datetime
    tender_title: str | None = None
    source_deadline: datetime | None = None
    title: str | None = None
    buyer: str | None = None
    declared_funder: str | None = None
    country: str | None = None
    reference: str | None = None
    external_deadline: datetime | None = None
    deadline_timezone: str | None = None
    source_url: str | None = None
    confirmed_fields: list[str] = Field(default_factory=list)
    processing_state: DocumentProcessingState | None = None
    file_count: int = 0
    processed_count: int = 0
    failed_count: int = 0
    owner_name: str | None = None
    # D2-05: display name of the first uploaded document, used when there is no title.
    first_document_name: str | None = None


class PursuitListResponse(BaseModel):
    items: list[PursuitResponse] = Field(default_factory=list)
    total: int
    limit: int
    offset: int


class SourcePursuitCreateRequest(BaseModel):
    tender_id: UUID
    stage: TenderEngagementStatus = TenderEngagementStatus.SAVED


class PursuitTransitionRequest(BaseModel):
    expected_stage: TenderEngagementStatus
    destination: TenderEngagementStatus
    reason: str | None = Field(default=None, max_length=1000)


class PursuitReopenRequest(BaseModel):
    expected_stage: TenderEngagementStatus | None = None
    destination: TenderEngagementStatus
    reason: str | None = Field(default=None, max_length=1000)


class PursuitOwnerRequest(BaseModel):
    owner_membership_id: UUID | None = None


class PrivateDocumentItem(BaseModel):
    document_id: UUID
    current_version_id: UUID
    role: PrivateDocumentRole
    display_name: str
    version_number: int
    media_type: str
    byte_size: int
    sha256: str
    processing_state: DocumentProcessingState
    page_count: int | None = None
    page_count_known: bool
    retry_allowed: bool
    error_code: str | None = None
    created_at: datetime
    updated_at: datetime


class PrivateDocumentListResponse(BaseModel):
    items: list[PrivateDocumentItem] = Field(default_factory=list)


class PrivateDocumentRoleRequest(BaseModel):
    role: PrivateDocumentRole


class PrivateUploadResponse(BaseModel):
    pursuit: PursuitResponse
    batch_id: UUID
    document_ids: list[UUID]
    processing_state: DocumentProcessingState
    duplicate_document_ids: list[UUID] = Field(default_factory=list)


class PursuitContextSuggestionResponse(BaseModel):
    suggestion_id: UUID
    field_name: str
    suggested_value: str
    document_version_id: UUID
    page_number: int | None = None
    evidence_span: str | None = None
    confidence: float | None = None
    review_state: str
    provenance_state: str
    user_confirmed_value: str | None = None


class PursuitContextFieldProvenanceResponse(BaseModel):
    field_name: str
    provenance_state: str
    source_value: str | None = None
    user_confirmed_value: str | None = None


class PursuitContextResponse(BaseModel):
    pursuit_id: UUID
    title: str | None = None
    buyer: str | None = None
    declared_funder: str | None = None
    country: str | None = None
    reference: str | None = None
    procurement_stage: str | None = None
    external_deadline: datetime | None = None
    deadline_timezone: str | None = None
    source_url: str | None = None
    confirmed_fields: list[str] = Field(default_factory=list)
    suggestions: list[PursuitContextSuggestionResponse] = Field(default_factory=list)
    field_provenance: list[PursuitContextFieldProvenanceResponse] = Field(default_factory=list)


class PursuitContextUpdateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=500)
    buyer: str | None = Field(default=None, max_length=500)
    declared_funder: str | None = Field(default=None, max_length=255)
    country: str | None = Field(default=None, max_length=255)
    reference: str | None = Field(default=None, max_length=255)
    procurement_stage: str | None = Field(default=None, max_length=255)
    external_deadline: datetime | None = None
    deadline_timezone: str | None = Field(default=None, max_length=100)
    source_url: str | None = Field(default=None, max_length=2000)
    confirmed_fields: set[str] = Field(default_factory=set)


class MembershipLifecycleEventResponse(BaseModel):
    event_id: UUID
    organization_id: UUID
    membership_id: UUID
    actor_user_id: UUID | None = None
    actor_membership_id: UUID | None = None
    action: str
    previous_role: str | None = None
    new_role: str | None = None
    previous_state: str | None = None
    new_state: str | None = None
    created_at: datetime


class AnalysisSourceDocumentSnapshot(BaseModel):
    tender_document_id: UUID
    display_name: str
    role: str
    snapshot_sha256: str
    content_sha256: str
    analyzed_text_sha256: str
    extracted_character_count: int
    file_type: str
    parse_ready: bool
    page_count: int | None = None
    page_count_known: bool = False
    language: str | None = None
    source_url: str | None = None
    duplicate_warning: str | None = None
    provenance: str = "SHARED_SOURCE"
    captured_at: datetime


class AnalysisPrivateVersionSnapshot(BaseModel):
    private_document_id: UUID
    document_version_id: UUID
    display_name: str
    version_number: int
    role: PrivateDocumentRole
    content_sha256: str
    processing_result_id: UUID | None = None
    processing_result_sha256: str | None = None
    extracted_character_count: int = 0
    processing_state: DocumentProcessingState
    parse_ready: bool
    page_count: int | None = None
    page_count_known: bool
    language: str | None = None
    malware_scan_status: str | None = None
    duplicate_warning: str | None = None
    provenance: str = "ORGANIZATION_PRIVATE_UPLOAD"


class AnalysisPackCandidateResponse(BaseModel):
    schema_version: str = "w4-analysis-pack-candidate-v1"
    candidate_sha256: str
    organization_id: UUID
    pursuit_id: UUID
    pursuit_origin: PursuitOrigin
    source_tender_id: UUID | None = None
    parse_ready: bool
    page_count_total: int | None = None
    source_documents: list[AnalysisSourceDocumentSnapshot] = Field(default_factory=list)
    private_versions: list[AnalysisPrivateVersionSnapshot] = Field(default_factory=list)
    generated_at: datetime


class PursuitAnalysisStartRequest(BaseModel):
    candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    analysis_language: str = Field(pattern=r"^(en|uz|ru)$")
    source_document_ids: list[UUID] = Field(default_factory=list)
    private_version_ids: list[UUID] = Field(default_factory=list)


class PursuitAnalysisStartResponse(BaseModel):
    analysis_run_id: UUID
    analysis_pack_id: UUID
    status: str
    selected_pack_sha256: str
    page_count_known: bool
    total_known_pages: int
    limit_disclosure: str


class PursuitAnalysisPackItemResponse(BaseModel):
    pack_item_id: UUID
    item_kind: str
    provenance: str
    display_name: str
    role: str
    version_number: int | None = None
    page_count: int | None = None
    page_count_known: bool
    content_sha256: str
    source_url: str | None = None


class PursuitRequirementResponse(BaseModel):
    requirement_id: UUID
    pack_item_id: UUID
    original_quote: str
    source_context: str | None = None
    normalized_requirement: str
    effective_normalized_requirement: str
    category: str
    requirement_type: str
    stage_scope: str
    distinction: str
    predicate: dict[str, Any] | None = None
    contribution_rule: str | None = None
    coverage_state: str
    effective_coverage_state: str
    review_state: str
    effective_review_state: str
    source_locator: dict[str, Any]
    generated_interpretation: str | None = None


class PursuitPositionResponse(BaseModel):
    position_id: UUID
    pack_item_id: UUID
    title: str
    effective_title: str
    quantity: int | None = None
    distinction: str
    education_qualification: str | None = None
    general_experience: str | None = None
    specific_experience: str | None = None
    relevant_assignments: str | None = None
    languages: list[Any] = Field(default_factory=list)
    certifications: list[Any] = Field(default_factory=list)
    location_travel: str | None = None
    expected_effort: str | None = None
    assignment_dates: str | None = None
    qualification_criteria: list[dict[str, Any]] = Field(default_factory=list)
    original_quote: str
    source_context: str | None = None
    coverage_state: str
    effective_coverage_state: str
    review_state: str
    effective_review_state: str
    source_locator: dict[str, Any]
    generated_interpretation: str | None = None


class PursuitGapResponse(BaseModel):
    gap_id: UUID
    requirement_id: UUID | None = None
    position_id: UUID | None = None
    source_pack_item_id: UUID
    missing_contribution: str
    coverage_state: str
    effective_coverage_state: str
    resolution_category: str
    effective_resolution_category: str
    review_state: str
    effective_review_state: str
    rationale: str


class PursuitAnalysisResponse(BaseModel):
    analysis_run_id: UUID
    analysis_pack_id: UUID
    status: str
    result_completeness: str | None = None
    quality_state: str
    quality_summary: str
    analysis_language: str
    model_provider: str
    model_name: str
    prompt_version: str
    schema_version: str
    pipeline_version: str
    created_at: datetime
    completed_at: datetime | None = None
    failure_stage: str | None = None
    failure_reason: str | None = None
    inputs_changed: bool
    stale_reason: str | None = None
    page_count_known: bool
    limit_disclosure: str
    pack_items: list[PursuitAnalysisPackItemResponse] = Field(default_factory=list)
    requirements: list[PursuitRequirementResponse] = Field(default_factory=list)
    positions: list[PursuitPositionResponse] = Field(default_factory=list)
    gaps: list[PursuitGapResponse] = Field(default_factory=list)


class AnalysisReviewAssertionRequest(BaseModel):
    target_kind: str = Field(pattern=r"^(REQUIREMENT|POSITION|GAP)$")
    target_id: UUID
    new_coverage_state: str = Field(
        pattern=r"^(SUPPORTED|PARTIAL|GAP|EVIDENCE_MISSING|NEEDS_INTERPRETATION|NOT_APPLICABLE|LATER_STAGE_OBLIGATION)$"
    )
    new_review_state: str = Field(pattern=r"^(CONFIRMED|CORRECTED)$")
    corrected_fields: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(min_length=3, max_length=4000)


class AnalysisReviewAssertionResponse(BaseModel):
    assertion_id: UUID
    analysis_run_id: UUID
    target_kind: str
    target_id: UUID
    prior_coverage_state: str | None = None
    new_coverage_state: str
    prior_review_state: str
    new_review_state: str
    corrected_fields: dict[str, Any]
    reason: str
    actor_membership_id: UUID
    created_at: datetime


class AnalysisLineageRequest(BaseModel):
    target_kind: str = Field(pattern=r"^(REQUIREMENT|POSITION)$")
    prior_item_id: UUID
    current_item_id: UUID
    rationale: str = Field(min_length=3, max_length=4000)


class AnalysisLineageResponse(BaseModel):
    lineage_id: UUID
    target_kind: str
    prior_item_id: UUID
    current_item_id: UUID
    actor_membership_id: UUID
    rationale: str
    created_at: datetime
