'use client';

import { use, useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import {
    AlertCircle,
    ArrowLeft,
    Building2,
    Calendar,
    CheckCircle2,
    CircleDollarSign,
    Download,
    ExternalLink,
    FileSearch,
    FileText,
    Globe2,
    Info,
    Loader2,
    Mail,
    MapPin,
    Phone,
    Send,
    ShieldCheck,
    UserRound,
    UsersRound,
} from 'lucide-react';

import { api } from '@/lib/api';
import { ProjectContextSection } from '@/components/tenders/ProjectContextSection';
import {
    classifyProjectContextFailure,
    type TenderProjectContext,
} from '@/types/project';
import type { Tender, TenderCompetitorIntelligence, TenderDecisionSnapshot, TenderDocument } from '@/types/tender';
import {
    availabilityClasses,
    competitorStatusLabel,
    competitorConfidenceClasses,
    competitorConfidenceLabel,
    competitorParticipationLabel,
    complianceUnavailableMessage,
    contactAvailabilityLabel,
    deadlineUrgencyClasses,
    deadlineUrgencyLabel,
    documentAggregateLabel,
    documentStatusClasses,
    isTenderActionable,
    sourceBadgeClasses,
    sourceLabel,
    tenderActionabilityMessage,
    tenderStatusClasses,
    tenderStatusLabel,
} from '@/types/tender';

type TenderSyncState = 'IDLE' | 'PENDING' | 'IN_PROGRESS' | 'SUCCESS' | 'FAILED';
type HydrationStage = 'queued' | 'downloading' | 'processing' | 'complete' | 'partial' | 'failed';
const EXPLORER_RESTORE_KEY = 'plasmaos:tender-explorer:return';
const EXPLORER_FALLBACK_HREF = '/dashboard/tenders';

interface TenderSyncStatusResponse {
    state: TenderSyncState;
    progress: number;
    docs_parsed: number;
    error: string | null;
    source_system?: string | null;
    coverage_status?: string | null;
}

interface GizHydrateJobResponse {
    external_id: string;
    tender_id: string;
    job_id: string;
    status: TenderSyncState;
    progress: number;
    queued: boolean;
    message: string;
}

interface GizHydrateAcceptedResponse {
    jobs: GizHydrateJobResponse[];
}

const wait = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms));

function formatDate(value: string | null) {
    if (!value) return 'Unknown';
    return new Date(value).toLocaleDateString('en-US', {
        month: 'long',
        day: 'numeric',
        year: 'numeric',
    });
}

function timeRemaining(deadline: string | null) {
    if (!deadline) return 'Unknown deadline';
    const daysLeft = Math.ceil((new Date(deadline).getTime() - Date.now()) / (1000 * 60 * 60 * 24));
    if (daysLeft < 0) return 'Expired';
    if (daysLeft === 0) return 'Due today';
    if (daysLeft === 1) return '1 day remaining';
    return `${daysLeft} days remaining`;
}

function safeField(value: string | null | undefined) {
    return value && value.trim() ? value : 'Not specified';
}

function contactField(value: string | null | undefined) {
    return value && value.trim() ? value : 'Not provided in source metadata';
}

function accessNotes(value: string | null | undefined) {
    return value && value.trim() ? value : 'Open source notice for full details';
}

function contactDate(value: string | null | undefined) {
    return value ? formatDate(value) : 'Not provided in source metadata';
}

function sourceHost(value: string | null | undefined) {
    if (!value) return 'Open source notice for full details';
    try {
        return new URL(value).hostname.replace(/^www\./, '');
    } catch {
        return 'Source notice';
    }
}

function priceDisplay(tender: Tender) {
    if (tender.price_display) return tender.price_display;
    if (typeof tender.budget === 'number' && tender.budget > 0) {
        const amount = tender.budget.toLocaleString('en-US', {
            maximumFractionDigits: 2,
        });
        return `${amount}${tender.currency ? ` ${tender.currency}` : ''}`;
    }
    return 'Price not specified';
}

function snapshotPriceDisplay(snapshot: TenderDecisionSnapshot) {
    if (snapshot.price_display) return snapshot.price_display;
    if (typeof snapshot.price_amount === 'number' && snapshot.price_amount > 0) {
        const amount = snapshot.price_amount.toLocaleString('en-US', {
            maximumFractionDigits: 2,
        });
        return `${amount}${snapshot.price_currency ? ` ${snapshot.price_currency}` : ''}`;
    }
    return 'Price not specified';
}

function snapshotCountryRegion(snapshot: TenderDecisionSnapshot) {
    const country = safeField(snapshot.country);
    const region = safeField(snapshot.region);
    if (country === 'Not specified' && region === 'Not specified') return 'Not specified';
    if (country === 'Not specified') return region;
    if (region === 'Not specified') return country;
    return `${country} / ${region}`;
}

function snapshotDocumentLabel(snapshot: TenderDecisionSnapshot) {
    return documentAggregateLabel(snapshot);
}

function snapshotComplianceLabel(snapshot: TenderDecisionSnapshot) {
    if (snapshot.compliance_availability === 'available') return 'Ready for analysis';
    if (snapshot.document_status === 'metadata_only') return 'Metadata only';
    if (snapshot.document_status === 'access_required') return 'Access required';
    return 'Documents required';
}

