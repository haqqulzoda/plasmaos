/** R3 Task 5: admin/operator panels (English/LTR admin boundary). Import-free helpers. */

export type SourcePanelItem = {
    source_system: string;
    display_name: string;
    status: string;
    running: boolean;
    last_attempt_at: string | null;
    last_success_at: string | null;
    last_success_partial: boolean;
    new_count: number | null;
    updated_count: number | null;
    failed_count: number | null;
    terminal_reason: string | null;
    scheduled_cadence_seconds: number | null;
    next_scheduled_run_at: string | null;
    stale: boolean | null;
    can_run_now: boolean;
};

export type AnalysisRunPanelItem = {
    analysis_run_id: string;
    organization_id: string;
    organization_name: string | null;
    pursuit_id: string;
    status: string;
    stage: string;
    failure_code: string | null;
    model_name: string;
    pipeline_version: string;
    attempt_count: number;
    max_attempts: number;
    created_at: string;
    started_at: string | null;
    completed_at: string | null;
    latency_ms: number | null;
    stuck: boolean;
    long: boolean;
    retry_allowed: boolean;
};

export type OrganizationPanelItem = {
    organization_id: string;
    display_name: string | null;
    approval_status: string | null;
    pilot_status: string | null;
    members_count: number;
    pursuits_count: number;
    last_activity_at: string | null;
    created_at: string;
    demo: boolean;
};

export const RUN_KINDS = ['failed', 'stuck', 'long'] as const;
export type RunKind = (typeof RUN_KINDS)[number];

export function shortId(value: string): string {
    return value.slice(0, 8);
}

/** 950 ms, 12.4 s, 3 min 05 s, 2 h 04 min. */
export function formatLatency(ms: number | null | undefined): string {
    if (ms === null || ms === undefined || ms < 0) return '—';
    if (ms < 1_000) return `${ms} ms`;
    const seconds = ms / 1_000;
    if (seconds < 60) return `${seconds.toFixed(1)} s`;
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes} min ${String(Math.floor(seconds % 60)).padStart(2, '0')} s`;
    return `${Math.floor(minutes / 60)} h ${String(minutes % 60).padStart(2, '0')} min`;
}

export function formatCadence(seconds: number | null | undefined): string {
    if (!seconds) return 'Not scheduled';
    if (seconds % 86_400 === 0) return `Every ${seconds / 86_400 === 1 ? 'day' : `${seconds / 86_400} days`}`;
    if (seconds % 3_600 === 0) return `Every ${seconds / 3_600} h`;
    return `Every ${Math.round(seconds / 60)} min`;
}

export function formatTimestamp(value: string | null | undefined): string {
    if (!value) return '—';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? '—' : date.toISOString().replace('T', ' ').slice(0, 16) + ' UTC';
}

export function sourceTone(item: Pick<SourcePanelItem, 'status' | 'stale' | 'running'>): 'success' | 'warning' | 'danger' | 'info' | 'neutral' {
    if (item.running) return 'info';
    if (item.status === 'failed' || item.status === 'source_unavailable') return 'danger';
    if (item.stale || item.status === 'partial') return 'warning';
    if (item.status === 'completed') return 'success';
    return 'neutral';
}

/** The run's attention labels, most severe first. */
export function runLabels(item: Pick<AnalysisRunPanelItem, 'status' | 'stuck' | 'long'>): string[] {
    const labels: string[] = [];
    if (item.status === 'FAILED') labels.push('Failed');
    if (item.stuck) labels.push('Stuck');
    if (item.long) labels.push('Long');
    return labels;
}

export function runQuery(kinds: readonly RunKind[]): string {
    const selected = RUN_KINDS.filter((kind) => kinds.includes(kind));
    return (selected.length ? selected : RUN_KINDS).map((kind) => `kind=${kind}`).join('&');
}
