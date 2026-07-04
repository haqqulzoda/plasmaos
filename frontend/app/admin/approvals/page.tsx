'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { Check, Loader2, RefreshCw, ShieldAlert, X } from 'lucide-react';
import { useSession } from 'next-auth/react';
import { api } from '@/lib/api';
import { labelForService, useServiceMeta } from '@/lib/services';

type QueueUser = {
    id: string;
    name: string;
    email: string;
    approval_status: string;
    platform_role: string;
    is_admin: boolean;
    rejection_reason?: string | null;
    created_at?: string | null;
};

type QueueCompany = {
    id: string;
    company_name?: string | null;
    industry?: string | null;
    target_regions?: string[] | null;
    target_countries?: string[] | null;
    target_services?: string[] | null;
    approval_status: string;
    pilot_status: string;
    rejection_reason?: string | null;
};

type QueueItem = {
    user: QueueUser;
    company?: QueueCompany | null;
};

type QueueResponse = {
    items: QueueItem[];
};

const statusClass = (status?: string | null) => {
    if (status === 'approved') return 'text-emerald-300 bg-emerald-500/10 border-emerald-500/20';
    if (status === 'pending') return 'text-amber-300 bg-amber-500/10 border-amber-500/20';
    if (status === 'rejected') return 'text-red-300 bg-red-500/10 border-red-500/20';
    if (status === 'disabled') return 'text-gray-300 bg-gray-700/40 border-gray-600';
    return 'text-gray-300 bg-gray-800 border-gray-700';
};

const joinValues = (values?: string[] | null) =>
    values && values.length > 0 ? values.join(', ') : '—';

