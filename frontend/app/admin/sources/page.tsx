'use client';

import { useCallback, useEffect, useState } from 'react';
import { Play, RefreshCw, Satellite } from 'lucide-react';

import { Button } from '@/components/ui/Button';
import { DataTable, StatusBadge } from '@/components/ui/Display';
import { Alert } from '@/components/ui/Feedback';
import { api } from '@/lib/api';
import { formatCadence, formatTimestamp, sourceTone, type SourcePanelItem } from '@/lib/adminPanels';

/** R3 Task 5: source refresh health. "Run now" uses the existing operator refresh path. */
export default function AdminSourcesPage() {
    const [items, setItems] = useState<SourcePanelItem[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [notice, setNotice] = useState<string | null>(null);
    const [busy, setBusy] = useState<string | null>(null);

    const load = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            setItems((await api.get<SourcePanelItem[]>('/admin/panels/sources')).data);
        } catch {
            setError('Source health could not be loaded.');
        } finally {
            setLoading(false);
        }
    }, []);
    useEffect(() => { void load(); }, [load]);

    const runNow = async (item: SourcePanelItem) => {
        setBusy(item.source_system);
        setNotice(null);
        setError(null);
        try {
            await api.post(`/tenders/sources/${encodeURIComponent(item.source_system)}/refresh`, undefined, { params: { force: true } });
            setNotice(`${item.display_name} refresh queued.`);
            await load();
        } catch {
            setError(`${item.display_name} refresh could not be queued.`);
        } finally {
            setBusy(null);
        }
    };

    return <div className="admin-page ds-container-data ds-stack" data-admin-sources>
        <header className="admin-page-header">
            <div className="admin-heading-with-icon">
                <Satellite aria-hidden />
                <div>
                    <span className="ds-eyebrow">Operations</span>
                    <h1>Sources</h1>
                    <p className="ds-muted">Refresh health of every customer-visible source. Reading this page changes nothing.</p>
                </div>
            </div>
            <Button variant="secondary" onClick={() => void load()} loading={loading} leadingIcon={<RefreshCw aria-hidden />}>Refresh</Button>
        </header>
        {error && <Alert tone="danger" title={error} />}
        {notice && <Alert tone="success" title={notice} />}
        <DataTable<SourcePanelItem>
            caption="Source refresh health"
            loading={loading}
            loadingLabel="Loading sources…"
            empty={<span className="ds-muted">No customer-visible sources.</span>}
            rows={items}
            rowKey={(item) => item.source_system}
            columns={[
                { key: 'source', heading: 'Source', cell: (item) => <strong>{item.display_name}</strong> },
                { key: 'status', heading: 'Status', cell: (item) => <span className="ds-row">
                    <StatusBadge tone={sourceTone(item)}>{item.running ? `Running (${item.status})` : item.status.replaceAll('_', ' ')}</StatusBadge>
                    {item.stale && <StatusBadge tone="warning">Stale</StatusBadge>}
                </span> },
                { key: 'attempt', heading: 'Last attempt', cell: (item) => formatTimestamp(item.last_attempt_at) },
                { key: 'success', heading: 'Last success', cell: (item) => <>{formatTimestamp(item.last_success_at)}{item.last_success_partial ? ' (partial)' : ''}</> },
                { key: 'new', heading: 'New', numeric: true, cell: (item) => item.new_count ?? '—' },
                { key: 'updated', heading: 'Updated', numeric: true, cell: (item) => item.updated_count ?? '—' },
                { key: 'next', heading: 'Next scheduled run', cell: (item) => <span>{formatTimestamp(item.next_scheduled_run_at)}<br /><small className="ds-muted">{formatCadence(item.scheduled_cadence_seconds)}</small></span> },
                { key: 'run', heading: <span className="sr-only">Actions</span>, cell: (item) => <Button size="sm" variant="secondary"
                    disabled={!item.can_run_now || busy !== null} loading={busy === item.source_system}
                    leadingIcon={<Play aria-hidden />} onClick={() => void runNow(item)}>Run now</Button> },
            ]}
        />
    </div>;
}
