export type SourceSystem = 'uzex' | 'world_bank' | 'adb' | 'giz' | 'ebrd';
export type TenderStatus = 'OPEN' | 'CLOSED' | 'CANCELLED' | 'UNKNOWN';

export type TenderDocumentStatus =
    | 'documents_available'
    | 'files_missing'
    | 'metadata_only'
    | 'access_required'
    | 'no_documents_found'
    | 'processing'
    | 'partial'
    | 'failed';

export type DocumentDownloadStatus =
    | 'available'
    | 'metadata_only'
    | 'failed'
    | 'missing_file'
    | 'processing'
    | 'access_required'
    | string;
export type CompetitorParticipationType = 'winner' | 'participant' | 'similar_market_actor';
export type CompetitorConfidence = 'high' | 'medium' | 'low';
export type TenderDeadlineUrgency = 'expired' | 'urgent' | 'soon' | 'normal' | 'unknown';
export type TenderContactAvailability = 'available' | 'partial' | 'missing';
export type TenderAvailabilityStatus = 'available' | 'unavailable';

export interface Tender {
    id: string;
    external_id: string;
    source_system: SourceSystem;
    canonical_source_key: string;
    source_url: string | null;
    title: string;
    description: string | null;
    budget: number;
    currency: string;
    deadline: string | null;
    publication_date: string | null;
    country: string | null;
    region: string | null;
    sector: string | null;
    buyer: string | null;
    procurement_category: string | null;
    procurement_method: string | null;
    notice_type: string | null;
    project_id: string | null;
    price_amount: number | null;
    price_currency: string | null;
    price_display: string | null;
    status: TenderStatus;
    category: string;
    has_compiled_text: boolean;
    document_status: TenderDocumentStatus;
    document_count: number;
    available_document_count: number;
    downloadable_document_count: number;
    missing_file_document_count: number;
    parsed_document_count: number;
    metadata_only_document_count: number;
    failed_document_count: number;
    compliance_analysis_available: boolean;
    compliance_unavailable_reason: string | null;
    contact_submission: TenderContactSubmission | null;
    created_at: string;
}

export interface TenderContactSubmission {
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
    source_url: string | null;
    document_access_notes: string | null;
}

export interface TenderDocument {
    id: string;
    file_type: string;
    display_name: string;
    download_url: string;
    download_status: DocumentDownloadStatus;
    original_filename?: string | null;
    storage_filename?: string | null;
    parsed_source_filenames?: string[];
    archive_inner_filenames?: string[];
    analysis_text_available?: boolean;
    file_size?: number | null;
    created_at: string;
}

export interface TenderCompetitor {
    company_name: string;
    industry: string;
    service_category: string;
    source: string;
    related_tender_id: string | null;
    buyer: string | null;
    country: string | null;
    sector: string | null;
    category: string | null;
    participation_type: CompetitorParticipationType;
    confidence: CompetitorConfidence;
    reason: string;
    evidence_source: string | null;
}

export interface TenderCompetitorGroup {
    industry: string;
    service_category: string;
    competitors: TenderCompetitor[];
}

export interface TenderCompetitorIntelligence {
    tender_id: string;
    message: string;
    groups: TenderCompetitorGroup[];
}

export interface TenderDecisionSnapshot {
    tender_id: string;
    source: SourceSystem;
    country: string | null;
    region: string | null;
    service_category: string | null;
    deadline: string | null;
    deadline_urgency: TenderDeadlineUrgency;
    price_amount: number | null;
    price_currency: string | null;
    price_display: string | null;
    document_status: TenderDocumentStatus;
    document_count: number;
    downloadable_document_count: number;
    missing_file_document_count: number;
    parsed_document_count: number;
    contact_availability: TenderContactAvailability;
    competitor_intelligence_status: TenderAvailabilityStatus;
    compliance_availability: TenderAvailabilityStatus;
    source_notice_available: boolean;
}

