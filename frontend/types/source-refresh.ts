export type ActiveRefreshStatus = 'queued' | 'running';
export type TerminalRefreshStatus = 'completed' | 'partial' | 'failed' | 'source_unavailable';

export interface SourceCatalogItem {
    source_system: string;
    display_name: string;
    refresh_enabled: boolean;
    can_refresh: boolean;
}

export interface SourceRefreshActiveJob {
    job_id: string;
    status: ActiveRefreshStatus;
    queued_at: string;
    started_at: string | null;
    heartbeat_at: string | null;
}

export interface SourceRefreshTerminalSummary {
    job_id: string;
    status: TerminalRefreshStatus;
    completed_at: string;
    fetched_count: number;
    created_count: number;
    updated_count: number;
    unchanged_count: number;
    skipped_count: number;
    failed_count: number;
    documents_discovered_count: number;
    documents_queued_count: number;
    counts_authoritative: boolean;
    fallback_used: boolean;
    degraded: boolean;
    terminal_reason: string;
}

export interface SourceRefreshStatusItem {
    source_system: string;
    display_name: string;
    refresh_enabled: boolean;
    can_refresh: boolean;
    active_job: SourceRefreshActiveJob | null;
    latest_terminal: SourceRefreshTerminalSummary | null;
    last_clean_completed: SourceRefreshTerminalSummary | null;
    last_partial: SourceRefreshTerminalSummary | null;
    last_failure: SourceRefreshTerminalSummary | null;
    activity_cursor: string;
}

export interface SourceRefreshActivityEvent extends SourceRefreshTerminalSummary {
    source_system: string;
    source_display_name: string;
}

export interface SourceRefreshActivityPage {
    events: SourceRefreshActivityEvent[];
    next_cursor: string;
    has_more: boolean;
}

export interface SourceRefreshCommandResponse {
    status: string;
    source_system: string;
    display_name: string;
    job_id: string | null;
    created_count: number;
    updated_count: number;
    unchanged_count: number;
    fetched_count: number;
    skipped_count: number;
    rejected_count: number;
    failed_count: number;
    documents_discovered_count: number;
    documents_queued_count: number;
    fallback_used: boolean;
    created_at: string | null;
    started_at: string | null;
    heartbeat_at: string | null;
    completed_at: string | null;
    elapsed_ms: number | null;
    source_newest_published_at: string | null;
    source_oldest_published_at: string | null;
    source_age_days: number | null;
    execution_health: string | null;
    freshness_health: string | null;
    coverage_health: string | null;
    last_updated: string | null;
    reused: boolean;
    message: string;
}

export interface RefreshActivityBatch {
    id: number;
    events: SourceRefreshActivityEvent[];
    total_created: number;
}

export type RefreshNoticeTone = 'success' | 'warning' | 'danger' | 'info';

export interface RefreshNotice {
    id: string;
    title: string;
    detail: string | null;
    tone: RefreshNoticeTone;
    href: string | null;
    action_label: string | null;
}
