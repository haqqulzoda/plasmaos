import type { EngagementAction, EngagementStatus } from '@/types/engagement';
import type { SourceSystem, TenderDocumentStatus, TenderStatus } from '@/types/tender';

export type ExplorerView = 'all' | 'recommended' | 'dismissed';
export type RecommendationAvailability = 'AVAILABLE' | 'PROFILE_REQUIRED';

export interface ExplorerTenderSummary {
    id: string;
    external_id: string;
    source_system: SourceSystem;
    canonical_source_key: string;
    source_url: string | null;
    title: string;
    buyer: string | null;
    budget: number;
    currency: string;
    deadline: string | null;
    publication_date: string | null;
    country: string | null;
    region: string | null;
    sector: string | null;
    status: TenderStatus;
    category: string;
    document_status: TenderDocumentStatus;
    document_count: number;
    created_at: string;
}

export interface RecommendationSummary {
    recommendation_id: string;
    match_score: number;
    rationale_summary: string;
    is_dismissed: boolean;
    created_at: string;
}

export interface PursuitSummary {
    engagement_id: string;
    status: EngagementStatus;
    allowed_actions: EngagementAction[];
}

export interface ExplorerItem {
    tender: ExplorerTenderSummary;
    recommendation: RecommendationSummary | null;
    pursuit: PursuitSummary | null;
}

export interface ExplorerCounts {
    all_tenders: number;
    active_recommendations: number;
    dismissed_recommendations: number;
}

export interface ExplorerResponse {
    view: ExplorerView;
    items: ExplorerItem[];
    total: number;
    limit: number;
    offset: number;
    counts: ExplorerCounts;
    recommendation_availability: RecommendationAvailability;
}

export interface RecommendationCommandResponse {
    status: 'dismissed' | 'restored';
    recommendation: RecommendationSummary;
}

export interface ExplorerListParams {
    view: ExplorerView;
    limit: number;
    offset: number;
    status: string;
    source?: string;
    q?: string;
    region?: string;
    countries?: string;
    services?: string;
    deadline_status?: string;
    price_min?: string;
    price_max?: string;
    document_status?: string;
    category?: string;
    sort?: string;
}
