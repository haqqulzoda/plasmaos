'use client';

import { useCallback, useEffect, useState } from 'react';
import { BarChart3, RefreshCw } from 'lucide-react';

import { TechnicalText } from '@/components/i18n/BidiText';
import { Button } from '@/components/ui/Button';
import { DataTable, Metric } from '@/components/ui/Display';
import { Alert } from '@/components/ui/Feedback';
import { Checkbox, Select } from '@/components/ui/Forms';
import { api } from '@/lib/api';
import { eventLabel, formatCount, formatUsd, funnelShare, type ProductMetrics } from '@/lib/adminAnalytics';
import { formatLatency, formatTimestamp } from '@/lib/adminPanels';

type FunnelRow = ProductMetrics['funnel'][number];
type WeekRow = ProductMetrics['weekly_active_organizations'][number];
type CostRow = ProductMetrics['cost']['by_kind'][number];

function Bar({ value, max, label }: { value: number; max: number; label: string }) {
    const width = max > 0 ? Math.max(0, Math.min(100, (value / max) * 100)) : 0;
    return <span className="admin-bar-track" role="img" aria-label={label}>
        <span className="admin-bar" style={{ inlineSize: `${width}%` }} />
    </span>;
}

/** Sprint 1: weekly active organizations, the product funnel, analysis time and AI cost. Counts only. */
export default function AdminMetricsPage() {
    const [metrics, setMetrics] = useState<ProductMetrics | null>(null);
    const [funnelDays, setFunnelDays] = useState(28);
    const [includeDemo, setIncludeDemo] = useState(false);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const load = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const query = new URLSearchParams({ weeks: '8', funnel_days: String(funnelDays), include_demo: String(includeDemo) });
            setMetrics((await api.get<ProductMetrics>(`/admin/metrics?${query}`)).data);
        } catch {
            setError('Metrics could not be loaded.');
        } finally {
            setLoading(false);
        }
    }, [funnelDays, includeDemo]);
    useEffect(() => { void load(); }, [load]);

    const firstStep = metrics?.funnel[0]?.organizations ?? 0;
    const maxWeekly = Math.max(0, ...(metrics?.weekly_active_organizations ?? []).map((row) => row.active_organizations));
    const analysisCost = metrics?.cost.by_kind.find((row) => row.call_kind === 'ANALYSIS');
    const thisWeek = metrics?.weekly_active_organizations.at(-1)?.active_organizations;

    return <div className="admin-page ds-container-data ds-stack" data-admin-metrics>
        <header className="admin-page-header">
            <div className="admin-heading-with-icon">
                <BarChart3 aria-hidden />
                <div>
                    <span className="ds-eyebrow">Product</span>
                    <h1>Metrics</h1>
                    <p className="ds-muted">Server-side events and the AI cost ledger: ids, counts and timings only, never document content.</p>
                </div>
            </div>
            <Button variant="secondary" onClick={() => void load()} loading={loading} leadingIcon={<RefreshCw aria-hidden />}>Refresh</Button>
        </header>
        <fieldset className="admin-ledger-filters ds-row">
            <legend className="sr-only">Metric window</legend>
            <Select label="Funnel window" value={String(funnelDays)} onChange={(event) => setFunnelDays(Number(event.target.value))}>
                <option value="7">Last 7 days</option>
                <option value="28">Last 28 days</option>
                <option value="90">Last 90 days</option>
            </Select>
            <Checkbox label="Include demo organizations" checked={includeDemo} onChange={(event) => setIncludeDemo(event.target.checked)} />
        </fieldset>
        {error && <Alert tone="danger" title={error} />}

        <section className="admin-metric-grid" aria-label="Headline metrics">
            <Metric label="Active organizations this week" value={formatCount(thisWeek)} />
            <Metric label="Median analysis time" value={formatLatency(metrics?.analysis.median_time_to_result_ms)}
                supporting={metrics ? `p90 ${formatLatency(metrics.analysis.p90_time_to_result_ms)} · processing ${formatLatency(metrics.analysis.median_processing_ms)}` : undefined} />
            <Metric label="Analyses completed / failed" value={metrics ? `${formatCount(metrics.analysis.completed)} / ${formatCount(metrics.analysis.failed)}` : '—'}
                supporting={metrics ? `Last ${metrics.funnel_days} days` : undefined} />
            <Metric label="Cost per analysis" value={formatUsd(metrics?.cost.mean_cost_per_analysis_usd)}
                supporting={metrics ? `median ${formatUsd(metrics.cost.median_cost_per_analysis_usd)} · ${formatCount(metrics.cost.analyses_with_cost)} analyses` : undefined} />
            <Metric label="Analysis AI cost" value={formatUsd(analysisCost?.estimated_cost_usd)}
                supporting={analysisCost ? `${formatCount(analysisCost.calls)} calls` : undefined} />
        </section>
        {metrics && !metrics.include_demo && metrics.excluded_demo_organizations > 0 &&
            <p className="ds-muted">{formatCount(metrics.excluded_demo_organizations)} demo organization(s) excluded.</p>}

        <DataTable<FunnelRow>
            caption={`Funnel: organizations reaching each step, last ${metrics?.funnel_days ?? funnelDays} days`}
            loading={loading && !metrics}
            loadingLabel="Loading the funnel…"
            empty={<span className="ds-muted">No events yet.</span>}
            rows={metrics?.funnel ?? []}
            rowKey={(row) => row.step}
            columns={[
                { key: 'step', heading: 'Step', cell: (row) => eventLabel(row.step) },
                { key: 'organizations', heading: 'Organizations', numeric: true, cell: (row) => formatCount(row.organizations) },
                { key: 'share', heading: 'Of first step', numeric: true, cell: (row) => funnelShare(row.organizations, firstStep) },
                { key: 'bar', heading: <span className="sr-only">Share</span>, cell: (row) =>
                    <Bar value={row.organizations} max={firstStep} label={`${funnelShare(row.organizations, firstStep)} of organizations`} /> },
                { key: 'events', heading: 'Events', numeric: true, cell: (row) => formatCount(row.events) },
            ]}
        />

        <DataTable<WeekRow>
            caption="Weekly active organizations (any event by a member)"
            loading={loading && !metrics}
            loadingLabel="Loading weeks…"
            empty={<span className="ds-muted">No activity yet.</span>}
            rows={metrics?.weekly_active_organizations ?? []}
            rowKey={(row) => row.week_start}
            columns={[
                { key: 'week', heading: 'Week of', cell: (row) => row.week_start },
                { key: 'active', heading: 'Active organizations', numeric: true, cell: (row) => formatCount(row.active_organizations) },
                { key: 'bar', heading: <span className="sr-only">Relative</span>, cell: (row) =>
                    <Bar value={row.active_organizations} max={maxWeekly} label={`${row.active_organizations} active organizations`} /> },
            ]}
        />

        <DataTable<CostRow>
            caption={`AI cost by call type, last ${metrics?.funnel_days ?? funnelDays} days`}
            loading={loading && !metrics}
            loadingLabel="Loading costs…"
            empty={<span className="ds-muted">No AI calls recorded yet.</span>}
            rows={metrics?.cost.by_kind ?? []}
            rowKey={(row) => row.call_kind}
            columns={[
                { key: 'kind', heading: 'Call type', cell: (row) => eventLabel(row.call_kind.toLowerCase()) },
                { key: 'calls', heading: 'Calls', numeric: true, cell: (row) => formatCount(row.calls) },
                { key: 'subjects', heading: 'Runs / drafts', numeric: true, cell: (row) => formatCount(row.subjects) },
                { key: 'in', heading: 'Tokens in', numeric: true, cell: (row) => formatCount(row.input_tokens) },
                { key: 'out', heading: 'Tokens out', numeric: true, cell: (row) => formatCount(row.output_tokens) },
                { key: 'thinking', heading: 'Thinking', numeric: true, cell: (row) => formatCount(row.thinking_tokens) },
                { key: 'cost', heading: 'Estimated cost', numeric: true, cell: (row) => formatUsd(row.estimated_cost_usd) },
                { key: 'unpriced', heading: 'Unpriced calls', numeric: true, cell: (row) => formatCount(row.calls_without_price) },
            ]}
        />
        {metrics && <p className="ds-muted">
            Price table <TechnicalText>{metrics.cost.price_table_version}</TechnicalText> (set AI_PRICE_TABLE_JSON to change it). Other events:{' '}
            {Object.entries(metrics.other_events).map(([name, count]) => `${eventLabel(name)} ${formatCount(count)}`).join(' · ') || 'none'}.
            Generated {formatTimestamp(metrics.generated_at)}.
        </p>}
    </div>;
}
