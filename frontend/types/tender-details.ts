import type {
    EngagementAction,
    EngagementOrigin,
    EngagementStatus,
} from '@/types/engagement';
import type { SourceSystem } from '@/types/tender';

export type DetailsSectionState = 'AVAILABLE' | 'EMPTY' | 'UNAVAILABLE';

export interface DetailsSection<T> {
    state: DetailsSectionState;
    data: T | null;
    reason_code: string | null;
}

export interface TenderDetailsProjectContext {
    project_id: string;
    external_project_id: string;
    name: string | null;
    source_system: SourceSystem;
    project_status: string | null;
    country: string | null;
    region: string | null;
    approval_date: string | null;
    closing_date: string | null;
    enrichment_state: string;
    last_enriched_at: string | null;
}

export interface TenderDetailsProjectLeadershipItem {
    role_id: string;
    role_type: 'PROJECT_LEADERSHIP';
    display_name: string;
    native_role: string;
    canonical_role: string;
    source_system: SourceSystem;
    source_url: string | null;
    is_current: boolean;
    first_observed_at: string;
    last_observed_at: string;
    ended_at: string | null;
}

export interface TenderDetailsProjectLeadership {
    items: TenderDetailsProjectLeadershipItem[];
    total_count: number;
    returned_count: number;
    truncated: boolean;
}

export interface TenderDetailsProcurementContacts {
    buyer_agency: string | null;
    contact_person: string | null;
    email: string | null;
    phone: string | null;
    address: string | null;
    submission_method: string | null;
    submission_deadline: string | null;
    question_deadline: string | null;
    procedure_type: string | null;
    participation_instructions: string | null;
    official_source_url: string | null;
    document_access_notes: string | null;
    source_type: 'TENDER_SOURCE';
}

export interface TenderDetailsRequirementItem {
    label: string;
    source_type: 'AI_EXTRACTED' | 'ANALYSIS_DERIVED';
    document_name: string | null;
    page: number | null;
    section: string | null;
}

export interface TenderDetailsRequirements {
    source_native_available: boolean;
    derivation: 'ANALYSIS_VERSION';
    items: TenderDetailsRequirementItem[];
    total_count: number;
    returned_count: number;
    truncated: boolean;
}

export type TenderDetailsDocumentAvailability =
    | 'AVAILABLE'
    | 'UNAVAILABLE'
    | 'METADATA_ONLY';

export interface TenderDetailsDocumentItem {
    document_id: string;
    display_name: string;
    document_type: string;
    metadata_classification: 'PUBLIC_SOURCE_METADATA';
    source_system: SourceSystem;
    availability: TenderDetailsDocumentAvailability;
    file_size: number | null;
    content_type: string | null;
    created_at: string;
}

export interface TenderDetailsDocuments {
    items: TenderDetailsDocumentItem[];
    visible_total_count: number;
    returned_count: number;
    omitted_unknown_count: number;
    truncated: boolean;
    download_authorization_separate: true;
}

export interface TenderDetailsCompliance {
    analysis_id: string;
    version_number: number;
    execution_state: string;
    compliance_completeness: string;
    decision_label: string | null;
    key_issue_count: number | null;
    coverage_signal: string | null;
    version_origin: string;
    override_applied: boolean;
    created_at: string;
    completed_at: string | null;
}

export interface TenderDetailsCompanyReadiness {
    profile_available: true;
    certifications_total: number;
    expired_certifications: number;
    licenses_total: number;
    active_licenses: number;
    credentials_total: number;
    expired_credentials: number;
    readiness_documents_total: number;
    readiness_documents_available: number;
    readiness_documents_missing: number;
    readiness_documents_expired: number;
    readiness_documents_unknown: number;
    financial_history_years: number;
}

export interface TenderDetailsPursuit {
    engagement_id: string;
    engagement_status: EngagementStatus;
    engagement_origin: EngagementOrigin;
    status_changed_at: string;
    allowed_actions: EngagementAction[];
}

export type ProposalStatus = 'DRAFT' | 'GENERATING' | 'COMPLETED' | 'SUBMITTED';

export interface TenderDetailsBidPreparation {
    proposal_id: string;
    proposal_status: ProposalStatus;
    created_at: string;
    detail_route_id: string;
}

export interface TenderDetailsResponse {
    tender_id: string;
    project_context: DetailsSection<TenderDetailsProjectContext>;
    project_leadership: DetailsSection<TenderDetailsProjectLeadership>;
    procurement_contacts: DetailsSection<TenderDetailsProcurementContacts>;
    requirements: DetailsSection<TenderDetailsRequirements>;
    documents: DetailsSection<TenderDetailsDocuments>;
    compliance: DetailsSection<TenderDetailsCompliance>;
    company_readiness: DetailsSection<TenderDetailsCompanyReadiness>;
    pursuit: DetailsSection<TenderDetailsPursuit>;
    bid_preparation: DetailsSection<TenderDetailsBidPreparation>;
}
