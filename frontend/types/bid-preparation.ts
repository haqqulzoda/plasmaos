import type { EngagementStatus, TenderEngagementSummary } from '@/types/engagement';
import type { TenderStatus } from '@/types/tender';

export type ProposalArtifactStatus = 'DRAFT' | 'GENERATING' | 'COMPLETED' | 'SUBMITTED';

export interface BidPreparationArtifact {
    id: string;
    user_id: string;
    tender_id: string;
    status: ProposalArtifactStatus;
    ai_confidence_score: number;
    structured_data: {
        strategic_summary?: string;
        ai_summary?: string;
        our_price?: number;
        delivery_days?: string | number;
    } | null;
    final_pdf_url: string | null;
    margin_percent: number;
    include_vat: boolean;
    currency: string;
    created_at: string;
    tender_title: string;
    tender_budget: number;
    tender_currency: string;
    tender_deadline: string | null;
    tender_region: string | null;
    tender_source_system: string;
    tender_status: TenderStatus;
    engagement_status: EngagementStatus | null;
}

export interface PrepareBidResponse {
    proposal: BidPreparationArtifact;
    engagement: TenderEngagementSummary;
    proposal_created: boolean;
    engagement_created: boolean;
}

export function preparationStatusLabel(status: ProposalArtifactStatus) {
    if (status === 'COMPLETED') return 'Completed preparation';
    if (status === 'GENERATING') return 'Generating';
    if (status === 'SUBMITTED') return 'Legacy submitted artifact';
    return 'Draft';
}

export function preparationStatusClasses(status: ProposalArtifactStatus) {
    if (status === 'COMPLETED') return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-200';
    if (status === 'GENERATING') return 'border-sky-500/30 bg-sky-500/10 text-sky-200';
    if (status === 'SUBMITTED') return 'border-amber-500/30 bg-amber-500/10 text-amber-200';
    return 'border-zinc-600 bg-zinc-800 text-zinc-200';
}
