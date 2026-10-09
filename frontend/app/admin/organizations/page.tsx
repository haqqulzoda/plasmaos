'use client';

import { useCallback, useEffect, useState } from 'react';
import { Building2, RefreshCw } from 'lucide-react';

import { BidiText } from '@/components/i18n/BidiText';
import { Button } from '@/components/ui/Button';
import { DataTable, StatusBadge } from '@/components/ui/Display';
import { Alert } from '@/components/ui/Feedback';
import { api } from '@/lib/api';
import { formatTimestamp, type OrganizationPanelItem } from '@/lib/adminPanels';

/** R3 Task 5: organizations, read-only. The demo flag comes from the demo seed's provenance. */
export default function AdminOrganizationsPage() {
    const [items, setItems] = useState<OrganizationPanelItem[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const load = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            setItems((await api.get<OrganizationPanelItem[]>('/admin/panels/organizations')).data);
        } catch {
            setError('Organizations could not be loaded.');
        } finally {
            setLoading(false);
        }
    }, []);
    useEffect(() => { void load(); }, [load]);

    return <div className="admin-page ds-container-data ds-stack" data-admin-organizations>
        <header className="admin-page-header">
            <div className="admin-heading-with-icon">
                <Building2 aria-hidden />
                <div>
                    <span className="ds-eyebrow">Operations</span>
                    <h1>Organizations</h1>
                    <p className="ds-muted">Members, pursuits and last activity per organization. Read-only.</p>
                </div>
            </div>
            <Button variant="secondary" onClick={() => void load()} loading={loading} leadingIcon={<RefreshCw aria-hidden />}>Refresh</Button>
        </header>
        {error && <Alert tone="danger" title={error} />}
        <DataTable<OrganizationPanelItem>
            caption="Organizations"
            loading={loading}
            loadingLabel="Loading organizations…"
            empty={<span className="ds-muted">No organizations yet.</span>}
            rows={items}
            rowKey={(item) => item.organization_id}
            columns={[
                { key: 'name', heading: 'Organization', cell: (item) => <span className="ds-row">
                    <strong><BidiText>{item.display_name ?? '—'}</BidiText></strong>
                    {item.demo && <StatusBadge tone="info">Demo</StatusBadge>}
                </span> },
                { key: 'approval', heading: 'Approval', cell: (item) => item.approval_status ?? '—' },
                { key: 'pilot', heading: 'Pilot', cell: (item) => item.pilot_status?.replaceAll('_', ' ') ?? '—' },
                { key: 'members', heading: 'Members', numeric: true, cell: (item) => item.members_count },
                { key: 'pursuits', heading: 'Pursuits', numeric: true, cell: (item) => item.pursuits_count },
                { key: 'activity', heading: 'Last activity', cell: (item) => formatTimestamp(item.last_activity_at) },
                { key: 'created', heading: 'Created', cell: (item) => formatTimestamp(item.created_at) },
            ]}
        />
    </div>;
}
