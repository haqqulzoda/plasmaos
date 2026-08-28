'use client';

import { FormEvent, useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Check, ChevronLeft, ChevronRight, Loader2, RefreshCw, RotateCcw, Search, ShieldAlert, X } from 'lucide-react';
import { useSession } from 'next-auth/react';
import { api } from '@/lib/api';
import {
    ACCOUNT_ROLES,
    ACCOUNT_STATUSES,
    AccountStatus,
    AdminAccount,
    AdminAccountsPage,
    LifecycleAction,
    actionConsequence,
    actionLabel,
    adminActionError,
    roleLabel,
    statusLabel,
} from '@/lib/adminOperations';

const PAGE_SIZE = 25;

type CompanyAction = 'approve' | 'reject' | 'disable';
type PendingAction = {
    rowKey: string;
    resource: 'account' | 'company';
    resourceId: string;
    action: LifecycleAction | CompanyAction;
    targetLabel: string;
    restoreTargetStatus?: AccountStatus | null;
};

const statusClass = (status?: string | null) => {
    if (status === 'approved') return 'text-emerald-300 bg-emerald-500/10 border-emerald-500/30';
    if (status === 'pending') return 'text-amber-300 bg-amber-500/10 border-amber-500/30';
    if (status === 'rejected') return 'text-red-300 bg-red-500/10 border-red-500/30';
    if (status === 'disabled') return 'text-gray-200 bg-gray-700/50 border-gray-600';
    return 'text-gray-300 bg-gray-800 border-gray-700';
};

const actionClass = (action: string) => {
    if (action === 'approve') return 'border-emerald-500/30 text-emerald-200 hover:bg-emerald-500/10';
    if (action === 'restore') return 'border-cyan-500/30 text-cyan-200 hover:bg-cyan-500/10';
    if (action === 'reject') return 'border-red-500/30 text-red-200 hover:bg-red-500/10';
    return 'border-gray-600 text-gray-200 hover:bg-gray-800';
};

const companyConsequence = (action: CompanyAction): string => {
    if (action === 'approve') return 'The company profile will become Approved.';
    if (action === 'reject') return 'The company profile will become Rejected and company access checks will use that state.';
    return 'The company profile will become Disabled. This does not delete its records.';
};