export default function AdminApprovalsPage() {
    const { data: session } = useSession();
    const services = useServiceMeta();
    const [items, setItems] = useState<QueueItem[]>([]);
    const [loading, setLoading] = useState(true);
    const [actingId, setActingId] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);

    const canMutate = useMemo(
        () => session?.is_admin === true || session?.platform_role === 'admin',
        [session?.is_admin, session?.platform_role],
    );

    const loadQueue = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const response = await api.get<QueueResponse>('/admin/approval-queue');
            setItems(response.data.items ?? []);
        } catch (err) {
            console.error('Failed to load approval queue:', err);
            setError('Failed to load approval queue.');
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        loadQueue();
    }, [loadQueue]);

    const postAction = async (key: string, url: string, needsReason = false) => {
        if (!canMutate) {
            setError('Only admins can change approval status.');
            return;
        }

        const reason = needsReason ? window.prompt('Optional reason') : null;
        setActingId(key);
        setError(null);
        try {
            await api.post(url, { reason });
            await loadQueue();
        } catch (err) {
            console.error('Approval action failed:', err);
            setError('Approval action failed.');
        } finally {
            setActingId(null);
        }
    };

    const joinServices = (values?: string[] | null) =>
        values && values.length > 0
            ? values.map((value) => labelForService(value, services)).join(', ')
            : '—';

    return (
        <div className="space-y-6">
            <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
                <div>
                    <h1 className="text-2xl font-semibold text-white">Approval queue</h1>
                    <p className="text-sm text-gray-400">Review onboarded pilot users and company profiles.</p>
                </div>
                <button
                    type="button"
                    onClick={loadQueue}
                    className="inline-flex items-center justify-center gap-2 rounded-lg border border-gray-700 px-4 py-2 text-sm font-medium text-gray-300 hover:bg-gray-900 hover:text-white transition-colors"
                >
                    <RefreshCw className="w-4 h-4" />
                    Refresh
                </button>
            </div>

            <div className="border border-cyan-500/20 bg-cyan-500/10 rounded-lg px-4 py-3 text-sm text-cyan-100">
                Pilot may need to refresh or sign in again for access status to update.
            </div>

            {!canMutate && (
                <div className="border border-amber-500/20 bg-amber-500/10 rounded-lg px-4 py-3 text-sm text-amber-100 flex items-center gap-2">
                    <ShieldAlert className="w-4 h-4" />
                    Operators can view this queue. Approval actions require admin access.
                </div>
            )}

            {error && (
                <div className="border border-red-500/30 bg-red-500/10 text-red-300 rounded-lg px-4 py-3 text-sm">
                    {error}
                </div>
            )}

            <div className="border border-gray-800 rounded-lg overflow-hidden bg-gray-950">
                {loading ? (
                    <div className="h-56 flex items-center justify-center">
                        <Loader2 className="w-6 h-6 animate-spin text-cyan-300" />
                    </div>
                ) : items.length === 0 ? (
                    <div className="p-8 text-sm text-gray-400">No pending approvals.</div>
                ) : (
                    <div className="overflow-x-auto">
                        <table className="min-w-[1180px] w-full text-sm">
                            <thead className="bg-gray-900 text-gray-400">
                                <tr>
                                    <th className="px-4 py-3 text-left font-medium">User</th>
                                    <th className="px-4 py-3 text-left font-medium">Company</th>
                                    <th className="px-4 py-3 text-left font-medium">Industry</th>
                                    <th className="px-4 py-3 text-left font-medium">Targets</th>
                                    <th className="px-4 py-3 text-left font-medium">Services</th>
                                    <th className="px-4 py-3 text-left font-medium">User status</th>
                                    <th className="px-4 py-3 text-left font-medium">Company status</th>
                                    <th className="px-4 py-3 text-left font-medium">Pilot status</th>
                                    <th className="px-4 py-3 text-left font-medium">Actions</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-gray-800">
                                {items.map((item) => {
                                    const company = item.company;
                                    const rowKey = `${item.user.id}-${company?.id ?? 'no-company'}`;
                                    const busy = actingId === rowKey;
                                    return (
                                        <tr key={rowKey} className="align-top">
                                            <td className="px-4 py-4">
                                                <div className="font-medium text-white">{item.user.name}</div>
                                                <div className="text-gray-500">{item.user.email}</div>
                                            </td>
                                            <td className="px-4 py-4 text-gray-200">
                                                {company ? (
                                                    <Link
                                                        href={`/admin/companies/${company.id}`}
                                                        className="font-medium text-cyan-200 hover:text-cyan-100"
                                                    >
                                                        {company.company_name ?? 'Company detail'}
                                                    </Link>
                                                ) : (
                                                    '—'
                                                )}
                                            </td>
                                            <td className="px-4 py-4 text-gray-300">
                                                {company?.industry ?? '—'}
                                            </td>
                                            <td className="px-4 py-4 text-gray-300 max-w-64">
                                                <div>{joinValues(company?.target_regions)}</div>
                                                <div className="text-gray-500">{joinValues(company?.target_countries)}</div>
                                            </td>
                                            <td className="px-4 py-4 text-gray-300 max-w-56">
                                                {joinServices(company?.target_services)}
                                            </td>
                                            <td className="px-4 py-4">
                                                <span className={`inline-flex rounded border px-2 py-1 text-xs ${statusClass(item.user.approval_status)}`}>
                                                    {item.user.approval_status}
                                                </span>
                                            </td>
                                            <td className="px-4 py-4">
                                                <span className={`inline-flex rounded border px-2 py-1 text-xs ${statusClass(company?.approval_status)}`}>
                                                    {company?.approval_status ?? 'missing'}
                                                </span>
                                            </td>
                                            <td className="px-4 py-4 text-gray-300">
                                                {company?.pilot_status ?? '—'}
                                            </td>
                                            <td className="px-4 py-4">
                                                <div className="flex flex-wrap gap-2">
                                                    <button
                                                        type="button"
                                                        disabled={!canMutate || busy}
                                                        onClick={() => postAction(rowKey, `/admin/users/${item.user.id}/approve`)}
                                                        className="inline-flex items-center gap-1 rounded border border-emerald-500/30 px-2 py-1 text-xs text-emerald-200 hover:bg-emerald-500/10 disabled:opacity-40"
                                                    >
                                                        <Check className="w-3 h-3" />
                                                        User
                                                    </button>
                                                    <button
                                                        type="button"
                                                        disabled={!canMutate || busy || !company}
                                                        onClick={() => company && postAction(rowKey, `/admin/companies/${company.id}/approve`)}
                                                        className="inline-flex items-center gap-1 rounded border border-emerald-500/30 px-2 py-1 text-xs text-emerald-200 hover:bg-emerald-500/10 disabled:opacity-40"
                                                    >
                                                        <Check className="w-3 h-3" />
                                                        Company
                                                    </button>
                                                    <button
                                                        type="button"
                                                        disabled={!canMutate || busy}
                                                        onClick={() => postAction(rowKey, `/admin/users/${item.user.id}/reject`, true)}
                                                        className="inline-flex items-center gap-1 rounded border border-red-500/30 px-2 py-1 text-xs text-red-200 hover:bg-red-500/10 disabled:opacity-40"
                                                    >
                                                        <X className="w-3 h-3" />
                                                        Reject user
                                                    </button>
                                                    <button
                                                        type="button"
                                                        disabled={!canMutate || busy || !company}
                                                        onClick={() => company && postAction(rowKey, `/admin/companies/${company.id}/reject`, true)}
                                                        className="inline-flex items-center gap-1 rounded border border-red-500/30 px-2 py-1 text-xs text-red-200 hover:bg-red-500/10 disabled:opacity-40"
                                                    >
                                                        <X className="w-3 h-3" />
                                                        Reject company
                                                    </button>
                                                    <button
                                                        type="button"
                                                        disabled={!canMutate || busy}
                                                        onClick={() => postAction(rowKey, `/admin/users/${item.user.id}/disable`, true)}
                                                        className="rounded border border-gray-600 px-2 py-1 text-xs text-gray-300 hover:bg-gray-800 disabled:opacity-40"
                                                    >
                                                        Disable user
                                                    </button>
                                                    <button
                                                        type="button"
                                                        disabled={!canMutate || busy || !company}
                                                        onClick={() => company && postAction(rowKey, `/admin/companies/${company.id}/disable`, true)}
                                                        className="rounded border border-gray-600 px-2 py-1 text-xs text-gray-300 hover:bg-gray-800 disabled:opacity-40"
                                                    >
                                                        Disable company
                                                    </button>
                                                </div>
                                            </td>
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                    </div>
                )}
            </div>
        </div>
    );
}
