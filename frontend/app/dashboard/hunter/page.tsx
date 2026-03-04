'use client';

import { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { motion, AnimatePresence } from 'framer-motion';
import {
    Radar,
    Loader2,
    Banknote,
    Clock,
    Sparkles,
    X,
    ArrowRight,
    Target,
} from 'lucide-react';
import { api } from '@/lib/api';
import type { HunterRecommendation } from '@/types/hunter';

// ── Helpers ────────────────────────────────────────────────────

function scoreBadgeClasses(score: number): string {
    if (score >= 90)
        return 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30';
    if (score >= 75)
        return 'bg-amber-500/15 text-amber-400 border-amber-500/30';
    return 'bg-zinc-700/40 text-zinc-400 border-zinc-600/30';
}

function scoreGlowColor(score: number): string {
    if (score >= 90) return 'rgba(16,185,129,0.08)';
    if (score >= 75) return 'rgba(245,158,11,0.06)';
    return 'transparent';
}

function formatBudget(amount: number): string {
    if (amount >= 1_000_000_000) return `${(amount / 1_000_000_000).toFixed(1)}B`;
    if (amount >= 1_000_000) return `${(amount / 1_000_000).toFixed(0)}M`;
    return new Intl.NumberFormat('en-US').format(amount);
}

function formatDeadline(iso: string | null): string | null {
    if (!iso) return null;
    return new Date(iso).toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
    });
}

// ── Component ──────────────────────────────────────────────────