export default function AdminAccountsPageView() {
    const router = useRouter();
    const { data: session } = useSession();
    const [page, setPage] = useState<AdminAccountsPage>({ items: [], total: 0, limit: PAGE_SIZE, offset: 0 });
    const [loading, setLoading] = useState(true);
    const [actingId, setActingId] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [success, setSuccess] = useState<string | null>(null);
    const [statusFilter, setStatusFilter] = useState('');
    const [roleFilter, setRoleFilter] = useState('');
    const [searchDraft, setSearchDraft] = useState('');
    const [searchQuery, setSearchQuery] = useState('');
    const [offset, setOffset] = useState(0);
    const [pendingAction, setPendingAction] = useState<PendingAction | null>(null);
    const [reason, setReason] = useState('');
    const confirmButtonRef = useRef<HTMLButtonElement>(null);

    const canManageAccounts =
        session?.approval_status === 'approved' &&
        (session?.is_admin === true || session?.platform_role === 'admin');

    const loadAccounts = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const response = await api.get<AdminAccountsPage>('/admin/accounts', {
                params: {
                    limit: PAGE_SIZE,
                    offset,
                    approval_status: statusFilter || undefined,
                    role: roleFilter || undefined,
                    query: searchQuery || undefined,
                },
            });
            setPage(response.data);
        } catch (caught) {
            const result = adminActionError(caught);
            setError(result.authorityLost ? result.message : 'Accounts could not be loaded. Try again.');
            if (result.authorityLost) router.replace('/dashboard');
        } finally {
            setLoading(false);
        }
    }, [offset, roleFilter, router, searchQuery, statusFilter]);

    useEffect(() => {
        loadAccounts();
    }, [loadAccounts]);

    useEffect(() => {
        if (!pendingAction) return;
        confirmButtonRef.current?.focus();
        const handleEscape = (event: KeyboardEvent) => {
            if (event.key === 'Escape' && !actingId) setPendingAction(null);
        };
        window.addEventListener('keydown', handleEscape);
        return () => window.removeEventListener('keydown', handleEscape);
    }, [actingId, pendingAction]);

    const beginAction = (action: PendingAction) => {
        setReason('');
        setError(null);
        setSuccess(null);
        setPendingAction(action);
    };

    const submitAction = async () => {
        if (!pendingAction || !canManageAccounts) return;
        setActingId(pendingAction.rowKey);
        setError(null);
        setSuccess(null);
        const url = pendingAction.resource === 'account'
            ? `/admin/users/${pendingAction.resourceId}/${pendingAction.action}`
            : `/admin/companies/${pendingAction.resourceId}/${pendingAction.action}`;
        try {
            const response = await api.post(url, { reason: reason.trim() || null });
            const resultStatus = response.data?.approval_status;
            const label = typeof resultStatus === 'string' ? statusLabel(resultStatus) : 'updated';
            setSuccess(`${pendingAction.targetLabel} is now ${label}. The backend confirmed the transition.`);
            setPendingAction(null);
            await loadAccounts();
        } catch (caught) {
            const result = adminActionError(caught);
            setPendingAction(null);
            if (result.refresh) {
                await loadAccounts();
            }
            setError(result.message);
            if (result.authorityLost) router.replace('/dashboard');
        } finally {
            setActingId(null);
        }
    };

    const applySearch = (event: FormEvent) => {
        event.preventDefault();
        setOffset(0);
        setSearchQuery(searchDraft.trim());
    };

    const pageNumber = Math.floor(page.offset / page.limit) + 1;
    const pageCount = Math.max(1, Math.ceil(page.total / page.limit));

    return (
        <div className="space-y-6">
            <header className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                <div>
                    <h1 className="text-2xl font-semibold text-white">Accounts &amp; approvals</h1>
                    <p className="text-sm text-gray-400">Canonical lifecycle state and explicit administrative transitions.</p>
                </div>
                <button
                    type="button"
                    onClick={loadAccounts}
                    disabled={loading}
                    className="inline-flex items-center justify-center gap-2 rounded-lg border border-gray-700 px-4 py-2 text-sm font-medium text-gray-300 hover:bg-gray-900 hover:text-white disabled:cursor-wait disabled:opacity-50"
                >
                    <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
                    Refresh
                </button>
            </header>

            <div className="rounded-lg border border-cyan-500/20 bg-cyan-500/10 px-4 py-3 text-sm text-cyan-100">
                Account status is authoritative. Every completed transition invalidates existing credentials and requires fresh authentication.
            </div>

            {!canManageAccounts && (
                <div className="flex items-center gap-2 rounded-lg border border-amber-500/20 bg-amber-500/10 px-4 py-3 text-sm text-amber-100">
                    <ShieldAlert className="h-4 w-4" aria-hidden="true" />
                    This is a read-only account view. Current effective-admin authority is required for actions.
                </div>
            )}

            <form onSubmit={applySearch} className="grid gap-3 rounded-lg border border-gray-800 bg-gray-950 p-4 md:grid-cols-[1fr_180px_180px_auto]">
                <label className="space-y-1 text-xs text-gray-400">
                    <span>Account</span>
                    <div className="flex rounded-lg border border-gray-700 bg-gray-900 focus-within:border-cyan-500">
                        <Search className="m-2.5 h-4 w-4 text-gray-500" aria-hidden="true" />
                        <input
                            value={searchDraft}
                            onChange={(event) => setSearchDraft(event.target.value)}
                            placeholder="Name or email"
                            className="min-w-0 flex-1 bg-transparent px-1 py-2 text-sm text-white outline-none"
                        />
                    </div>
                </label>
                <label className="space-y-1 text-xs text-gray-400">
                    <span>Status</span>
                    <select
                        value={statusFilter}
                        onChange={(event) => { setOffset(0); setStatusFilter(event.target.value); }}
                        className="w-full rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-white"
                    >
                        <option value="">All statuses</option>
                        {ACCOUNT_STATUSES.map((status) => <option key={status} value={status}>{statusLabel(status)}</option>)}
                    </select>
                </label>
                <label className="space-y-1 text-xs text-gray-400">
                    <span>Role</span>
                    <select
                        value={roleFilter}
                        onChange={(event) => { setOffset(0); setRoleFilter(event.target.value); }}
                        className="w-full rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-white"
                    >
                        <option value="">All roles</option>
                        {ACCOUNT_ROLES.map((role) => <option key={role} value={role}>{roleLabel(role)}</option>)}
                    </select>
                </label>
                <button type="submit" className="self-end rounded-lg bg-cyan-600 px-4 py-2 text-sm font-semibold text-white hover:bg-cyan-500">
                    Apply
                </button>
            </form>

            {error && <div role="alert" className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">{error}</div>}
            {success && <div role="status" className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-200">{success}</div>}

            <section aria-busy={loading} className="overflow-hidden rounded-lg border border-gray-800 bg-gray-950">
                {loading ? (
                    <div className="flex h-56 items-center justify-center" aria-label="Loading accounts"><Loader2 className="h-6 w-6 animate-spin text-cyan-300" /></div>
                ) : page.items.length === 0 ? (
                    <div className="p-8 text-sm text-gray-400">No accounts match these filters.</div>
                ) : (
                    <div className="overflow-x-auto">
                        <table className="min-w-[920px] w-full text-sm">
                            <thead className="bg-gray-900 text-gray-400">
                                <tr>
                                    <th className="px-4 py-3 text-left font-medium">User</th>
                                    <th className="px-4 py-3 text-left font-medium">Status</th>
                                    <th className="px-4 py-3 text-left font-medium">Role</th>
                                    <th className="px-4 py-3 text-left font-medium">Company</th>
                                    <th className="px-4 py-3 text-left font-medium">Actions</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-gray-800">
                                {page.items.map((account) => (
                                    <AccountRow
                                        key={account.id}
                                        account={account}
                                        busy={actingId === account.id}
                                        canManage={canManageAccounts}
                                        onAction={beginAction}
                                    />
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}
            </section>

            <div className="flex flex-col gap-3 text-sm text-gray-400 sm:flex-row sm:items-center sm:justify-between">
                <span>{page.total} accounts · Page {pageNumber} of {pageCount}</span>
                <div className="flex gap-2">
                    <button
                        type="button"
                        disabled={loading || offset === 0}
                        onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                        className="inline-flex items-center gap-1 rounded-lg border border-gray-700 px-3 py-2 disabled:opacity-40"
                    ><ChevronLeft className="h-4 w-4" />Previous</button>
                    <button
                        type="button"
                        disabled={loading || offset + page.limit >= page.total}
                        onClick={() => setOffset(offset + PAGE_SIZE)}
                        className="inline-flex items-center gap-1 rounded-lg border border-gray-700 px-3 py-2 disabled:opacity-40"
                    >Next<ChevronRight className="h-4 w-4" /></button>
                </div>
            </div>

            {pendingAction && (
                <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" role="presentation">
                    <div role="dialog" aria-modal="true" aria-labelledby="action-dialog-title" className="w-full max-w-lg rounded-xl border border-gray-700 bg-gray-950 p-6 shadow-2xl">
                        <h2 id="action-dialog-title" className="text-lg font-semibold text-white">
                            {actionLabel(pendingAction.action as LifecycleAction)} {pendingAction.targetLabel}?
                        </h2>
                        <p className="mt-3 text-sm leading-6 text-gray-300">
                            {pendingAction.resource === 'account'
                                ? actionConsequence(pendingAction.action as LifecycleAction, pendingAction.restoreTargetStatus)
                                : companyConsequence(pendingAction.action as CompanyAction)}
                        </p>
                        {(pendingAction.action === 'reject' || pendingAction.action === 'disable') && (
                            <label className="mt-4 block space-y-2 text-sm text-gray-300">
                                <span>Reason (optional)</span>
                                <textarea
                                    value={reason}
                                    onChange={(event) => setReason(event.target.value)}
                                    rows={3}
                                    maxLength={500}
                                    className="w-full rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-white outline-none focus:border-cyan-500"
                                />
                            </label>
                        )}
                        <div className="mt-6 flex justify-end gap-3">
                            <button type="button" onClick={() => setPendingAction(null)} disabled={Boolean(actingId)} className="rounded-lg border border-gray-700 px-4 py-2 text-sm text-gray-300 hover:bg-gray-900 disabled:opacity-50">Cancel</button>
                            <button ref={confirmButtonRef} type="button" onClick={submitAction} disabled={Boolean(actingId)} className={`rounded-lg border px-4 py-2 text-sm font-semibold disabled:cursor-wait disabled:opacity-50 ${actionClass(pendingAction.action)}`}>
                                {actingId ? 'Applying…' : `Confirm ${actionLabel(pendingAction.action as LifecycleAction)}`}
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}

function AccountRow({
    account,
    busy,
    canManage,
    onAction,
}: {
    account: AdminAccount;
    busy: boolean;
    canManage: boolean;
    onAction: (action: PendingAction) => void;
}) {
    const company = account.company;
    const accountAction = (action: LifecycleAction) => onAction({
        rowKey: account.id,
        resource: 'account',
        resourceId: account.id,
        action,
        targetLabel: account.email,
        restoreTargetStatus: account.restore_target_status,
    });
    const companyAction = (action: CompanyAction) => {
        if (!company) return;
        onAction({
            rowKey: account.id,
            resource: 'company',
            resourceId: company.id,
            action,
            targetLabel: company.company_name || account.email,
        });
    };
    const companyActions: CompanyAction[] = company
        ? (['approve', 'reject', 'disable'] as CompanyAction[]).filter((action) => company.approval_status !== ({ approve: 'approved', reject: 'rejected', disable: 'disabled' }[action]))
        : [];

    return (
        <tr className="align-top">
            <td className="px-4 py-4">
                <div className="font-medium text-white">{account.name} {account.is_current_actor && <span className="text-xs text-cyan-300">(You)</span>}</div>
                <div className="text-gray-500">{account.email}</div>
                <Link href={`/admin/audit?target_user_id=${encodeURIComponent(account.id)}`} className="mt-1 inline-flex text-xs text-cyan-300 hover:text-cyan-200">View audit history</Link>
            </td>
            <td className="px-4 py-4"><span className={`inline-flex rounded border px-2 py-1 text-xs font-medium ${statusClass(account.approval_status)}`}>{statusLabel(account.approval_status)}</span></td>
            <td className="px-4 py-4 text-gray-200">{roleLabel(account.role)}</td>
            <td className="px-4 py-4 text-gray-300">
                {company ? <><Link href={`/admin/companies/${company.id}`} className="text-cyan-200 hover:text-cyan-100">{company.company_name || 'Company detail'}</Link><div className="mt-1 text-xs text-gray-500">{statusLabel(company.approval_status)}</div></> : '—'}
            </td>
            <td className="px-4 py-4">
                <div className="flex flex-wrap gap-2">
                    {account.allowed_actions.map((action) => (
                        <button key={action} type="button" disabled={!canManage || busy} onClick={() => accountAction(action)} className={`inline-flex items-center gap-1 rounded border px-2.5 py-1.5 text-xs font-medium disabled:opacity-40 ${actionClass(action)}`}>
                            {action === 'approve' && <Check className="h-3 w-3" />}
                            {action === 'reject' && <X className="h-3 w-3" />}
                            {action === 'restore' && <RotateCcw className="h-3 w-3" />}
                            {actionLabel(action)}
                        </button>
                    ))}
                    {account.is_current_actor && <span className="self-center text-xs text-gray-500">Administrators cannot reject themselves. Administrators cannot disable themselves.</span>}
                </div>
                {company && companyActions.length > 0 && (
                    <details className="mt-3 text-xs text-gray-400">
                        <summary className="cursor-pointer select-none hover:text-gray-200">Company actions</summary>
                        <div className="mt-2 flex flex-wrap gap-2">
                            {companyActions.map((action) => <button key={action} type="button" disabled={!canManage || busy} onClick={() => companyAction(action)} className={`rounded border px-2 py-1 disabled:opacity-40 ${actionClass(action)}`}>{actionLabel(action)}</button>)}
                        </div>
                    </details>
                )}
            </td>
        </tr>
    );
}
