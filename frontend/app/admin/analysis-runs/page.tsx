'use client';

import { useCallback, useEffect, useState } from 'react';
import { Activity, RefreshCw, RotateCcw } from 'lucide-react';

import { TechnicalText } from '@/components/i18n/BidiText';
import { Button } from '@/components/ui/Button';
import { DataTable, StatusBadge } from '@/components/ui/Display';
import { Alert } from '@/components/ui/Feedback';
import { Checkbox } from '@/components/ui/Forms';
import { api } from '@/lib/api';
import {
    RUN_KINDS,
    formatLatency,
    formatTimestamp,
    runLabels,
    runQuery,
    shortId,
    type AnalysisRunPanelItem,
    type RunKind,
} from '@/lib/adminPanels';

/** R3 Task 5: failed, stuck and long analysis runs across organizations. Ids, stages and codes only. */
export default function AdminAnalysisRunsPage() {
    const [kinds, setKinds] = useState<RunKind[]>([...RUN_KINDS]);
    const [items, setItems] = useState<AnalysisRunPanelItem[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [notice, setNotice] = useState<string | null>(null);
    const [busy, setBusy] = useState<string | null>(null);

    const load = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            setItems((await api.get<AnalysisRunPanelItem[]>(`/admin/panels/analysis-runs?${runQuery(kinds)}`)).data);
        } catch {
            setError('Analysis runs could not be loaded.');
        } finally {
            setLoading(false);
        }
    }, [kinds]);
    useEffect(() => { void load(); }, [load]);

    const retry = async (item: AnalysisRunPanelItem) => {
        setBusy(item.analysis_run_id);
        setError(null);
        setNotice(null);
        try {
            const { data } = await api.post<{ analysis_run_id: string }>(`/admin/panels/analysis-runs/${encodeURIComponent(item.analysis_run_id)}/retry`);
            setNotice(`Retry queued as run ${shortId(data.analysis_run_id)}.`);
            await load();
        } catch (failure) {
            const detail = (failure as { response?: { data?: { detail?: { message?: string } } } })?.response?.data?.detail;
            setError(detail?.message ?? 'The retry could not be queued.');
        } finally {
            setBusy(null);
        }
    };

    return <div className="admin-page ds-container-data ds-stack" data-admin-analysis-runs>
        <header className="admin-page-header">
            <div className="admin-heading-with-icon">
                <Activity aria-hidden />
                <div>
                    <span className="ds-eyebrow">Operations</span>
                    <h1>Analysis runs</h1>
                    <p className="ds-muted">Failed, stuck and long runs across organizations. No document or finding content is shown.</p>
                </div>
            </div>
            <Button variant="secondary" onClick={() => void load()} loading={loading} leadingIcon={<RefreshCw aria-hidden />}>Refresh</Button>
        </header>
        <fieldset className="admin-run-filters ds-row">
            <legend className="sr-only">Show runs that are</legend>
            {RUN_KINDS.map((kind) => <Checkbox key={kind} label={kind[0].toUpperCase() + kind.slice(1)} checked={kinds.includes(kind)}
                onChange={(event) => setKinds((current) => event.target.checked ? [...current, kind] : current.filter((value) => value !== kind))} />)}
        </fieldset>
        {error && <Alert tone="danger" title={error} />}
        {notice && <Alert tone="success" title={notice} />}
        <DataTable<AnalysisRunPanelItem>
            caption="Analysis runs needing attention"
            loading={loading}
            loadingLabel="Loading runs…"
            empty={<span className="ds-muted">No failed, stuck or long runs.</span>}
            rows={items}
            rowKey={(item) => item.analysis_run_id}
            columns={[
                { key: 'run', heading: 'Run', cell: (item) => <TechnicalText>{shortId(item.analysis_run_id)}</TechnicalText> },
                { key: 'organization', heading: 'Organization', cell: (item) => <span>{item.organization_name ?? '—'}<br /><small className="ds-muted"><TechnicalText>{shortId(item.organization_id)}</TechnicalText> · pursuit <TechnicalText>{shortId(item.pursuit_id)}</TechnicalText></small></span> },
                { key: 'state', heading: 'Status / stage', cell: (item) => <span className="ds-row">
                    {runLabels(item).map((label) => <StatusBadge key={label} tone={label === 'Failed' ? 'danger' : 'warning'}>{label}</StatusBadge>)}
                    <small className="ds-muted">{item.status}{item.stage !== item.status ? ` · ${item.stage}` : ''}</small>
                </span> },
                { key: 'code', heading: 'Failure code', cell: (item) => item.failure_code ? <TechnicalText>{item.failure_code}</TechnicalText> : '—' },
                { key: 'model', heading: 'Model', cell: (item) => <TechnicalText>{item.model_name}</TechnicalText> },
                { key: 'latency', heading: 'Latency', numeric: true, cell: (item) => formatLatency(item.latency_ms) },
                { key: 'attempts', heading: 'Attempts', numeric: true, cell: (item) => `${item.attempt_count}/${item.max_attempts}` },
                { key: 'created', heading: 'Created', cell: (item) => formatTimestamp(item.created_at) },
                { key: 'retry', heading: <span className="sr-only">Actions</span>, cell: (item) => item.retry_allowed
                    ? <Button size="sm" variant="secondary" loading={busy === item.analysis_run_id} disabled={busy !== null}
                        leadingIcon={<RotateCcw aria-hidden />} onClick={() => void retry(item)}>Retry</Button>
                    : null },
            ]}
        />
    </div>;
}
