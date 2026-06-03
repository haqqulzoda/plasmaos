'use client';

import { useState, useEffect, use, useMemo } from 'react';
import DocumentViewer from '@/components/workspace/DocumentViewer';
import type {
    DynamicRequirements,
    DynamicEvaluation,
    AnalyzeTenderResponse,
    ComplianceVerdictStatus,
    HybridCompliancePayload,
    RequirementMatchDetail,
    OverrideResponse,
} from '@/types/compliance';
import { extractHybridCompliance } from '@/lib/useHybridCompliance';
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
    ShieldOff,
    CheckCircle2,

    AlertTriangle,
    Fingerprint,
    Lock,
    FolderTree,
    ClipboardList,
    Download,
} from 'lucide-react';
import Link from 'next/link';
import { clsx } from 'clsx';

function extractContentHash(data: Record<string, unknown> | null | undefined): string | null {
    if (!data || typeof data !== 'object') return null;
    const raw = (data as { content_hash?: unknown }).content_hash;
    return typeof raw === 'string' && raw.trim().length > 0 ? raw : null;
}

/**
 * Deterministic hash for requirement text → synthetic node ID.
 * Used when a requirement lacks a taxonomy_node_id (token-overlap matches).
 * FNV-1a 32-bit: fast, deterministic, zero dependencies.
 */
function hashSnippet(text: string): string {
    let hash = 0x811c9dc5;
    for (let i = 0; i < text.length; i++) {
        hash ^= text.charCodeAt(i);
        hash = Math.imul(hash, 0x01000193);
    }
    return (hash >>> 0).toString(16).padStart(8, '0');
}

type VerdictTone = 'success' | 'review' | 'danger' | 'pending';

type UiVerdict = {
    status: ComplianceVerdictStatus | 'PENDING';
    label: string;
    tone: VerdictTone;
};

type TenderDocument = {
    id: string;
    file_url: string;
    file_type: string;
    display_name: string;
    original_filename?: string | null;
    storage_filename?: string | null;
    parsed_source_filenames?: string[];
    archive_inner_filenames?: string[];
    file_size?: number | null;
    created_at?: string;
};

function safeDecodeURIComponent(value: string): string {
    try {
        return decodeURIComponent(value);
    } catch {
        return value;
    }
}

function stripStoredNamePrefix(filename: string): string {
    const [, prefix, remainder] = filename.match(/^([a-f0-9]{32})_(.+)$/i) ?? [];
    return prefix && remainder ? remainder : filename;
}

function basenameFromPathish(value: string | null | undefined): string {
    const raw = (value ?? '').trim();
    if (!raw) return '';

    try {
        const parsed = new URL(raw);
        const queryPath = parsed.searchParams.get('path');
        const candidate = safeDecodeURIComponent(queryPath || parsed.pathname);
        return stripStoredNamePrefix(candidate.split(/[\\/]/).filter(Boolean).pop() ?? '');
    } catch {
        const candidate = safeDecodeURIComponent(raw).split('?')[0].split('#')[0];
        return stripStoredNamePrefix(candidate.split(/[\\/]/).filter(Boolean).pop() ?? candidate);
    }
}

function normalizeFilenameValue(value: string): string {
    return value
        .normalize('NFKC')
        .toLowerCase()
        .replace(/\s+/g, ' ')
        .trim();
}

function repairUtf8Mojibake(value: string): string {
    const raw = value.trim();
    if (!raw || !/[ÃÂÐÑ]/.test(raw)) return raw;

    const chars = Array.from(raw);
    const bytes = chars.map((char) => char.charCodeAt(0));
    if (bytes.some((byte) => byte > 255)) return raw;

    try {
        return new TextDecoder('utf-8', { fatal: true }).decode(new Uint8Array(bytes)) || raw;
    } catch {
        return raw;
    }
}

function normalizedFilenameCandidates(value: string | null | undefined): string[] {
    const basename = basenameFromPathish(value);
    const repairedBasename = repairUtf8Mojibake(basename);

    return Array.from(new Set(
        [basename, repairedBasename]
            .map(normalizeFilenameValue)
            .filter(Boolean),
    ));
}

function getFileExtension(value: string | null | undefined): string {
    const filename = basenameFromPathish(value);
    const parts = filename.split('.');
    return parts.length > 1 ? parts[parts.length - 1].toLowerCase() : '';
}

function filenameFromContentDisposition(value: string | null): string | null {
    if (!value) return null;

    const utf8Match = value.match(/filename\*=UTF-8''([^;]+)/i);
    if (utf8Match?.[1]) {
        return safeDecodeURIComponent(utf8Match[1].replace(/^"|"$/g, ''));
    }

    const asciiMatch = value.match(/filename="?([^";]+)"?/i);
    return asciiMatch?.[1] ?? null;
}

function axiosStatus(error: unknown): number | undefined {
    return (error as { response?: { status?: number } })?.response?.status;
}

async function complianceExportErrorMessage(error: unknown): Promise<string> {
    const response = (error as { response?: { data?: unknown; status?: number } })?.response;
    const status = response?.status;

    if (response?.data instanceof Blob) {
        try {
            const text = await response.data.text();
            if (text.trim()) {
                const payload = JSON.parse(text) as { detail?: unknown };
                if (typeof payload.detail === 'string' && payload.detail.trim()) {
                    return payload.detail;
                }
            }
        } catch {
            // Fall through to status-based copy.
        }
    } else {
        const detail = (response?.data as { detail?: unknown } | undefined)?.detail;
        if (typeof detail === 'string' && detail.trim()) {
            return detail;
        }
    }

    if (status === 401) return 'Sign in again to download the compliance report.';
    if (status === 403 || status === 404) return 'Compliance report is unavailable for this tender.';
    return 'Compliance PDF export failed. Please try again later.';
}

async function errorDetailFromResponse(response: Response): Promise<string> {
    try {
        const text = await response.text();
        if (text.trim()) {
            try {
                const payload = JSON.parse(text) as { detail?: unknown };
                if (typeof payload.detail === 'string' && payload.detail.trim()) {
                    return payload.detail;
                }
            } catch {
                return text.trim();
            }
        }
    } catch {
        // Fall through to status-based copy.
    }

    if (response.status === 401) return 'Sign in again to open this source document.';
    if (response.status === 403) return 'You do not have access to this source document.';
    if (response.status === 404) return 'Source document file is unavailable. Re-sync documents for this tender.';
    return 'Source document could not be opened. Please try again or re-sync documents for this tender.';
}

function getDocumentDisplayName(doc: TenderDocument): string {
    return (
        basenameFromPathish(doc.display_name)
        || basenameFromPathish(doc.original_filename)
        || basenameFromPathish(doc.file_url)
        || basenameFromPathish(doc.storage_filename)
        || (doc.file_type ? `document.${doc.file_type}` : 'document')
    );
}

function documentCandidateNames(doc: TenderDocument): string[] {
    return [
        doc.display_name,
        doc.original_filename,
        getDocumentDisplayName(doc),
        basenameFromPathish(doc.file_url),
        basenameFromPathish(doc.storage_filename),
        ...(doc.parsed_source_filenames ?? []),
        ...(doc.archive_inner_filenames ?? []),
    ].filter((value): value is string => Boolean(value && value.trim()));
}

