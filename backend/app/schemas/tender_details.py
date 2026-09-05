"""Explicit, bounded schemas for the secondary Tender Details read model."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.base import ProposalStatus, TenderEngagementOrigin, TenderEngagementStatus


class DetailsSectionState(str, Enum):
    AVAILABLE = "AVAILABLE"
    EMPTY = "EMPTY"
    UNAVAILABLE = "UNAVAILABLE"


class ProjectContextSummary(BaseModel):
    project_id: UUID
    external_project_id: str
    name: str | None = None
    source_system: str
    project_status: str | None = None
    country: str | None = None
    region: str | None = None
    approval_date: date | None = None
    closing_date: date | None = None
    enrichment_state: str
    last_enriched_at: datetime | None = None


class ProjectLeadershipItem(BaseModel):
    role_id: UUID
    role_type: Literal["PROJECT_LEADERSHIP"] = "PROJECT_LEADERSHIP"
    display_name: str
    native_role: str
    canonical_role: str
    source_system: str
    source_url: str | None = None
    is_current: bool
    first_observed_at: datetime
    last_observed_at: datetime
    ended_at: datetime | None = None


class ProjectLeadershipSummary(BaseModel):
    items: list[ProjectLeadershipItem] = Field(default_factory=list)
    total_count: int
    returned_count: int
    truncated: bool


class ProcurementContactsSummary(BaseModel):
    buyer_agency: str | None = None
    contact_person: str | None = None
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    submission_method: str | None = None
    submission_deadline: datetime | None = None
    question_deadline: datetime | None = None
    procedure_type: str | None = None
    participation_instructions: str | None = None
    official_source_url: str | None = None
    document_access_notes: str | None = None
    source_type: Literal["TENDER_SOURCE"] = "TENDER_SOURCE"


class RequirementSummaryItem(BaseModel):
    label: str
    source_type: Literal["AI_EXTRACTED", "ANALYSIS_DERIVED"]
    document_name: str | None = None
    page: int | None = None
    section: str | None = None


class RequirementsSummary(BaseModel):
    source_native_available: bool = False
    derivation: Literal["ANALYSIS_VERSION"] = "ANALYSIS_VERSION"
    items: list[RequirementSummaryItem] = Field(default_factory=list)
    total_count: int
    returned_count: int
    truncated: bool


class TenderDocumentSummaryItem(BaseModel):
    document_id: UUID
    display_name: str
    document_type: str
    metadata_classification: Literal["PUBLIC_SOURCE_METADATA"]
    source_system: str
    availability: Literal["AVAILABLE", "UNAVAILABLE", "METADATA_ONLY"]
    file_size: int | None = None
    content_type: str | None = None
    created_at: datetime


class TenderDocumentsSummary(BaseModel):
    items: list[TenderDocumentSummaryItem] = Field(default_factory=list)
    visible_total_count: int
    returned_count: int
    omitted_unknown_count: int
    truncated: bool
    download_authorization_separate: Literal[True] = True


class ComplianceSummary(BaseModel):
    analysis_id: UUID
    version_number: int
    analysis_language: str | None = None
    execution_state: str
    compliance_completeness: str
    decision_label: str | None = None
    key_issue_count: int | None = None
    coverage_signal: str | None = None
    version_origin: str
    override_applied: bool
    created_at: datetime
    completed_at: datetime | None = None


class CompanyReadinessSummary(BaseModel):
    profile_available: Literal[True] = True
    certifications_total: int
    expired_certifications: int
    licenses_total: int
    active_licenses: int
    credentials_total: int
    expired_credentials: int
    readiness_documents_total: int
    readiness_documents_available: int
    readiness_documents_missing: int
    readiness_documents_expired: int
    readiness_documents_unknown: int
    financial_history_years: int


class PursuitSummary(BaseModel):
    engagement_id: UUID
    engagement_status: TenderEngagementStatus
    engagement_origin: TenderEngagementOrigin
    status_changed_at: datetime
    allowed_actions: list[str] = Field(default_factory=list)


class BidPreparationSummary(BaseModel):
    proposal_id: UUID
    proposal_status: ProposalStatus
    created_at: datetime
    detail_route_id: UUID


class ProjectContextSection(BaseModel):
    state: DetailsSectionState
    data: ProjectContextSummary | None = None
    reason_code: str | None = None


class ProjectLeadershipSection(BaseModel):
    state: DetailsSectionState
    data: ProjectLeadershipSummary | None = None
    reason_code: str | None = None


class ProcurementContactsSection(BaseModel):
    state: DetailsSectionState
    data: ProcurementContactsSummary | None = None
    reason_code: str | None = None


class RequirementsSection(BaseModel):
    state: DetailsSectionState
    data: RequirementsSummary | None = None
    reason_code: str | None = None


class TenderDocumentsSection(BaseModel):
    state: DetailsSectionState
    data: TenderDocumentsSummary | None = None
    reason_code: str | None = None


class ComplianceSection(BaseModel):
    state: DetailsSectionState
    data: ComplianceSummary | None = None
    reason_code: str | None = None


class CompanyReadinessSection(BaseModel):
    state: DetailsSectionState
    data: CompanyReadinessSummary | None = None
    reason_code: str | None = None


class PursuitSection(BaseModel):
    state: DetailsSectionState
    data: PursuitSummary | None = None
    reason_code: str | None = None


class BidPreparationSection(BaseModel):
    state: DetailsSectionState
    data: BidPreparationSummary | None = None
    reason_code: str | None = None


class TenderDetailsResponse(BaseModel):
    tender_id: UUID
    project_context: ProjectContextSection
    project_leadership: ProjectLeadershipSection
    procurement_contacts: ProcurementContactsSection
    requirements: RequirementsSection
    documents: TenderDocumentsSection
    compliance: ComplianceSection
    company_readiness: CompanyReadinessSection
    pursuit: PursuitSection
    bid_preparation: BidPreparationSection