export const sourceLabel = (source?: string | null) => {
    if (source === 'world_bank') return 'World Bank';
    if (source === 'adb') return 'ADB';
    if (source === 'giz') return 'GIZ';
    if (source === 'ebrd') return 'EBRD';
    return 'UzEx';
};

export const sourceBadgeClasses = (source?: string | null) => {
    if (source === 'world_bank') {
        return 'border-sky-500/30 bg-sky-500/10 text-sky-300';
    }
    if (source === 'adb') {
        return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300';
    }
    if (source === 'giz') {
        return 'border-cyan-500/30 bg-cyan-500/10 text-cyan-300';
    }
    if (source === 'ebrd') {
        return 'border-violet-500/30 bg-violet-500/10 text-violet-300';
    }
    return 'border-indigo-500/30 bg-indigo-500/10 text-indigo-300';
};

export const isTenderActionable = (tenderOrStatus?: Tender | TenderStatus | string | null) => {
    const status = typeof tenderOrStatus === 'object' && tenderOrStatus !== null
        ? tenderOrStatus.status
        : tenderOrStatus;
    return String(status ?? '').trim().toUpperCase() === 'OPEN';
};

export const tenderStatusLabel = (status?: TenderStatus | string | null) => {
    const normalized = String(status ?? '').trim().toUpperCase();
    if (normalized === 'OPEN') return 'Open';
    if (normalized === 'CLOSED') return 'Closed';
    if (normalized === 'CANCELLED') return 'Cancelled';
    return 'Actionability unknown';
};

export const tenderStatusClasses = (status?: TenderStatus | string | null) => {
    const normalized = String(status ?? '').trim().toUpperCase();
    if (normalized === 'OPEN') return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300';
    if (normalized === 'CLOSED') return 'border-zinc-600 bg-zinc-800/60 text-zinc-300';
    if (normalized === 'CANCELLED') return 'border-red-500/30 bg-red-500/10 text-red-300';
    return 'border-amber-500/30 bg-amber-500/10 text-amber-300';
};

export const tenderActionabilityMessage = (status?: TenderStatus | string | null) => (
    isTenderActionable(status)
        ? ''
        : `${tenderStatusLabel(status)}. Only OPEN tenders can start a new compliance or bid workflow.`
);

export const documentStatusLabel = (status?: string | null) => {
    if (status === 'documents_available') return 'Ready for analysis';
    if (status === 'files_missing') return 'Preparation failed';
    if (status === 'metadata_only') return 'Document discovered';
    if (status === 'access_required') return 'Document discovered';
    if (status === 'processing') return 'Processing';
    if (status === 'partial') return 'Partial coverage';
    if (status === 'failed') return 'Preparation failed';
    return 'Documents unavailable';
};

export const documentStatusClasses = (status?: string | null) => {
    if (status === 'documents_available') {
        return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300';
    }
    if (status === 'files_missing') {
        return 'border-amber-500/30 bg-amber-500/10 text-amber-300';
    }
    if (status === 'metadata_only') {
        return 'border-amber-500/30 bg-amber-500/10 text-amber-300';
    }
    if (status === 'access_required') {
        return 'border-sky-500/30 bg-sky-500/10 text-sky-300';
    }
    if (status === 'processing') {
        return 'border-indigo-500/30 bg-indigo-500/10 text-indigo-300';
    }
    if (status === 'partial') {
        return 'border-amber-500/30 bg-amber-500/10 text-amber-300';
    }
    if (status === 'failed') {
        return 'border-red-500/30 bg-red-500/10 text-red-300';
    }
    return 'border-zinc-700 bg-zinc-800/60 text-zinc-400';
};

export type TenderDocumentAggregate = {
    document_status?: string | null;
    has_compiled_text?: boolean | null;
    compliance_analysis_available?: boolean | null;
    compliance_availability?: TenderAvailabilityStatus | null;
    downloadable_document_count?: number | null;
    missing_file_document_count?: number | null;
    parsed_document_count?: number | null;
};

