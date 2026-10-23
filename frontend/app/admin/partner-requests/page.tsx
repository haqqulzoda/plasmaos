'use client';

import { useCallback, useEffect, useState } from 'react';
import { ExternalLink, Handshake, RefreshCw } from 'lucide-react';

import { BidiText } from '@/components/i18n/BidiText';
import { Button } from '@/components/ui/Button';
import { DataTable, StatusBadge } from '@/components/ui/Display';
import { Alert } from '@/components/ui/Feedback';
import { Select, Textarea } from '@/components/ui/Forms';
import { Dialog } from '@/components/ui/Overlay';
import { api } from '@/lib/api';
import { formatTimestamp } from '@/lib/adminPanels';
import type { PartnerRequest, PartnerRequestStatus } from '@/types/pursuit';

type AdminPartnerRequest = PartnerRequest & {
    organization_id: string | null;
    organization_name: string | null;
    requester_name: string | null;
    requester_email: string | null;
    tender_reference: string | null;
    tender_title: string | null;
    tender_url: string | null;
    next_statuses: PartnerRequestStatus[];
};

const STATUSES: PartnerRequestStatus[] = ['REQUESTED', 'CONTACTED', 'ACCEPTED', 'DECLINED', 'INTRODUCED'];
const LABEL: Record<PartnerRequestStatus, string> = {
    REQUESTED: 'Requested', CONTACTED: 'Contacted', ACCEPTED: 'Accepted', DECLINED: 'Declined', INTRODUCED: 'Introduced',
};
const TONE: Record<PartnerRequestStatus, 'info' | 'success' | 'warning' | 'danger'> = {
    REQUESTED: 'warning', CONTACTED: 'info', ACCEPTED: 'success', DECLINED: 'danger', INTRODUCED: 'success',
};

