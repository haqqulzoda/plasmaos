'use client';

import { use, useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import Link from 'next/link';
import {
    AlertCircle,
    ArrowLeft,
    Building2,
    Calendar,
    CircleDollarSign,
    Download,
    ExternalLink,
    FileCheck2,
    FileText,
    Globe2,
    Landmark,
    Loader2,
    Mail,
    MapPin,
    Phone,
    RefreshCw,
    ShieldCheck,
    Sparkles,
    UserRound,
    UsersRound,
} from 'lucide-react';

import { TenderEngagementPanel } from '@/components/tenders/TenderEngagementPanel';
import { api } from '@/lib/api';
import type {
    DetailsSectionState,
    TenderDetailsCompliance,
    TenderDetailsDocumentItem,
    TenderDetailsProjectLeadershipItem,
    TenderDetailsResponse,
} from '@/types/tender-details';
import type { Tender } from '@/types/tender';
import {
    isTenderActionable,
    sourceBadgeClasses,
    sourceLabel,
    tenderStatusClasses,
    tenderStatusLabel,
} from '@/types/tender';

const EXPLORER_RESTORE_KEY = 'plasmaos:tender-explorer:return';
const EXPLORER_FALLBACK_HREF = '/dashboard/tenders';

const SECTION_LINKS = [
    { href: '#pursuit', label: 'Pursuit' },
    { href: '#project-context', label: 'Project' },
    { href: '#requirements-documents', label: 'Requirements & Documents' },
    { href: '#compliance-readiness', label: 'Compliance & Readiness' },
    { href: '#contacts', label: 'Procurement Contacts' },
    { href: '#bid-preparation', label: 'Bid Preparation' },
] as const;

function formatDate(value: string | null | undefined, includeTime = false) {
    if (!value) return 'Not available';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return 'Not available';
    return new Intl.DateTimeFormat('en-US', {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
        ...(includeTime ? { hour: 'numeric', minute: '2-digit' } : {}),
    }).format(date);
}

function formatFileSize(value: number | null) {
    if (value === null || value < 0) return 'Size not reported';
    if (value < 1024) return `${value} B`;
    if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
    return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function formatMoney(tender: Tender) {
    if (tender.price_display) return tender.price_display;
    if (tender.budget <= 0) return 'Not specified';
    return `${new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 }).format(tender.budget)} ${tender.currency}`;
}

function safeText(value: string | null | undefined, fallback = 'Not specified') {
    return value?.trim() || fallback;
}

function apiErrorMessage(error: unknown, fallback: string) {
    const detail = (error as { response?: { data?: { detail?: string } } }).response?.data?.detail;
    return typeof detail === 'string' && detail.trim() ? detail : fallback;
}

function sectionStateClasses(state: DetailsSectionState) {
    if (state === 'AVAILABLE') return 'border-emerald-500/25 bg-emerald-500/10 text-emerald-200';
    if (state === 'UNAVAILABLE') return 'border-amber-500/25 bg-amber-500/10 text-amber-200';
    return 'border-zinc-700 bg-zinc-800/60 text-zinc-400';
}

function SectionStateBadge({ state }: { state: DetailsSectionState }) {
    return (
        <span className={`inline-flex rounded-md border px-2 py-1 text-[11px] font-semibold uppercase tracking-wide ${sectionStateClasses(state)}`}>
            {state === 'AVAILABLE' ? 'Available' : state === 'UNAVAILABLE' ? 'Unavailable' : 'Not available'}
        </span>
    );
}

function SectionShell({
    id,
    title,
    description,
    icon,
    state,
    children,
}: {
    id: string;
    title: string;
    description: string;
    icon: ReactNode;
    state?: DetailsSectionState;
    children: ReactNode;
}) {
    return (
        <section id={id} aria-labelledby={`${id}-heading`} className="scroll-mt-28 rounded-xl border border-zinc-800 bg-zinc-950 p-4 sm:p-5">
            <div className="flex flex-col gap-3 border-b border-zinc-800 pb-4 sm:flex-row sm:items-start sm:justify-between">
                <div className="flex min-w-0 items-start gap-3">
                    <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-zinc-700 bg-zinc-900 text-indigo-300">
                        {icon}
                    </div>
                    <div>
                        <h2 id={`${id}-heading`} className="text-base font-semibold text-white sm:text-lg">{title}</h2>
                        <p className="mt-1 text-sm leading-5 text-zinc-500">{description}</p>
                    </div>
                </div>
                {state ? <SectionStateBadge state={state} /> : null}
            </div>
            <div className="pt-4">{children}</div>
        </section>
    );
}

function CompactState({ state, empty, unavailable }: { state: DetailsSectionState; empty: string; unavailable: string }) {
    const isUnavailable = state === 'UNAVAILABLE';
    return (
        <div role={isUnavailable ? 'status' : undefined} className={`flex items-start gap-2 rounded-lg border px-3 py-3 text-sm ${isUnavailable ? 'border-amber-500/20 bg-amber-500/5 text-amber-200' : 'border-zinc-800 bg-zinc-900/50 text-zinc-400'}`}>
            {isUnavailable ? <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" /> : <FileText className="mt-0.5 h-4 w-4 shrink-0 text-zinc-500" aria-hidden="true" />}
            <span>{isUnavailable ? unavailable : empty}</span>
        </div>
    );
}

function DetailsLoading() {
    return (
        <div role="status" aria-live="polite" className="rounded-xl border border-zinc-800 bg-zinc-950 p-5">
            <div className="flex items-center gap-3 text-sm text-zinc-300">
                <Loader2 className="h-4 w-4 animate-spin text-indigo-300" aria-hidden="true" />
                Loading additional Tender details…
            </div>
            <div className="mt-4 grid gap-3 md:grid-cols-3">
                {[0, 1, 2].map((item) => <div key={item} className="h-20 animate-pulse rounded-lg bg-zinc-900" />)}
            </div>
        </div>
    );
}

function leadershipRoleLabel(role: TenderDetailsProjectLeadershipItem) {
    if (role.native_role.trim().toLowerCase() === 'teamleadname') return `${sourceLabel(role.source_system)} project team`;
    if (role.canonical_role === 'TASK_TEAM_LEADER') return 'Task Team Leader';
    if (role.canonical_role === 'CO_TASK_TEAM_LEADER') return 'Co-Task Team Leader';
    if (role.canonical_role === 'PROJECT_TASK_MANAGER') return 'Project Task Manager';
    return role.native_role || 'Project role';
}

function compliancePresentation(compliance: TenderDetailsCompliance, state: DetailsSectionState) {
    const failed = compliance.execution_state === 'FAILED' || state === 'UNAVAILABLE';
    const partial = compliance.compliance_completeness === 'PARTIAL';
    const legacy = compliance.version_origin === 'LEGACY_BACKFILL';
    if (failed) return { label: 'Analysis failed', classes: 'border-red-500/30 bg-red-500/10 text-red-200', detail: 'The latest analysis is unavailable and must not be treated as compliant.' };
    if (partial) return { label: 'Partial analysis', classes: 'border-amber-500/30 bg-amber-500/10 text-amber-200', detail: 'Coverage is partial. Review the Compliance workbench before making a decision.' };
    if (legacy) return { label: 'Legacy analysis', classes: 'border-zinc-600 bg-zinc-800/70 text-zinc-200', detail: 'This historical result has limited modern provenance.' };
    return { label: compliance.decision_label || compliance.execution_state, classes: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-200', detail: 'Summary from the latest immutable Compliance version.' };
}

function documentAvailability(item: TenderDetailsDocumentItem) {
    if (item.availability === 'AVAILABLE') return { label: 'Available', classes: 'text-emerald-300' };
    if (item.availability === 'UNAVAILABLE') return { label: 'Unavailable', classes: 'text-red-300' };
    return { label: 'Metadata only', classes: 'text-amber-300' };
}

export default function TenderDetailPage({ params }: { params: Promise<{ tenderId: string }> }) {
    const { tenderId } = use(params);
    const [returnHref, setReturnHref] = useState(EXPLORER_FALLBACK_HREF);
    const [tender, setTender] = useState<Tender | null>(null);
    const [details, setDetails] = useState<TenderDetailsResponse | null>(null);
    const [isLoadingTender, setIsLoadingTender] = useState(true);
    const [isLoadingDetails, setIsLoadingDetails] = useState(true);
    const [tenderError, setTenderError] = useState<string | null>(null);
    const [detailsError, setDetailsError] = useState<string | null>(null);
    const [openingDocumentId, setOpeningDocumentId] = useState<string | null>(null);
    const [documentActionError, setDocumentActionError] = useState<string | null>(null);

    useEffect(() => {
        const rawState = window.sessionStorage.getItem(EXPLORER_RESTORE_KEY);
        if (!rawState) return;
        try {
            const explorerUrl = JSON.parse(rawState)?.explorerUrl;
            if (typeof explorerUrl === 'string' && explorerUrl.startsWith(EXPLORER_FALLBACK_HREF)) setReturnHref(explorerUrl);
        } catch {
            window.sessionStorage.removeItem(EXPLORER_RESTORE_KEY);
        }
    }, []);

    const loadTender = useCallback(async () => {
        setIsLoadingTender(true);
        setTenderError(null);
        try {
            const response = await api.get<Tender>(`/tenders/${tenderId}`);
            setTender(response.data);
        } catch (error: unknown) {
            setTender(null);
            setTenderError(apiErrorMessage(error, 'Tender could not be loaded.'));
        } finally {
            setIsLoadingTender(false);
        }
    }, [tenderId]);

    const loadDetails = useCallback(async () => {
        setIsLoadingDetails(true);
        setDetailsError(null);
        try {
            const response = await api.get<TenderDetailsResponse>(`/tenders/${tenderId}/details`);
            setDetails(response.data);
        } catch (error: unknown) {
            setDetails(null);
            setDetailsError(apiErrorMessage(error, 'Additional Tender details could not be loaded.'));
        } finally {
            setIsLoadingDetails(false);
        }
    }, [tenderId]);

    useEffect(() => { void loadTender(); }, [loadTender]);
    useEffect(() => { void loadDetails(); }, [loadDetails]);

    useEffect(() => {
        if (isLoadingDetails || !window.location.hash) return;
        const target = document.querySelector(window.location.hash);
        if (!target) return;
        window.requestAnimationFrame(() => target.scrollIntoView({ block: 'start' }));
    }, [isLoadingDetails]);

    const openDocument = useCallback(async (item: TenderDetailsDocumentItem) => {
        if (item.availability !== 'AVAILABLE' || openingDocumentId) return;
        setOpeningDocumentId(item.document_id);
        setDocumentActionError(null);
        try {
            const response = await api.get(`/tenders/documents/${item.document_id}/download`, { responseType: 'blob' });
            const contentType = response.headers['content-type'] || item.content_type || 'application/octet-stream';
            const url = URL.createObjectURL(new Blob([response.data], { type: contentType }));
            const link = document.createElement('a');
            link.href = url;
            if (contentType.includes('pdf')) {
                link.target = '_blank';
                link.rel = 'noreferrer';
            } else {
                link.download = item.display_name;
            }
            document.body.appendChild(link);
            link.click();
            link.remove();
            window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
        } catch (error: unknown) {
            setDocumentActionError(apiErrorMessage(error, 'This document could not be opened with your current access.'));
        } finally {
            setOpeningDocumentId(null);
        }
    }, [openingDocumentId]);

    const actionable = isTenderActionable(tender);
    const project = details?.project_context.data ?? null;
    const leadership = details?.project_leadership.data ?? null;
    const contacts = details?.procurement_contacts.data ?? null;
    const requirements = details?.requirements.data ?? null;
    const documents = details?.documents.data ?? null;
    const compliance = details?.compliance.data ?? null;
    const readiness = details?.company_readiness.data ?? null;
    const pursuit = details?.pursuit.data ?? null;
    const bidPreparation = details?.bid_preparation.data ?? null;
    const currentRoles = useMemo(() => leadership?.items.filter((role) => role.is_current) ?? [], [leadership]);
    const historicalRoles = useMemo(() => leadership?.items.filter((role) => !role.is_current) ?? [], [leadership]);

    if (isLoadingTender) {
        return <div role="status" aria-live="polite" className="space-y-4"><div className="h-5 w-32 animate-pulse rounded bg-zinc-800" /><div className="h-56 animate-pulse rounded-xl border border-zinc-800 bg-zinc-950" /><span className="sr-only">Loading Tender…</span></div>;
    }

    if (tenderError || !tender) {
        return (
            <div className="space-y-4">
                <Link href={returnHref} className="inline-flex items-center gap-2 text-sm text-zinc-400 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400"><ArrowLeft className="h-4 w-4" aria-hidden="true" />Back to tenders</Link>
                <div role="alert" className="rounded-xl border border-red-500/25 bg-red-500/10 p-5 text-sm text-red-200">{tenderError || 'Tender not found.'}</div>
            </div>
        );
    }

    return (
        <main className="space-y-5 pb-10">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <Link href={returnHref} className="inline-flex w-fit items-center gap-2 text-sm text-zinc-400 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400"><ArrowLeft className="h-4 w-4" aria-hidden="true" />Back to tenders</Link>
                <div className="flex flex-wrap gap-2">
                    {tender.source_url ? <a href={tender.source_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-2 rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-xs font-semibold text-zinc-200 hover:border-indigo-500 hover:text-indigo-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400"><ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />Open source notice</a> : null}
                    <Link href={`/dashboard/tenders/${tender.id}/compliance`} className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-3 py-2 text-xs font-semibold text-white hover:bg-indigo-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400"><ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />Open Compliance</Link>
                </div>
            </div>

            <header className="overflow-hidden rounded-xl border border-zinc-800 bg-zinc-950">
                <div className="border-b border-zinc-800 bg-gradient-to-r from-indigo-500/10 via-transparent to-sky-500/5 p-5 sm:p-6">
                    <div className="flex flex-wrap items-center gap-2">
                        <span className={`inline-flex rounded-md border px-2 py-1 text-xs font-semibold ${sourceBadgeClasses(tender.source_system)}`}>Source: {sourceLabel(tender.source_system)}</span>
                        <span className={`inline-flex rounded-md border px-2 py-1 text-xs font-semibold ${tenderStatusClasses(tender.status)}`}>Tender status: {tenderStatusLabel(tender.status)}</span>
                        <span className="inline-flex rounded-md border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs font-medium text-zinc-400">Reference: {tender.external_id}</span>
                    </div>
                    <h1 className="mt-4 max-w-5xl text-2xl font-bold leading-tight text-white sm:text-3xl">{tender.title}</h1>
                    <p className="mt-3 max-w-5xl text-sm leading-6 text-zinc-400">{tender.description || 'No source description was provided.'}</p>
                </div>
                <dl className="grid grid-cols-1 divide-y divide-zinc-800 sm:grid-cols-2 xl:grid-cols-4 xl:divide-x xl:divide-y-0">
                    {[
                        { label: 'Procuring entity', value: safeText(tender.buyer), icon: <Building2 className="h-4 w-4" /> },
                        { label: 'Tender deadline', value: formatDate(tender.deadline), icon: <Calendar className="h-4 w-4" /> },
                        { label: 'Estimated value', value: formatMoney(tender), icon: <CircleDollarSign className="h-4 w-4" /> },
                        { label: 'Location', value: [tender.country, tender.region].filter(Boolean).join(' / ') || 'Not specified', icon: <MapPin className="h-4 w-4" /> },
                    ].map((item) => <div key={item.label} className="min-w-0 p-4"><dt className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">{item.icon}{item.label}</dt><dd className="mt-2 break-words text-sm font-medium text-zinc-100">{item.value}</dd></div>)}
                </dl>
            </header>

            <nav aria-label="Tender detail sections" className="sticky top-16 z-20 -mx-1 overflow-x-auto rounded-xl border border-zinc-800 bg-zinc-950/95 px-2 py-2 shadow-xl backdrop-blur">
                <div className="flex min-w-max gap-1">{SECTION_LINKS.map((item) => <a key={item.href} href={item.href} className="rounded-lg px-3 py-2 text-xs font-semibold text-zinc-400 hover:bg-zinc-900 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400">{item.label}</a>)}</div>
            </nav>

            {isLoadingDetails ? <DetailsLoading /> : null}
            {detailsError ? <div role="alert" className="flex flex-col gap-3 rounded-xl border border-amber-500/25 bg-amber-500/10 p-4 text-sm text-amber-100 sm:flex-row sm:items-center sm:justify-between"><div className="flex items-start gap-2"><AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" /><div><p className="font-semibold">Additional Tender details could not be loaded.</p><p className="mt-1 text-amber-200/80">{detailsError} The source opportunity above remains available.</p></div></div><button type="button" onClick={() => void loadDetails()} className="inline-flex w-fit items-center gap-2 rounded-lg border border-amber-400/30 px-3 py-2 text-xs font-semibold hover:bg-amber-500/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400"><RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />Retry details</button></div> : null}

            {details ? (
                <>
                    <div id="pursuit" className="scroll-mt-28">
                        <TenderEngagementPanel tenderId={tender.id} proposalContext engagementData={pursuit} proposalIdData={bidPreparation?.proposal_id ?? null} loadingData={false} canStartNew={actionable} onRefresh={loadDetails} />
                        {pursuit ? <p className="mt-2 px-1 text-xs text-zinc-500">Pursuit status changed {formatDate(pursuit.status_changed_at, true)}. Tender status remains a separate source fact.</p> : null}
                    </div>

                    <SectionShell id="project-context" title="Project Context" description="The canonical source Project and its separately classified leadership." icon={<Globe2 className="h-4 w-4" />} state={details.project_context.state}>
                        {project ? (
                            <div className="space-y-5">
                                {details.project_context.state === 'UNAVAILABLE' ? <div role="status" className="flex items-start gap-2 rounded-lg border border-amber-500/20 bg-amber-500/5 px-3 py-2 text-sm text-amber-200"><AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />Project details are not currently available. Existing source identity is shown below.</div> : ['queued', 'running', 'never_attempted'].includes(project.enrichment_state) ? <div role="status" className="flex items-start gap-2 rounded-lg border border-sky-500/20 bg-sky-500/5 px-3 py-2 text-sm text-sky-200"><Loader2 className="mt-0.5 h-4 w-4 shrink-0 animate-spin" />Project details are being prepared. This page does not trigger enrichment.</div> : null}
                                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between"><div><h3 className="font-semibold text-zinc-100">{project.name || `${sourceLabel(project.source_system)} Project`}</h3><p className="mt-1 text-sm text-zinc-500">{sourceLabel(project.source_system)} · {project.external_project_id}</p></div><span className="w-fit rounded-md border border-sky-500/25 bg-sky-500/10 px-2 py-1 text-xs font-semibold text-sky-200">Project status: {safeText(project.project_status, 'Not reported')}</span></div>
                                <dl className="grid grid-cols-1 gap-4 text-sm sm:grid-cols-2 lg:grid-cols-4"><div><dt className="text-xs uppercase tracking-wide text-zinc-500">Country / Region</dt><dd className="mt-1 text-zinc-200">{[project.country, project.region].filter(Boolean).join(' / ') || 'Not reported'}</dd></div><div><dt className="text-xs uppercase tracking-wide text-zinc-500">Project approval</dt><dd className="mt-1 text-zinc-200">{formatDate(project.approval_date)}</dd></div><div><dt className="text-xs uppercase tracking-wide text-zinc-500">Project closing</dt><dd className="mt-1 text-zinc-200">{formatDate(project.closing_date)}</dd></div><div><dt className="text-xs uppercase tracking-wide text-zinc-500">Project enrichment</dt><dd className="mt-1 capitalize text-zinc-200">{project.enrichment_state.replaceAll('_', ' ')}</dd></div></dl>
                                <div aria-labelledby="project-leadership-heading" className="border-t border-zinc-800 pt-5">
                                    <div className="flex items-center gap-2"><UsersRound className="h-4 w-4 text-cyan-300" /><h3 id="project-leadership-heading" className="text-sm font-semibold uppercase tracking-wide text-zinc-200">Project Leadership</h3></div>
                                    <p className="mt-2 text-xs leading-5 text-zinc-500">Project leadership is source Project context and is not the Tender&apos;s procurement contact.</p>
                                    {currentRoles.length ? <div className="mt-3 grid gap-2 md:grid-cols-2">{currentRoles.map((role) => <div key={role.role_id} className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-3"><p className="font-medium text-zinc-100">{role.display_name}</p><p className="mt-1 text-xs text-zinc-400">{leadershipRoleLabel(role)}</p><p className="mt-2 text-xs text-zinc-500">Source: {sourceLabel(role.source_system)}</p></div>)}</div> : <p className="mt-3 text-sm text-zinc-500">No current Project Leadership is available.</p>}
                                    {historicalRoles.length ? <details className="mt-3"><summary className="cursor-pointer text-sm font-medium text-zinc-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400">Previous project leadership ({historicalRoles.length})</summary><div className="mt-2 grid gap-2 md:grid-cols-2">{historicalRoles.map((role) => <div key={role.role_id} className="rounded-lg border border-zinc-800 p-3 text-sm text-zinc-300"><p>{role.display_name}</p><p className="mt-1 text-xs text-zinc-500">{leadershipRoleLabel(role)} · observed until {formatDate(role.ended_at)}</p></div>)}</div></details> : null}
                                </div>
                            </div>
                        ) : <CompactState state={details.project_context.state} empty="No canonical Project is linked to this Tender." unavailable="Project details are not currently available." />}
                    </SectionShell>

                    <SectionShell id="requirements-documents" title="Requirements & Documents" description="Bounded source-document metadata and clearly labeled analysis-derived requirements." icon={<FileCheck2 className="h-4 w-4" />} state={details.documents.state === 'UNAVAILABLE' || details.requirements.state === 'UNAVAILABLE' ? 'UNAVAILABLE' : documents || requirements ? 'AVAILABLE' : 'EMPTY'}>
                        <div className="grid gap-5 xl:grid-cols-[0.9fr_1.1fr]">
                            <div>
                                <div className="flex items-center justify-between gap-2"><h3 className="text-sm font-semibold text-zinc-100">Important requirements</h3><SectionStateBadge state={details.requirements.state} /></div>
                                {requirements?.items.length ? <ul className="mt-3 space-y-2">{requirements.items.map((item, index) => <li key={`${item.label}-${index}`} className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-3"><div className="flex items-start gap-2"><Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-violet-300" /><div><p className="text-sm text-zinc-100">{item.label}</p><p className="mt-1 text-xs font-medium text-violet-300">AI-extracted requirement</p>{item.document_name || item.page || item.section ? <p className="mt-1 text-xs text-zinc-500">{[item.document_name, item.section, item.page ? `page ${item.page}` : null].filter(Boolean).join(' · ')}</p> : null}</div></div></li>)}</ul> : <div className="mt-3"><CompactState state={details.requirements.state} empty="No structured requirements are available." unavailable="The requirement summary is currently unavailable." /></div>}
                                {requirements?.truncated ? <p className="mt-2 text-xs text-zinc-500">Showing {requirements.returned_count} of {requirements.total_count} analysis-derived requirements. Open Compliance for the full workbench.</p> : null}
                            </div>
                            <div>
                                <div className="flex items-center justify-between gap-2"><h3 className="text-sm font-semibold text-zinc-100">Tender documents</h3><SectionStateBadge state={details.documents.state} /></div>
                                {documentActionError ? <p role="alert" className="mt-3 rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-2 text-sm text-red-200">{documentActionError}</p> : null}
                                {documents?.items.length ? <div className="mt-3 overflow-hidden rounded-lg border border-zinc-800"><div className="divide-y divide-zinc-800">{documents.items.map((item) => { const availability = documentAvailability(item); const canOpen = item.availability === 'AVAILABLE'; return <div key={item.document_id} className="grid gap-3 p-3 text-sm sm:grid-cols-[minmax(0,1fr)_130px_auto] sm:items-center"><div className="min-w-0"><p className="truncate font-medium text-zinc-100">{item.display_name}</p><p className="mt-1 text-xs text-zinc-500">{item.document_type} · {sourceLabel(item.source_system)} · {formatFileSize(item.file_size)}</p></div><p className={`text-xs font-semibold ${availability.classes}`}>{availability.label}</p><button type="button" onClick={() => void openDocument(item)} disabled={!canOpen || openingDocumentId !== null} className="inline-flex w-fit items-center gap-2 rounded-lg border border-zinc-700 px-3 py-2 text-xs font-semibold text-zinc-200 hover:border-indigo-500 hover:text-indigo-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400 disabled:cursor-not-allowed disabled:opacity-50">{openingDocumentId === item.document_id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : canOpen ? <Download className="h-3.5 w-3.5" /> : <FileText className="h-3.5 w-3.5" />}{openingDocumentId === item.document_id ? 'Opening' : canOpen ? 'Open document' : 'Metadata only'}</button></div>; })}</div></div> : <div className="mt-3"><CompactState state={details.documents.state} empty="No public source-document metadata is available." unavailable="Tender document metadata is currently unavailable." /></div>}
                                {documents?.truncated ? <p className="mt-2 text-xs text-zinc-500">+ {documents.visible_total_count - documents.returned_count} more public source documents. Open Compliance for evidence workflows.</p> : null}
                            </div>
                        </div>
                    </SectionShell>

                    <SectionShell id="compliance-readiness" title="Compliance & Company Readiness" description="Tender-specific analysis and company evidence are related, but remain separate authorities." icon={<ShieldCheck className="h-4 w-4" />} state={details.compliance.state === 'UNAVAILABLE' ? 'UNAVAILABLE' : compliance || readiness ? 'AVAILABLE' : 'EMPTY'}>
                        <div className="grid gap-4 lg:grid-cols-2">
                            <article className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4" aria-labelledby="compliance-summary-heading">
                                <div className="flex items-center justify-between gap-2"><h3 id="compliance-summary-heading" className="font-semibold text-zinc-100">Compliance</h3><SectionStateBadge state={details.compliance.state} /></div>
                                {compliance ? (() => { const presentation = compliancePresentation(compliance, details.compliance.state); return <div className="mt-4 space-y-3"><span className={`inline-flex rounded-md border px-2 py-1 text-xs font-semibold ${presentation.classes}`}>{presentation.label}</span><p className="text-sm leading-5 text-zinc-400">{presentation.detail}</p><dl className="grid grid-cols-2 gap-3 text-sm"><div><dt className="text-xs text-zinc-500">Completeness</dt><dd className="mt-1 text-zinc-200">{compliance.compliance_completeness}</dd></div><div><dt className="text-xs text-zinc-500">Version</dt><dd className="mt-1 text-zinc-200">v{compliance.version_number}</dd></div><div><dt className="text-xs text-zinc-500">Key issues</dt><dd className="mt-1 text-zinc-200">{compliance.key_issue_count ?? 'Not reported'}</dd></div><div><dt className="text-xs text-zinc-500">Analysis created</dt><dd className="mt-1 text-zinc-200">{formatDate(compliance.created_at)}</dd></div></dl>{compliance.version_origin === 'LEGACY_BACKFILL' ? <p className="text-xs font-medium text-zinc-400">Legacy analysis · historical provenance limitations apply.</p> : null}{compliance.override_applied ? <p className="text-xs text-amber-300">A current risk-override overlay is recorded.</p> : null}</div>; })() : <div className="mt-4"><CompactState state={details.compliance.state} empty="No Compliance analysis is available." unavailable="The latest Compliance analysis is unavailable." /></div>}
                                <Link href={`/dashboard/tenders/${tender.id}/compliance`} className="mt-4 inline-flex items-center gap-2 text-sm font-semibold text-indigo-300 hover:text-indigo-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400"><ShieldCheck className="h-4 w-4" />Open Compliance</Link>
                            </article>
                            <article className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4" aria-labelledby="readiness-summary-heading">
                                <div className="flex items-center justify-between gap-2"><h3 id="readiness-summary-heading" className="font-semibold text-zinc-100">Company Readiness</h3><SectionStateBadge state={details.company_readiness.state} /></div>
                                {readiness ? <div className="mt-4"><p className="text-sm leading-5 text-zinc-400">Evidence counts from your owned company profile. No readiness percentage is calculated.</p><dl className="mt-4 grid grid-cols-2 gap-3 text-sm sm:grid-cols-3"><div><dt className="text-xs text-zinc-500">Certifications</dt><dd className="mt-1 text-zinc-100">{readiness.certifications_total}</dd><p className="text-xs text-zinc-500">{readiness.expired_certifications} expired</p></div><div><dt className="text-xs text-zinc-500">Licenses</dt><dd className="mt-1 text-zinc-100">{readiness.active_licenses} active</dd><p className="text-xs text-zinc-500">{readiness.licenses_total} total</p></div><div><dt className="text-xs text-zinc-500">Credentials</dt><dd className="mt-1 text-zinc-100">{readiness.credentials_total}</dd><p className="text-xs text-zinc-500">{readiness.expired_credentials} expired</p></div><div><dt className="text-xs text-zinc-500">Readiness files</dt><dd className="mt-1 text-zinc-100">{readiness.readiness_documents_available} available</dd><p className="text-xs text-zinc-500">{readiness.readiness_documents_total} total</p></div><div><dt className="text-xs text-zinc-500">Missing evidence</dt><dd className="mt-1 text-zinc-100">{readiness.readiness_documents_missing}</dd></div><div><dt className="text-xs text-zinc-500">Financial years</dt><dd className="mt-1 text-zinc-100">{readiness.financial_history_years}</dd></div></dl></div> : <div className="mt-4"><CompactState state={details.company_readiness.state} empty="Company readiness information is incomplete or not available." unavailable="Company readiness information is currently unavailable." /></div>}
                                <Link href="/dashboard/readiness-vault" className="mt-4 inline-flex items-center gap-2 text-sm font-semibold text-sky-300 hover:text-sky-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400"><FileCheck2 className="h-4 w-4" />Open Readiness Vault</Link>
                            </article>
                        </div>
                    </SectionShell>

                    <SectionShell id="contacts" title="Procurement Contacts" description="Tender procurement and submission details from source-exposed metadata—not Project Leadership." icon={<UserRound className="h-4 w-4" />} state={details.procurement_contacts.state}>
                        {contacts ? <div className="grid gap-5 lg:grid-cols-2"><dl className="grid grid-cols-1 gap-4 text-sm sm:grid-cols-2"><div><dt className="text-xs uppercase tracking-wide text-zinc-500">Procuring entity</dt><dd className="mt-1 text-zinc-200">{safeText(contacts.buyer_agency)}</dd></div><div><dt className="text-xs uppercase tracking-wide text-zinc-500">Procurement contact</dt><dd className="mt-1 text-zinc-200">{safeText(contacts.contact_person, 'Not provided by source')}</dd></div><div><dt className="flex items-center gap-1 text-xs uppercase tracking-wide text-zinc-500"><Mail className="h-3.5 w-3.5" />Email</dt><dd className="mt-1 break-all text-zinc-200">{safeText(contacts.email, 'Not provided by source')}</dd></div><div><dt className="flex items-center gap-1 text-xs uppercase tracking-wide text-zinc-500"><Phone className="h-3.5 w-3.5" />Phone</dt><dd className="mt-1 text-zinc-200">{safeText(contacts.phone, 'Not provided by source')}</dd></div></dl><dl className="grid grid-cols-1 gap-4 text-sm sm:grid-cols-2"><div><dt className="text-xs uppercase tracking-wide text-zinc-500">Submission method</dt><dd className="mt-1 text-zinc-200">{safeText(contacts.submission_method)}</dd></div><div><dt className="text-xs uppercase tracking-wide text-zinc-500">Submission deadline</dt><dd className="mt-1 text-zinc-200">{formatDate(contacts.submission_deadline)}</dd></div><div><dt className="text-xs uppercase tracking-wide text-zinc-500">Question deadline</dt><dd className="mt-1 text-zinc-200">{formatDate(contacts.question_deadline)}</dd></div><div><dt className="text-xs uppercase tracking-wide text-zinc-500">Procedure</dt><dd className="mt-1 text-zinc-200">{safeText(contacts.procedure_type)}</dd></div></dl>{contacts.participation_instructions || contacts.address || contacts.document_access_notes ? <div className="lg:col-span-2 rounded-lg border border-zinc-800 bg-zinc-900/50 p-3 text-sm text-zinc-400"><p>{safeText(contacts.participation_instructions || contacts.document_access_notes || contacts.address)}</p></div> : null}</div> : <CompactState state={details.procurement_contacts.state} empty="No Procurement Contacts are available in source metadata." unavailable="Procurement Contacts are currently unavailable." />}
                    </SectionShell>

                    <SectionShell id="bid-preparation" title="Bid Preparation" description="The Proposal-backed preparation artifact remains independent from pursuit and Compliance." icon={<Landmark className="h-4 w-4" />} state={details.bid_preparation.state}>
                        {bidPreparation ? <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between"><div><p className="text-sm font-semibold text-zinc-100">Preparation status: {bidPreparation.proposal_status}</p><p className="mt-1 text-sm text-zinc-500">Created {formatDate(bidPreparation.created_at)}. Pursuit state is shown separately above.</p></div><Link href={`/dashboard/bid-preparation/${bidPreparation.detail_route_id}`} className="inline-flex w-fit items-center gap-2 rounded-lg bg-indigo-600 px-3 py-2 text-xs font-semibold text-white hover:bg-indigo-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400"><ExternalLink className="h-3.5 w-3.5" />{pursuit ? 'Open Bid Preparation' : 'Continue Bid Preparation'}</Link></div> : <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between"><div><p className="text-sm font-medium text-zinc-200">Not started</p><p className="mt-1 text-sm text-zinc-500">Prepare Bid from the Pursuit section when the canonical action is available.</p></div><SectionStateBadge state={details.bid_preparation.state} /></div>}
                    </SectionShell>
                </>
            ) : null}

            <section aria-label="Source classification" className="rounded-xl border border-zinc-800 bg-zinc-950 p-4">
                <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-zinc-500"><Globe2 className="h-4 w-4" />Source classification</div>
                <div className="mt-3 grid gap-3 text-sm sm:grid-cols-3"><p><span className="text-zinc-500">Category:</span> <span className="text-zinc-200">{safeText(tender.procurement_category || tender.category)}</span></p><p><span className="text-zinc-500">Method:</span> <span className="text-zinc-200">{safeText(tender.procurement_method)}</span></p><p><span className="text-zinc-500">Notice type:</span> <span className="text-zinc-200">{safeText(tender.notice_type)}</span></p></div>
            </section>
        </main>
    );
}
