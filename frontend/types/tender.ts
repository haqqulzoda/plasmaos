export type SourceSystem = 'uzex' | 'world_bank' | 'adb';

export type TenderDocumentStatus =
    | 'documents_available'
    | 'metadata_only'
    | 'no_documents_found'
    | 'processing'
    | 'failed';

export type DocumentDownloadStatus = 'available' | 'metadata_only' | 'failed' | string;

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
    status: string;
    category: string;
    has_compiled_text: boolean;
    document_status: TenderDocumentStatus;
    document_count: number;
    available_document_count: number;
    metadata_only_document_count: number;
    failed_document_count: number;
    compliance_analysis_available: boolean;
    compliance_unavailable_reason: string | null;
    created_at: string;
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
    file_size?: number | null;
    created_at: string;
}

export const sourceLabel = (source?: string | null) => {
    if (source === 'world_bank') return 'World Bank';
    if (source === 'adb') return 'ADB';
    return 'UzEx';
};

export const sourceBadgeClasses = (source?: string | null) => {
    if (source === 'world_bank') {
        return 'border-sky-500/30 bg-sky-500/10 text-sky-300';
    }
    if (source === 'adb') {
        return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300';
    }
    return 'border-indigo-500/30 bg-indigo-500/10 text-indigo-300';
};

export const documentStatusLabel = (status?: string | null) => {
    if (status === 'documents_available') return 'Documents available';
    if (status === 'metadata_only') return 'PDF notice discovered';
    if (status === 'processing') return 'Processing documents';
    if (status === 'failed') return 'Document processing failed';
    return 'No documents found';
};

export const documentStatusClasses = (status?: string | null) => {
    if (status === 'documents_available') {
        return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300';
    }
    if (status === 'metadata_only') {
        return 'border-amber-500/30 bg-amber-500/10 text-amber-300';
    }
    if (status === 'processing') {
        return 'border-indigo-500/30 bg-indigo-500/10 text-indigo-300';
    }
    if (status === 'failed') {
        return 'border-red-500/30 bg-red-500/10 text-red-300';
    }
    return 'border-zinc-700 bg-zinc-800/60 text-zinc-400';
};

export const complianceUnavailableMessage = (tender: Tender) => {
    if (tender.compliance_unavailable_reason) return tender.compliance_unavailable_reason;
    if (tender.source_system === 'adb' && tender.document_status === 'metadata_only') {
        return 'PDF notice discovered — download/parse required before analysis.';
    }
    return 'Document ingestion required before analysis.';
};
