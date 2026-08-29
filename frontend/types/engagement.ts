import type { SourceSystem, TenderStatus } from '@/types/tender';

export type EngagementStatus =
    | 'SAVED'
    | 'EVALUATING'
    | 'PREPARING'
    | 'SUBMITTED'
    | 'WON'
    | 'LOST'
    | 'DISMISSED';

export type EngagementOrigin =
    | 'MANUAL_SAVE'
    | 'MANUAL_EVALUATION'
    | 'BID_PREPARATION'
    | 'LEGACY_PROPOSAL'
    | 'OTHER_EXPLICIT_USER_ACTION';

export type EngagementAction =
    | 'SAVE'
    | 'EVALUATE'
    | 'PREPARE_BID'
    | 'MARK_SUBMITTED'
    | 'RECORD_WON'
    | 'RECORD_LOST'
    | 'DISMISS'
    | 'CORRECT_TO_PREPARING'
    | 'CORRECT_TO_SUBMITTED'
    | 'CORRECT_TO_WON'
    | 'CORRECT_TO_LOST';

export interface TenderEngagementSummary {
    engagement_id: string;
    tender_id: string;
    engagement_status: EngagementStatus;
    engagement_origin: EngagementOrigin;
    engagement_created_at: string;
    engagement_updated_at: string;
    status_changed_at: string;
    allowed_actions: EngagementAction[];
}

export interface TenderEngagementActionContext {
    engagement_id: string;
    engagement_status: EngagementStatus;
    allowed_actions: EngagementAction[];
}

export interface MyTenderListItem extends TenderEngagementSummary {
    tender_title: string;
    buyer: string | null;
    source_system: SourceSystem;
    tender_status: TenderStatus;
    deadline: string | null;
    estimated_value: number | null;
    currency: string | null;
    notice_type: string | null;
    procurement_method: string | null;
    country: string | null;
    region: string | null;
    project_external_id: string | null;
    project_name: string | null;
    project_source_system: string | null;
    project_enrichment_status: string | null;
}

export interface MyTenderStatusCounts {
    all: number;
    active: number;
    saved: number;
    evaluating: number;
    preparing: number;
    submitted: number;
    won: number;
    lost: number;
    dismissed: number;
}

export interface MyTendersListResponse {
    items: MyTenderListItem[];
    total: number;
    limit: number;
    offset: number;
    counts: MyTenderStatusCounts;
}

export interface TenderScopedEngagementResponse {
    engagement: TenderEngagementSummary | null;
    proposal_id: string | null;
}

export interface SaveToMyTendersResponse {
    engagement: TenderEngagementSummary;
    created: boolean;
    reengaged: boolean;
}

export interface TenderEngagementActionResponse {
    engagement: TenderEngagementSummary;
}

export const engagementStatusLabel = (status: EngagementStatus) => ({
    SAVED: 'Saved',
    EVALUATING: 'Evaluating',
    PREPARING: 'Preparing',
    SUBMITTED: 'Submitted',
    WON: 'Won',
    LOST: 'Lost',
    DISMISSED: 'Dismissed',
}[status]);

export const engagementStatusClasses = (status: EngagementStatus) => ({
    SAVED: 'border-sky-500/30 bg-sky-500/10 text-sky-200',
    EVALUATING: 'border-amber-500/30 bg-amber-500/10 text-amber-200',
    PREPARING: 'border-indigo-500/30 bg-indigo-500/10 text-indigo-200',
    SUBMITTED: 'border-violet-500/30 bg-violet-500/10 text-violet-200',
    WON: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-200',
    LOST: 'border-red-500/30 bg-red-500/10 text-red-200',
    DISMISSED: 'border-zinc-600 bg-zinc-800/70 text-zinc-300',
}[status]);

export const engagementStatusDescription = (status: EngagementStatus) => ({
    SAVED: 'Kept for later review.',
    EVALUATING: 'Assessing whether to pursue.',
    PREPARING: 'Preparing a bid.',
    SUBMITTED: 'Recorded as submitted.',
    WON: 'Recorded as won.',
    LOST: 'Recorded as lost.',
    DISMISSED: 'Not currently pursuing.',
}[status]);
