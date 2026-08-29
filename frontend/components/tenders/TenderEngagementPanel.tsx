'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { Bookmark, Loader2 } from 'lucide-react';

import { PrepareBidButton } from '@/components/bid-preparation/PrepareBidButton';
import { EngagementWorkflowActions } from '@/components/tenders/EngagementWorkflowActions';
import { api } from '@/lib/api';
import {
    engagementStatusClasses,
    engagementStatusDescription,
    engagementStatusLabel,
    type SaveToMyTendersResponse,
    type TenderEngagementActionContext,
    type TenderScopedEngagementResponse,
} from '@/types/engagement';

interface TenderEngagementPanelProps {
    tenderId: string;
    proposalContext?: boolean;
    engagementData?: TenderEngagementActionContext | null;
    proposalIdData?: string | null;
    loadingData?: boolean;
    canStartNew?: boolean;
    onRefresh?: () => void | Promise<void>;
}

export function TenderEngagementPanel({
    tenderId,
    proposalContext = false,
    engagementData,
    proposalIdData,
    loadingData = false,
    canStartNew = true,
    onRefresh,
}: TenderEngagementPanelProps) {
    const controlled = engagementData !== undefined;
    const [engagement, setEngagement] = useState<TenderEngagementActionContext | null>(engagementData ?? null);
    const [proposalId, setProposalId] = useState<string | null>(proposalIdData ?? null);
    const [loading, setLoading] = useState(!controlled);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const load = useCallback(async () => {
        if (controlled) {
            await onRefresh?.();
            return;
        }
        try {
            const response = await api.get<TenderScopedEngagementResponse>(`/tenders/${tenderId}/engagement`);
            setEngagement(response.data.engagement);
            setProposalId(response.data.proposal_id);
            setError(null);
        } catch {
            setError('Pursuit status could not be loaded.');
        } finally {
            setLoading(false);
        }
    }, [controlled, onRefresh, tenderId]);

    useEffect(() => {
        if (controlled) {
            setEngagement(engagementData ?? null);
            setProposalId(proposalIdData ?? null);
            setLoading(loadingData);
            return;
        }
        void load();
    }, [controlled, engagementData, load, loadingData, proposalIdData]);

    const save = async () => {
        setSaving(true);
        setError(null);
        try {
            const response = await api.post<SaveToMyTendersResponse>(`/tenders/${tenderId}/engagement`);
            setEngagement(response.data.engagement);
            await onRefresh?.();
        } catch (requestError: unknown) {
            const status = (requestError as { response?: { status?: number } }).response?.status;
            if (status === 409) {
                setError('Status changed. We refreshed the latest state.');
                await load();
            } else {
                setError('Tender could not be saved. Please try again.');
            }
        } finally {
            setSaving(false);
        }
    };

    return (
        <section aria-labelledby="pursuit-status-heading" className="rounded-xl border border-zinc-800 bg-zinc-950 p-4">
            <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-center">
                <div>
                    <h2 id="pursuit-status-heading" className="text-sm font-semibold text-white">Pursuit</h2>
                    {loading ? <p role="status" className="mt-2 flex items-center gap-2 text-sm text-zinc-400"><Loader2 className="h-4 w-4 animate-spin" />Loading pursuit status…</p> : engagement ? (
                        <div className="mt-2 flex flex-wrap items-center gap-2">
                            <span className={`rounded-md border px-2 py-1 text-xs font-semibold ${engagementStatusClasses(engagement.engagement_status)}`}>Pursuit: {engagementStatusLabel(engagement.engagement_status)}</span>
                            <span className="text-sm text-zinc-400">{engagementStatusDescription(engagement.engagement_status)}</span>
                        </div>
                    ) : (
                        <p className="mt-2 text-sm text-zinc-400">Not currently in My Tenders.</p>
                    )}
                </div>
                {!loading && engagement ? (
                    <EngagementWorkflowActions engagement={engagement} tenderId={tenderId} proposalId={proposalId} onChanged={setEngagement} onRefresh={load} />
                ) : !loading && proposalContext && proposalId ? (
                    <PrepareBidButton proposalId={proposalId} label="Continue Bid Preparation" />
                ) : !loading && canStartNew ? (
                    <div className="flex flex-wrap gap-2">
                        <button type="button" onClick={save} disabled={saving} className="inline-flex items-center gap-2 rounded-lg border border-sky-500/40 bg-sky-500/10 px-3 py-2 text-xs font-semibold text-sky-100 hover:bg-sky-500/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400 disabled:opacity-60">
                            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Bookmark className="h-4 w-4" />}{saving ? 'Saving…' : 'Save to My Tenders'}
                        </button>
                        <PrepareBidButton tenderId={tenderId} />
                    </div>
                ) : !loading ? (
                    <p className="text-xs text-zinc-500">No new pursuit action is available for this Tender status.</p>
                ) : null}
            </div>
            <div className="mt-3 flex gap-4 text-xs">
                <Link href="/dashboard/my-tenders" className="text-sky-300 hover:text-sky-200">Open My Tenders</Link>
                {proposalId ? <Link href={`/dashboard/bid-preparation/${proposalId}`} className="text-indigo-300 hover:text-indigo-200">Open Bid Preparation</Link> : null}
            </div>
            {error ? <p role="alert" className="mt-2 text-xs text-red-300">{error}</p> : null}
        </section>
    );
}
