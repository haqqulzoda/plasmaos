'use client';

import { FormEvent, Suspense, useCallback, useEffect, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { AlertCircle, CheckCircle2, ChevronLeft, ChevronRight, Clock3, Loader2, RefreshCw, Search, Server, ShieldX } from 'lucide-react';
import { api } from '@/lib/api';
import { adminActionError, auditReasonLabel, safeStateSummary } from '@/lib/adminOperations';

const PAGE_SIZE = 25;
const ACTIONS = [
    'USER_APPROVED', 'USER_REJECTED', 'USER_DISABLED', 'USER_RESTORED',
    'COMPANY_APPROVED', 'COMPANY_REJECTED', 'COMPANY_DISABLED',
    'ADMIN_GRANTED', 'OPERATOR_GRANTED', 'ALLOWLIST_PRIVILEGE_RECONCILED',
    'ADMIN_REPAIR_PROMOTION',
];

type AuditEvent = {
    id: string;
    occurred_at: string;
    action: string;
    outcome?: 'SUCCESS' | 'DENIED' | 'FAILED' | null;
    actor_user_id?: string | null;
    actor_type?: 'USER' | 'SYSTEM' | 'SERVER_COMMAND' | null;
    actor_email_snapshot?: string | null;
    actor_role_snapshot?: string | null;
    actor_label?: string | null;
    target_user_id?: string | null;
    target_email_snapshot: string;
    target_resource_type?: string | null;
    target_resource_id?: string | null;
    previous_state?: Record<string, unknown> | null;
    new_state?: Record<string, unknown> | null;
    reason_code?: string | null;
    reason?: string | null;
    request_id?: string | null;
    source?: string | null;
};

type AuditPage = { items: AuditEvent[]; total: number; limit: number; offset: number };

const actionLabel = (action: string) => action
    .toLowerCase()
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');

const actorLabel = (event: AuditEvent) => {
    if (event.actor_type === 'SERVER_COMMAND') return 'Server command';
    if (event.actor_type === 'SYSTEM') return 'System';
    return event.actor_email_snapshot || event.actor_label || 'Unavailable';
};

const formatTime = (value: string) => {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? 'Unavailable' : date.toLocaleString();
};

const outcomeStyle = (outcome?: string | null) => {
    if (outcome === 'SUCCESS') return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-200';
    if (outcome === 'DENIED') return 'border-amber-500/30 bg-amber-500/10 text-amber-200';
    if (outcome === 'FAILED') return 'border-red-500/30 bg-red-500/10 text-red-200';
    return 'border-gray-600 bg-gray-800 text-gray-300';
};

export default function AdminAuditPage() {
    return <Suspense fallback={<AuditLoading />}><AdminAuditContent /></Suspense>;
}

function AuditLoading() {
    return <div className="flex h-64 items-center justify-center"><Loader2 className="h-7 w-7 animate-spin text-cyan-300" /></div>;
}

function AdminAuditContent() {
    const router = useRouter();
    const searchParams = useSearchParams();
    const [page, setPage] = useState<AuditPage>({ items: [], total: 0, limit: PAGE_SIZE, offset: 0 });
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [offset, setOffset] = useState(0);
    const [action, setAction] = useState('');
    const [outcome, setOutcome] = useState('');
    const [actorDraft, setActorDraft] = useState(searchParams.get('actor_user_id') ?? '');
    const [targetDraft, setTargetDraft] = useState(searchParams.get('target_user_id') ?? '');
    const [actorId, setActorId] = useState(actorDraft);
    const [targetId, setTargetId] = useState(targetDraft);

    const loadEvents = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const response = await api.get<AuditPage>('/admin/audit-events', {
                params: {
                    limit: PAGE_SIZE,
                    offset,
                    action: action || undefined,
                    outcome: outcome || undefined,
                    actor_user_id: actorId || undefined,
                    target_user_id: targetId || undefined,
                },
            });
            setPage(response.data);
        } catch (caught) {
            const result = adminActionError(caught);
            setError(result.authorityLost
                ? 'Current effective-admin authorization is required to view audit history.'
                : 'Administrative activity could not be loaded. Try again.');
            if (result.authorityLost) router.replace('/dashboard');
        } finally {
            setLoading(false);
        }
    }, [action, actorId, offset, outcome, router, targetId]);

    useEffect(() => { loadEvents(); }, [loadEvents]);

    const applyIdentityFilters = (event: FormEvent) => {
        event.preventDefault();
        setOffset(0);
        setActorId(actorDraft.trim());
        setTargetId(targetDraft.trim());
    };

    const pageNumber = Math.floor(page.offset / page.limit) + 1;
    const pageCount = Math.max(1, Math.ceil(page.total / page.limit));

    return (
        <div className="space-y-6">
            <header className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
                <div>
                    <h1 className="text-2xl font-semibold text-white">Administrative activity</h1>
                    <p className="text-sm text-gray-400">Immutable security transitions and privileged attempts.</p>
                </div>
                <button type="button" onClick={loadEvents} disabled={loading} className="inline-flex items-center justify-center gap-2 rounded-lg border border-gray-700 px-4 py-2 text-sm text-gray-300 hover:bg-gray-900 disabled:opacity-50">
                    <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />Refresh
                </button>
            </header>

            <div className="rounded-lg border border-gray-800 bg-gray-950 p-4 text-sm text-gray-300">
                Success means a transition committed. Denied and Failed events do not mean the target state changed.
            </div>

            <form onSubmit={applyIdentityFilters} className="grid gap-3 rounded-lg border border-gray-800 bg-gray-950 p-4 md:grid-cols-2 xl:grid-cols-[220px_180px_1fr_1fr_auto]">
                <label className="space-y-1 text-xs text-gray-400"><span>Action</span><select value={action} onChange={(event) => { setOffset(0); setAction(event.target.value); }} className="w-full rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-white"><option value="">All actions</option>{ACTIONS.map((value) => <option key={value} value={value}>{actionLabel(value)}</option>)}</select></label>
                <label className="space-y-1 text-xs text-gray-400"><span>Outcome</span><select value={outcome} onChange={(event) => { setOffset(0); setOutcome(event.target.value); }} className="w-full rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-white"><option value="">All outcomes</option><option value="SUCCESS">Success</option><option value="DENIED">Denied</option><option value="FAILED">Failed</option></select></label>
                <label className="space-y-1 text-xs text-gray-400"><span>Actor user ID</span><input aria-label="Actor user ID" value={actorDraft} onChange={(event) => setActorDraft(event.target.value)} placeholder="Optional exact UUID" className="w-full rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-white outline-none focus:border-cyan-500" /></label>
                <label className="space-y-1 text-xs text-gray-400"><span>Target user ID</span><input aria-label="Target user ID" value={targetDraft} onChange={(event) => setTargetDraft(event.target.value)} placeholder="Optional exact UUID" className="w-full rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-white outline-none focus:border-cyan-500" /></label>
                <button type="submit" className="inline-flex self-end items-center justify-center gap-2 rounded-lg bg-cyan-600 px-4 py-2 text-sm font-semibold text-white hover:bg-cyan-500"><Search className="h-4 w-4" />Apply</button>
            </form>

            {error && <div role="alert" className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">{error}</div>}

            <section aria-busy={loading} className="overflow-hidden rounded-lg border border-gray-800 bg-gray-950">
                {loading ? <AuditLoading /> : page.items.length === 0 ? <div className="p-8 text-sm text-gray-400">No audit events match these filters.</div> : (
                    <div className="overflow-x-auto">
                        <table className="min-w-[980px] w-full text-sm">
                            <thead className="bg-gray-900 text-gray-400"><tr><th className="px-4 py-3 text-left font-medium">Time</th><th className="px-4 py-3 text-left font-medium">Actor</th><th className="px-4 py-3 text-left font-medium">Action</th><th className="px-4 py-3 text-left font-medium">Target</th><th className="px-4 py-3 text-left font-medium">Outcome</th><th className="px-4 py-3 text-left font-medium">Reason / detail</th></tr></thead>
                            <tbody className="divide-y divide-gray-800">{page.items.map((event) => <AuditRow key={event.id} event={event} />)}</tbody>
                        </table>
                    </div>
                )}
            </section>

            <div className="flex flex-col gap-3 text-sm text-gray-400 sm:flex-row sm:items-center sm:justify-between">
                <span>{page.total} events · Page {pageNumber} of {pageCount}</span>
                <div className="flex gap-2">
                    <button type="button" disabled={loading || offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))} className="inline-flex items-center gap-1 rounded-lg border border-gray-700 px-3 py-2 disabled:opacity-40"><ChevronLeft className="h-4 w-4" />Previous</button>
                    <button type="button" disabled={loading || offset + page.limit >= page.total} onClick={() => setOffset(offset + PAGE_SIZE)} className="inline-flex items-center gap-1 rounded-lg border border-gray-700 px-3 py-2 disabled:opacity-40">Next<ChevronRight className="h-4 w-4" /></button>
                </div>
            </div>
        </div>
    );
}

