'use client';

import { useCallback, useEffect, useState } from 'react';
import { useSession } from 'next-auth/react';
import { Building2, Pencil, RefreshCw } from 'lucide-react';

import { BidiText } from '@/components/i18n/BidiText';
import { Button } from '@/components/ui/Button';
import { DataTable, StatusBadge } from '@/components/ui/Display';
import { Alert } from '@/components/ui/Feedback';
import { Input, Select, Textarea } from '@/components/ui/Forms';
import { Dialog } from '@/components/ui/Overlay';
import { api } from '@/lib/api';
import {
    formatTimestamp,
    ORGANIZATION_ACCESS_STATES,
    type OrganizationAccessState,
    type OrganizationPanelItem,
} from '@/lib/adminPanels';

const ACCESS_TONE: Record<OrganizationAccessState, 'info' | 'success' | 'warning' | 'danger'> = {
    explore: 'info', pilot: 'success', paid: 'success', disabled: 'danger',
};
const ACCESS_HELP: Record<OrganizationAccessState, string> = {
    explore: 'Opportunities feed, coverage and the guided demo analysis only.',
    pilot: 'Full access for the pilot period.',
    paid: 'Full access.',
    disabled: 'No access for any member.',
};

type AccessForm = {
    access_state: OrganizationAccessState;
    plan_started_on: string;
    plan_ends_on: string;
    success_criteria: string;
    reason: string;
};

function plusMonths(isoDate: string, months: number): string {
    const [year, month, day] = isoDate.split('-').map(Number);
    const end = new Date(Date.UTC(year, month - 1 + months, day));
    if (end.getUTCDate() !== day) end.setUTCDate(0); // 31 Jan + 1 month = 28/29 Feb
    return end.toISOString().slice(0, 10);
}

function planLabel(item: OrganizationPanelItem): string {
    if (!item.plan_started_on && !item.plan_ends_on) return '—';
    return `${item.plan_started_on ?? '…'} → ${item.plan_ends_on ?? '…'}`;
}