/** P2: the Plasma team's queue of partner introduction and expert sourcing requests. Every change is audited. */
export default function AdminPartnerRequestsPage() {
    const [items, setItems] = useState<AdminPartnerRequest[]>([]);
    const [filter, setFilter] = useState<PartnerRequestStatus | ''>('');
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [success, setSuccess] = useState<string | null>(null);
    const [editing, setEditing] = useState<{ item: AdminPartnerRequest; status: PartnerRequestStatus } | null>(null);
    const [message, setMessage] = useState('');
    const [saving, setSaving] = useState(false);
    const [formError, setFormError] = useState<string | null>(null);

    const load = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            setItems((await api.get<AdminPartnerRequest[]>('/admin/partner-requests', { params: filter ? { status: filter } : {} })).data);
        } catch {
            setError('Partner requests could not be loaded.');
        } finally {
            setLoading(false);
        }
    }, [filter]);
    useEffect(() => { void load(); }, [load]);

    const save = async () => {
        if (!editing) return;
        setSaving(true);
        setFormError(null);
        try {
            await api.post(`/admin/partner-requests/${editing.item.request_id}/status`, {
                status: editing.status, message: message.trim() || null,
            });
            setSuccess(`${editing.item.firm_name ?? 'Expert sourcing'} for ${editing.item.organization_name ?? 'the organization'}: ${LABEL[editing.status].toLowerCase()}.`);
            setEditing(null);
            setMessage('');
            await load();
        } catch (failure) {
            const detail = (failure as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
            setFormError(typeof detail === 'string' ? detail : 'The status could not be changed.');
        } finally {
            setSaving(false);
        }
    };

    return <div className="admin-page ds-container-data ds-stack" data-admin-partner-requests>
        <header className="admin-page-header">
            <div className="admin-heading-with-icon">
                <Handshake aria-hidden />
                <div>
                    <span className="ds-eyebrow">Operations</span>
                    <h1>Partner requests</h1>
                    <p className="ds-muted">
                        Introductions customers asked for, and experts to source. Plasma contacts the firm by hand; nothing is
                        sent to a suggested firm automatically. Suggestions come from public award records and are unverified.
                    </p>
                </div>
            </div>
            <Button variant="secondary" onClick={() => void load()} loading={loading} leadingIcon={<RefreshCw aria-hidden />}>Refresh</Button>
        </header>
        <div className="admin-filters">
            <Select label="Status" value={filter} onChange={(event) => setFilter(event.target.value as PartnerRequestStatus | '')}>
                <option value="">All</option>
                {STATUSES.map((status) => <option key={status} value={status}>{LABEL[status]}</option>)}
            </Select>
        </div>
        {error && <Alert tone="danger" title={error} />}
        {success && <Alert tone="success" title={success} />}
        <DataTable<AdminPartnerRequest>
            caption="Partner requests"
            loading={loading}
            loadingLabel="Loading partner requests…"
            empty={<span className="ds-muted">No partner requests{filter ? ` with status ${LABEL[filter].toLowerCase()}` : ''}.</span>}
            rows={items}
            rowKey={(item) => item.request_id}
            columns={[
                { key: 'created', heading: 'Requested', cell: (item) => formatTimestamp(item.created_at) },
                { key: 'organization', heading: 'Organization', cell: (item) => <span className="admin-partner-cell">
                    <strong><BidiText>{item.organization_name ?? '—'}</BidiText></strong>
                    <span className="ds-muted ds-text-small">{item.requester_name ? `${item.requester_name} · ` : ''}{item.requester_email ?? ''}</span>
                </span> },
                { key: 'tender', heading: 'Tender and gap', cell: (item) => <span className="admin-partner-cell">
                    {item.tender_url
                        ? <a href={item.tender_url} target="_blank" rel="noopener noreferrer">{item.tender_reference ?? 'Tender'} <ExternalLink aria-hidden /></a>
                        : <span>{item.tender_reference ?? '—'}</span>}
                    <span className="ds-text-small"><BidiText>{item.tender_title ?? ''}</BidiText></span>
                    <span className="ds-muted ds-text-small"><BidiText>{item.gap_summary}</BidiText></span>
                </span> },
                { key: 'firm', heading: 'Suggested firm', cell: (item) => item.kind === 'EXPERT_SOURCING'
                    ? <StatusBadge tone="info">Source an expert</StatusBadge>
                    : <span className="admin-partner-cell">
                        <strong><BidiText>{item.firm_name ?? '—'}</BidiText></strong>
                        <span className="ds-muted ds-text-small">{item.firm_country ?? ''}</span>
                        {item.awards.slice(0, 3).map((award) => <a key={award.notice_id} className="ds-text-small" href={award.notice_url} target="_blank" rel="noopener noreferrer">
                            {award.notice_id} · {award.year ?? ''} <ExternalLink aria-hidden />
                        </a>)}
                    </span> },
                { key: 'note', heading: 'Note', cell: (item) => item.note ? <span className="ds-text-small"><BidiText>{item.note}</BidiText></span> : '—' },
                { key: 'status', heading: 'Status', cell: (item) => <span className="admin-partner-cell admin-partner-status">
                    <StatusBadge tone={TONE[item.status]}>{LABEL[item.status]}</StatusBadge>
                    <span className="ds-muted ds-text-small">{formatTimestamp(item.status_changed_at)}</span>
                </span> },
                { key: 'next', heading: 'Move to', cell: (item) => item.next_statuses.length
                    ? <span className="ds-row">{item.next_statuses.map((status) => <Button key={status} size="sm"
                        variant={status === 'DECLINED' ? 'secondary' : 'primary'}
                        onClick={() => { setEditing({ item, status }); setMessage(''); setFormError(null); }}
                        aria-label={`Mark ${item.firm_name ?? 'expert sourcing'} as ${LABEL[status].toLowerCase()}`}>{LABEL[status]}</Button>)}</span>
                    : <span className="ds-muted">Closed</span> },
            ]}
        />
        <Dialog
            open={Boolean(editing)}
            onClose={() => !saving && setEditing(null)}
            title={editing ? `${LABEL[editing.status]}: ${editing.item.firm_name ?? 'expert sourcing'}` : ''}
            description="Audited. The requesting organization sees the new status and this message on its Team tab."
            closeLabel="Close status editor"
            footer={<>
                <Button variant="secondary" onClick={() => setEditing(null)} disabled={saving}>Cancel</Button>
                <Button onClick={() => void save()} loading={saving} variant={editing?.status === 'DECLINED' ? 'danger' : 'primary'}>Save</Button>
            </>}
        >
            <div className="ds-stack">
                <Textarea label="Message to the requesting organization (optional)" rows={3} maxLength={2000} value={message}
                    onChange={(event) => setMessage(event.target.value)} />
                {editing && editing.item.history.length > 0 && <ol className="ds-text-small">
                    {editing.item.history.map((event, index) => <li key={index}>
                        {formatTimestamp(event.at)} · {LABEL[event.to_status]}{event.message ? ` · ${event.message}` : ''}
                    </li>)}
                </ol>}
                {formError && <Alert tone="danger" title={formError} />}
            </div>
        </Dialog>
    </div>;
}