function getDocumentExtension(doc: TenderDocument | null): string {
    if (!doc) return '';
    return (
        getFileExtension(doc.display_name)
        || getFileExtension(doc.original_filename)
        || getFileExtension(doc.file_url)
        || getFileExtension(doc.storage_filename)
        || doc.file_type.toLowerCase()
    );
}

function isPdfDocument(doc: TenderDocument | null): boolean {
    return getDocumentExtension(doc) === 'pdf' || doc?.file_type?.toLowerCase() === 'pdf';
}

function isArchiveDocument(doc: TenderDocument | null): boolean {
    return ['zip', 'rar', '7z', 'tar', 'gz'].includes(getDocumentExtension(doc));
}

function isArchiveInnerSource(requirement: RequirementMatchDetail, doc: TenderDocument | null): boolean {
    if (!doc || !isArchiveDocument(doc)) return false;
    const sourceNames = new Set(normalizedFilenameCandidates(requirement.source_filename));
    return (doc.archive_inner_filenames ?? []).some(
        (filename) => normalizedFilenameCandidates(filename).some((candidate) => sourceNames.has(candidate)),
    );
}

function getRequirementKey(detail: RequirementMatchDetail): string {
    return [
        detail.taxonomy_node_id ?? `synth_${hashSnippet(detail.raw_text_snippet)}`,
        detail.source_filename,
        detail.source_page,
        detail.verdict,
        detail.exact_quote || detail.raw_text_snippet,
    ].join('|');
}

function buildDocumentFilenameIndex(documents: TenderDocument[]): Map<string, TenderDocument> {
    const index = new Map<string, TenderDocument>();

    for (const doc of documents) {
        for (const candidate of documentCandidateNames(doc)) {
            for (const normalized of normalizedFilenameCandidates(candidate)) {
                if (normalized && !index.has(normalized)) {
                    index.set(normalized, doc);
                }
            }
        }
    }

    return index;
}

function resolveDocumentForRequirement(
    detail: RequirementMatchDetail | null,
    documentIndex: Map<string, TenderDocument>,
): TenderDocument | null {
    if (!detail) return null;
    for (const candidate of normalizedFilenameCandidates(detail.source_filename)) {
        const doc = documentIndex.get(candidate);
        if (doc) return doc;
    }
    return null;
}

function deriveHybridVerdict(hybridCompliance: HybridCompliancePayload | null): UiVerdict | null {
    if (!hybridCompliance) return null;

    const knownStatus = hybridCompliance.verdict_status
        && ['NOT_ELIGIBLE', 'NEEDS_REVIEW', 'ELIGIBLE_WITH_REVIEW', 'COMPLIANT'].includes(hybridCompliance.verdict_status)
        ? hybridCompliance.verdict_status
        : undefined;
    const status =
        knownStatus ??
        (hybridCompliance.failed_dealbreakers.length > 0 || hybridCompliance.failed_count > 0
            ? 'NOT_ELIGIBLE'
            : hybridCompliance.manual_reviews_required.length > 0 || hybridCompliance.manual_review_count > 0
                ? hybridCompliance.satisfied_count > 0
                    ? 'ELIGIBLE_WITH_REVIEW'
                    : 'NEEDS_REVIEW'
                : hybridCompliance.satisfied_count > 0
                    ? 'COMPLIANT'
                    : (hybridCompliance.recorded_obligations_count ?? 0) > 0
                        ? 'ELIGIBLE_WITH_REVIEW'
                        : 'NEEDS_REVIEW');

    if (status === 'NOT_ELIGIBLE') {
        return { status, label: 'Non-Compliant', tone: 'danger' };
    }
    if (status === 'ELIGIBLE_WITH_REVIEW') {
        return { status, label: 'Eligible With Review', tone: 'review' };
    }
    if (status === 'NEEDS_REVIEW') {
        return { status, label: 'Needs Review', tone: 'review' };
    }
    return { status, label: 'Fully Compliant', tone: 'success' };
}

function deriveUiVerdict(
    hybridCompliance: HybridCompliancePayload | null,
    evaluation: DynamicEvaluation | null,
): UiVerdict {
    const hybridVerdict = deriveHybridVerdict(hybridCompliance);
    if (hybridVerdict) return hybridVerdict;

    if (!evaluation) return { status: 'PENDING', label: 'Pending', tone: 'pending' };
    return evaluation.is_compliant
        ? { status: 'COMPLIANT', label: 'Compliant', tone: 'success' }
        : { status: 'NOT_ELIGIBLE', label: 'Non-Compliant', tone: 'danger' };
}

function deriveStatusMessage(
    hybridCompliance: HybridCompliancePayload | null,
    evaluation: DynamicEvaluation,
): string {
    if (hybridCompliance) {
        const manualOnly =
            hybridCompliance.failed_dealbreakers.length === 0
            && hybridCompliance.failed_count === 0
            && hybridCompliance.satisfied_count === 0
            && (
                hybridCompliance.manual_reviews_required.length > 0
                || hybridCompliance.manual_review_count > 0
            );

        if (manualOnly) {
            return 'No verified requirements yet — manual review required.';
        }

        return hybridCompliance.status_message;
    }

    return evaluation.status_message ?? '';
}

const verdictBadgeClasses: Record<VerdictTone, string> = {
    success: 'bg-emerald-500/10 border-emerald-500/20',
    review: 'bg-amber-500/10 border-amber-500/20',
    danger: 'bg-red-500/10 border-red-500/20',
    pending: 'bg-gray-500/10 border-gray-500/20',
};

const verdictDotClasses: Record<VerdictTone, string> = {
    success: 'bg-emerald-400',
    review: 'bg-amber-400',
    danger: 'bg-red-400',
    pending: 'bg-gray-400',
};

const verdictTextClasses: Record<VerdictTone, string> = {
    success: 'text-emerald-400',
    review: 'text-amber-400',
    danger: 'text-red-400',
    pending: 'text-gray-400',
};

const verdictPanelClasses: Record<VerdictTone, string> = {
    success: 'bg-emerald-500/5 border-emerald-500/20',
    review: 'bg-amber-500/5 border-amber-500/20',
    danger: 'bg-red-500/5 border-red-500/20',
    pending: 'bg-gray-500/5 border-gray-500/20',
};

