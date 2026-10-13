/** Sprint 1: award ledger and product metrics admin pages (English/LTR admin boundary). Import-free helpers. */

export const LEDGER_STATUSES = ['AWARDED', 'EVALUATED', 'REJECTED', 'NOT_EVALUATED'] as const;
export type LedgerStatus = (typeof LEDGER_STATUSES)[number];

export type LedgerCountrySummary = {
    country: string;
    notices: number;
    notices_without_bidders: number;
    rows: Partial<Record<LedgerStatus, number>>;
};

export type LedgerSummary = {
    countries: LedgerCountrySummary[];
    notice_count: number;
    row_count: number;
    stored_snapshot_count: number;
    first_notice_date: string | null;
    last_notice_date: string | null;
    last_retrieved_at: string | null;
};

export type AwardOutcomeItem = {
    id: string;
    lender: string;
    country: string | null;
    project_id: string | null;
    project_name: string | null;
    notice_id: string;
    notice_url: string;
    notice_date: string | null;
    award_date: string | null;
    package_reference: string | null;
    package_title: string | null;
    procurement_group: string | null;
    procurement_method: string | null;
    bid_ordinal: number;
    member_ordinal: number;
    member_count: number;
    bidder_name: string;
    bidder_source_id: string | null;
    bidder_country: string | null;
    bidder_kind: string;
    status: LedgerStatus;
    evaluated_price_text: string | null;
    evaluated_price_currency: string | null;
    evaluated_price_amount: string | number | null;
    signed_contract_price_text: string | null;
    rejection_reason: string | null;
    retrieved_at: string;
    content_hash: string;
};

export type AwardOutcomePage = { items: AwardOutcomeItem[]; total: number; limit: number; offset: number };

export type LedgerFilters = {
    country?: string;
    status?: LedgerStatus | '';
    procurement_group?: string;
    q?: string;
};

export type ProductMetrics = {
    generated_at: string;
    include_demo: boolean;
    excluded_demo_organizations: number;
    weeks: number;
    funnel_days: number;
    weekly_active_organizations: { week_start: string; active_organizations: number }[];
    funnel: { step: string; organizations: number; events: number }[];
    other_events: Record<string, number>;
    analysis: {
        completed: number;
        failed: number;
        median_time_to_result_ms: number | null;
        median_processing_ms: number | null;
        p90_time_to_result_ms: number | null;
    };
    cost: {
        price_table_version: string;
        by_kind: {
            call_kind: string;
            calls: number;
            subjects: number;
            input_tokens: number;
            output_tokens: number;
            thinking_tokens: number;
            estimated_cost_usd: number | null;
            calls_without_price: number;
        }[];
        analyses_with_cost: number;
        mean_cost_per_analysis_usd: number | null;
        median_cost_per_analysis_usd: number | null;
    };
};

/** Non-empty filters only, in a stable order. */
export function ledgerQuery(filters: LedgerFilters, page?: { limit: number; offset: number }): string {
    const params = new URLSearchParams();
    for (const key of ['country', 'status', 'procurement_group', 'q'] as const) {
        const value = filters[key]?.trim();
        if (value) params.set(key, value);
    }
    if (page) {
        params.set('limit', String(page.limit));
        params.set('offset', String(page.offset));
    }
    return params.toString();
}

export function statusLabel(status: string): string {
    return status === 'NOT_EVALUATED' ? 'Not evaluated' : status.charAt(0) + status.slice(1).toLowerCase();
}

export function statusTone(status: string): 'success' | 'warning' | 'danger' | 'info' | 'neutral' {
    if (status === 'AWARDED') return 'success';
    if (status === 'REJECTED') return 'danger';
    if (status === 'EVALUATED') return 'info';
    return 'neutral';
}

/** "Bid 2 · member 1 of 3" for joint ventures, "Bid 2" otherwise. */
export function bidLabel(item: Pick<AwardOutcomeItem, 'bid_ordinal' | 'member_ordinal' | 'member_count'>): string {
    return item.member_count > 1
        ? `Bid ${item.bid_ordinal} · JV member ${item.member_ordinal} of ${item.member_count}`
        : `Bid ${item.bid_ordinal}`;
}

export function formatCount(value: number | null | undefined): string {
    return value === null || value === undefined ? '—' : value.toLocaleString('en-US');
}

/** US$ with enough precision for per-call costs: $0.0131, $4.50, $1,234. */
export function formatUsd(value: number | null | undefined): string {
    if (value === null || value === undefined) return '—';
    if (value !== 0 && Math.abs(value) < 1) return `$${value.toFixed(4)}`;
    return `$${value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

/** Share of the first funnel step that reached this step, as a whole percentage. */
export function funnelShare(organizations: number, first: number): string {
    if (!first) return '—';
    return `${Math.round((organizations / first) * 100)}%`;
}

export function eventLabel(name: string): string {
    const text = name.replaceAll('_', ' ');
    return text.charAt(0).toUpperCase() + text.slice(1);
}

/** Save a text download the API returned (CSV/markdown) under the server's file name. */
export function saveDownload(content: string, filename: string, type: string): void {
    const link = document.createElement('a');
    link.href = URL.createObjectURL(new Blob([content], { type }));
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}

/** attachment; filename="x.csv" -> x.csv */
export function filenameFrom(disposition: string | null | undefined, fallback: string): string {
    const match = /filename="([^"]+)"/.exec(disposition ?? '');
    return match ? match[1] : fallback;
}
