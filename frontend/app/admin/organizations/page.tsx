'use client';

import { useCallback, useEffect, useState } from 'react';
import { useSession } from 'next-auth/react';
import { BarChart3, Building2, Pencil, RefreshCw } from 'lucide-react';

import { BidiText } from '@/components/i18n/BidiText';
import { Button } from '@/components/ui/Button';
import { DataTable, StatusBadge } from '@/components/ui/Display';
import { Alert } from '@/components/ui/Feedback';
import { Checkbox, Input, Select, Textarea } from '@/components/ui/Forms';
import { Dialog } from '@/components/ui/Overlay';
import { api } from '@/lib/api';
import { formatTimestamp, usageLabel, type OrganizationPanelItem } from '@/lib/adminPanels';
import { PLAN_CODES, type PlanCode, type PlanStatus } from '@/lib/plans';

const PLAN_LABEL: Record<PlanCode, string> = {
    explore: 'Explore', pilot: 'Pilot', pursuit_desk: 'Pursuit Desk', agent: 'Agent', enterprise: 'Enterprise',
    per_tender: 'Per-tender review',
};
const PLAN_HELP: Record<PlanCode, string> = {
    explore: 'Free. 1 tender check a calendar month (requirements only), 2 users, no company records, EOI or partner search.',
    pilot: '6 pursuits over the pilot term, 1 introduction, unlimited users. No competitor intelligence.',
    pursuit_desk: '24 pursuits and 2 introductions a plan year. Sector figures only.',
    agent: '60 pursuits and 12 introductions a plan year, full competitor intelligence.',
    enterprise: 'Pursuits from the agreement (set the limit; 150 until set), unlimited introductions.',
    per_tender: 'One pursuit end to end per purchase: set the pursuit limit to the number bought. No partner search.',
};
const PLAN_TONE: Record<PlanCode, 'info' | 'success' | 'warning' | 'neutral'> = {
    explore: 'info', pilot: 'warning', pursuit_desk: 'success', agent: 'success', enterprise: 'success', per_tender: 'neutral',
};
const NOTICE_TONE = { none: 'neutral', near_limit: 'warning', limit_reached: 'danger' } as const;
const ACCESS_FOR_PLAN: Record<PlanCode, 'explore' | 'pilot' | 'paid'> = {
    explore: 'explore', pilot: 'pilot', pursuit_desk: 'paid', agent: 'paid', enterprise: 'paid', per_tender: 'paid',
};

type PlanForm = {
    plan: PlanCode;
    disabled: boolean;
    plan_started_on: string;
    plan_ends_on: string;
    pursuit_limit_override: string;
    introduction_limit_override: string;
    success_criteria: string;
    reason: string;
};

type PlanDetail = {
    status: PlanStatus;
    success_criteria: string | null;
    grants: { grant_id: string; kind: string; quantity: number; period_start: string; reason: string; granted_by_email: string | null; created_at: string }[];
    audit_events: { event_id: string; action: string; actor_email: string | null; previous_state: Record<string, unknown> | null; new_state: Record<string, unknown> | null; reason: string | null; created_at: string }[];
};

function plusMonths(isoDate: string, months: number): string {
    const [year, month, day] = isoDate.split('-').map(Number);
    const end = new Date(Date.UTC(year, month - 1 + months, day));
    if (end.getUTCDate() !== day) end.setUTCDate(0); // 31 Jan + 1 month = 28/29 Feb
    return end.toISOString().slice(0, 10);
}

const wholeOrNull = (value: string) => (value.trim() === '' ? null : Math.max(0, Math.floor(Number(value))));

function changes(event: PlanDetail['audit_events'][number]): string {
    if (event.action === 'ORGANIZATION_PLAN_GRANTED') {
        const state = event.new_state ?? {};
        return `+${state.quantity} ${String(state.kind ?? '').toLowerCase()} for the period from ${state.period_start}`;
    }
    const before = event.previous_state ?? {};
    const after = event.new_state ?? {};
    return Object.keys(after)
        .filter((key) => JSON.stringify(before[key]) !== JSON.stringify(after[key]))
        .map((key) => `${key.replaceAll('_', ' ')}: ${before[key] ?? '—'} → ${after[key] ?? '—'}`)
        .join('; ') || 'no change';
}