/** R3 Task 5 organizations; P1: access state (explore | pilot | paid | disabled) and plan, editable by admins. */
export default function AdminOrganizationsPage() {
    const { data: session } = useSession();
    const canEdit = session?.approval_status === 'approved' && (session?.is_admin === true || session?.platform_role === 'admin');
    const [items, setItems] = useState<OrganizationPanelItem[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [success, setSuccess] = useState<string | null>(null);
    const [editing, setEditing] = useState<OrganizationPanelItem | null>(null);
    const [form, setForm] = useState<AccessForm | null>(null);
    const [saving, setSaving] = useState(false);
    const [formError, setFormError] = useState<string | null>(null);

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

    const startEdit = (item: OrganizationPanelItem) => {
        setEditing(item);
        setFormError(null);
        setForm({
            access_state: item.access_state,
            plan_started_on: item.plan_started_on ?? '',
            plan_ends_on: item.plan_ends_on ?? '',
            success_criteria: item.success_criteria ?? '',
            reason: '',
        });
    };

    const change = (patch: Partial<AccessForm>) => setForm((current) => {
        if (!current) return current;
        const next = { ...current, ...patch };
        // A pilot started today runs three months unless an end date is chosen.
        if (patch.access_state === 'pilot' && !next.plan_started_on) next.plan_started_on = new Date().toISOString().slice(0, 10);
        if ((patch.access_state === 'pilot' || patch.plan_started_on) && next.access_state === 'pilot' && next.plan_started_on && !current.plan_ends_on) {
            next.plan_ends_on = plusMonths(next.plan_started_on, 3);
        }
        return next;
    });

    const save = async () => {
        if (!editing || !form) return;
        setSaving(true);
        setFormError(null);
        try {
            const response = await api.put<OrganizationPanelItem>(`/admin/panels/organizations/${editing.organization_id}/access`, {
                access_state: form.access_state,
                plan_started_on: form.plan_started_on || null,
                plan_ends_on: form.plan_ends_on || null,
                success_criteria: form.success_criteria.trim() || null,
                reason: form.reason.trim() || null,
            });
            setItems((rows) => rows.map((row) => (row.organization_id === editing.organization_id ? response.data : row)));
            setSuccess(`${editing.display_name ?? 'The organization'} is now ${response.data.access_state}.`);
            setEditing(null);
        } catch (failure) {
            const detail = (failure as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
            setFormError(typeof detail === 'string' ? detail : 'The access state could not be saved.');
        } finally {
            setSaving(false);
        }
    };

    return <div className="admin-page ds-container-data ds-stack" data-admin-organizations>
        <header className="admin-page-header">
            <div className="admin-heading-with-icon">
                <Building2 aria-hidden />
                <div>
                    <span className="ds-eyebrow">Operations</span>
                    <h1>Organizations</h1>
                    <p className="ds-muted">Access state, plan, members, pursuits and last activity per organization.</p>
                </div>
            </div>
            <Button variant="secondary" onClick={() => void load()} loading={loading} leadingIcon={<RefreshCw aria-hidden />}>Refresh</Button>
        </header>
        {error && <Alert tone="danger" title={error} />}
        {success && <Alert tone="success" title={success} />}
        {!canEdit && <Alert tone="info" title="Read-only: only administrators change an organization's access state." />}
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
                { key: 'access', heading: 'Access', cell: (item) => <StatusBadge tone={ACCESS_TONE[item.access_state] ?? 'info'}>{item.access_state}</StatusBadge> },
                { key: 'plan', heading: 'Plan', cell: (item) => <span className="ds-numeric">{planLabel(item)}</span> },
                { key: 'criteria', heading: 'Success criteria', cell: (item) => item.success_criteria
                    ? <span className="admin-org-criteria" title={item.success_criteria}><BidiText>{item.success_criteria}</BidiText></span> : '—' },
                { key: 'members', heading: 'Members', numeric: true, cell: (item) => item.members_count },
                { key: 'pursuits', heading: 'Pursuits', numeric: true, cell: (item) => item.pursuits_count },
                { key: 'activity', heading: 'Last activity', cell: (item) => formatTimestamp(item.last_activity_at) },
                { key: 'created', heading: 'Created', cell: (item) => formatTimestamp(item.created_at) },
                { key: 'edit', heading: 'Change', cell: (item) => canEdit
                    ? <Button size="sm" variant="secondary" leadingIcon={<Pencil aria-hidden />} onClick={() => startEdit(item)}
                        aria-label={`Change access for ${item.display_name ?? 'organization'}`}>Access</Button> : null },
            ]}
        />
        <Dialog
            open={Boolean(editing && form)}
            onClose={() => !saving && setEditing(null)}
            title={`Access for ${editing?.display_name ?? 'organization'}`}
            description="Audited. Members keep their sessions; the workspace follows the new state on their next page load."
            closeLabel="Close access editor"
            footer={<>
                <Button variant="secondary" onClick={() => setEditing(null)} disabled={saving}>Cancel</Button>
                <Button onClick={() => void save()} loading={saving} variant={form?.access_state === 'disabled' ? 'danger' : 'primary'}>Save</Button>
            </>}
        >
            {form && <div className="ds-stack" data-access-editor>
                <Select label="Access state" value={form.access_state} helper={ACCESS_HELP[form.access_state]}
                    onChange={(event) => change({ access_state: event.target.value as OrganizationAccessState })}>
                    {ORGANIZATION_ACCESS_STATES.map((state) => <option key={state} value={state}>{state}</option>)}
                </Select>
                <Input label="Plan start" type="date" value={form.plan_started_on}
                    onChange={(event) => change({ plan_started_on: event.target.value })} />
                <Input label="Plan end" type="date" value={form.plan_ends_on} helper="A pilot defaults to three months from its start."
                    onChange={(event) => change({ plan_ends_on: event.target.value })} />
                <Textarea label="Success criteria" rows={4} maxLength={4000} value={form.success_criteria}
                    onChange={(event) => change({ success_criteria: event.target.value })} />
                <Input label="Reason (audit log, optional)" maxLength={500} value={form.reason}
                    onChange={(event) => change({ reason: event.target.value })} />
                {formError && <Alert tone="danger" title={formError} />}
            </div>}
        </Dialog>
    </div>;
}
