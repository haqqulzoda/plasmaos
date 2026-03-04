'use client';

import { useState, useEffect, use } from 'react';
import DocumentViewer from '@/components/workspace/DocumentViewer';
import type {
    DynamicRequirements,
    DynamicEvaluation,
    AnalyzeTenderResponse,
    MissingRequirement,
} from '@/types/compliance';
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
    ShieldAlert,
    CheckCircle2,
    XCircle,
    AlertTriangle,
    Fingerprint,
} from 'lucide-react';
import Link from 'next/link';
import { clsx } from 'clsx';


// ═══════════════════════════════════════════════════════════════
// Page Component
// ═══════════════════════════════════════════════════════════════

export default function CompliancePage({ params }: { params: Promise<{ tenderId: string }> }) {
    const { tenderId } = use(params);

    // ── State ──
    const [isLoading, setIsLoading] = useState(false);
    const [requirements, setRequirements] = useState<DynamicRequirements | null>(null);
    const [evaluation, setEvaluation] = useState<DynamicEvaluation | null>(null);
    const [analysisId, setAnalysisId] = useState<string | null>(null);
    const [resolvedTenderId, setResolvedTenderId] = useState<string>(tenderId);
    const [rawText, setRawText] = useState<string>('');
    const [tenderTitle, setTenderTitle] = useState<string>('');
    const [isLoadingText, setIsLoadingText] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [elapsedTime, setElapsedTime] = useState<number | null>(null);
    const [acceptedNodeIds, setAcceptedNodeIds] = useState<string[]>([]);

    // ── Fetch compiled_master_text on mount ──
    useEffect(() => {
        const fetchTenderText = async () => {
            setIsLoadingText(true);
            try {
                // Primary path: treat route param as a tender ID.
                try {
                    const { data } = await api.get(`/tenders/${tenderId}`);
                    setResolvedTenderId(tenderId);
                    setRawText(data.compiled_master_text || '');
                    setTenderTitle(data.title || `Tender ${tenderId.slice(0, 8)}`);
                    return;
                } catch (primaryErr: unknown) {
                    const status = (primaryErr as { response?: { status?: number } })?.response?.status;
                    if (status !== 404) {
                        throw new Error(`Failed to fetch tender: ${status ?? 'unknown'}`);
                    }
                }

                // Fallback: users may paste a proposal ID from /dashboard/bids/{id}.
                let mappedTenderId: string | undefined;
                try {
                    const proposalResponse = await api.get(`/proposals/${tenderId}`);
                    mappedTenderId = proposalResponse.data?.tender_id;
                } catch {
                    throw new Error('Failed to resolve tender from proposal ID');
                }
                if (!mappedTenderId) {
                    throw new Error('Could not resolve tender from proposal ID');
                }

                const { data: tenderData } = await api.get(`/tenders/${mappedTenderId}`);
                setResolvedTenderId(mappedTenderId);
                setRawText(tenderData.compiled_master_text || '');
                setTenderTitle(tenderData.title || `Tender ${mappedTenderId.slice(0, 8)}`);
            } catch (err: unknown) {
                const message = err instanceof Error ? err.message : 'Failed to load tender text';
                setError(message);
            } finally {
                setIsLoadingText(false);
            }
        };

        fetchTenderText();
    }, [tenderId]);

    // ── Load cached analysis on mount ──
    useEffect(() => {
        if (!resolvedTenderId) return;

        const fetchCachedAnalysis = async () => {
            try {
                const { data } = await api.get(`/tenders/${resolvedTenderId}/latest-analysis`);
                if (data.analysis_id && data.requirements && data.evaluation) {
                    setAnalysisId(data.analysis_id);
                    setRequirements(data.requirements);
                    setEvaluation(data.evaluation);
                }
            } catch {
                // No cached analysis — user will see "Ready to Scan" state
            }
        };

        fetchCachedAnalysis();
    }, [resolvedTenderId]);

    // ── Load persisted risk overrides scoped to current analysis ──
    useEffect(() => {
        if (!resolvedTenderId || !analysisId) return;

        const fetchOverrides = async () => {
            try {
                const { data } = await api.get(`/tenders/${resolvedTenderId}/overrides?analysis_id=${analysisId}`);
                const ids = Array.isArray(data.accepted_node_ids) ? data.accepted_node_ids : [];
                setAcceptedNodeIds(ids.map((id: string) => id.toLowerCase()));
            } catch {
                setAcceptedNodeIds([]);
            }
        };

        fetchOverrides();
    }, [resolvedTenderId, analysisId]);

    // ── API Call: Trigger Compliance Scan ──
    const handleAnalyzeTender = async () => {
        setIsLoading(true);
        setError(null);
        setRequirements(null);
        setEvaluation(null);
        setAnalysisId(null);

        const startTime = performance.now();

        // Use force=true when re-scanning (cached results already shown)
        const forceParam = evaluation !== null ? '?force=true' : '';

        try {
            const { data } = await api.post<AnalyzeTenderResponse>(`/tenders/${resolvedTenderId}/analyze${forceParam}`);
            const elapsed = ((performance.now() - startTime) / 1000).toFixed(1);

            setAnalysisId(data.analysis_id ?? null);
            setRequirements(data.requirements ?? null);
            setEvaluation(data.evaluation ?? null);
            setElapsedTime(parseFloat(elapsed));
        } catch (err: unknown) {
            const axiosErr = err as { response?: { data?: { detail?: string }; status?: number } };
            const message =
                axiosErr?.response?.data?.detail ||
                (err instanceof Error ? err.message : 'An unexpected error occurred');
            setError(message);
        } finally {
            setIsLoading(false);
        }
    };

    // ── Derive UI state ──
    const hasAnalysis = requirements !== null && evaluation !== null;
    const hasText = rawText.length > 0;
    const isCompliant = evaluation?.is_compliant ?? false;
    const complianceLabel = hasAnalysis
        ? isCompliant
            ? 'Compliant'
            : 'Non-Compliant'
        : 'Pending';

    return (
        <div className="flex flex-col h-screen bg-gray-950">
            {/* ── Command Bar ── */}
            <header className="flex items-center justify-between px-5 py-3 border-b border-gray-800 bg-gray-950/90 backdrop-blur-sm shrink-0">
                <div className="flex items-center gap-4">
                    <Link
                        href="/dashboard/tenders"
                        className="flex items-center gap-1.5 text-gray-500 hover:text-gray-300 transition-colors text-[13px]"
                    >
                        <ArrowLeft className="w-4 h-4" />
                        <span>Back</span>
                    </Link>
                    <div className="w-px h-5 bg-gray-800" />
                    <div>
                        <h1 className="text-[15px] font-semibold text-gray-100">
                            {tenderTitle || 'Sovereign Compliance Engine'}
                        </h1>
                        <p className="text-[11px] text-gray-500 mt-0.5">
                            {hasAnalysis
                                ? 'Compliance scan complete · Review risk radar below'
                                : isLoading
                                    ? 'AI is analyzing taxonomy requirements...'
                                    : 'Initialize a compliance scan to identify gaps'}
                        </p>
                    </div>
                </div>
                <div className="flex items-center gap-3">
                    {/* Status Badge */}
                    {hasAnalysis && (
                        <div
                            className={clsx(
                                'flex items-center gap-1.5 px-3 py-1.5 rounded-lg border',
                                isCompliant
                                    ? 'bg-emerald-500/10 border-emerald-500/20'
                                    : 'bg-red-500/10 border-red-500/20'
                            )}
                        >
                            <span
                                className={clsx(
                                    'w-1.5 h-1.5 rounded-full animate-pulse',
                                    isCompliant ? 'bg-emerald-400' : 'bg-red-400'
                                )}
                            />
                            <span
                                className={clsx(
                                    'text-[11px] font-semibold uppercase tracking-wider',
                                    isCompliant ? 'text-emerald-400' : 'text-red-400'
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

                    {elapsedTime !== null && (
                        <div className="flex items-center gap-1.5 text-[11px] text-gray-500">
                            <Clock className="w-3.5 h-3.5" />
                            <span>{elapsedTime}s</span>
                        </div>
                    )}
                </div>
            </header>

            {/* ── Split Hemispheres ── */}
            <div className="flex-1 grid grid-cols-2 min-h-0">
                {/* ══ Left: Document Pane ══ */}
                <div className="border-r border-gray-800 min-h-0">
                    {isLoadingText ? (
                        <div className="flex flex-col h-full bg-gray-950">
                            <div className="flex-1 flex items-center justify-center p-8">
                                <div className="text-center space-y-4">
                                    <Loader2 className="w-8 h-8 text-indigo-400 animate-spin mx-auto" />
                                    <p className="text-sm text-gray-400">
                                        Loading tender document...
                                    </p>
                                </div>
                            </div>
                        </div>
                    ) : hasText ? (
                        <DocumentViewer
                            title={tenderTitle || 'Tender Document'}
                            content={rawText}
                        />
                    ) : (
                        <div className="flex flex-col h-full bg-gray-950">
                            <div className="flex-1 flex items-center justify-center p-8">
                                <div className="text-center space-y-4 max-w-sm">
                                    <div className="w-16 h-16 mx-auto rounded-xl bg-amber-500/10 flex items-center justify-center">
                                        <FileSearch className="w-7 h-7 text-amber-400" />
                                    </div>
                                    <div>
                                        <p className="text-sm font-semibold text-gray-200">
                                            No Document Text Available
                                        </p>
                                        <p className="text-[12px] text-gray-500 mt-1">
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
                                    <p className="text-[12px] text-gray-400 mt-0.5">{error}</p>
                                </div>
                                <button
                                    onClick={() => setError(null)}
                                    className="ml-auto text-gray-500 hover:text-gray-300 transition-colors"
                                >
                                    <X className="w-3.5 h-3.5" />
                                </button>
                            </div>
                        </div>
                    )}
                </div>

                {/* ══ Right: Compliance Results ══ */}
                <div className="min-h-0 overflow-y-auto">
                    {hasAnalysis ? (
                        <ComplianceResults
                            evaluation={evaluation}
                            analysisId={analysisId}
                            tenderId={resolvedTenderId}
                            acceptedNodeIds={acceptedNodeIds}
                            onOverrideAccepted={(nodeId) =>
                                setAcceptedNodeIds((prev) => {
                                    const normalized = nodeId.toLowerCase();
                                    if (prev.includes(normalized)) return prev;
                                    return [...prev, normalized];
                                })
                            }
                        />
                    ) : isLoading ? (
                        /* Loading Skeleton */
                        <div className="flex flex-col h-full bg-gray-950">
                            <div className="px-5 py-3.5 border-b border-gray-800 bg-gray-950/80 shrink-0">
                                <div className="flex items-center gap-3">
                                    <div className="w-8 h-8 rounded-lg bg-indigo-500/10 flex items-center justify-center">
                                        <Loader2 className="w-4 h-4 text-indigo-400 animate-spin" />
                                    </div>
                                    <div>
                                        <p className="text-[11px] font-medium uppercase tracking-widest text-gray-500">
                                            Processing
                                        </p>
                                        <h3 className="text-sm font-semibold text-gray-200">Running Analysis...</h3>
                                    </div>
                                </div>
                            </div>
                            <div className="flex-1 flex items-center justify-center p-8">
                                <div className="text-center space-y-6 max-w-sm">
                                    <div className="relative w-20 h-20 mx-auto">
                                        <div className="absolute inset-0 rounded-xl bg-indigo-500/10 animate-pulse" />
                                        <div className="absolute inset-0 flex items-center justify-center">
                                            <Cpu className="w-8 h-8 text-indigo-400" />
                                        </div>
                                    </div>
                                    <div>
                                        <p className="text-sm font-semibold text-gray-200">
                                            Plasma AI is mapping taxonomy requirements...
                                        </p>
                                        <p className="text-[12px] text-gray-500 mt-2">
                                            Classifying against the compliance ontology and evaluating
                                            your credentials. This may take 15–45 seconds.
                                        </p>
                                    </div>
                                    <div className="space-y-3 pt-4">
                                        <div className="h-3 bg-gray-800 rounded-full animate-pulse" />
                                        <div className="h-3 bg-gray-800 rounded-full animate-pulse w-4/5" />
                                        <div className="h-3 bg-gray-800 rounded-full animate-pulse w-3/5" />
                                        <div className="h-10 bg-gray-800/60 rounded-xl animate-pulse mt-4" />
                                        <div className="h-10 bg-gray-800/60 rounded-xl animate-pulse" />
                                    </div>
                                </div>
                            </div>
                        </div>
                    ) : (
                        /* Pre-Scan: Initialize Button */
                        <div className="flex flex-col h-full bg-gray-950">
                            <div className="px-5 py-3.5 border-b border-gray-800 bg-gray-950/80 shrink-0">
                                <div className="flex items-center gap-3">
                                    <div className="w-8 h-8 rounded-lg bg-gray-800 flex items-center justify-center">
                                        <ShieldCheck className="w-4 h-4 text-gray-500" />
                                    </div>
                                    <div>
                                        <p className="text-[11px] font-medium uppercase tracking-widest text-gray-500">
                                            Compliance Analysis
                                        </p>
                                        <h3 className="text-sm font-semibold text-gray-400">Ready to Scan</h3>
                                    </div>
                                </div>
                            </div>
                            <div className="flex-1 flex items-center justify-center p-8">
                                <div className="text-center space-y-6 max-w-sm">
                                    <div className="w-20 h-20 mx-auto rounded-xl bg-indigo-500/10 flex items-center justify-center border border-indigo-500/20">
                                        <Sparkles className="w-9 h-9 text-indigo-400" />
                                    </div>
                                    <div>
                                        <p className="text-sm font-semibold text-gray-200">
                                            Sovereign Compliance Engine
                                        </p>
                                        <p className="text-[12px] text-gray-500 mt-2 leading-relaxed">
                                            Run an AI-powered compliance scan against this tender&apos;s full
                                            document text. The engine maps requirements to the taxonomy ontology
                                            and evaluates your credentials for disqualification risks.
                                        </p>
                                    </div>
                                    <button
                                        onClick={handleAnalyzeTender}
                                        disabled={isLoading || !hasText}
                                        className={clsx(
                                            'flex items-center justify-center gap-2.5 w-full px-6 py-4 rounded-lg text-[14px] font-medium shadow-md transition-colors',
                                            hasText
                                                ? 'bg-indigo-600 hover:bg-indigo-500 text-white'
                                                : 'bg-gray-800 text-gray-500 cursor-not-allowed'
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


// ═══════════════════════════════════════════════════════════════
// Dynamic Compliance Results — Risk Radar
// ═══════════════════════════════════════════════════════════════

function ComplianceResults({
    evaluation,
    analysisId,
    tenderId,
    acceptedNodeIds,
    onOverrideAccepted,
}: {
    evaluation: DynamicEvaluation;
    analysisId: string | null;
    tenderId: string;
    acceptedNodeIds: string[];
    onOverrideAccepted: (nodeId: string) => void;
}) {
    const isCompliant = evaluation.is_compliant;
    const metReqs = evaluation.met_requirements ?? [];
    const missingReqs = evaluation.missing_requirements ?? [];
    const unmappedReqs = evaluation.unmapped_requirements ?? [];
    const statusMessage = evaluation.status_message ?? '';

    return (
        <div className="flex flex-col h-full bg-gray-950">
            {/* ── Verdict Banner ── */}
            <div
                className={clsx(
                    'px-5 py-4 border-b shrink-0',
                    isCompliant
                        ? 'bg-emerald-500/5 border-emerald-500/20'
                        : 'bg-red-500/5 border-red-500/20'
                )}
            >
                <div className="flex items-start gap-3">
                    <div
                        className={clsx(
                            'w-10 h-10 rounded-xl flex items-center justify-center shrink-0',
                            isCompliant ? 'bg-emerald-500/15' : 'bg-red-500/15'
                        )}
                    >
                        {isCompliant ? (
                            <ShieldCheck className="w-5 h-5 text-emerald-400" />
                        ) : (
                            <ShieldAlert className="w-5 h-5 text-red-400" />
                        )}
                    </div>
                    <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                            <h2
                                className={clsx(
                                    'text-[15px] font-bold uppercase tracking-wide',
                                    isCompliant ? 'text-emerald-400' : 'text-red-400'
                                )}
                            >
                                {isCompliant ? 'Fully Compliant' : 'Non-Compliant'}
                            </h2>
                        </div>
                        <p className="text-[12px] text-gray-400 mt-1 leading-relaxed">
                            {statusMessage}
                        </p>
                        {analysisId && (
                            <p className="text-[10px] text-gray-600 mt-2 font-mono">
                                Analysis ID: {analysisId}
                            </p>
                        )}
                    </div>
                </div>
            </div>

            {/* ── Dynamic Risk Radar Sections ── */}
            <div className="flex-1 overflow-y-auto p-5 space-y-4">
                {/* ═══ 1. Verified Credentials (Green) ═══ */}
                <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/5 overflow-hidden">
                    <div className="flex items-center gap-2.5 px-4 py-3 border-b border-emerald-500/15">
                        <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                        <h3 className="text-[13px] font-semibold text-emerald-300">
                            Verified Credentials
                        </h3>
                        <span className="ml-auto text-[10px] font-semibold uppercase tracking-wider text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded-md">
                            {metReqs.length} Met
                        </span>
                    </div>
                    <div className="px-4 py-3">
                        {metReqs.length === 0 ? (
                            <p className="text-[12px] text-gray-500 italic">
                                No mapped requirements matched your credentials
                            </p>
                        ) : (
                            <ul className="space-y-1.5">
                                {metReqs.map((req) => (
                                    <li key={req.uuid} className="flex items-center gap-2">
                                        <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                                        <span className="text-[12px] text-gray-300">{req.name}</span>
                                        <span className="ml-auto text-[10px] text-gray-600 font-mono">
                                            {req.uuid.slice(0, 8)}
                                        </span>
                                    </li>
                                ))}
                            </ul>
                        )}
                    </div>
                </div>

                {/* ═══ 2. Disqualification Risks (Red) ═══ */}
                <div className="rounded-xl border border-red-500/20 bg-red-500/5 overflow-hidden">
                    <div className="flex items-center gap-2.5 px-4 py-3 border-b border-red-500/15">
                        <XCircle className="w-4 h-4 text-red-400" />
                        <h3 className="text-[13px] font-semibold text-red-300">
                            Disqualification Risks
                        </h3>
                        {missingReqs.length > 0 && (
                            <span className="ml-auto text-[10px] font-semibold uppercase tracking-wider text-red-400 bg-red-500/10 px-2 py-0.5 rounded-md">
                                {missingReqs.length} Missing
                            </span>
                        )}
                    </div>
                    <div className="px-4 py-3">
                        {missingReqs.length === 0 ? (
                            <p className="text-[12px] text-gray-500 italic">
                                No disqualification risks identified
                            </p>
                        ) : (
                            <ul className="space-y-2.5">
                                {missingReqs.map((req) => (
                                    <DisqualificationRiskItem
                                        key={req.uuid}
                                        requirement={req}
                                        tenderId={tenderId}
                                        analysisId={analysisId}
                                        accepted={acceptedNodeIds.includes(req.uuid.toLowerCase())}
                                        onAccepted={onOverrideAccepted}
                                    />
                                ))}
                            </ul>
                        )}
                    </div>
                </div>

                {/* ═══ 3. Unmapped Tender Rules (Yellow/Amber) ═══ */}
                <div className="rounded-xl border border-amber-500/20 bg-amber-500/5 overflow-hidden">
                    <div className="flex items-center gap-2.5 px-4 py-3 border-b border-amber-500/15">
                        <AlertTriangle className="w-4 h-4 text-amber-400" />
                        <h3 className="text-[13px] font-semibold text-amber-300">
                            Unmapped Tender Rules
                        </h3>
                        {unmappedReqs.length > 0 && (
                            <span className="ml-auto text-[10px] font-semibold uppercase tracking-wider text-amber-400 bg-amber-500/10 px-2 py-0.5 rounded-md">
                                {unmappedReqs.length} Unclassified
                            </span>
                        )}
                    </div>
                    <div className="px-4 py-3">
                        {unmappedReqs.length === 0 ? (
                            <p className="text-[12px] text-gray-500 italic">
                                All tender requirements were mapped to the taxonomy
                            </p>
                        ) : (
                            <ul className="space-y-1.5">
                                {unmappedReqs.map((rule, idx) => (
                                    <li key={idx} className="flex items-start gap-2">
                                        <AlertTriangle className="w-3.5 h-3.5 text-amber-400 shrink-0 mt-0.5" />
                                        <span className="text-[12px] text-gray-300">{rule}</span>
                                    </li>
                                ))}
                            </ul>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
}


// ═══════════════════════════════════════════════════════════════
// Disqualification Risk Item + Accept Liability Button
// ═══════════════════════════════════════════════════════════════

function DisqualificationRiskItem({
    requirement,
    tenderId,
    analysisId,
    accepted,
    onAccepted,
}: {
    requirement: MissingRequirement;
    tenderId: string;
    analysisId: string | null;
    accepted: boolean;
    onAccepted: (nodeId: string) => void;
}) {
    const [isOverriding, setIsOverriding] = useState(false);

    const handleOverride = async () => {
        if (accepted || isOverriding || !analysisId) return;

        setIsOverriding(true);
        try {
            const response = await api.post(`/tenders/${tenderId}/override`, {
                node_id: requirement.uuid,
                analysis_id: analysisId,
            });
            if (response.status === 200) {
                onAccepted(requirement.uuid);
            }
        } finally {
            setIsOverriding(false);
        }
    };

    return (
        <li className="rounded-lg border border-red-500/10 bg-gray-900/60 px-3 py-2.5 space-y-2">
            <div className="flex items-start gap-2">
                <XCircle className="w-3.5 h-3.5 text-red-400 shrink-0 mt-0.5" />
                <div className="flex-1 min-w-0">
                    <span className="text-[12px] text-red-300 font-medium">{requirement.name}</span>
                    <div className="flex items-center gap-2 mt-1">
                        <span className="text-[10px] text-gray-600 font-mono">
                            {requirement.uuid.slice(0, 8)}
                        </span>
                        <span className="text-[10px] text-gray-500">
                            Weight: {requirement.impact_weight}
                        </span>
                        {requirement.is_fatal && (
                            <span className="text-[9px] font-bold uppercase tracking-wider text-red-500 bg-red-500/10 px-1.5 py-0.5 rounded">
                                Fatal
                            </span>
                        )}
                    </div>
                </div>
            </div>

            {/* Liability Handshake Button */}
            {accepted ? (
                <div className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-amber-500/10 border border-amber-500/20">
                    <Fingerprint className="w-3.5 h-3.5 text-amber-400" />
                    <span className="text-[11px] font-semibold text-amber-400">
                        Liability Accepted
                    </span>
                </div>
            ) : (
                <button
                    onClick={handleOverride}
                    disabled={isOverriding}
                    className="flex items-center gap-1.5 w-full px-2.5 py-1.5 rounded-lg border border-gray-700 bg-gray-800/60 hover:bg-gray-700/60 hover:border-amber-500/30 transition-all duration-200 group disabled:opacity-70 disabled:cursor-not-allowed"
                >
                    {isOverriding ? (
                        <Loader2 className="w-3.5 h-3.5 text-amber-400 animate-spin" />
                    ) : (
                        <Fingerprint className="w-3.5 h-3.5 text-gray-500 group-hover:text-amber-400 transition-colors" />
                    )}
                    <span className="text-[11px] font-medium text-gray-400 group-hover:text-amber-300 transition-colors">
                        {isOverriding ? 'Accepting Liability...' : 'Accept Liability'}
                    </span>
                </button>
            )}
        </li>
    );
}