/** R3 Task 5 organizations; P1 access state; P3: plan, period usage, overrides, grants and the plan's audit trail. */
export default function AdminOrganizationsPage() {
    const { data: session } = useSession();
    const canEdit = session?.approval_status === 'approved' && (session?.is_admin === true || session?.platform_role === 'admin');
    const [items, setItems] = useState<OrganizationPanelItem[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [success, setSuccess] = useState<string | null>(null);
    const [editing, setEditing] = useState<OrganizationPanelItem | null>(null);
    const [form, setForm] = useState<PlanForm | null>(null);
    const [saving, setSaving] = useState(false);
    const [formError, setFormError] = useState<string | null>(null);
    const [viewing, setViewing] = useState<OrganizationPanelItem | null>(null);
    const [detail, setDetail] = useState<PlanDetail | null>(null);
    const [grant, setGrant] = useState({ kind: 'PURSUITS', quantity: '1', reason: '' });
    const [granting, setGranting] = useState(false);
    const [grantError, setGrantError] = useState<string | null>(null);

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
            plan: (item.plan as PlanCode) || 'explore',
            disabled: item.access_state === 'disabled',
            plan_started_on: item.plan_started_on ?? '',
            plan_ends_on: item.plan_ends_on ?? '',
            pursuit_limit_override: item.pursuit_limit_override?.toString() ?? '',
            introduction_limit_override: item.introduction_limit_override?.toString() ?? '',
            success_criteria: item.success_criteria ?? '',
            reason: '',
        });
    };

    const change = (patch: Partial<PlanForm>) => setForm((current) => {
        if (!current) return current;
        const next = { ...current, ...patch };
        if (patch.plan && patch.plan !== 'explore' && !next.plan_started_on) next.plan_started_on = new Date().toISOString().slice(0, 10);
        // A pilot runs three months from its start unless an end date is chosen.
        if (next.plan === 'pilot' && next.plan_started_on && !current.plan_ends_on && (patch.plan || patch.plan_started_on)) {
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
                access_state: form.disabled ? 'disabled' : ACCESS_FOR_PLAN[form.plan],
                plan: form.plan,
                plan_started_on: form.plan_started_on || null,
                plan_ends_on: form.plan_ends_on || null,
                pursuit_limit_override: wholeOrNull(form.pursuit_limit_override),
                introduction_limit_override: wholeOrNull(form.introduction_limit_override),
                success_criteria: form.success_criteria.trim() || null,
                reason: form.reason.trim() || null,
            });
            setItems((rows) => rows.map((row) => (row.organization_id === editing.organization_id ? response.data : row)));
            setSuccess(`${editing.display_name ?? 'The organization'} is now on ${PLAN_LABEL[response.data.plan as PlanCode] ?? response.data.plan}${response.data.access_state === 'disabled' ? ' (disabled)' : ''}.`);
            setEditing(null);
        } catch (failure) {
            const detail = (failure as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
            setFormError(typeof detail === 'string' ? detail : 'The plan could not be saved.');
        } finally {
            setSaving(false);
        }
    };

    const openDetail = async (item: OrganizationPanelItem) => {
        setViewing(item);
        setDetail(null);
        setGrantError(null);
        setGrant({ kind: 'PURSUITS', quantity: '1', reason: '' });
        try {
            setDetail((await api.get<PlanDetail>(`/admin/panels/organizations/${item.organization_id}/plan`)).data);
        } catch {
            setGrantError('The plan details could not be loaded.');
        }
    };

    const addGrant = async () => {
        if (!viewing) return;
        setGranting(true);
        setGrantError(null);
        try {
            const response = await api.post<PlanDetail>(`/admin/panels/organizations/${viewing.organization_id}/plan-grants`, {
                kind: grant.kind, quantity: Math.max(1, Math.floor(Number(grant.quantity) || 1)), reason: grant.reason.trim(),
            });
            setDetail(response.data);
            setGrant({ kind: grant.kind, quantity: '1', reason: '' });
            await load();
        } catch (failure) {
            const message = (failure as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
            setGrantError(typeof message === 'string' ? message : 'The grant could not be saved (a reason of 3 characters or more is required).');
        } finally {
            setGranting(false);
        }
    };

    return <div className="admin-page ds-container-data ds-stack" data-admin-organizations>
        <header className="admin-page-header">
            <div className="admin-heading-with-icon">
                <Building2 aria-hidden />
                <div>
                    <span className="ds-eyebrow">Operations</span>
                    <h1>Organizations</h1>
                    <p className="ds-muted">Plan, this period&apos;s usage (pursuits counted when their first analysis starts), members and activity.</p>
                </div>
            </div>
            <Button variant="secondary" onClick={() => void load()} loading={loading} leadingIcon={<RefreshCw aria-hidden />}>Refresh</Button>
        </header>
        {error && <Alert tone="danger" title={error} />}
        {success && <Alert tone="success" title={success} />}
        {!canEdit && <Alert tone="info" title="Read-only: only administrators change an organization's plan or grant extra pursuits." />}
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
                { key: 'plan', heading: 'Plan', cell: (item) => <span className="admin-plan-cell">
                    <StatusBadge tone={PLAN_TONE[item.plan as PlanCode] ?? 'neutral'}>{PLAN_LABEL[item.plan as PlanCode] ?? item.plan}</StatusBadge>
                    {item.access_state === 'disabled' && <StatusBadge tone="danger">disabled</StatusBadge>}
                </span> },
                { key: 'period', heading: 'Period', cell: (item) => <span className="ds-numeric">{item.period_start ?? '…'} → {item.period_end ?? 'open'}</span> },
                { key: 'pursuits', heading: 'Pursuits', cell: (item) => <StatusBadge tone={NOTICE_TONE[item.pursuit_notice] ?? 'neutral'}>{usageLabel(item.pursuits_used, item.pursuit_limit)}</StatusBadge> },
                { key: 'introductions', heading: 'Introductions', cell: (item) => <span className="ds-numeric">{usageLabel(item.introductions_used, item.introduction_limit)}</span> },
                { key: 'users', heading: 'Users', cell: (item) => <span className="ds-numeric">{usageLabel(item.users_used, item.user_limit)}</span> },
                { key: 'activity', heading: 'Last activity', cell: (item) => formatTimestamp(item.last_activity_at) },
                { key: 'actions', heading: 'Change', cell: (item) => <span className="ds-row">
                    <Button size="sm" variant="secondary" leadingIcon={<BarChart3 aria-hidden />} onClick={() => void openDetail(item)}
                        aria-label={`Usage and history for ${item.display_name ?? 'organization'}`}>Usage</Button>
                    {canEdit && <Button size="sm" variant="secondary" leadingIcon={<Pencil aria-hidden />} onClick={() => startEdit(item)}
                        aria-label={`Change plan for ${item.display_name ?? 'organization'}`}>Plan</Button>}
                </span> },
            ]}
        />
        <Dialog
            open={Boolean(editing && form)}
            onClose={() => !saving && setEditing(null)}
            title={`Plan for ${editing?.display_name ?? 'organization'}`}
            description="Audited. The plan sets what members can do on their next page load; usage already counted stays counted."
            closeLabel="Close plan editor"
            footer={<>
                <Button variant="secondary" onClick={() => setEditing(null)} disabled={saving}>Cancel</Button>
                <Button onClick={() => void save()} loading={saving} variant={form?.disabled ? 'danger' : 'primary'}>Save</Button>
            </>}
        >
            {form && <div className="ds-stack" data-plan-editor>
                <Select label="Plan" value={form.plan} helper={PLAN_HELP[form.plan]}
                    onChange={(event) => change({ plan: event.target.value as PlanCode })}>
                    {PLAN_CODES.map((code) => <option key={code} value={code}>{PLAN_LABEL[code]}</option>)}
                </Select>
                <Checkbox label="Disable the organization (no member can sign in to its workspace)" checked={form.disabled}
                    onChange={(event) => change({ disabled: event.target.checked })} />
                <Input label="Plan start" type="date" value={form.plan_started_on}
                    helper="Paid plans count by plan year from this date; a pilot counts every pursuit since it."
                    onChange={(event) => change({ plan_started_on: event.target.value })} />
                <Input label="Plan end" type="date" value={form.plan_ends_on} helper="A pilot defaults to three months from its start."
                    onChange={(event) => change({ plan_ends_on: event.target.value })} />
                <Input label="Pursuit limit (blank = the plan's)" type="number" min={0} value={form.pursuit_limit_override}
                    helper="Enterprise agreements and per-tender purchases. Extra pursuits for one period: use Usage → Grant."
                    onChange={(event) => change({ pursuit_limit_override: event.target.value })} />
                <Input label="Introduction limit (blank = the plan's)" type="number" min={0} value={form.introduction_limit_override}
                    onChange={(event) => change({ introduction_limit_override: event.target.value })} />
                <Textarea label="Success criteria" rows={3} maxLength={4000} value={form.success_criteria}
                    onChange={(event) => change({ success_criteria: event.target.value })} />
                <Input label="Reason (audit log, optional)" maxLength={500} value={form.reason}
                    onChange={(event) => change({ reason: event.target.value })} />
                {formError && <Alert tone="danger" title={formError} />}
            </div>}
        </Dialog>
        <Dialog
            open={Boolean(viewing)}
            onClose={() => !granting && setViewing(null)}
            title={`Usage: ${viewing?.display_name ?? 'organization'}`}
            description="This period's usage, extra allowances and every plan change (newest first)."
            closeLabel="Close usage"
            footer={<Button variant="secondary" onClick={() => setViewing(null)} disabled={granting}>Close</Button>}
        >
            {detail ? <div className="ds-stack admin-plan-detail" data-plan-detail>
                <dl className="admin-plan-summary">
                    <div><dt>Plan</dt><dd>{PLAN_LABEL[detail.status.plan] ?? detail.status.plan} · {detail.status.access_state}</dd></div>
                    <div><dt>Period</dt><dd>{detail.status.period_start} → {detail.status.period_end ?? 'open'}</dd></div>
                    <div><dt>Pursuits</dt><dd>{usageLabel(detail.status.pursuits.used, detail.status.pursuits.limit)}{detail.status.pursuits.extra_granted ? ` (incl. +${detail.status.pursuits.extra_granted} granted)` : ''}</dd></div>
                    <div><dt>Introductions</dt><dd>{usageLabel(detail.status.introductions.used, detail.status.introductions.limit)}{detail.status.introductions.extra_granted ? ` (incl. +${detail.status.introductions.extra_granted} granted)` : ''}</dd></div>
                    <div><dt>Users</dt><dd>{usageLabel(detail.status.users.used, detail.status.users.limit)}</dd></div>
                </dl>
                {canEdit && <section className="admin-plan-grant" aria-label="Grant extra">
                    <h3>Grant extra for this period</h3>
                    <div className="admin-plan-grant-row">
                        <Select label="What" value={grant.kind} onChange={(event) => setGrant({ ...grant, kind: event.target.value })}>
                            <option value="PURSUITS">Pursuits</option>
                            <option value="INTRODUCTIONS">Introductions</option>
                        </Select>
                        <Input label="How many" type="number" min={1} max={1000} value={grant.quantity}
                            onChange={(event) => setGrant({ ...grant, quantity: event.target.value })} />
                        <Input label="Reason (audit log)" maxLength={1000} value={grant.reason}
                            onChange={(event) => setGrant({ ...grant, reason: event.target.value })} />
                    </div>
                    <Button size="sm" loading={granting} disabled={grant.reason.trim().length < 3} onClick={() => void addGrant()}>Grant</Button>
                </section>}
                {grantError && <Alert tone="danger" title={grantError} />}
                <section aria-label="Grants">
                    <h3>Grants</h3>
                    {detail.grants.length ? <ul className="admin-plan-list">{detail.grants.map((item) => <li key={item.grant_id}>
                        +{item.quantity} {item.kind.toLowerCase()} · period from {item.period_start} · {item.reason} · {item.granted_by_email ?? '—'} · {formatTimestamp(item.created_at)}
                    </li>)}</ul> : <p className="ds-muted">None.</p>}
                </section>
                <section aria-label="Audit events">
                    <h3>Audit events</h3>
                    {detail.audit_events.length ? <ul className="admin-plan-list">{detail.audit_events.map((event) => <li key={event.event_id}>
                        <strong>{formatTimestamp(event.created_at)}</strong> · {event.action === 'ORGANIZATION_PLAN_GRANTED' ? 'Grant' : 'Plan change'} · {event.actor_email ?? 'server'} · {changes(event)}{event.reason ? ` · “${event.reason}”` : ''}
                    </li>)}</ul> : <p className="ds-muted">None.</p>}
                </section>
            </div> : grantError ? <Alert tone="danger" title={grantError} /> : <p className="ds-muted">Loading…</p>}
        </Dialog>
    </div>;
}
