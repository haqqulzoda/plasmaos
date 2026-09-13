'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { Building2, Database, FileBarChart, Loader2, RefreshCw, ShieldCheck, Users } from 'lucide-react';
import { api } from '@/lib/api';
import { Button } from '@/components/ui/Button';
import { Alert } from '@/components/ui/Feedback';

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
        } catch {
            console.error('Failed to load admin overview:');
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
                Icon: Users,
                tone: 'warning',
            },
            {
                label: 'Pending companies',
                value: activity?.pending_companies,
                Icon: Building2,
                tone: 'info',
            },
            {
                label: 'Analyses',
                value: activity?.analyses_count,
                Icon: FileBarChart,
                tone: 'success',
            },
            {
                label: 'Vault records',
                value: activity?.vault_records_count,
                Icon: Database,
                tone: 'info',
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
        <div className="admin-page admin-overview ds-container-data ds-stack">
            <header className="admin-page-header">
                <div className="admin-heading-with-icon">
                    <ShieldCheck aria-hidden />
                    <div>
                        <span className="ds-eyebrow">Operations</span>
                        <h1>Admin Console</h1>
                        <p className="ds-muted">Account operations and corpus visibility</p>
                    </div>
                </div>
                <Button
                    variant="secondary"
                    onClick={loadOverview}
                    loading={loading}
                    leadingIcon={<RefreshCw aria-hidden />}
                >
                    Refresh
                </Button>
            </header>

            {error && <Alert tone="danger" title={error} />}

            {loading ? (
                <div className="ds-surface admin-loading" role="status">
                    <Loader2 className="ds-spin" aria-hidden /> Loading overview…
                </div>
            ) : (
                <>
                    <section className="admin-stat-grid" aria-label="Operational metrics">
                        {activityCards.map((card) => (
                            <div key={card.label} className={`ds-surface admin-stat ds-tone-${card.tone}`}>
                                <div>
                                    <span>{card.label}</span>
                                    <card.Icon aria-hidden />
                                </div>
                                <strong className="ds-numeric">
                                    {formatCount(card.value)}
                                </strong>
                            </div>
                        ))}
                    </section>

                    <div className="admin-overview-grid">
                        <section className="ds-surface admin-metric-list">
                            <header><h2>Activity</h2></header>
                            <dl>
                                {([
                                    ['Total users', activity?.total_users],
                                    ['Approved users', activity?.approved_users],
                                    ['Total companies', activity?.total_companies],
                                    ['Approved companies', activity?.approved_companies],
                                    ['Reports', activity?.reports_count],
                                ] satisfies CountRow[]).map(([label, value]) => (
                                    <div key={label}>
                                        <dt className="ds-muted">{label}</dt>
                                        <dd className="ds-numeric">{formatCount(value)}</dd>
                                    </div>
                                ))}
                            </dl>
                        </section>

                        <section className="ds-surface admin-table-surface">
                            <header className="admin-section-heading"><h2>Corpus health</h2></header>
                            <table className="admin-table">
                                <thead><tr><th scope="col">Source cohort</th><th scope="col">Visible records</th></tr></thead>
                                <tbody>
                                    {corpusRows.map(([label, value]) => (
                                        <tr key={label}>
                                            <th scope="row">{label}</th>
                                            <td className="ds-numeric">
                                                {formatCount(value)}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </section>
                    </div>

                    <div className="ds-surface admin-overview-action">
                        <Link
                            href="/admin/approvals"
                            className="ds-button ds-button-primary"
                        >
                            Open accounts
                        </Link>
                    </div>
                </>
            )}
        </div>
    );
}
