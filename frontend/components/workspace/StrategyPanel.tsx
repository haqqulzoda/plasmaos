'use client';

import { useState, useCallback } from 'react';
import {
    ShieldCheck,
    ShieldAlert,
    AlertTriangle,
    CheckCircle2,
    ChevronRight,
    Fingerprint,
    BookOpen,
    Flame,
    Info,
    Loader2,
    X,
    AlertCircle,
} from 'lucide-react';
import { clsx } from 'clsx';
import type { GapAnalysis, Severity } from '@/types/compliance';

// ═══════════════════════════════════════════════════════════════
// Config
// ═══════════════════════════════════════════════════════════════

const API_BASE = '/api/v1';
const DEMO_USER_ID = 'demo_user_01';

// ═══════════════════════════════════════════════════════════════
// Props
// ═══════════════════════════════════════════════════════════════

interface StrategyPanelProps {
    analysis: GapAnalysis;
    analysisId: string;
}

const severityConfig: Record<Severity, { border: string; bg: string; badge: string; badgeBg: string; icon: string }> = {
    High: {
        border: 'border-red-500/30',
        bg: 'bg-red-500/5',
        badge: 'text-red-400',
        badgeBg: 'bg-red-500/10',
        icon: 'text-red-400',
    },
    Medium: {
        border: 'border-amber-500/30',
        bg: 'bg-amber-500/5',
        badge: 'text-amber-400',
        badgeBg: 'bg-amber-500/10',
        icon: 'text-amber-400',
    },
    Low: {
        border: 'border-blue-500/30',
        bg: 'bg-blue-500/5',
        badge: 'text-blue-400',
        badgeBg: 'bg-blue-500/10',
        icon: 'text-blue-400',
    },
};

// ═══════════════════════════════════════════════════════════════
// Component
// ═══════════════════════════════════════════════════════════════