export default function HunterFeedPage() {
    const router = useRouter();
    const [recommendations, setRecommendations] = useState<HunterRecommendation[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [dismissing, setDismissing] = useState<Set<string>>(new Set());

    const fetchFeed = useCallback(async () => {
        try {
            const res = await api.get<HunterRecommendation[]>('/hunter/');
            setRecommendations(res.data);
        } catch (err) {
            console.error('Failed to fetch hunter feed:', err);
            setError('Failed to load recommendations');
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchFeed();
    }, [fetchFeed]);

    const handleDismiss = async (id: string) => {
        setDismissing((prev) => new Set(prev).add(id));
        try {
            await api.post(`/hunter/${id}/dismiss`);
            setRecommendations((prev) => prev.filter((r) => r.id !== id));
        } catch (err) {
            console.error('Dismiss failed:', err);
        } finally {
            setDismissing((prev) => {
                const next = new Set(prev);
                next.delete(id);
                return next;
            });
        }
    };

    // ── Loading state ──────────────────────────────────────────
    if (loading) {
        return (
            <div className="flex items-center justify-center h-64">
                <Loader2 className="w-8 h-8 text-indigo-500 animate-spin" />
            </div>
        );
    }

    // ── Error state ────────────────────────────────────────────
    if (error) {
        return (
            <div className="text-red-400 bg-red-500/10 border border-red-500/20 rounded-xl p-6">
                {error}
            </div>
        );
    }

    // ── Main render ────────────────────────────────────────────
    return (
        <div className="space-y-8">
            {/* Header */}
            <motion.div
                initial={{ opacity: 0, y: -20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.5 }}
            >
                <div className="flex items-center gap-3 mb-1">
                    <div className="w-10 h-10 rounded-xl bg-indigo-600 flex items-center justify-center">
                        <Target className="w-5 h-5 text-white" />
                    </div>
                    <h1 className="text-3xl font-bold text-white">Hunter Feed</h1>
                </div>
                <p className="text-zinc-400 mt-2 ml-[52px]">
                    AI-curated tender opportunities ranked by match strength
                </p>
            </motion.div>

            {/* Empty state */}
            {recommendations.length === 0 ? (
                <motion.div
                    initial={{ opacity: 0, scale: 0.95 }}
                    animate={{ opacity: 1, scale: 1 }}
                    className="bg-gray-900 border border-gray-800 rounded-xl p-16 text-center"
                >
                    <Radar className="w-16 h-16 text-zinc-700 mx-auto mb-4" />
                    <h3 className="text-xl font-semibold text-zinc-400 mb-2">
                        No Recommendations Yet
                    </h3>
                    <p className="text-zinc-500 max-w-md mx-auto">
                        The Hunter is scanning the market for opportunities that match
                        your company profile. Check back soon.
                    </p>
                </motion.div>
            ) : (
                /* Recommendation cards */
                <div className="space-y-4">
                    <AnimatePresence mode="popLayout">
                        {recommendations.map((rec, index) => (
                            <motion.div
                                key={rec.id}
                                layout
                                initial={{ opacity: 0, y: 20 }}
                                animate={{ opacity: 1, y: 0 }}
                                exit={{ opacity: 0, x: -300, transition: { duration: 0.3 } }}
                                transition={{ duration: 0.4, delay: index * 0.06 }}
                                className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden hover:border-gray-700 transition-colors"
                                style={{
                                    boxShadow: `inset 0 1px 0 0 ${scoreGlowColor(rec.match_score)}`,
                                }}
                            >
                                <div className="p-6">
                                    <div className="flex items-start justify-between gap-4">
                                        {/* Left: score + content */}
                                        <div className="flex gap-5 flex-1 min-w-0">
                                            {/* Score badge */}
                                            <div
                                                className={`shrink-0 w-16 h-16 rounded-xl border flex flex-col items-center justify-center ${scoreBadgeClasses(rec.match_score)}`}
                                            >
                                                <span className="text-2xl font-bold leading-none">
                                                    {rec.match_score}
                                                </span>
                                                <span className="text-[10px] uppercase tracking-wider opacity-70 mt-0.5">
                                                    match
                                                </span>
                                            </div>

                                            {/* Content */}
                                            <div className="min-w-0 flex-1">
                                                <h3 className="text-white font-semibold text-lg leading-snug truncate">
                                                    {rec.tender.title}
                                                </h3>

                                                {/* Meta row */}
                                                <div className="flex items-center gap-4 mt-2 text-sm">
                                                    <span className="flex items-center gap-1.5 text-green-400 font-medium">
                                                        <Banknote className="w-4 h-4" />
                                                        {formatBudget(rec.tender.budget)}{' '}
                                                        {rec.tender.currency}
                                                    </span>
                                                    {rec.tender.deadline && (
                                                        <span className="flex items-center gap-1.5 text-zinc-500">
                                                            <Clock className="w-3.5 h-3.5" />
                                                            {formatDeadline(rec.tender.deadline)}
                                                        </span>
                                                    )}
                                                </div>

                                                {/* Rationale */}
                                                <div className="mt-3 flex items-start gap-2">
                                                    <Sparkles className="w-4 h-4 text-indigo-400 shrink-0 mt-0.5" />
                                                    <p className="text-zinc-400 text-sm leading-relaxed">
                                                        {rec.strategic_rationale}
                                                    </p>
                                                </div>
                                            </div>
                                        </div>

                                        {/* Right: actions */}
                                        <div className="flex flex-col gap-2 shrink-0">
                                            <button
                                                onClick={() =>
                                                    router.push(
                                                        `/dashboard/bids/${rec.tender.id}`
                                                    )
                                                }
                                                className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium transition-colors"
                                            >
                                                Review Tender
                                                <ArrowRight className="w-4 h-4" />
                                            </button>
                                            <button
                                                onClick={() => handleDismiss(rec.id)}
                                                disabled={dismissing.has(rec.id)}
                                                className="flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl border border-zinc-700 text-zinc-400 hover:text-red-400 hover:border-red-500/30 hover:bg-red-500/5 text-sm font-medium transition-all disabled:opacity-50"
                                            >
                                                {dismissing.has(rec.id) ? (
                                                    <Loader2 className="w-4 h-4 animate-spin" />
                                                ) : (
                                                    <X className="w-4 h-4" />
                                                )}
                                                Dismiss
                                            </button>
                                        </div>
                                    </div>
                                </div>
                            </motion.div>
                        ))}
                    </AnimatePresence>
                </div>
            )}
        </div>
    );
}