export const documentAggregateLabel = (aggregate: TenderDocumentAggregate) => {
    const downloadableCount = aggregate.downloadable_document_count ?? 0;
    const missingCount = aggregate.missing_file_document_count ?? 0;
    const parsedCount = aggregate.parsed_document_count ?? 0;
    const analysisAvailable = Boolean(
        aggregate.has_compiled_text ||
        aggregate.compliance_analysis_available ||
        aggregate.compliance_availability === 'available' ||
        parsedCount > 0,
    );

    if (aggregate.document_status === 'partial') return 'Partial coverage';
    if (downloadableCount > 0 && analysisAvailable) return 'Ready for analysis';
    if (downloadableCount > 0) return 'Document discovered';
    if (missingCount > 0 && analysisAvailable) {
        return 'Partial coverage';
    }
    if (missingCount > 0) return 'Preparation failed';
    if (analysisAvailable) return 'Ready for analysis';
    return documentStatusLabel(aggregate.document_status);
};

export const deadlineUrgencyLabel = (urgency?: string | null) => {
    if (urgency === 'expired') return 'Expired';
    if (urgency === 'urgent') return 'Urgent';
    if (urgency === 'soon') return 'Soon';
    if (urgency === 'normal') return 'Normal';
    return 'Unknown deadline';
};

export const deadlineUrgencyClasses = (urgency?: string | null) => {
    if (urgency === 'expired') return 'border-red-500/30 bg-red-500/10 text-red-300';
    if (urgency === 'urgent') return 'border-amber-500/30 bg-amber-500/10 text-amber-300';
    if (urgency === 'soon') return 'border-sky-500/30 bg-sky-500/10 text-sky-300';
    if (urgency === 'normal') return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300';
    return 'border-zinc-700 bg-zinc-800/60 text-zinc-400';
};

export const contactAvailabilityLabel = (status?: string | null) => {
    if (status === 'available') return 'Contact available';
    if (status === 'partial') return 'Source notice available';
    return 'Contact missing';
};

export const contactAvailabilityClasses = (status?: string | null) => {
    if (status === 'available') return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300';
    if (status === 'partial') return 'border-sky-500/30 bg-sky-500/10 text-sky-300';
    return 'border-zinc-700 bg-zinc-800/60 text-zinc-400';
};

export const competitorStatusLabel = (status?: string | null) =>
    status === 'available' ? 'Competitor data available' : 'No competitor data yet';

export const complianceAvailabilityLabel = (status?: string | null) =>
    status === 'available' ? 'Ready for analysis' : 'Prepare documents for analysis';

export const availabilityClasses = (status?: string | null) =>
    status === 'available'
        ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
        : 'border-zinc-700 bg-zinc-800/60 text-zinc-400';

export const competitorConfidenceLabel = (confidence?: string | null) => {
    if (confidence === 'high') return 'High confidence';
    if (confidence === 'medium') return 'Medium confidence';
    return 'Low confidence';
};

export const competitorConfidenceClasses = (confidence?: string | null) => {
    if (confidence === 'high') {
        return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300';
    }
    if (confidence === 'medium') {
        return 'border-sky-500/30 bg-sky-500/10 text-sky-300';
    }
    return 'border-amber-500/30 bg-amber-500/10 text-amber-300';
};

export const competitorParticipationLabel = (participation?: string | null) => {
    if (participation === 'winner') return 'Historical winner';
    if (participation === 'participant') return 'Known market participant';
    return 'Similar market actor';
};

export const complianceUnavailableMessage = (tender: Tender) => {
    if (tender.compliance_unavailable_reason) return tender.compliance_unavailable_reason;
    if (tender.source_system === 'adb' && tender.document_status === 'metadata_only') {
        return 'Document discovered — preparation required before analysis.';
    }
    if (tender.source_system === 'ebrd') {
        return 'EBRD notices are metadata-only; participation documents require ECEPP registration.';
    }
    if (tender.document_status === 'files_missing') {
        return 'Preparation failed. Try preparing documents again before analysis.';
    }
    return 'Prepare documents for analysis';
};