export default function StrategyPanel({ analysis, analysisId }: StrategyPanelProps) {
    const [authorizedRisks, setAuthorizedRisks] = useState<Set<string>>(new Set());
    const [authorizingRisks, setAuthorizingRisks] = useState<Set<string>>(new Set());
    const [errorMessage, setErrorMessage] = useState<string | null>(null);

    const handleAuthorizeRisk = useCallback(
        async (riskType: string) => {
            // Guard: already authorized, currently authorizing, or missing analysisId
            if (authorizedRisks.has(riskType) || authorizingRisks.has(riskType)) return;
            if (!analysisId) {
                setErrorMessage('Cannot authorize: no analysis ID available. Run the analysis first.');
                return;
            }

            // Set loading state for this specific button
            setAuthorizingRisks((prev) => new Set(prev).add(riskType));
            setErrorMessage(null);

            try {
                const response = await fetch(`${API_BASE}/audit/authorize`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        analysis_id: analysisId,
                        risk_type: riskType,
                        user_id: DEMO_USER_ID,
                    }),
                });

                if (!response.ok) {
                    const errorData = await response.json().catch(() => null);
                    const detail = errorData?.detail || `Server returned ${response.status}`;
                    throw new Error(detail);
                }

                // Server confirmed — mark as authorized
                setAuthorizedRisks((prev) => new Set(prev).add(riskType));
            } catch (err: unknown) {
                const message = err instanceof Error ? err.message : 'Authorization failed';
                setErrorMessage(`Failed to authorize "${riskType}": ${message}`);
            } finally {
                // Clear loading state regardless of outcome
                setAuthorizingRisks((prev) => {
                    const next = new Set(prev);
                    next.delete(riskType);
                    return next;
                });
            }
        },
        [authorizedRisks, authorizingRisks, analysisId]
    );

    const totalRisks = analysis.identified_risks.length;
    const authorizedCount = authorizedRisks.size;

    return (
        <div className="flex flex-col h-full bg-zinc-950">
            {/* ── Header ── */}
            <div className="px-5 py-3.5 border-b border-zinc-800 bg-zinc-950/80 backdrop-blur-sm shrink-0">
                <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                        <div
                            className={clsx(
                                'w-8 h-8 rounded-lg flex items-center justify-center',
                                analysis.is_fully_compliant ? 'bg-emerald-500/10' : 'bg-red-500/10'
                            )}
                        >
                            {analysis.is_fully_compliant ? (
                                <ShieldCheck className="w-4 h-4 text-emerald-400" />
                            ) : (
                                <ShieldAlert className="w-4 h-4 text-red-400" />
                            )}
                        </div>
                        <div>
                            <p className="text-[11px] font-medium uppercase tracking-widest text-zinc-500">
                                Compliance Analysis
                            </p>
                            <h3 className="text-sm font-semibold text-zinc-200">Strategy Panel</h3>
                        </div>
                    </div>

                    {/* Authorization Progress */}
                    {totalRisks > 0 && (
                        <div className="flex items-center gap-2 text-[11px] text-zinc-500">
                            <Fingerprint className="w-3.5 h-3.5" />
                            <span>
                                {authorizedCount}/{totalRisks} authorized
                            </span>
                        </div>
                    )}
                </div>
            </div>

            {/* ── Body ── */}
            <div className="flex-1 overflow-y-auto">
                <div className="p-5 space-y-5">
                    {/* ── Error Banner ── */}
                    {errorMessage && (
                        <div className="flex items-start gap-3 rounded-xl border border-red-500/20 bg-red-500/5 px-4 py-3">
                            <AlertCircle className="w-4 h-4 text-red-400 mt-0.5 shrink-0" />
                            <div className="flex-1">
                                <p className="text-[13px] font-semibold text-red-400">Authorization Failed</p>
                                <p className="text-[12px] text-zinc-400 mt-0.5">{errorMessage}</p>
                            </div>
                            <button
                                onClick={() => setErrorMessage(null)}
                                className="text-zinc-500 hover:text-zinc-300 transition-colors"
                            >
                                <X className="w-3.5 h-3.5" />
                            </button>
                        </div>
                    )}

                    {/* ── Compliance Status Banner ── */}
                    <div
                        className={clsx(
                            'rounded-xl border px-5 py-4',
                            analysis.is_fully_compliant
                                ? 'border-emerald-500/20 bg-emerald-500/5'
                                : 'border-red-500/20 bg-red-500/5'
                        )}
                    >
                        <div className="flex items-center gap-3">
                            {analysis.is_fully_compliant ? (
                                <ShieldCheck className="w-6 h-6 text-emerald-400 shrink-0" />
                            ) : (
                                <ShieldAlert className="w-6 h-6 text-red-400 shrink-0" />
                            )}
                            <div>
                                <p
                                    className={clsx(
                                        'text-sm font-bold uppercase tracking-wide',
                                        analysis.is_fully_compliant ? 'text-emerald-400' : 'text-red-400'
                                    )}
                                >
                                    {analysis.is_fully_compliant ? 'FULLY COMPLIANT' : 'NON-COMPLIANT'}
                                </p>
                                <p className="text-[13px] text-zinc-400 mt-0.5">
                                    {analysis.is_fully_compliant
                                        ? 'All regulatory requirements are met for this tender.'
                                        : `${analysis.missing_requirements.length} missing requirements · ${totalRisks} identified risks`}
                                </p>
                            </div>
                        </div>
                    </div>

                    {/* ── Missing Requirements ── */}
                    {analysis.missing_requirements.length > 0 && (
                        <section>
                            <div className="flex items-center gap-2 mb-3">
                                <AlertTriangle className="w-4 h-4 text-amber-400" />
                                <h4 className="text-xs font-semibold uppercase tracking-widest text-zinc-400">
                                    Missing Requirements
                                </h4>
                            </div>
                            <div className="space-y-2">
                                {analysis.missing_requirements.map((req, i) => (
                                    <div
                                        key={i}
                                        className="flex items-start gap-3 rounded-lg border border-amber-500/20 bg-amber-500/5 px-4 py-3"
                                    >
                                        <ChevronRight className="w-4 h-4 text-amber-400 mt-0.5 shrink-0" />
                                        <p className="text-[13px] text-zinc-300 leading-relaxed">{req}</p>
                                    </div>
                                ))}
                            </div>
                        </section>
                    )}

                    {/* ── Identified Risks ── */}
                    {totalRisks > 0 && (
                        <section>
                            <div className="flex items-center gap-2 mb-3">
                                <Flame className="w-4 h-4 text-red-400" />
                                <h4 className="text-xs font-semibold uppercase tracking-widest text-zinc-400">
                                    Identified Risks
                                </h4>
                            </div>
                            <div className="space-y-3">
                                {analysis.identified_risks.map((risk, i) => {
                                    const config = severityConfig[risk.severity];
                                    const isAuthorized = authorizedRisks.has(risk.risk_type);
                                    const isAuthorizing = authorizingRisks.has(risk.risk_type);

                                    return (
                                        <div
                                            key={i}
                                            className={clsx(
                                                'rounded-xl border px-5 py-4 transition-all duration-200',
                                                config.border,
                                                config.bg,
                                                isAuthorized && 'ring-1 ring-emerald-500/30'
                                            )}
                                        >
                                            {/* Risk Header */}
                                            <div className="flex items-center justify-between mb-2">
                                                <div className="flex items-center gap-2">
                                                    <span
                                                        className={clsx(
                                                            'inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-bold uppercase tracking-wider',
                                                            config.badgeBg,
                                                            config.badge
                                                        )}
                                                    >
                                                        {risk.severity}
                                                    </span>
                                                    <span className="text-sm font-semibold text-zinc-200">
                                                        {risk.risk_type}
                                                    </span>
                                                </div>
                                                {isAuthorized && (
                                                    <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                                                )}
                                            </div>

                                            {/* Risk Description */}
                                            <p className="text-[13px] text-zinc-400 leading-relaxed mb-4">
                                                {risk.description}
                                            </p>

                                            {/* ── LIABILITY HANDSHAKE ── */}
                                            <button
                                                onClick={() => handleAuthorizeRisk(risk.risk_type)}
                                                disabled={isAuthorized || isAuthorizing}
                                                className={clsx(
                                                    'w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg text-[13px] font-semibold transition-all duration-200',
                                                    isAuthorized
                                                        ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 cursor-default'
                                                        : isAuthorizing
                                                            ? 'bg-zinc-800 text-indigo-400 border border-indigo-500/30 cursor-wait'
                                                            : 'bg-zinc-800 text-zinc-300 border border-zinc-700 hover:bg-zinc-700 hover:text-white hover:border-zinc-600'
                                                )}
                                            >
                                                {isAuthorized ? (
                                                    <>
                                                        <CheckCircle2 className="w-4 h-4" />
                                                        Authorized
                                                    </>
                                                ) : isAuthorizing ? (
                                                    <>
                                                        <Loader2 className="w-4 h-4 animate-spin" />
                                                        Authorizing...
                                                    </>
                                                ) : (
                                                    <>
                                                        <Fingerprint className="w-4 h-4" />
                                                        Authorize Mitigation
                                                    </>
                                                )}
                                            </button>
                                        </div>
                                    );
                                })}
                            </div>
                        </section>
                    )}

                    {/* ── Recommended Mitigation Strategy ── */}
                    {analysis.recommended_mitigation_strategy && (
                        <section>
                            <div className="flex items-center gap-2 mb-3">
                                <BookOpen className="w-4 h-4 text-indigo-400" />
                                <h4 className="text-xs font-semibold uppercase tracking-widest text-zinc-400">
                                    Recommended Mitigation
                                </h4>
                            </div>
                            <div className="rounded-xl border border-indigo-500/20 bg-indigo-500/5 px-5 py-4">
                                <div className="flex gap-3">
                                    <Info className="w-4 h-4 text-indigo-400 mt-0.5 shrink-0" />
                                    <p className="text-[13px] text-zinc-300 leading-relaxed">
                                        {analysis.recommended_mitigation_strategy}
                                    </p>
                                </div>
                            </div>
                        </section>
                    )}
                </div>
            </div>

            {/* ── Footer ── */}
            <div className="px-5 py-2.5 border-t border-zinc-800 bg-zinc-950/80 shrink-0">
                <div className="flex items-center justify-between text-[11px] text-zinc-500">
                    <span>Sovereign Compliance Engine v1.0</span>
                    <span>
                        {authorizedCount === totalRisks && totalRisks > 0
                            ? '✓ All risks reviewed'
                            : `${totalRisks - authorizedCount} pending review`}
                    </span>
                </div>
            </div>
        </div>
    );
}
