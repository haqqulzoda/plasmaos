'use client';

import { useEffect, useState } from 'react';
import { Bookmark, CheckCircle2, Loader2 } from 'lucide-react';

import { api } from '@/lib/api';
import {
    engagementStatusLabel,
    type SaveToMyTendersResponse,
    type TenderEngagementSummary,
    type TenderScopedEngagementResponse,
} from '@/types/engagement';

export function SaveToMyTendersButton({ tenderId }: { tenderId: string }) {
    const [engagement, setEngagement] = useState<TenderEngagementSummary | null>(null);
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        let cancelled = false;
        api.get<TenderScopedEngagementResponse>(`/tenders/${tenderId}/engagement`)
            .then((response) => {
                if (!cancelled) setEngagement(response.data.engagement);
            })
            .catch(() => {
                if (!cancelled) setError('My Tenders status could not be loaded.');
            })
            .finally(() => {
                if (!cancelled) setLoading(false);
            });
        return () => {
            cancelled = true;
        };
    }, [tenderId]);

    const save = async () => {
        setSaving(true);
        setError(null);
        try {
            const response = await api.post<SaveToMyTendersResponse>(
                `/tenders/${tenderId}/engagement`,
            );
            setEngagement(response.data.engagement);
        } catch {
            setError('Tender could not be saved. Please try again.');
        } finally {
            setSaving(false);
        }
    };

    const label = engagement
        ? engagement.engagement_status === 'DISMISSED'
            ? 'Save to My Tenders again'
            : `In My Tenders: ${engagementStatusLabel(engagement.engagement_status)}`
        : 'Save to My Tenders';

    return (
        <div className="flex flex-col items-end gap-1">
            <button
                type="button"
                onClick={save}
                disabled={loading || saving}
                aria-label={label}
                className="inline-flex items-center gap-2 rounded-lg border border-sky-500/40 bg-sky-500/10 px-3 py-2 text-xs font-semibold text-sky-100 transition hover:border-sky-400 hover:bg-sky-500/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400 disabled:cursor-not-allowed disabled:opacity-60"
            >
                {loading || saving ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                ) : engagement && engagement.engagement_status !== 'DISMISSED' ? (
                    <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
                ) : (
                    <Bookmark className="h-3.5 w-3.5" aria-hidden="true" />
                )}
                {saving ? 'Saving…' : label}
            </button>
            {error ? <span role="alert" className="text-xs text-red-300">{error}</span> : null}
        </div>
    );
}