function AuditRow({ event }: { event: AuditEvent }) {
    const legacy = !event.outcome;
    const reason = auditReasonLabel(event.reason_code) || event.reason || (legacy ? 'Legacy event' : '—');
    const previous = safeStateSummary(event.previous_state);
    const next = safeStateSummary(event.new_state);
    return (
        <tr className="align-top text-gray-300">
            <td className="whitespace-nowrap px-4 py-4"><span className="inline-flex items-center gap-2"><Clock3 className="h-4 w-4 text-gray-500" />{formatTime(event.occurred_at)}</span></td>
            <td className="px-4 py-4"><span className="inline-flex items-center gap-2">{event.actor_type !== 'USER' && <Server className="h-4 w-4 text-cyan-300" />}{actorLabel(event)}</span>{event.actor_role_snapshot && <div className="mt-1 text-xs text-gray-500">Role: {event.actor_role_snapshot}</div>}</td>
            <td className="px-4 py-4 font-medium text-white">{actionLabel(event.action)}</td>
            <td className="px-4 py-4">{event.target_email_snapshot || 'Unavailable'}<div className="mt-1 text-xs text-gray-500">{event.target_resource_type ? actionLabel(event.target_resource_type) : 'Legacy resource'}</div></td>
            <td className="px-4 py-4"><span className={`inline-flex items-center gap-1 rounded border px-2 py-1 text-xs font-medium ${outcomeStyle(event.outcome)}`}>{event.outcome === 'SUCCESS' && <CheckCircle2 className="h-3 w-3" />}{event.outcome === 'DENIED' && <ShieldX className="h-3 w-3" />}{event.outcome === 'FAILED' && <AlertCircle className="h-3 w-3" />}{event.outcome ? actionLabel(event.outcome) : 'Legacy event'}</span></td>
            <td className="max-w-sm px-4 py-4"><div>{reason}</div><details className="mt-2 text-xs text-gray-400"><summary className="cursor-pointer hover:text-gray-200">Safe event detail</summary><div className="mt-2 space-y-2 rounded border border-gray-800 bg-gray-900 p-3"><div><span className="text-gray-500">Previous:</span> {previous.length ? previous.join(' · ') : 'Unavailable'}</div><div><span className="text-gray-500">New:</span> {next.length ? next.join(' · ') : 'Unavailable'}</div><div><span className="text-gray-500">Source:</span> {event.source ? actionLabel(event.source) : 'Unavailable'}</div>{event.outcome !== 'SUCCESS' && <div className="font-medium text-amber-200">No target state change is claimed.</div>}</div></details></td>
        </tr>
    );
}