function SnapshotChip({
    icon,
    label,
    value,
    badge,
    badgeClasses,
}: {
    icon: ReactNode;
    label: string;
    value: string;
    badge?: string;
    badgeClasses?: string;
}) {
    return (
        <div className="inline-flex min-h-[68px] min-w-0 items-center gap-3 rounded-md border border-zinc-800 bg-zinc-900/70 px-3 py-2">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-zinc-700 bg-gray-950 text-zinc-300">
                {icon}
            </div>
            <div className="min-w-0 flex-1">
                <p className="text-[11px] font-semibold uppercase text-zinc-500">{label}</p>
                <p className="mt-1 truncate text-sm font-medium text-zinc-100">{value}</p>
                {badge ? (
                    <span className={`mt-1 inline-flex max-w-full rounded-md border px-2 py-0.5 text-[11px] font-semibold ${badgeClasses ?? 'border-zinc-700 bg-zinc-800/60 text-zinc-400'}`}>
                        <span className="truncate">{badge}</span>
                    </span>
                ) : null}
            </div>
        </div>
    );
}

function filenameForDocument(doc: TenderDocument) {
    return doc.display_name || doc.original_filename || (doc.file_type ? `document.${doc.file_type}` : 'document');
}

function documentExtension(doc: TenderDocument) {
    const filename = filenameForDocument(doc).split('?')[0].split('#')[0];
    const extension = filename.includes('.') ? filename.split('.').pop() : doc.file_type;
    return (extension || '').trim().toLowerCase();
}

function isUnsupportedDocument(doc: TenderDocument) {
    return ['doc', 'xls', 'xlsx', 'rtf', 'rar', '7z', 'tar', 'gz'].includes(documentExtension(doc));
}

function downloadStatusText(doc: TenderDocument) {
    if (doc.analysis_text_available) return 'Ready for analysis';
    if (doc.download_status === 'processing') return 'Processing';
    if (doc.download_status === 'metadata_only' || doc.download_status === 'access_required') return 'Document discovered';
    if (doc.download_status === 'missing_file') return 'Preparation failed';
    if (doc.download_status === 'failed' && isUnsupportedDocument(doc)) return 'Unsupported format';
    if (doc.download_status === 'failed') return 'Preparation failed';
    if (doc.download_status === 'available') return 'Document discovered';
    return 'Document discovered';
}

function downloadStatusClasses(doc: TenderDocument) {
    if (doc.analysis_text_available) return 'text-emerald-300';
    if (doc.download_status === 'processing') return 'text-indigo-300';
    if (doc.download_status === 'failed' && isUnsupportedDocument(doc)) return 'text-amber-300';
    if (doc.download_status === 'failed' || doc.download_status === 'missing_file') return 'text-red-300';
    return 'text-amber-300';
}

function documentAggregateSummary(tender: Tender) {
    const parts = [`${tender.document_count} captured records`];
    parts.push(`${tender.downloadable_document_count ?? tender.available_document_count} downloadable`);
    if (tender.missing_file_document_count > 0) {
        parts.push(`${tender.missing_file_document_count} need preparation`);
    }
    if (tender.parsed_document_count > 0 || tender.has_compiled_text) {
        parts.push('analysis text available');
    }
    return `${parts.join(', ')}.`;
}

function hydrationStageFromStatus(status: TenderSyncStatusResponse): HydrationStage {
    const coverage = (status.coverage_status || '').toLowerCase();
    if (status.state === 'PENDING') return 'queued';
    if (status.state === 'IN_PROGRESS') return status.progress < 60 ? 'downloading' : 'processing';
    if (status.state === 'SUCCESS') return coverage === 'partial' ? 'partial' : 'complete';
    if (status.state === 'FAILED') return 'failed';
    if (status.docs_parsed > 0) return coverage === 'partial' ? 'partial' : 'complete';
    return 'queued';
}

function hydrationStageLabel(stage: HydrationStage | null) {
    if (stage === 'queued') return 'queued';
    if (stage === 'downloading') return 'downloading';
    if (stage === 'processing') return 'processing';
    if (stage === 'complete') return 'complete';
    if (stage === 'partial') return 'partial coverage';
    if (stage === 'failed') return 'failed';
    return 'queued';
}