const verdictIconClasses: Record<VerdictTone, string> = {
    success: 'bg-emerald-500/15',
    review: 'bg-amber-500/15',
    danger: 'bg-red-500/15',
    pending: 'bg-gray-500/15',
};


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
    const [textAccessReadyVersion, setTextAccessReadyVersion] = useState(0);
    const [error, setError] = useState<string | null>(null);
    const [elapsedTime, setElapsedTime] = useState<number | null>(null);
    const [acceptedNodeIds, setAcceptedNodeIds] = useState<string[]>([]);
    const [hybridCompliance, setHybridCompliance] = useState<HybridCompliancePayload | null>(null);
    const [contentHash, setContentHash] = useState<string | null>(null);
    const [overrideSeal, setOverrideSeal] = useState<string | null>(null);
    const [documents, setDocuments] = useState<TenderDocument[]>([]);
    const [isLoadingDocuments, setIsLoadingDocuments] = useState(false);
    const [documentFetchError, setDocumentFetchError] = useState<string | null>(null);
    const [selectedRequirement, setSelectedRequirement] = useState<RequirementMatchDetail | null>(null);
    const [isDownloadingPdf, setIsDownloadingPdf] = useState(false);

    // ── Fetch compiled source text on mount ──
    useEffect(() => {
        const fetchTenderText = async () => {
            setIsLoadingText(true);
            try {
                let resolvedId = tenderId;
                let tenderData: { title?: string } | null = null;

                try {
                    const { data } = await api.get(`/tenders/${tenderId}`);
                    tenderData = data;
                } catch (primaryErr: unknown) {
                    const status = axiosStatus(primaryErr);
                    if (status !== 404) {
                        throw new Error(`Failed to fetch tender: ${status ?? 'unknown'}`);
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

                    resolvedId = mappedTenderId;
                    const { data } = await api.get(`/tenders/${resolvedId}`);
                    tenderData = data;
                }

                let textResponse;
                try {
                    textResponse = await api.get(`/tenders/${resolvedId}/compiled-text`);
                } catch (textErr: unknown) {
                    if (axiosStatus(textErr) !== 404) {
                        throw textErr;
                    }

                    await api.post('/proposals', { tender_id: resolvedId });
                    textResponse = await api.get(`/tenders/${resolvedId}/compiled-text`);
                }

                setResolvedTenderId(resolvedId);
                setRawText(textResponse.data.compiled_master_text || '');
                setTenderTitle(tenderData?.title || `Tender ${resolvedId.slice(0, 8)}`);
                setTextAccessReadyVersion((version) => version + 1);
            } catch (err: unknown) {
                const message = err instanceof Error ? err.message : 'Failed to load tender text';
                setError(message);
            } finally {
                setIsLoadingText(false);
            }
        };

        fetchTenderText();
    }, [tenderId]);

    // ── Load synchronized source documents for evidence preview ──
    useEffect(() => {
        if (!resolvedTenderId) return;

        const fetchTenderDocuments = async () => {
            setIsLoadingDocuments(true);
            setDocumentFetchError(null);

            try {
                const { data } = await api.get<TenderDocument[]>(`/tenders/${resolvedTenderId}/documents`);
                setDocuments(Array.isArray(data) ? data : []);
            } catch (err: unknown) {
                const axiosErr = err as { response?: { data?: { detail?: string }; status?: number } };
                setDocuments([]);
                setDocumentFetchError(
                    axiosErr?.response?.data?.detail ||
                    (err instanceof Error ? err.message : 'Source documents could not be loaded')
                );
            } finally {
                setIsLoadingDocuments(false);
            }
        };

        fetchTenderDocuments();
    }, [resolvedTenderId]);

    // ── Load cached analysis on mount ──
    useEffect(() => {
        if (!resolvedTenderId || textAccessReadyVersion === 0) return;

        const fetchCachedAnalysis = async () => {
            try {
                const { data } = await api.get(`/tenders/${resolvedTenderId}/latest-analysis`);
                if (data.analysis_id && data.requirements && data.evaluation) {
                    setAnalysisId(data.analysis_id);
                    setRequirements(data.requirements);
                    setEvaluation(data.evaluation);
                    setHybridCompliance(extractHybridCompliance(data));
                    setContentHash(extractContentHash(data));
                    setOverrideSeal((data as Record<string, unknown>).override_seal as string | null ?? null);
                }
            } catch {
                // No cached analysis — user will see "Ready to Scan" state
            }
        };

        fetchCachedAnalysis();
    }, [resolvedTenderId, textAccessReadyVersion]);

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
        setHybridCompliance(null);
        setContentHash(null);
        setOverrideSeal(null);
        setSelectedRequirement(null);

        const startTime = performance.now();

        // Use force=true when re-scanning (cached results already shown)
        const forceParam = evaluation !== null ? '?force=true' : '';

        try {
            const { data } = await api.post<AnalyzeTenderResponse>(`/tenders/${resolvedTenderId}/analyze${forceParam}`);
            const elapsed = ((performance.now() - startTime) / 1000).toFixed(1);

            setAnalysisId(data.analysis_id ?? null);
            setRequirements(data.requirements ?? null);
            setEvaluation(data.evaluation ?? null);
            setHybridCompliance(extractHybridCompliance(data as unknown as Record<string, unknown>));
            setContentHash(data.content_hash);
            setOverrideSeal(data.override_seal ?? null);
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

    const handleDownloadCompliancePdf = async () => {
        if (!resolvedTenderId || isDownloadingPdf) return;

        setIsDownloadingPdf(true);
        setError(null);

        try {
            const query = analysisId ? `?analysis_id=${encodeURIComponent(analysisId)}` : '';
            const response = await api.get(
                `/tenders/${resolvedTenderId}/compliance/export/pdf${query}`,
                { responseType: 'blob' },
            );
            const contentType = response.headers['content-type'] || 'application/pdf';
            const blob = new Blob([response.data], { type: contentType });
            const url = URL.createObjectURL(blob);
            const downloadName = filenameFromContentDisposition(
                (response.headers['content-disposition'] as string | undefined) ?? null,
            ) || `compliance_report_${resolvedTenderId.slice(0, 8)}.pdf`;

            const link = document.createElement('a');
            link.href = url;
            link.download = downloadName;
            document.body.appendChild(link);
            link.click();
            link.remove();

            window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
        } catch (err: unknown) {
            setError(await complianceExportErrorMessage(err));
        } finally {
            setIsDownloadingPdf(false);
        }
    };

    // ── Derive UI state ──
    const hasAnalysis = requirements !== null && evaluation !== null;
    const hasText = rawText.length > 0;
    const uiVerdict = deriveUiVerdict(hybridCompliance, evaluation);
    const complianceLabel = hasAnalysis ? uiVerdict.label : 'Pending';
    const documentIndex = useMemo(() => buildDocumentFilenameIndex(documents), [documents]);
    const selectedDocument = useMemo(
        () => resolveDocumentForRequirement(selectedRequirement, documentIndex),
        [selectedRequirement, documentIndex],
    );

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
                        <button
                            type="button"
                            onClick={handleDownloadCompliancePdf}
                            disabled={isDownloadingPdf}
                            className="flex items-center gap-1.5 rounded-lg border border-gray-700 bg-gray-900 px-3 py-1.5 text-[11px] font-semibold text-gray-200 transition-colors hover:border-indigo-400/50 hover:text-indigo-200 disabled:cursor-wait disabled:opacity-60"
                        >
                            {isDownloadingPdf ? (
                                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                            ) : (
                                <Download className="w-3.5 h-3.5" />
                            )}
                            {isDownloadingPdf ? 'Preparing PDF' : 'Download Compliance PDF'}
                        </button>
                    )}

                    {hasAnalysis && (
                        <div
                            className={clsx(
                                'flex items-center gap-1.5 px-3 py-1.5 rounded-lg border',
                                verdictBadgeClasses[uiVerdict.tone]
                            )}
                        >
                            <span
                                className={clsx(
                                    'w-1.5 h-1.5 rounded-full animate-pulse',
                                    verdictDotClasses[uiVerdict.tone]
                                )}
                            />
                            <span
                                className={clsx(
                                    'text-[11px] font-semibold uppercase tracking-wider',
                                    verdictTextClasses[uiVerdict.tone]
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
                    {selectedRequirement ? (
                        <EvidenceDocumentPane
                            requirement={selectedRequirement}
                            matchedDocument={selectedDocument}
                            isLoadingDocuments={isLoadingDocuments}
                            documentFetchError={documentFetchError}
                            onClearSelection={() => setSelectedRequirement(null)}
                        />
                    ) : isLoadingText ? (
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
                            onOverrideSealUpdated={(seal, nodeIds) => {
                                setOverrideSeal(seal);
                                setAcceptedNodeIds((prev) => {
                                    const merged = new Set(prev);
                                    nodeIds.forEach((id) => merged.add(id.toLowerCase()));
                                    return [...merged];
                                });
                            }}
                            hybridCompliance={hybridCompliance}
                            contentHash={contentHash}
                            overrideSeal={overrideSeal}
                            selectedRequirementKey={selectedRequirement ? getRequirementKey(selectedRequirement) : null}
                            onSelectRequirement={setSelectedRequirement}
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

function EvidenceDocumentPane({
    requirement,
    matchedDocument,
    isLoadingDocuments,
    documentFetchError,
    onClearSelection,
}: {
    requirement: RequirementMatchDetail;
    matchedDocument: TenderDocument | null;
    isLoadingDocuments: boolean;
    documentFetchError: string | null;
    onClearSelection: () => void;
}) {
    const sourcePage = requirement.source_page || 1;
    const quote = requirement.exact_quote || requirement.raw_text_snippet;
    const sourceFilename = requirement.source_filename || 'source document';
    const matchedName = matchedDocument ? getDocumentDisplayName(matchedDocument) : sourceFilename;
    const documentUrl = matchedDocument ? `/api/documents/${matchedDocument.id}` : null;
    const iframeSrc = documentUrl ? `${documentUrl}#page=${sourcePage}` : null;
    const extension = getDocumentExtension(matchedDocument);
    const isPdf = isPdfDocument(matchedDocument);
    const isDocx = extension === 'docx' || extension === 'doc';
    const isArchive = isArchiveDocument(matchedDocument);
    const isArchiveInner = isArchiveInnerSource(requirement, matchedDocument);
    const pageLabel = isDocx
        ? 'Document-level provenance'
        : `Page ${sourcePage}`;

    return (
        <div className="flex flex-col h-full bg-gray-950">
            <div className="flex items-center gap-3 px-5 py-3.5 border-b border-gray-800 bg-gray-950/80 backdrop-blur-sm shrink-0">
                <div className="w-8 h-8 rounded-lg bg-indigo-500/10 flex items-center justify-center">
                    <FileSearch className="w-4 h-4 text-indigo-400" />
                </div>
                <div className="min-w-0 flex-1">
                    <p className="text-[11px] font-medium uppercase tracking-widest text-gray-500">
                        Source Evidence
                    </p>
                    <h3 className="text-sm font-semibold text-gray-200 truncate max-w-md">
                        {matchedName}
                    </h3>
                </div>
                <button
                    type="button"
                    onClick={onClearSelection}
                    className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-[12px] font-semibold text-gray-200 transition hover:border-indigo-400/50 hover:text-indigo-200 focus:outline-none focus:ring-2 focus:ring-indigo-500/40"
                >
                    <ArrowLeft className="w-3.5 h-3.5" />
                    Back to source document
                </button>
            </div>

            <div className="shrink-0 border-b border-gray-800 bg-gray-900/45 px-5 py-3 space-y-2">
                <div className="flex flex-wrap items-center gap-2 text-[11px] text-gray-400">
                    <span className="inline-flex items-center gap-1 rounded bg-gray-800/80 px-2 py-1">
                        <FileSearch className="w-3 h-3 text-gray-500" />
                        <span className="max-w-[20rem] truncate">{sourceFilename}</span>
                    </span>
                    <span className="rounded bg-gray-800/80 px-2 py-1">{pageLabel}</span>
                    {isPdf && (
                        <span className="rounded bg-indigo-500/10 px-2 py-1 text-indigo-300">
                            PDF page jump is best-effort
                        </span>
                    )}
                </div>
                <div className="rounded-lg border border-indigo-500/15 bg-indigo-500/8 px-3 py-2">
                    <p className="text-[10px] font-semibold uppercase tracking-wider text-indigo-300">
                        Evidence Quote
                    </p>
                    <p className="text-[12px] text-gray-200 leading-relaxed mt-1">
                        &quot;{quote}&quot;
                    </p>
                </div>
            </div>

            {isPdf && iframeSrc ? (
                <div className="flex-1 min-h-0 bg-gray-900">
                    <iframe
                        key={iframeSrc}
                        title={`Source evidence: ${matchedName}`}
                        src={iframeSrc}
                        className="h-full w-full border-0 bg-gray-900"
                    />
                </div>
            ) : (
                <EvidenceFallbackPanel
                    matchedDocument={matchedDocument}
                    documentUrl={documentUrl}
                    sourceFilename={sourceFilename}
                    pageLabel={pageLabel}
                    isLoadingDocuments={isLoadingDocuments}
                    documentFetchError={documentFetchError}
                    isDocx={isDocx}
                    isArchive={isArchive}
                    isArchiveInner={isArchiveInner}
                />
            )}
        </div>
    );
}

function EvidenceFallbackPanel({
    matchedDocument,
    documentUrl,
    sourceFilename,
    pageLabel,
    isLoadingDocuments,
    documentFetchError,
    isDocx,
    isArchive,
    isArchiveInner,
}: {
    matchedDocument: TenderDocument | null;
    documentUrl: string | null;
    sourceFilename: string;
    pageLabel: string;
    isLoadingDocuments: boolean;
    documentFetchError: string | null;
    isDocx: boolean;
    isArchive: boolean;
    isArchiveInner: boolean;
}) {
    const [openError, setOpenError] = useState<string | null>(null);
    const [isOpening, setIsOpening] = useState(false);
    let message = 'This source file is not a PDF, so inline page navigation is unavailable.';

    if (isLoadingDocuments) {
        message = 'Resolving the source document from synchronized tender files.';
    } else if (documentFetchError) {
        message = documentFetchError;
    } else if (isArchiveInner) {
        message = 'Source file is inside an archive. Preview is not available yet, but the quote and filename are preserved.';
    } else if (!matchedDocument) {
        message = 'Document not matched. The filename may differ from the synchronized source file.';
    } else if (isDocx) {
        message = 'DOCX provenance is document-level. Page 1 is not a true rendered page.';
    } else if (isArchive) {
        message = 'Archive contents cannot be previewed inline here. Open or download the source archive.';
    }

    const handleOpenDocument = async () => {
        if (!documentUrl || isOpening) return;

        setIsOpening(true);
        setOpenError(null);

        try {
            const response = await fetch(documentUrl, { cache: 'no-store' });
            if (!response.ok) {
                setOpenError(await errorDetailFromResponse(response));
                return;
            }

            const blob = await response.blob();
            const blobUrl = URL.createObjectURL(blob);
            const contentType = response.headers.get('Content-Type') ?? '';
            const downloadName = filenameFromContentDisposition(
                response.headers.get('Content-Disposition'),
            ) || (matchedDocument ? getDocumentDisplayName(matchedDocument) : sourceFilename);

            const link = document.createElement('a');
            link.href = blobUrl;

            if (contentType.includes('pdf')) {
                link.target = '_blank';
                link.rel = 'noreferrer';
            } else {
                link.download = downloadName;
            }

            document.body.appendChild(link);
            link.click();
            link.remove();
            window.setTimeout(() => URL.revokeObjectURL(blobUrl), 30_000);
        } catch {
            setOpenError('Source document could not be opened. Please try again or re-sync documents for this tender.');
        } finally {
            setIsOpening(false);
        }
    };

    return (
        <div className="flex-1 min-h-0 overflow-y-auto bg-gray-950 p-5">
            <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-4 space-y-3">
                <div className="flex items-start gap-3">
                    <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
                    <div className="min-w-0">
                        <p className="text-[13px] font-semibold text-amber-300">
                            Source Preview Fallback
                        </p>
                        <p className="text-[12px] text-gray-400 leading-relaxed mt-1">
                            {message}
                        </p>
                    </div>
                </div>

                <div className="grid grid-cols-1 gap-2 text-[12px]">
                    <div className="rounded border border-gray-800 bg-gray-900/70 px-3 py-2">
                        <p className="text-[10px] uppercase tracking-wider text-gray-500">Source Filename</p>
                        <p className="text-gray-200 break-all mt-0.5">{sourceFilename}</p>
                    </div>
                    <div className="rounded border border-gray-800 bg-gray-900/70 px-3 py-2">
                        <p className="text-[10px] uppercase tracking-wider text-gray-500">Source Position</p>
                        <p className="text-gray-200 mt-0.5">{pageLabel}</p>
                    </div>
                </div>

                {openError && (
                    <div className="flex items-start gap-2 rounded border border-red-500/20 bg-red-500/8 px-3 py-2">
                        <AlertCircle className="w-3.5 h-3.5 text-red-400 shrink-0 mt-0.5" />
                        <p className="text-[12px] text-red-200 leading-relaxed">{openError}</p>
                    </div>
                )}

                {documentUrl && (
                    <button
                        type="button"
                        onClick={handleOpenDocument}
                        disabled={isOpening}
                        className="inline-flex items-center gap-2 rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-[12px] font-semibold text-gray-200 transition hover:border-indigo-400/50 hover:text-indigo-200"
                    >
                        {isOpening ? (
                            <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        ) : (
                            <Download className="w-3.5 h-3.5" />
                        )}
                        {isOpening ? 'Opening Source...' : 'Open or Download Source'}
                    </button>
                )}
            </div>
        </div>
    );
}


// ═══════════════════════════════════════════════════════════════
// Dynamic Compliance Results — Eligibility Audit Dashboard
// ═══════════════════════════════════════════════════════════════

function ComplianceResults({
    evaluation,
    analysisId,
    tenderId,
    acceptedNodeIds,
    onOverrideSealUpdated,
    hybridCompliance,
    contentHash,
    overrideSeal,
    selectedRequirementKey,
    onSelectRequirement,
}: {
    evaluation: DynamicEvaluation;
    analysisId: string | null;
    tenderId: string;
    acceptedNodeIds: string[];
    onOverrideSealUpdated: (seal: string | null, nodeIds: string[]) => void;
    hybridCompliance: HybridCompliancePayload | null;
    contentHash: string | null;
    overrideSeal: string | null;
    selectedRequirementKey: string | null;
    onSelectRequirement: (detail: RequirementMatchDetail) => void;
}) {
    // Use hybrid result for the verdict when available, fall back to legacy
    const uiVerdict = deriveUiVerdict(hybridCompliance, evaluation);
    const statusMessage = deriveStatusMessage(hybridCompliance, evaluation);
    const recordedObligations = hybridCompliance?.recorded_obligations ?? [];
    const recordedObligationCount = hybridCompliance?.recorded_obligations_count
        ?? recordedObligations.length
        ?? 0;

    const verdictColor = (v: string) => {
        if (v === 'SATISFIED') return 'text-emerald-400';
        if (v === 'FAILED') return 'text-red-400';
        return 'text-amber-400';
    };

    const verdictBg = (v: string) => {
        if (v === 'SATISFIED') return 'bg-emerald-500/10';
        if (v === 'FAILED') return 'bg-red-500/10';
        return 'bg-amber-500/10';
    };

    return (
        <div className="flex flex-col h-full bg-gray-950">
            {/* ── Verdict Banner ── */}
            <div
                className={clsx(
                    'px-5 py-4 border-b shrink-0',
                    verdictPanelClasses[uiVerdict.tone]
                )}
            >
                <div className="flex items-start gap-3">
                    <div
                        className={clsx(
                            'w-10 h-10 rounded-xl flex items-center justify-center shrink-0',
                            verdictIconClasses[uiVerdict.tone]
                        )}
                    >
                        {uiVerdict.tone === 'success' && (
                            <ShieldCheck className="w-5 h-5 text-emerald-400" />
                        )}
                        {uiVerdict.tone === 'review' && (
                            <AlertTriangle className="w-5 h-5 text-amber-400" />
                        )}
                        {uiVerdict.tone === 'danger' && (
                            <ShieldAlert className="w-5 h-5 text-red-400" />
                        )}
                        {uiVerdict.tone === 'pending' && (
                            <ShieldCheck className="w-5 h-5 text-gray-400" />
                        )}
                    </div>
                    <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                            <h2
                                className={clsx(
                                    'text-[15px] font-bold uppercase tracking-wide',
                                    verdictTextClasses[uiVerdict.tone]
                                )}
                            >
                                {uiVerdict.label}
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

            {hybridCompliance ? (
                <>
                    {/* ── Stats Bar — unified dashboard header ── */}
                    <div className="px-5 py-3 border-b border-gray-800/60 shrink-0">
                        <div className="grid grid-cols-4 gap-2">
                            <div className="rounded-lg bg-emerald-500/10 border border-emerald-500/15 px-3 py-2 text-center">
                                <p className="text-[18px] font-bold text-emerald-400">{hybridCompliance.satisfied_count}</p>
                                <p className="text-[10px] text-gray-500 uppercase tracking-wider">Satisfied</p>
                            </div>
                            <div className="rounded-lg bg-red-500/10 border border-red-500/15 px-3 py-2 text-center">
                                <p className="text-[18px] font-bold text-red-400">{hybridCompliance.failed_count}</p>
                                <p className="text-[10px] text-gray-500 uppercase tracking-wider">Failed</p>
                            </div>
                            <div className="rounded-lg bg-amber-500/10 border border-amber-500/15 px-3 py-2 text-center">
                                <p className="text-[18px] font-bold text-amber-400">{hybridCompliance.manual_review_count}</p>
                                <p className="text-[10px] text-gray-500 uppercase tracking-wider">Manual</p>
                            </div>
                            <div className="rounded-lg bg-gray-500/10 border border-gray-500/15 px-3 py-2 text-center">
                                <p className="text-[18px] font-bold text-gray-400">
                                    {recordedObligationCount || hybridCompliance.skipped_optional_count}
                                </p>
                                <p className="text-[10px] text-gray-500 uppercase tracking-wider">
                                    {recordedObligationCount ? 'Recorded' : 'Skipped'}
                                </p>
                            </div>
                        </div>
                    </div>

                    {/* ── Scrollable Results ── */}
                    <div className="flex-1 overflow-y-auto p-5 space-y-4">
                        {/* ── Failed Dealbreakers ── */}
                        {hybridCompliance.failed_dealbreakers.length > 0 && (
                            <div>
                                <p className="text-[11px] font-semibold uppercase tracking-wider text-red-400 mb-2">
                                    Dealbreaker Failures ({hybridCompliance.failed_dealbreakers.length})
                                </p>
                                <div className="space-y-2">
                                    {hybridCompliance.failed_dealbreakers.map((d, i) => (
                                        <MatchDetailCard
                                            key={i}
                                            detail={d}
                                            verdictColor={verdictColor}
                                            verdictBg={verdictBg}
                                            tenderId={tenderId}
                                            analysisId={analysisId}
                                            isOverridden={acceptedNodeIds.includes((d.taxonomy_node_id ?? `synth_${hashSnippet(d.raw_text_snippet)}`).toLowerCase())}
                                            onOverrideSealUpdated={onOverrideSealUpdated}
                                            isSelected={selectedRequirementKey === getRequirementKey(d)}
                                            onSelect={onSelectRequirement}
                                        />
                                    ))}
                                </div>
                            </div>
                        )}

                        {/* ── Manual Reviews Required ── */}
                        {hybridCompliance.manual_reviews_required.length > 0 && (
                            <div>
                                <p className="text-[11px] font-semibold uppercase tracking-wider text-amber-400 mb-2">
                                    Manual Review Required ({hybridCompliance.manual_reviews_required.length})
                                </p>
                                <div className="space-y-2">
                                    {hybridCompliance.manual_reviews_required.map((d, i) => (
                                        <MatchDetailCard
                                            key={i}
                                            detail={d}
                                            verdictColor={verdictColor}
                                            verdictBg={verdictBg}
                                            isSelected={selectedRequirementKey === getRequirementKey(d)}
                                            onSelect={onSelectRequirement}
                                        />
                                    ))}
                                </div>
                            </div>
                        )}

                        {/* ── Satisfied Requirements (collapsed by default) ── */}
                        {hybridCompliance.satisfied_requirements.length > 0 && (
                            <SatisfiedSection
                                items={hybridCompliance.satisfied_requirements}
                                selectedRequirementKey={selectedRequirementKey}
                                onSelectRequirement={onSelectRequirement}
                            />
                        )}

                        {recordedObligations.length > 0 && (
                            <SatisfiedSection
                                title="Recorded Obligations"
                                items={recordedObligations}
                                variant="recorded"
                                selectedRequirementKey={selectedRequirementKey}
                                onSelectRequirement={onSelectRequirement}
                            />
                        )}
                    </div>

                    {/* ── Cryptographic Audit Seal ── */}
                    {contentHash && (
                        <div className="px-5 py-2.5 border-t border-gray-800/60 bg-gray-900/40 shrink-0 space-y-1.5">
                            <p className="text-[11px] text-gray-300 flex items-center gap-1.5">
                                <Lock className="w-3 h-3 text-indigo-400 shrink-0" />
                                <span>Content Seal: SHA-256</span>{' '}
                                <span className="font-mono text-indigo-300 break-all">{contentHash}</span>
                            </p>
                            {overrideSeal && (
                                <p className="text-[11px] text-amber-300 flex items-center gap-1.5">
                                    <ShieldOff className="w-3 h-3 text-amber-400 shrink-0" />
                                    <span>Override Seal: SHA-256</span>{' '}
                                    <span className="font-mono text-amber-300 break-all">{overrideSeal}</span>
                                    <span className="ml-1 text-[9px] px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-400 font-semibold uppercase">
                                        {acceptedNodeIds.length} override{acceptedNodeIds.length !== 1 ? 's' : ''}
                                    </span>
                                </p>
                            )}
                        </div>
                    )}
                </>
            ) : (
                <div className="flex-1 overflow-y-auto p-5">
                    <div className="rounded-xl border border-gray-700/50 bg-gray-900/40 p-6 text-center">
                        <Cpu className="w-8 h-8 text-gray-600 mx-auto mb-2" />
                        <p className="text-[13px] text-gray-400">
                            Eligibility Audit data unavailable for this analysis.
                        </p>
                        <p className="text-[11px] text-gray-600 mt-1">
                            Re-run the analysis to generate the full eligibility audit report.
                        </p>
                    </div>
                </div>
            )}
        </div>
    );
}


function MatchDetailCard({
    detail,
    verdictColor,
    verdictBg,
    tenderId,
    analysisId,
    isOverridden,
    onOverrideSealUpdated,
    isSelected = false,
    onSelect,
}: {
    detail: RequirementMatchDetail;
    verdictColor: (v: string) => string;
    verdictBg: (v: string) => string;
    tenderId?: string;
    analysisId?: string | null;
    isOverridden?: boolean;
    onOverrideSealUpdated?: (seal: string | null, nodeIds: string[]) => void;
    isSelected?: boolean;
    onSelect?: (detail: RequirementMatchDetail) => void;
}) {
    const [showModal, setShowModal] = useState(false);
    // Compute a deterministic node ID — use taxonomy UUID when present,
    // otherwise generate a synthetic ID from the requirement text so
    // token-overlap matches can also be overridden.
    const nodeId = detail.taxonomy_node_id ?? `synth_${hashSnippet(detail.raw_text_snippet)}`;
    const isFatalFailed = detail.verdict === 'FAILED' && detail.is_dealbreaker;
    const canOverride = isFatalFailed && tenderId && analysisId && onOverrideSealUpdated && !isOverridden;
    const quote = detail.exact_quote || detail.raw_text_snippet;

    return (
        <>
            <div
                role="button"
                tabIndex={0}
                aria-pressed={isSelected}
                onClick={() => onSelect?.(detail)}
                onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        onSelect?.(detail);
                    }
                }}
                className={clsx(
                    'rounded-lg border px-3 py-2.5 space-y-1.5 border-l-2 cursor-pointer transition-all focus:outline-none focus:ring-2 focus:ring-indigo-500/40',
                    isSelected
                        ? 'border-indigo-400/60 border-l-indigo-400 bg-indigo-500/10 shadow-sm shadow-indigo-500/10'
                        : isOverridden
                            ? 'border-amber-500/20 border-l-amber-500/60 bg-amber-500/5 hover:border-amber-400/30'
                            : detail.verdict === 'FAILED'
                                ? 'border-gray-700/50 border-l-red-500/60 bg-gray-900/70 hover:border-red-400/30'
                                : 'border-gray-700/50 border-l-amber-500/50 bg-gray-900/70 hover:border-amber-400/30'
                )}
            >
                {detail.parent_section_header && (
                    <p className="flex items-center gap-1.5 text-[10px] text-gray-500 font-medium tracking-wide">
                        <FolderTree className="w-3 h-3 text-gray-600 shrink-0" />
                        <span className="truncate">{detail.parent_section_header}</span>
                    </p>
                )}
                <p className="flex flex-wrap items-center gap-2 text-[10px] text-gray-500 font-medium">
                    <span className="inline-flex items-center gap-1">
                        <FileSearch className="w-3 h-3 text-gray-600 shrink-0" />
                        <span>{detail.source_filename || 'source document'}</span>
                    </span>
                    <span>Page {detail.source_page || 1}</span>
                    <span className="px-1.5 py-0.5 rounded bg-gray-800/70 text-gray-400 uppercase">
                        {detail.category || detail.requirement_type}
                    </span>
                </p>
                <p className="text-[12px] text-gray-300 leading-relaxed">
                    {detail.headline || detail.raw_text_snippet}
                </p>
                <p className="text-[11px] text-gray-500 leading-relaxed">
                    Quote: <span>&quot;{quote}&quot;</span>
                </p>
                <div className="flex flex-wrap items-center gap-2 text-[10px]">
                    {isOverridden ? (
                        <span className="px-1.5 py-0.5 rounded font-bold uppercase tracking-wider bg-amber-500/15 text-amber-400">
                            Overridden
                        </span>
                    ) : (
                        <span className={clsx('px-1.5 py-0.5 rounded font-bold uppercase tracking-wider', verdictBg(detail.verdict), verdictColor(detail.verdict))}>
                            {detail.verdict}
                        </span>
                    )}
                    {detail.is_dealbreaker && !isOverridden && (
                        <span className="text-red-500 font-bold uppercase">Fatal</span>
                    )}
                    {isOverridden && (
                        <span className="flex items-center gap-1 text-amber-400">
                            <Fingerprint className="w-3 h-3" />
                            Override Sealed
                        </span>
                    )}
                </div>

                {/* Override System Flag Button — Hybrid Engine dealbreakers only */}
                {canOverride && (
                    <button
                        onClick={(event) => {
                            event.stopPropagation();
                            setShowModal(true);
                        }}
                        onKeyDown={(event) => event.stopPropagation()}
                        className="flex items-center gap-1.5 w-full mt-1.5 px-2.5 py-2 rounded-lg border border-amber-500/25 bg-amber-500/8 hover:bg-amber-500/15 hover:border-amber-400/40 hover:shadow-md hover:shadow-amber-500/10 transition-all duration-200 group"
                    >
                        <ShieldOff className="w-3.5 h-3.5 text-amber-400 group-hover:text-amber-300 group-hover:scale-110 transition-all" />
                        <span className="text-[11px] font-semibold text-amber-400 group-hover:text-amber-300 transition-colors">
                            Override System Flag
                        </span>
                        <span className="ml-auto text-[9px] text-gray-500 group-hover:text-gray-400 transition-colors">
                            Permanent audit record
                        </span>
                    </button>
                )}

                {/* Override Sealed Badge (after override) */}
                {isOverridden && isFatalFailed && (
                    <div className="flex items-center gap-1.5 px-2.5 py-2 rounded-lg bg-amber-500/10 border border-amber-500/20 mt-1.5">
                        <Fingerprint className="w-3.5 h-3.5 text-amber-400" />
                        <span className="text-[11px] font-semibold text-amber-400">
                            Override Sealed in Audit Trail
                        </span>
                    </div>
                )}
            </div>

            {/* Challenge Modal */}
            {showModal && tenderId && analysisId && onOverrideSealUpdated && (
                <OverrideChallengeModal
                    tenderId={tenderId}
                    analysisId={analysisId}
                    nodeId={nodeId}
                    requirementSnippet={detail.raw_text_snippet}
                    onClose={() => setShowModal(false)}
                    onOverrideComplete={(seal, nodeIds) => {
                        onOverrideSealUpdated(seal, nodeIds);
                        setShowModal(false);
                    }}
                />
            )}
        </>
    );
}


// ═══════════════════════════════════════════════════════════════
// Override Challenge Modal — Immutable Liability Handshake
// ═══════════════════════════════════════════════════════════════

function OverrideChallengeModal({
    tenderId,
    analysisId,
    nodeId,
    requirementSnippet,
    onClose,
    onOverrideComplete,
}: {
    tenderId: string;
    analysisId: string;
    nodeId: string;
    requirementSnippet: string;
    onClose: () => void;
    onOverrideComplete: (seal: string | null, nodeIds: string[]) => void;
}) {
    const [justification, setJustification] = useState('');
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const isValid = justification.trim().length >= 10;

    const handleSubmit = async () => {
        if (!isValid || isSubmitting) return;

        setIsSubmitting(true);
        setError(null);

        try {
            const { data } = await api.post<OverrideResponse>(`/tenders/${tenderId}/override`, {
                node_id: nodeId,
                analysis_id: analysisId,
                justification: justification.trim(),
            });
            onOverrideComplete(data.override_seal, data.overridden_node_ids);
        } catch (err: unknown) {
            const axiosErr = err as { response?: { data?: { detail?: string } } };
            setError(
                axiosErr?.response?.data?.detail ||
                (err instanceof Error ? err.message : 'Override failed')
            );
        } finally {
            setIsSubmitting(false);
        }
    };

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            {/* Backdrop */}
            <div
                className="absolute inset-0 bg-black/70 backdrop-blur-sm"
                onClick={onClose}
            />

            {/* Modal */}
            <div className="relative w-full max-w-lg rounded-2xl border border-red-500/20 bg-gray-950/95 backdrop-blur-xl shadow-2xl shadow-red-500/5 overflow-hidden">
                {/* Header */}
                <div className="px-6 pt-6 pb-4 border-b border-red-500/15 bg-red-500/5">
                    <div className="flex items-start gap-3">
                        <div className="w-10 h-10 rounded-xl bg-red-500/15 flex items-center justify-center shrink-0">
                            <ShieldOff className="w-5 h-5 text-red-400" />
                        </div>
                        <div className="flex-1 min-w-0">
                            <h3 className="text-[15px] font-bold text-red-300 uppercase tracking-wide">
                                Override System Flag
                            </h3>
                            <p className="text-[12px] text-gray-400 mt-1 leading-relaxed">
                                You are about to override a <span className="text-red-400 font-bold">FATAL</span> compliance requirement.
                                This action will be <span className="text-amber-400 font-semibold">permanently sealed</span> in the cryptographic audit trail and cannot be undone.
                            </p>
                        </div>
                        <button
                            onClick={onClose}
                            className="text-gray-500 hover:text-gray-300 transition-colors p-1"
                        >
                            <X className="w-4 h-4" />
                        </button>
                    </div>
                </div>

                {/* Requirement being overridden */}
                <div className="px-6 py-3 bg-gray-900/60 border-b border-gray-800/50">
                    <p className="text-[10px] uppercase tracking-wider text-gray-500 font-semibold mb-1">
                        Requirement Being Overridden
                    </p>
                    <p className="text-[12px] text-gray-300 leading-relaxed line-clamp-3">
                        {requirementSnippet}
                    </p>
                </div>

                {/* Body */}
                <div className="px-6 py-5 space-y-4">
                    {/* Warning */}
                    <div className="flex items-start gap-2.5 px-3.5 py-3 rounded-lg border border-amber-500/20 bg-amber-500/5">
                        <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
                        <div className="text-[11px] text-gray-300 leading-relaxed space-y-1">
                            <p className="font-semibold text-amber-300">Liability Transfer Warning</p>
                            <p>
                                By overriding this flag, you certify that you possess offline context
                                (e.g., a physical waiver, verbal authorization, or supplementary documentation)
                                that the AI system cannot access. Full liability transfers to you.
                            </p>
                        </div>
                    </div>

                    {/* Justification Input */}
                    <div>
                        <label
                            htmlFor="override-justification"
                            className="block text-[11px] font-semibold uppercase tracking-wider text-gray-400 mb-1.5"
                        >
                            Justification <span className="text-red-400">*</span>
                        </label>
                        <textarea
                            id="override-justification"
                            value={justification}
                            onChange={(e) => setJustification(e.target.value)}
                            placeholder="State why you are overriding this requirement (min. 10 characters)..."
                            rows={3}
                            className={clsx(
                                'w-full rounded-lg border bg-gray-900/80 px-3.5 py-2.5 text-[13px] text-gray-200 placeholder-gray-600',
                                'focus:outline-none focus:ring-2 transition-all resize-none',
                                justification.length > 0 && !isValid
                                    ? 'border-red-500/30 focus:ring-red-500/30'
                                    : 'border-gray-700 focus:ring-indigo-500/30 focus:border-indigo-500/30'
                            )}
                        />
                        <div className="flex items-center justify-between mt-1.5">
                            <p className={clsx(
                                'text-[10px]',
                                justification.length > 0 && !isValid ? 'text-red-400' : 'text-gray-600'
                            )}>
                                {justification.trim().length}/10 minimum characters
                            </p>
                            {justification.trim().length >= 10 && (
                                <p className="text-[10px] text-emerald-400 flex items-center gap-1">
                                    <CheckCircle2 className="w-3 h-3" /> Valid
                                </p>
                            )}
                        </div>
                    </div>

                    {/* Error */}
                    {error && (
                        <div className="flex items-start gap-2 px-3 py-2 rounded-lg border border-red-500/20 bg-red-500/5">
                            <AlertCircle className="w-3.5 h-3.5 text-red-400 shrink-0 mt-0.5" />
                            <p className="text-[11px] text-red-300">{error}</p>
                        </div>
                    )}
                </div>

                {/* Footer */}
                <div className="px-6 py-4 border-t border-gray-800/50 bg-gray-900/40 flex items-center gap-3">
                    <button
                        onClick={onClose}
                        disabled={isSubmitting}
                        className="flex-1 px-4 py-2.5 rounded-lg border border-gray-700 bg-gray-800/60 text-[13px] font-medium text-gray-300 hover:bg-gray-700/60 hover:text-gray-100 transition-all disabled:opacity-50"
                    >
                        Cancel
                    </button>
                    <button
                        onClick={handleSubmit}
                        disabled={!isValid || isSubmitting}
                        className={clsx(
                            'flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg text-[13px] font-semibold transition-all',
                            isValid && !isSubmitting
                                ? 'bg-red-600 hover:bg-red-500 text-white shadow-lg shadow-red-500/20'
                                : 'bg-gray-800 text-gray-500 cursor-not-allowed'
                        )}
                    >
                        {isSubmitting ? (
                            <>
                                <Loader2 className="w-4 h-4 animate-spin" />
                                Sealing Override...
                            </>
                        ) : (
                            <>
                                <Fingerprint className="w-4 h-4" />
                                Seal Override
                            </>
                        )}
                    </button>
                </div>

                {/* Seal Notice */}
                <div className="px-6 py-2 bg-gray-950/80 border-t border-gray-800/30">
                    <p className="text-[9px] text-gray-600 text-center">
                        This override will be cryptographically sealed with SHA-256 and permanently recorded in the audit ledger.
                    </p>
                </div>
            </div>
        </div>
    );
}


function SatisfiedSection({
    title = 'Satisfied Requirements',
    items,
    variant = 'satisfied',
    selectedRequirementKey,
    onSelectRequirement,
}: {
    title?: string;
    items: RequirementMatchDetail[];
    variant?: 'satisfied' | 'recorded';
    selectedRequirementKey: string | null;
    onSelectRequirement: (detail: RequirementMatchDetail) => void;
}) {
    const [showSatisfied, setShowSatisfied] = useState(false);
    const isRecorded = variant === 'recorded';
    const Icon = isRecorded ? ClipboardList : CheckCircle2;
    const titleClass = isRecorded
        ? 'text-amber-400 hover:text-amber-300'
        : 'text-emerald-400 hover:text-emerald-300';
    const itemClass = isRecorded
        ? 'border-amber-500/10 bg-gray-900/40'
        : 'border-emerald-500/10 bg-gray-900/40';
    const iconClass = isRecorded ? 'text-amber-400' : 'text-emerald-400';

    return (
        <div>
            <button
                onClick={() => setShowSatisfied(!showSatisfied)}
                className={clsx(
                    'flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider transition-colors',
                    titleClass,
                )}
            >
                <Icon className="w-3.5 h-3.5" />
                {title} ({items.length})
                <span className="text-gray-600 normal-case font-normal ml-1">
                    {showSatisfied ? '▾ hide' : '▸ show'}
                </span>
            </button>
            {showSatisfied && (
                <div className="mt-2 space-y-1.5">
                    {items.map((d, i) => {
                        const isSelected = selectedRequirementKey === getRequirementKey(d);

                        return (
                            <div
                                key={i}
                                role="button"
                                tabIndex={0}
                                aria-pressed={isSelected}
                                onClick={() => onSelectRequirement(d)}
                                onKeyDown={(event) => {
                                    if (event.key === 'Enter' || event.key === ' ') {
                                        event.preventDefault();
                                        onSelectRequirement(d);
                                    }
                                }}
                                className={clsx(
                                    'flex items-start gap-2 rounded-lg border px-3 py-2 cursor-pointer transition-all focus:outline-none focus:ring-2 focus:ring-indigo-500/40',
                                    isSelected
                                        ? 'border-indigo-400/60 bg-indigo-500/10 shadow-sm shadow-indigo-500/10'
                                        : itemClass,
                                )}
                            >
                                <Icon className={clsx('w-3.5 h-3.5 shrink-0 mt-0.5', isSelected ? 'text-indigo-300' : iconClass)} />
                                <div className="min-w-0 flex-1">
                                    {d.parent_section_header && (
                                        <p className="flex items-center gap-1 text-[9px] text-gray-500 font-medium tracking-wide mb-0.5">
                                            <FolderTree className="w-2.5 h-2.5 text-gray-600 shrink-0" />
                                            <span className="truncate">{d.parent_section_header}</span>
                                        </p>
                                    )}
                                    <p className="flex flex-wrap items-center gap-1.5 text-[9px] text-gray-500 font-medium mb-0.5">
                                        <FileSearch className="w-2.5 h-2.5 text-gray-600 shrink-0" />
                                        <span className="truncate">{d.source_filename || 'source document'}</span>
                                        <span>Page {d.source_page || 1}</span>
                                        <span className="uppercase">{d.category || d.requirement_type}</span>
                                    </p>
                                    <p className="text-[11px] text-gray-300 leading-relaxed truncate">
                                        {d.headline || d.raw_text_snippet}
                                    </p>
                                    <p className="text-[10px] text-gray-500 mt-0.5 truncate">
                                        Quote: <span>&quot;{d.exact_quote || d.raw_text_snippet}&quot;</span>
                                    </p>
                                    {d.matched_credential && (
                                        <p className="text-[10px] text-cyan-400/60 mt-0.5">
                                            {d.matched_credential}
                                        </p>
                                    )}
                                </div>
                            </div>
                        );
                    })}
                </div>
            )}
        </div>
    );
}
