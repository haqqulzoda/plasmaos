'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { Building2, Database, FileBarChart, Loader2, RefreshCw, ShieldCheck, Users } from 'lucide-react';
import { api } from '@/lib/api';

type AdminActivity = {
    total_users: number;
    pending_users: number;
    approved_users: number;
    total_companies: number;
    pending_companies: number;
    approved_companies: number;
    analyses_count: number;
    reports_count: number;
    vault_records_count: number;
};

type AdminCorpusHealth = {
    uzex_visible_count: number;
    world_bank_visible_count: number;
    adb_visible_count: number;
    hidden_legacy_uzex_count: number;
    small_uzex_count: number;
};

type CountRow = [label: string, value?: number];

const formatCount = (value?: number) =>
    new Intl.NumberFormat('en-US').format(value ?? 0);

export default function AdminPage() {
    const [activity, setActivity] = useState<AdminActivity | null>(null);
    const [corpusHealth, setCorpusHealth] = useState<AdminCorpusHealth | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const loadOverview = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const [activityResponse, corpusResponse] = await Promise.all([
                api.get<AdminActivity>('/admin/activity'),
                api.get<AdminCorpusHealth>('/admin/corpus-health'),
            ]);
            setActivity(activityResponse.data);
            setCorpusHealth(corpusResponse.data);
        } catch (err) {
            console.error('Failed to load admin overview:', err);
            setError('Failed to load admin overview.');
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        loadOverview();
    }, [loadOverview]);

    const activityCards = useMemo(
        () => [
            {
                label: 'Pending users',
                value: activity?.pending_users,
                icon: <Users className="h-5 w-5 text-amber-300" />,
                tone: 'border-amber-500/20 bg-amber-500/10',
            },
            {
                label: 'Pending companies',
                value: activity?.pending_companies,
                icon: <Building2 className="h-5 w-5 text-cyan-300" />,
                tone: 'border-cyan-500/20 bg-cyan-500/10',
            },
            {
                label: 'Analyses',
                value: activity?.analyses_count,
                icon: <FileBarChart className="h-5 w-5 text-emerald-300" />,
                tone: 'border-emerald-500/20 bg-emerald-500/10',
            },
            {
                label: 'Vault records',
                value: activity?.vault_records_count,
                icon: <Database className="h-5 w-5 text-indigo-300" />,
                tone: 'border-indigo-500/20 bg-indigo-500/10',
            },
        ],
        [activity],
    );

    const corpusRows: CountRow[] = [
        ['UzEx enterprise visible', corpusHealth?.uzex_visible_count],
        ['World Bank visible', corpusHealth?.world_bank_visible_count],
        ['ADB visible', corpusHealth?.adb_visible_count],
        ['Hidden legacy UzEx', corpusHealth?.hidden_legacy_uzex_count],
        ['Small UzEx excluded', corpusHealth?.small_uzex_count],
    ];

    return (
        <div className="space-y-6">
            <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
                <div className="flex items-center gap-3">
                    <ShieldCheck className="w-6 h-6 text-cyan-300" />
                    <div>
                        <h1 className="text-2xl font-semibold text-white">Admin Console</h1>
                        <p className="text-sm text-gray-400">Account operations and corpus visibility</p>
                    </div>
                </div>
                <button
                    type="button"
                    onClick={loadOverview}
                    className="inline-flex items-center justify-center gap-2 rounded-lg border border-gray-700 px-4 py-2 text-sm font-medium text-gray-300 hover:bg-gray-900 hover:text-white transition-colors"
                >
                    <RefreshCw className="h-4 w-4" />
                    Refresh
                </button>
            </div>

            {error && (
                <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
                    {error}
                </div>
            )}

            {loading ? (
                <div className="h-64 rounded-lg border border-gray-800 bg-gray-950 flex items-center justify-center">
                    <Loader2 className="h-7 w-7 animate-spin text-cyan-300" />
                </div>
            ) : (
                <>
                    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                        {activityCards.map((card) => (
                            <div key={card.label} className={`rounded-lg border p-5 ${card.tone}`}>
                                <div className="flex items-center justify-between">
                                    <span className="text-sm text-gray-300">{card.label}</span>
                                    {card.icon}
                                </div>
                                <div className="mt-4 text-3xl font-semibold text-white">
                                    {formatCount(card.value)}
                                </div>
                            </div>
                        ))}
                    </div>

                    <div className="grid gap-6 xl:grid-cols-[1fr_1.2fr]">
                        <div className="rounded-lg border border-gray-800 bg-gray-950 overflow-hidden">
                            <div className="border-b border-gray-800 px-5 py-4">
                                <h2 className="text-base font-semibold text-white">Activity</h2>
                            </div>
                            <div className="divide-y divide-gray-800 text-sm">
                                {([
                                    ['Total users', activity?.total_users],
                                    ['Approved users', activity?.approved_users],
                                    ['Total companies', activity?.total_companies],
                                    ['Approved companies', activity?.approved_companies],
                                    ['Reports', activity?.reports_count],
                                ] satisfies CountRow[]).map(([label, value]) => (
                                    <div key={label} className="flex items-center justify-between px-5 py-3">
                                        <span className="text-gray-400">{label}</span>
                                        <span className="font-medium text-white">{formatCount(value)}</span>
                                    </div>
                                ))}
                            </div>
                        </div>

                        <div className="rounded-lg border border-gray-800 bg-gray-950 overflow-hidden">
                            <div className="border-b border-gray-800 px-5 py-4">
                                <h2 className="text-base font-semibold text-white">Corpus health</h2>
                            </div>
                            <table className="w-full text-sm">
                                <tbody className="divide-y divide-gray-800">
                                    {corpusRows.map(([label, value]) => (
                                        <tr key={label}>
                                            <td className="px-5 py-3 text-gray-400">{label}</td>
                                            <td className="px-5 py-3 text-right font-medium text-white">
                                                {formatCount(value)}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </div>

                    <div className="rounded-lg border border-gray-800 bg-gray-950 p-5">
                        <Link
                            href="/admin/approvals"
                            className="inline-flex items-center rounded-lg bg-cyan-600 px-4 py-2 text-sm font-semibold text-white hover:bg-cyan-500 transition-colors"
                        >
                            Open accounts
                        </Link>
                    </div>
                </>
            )}
        </div>
    );
}