export default function TenderDetailPage({ params }: { params: Promise<{ tenderId: string }> }) {
    const router = useRouter();
    const { tenderId } = use(params);
    const [returnHref, setReturnHref] = useState(EXPLORER_FALLBACK_HREF);
    const [tender, setTender] = useState<Tender | null>(null);
    const [decisionSnapshot, setDecisionSnapshot] = useState<TenderDecisionSnapshot | null>(null);
    const [documents, setDocuments] = useState<TenderDocument[]>([]);
    const [competitorIntel, setCompetitorIntel] = useState<TenderCompetitorIntelligence | null>(null);
    const [projectContext, setProjectContext] = useState<TenderProjectContext | null>(null);
    const [isLoading, setIsLoading] = useState(true);
    const [isLoadingSnapshot, setIsLoadingSnapshot] = useState(true);
    const [isLoadingDocuments, setIsLoadingDocuments] = useState(true);
    const [isLoadingCompetitors, setIsLoadingCompetitors] = useState(true);
    const [isLoadingProject, setIsLoadingProject] = useState(true);
    const [openingDocId, setOpeningDocId] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [snapshotError, setSnapshotError] = useState<string | null>(null);
    const [documentError, setDocumentError] = useState<string | null>(null);
    const [competitorError, setCompetitorError] = useState<string | null>(null);
    const [projectContextFailed, setProjectContextFailed] = useState(false);
    const [isPreparingDocuments, setIsPreparingDocuments] = useState(false);
    const [prepareProgress, setPrepareProgress] = useState(0);
    const [prepareStage, setPrepareStage] = useState<HydrationStage | null>(null);
    const [prepareError, setPrepareError] = useState<string | null>(null);

    useEffect(() => {
        const rawState = window.sessionStorage.getItem(EXPLORER_RESTORE_KEY);
        if (!rawState) return;

        try {
            const explorerUrl = JSON.parse(rawState)?.explorerUrl;
            if (typeof explorerUrl === 'string' && explorerUrl.startsWith(EXPLORER_FALLBACK_HREF)) {
                setReturnHref(explorerUrl);
            }
        } catch {
            window.sessionStorage.removeItem(EXPLORER_RESTORE_KEY);
        }
    }, []);

    const loadTender = useCallback(async ({ silent = false }: { silent?: boolean } = {}) => {
        if (!silent) {
            setIsLoading(true);
            setError(null);
        }
        try {
            const { data } = await api.get<Tender>(`/tenders/${tenderId}`);
            setTender(data);
            return data;
        } catch (err) {
            const axiosErr = err as { response?: { data?: { detail?: string } } };
            setError(axiosErr.response?.data?.detail || 'Tender could not be loaded.');
            throw err;
        } finally {
            if (!silent) setIsLoading(false);
        }
    }, [tenderId]);

    const loadDecisionSnapshot = useCallback(async ({ silent = false }: { silent?: boolean } = {}) => {
        if (!silent) {
            setIsLoadingSnapshot(true);
            setSnapshotError(null);
        }
        try {
            const { data } = await api.get<TenderDecisionSnapshot>(`/tenders/${tenderId}/decision-snapshot`);
            setDecisionSnapshot(data);
            return data;
        } catch (err) {
            const axiosErr = err as { response?: { data?: { detail?: string } } };
            setDecisionSnapshot(null);
            setSnapshotError(axiosErr.response?.data?.detail || 'Decision snapshot could not be loaded.');
            throw err;
        } finally {
            if (!silent) setIsLoadingSnapshot(false);
        }
    }, [tenderId]);

    const loadDocuments = useCallback(async ({ silent = false }: { silent?: boolean } = {}) => {
        if (!silent) {
            setIsLoadingDocuments(true);
            setDocumentError(null);
        }
        try {
            const { data } = await api.get<TenderDocument[]>(`/tenders/${tenderId}/documents`);
            const nextDocuments = Array.isArray(data) ? data : [];
            setDocuments(nextDocuments);
            return nextDocuments;
        } catch (err) {
            const axiosErr = err as { response?: { data?: { detail?: string } } };
            setDocuments([]);
            setDocumentError(axiosErr.response?.data?.detail || 'Document metadata could not be loaded.');
            throw err;
        } finally {
            if (!silent) setIsLoadingDocuments(false);
        }
    }, [tenderId]);

    const loadCompetitors = useCallback(async () => {
        setIsLoadingCompetitors(true);
        setCompetitorError(null);
        try {
            const { data } = await api.get<TenderCompetitorIntelligence>(`/tenders/${tenderId}/competitors`);
            setCompetitorIntel(data);
        } catch (err) {
            const axiosErr = err as { response?: { data?: { detail?: string } } };
            setCompetitorIntel(null);
            setCompetitorError(axiosErr.response?.data?.detail || 'Competitor intelligence could not be loaded.');
        } finally {
            setIsLoadingCompetitors(false);
        }
    }, [tenderId]);

    const loadProjectContext = useCallback(async () => {
        setIsLoadingProject(true);
        setProjectContextFailed(false);
        try {
            const { data } = await api.get<TenderProjectContext | null>(`/tenders/${tenderId}/project`);
            setProjectContext(data ?? null);
        } catch (error) {
            const status = (error as { response?: { status?: number } }).response?.status;
            const failureKind = classifyProjectContextFailure(status);
            setProjectContext(null);
            setProjectContextFailed(failureKind === 'endpoint_failure');
        } finally {
            setIsLoadingProject(false);
        }
    }, [tenderId]);

    const fetchTenderSyncStatus = useCallback(async () => {
        const { data } = await api.get<TenderSyncStatusResponse>(`/tenders/${tenderId}/sync-status`);
        return data;
    }, [tenderId]);

    const refreshTenderAnalysisState = useCallback(async () => {
        await Promise.allSettled([
            loadTender({ silent: true }),
            loadDecisionSnapshot({ silent: true }),
            loadDocuments({ silent: true }),
        ]);
    }, [loadDecisionSnapshot, loadDocuments, loadTender]);

    const pollGizHydration = useCallback(async () => {
        for (let attempt = 0; attempt < 80; attempt += 1) {
            const status = await fetchTenderSyncStatus();
            const stage = hydrationStageFromStatus(status);
            setPrepareStage(stage);
            setPrepareProgress(status.progress);

            if (status.state === 'SUCCESS') {
                await refreshTenderAnalysisState();
                return;
            }

            if (status.state === 'FAILED') {
                throw new Error(status.error || 'Document preparation failed.');
            }

            if (attempt > 0 && status.progress >= 60) {
                await loadDocuments({ silent: true }).catch(() => undefined);
            }

            await wait(3000);
        }

        throw new Error('Document preparation is taking longer than expected. Reload this page in a minute.');
    }, [fetchTenderSyncStatus, loadDocuments, refreshTenderAnalysisState]);

    useEffect(() => {
        let isActive = true;

        loadTender().catch(() => undefined).finally(() => {
            if (!isActive) return;
        });

        return () => {
            isActive = false;
        };
    }, [loadTender]);

    useEffect(() => {
        let isActive = true;

        loadDecisionSnapshot().catch(() => undefined).finally(() => {
            if (!isActive) return;
        });

        return () => {
            isActive = false;
        };
    }, [loadDecisionSnapshot]);

    useEffect(() => {
        let isActive = true;

        loadDocuments().catch(() => undefined).finally(() => {
            if (!isActive) return;
        });

        return () => {
            isActive = false;
        };
    }, [loadDocuments]);

    useEffect(() => {
        let isActive = true;

        loadCompetitors().finally(() => {
            if (!isActive) return;
        });

        return () => {
            isActive = false;
        };
    }, [loadCompetitors]);

    useEffect(() => {
        let isActive = true;

        loadProjectContext().finally(() => {
            if (!isActive) return;
        });

        return () => {
            isActive = false;
        };
    }, [loadProjectContext]);

    const handlePrepareGizDocuments = useCallback(async () => {
        if (!tender || tender.source_system !== 'giz' || isPreparingDocuments) return;

        setIsPreparingDocuments(true);
        setPrepareError(null);
        setDocumentError(null);
        setPrepareStage('queued');
        setPrepareProgress(0);

        try {
            const response = await api.post<GizHydrateAcceptedResponse>('/tenders/sources/giz/hydrate', {
                external_ids: [tender.external_id],
                force: false,
            });
            const job = response.data.jobs.find((item) => item.external_id === tender.external_id) ?? response.data.jobs[0];
            if (job) {
                setPrepareProgress(job.progress);
                setPrepareStage(
                    job.status === 'PENDING'
                        ? 'queued'
                        : job.status === 'IN_PROGRESS'
                            ? 'downloading'
                            : job.status === 'FAILED'
                                ? 'failed'
                                : 'complete',
                );
                if (job.status === 'FAILED') {
                    throw new Error(job.message || 'Document preparation failed.');
                }
            }
            await pollGizHydration();
        } catch (err) {
            const axiosErr = err as { response?: { data?: { detail?: string | { message?: string } } } };
            const detail = axiosErr.response?.data?.detail;
            const detailMessage = typeof detail === 'string' ? detail : detail?.message;
            setPrepareStage('failed');
            setPrepareError(
                detailMessage ||
                (err instanceof Error ? err.message : null) ||
                'Document preparation failed.',
            );
        } finally {
            setIsPreparingDocuments(false);
        }
    }, [isPreparingDocuments, pollGizHydration, tender]);

    const actionable = isTenderActionable(tender);
    const canAnalyze = actionable && Boolean(tender?.compliance_analysis_available);
    const unavailableMessage = useMemo(
        () => tender
            ? actionable
                ? complianceUnavailableMessage(tender)
                : tenderActionabilityMessage(tender.status)
            : 'Prepare documents for analysis',
        [actionable, tender],
    );
    const isPreparationTerminal = prepareStage === 'complete' || prepareStage === 'partial' || prepareStage === 'failed';
    const showPreparationBanner = Boolean(
        tender?.document_status === 'processing' ||
        isPreparingDocuments ||
        prepareStage,
    );
    const contact = tender?.contact_submission ?? null;
    const contactSourceUrl = contact?.source_url || tender?.source_url || null;
    const competitorGroups = competitorIntel?.groups ?? [];
    const projectFallbackIdentity = (
        (isLoadingProject || projectContextFailed) &&
        tender?.source_system === 'world_bank' &&
        tender.project_id
    ) ? {
            sourceSystem: tender.source_system,
            externalProjectId: tender.project_id,
        } : null;

    const handleOpenDocument = useCallback(async (doc: TenderDocument) => {
        if (doc.download_status !== 'available' || openingDocId) return;
        setOpeningDocId(doc.id);
        setDocumentError(null);

        try {
            const response = await api.get(`/tenders/documents/${doc.id}/download`, {
                responseType: 'blob',
            });
            const contentType = response.headers['content-type'] || 'application/octet-stream';
            const blob = new Blob([response.data], { type: contentType });
            const url = URL.createObjectURL(blob);

            const link = document.createElement('a');
            link.href = url;
            if (contentType.includes('pdf')) {
                link.target = '_blank';
                link.rel = 'noreferrer';
            } else {
                link.download = filenameForDocument(doc);
            }
            document.body.appendChild(link);
            link.click();
            link.remove();
            window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
        } catch (err) {
            const axiosErr = err as { response?: { data?: { detail?: string } } };
            setDocumentError(axiosErr.response?.data?.detail || 'Document could not be opened from Plasma storage.');
        } finally {
            setOpeningDocId(null);
        }
    }, [openingDocId]);

    if (isLoading) {
        return (
            <div className="flex h-64 items-center justify-center">
                <Loader2 className="h-7 w-7 animate-spin text-indigo-400" />
            </div>
        );
    }

    if (error || !tender) {
        return (
            <div className="space-y-4">
                <Link href={returnHref} className="inline-flex items-center gap-2 text-sm text-zinc-400 hover:text-zinc-200">
                    <ArrowLeft className="h-4 w-4" />
                    Back to tenders
                </Link>
                <div className="rounded-lg border border-red-500/20 bg-red-500/10 p-4 text-sm text-red-200">
                    {error || 'Tender not found.'}
                </div>
            </div>
        );
    }

    return (
        <div className="space-y-5">
            <div className="flex items-center justify-between gap-4">
                <Link href={returnHref} className="inline-flex items-center gap-2 text-sm text-zinc-400 hover:text-zinc-200">
                    <ArrowLeft className="h-4 w-4" />
                    Back to tenders
                </Link>
                <div className="flex items-center gap-2">
                    {tender.source_url && (
                        <a
                            href={tender.source_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-2 rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-xs font-semibold text-zinc-200 transition hover:border-indigo-500 hover:text-indigo-200"
                        >
                            <ExternalLink className="h-3.5 w-3.5" />
                            Open source notice
                        </a>
                    )}
                    <button
                        onClick={() => router.push(`/dashboard/tenders/${tender.id}/compliance`)}
                        disabled={!canAnalyze}
                        title={!canAnalyze ? unavailableMessage : 'Open compliance analysis'}
                        className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-3 py-2 text-xs font-semibold text-white transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:bg-zinc-800 disabled:text-zinc-500"
                    >
                        <ShieldCheck className="h-3.5 w-3.5" />
                        Compliance
                    </button>
                </div>
            </div>

            <section className="rounded-lg border border-gray-800 bg-gray-950 p-5">
                <div className="mb-4 flex flex-wrap items-center gap-2">
                    <span className={`inline-flex rounded-md border px-2 py-1 text-xs font-semibold ${sourceBadgeClasses(tender.source_system)}`}>
                        {sourceLabel(tender.source_system)}
                    </span>
                    <span className={`inline-flex rounded-md border px-2 py-1 text-xs font-semibold ${tenderStatusClasses(tender.status)}`}>
                        {tenderStatusLabel(tender.status)}
                    </span>
                    <span className={`inline-flex rounded-md border px-2 py-1 text-xs font-semibold ${documentStatusClasses(tender.document_status)}`}>
                        {documentAggregateLabel(tender)}
                    </span>
                    {!canAnalyze && (
                        <span className="inline-flex rounded-md border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-xs font-semibold text-amber-300">
                            {unavailableMessage}
                        </span>
                    )}
                </div>
                <h1 className="text-2xl font-bold leading-snug text-white">{tender.title}</h1>
                <p className="mt-2 max-w-4xl text-sm leading-6 text-zinc-400">{tender.description || 'No source description provided.'}</p>
            </section>

            {/* <section className="rounded-lg border border-zinc-800 bg-gray-950 p-4 shadow-[0_0_0_1px_rgba(16,185,129,0.06)]">
                <div className="mb-3 flex items-center justify-between gap-3">
                    <div className="flex items-center gap-2">
                        <ShieldCheck className="h-4 w-4 text-emerald-300" />
                        <h2 className="text-lg font-semibold text-white">Decision Snapshot</h2>
                    </div>
                    {isLoadingSnapshot ? (
                        <span className="inline-flex items-center gap-2 text-xs text-zinc-500">
                            <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            Loading
                        </span>
                    ) : null}
                </div>

                {snapshotError ? (
                    <div className="flex items-center gap-2 rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-2 text-sm text-red-200">
                        <AlertCircle className="h-4 w-4" />
                        {snapshotError}
                    </div>
                ) : isLoadingSnapshot ? (
                    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
                        {Array.from({ length: 9 }).map((_, index) => (
                            <div key={index} className="h-[68px] rounded-md border border-zinc-800 bg-zinc-900/50" />
                        ))}
                    </div>
                ) : decisionSnapshot ? (
                    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
                        <SnapshotChip
                            icon={<Globe2 className="h-4 w-4" />}
                            label="Source"
                            value={sourceLabel(decisionSnapshot.source)}
                            badge={decisionSnapshot.source_notice_available ? 'Source notice available' : 'Source notice missing'}
                            badgeClasses={availabilityClasses(decisionSnapshot.source_notice_available ? 'available' : 'unavailable')}
                        />
                        <SnapshotChip
                            icon={<MapPin className="h-4 w-4" />}
                            label="Country / Region"
                            value={snapshotCountryRegion(decisionSnapshot)}
                        />
                        <SnapshotChip
                            icon={<Building2 className="h-4 w-4" />}
                            label="Service"
                            value={safeField(decisionSnapshot.service_category)}
                        />
                        <SnapshotChip
                            icon={<Calendar className="h-4 w-4" />}
                            label="Deadline"
                            value={formatDate(decisionSnapshot.deadline)}
                            badge={deadlineUrgencyLabel(decisionSnapshot.deadline_urgency)}
                            badgeClasses={deadlineUrgencyClasses(decisionSnapshot.deadline_urgency)}
                        />
                        <SnapshotChip
                            icon={<CircleDollarSign className="h-4 w-4" />}
                            label="Budget"
                            value={snapshotPriceDisplay(decisionSnapshot)}
                        />
                        <SnapshotChip
                            icon={<FileText className="h-4 w-4" />}
                            label="Documents"
                            value={snapshotDocumentLabel(decisionSnapshot)}
                        />
                        <SnapshotChip
                            icon={<UserRound className="h-4 w-4" />}
                            label="Contact"
                            value={contactAvailabilityLabel(decisionSnapshot.contact_availability)}
                        />
                        <SnapshotChip
                            icon={<UsersRound className="h-4 w-4" />}
                            label="Competitors"
                            value={competitorStatusLabel(decisionSnapshot.competitor_intelligence_status)}
                        />
                        <SnapshotChip
                            icon={<ShieldCheck className="h-4 w-4" />}
                            label="Compliance"
                            value={snapshotComplianceLabel(decisionSnapshot)}
                        />
                    </div>
                ) : (
                    <div className="rounded-lg border border-zinc-800 bg-gray-900 px-4 py-5 text-sm text-zinc-400">
                        Decision snapshot unavailable.
                    </div>
                )}
            </section> */}

            <section className="rounded-lg border border-indigo-500/25 bg-gray-950 p-5 shadow-[0_0_0_1px_rgba(99,102,241,0.08)]">
                <div className="mb-4 flex items-center justify-between gap-3">
                    <div className="flex items-center gap-2">
                        <Send className="h-4 w-4 text-indigo-300" />
                        <h2 className="text-lg font-semibold text-white">Contact &amp; Submission</h2>
                    </div>
                    <span className={`hidden rounded-md border px-2 py-1 text-xs font-semibold sm:inline-flex ${sourceBadgeClasses(tender.source_system)}`}>
                        {sourceLabel(tender.source_system)}
                    </span>
                </div>

                <dl className="grid grid-cols-1 gap-x-6 gap-y-4 text-sm md:grid-cols-2 xl:grid-cols-4">
                    <div>
                        <dt className="text-xs uppercase text-zinc-500">Buyer / agency</dt>
                        <dd className="mt-1 text-zinc-100">{contactField(contact?.buyer_agency || tender.buyer)}</dd>
                    </div>
                    <div>
                        <dt className="text-xs uppercase text-zinc-500">Contact person</dt>
                        <dd className="mt-1 flex items-center gap-2 text-zinc-200">
                            <UserRound className="h-3.5 w-3.5 shrink-0 text-zinc-500" />
                            <span>{contactField(contact?.contact_person)}</span>
                        </dd>
                    </div>
                    <div>
                        <dt className="text-xs uppercase text-zinc-500">Email</dt>
                        <dd className="mt-1 flex min-w-0 items-center gap-2 text-zinc-200">
                            <Mail className="h-3.5 w-3.5 shrink-0 text-zinc-500" />
                            {contact?.email ? (
                                <a href={`mailto:${contact.email}`} className="truncate text-indigo-200 hover:text-indigo-100">
                                    {contact.email}
                                </a>
                            ) : (
                                <span>Not provided in source metadata</span>
                            )}
                        </dd>
                    </div>
                    <div>
                        <dt className="text-xs uppercase text-zinc-500">Phone</dt>
                        <dd className="mt-1 flex items-center gap-2 text-zinc-200">
                            <Phone className="h-3.5 w-3.5 shrink-0 text-zinc-500" />
                            {contact?.phone ? (
                                <a href={`tel:${contact.phone}`} className="text-indigo-200 hover:text-indigo-100">
                                    {contact.phone}
                                </a>
                            ) : (
                                <span>Not provided in source metadata</span>
                            )}
                        </dd>
                    </div>
                    <div className="xl:col-span-2">
                        <dt className="text-xs uppercase text-zinc-500">Address</dt>
                        <dd className="mt-1 flex items-start gap-2 text-zinc-200">
                            <MapPin className="mt-0.5 h-3.5 w-3.5 shrink-0 text-zinc-500" />
                            <span>{contactField(contact?.address)}</span>
                        </dd>
                    </div>
                    <div>
                        <dt className="text-xs uppercase text-zinc-500">Submission deadline</dt>
                        <dd className="mt-1 font-medium text-zinc-100">{contactDate(contact?.submission_deadline || tender.deadline)}</dd>
                    </div>
                    <div>
                        <dt className="text-xs uppercase text-zinc-500">Question deadline</dt>
                        <dd className="mt-1 text-zinc-200">{contactDate(contact?.question_deadline)}</dd>
                    </div>
                    <div>
                        <dt className="text-xs uppercase text-zinc-500">Procedure type</dt>
                        <dd className="mt-1 text-zinc-200">{contactField(contact?.procedure_type || tender.procurement_method)}</dd>
                    </div>
                    <div className="xl:col-span-2">
                        <dt className="text-xs uppercase text-zinc-500">Submission method</dt>
                        <dd className="mt-1 text-zinc-200">{contactField(contact?.submission_method)}</dd>
                    </div>
                    <div className="xl:col-span-2">
                        <dt className="text-xs uppercase text-zinc-500">Participation / access</dt>
                        <dd className="mt-1 text-zinc-200">{accessNotes(contact?.participation_instructions)}</dd>
                    </div>
                    <div className="xl:col-span-2">
                        <dt className="text-xs uppercase text-zinc-500">Document access notes</dt>
                        <dd className="mt-1 text-zinc-200">{accessNotes(contact?.document_access_notes)}</dd>
                    </div>
                </dl>

                <dl className="mt-5 border-t border-zinc-800 pt-4">
                    <dt className="text-xs uppercase text-zinc-500">Source notice link</dt>
                    <dd className="mt-2">
                        {contactSourceUrl ? (
                            <a
                                href={contactSourceUrl}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="inline-flex items-center gap-2 rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-xs font-semibold text-zinc-100 transition hover:border-indigo-500 hover:text-indigo-200"
                            >
                                <ExternalLink className="h-3.5 w-3.5" />
                                {sourceHost(contactSourceUrl)}
                            </a>
                        ) : (
                            <span className="text-sm text-zinc-400">Open source notice for full details</span>
                        )}
                    </dd>
                </dl>
            </section>

            <section className="grid grid-cols-1 gap-4 xl:grid-cols-3">
                <div className="rounded-lg border border-gray-800 bg-gray-950 p-4">
                    <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-zinc-200">
                        <FileSearch className="h-4 w-4 text-indigo-300" />
                        Source Identity
                    </div>
                    <dl className="space-y-3 text-sm">
                        <div><dt className="text-xs uppercase text-zinc-500">External ID</dt><dd className="mt-1 text-zinc-200">{tender.external_id}</dd></div>
                        <div><dt className="text-xs uppercase text-zinc-500">Project ID</dt><dd className="mt-1 text-zinc-200">{safeField(tender.project_id)}</dd></div>
                        <div><dt className="text-xs uppercase text-zinc-500">Notice Type</dt><dd className="mt-1 text-zinc-200">{safeField(tender.notice_type)}</dd></div>
                    </dl>
                </div>

                <div className="rounded-lg border border-gray-800 bg-gray-950 p-4">
                    <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-zinc-200">
                        <Building2 className="h-4 w-4 text-emerald-300" />
                        Buyer And Market
                    </div>
                    <dl className="space-y-3 text-sm">
                        <div><dt className="text-xs uppercase text-zinc-500">Buyer</dt><dd className="mt-1 text-zinc-200">{safeField(tender.buyer)}</dd></div>
                        <div><dt className="text-xs uppercase text-zinc-500">Country / Region</dt><dd className="mt-1 text-zinc-200">{safeField(tender.country)} / {safeField(tender.region)}</dd></div>
                        <div><dt className="text-xs uppercase text-zinc-500">Sector</dt><dd className="mt-1 text-zinc-200">{safeField(tender.sector || tender.category)}</dd></div>
                    </dl>
                </div>

                <div className="rounded-lg border border-gray-800 bg-gray-950 p-4">
                    <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-zinc-200">
                        <Calendar className="h-4 w-4 text-amber-300" />
                        Procurement Timing
                    </div>
                    <dl className="space-y-3 text-sm">
                        <div><dt className="text-xs uppercase text-zinc-500">Publication Date</dt><dd className="mt-1 text-zinc-200">{formatDate(tender.publication_date)}</dd></div>
                        <div><dt className="text-xs uppercase text-zinc-500">Deadline</dt><dd className="mt-1 text-zinc-200">{formatDate(tender.deadline)}</dd></div>
                        <div><dt className="text-xs uppercase text-zinc-500">Time Remaining</dt><dd className="mt-1 text-zinc-200">{timeRemaining(tender.deadline)}</dd></div>
                        <div><dt className="text-xs uppercase text-zinc-500">Price</dt><dd className={(tender.price_display || tender.budget > 0) ? 'mt-1 font-semibold text-emerald-300' : 'mt-1 text-zinc-500'}>{priceDisplay(tender)}</dd></div>
                    </dl>
                </div>
            </section>

            <ProjectContextSection
                context={projectContext}
                isLoading={isLoadingProject}
                failed={projectContextFailed}
                fallbackIdentity={projectFallbackIdentity}
            />

            <section className="rounded-lg border border-gray-800 bg-gray-950 p-5">
                <div className="mb-4 flex flex-col gap-3">
                    <div className="flex items-center gap-2">
                        <UsersRound className="h-4 w-4 text-cyan-300" />
                        <h2 className="text-lg font-semibold text-white">Likely Competitors</h2>
                    </div>
                    <p className="flex items-start gap-2 text-sm leading-6 text-zinc-500">
                        <Info className="mt-0.5 h-4 w-4 shrink-0 text-zinc-600" />
                        <span>
                            Based on public historical procurement data and similar tender activity. This does not confirm participation in the current tender.
                        </span>
                    </p>
                </div>

                {competitorError && (
                    <div className="mb-4 flex items-center gap-2 rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-2 text-sm text-red-200">
                        <AlertCircle className="h-4 w-4" />
                        {competitorError}
                    </div>
                )}

                {isLoadingCompetitors ? (
                    <div className="flex items-center gap-2 text-sm text-zinc-400">
                        <Loader2 className="h-4 w-4 animate-spin" />
                        Loading competitor intelligence...
                    </div>
                ) : competitorGroups.length === 0 ? (
                    <div className="rounded-lg border border-zinc-800 bg-gray-900 px-4 py-5 text-sm text-zinc-400">
                        No historical competitor intelligence available yet.
                    </div>
                ) : (
                    <div className="space-y-5">
                        {competitorGroups.map((group) => (
                            <div key={group.service_category} className="border-t border-zinc-800 pt-4 first:border-t-0 first:pt-0">
                                <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                                    <div>
                                        <h3 className="text-sm font-semibold text-zinc-100">{group.industry}</h3>
                                        <p className="mt-1 text-xs text-zinc-500">{group.service_category}</p>
                                    </div>
                                    <span className="rounded-md border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs font-semibold text-zinc-300">
                                        {group.competitors.length} known market {group.competitors.length === 1 ? 'actor' : 'actors'}
                                    </span>
                                </div>

                                <div className="overflow-hidden rounded-lg border border-zinc-800">
                                    <div className="hidden grid-cols-[minmax(0,1fr)_150px_190px_190px] gap-3 border-b border-zinc-800 bg-gray-900 px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-zinc-500 md:grid">
                                        <span>Company</span>
                                        <span>Confidence</span>
                                        <span>Type</span>
                                        <span>Evidence</span>
                                    </div>
                                    <div className="divide-y divide-zinc-900">
                                        {group.competitors.map((competitor) => (
                                            <div key={`${group.service_category}-${competitor.company_name}-${competitor.related_tender_id || competitor.source}`} className="grid grid-cols-1 gap-3 px-3 py-3 text-sm md:grid-cols-[minmax(0,1fr)_150px_190px_190px]">
                                                <div className="min-w-0">
                                                    <p className="font-medium text-zinc-100">{competitor.company_name}</p>
                                                    <p className="mt-1 text-xs text-zinc-500">{competitor.industry}</p>
                                                    <p className="mt-2 text-sm leading-6 text-zinc-400">{competitor.reason}</p>
                                                </div>
                                                <div>
                                                    <span className={`inline-flex rounded-md border px-2 py-1 text-xs font-semibold ${competitorConfidenceClasses(competitor.confidence)}`}>
                                                        {competitorConfidenceLabel(competitor.confidence)}
                                                    </span>
                                                </div>
                                                <div className="text-zinc-300">
                                                    {competitorParticipationLabel(competitor.participation_type)}
                                                </div>
                                                <div className="space-y-1 text-xs text-zinc-400">
                                                    <p>{sourceLabel(competitor.source)}</p>
                                                    {competitor.evidence_source ? (
                                                        <a
                                                            href={competitor.evidence_source}
                                                            target="_blank"
                                                            rel="noopener noreferrer"
                                                            className="inline-flex max-w-full items-center gap-1 text-indigo-200 hover:text-indigo-100"
                                                        >
                                                            <ExternalLink className="h-3 w-3 shrink-0" />
                                                            <span className="truncate">{sourceHost(competitor.evidence_source)}</span>
                                                        </a>
                                                    ) : (
                                                        <p>Evidence source not linked</p>
                                                    )}
                                                    <p>{safeField(competitor.country)}</p>
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </section>

            <section className="rounded-lg border border-gray-800 bg-gray-950 p-5">
                <div className="mb-4 flex items-center justify-between gap-3">
                    <div>
                        <h2 className="text-lg font-semibold text-white">Documents</h2>
                        <p className="mt-1 text-sm text-zinc-500">
                            {documentAggregateSummary(tender)}
                        </p>
                    </div>
                    <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">
                        {tender.source_system === 'giz' && (
                            <button
                                onClick={handlePrepareGizDocuments}
                                disabled={isPreparingDocuments}
                                className="inline-flex items-center gap-2 rounded-lg border border-cyan-500/30 bg-cyan-500/10 px-3 py-2 text-xs font-semibold text-cyan-200 transition hover:border-cyan-400 hover:text-cyan-100 disabled:cursor-not-allowed disabled:border-zinc-800 disabled:bg-zinc-900 disabled:text-zinc-500"
                            >
                                {isPreparingDocuments ? (
                                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                ) : (
                                    <FileSearch className="h-3.5 w-3.5" />
                                )}
                                Prepare documents for analysis
                            </button>
                        )}
                        <span className={`inline-flex rounded-md border px-2 py-1 text-xs font-semibold ${documentStatusClasses(tender.document_status)}`}>
                            {documentAggregateLabel(tender)}
                        </span>
                    </div>
                </div>

                {showPreparationBanner && (
                    <div className="mb-4 flex items-center gap-2 rounded-lg border border-indigo-500/20 bg-indigo-500/10 px-3 py-2 text-sm text-indigo-200">
                        {isPreparingDocuments || !isPreparationTerminal ? (
                            <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                            <CheckCircle2 className="h-4 w-4" />
                        )}
                        Document preparation is {hydrationStageLabel(prepareStage ?? (tender.document_status === 'processing' ? 'processing' : 'queued'))}
                        {isPreparingDocuments ? ` (${prepareProgress}%).` : '.'}
                    </div>
                )}

                {prepareError && (
                    <div className="mb-4 flex items-center gap-2 rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-2 text-sm text-red-200">
                        <AlertCircle className="h-4 w-4" />
                        {prepareError}
                    </div>
                )}

                {documentError && (
                    <div className="mb-4 flex items-center gap-2 rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-2 text-sm text-red-200">
                        <AlertCircle className="h-4 w-4" />
                        {documentError}
                    </div>
                )}

                {isLoadingDocuments ? (
                    <div className="flex items-center gap-2 text-sm text-zinc-400">
                        <Loader2 className="h-4 w-4 animate-spin" />
                        Loading document metadata...
                    </div>
                ) : documents.length === 0 ? (
                    <div className="rounded-lg border border-zinc-800 bg-gray-900 px-4 py-5 text-sm text-zinc-400">
                        No documents found for this tender.
                    </div>
                ) : (
                    <div className="overflow-hidden rounded-lg border border-zinc-800">
                        <div className="hidden grid-cols-[minmax(0,1fr)_180px_180px] gap-3 border-b border-zinc-800 bg-gray-900 px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-zinc-500 md:grid">
                            <span>Document</span>
                            <span>Status</span>
                            <span>Action</span>
                        </div>
                        <div className="divide-y divide-zinc-900">
                            {documents.map((doc) => {
                                const isAvailable = doc.download_status === 'available';
                                return (
                                    <div key={doc.id} className="grid grid-cols-1 gap-3 px-3 py-3 text-sm md:grid-cols-[minmax(0,1fr)_180px_180px]">
                                        <div className="flex min-w-0 items-center gap-2 text-zinc-200">
                                            {isAvailable ? (
                                                <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" />
                                            ) : (
                                                <FileText className="h-4 w-4 shrink-0 text-zinc-500" />
                                            )}
                                            <span className="truncate">{filenameForDocument(doc)}</span>
                                        </div>
                                        <div className={downloadStatusClasses(doc)}>
                                            {downloadStatusText(doc)}
                                        </div>
                                        <div>
                                            <button
                                                onClick={() => handleOpenDocument(doc)}
                                                disabled={!isAvailable || openingDocId === doc.id}
                                                className="inline-flex items-center gap-2 rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-xs font-semibold text-zinc-200 transition hover:border-indigo-500 hover:text-indigo-200 disabled:cursor-not-allowed disabled:border-zinc-800 disabled:text-zinc-600"
                                            >
                                                {openingDocId === doc.id ? (
                                                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                                ) : (
                                                    <Download className="h-3.5 w-3.5" />
                                                )}
                                                {openingDocId === doc.id ? 'Opening' : 'Open / Download'}
                                            </button>
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    </div>
                )}
            </section>

            <section className="rounded-lg border border-gray-800 bg-gray-950 p-5">
                <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-zinc-200">
                    <Globe2 className="h-4 w-4 text-sky-300" />
                    Procurement Classification
                </div>
                <div className="grid grid-cols-1 gap-4 text-sm md:grid-cols-3">
                    <div><p className="text-xs uppercase text-zinc-500">Category</p><p className="mt-1 text-zinc-200">{safeField(tender.procurement_category || tender.category)}</p></div>
                    <div><p className="text-xs uppercase text-zinc-500">Method</p><p className="mt-1 text-zinc-200">{safeField(tender.procurement_method)}</p></div>
                    <div><p className="text-xs uppercase text-zinc-500">Source</p><p className="mt-1 text-zinc-200">{sourceLabel(tender.source_system)}</p></div>
                </div>
            </section>
        </div>
    );
}
