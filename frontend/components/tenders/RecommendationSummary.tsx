'use client';

import { Loader2, RotateCcw, Sparkles, X } from 'lucide-react';

import type { RecommendationSummary as RecommendationData } from '@/types/explorer';

const formatCreatedDate = (value: string): string => new Date(value).toLocaleDateString(
    'en-US',
    { month: 'short', day: 'numeric', year: 'numeric' },
);

export function RecommendationSummary({
    recommendation,
    pending,
    onDismiss,
    onRestore,
}: {
    recommendation: RecommendationData;
    pending: boolean;
    onDismiss: (recommendationId: string) => void;
    onRestore: (recommendationId: string) => void;
}) {
    const dismissed = recommendation.is_dismissed;

    return (
        <section
            aria-label="Recommendation summary"
            className="grid gap-3 rounded-lg border border-indigo-500/20 bg-indigo-500/[0.06] p-3 md:grid-cols-[auto_minmax(0,1fr)_auto] md:items-start"
        >
            <div className="w-fit rounded-lg border border-indigo-400/30 bg-indigo-400/10 px-3 py-2 text-center text-indigo-100">
                <span className="block text-[10px] font-semibold uppercase tracking-wide text-indigo-300">
                    Match score
                </span>
                <span className="mt-0.5 block text-xl font-bold leading-none">
                    {recommendation.match_score}
                    <span className="ml-0.5 text-xs font-medium text-indigo-300">/100</span>
                </span>
            </div>

            <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                    <h3 className="flex items-center gap-1.5 text-xs font-semibold text-indigo-200">
                        <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
                        Why this may match
                    </h3>
                    {dismissed ? (
                        <span className="rounded-full border border-zinc-600 bg-zinc-800 px-2 py-0.5 text-[10px] font-semibold text-zinc-300">
                            Recommendation dismissed
                        </span>
                    ) : null}
                </div>
                {recommendation.rationale_summary ? (
                    <p className="mt-1 line-clamp-3 text-xs leading-5 text-zinc-300">
                        {recommendation.rationale_summary}
                    </p>
                ) : null}
                <p className="mt-1 text-[10px] text-zinc-500">
                    Recommended on {formatCreatedDate(recommendation.created_at)}
                </p>
            </div>

            <button
                type="button"
                disabled={pending}
                onClick={() => dismissed
                    ? onRestore(recommendation.recommendation_id)
                    : onDismiss(recommendation.recommendation_id)}
                aria-label={dismissed ? 'Restore recommendation' : 'Dismiss recommendation'}
                className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-zinc-700 px-3 py-2 text-xs font-semibold text-zinc-200 transition hover:border-indigo-400 hover:text-indigo-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400 disabled:cursor-wait disabled:opacity-60"
            >
                {pending ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                ) : dismissed ? (
                    <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
                ) : (
                    <X className="h-3.5 w-3.5" aria-hidden="true" />
                )}
                {dismissed ? 'Restore recommendation' : 'Dismiss recommendation'}
            </button>
        </section>
    );
}
