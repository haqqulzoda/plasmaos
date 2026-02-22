'use client';

import { useState, useEffect, useMemo, use } from 'react';
import HighlightedText from '@/components/workspace/HighlightedText';
import DocumentViewer from '@/components/workspace/DocumentViewer';
import StrategyPanel from '@/components/workspace/StrategyPanel';
import type { GapAnalysis } from '@/types/compliance';
import { api } from '@/lib/api';
import {
    Cpu,
    Clock,
    ArrowLeft,
    Loader2,
    AlertCircle,
    Sparkles,
    X,
    FileSearch,
    ShieldCheck,
} from 'lucide-react';
import Link from 'next/link';
import { clsx } from 'clsx';

// ═══════════════════════════════════════════════════════════════
// Config
// ═══════════════════════════════════════════════════════════════

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1';

// ═══════════════════════════════════════════════════════════════
// Page Component
// ═══════════════════════════════════════════════════════════════

export default function CompliancePage({ params }: { params: Promise<{ tenderId: string }> }) {
    const { tenderId } = use(params);

    // ── State ──
    const [isLoading, setIsLoading] = useState(false);
    const [analysisData, setAnalysisData] = useState<GapAnalysis | null>(null);
    const [analysisId, setAnalysisId] = useState<string | null>(null);
    const [resolvedTenderId, setResolvedTenderId] = useState<string>(tenderId);
    const [rawText, setRawText] = useState<string>('');
    const [tenderTitle, setTenderTitle] = useState<string>('');
    const [isLoadingText, setIsLoadingText] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [elapsedTime, setElapsedTime] = useState<number | null>(null);

    // ── Fetch compiled_master_text on mount ──
    useEffect(() => {
        const fetchTenderText = async () => {
            setIsLoadingText(true);
            try {
                // Primary path: treat route param as a tender ID.
                let response = await fetch(`${API_BASE}/tenders/${tenderId}`);
                if (response.ok) {
                    const data = await response.json();
                    setResolvedTenderId(tenderId);
                    setRawText(data.compiled_master_text || '');
                    setTenderTitle(data.title || `Tender ${tenderId.slice(0, 8)}`);
                    return;
                }

                // Fallback: users may paste a proposal ID from /dashboard/bids/{id}.
                if (response.status === 404) {
                    let mappedTenderId: string | undefined;
                    try {
                        const proposalResponse = await api.get(`/proposals/${tenderId}`);
                        mappedTenderId = proposalResponse.data?.tender_id;
                    } catch {
                        throw new Error(`Failed to fetch tender: ${response.status}`);
                    }
                    if (!mappedTenderId) {
                        throw new Error('Could not resolve tender from proposal ID');
                    }

                    response = await fetch(`${API_BASE}/tenders/${mappedTenderId}`);
                    if (!response.ok) {
                        throw new Error(`Failed to fetch tender: ${response.status}`);
                    }

                    const tenderData = await response.json();
                    setResolvedTenderId(mappedTenderId);
                    setRawText(tenderData.compiled_master_text || '');
                    setTenderTitle(tenderData.title || `Tender ${mappedTenderId.slice(0, 8)}`);
                    return;
                }

                throw new Error(`Failed to fetch tender: ${response.status}`);
            } catch (err: unknown) {
                const message = err instanceof Error ? err.message : 'Failed to load tender text';
                setError(message);
            } finally {
                setIsLoadingText(false);
            }
        };

        fetchTenderText();
    }, [tenderId]);

    // ── Extract source quotes for highlighting ──
    const sourceQuotes = useMemo(() => {
        if (!analysisData) return [];
        return analysisData.identified_risks
            .map((risk) => risk.source_quote)
            .filter((q): q is string => !!q && q.trim().length > 0);
    }, [analysisData]);

    // ── API Call: Trigger Compliance Scan ──
    const handleAnalyzeTender = async () => {
        setIsLoading(true);
        setError(null);
        setAnalysisData(null);
        setAnalysisId(null);

        const startTime = performance.now();

        try {
            const response = await fetch(`${API_BASE}/tenders/${resolvedTenderId}/analyze`, {
                method: 'POST',
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => null);
                const detail = errorData?.detail || `Server returned ${response.status}`;
                throw new Error(detail);
            }

            const data = await response.json();
            const elapsed = ((performance.now() - startTime) / 1000).toFixed(1);

            if (data.analysis_id && data.analysis) {
                setAnalysisId(data.analysis_id);
                setAnalysisData(data.analysis);
            } else {
                setAnalysisId(null);
                setAnalysisData(data as GapAnalysis);
            }
            setElapsedTime(parseFloat(elapsed));
        } catch (err: unknown) {
            const message = err instanceof Error ? err.message : 'An unexpected error occurred';
            setError(message);
        } finally {
            setIsLoading(false);
        }
    };

    // ── Derive UI state ──
    const hasAnalysis = analysisData !== null;
    const hasText = rawText.length > 0;
    const complianceLabel = analysisData
        ? analysisData.is_fully_compliant
            ? 'Compliant'
            : 'Non-Compliant'
        : 'Pending';

    return (
        <div className="flex flex-col h-screen bg-black">
            {/* ── Command Bar ── */}
            <header className="flex items-center justify-between px-5 py-3 border-b border-zinc-800 bg-zinc-950/90 backdrop-blur-sm shrink-0">
                <div className="flex items-center gap-4">
                    <Link
                        href="/dashboard/tenders"
                        className="flex items-center gap-1.5 text-zinc-500 hover:text-zinc-300 transition-colors text-[13px]"
                    >
                        <ArrowLeft className="w-4 h-4" />
                        <span>Back</span>
                    </Link>
                    <div className="w-px h-5 bg-zinc-800" />
                    <div>
                        <h1 className="text-[15px] font-semibold text-zinc-100">
                            {tenderTitle || 'Sovereign Compliance Engine'}
                        </h1>
                        <p className="text-[11px] text-zinc-500 mt-0.5">
                            {hasAnalysis
                                ? 'Compliance scan complete · Review flagged clauses'
                                : isLoading
                                    ? 'AI is analyzing legal requirements...'
                                    : 'Initialize a compliance scan to identify risks'}
                        </p>
                    </div>
                </div>
                <div className="flex items-center gap-3">
                    {/* Status Badge */}
                    {hasAnalysis && (
                        <div
                            className={clsx(
                                'flex items-center gap-1.5 px-3 py-1.5 rounded-lg border',
                                analysisData.is_fully_compliant
                                    ? 'bg-emerald-500/10 border-emerald-500/20'
                                    : 'bg-red-500/10 border-red-500/20'
                            )}
                        >
                            <span
                                className={clsx(
                                    'w-1.5 h-1.5 rounded-full animate-pulse',
                                    analysisData.is_fully_compliant ? 'bg-emerald-400' : 'bg-red-400'
                                )}
                            />
                            <span
                                className={clsx(
                                    'text-[11px] font-semibold uppercase tracking-wider',
                                    analysisData.is_fully_compliant ? 'text-emerald-400' : 'text-red-400'
                                )}
                            >
                                {complianceLabel}
                            </span>
                        </div>
                    )}

                    {isLoading && (
                        <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-indigo-500/10 border border-indigo-500/20">
                            <Loader2 className="w-3.5 h-3.5 text-indigo-400 animate-spin" />
                            <span className="text-[11px] font-semibold text-indigo-400">Analyzing</span>
                        </div>
                    )}

                    <div className="flex items-center gap-1.5 text-[11px] text-zinc-500">
                        <Cpu className="w-3.5 h-3.5" />
                        <span>Gemini AI</span>
                    </div>

                    {elapsedTime !== null && (
                        <div className="flex items-center gap-1.5 text-[11px] text-zinc-500">
                            <Clock className="w-3.5 h-3.5" />
                            <span>{elapsedTime}s</span>
                        </div>
                    )}
                </div>
            </header>

            {/* ── Split Hemispheres ── */}
            <div className="flex-1 grid grid-cols-2 min-h-0">
                {/* ══ Left: Reality Pane ══ */}
                <div className="border-r border-zinc-800 min-h-0">
                    {isLoadingText ? (
                        /* Loading tender text */
                        <div className="flex flex-col h-full bg-zinc-950">
                            <div className="flex-1 flex items-center justify-center p-8">
                                <div className="text-center space-y-4">
                                    <Loader2 className="w-8 h-8 text-indigo-400 animate-spin mx-auto" />
                                    <p className="text-sm text-zinc-400">
                                        Loading tender document...
                                    </p>
                                </div>
                            </div>
                        </div>
                    ) : hasText ? (
                        /* Show highlighted text (post-analysis) or plain text (pre-analysis) */
                        hasAnalysis && sourceQuotes.length > 0 ? (
                            <HighlightedText
                                text={rawText}
                                quotes={sourceQuotes}
                                title={tenderTitle}
                            />
                        ) : (
                            <DocumentViewer
                                title={tenderTitle || 'Tender Document'}
                                content={rawText}
                            />
                        )
                    ) : (
                        /* No text available */
                        <div className="flex flex-col h-full bg-zinc-950">
                            <div className="flex-1 flex items-center justify-center p-8">
                                <div className="text-center space-y-4 max-w-sm">
                                    <div className="w-16 h-16 mx-auto rounded-2xl bg-amber-500/10 flex items-center justify-center">
                                        <FileSearch className="w-7 h-7 text-amber-400" />
                                    </div>
                                    <div>
                                        <p className="text-sm font-semibold text-zinc-200">
                                            No Document Text Available
                                        </p>
                                        <p className="text-[12px] text-zinc-500 mt-1">
                                            This tender has no compiled master text yet. Documents may not have been scraped or parsed.
                                        </p>
                                    </div>
                                </div>
                            </div>
                        </div>
                    )}

                    {/* Error Banner */}
                    {error && !isLoading && (
                        <div className="absolute bottom-4 left-4 right-[50%] mr-4">
                            <div className="flex items-start gap-3 rounded-xl border border-red-500/20 bg-red-500/5 px-4 py-3 backdrop-blur-sm">
                                <AlertCircle className="w-4 h-4 text-red-400 mt-0.5 shrink-0" />
                                <div>
                                    <p className="text-[13px] font-semibold text-red-400">Error</p>
                                    <p className="text-[12px] text-zinc-400 mt-0.5">{error}</p>
                                </div>
                                <button
                                    onClick={() => setError(null)}
                                    className="ml-auto text-zinc-500 hover:text-zinc-300 transition-colors"
                                >
                                    <X className="w-3.5 h-3.5" />
                                </button>
                            </div>
                        </div>
                    )}
                </div>

                {/* ══ Right: Strategy Panel ══ */}
                <div className="min-h-0">
                    {hasAnalysis ? (
                        <StrategyPanel analysis={analysisData} analysisId={analysisId || ''} />
                    ) : isLoading ? (
                        /* Loading Skeleton */
                        <div className="flex flex-col h-full bg-zinc-950">
                            <div className="px-5 py-3.5 border-b border-zinc-800 bg-zinc-950/80 shrink-0">
                                <div className="flex items-center gap-3">
                                    <div className="w-8 h-8 rounded-lg bg-indigo-500/10 flex items-center justify-center">
                                        <Loader2 className="w-4 h-4 text-indigo-400 animate-spin" />
                                    </div>
                                    <div>
                                        <p className="text-[11px] font-medium uppercase tracking-widest text-zinc-500">
                                            Processing
                                        </p>
                                        <h3 className="text-sm font-semibold text-zinc-200">Running Analysis...</h3>
                                    </div>
                                </div>
                            </div>
                            <div className="flex-1 flex items-center justify-center p-8">
                                <div className="text-center space-y-6 max-w-sm">
                                    <div className="relative w-20 h-20 mx-auto">
                                        <div className="absolute inset-0 rounded-2xl bg-indigo-500/10 animate-pulse" />
                                        <div className="absolute inset-0 flex items-center justify-center">
                                            <Cpu className="w-8 h-8 text-indigo-400" />
                                        </div>
                                    </div>
                                    <div>
                                        <p className="text-sm font-semibold text-zinc-200">
                                            Plasma AI is analyzing legal requirements...
                                        </p>
                                        <p className="text-[12px] text-zinc-500 mt-2">
                                            Scanning compiled text for compliance gaps, identifying
                                            risk factors, and extracting source quotes. This may take 15–45 seconds.
                                        </p>
                                    </div>
                                    {/* Skeleton bars */}
                                    <div className="space-y-3 pt-4">
                                        <div className="h-3 bg-zinc-800 rounded-full animate-pulse" />
                                        <div className="h-3 bg-zinc-800 rounded-full animate-pulse w-4/5" />
                                        <div className="h-3 bg-zinc-800 rounded-full animate-pulse w-3/5" />
                                        <div className="h-10 bg-zinc-800/60 rounded-xl animate-pulse mt-4" />
                                        <div className="h-10 bg-zinc-800/60 rounded-xl animate-pulse" />
                                    </div>
                                </div>
                            </div>
                        </div>
                    ) : (
                        /* Pre-Scan: Initialize Button */
                        <div className="flex flex-col h-full bg-zinc-950">
                            <div className="px-5 py-3.5 border-b border-zinc-800 bg-zinc-950/80 shrink-0">
                                <div className="flex items-center gap-3">
                                    <div className="w-8 h-8 rounded-lg bg-zinc-800 flex items-center justify-center">
                                        <ShieldCheck className="w-4 h-4 text-zinc-500" />
                                    </div>
                                    <div>
                                        <p className="text-[11px] font-medium uppercase tracking-widest text-zinc-500">
                                            Compliance Analysis
                                        </p>
                                        <h3 className="text-sm font-semibold text-zinc-400">Ready to Scan</h3>
                                    </div>
                                </div>
                            </div>
                            <div className="flex-1 flex items-center justify-center p-8">
                                <div className="text-center space-y-6 max-w-sm">
                                    <div className="w-20 h-20 mx-auto rounded-2xl bg-gradient-to-br from-indigo-500/10 to-purple-500/10 flex items-center justify-center border border-indigo-500/20">
                                        <Sparkles className="w-9 h-9 text-indigo-400" />
                                    </div>
                                    <div>
                                        <p className="text-sm font-semibold text-zinc-200">
                                            Sovereign Compliance Engine
                                        </p>
                                        <p className="text-[12px] text-zinc-500 mt-2 leading-relaxed">
                                            Run an AI-powered gap analysis against this tender&apos;s full
                                            document text. The engine will identify missing requirements,
                                            compliance risks, and risky clauses.
                                        </p>
                                    </div>
                                    <button
                                        onClick={handleAnalyzeTender}
                                        disabled={isLoading || !hasText}
                                        className={clsx(
                                            'flex items-center justify-center gap-2.5 w-full px-6 py-3.5 rounded-xl text-[14px] font-semibold transition-all duration-300',
                                            hasText
                                                ? 'bg-gradient-to-r from-indigo-600 to-purple-600 text-white hover:from-indigo-500 hover:to-purple-500 shadow-lg shadow-indigo-500/20 hover:shadow-indigo-500/30'
                                                : 'bg-zinc-800 text-zinc-500 cursor-not-allowed'
                                        )}
                                    >
                                        <Sparkles className="w-5 h-5" />
                                        Initialize Plasma AI Compliance Scan
                                    </button>
                                    {!hasText && !isLoadingText && (
                                        <p className="text-[11px] text-amber-400/80">
                                            No document text found. Scan cannot proceed.
                                        </p>
                                    )}
                                </div>
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
