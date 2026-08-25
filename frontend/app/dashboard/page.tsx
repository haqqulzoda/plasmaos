'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import {
    AlertTriangle,
    Archive,
    ArrowRight,
    CheckCircle2,
    ClipboardCheck,
    Clock,
    FileSearch,
    Loader2,
    Radar,
    ShieldAlert,
    ShieldCheck,
} from 'lucide-react';

import { api } from '@/lib/api';
import {
    expiryState,
    labelForDocumentType,
} from '@/lib/readiness';
import { labelForService, useServiceMeta } from '@/lib/services';
import type { Tender } from '@/types/tender';
import {
    documentAggregateLabel,
    isTenderActionable,
    sourceLabel,
} from '@/types/tender';
import type {
    DynamicEvaluation,
    DynamicRequirements,
    HybridCompliancePayload,
} from '@/types/compliance';

type CompanyProfile = {
    company_profile_id?: string | null;
    onboarding_required?: boolean;
    company_name?: string | null;
    target_regions?: string[] | null;
    target_countries?: string[] | null;
    target_services?: string[] | null;
    approval_status?: string | null;
    pilot_status?: string | null;
};

type ReadinessDocument = {
    id: string;
    document_type: string;
    document_name: string;
    expiry_date?: string | null;
    status: string;
    related_service?: string | null;
    updated_at?: string | null;
    created_at?: string | null;
};

type LatestAnalysis = {
    analysis_id: string | null;
    requirements: DynamicRequirements | null;
    evaluation: DynamicEvaluation | null;
    hybrid_compliance?: HybridCompliancePayload | null;
    coverage_metadata?: Record<string, unknown> | null;
    analysis_status: string;
    extraction_error?: string | null;
    created_at?: string | null;
};

type AnalysisSummary = {
    tender: Tender;
    analysis: LatestAnalysis;
};

type LoadState = {
    profile: CompanyProfile | null;
    readiness: ReadinessDocument[];
    opportunities: Tender[];
    analyses: AnalysisSummary[];
    failures: string[];
};

type ActionItem = {
    key: string;
    issue: string;
    subject: string;
    status: string;
    href: string;
    tone: 'danger' | 'warning' | 'review';
    priority: number;
};

const SUPPORTED_SOURCES = ['uzex', 'world_bank', 'adb', 'giz', 'ebrd'];
const REQUIRED_READINESS_TYPES = [
    'registration_document',
    'tax_clearance',
    'financial_statement',
    'license',
];

function unique(values: Array<string | null | undefined>): string[] {
    return Array.from(new Set(values.filter((value): value is string => Boolean(value && value.trim()))));
}

function normalizeList(values?: string[] | null): string[] {
    return Array.isArray(values) ? unique(values) : [];
}

function formatDate(value?: string | null) {
    if (!value) return 'Not set';
    return new Date(value).toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
    });
}

function relativeDate(value?: string | null) {
    if (!value) return 'Last updated unavailable';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return 'Last updated unavailable';
    return date.toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
    });
}

function deadlineState(deadline: string | null) {
    if (!deadline) return 'Unknown deadline';
    const days = Math.ceil((new Date(deadline).getTime() - Date.now()) / (1000 * 60 * 60 * 24));
    if (days < 0) return 'Expired';
    if (days === 0) return 'Due today';
    if (days === 1) return '1 day left';
    return `${days} days left`;
}

function isCurrentTender(tender: Tender) {
    return isTenderActionable(tender)
        && (!tender.deadline || new Date(tender.deadline).getTime() >= Date.now());
}

function serviceFields(tender: Tender) {
    return unique([tender.sector, tender.procurement_category, tender.category]);
}

function matchesAny(values: string[], candidates: string[]) {
    const normalized = new Set(values.map((value) => value.toLowerCase()));
    return candidates.some((candidate) => normalized.has(candidate.toLowerCase()));
}

function matchReason(tender: Tender, profile: CompanyProfile | null, serviceOptions: ReturnType<typeof useServiceMeta>) {
    const countries = normalizeList(profile?.target_countries);
    const regions = normalizeList(profile?.target_regions);
    const services = normalizeList(profile?.target_services);
    const tenderServices = serviceFields(tender);

    const geographyMatch = countries.find((country) => tender.country === country)
        ?? regions.find((region) => tender.region === region)
        ?? tender.country
        ?? tender.region
        ?? 'supported geography';
    const serviceMatch = services.find((service) => matchesAny([service], tenderServices))
        ?? tenderServices[0]
        ?? 'source coverage';

    return `Matches ${geographyMatch} · ${labelForService(serviceMatch, serviceOptions) || serviceMatch}`;
}

function analysisRequirementCount(analysis: LatestAnalysis) {
    if (typeof analysis.hybrid_compliance?.total_requirements === 'number') {
        return analysis.hybrid_compliance.total_requirements;
    }
    const mapped = analysis.requirements?.mapped_requirement_uuids?.length ?? 0;
    const unmapped = analysis.requirements?.unmapped_custom_requirements?.length ?? 0;
    return mapped + unmapped;
}

function coverageStatus(analysis: LatestAnalysis) {
    const coverage = analysis.coverage_metadata ?? {};
    const status = String(coverage.coverage_status ?? '');
    const sourceCoverage = coverage.source_document_coverage as { coverage_status?: unknown } | undefined;
    if (status === 'failed') return 'Failed';
    if (status === 'partial' || sourceCoverage?.coverage_status === 'partial') return 'Partial coverage';
    if (status === 'complete') return 'Complete coverage';
    return 'Coverage recorded';
}

function cleanAnalysisStatus(analysis: LatestAnalysis) {
    if (analysis.analysis_status === 'failed') return 'Failed';
    if (coverageStatus(analysis) === 'Partial coverage') return 'Partial coverage';
    if (
        analysis.analysis_status === 'needs_review'
        || (analysis.hybrid_compliance?.manual_review_count ?? 0) > 0
        || (analysis.evaluation?.unmapped_requirements?.length ?? 0) > 0
    ) {
        return 'Needs review';
    }
    return 'Completed';
}

function statusClasses(tone: 'danger' | 'warning' | 'review' | 'success' | 'neutral') {
    if (tone === 'danger') return 'border-red-500/25 bg-red-500/10 text-red-200';
    if (tone === 'warning') return 'border-amber-500/25 bg-amber-500/10 text-amber-200';
    if (tone === 'review') return 'border-sky-500/25 bg-sky-500/10 text-sky-200';
    if (tone === 'success') return 'border-emerald-500/25 bg-emerald-500/10 text-emerald-200';
    return 'border-zinc-700 bg-zinc-900 text-zinc-300';
}

function isReadinessAvailable(document: ReadinessDocument) {
    return document.status === 'available' && expiryState(document.expiry_date) !== 'expired';
}

function requiredMissingTypes(documents: ReadinessDocument[]) {
    return REQUIRED_READINESS_TYPES.filter((type) =>
        !documents.some((document) => document.document_type === type && isReadinessAvailable(document)),
    );
}

function buildActionItems(
    analyses: AnalysisSummary[],
    opportunities: Tender[],
    readiness: ReadinessDocument[],
) {
    const items: ActionItem[] = [];

    analyses.forEach(({ tender, analysis }) => {
        const status = cleanAnalysisStatus(analysis);
        if (status === 'Failed') {
            items.push({
                key: `analysis-failed-${analysis.analysis_id}`,
                issue: 'Compliance analysis failed',
                subject: tender.title,
                status: 'Failed',
                href: `/dashboard/tenders/${tender.id}/compliance`,
                tone: 'danger',
                priority: 1,
            });
        } else if (status === 'Needs review') {
            items.push({
                key: `analysis-review-${analysis.analysis_id}`,
                issue: 'Manual compliance review required',
                subject: tender.title,
                status: `${analysis.hybrid_compliance?.manual_review_count ?? 1} item(s) need review`,
                href: `/dashboard/tenders/${tender.id}/compliance`,
                tone: 'review',
                priority: 2,
            });
        }
    });

    opportunities
        .filter((tender) => ['partial', 'files_missing', 'metadata_only', 'access_required'].includes(tender.document_status))
        .slice(0, 3)
        .forEach((tender) => {
            items.push({
                key: `coverage-${tender.id}`,
                issue: 'Document coverage needs attention',
                subject: tender.title,
                status: documentAggregateLabel(tender),
                href: `/dashboard/tenders/${tender.id}`,
                tone: 'warning',
                priority: 3,
            });
        });

    readiness.forEach((document) => {
        const expiry = expiryState(document.expiry_date);
        if (document.status === 'expired' || expiry === 'expired') {
            items.push({
                key: `readiness-expired-${document.id}`,
                issue: 'Readiness record expired',
                subject: document.document_name,
                status: formatDate(document.expiry_date),
                href: '/dashboard/readiness-vault',
                tone: 'danger',
                priority: 1,
            });
        } else if (expiry === 'expiring_soon') {
            items.push({
                key: `readiness-soon-${document.id}`,
                issue: 'Readiness record expiring soon',
                subject: document.document_name,
                status: formatDate(document.expiry_date),
                href: '/dashboard/readiness-vault',
                tone: 'warning',
                priority: 4,
            });
        }
    });

    requiredMissingTypes(readiness).forEach((type) => {
        items.push({
            key: `readiness-missing-${type}`,
            issue: 'Readiness record missing',
            subject: labelForDocumentType(type),
            status: 'Required for bid preparation',
            href: '/dashboard/readiness-vault',
            tone: 'warning',
            priority: 5,
        });
    });

    return items.sort((a, b) => a.priority - b.priority).slice(0, 5);
}

function buildTenderParams(profile: CompanyProfile | null) {
    const params: Record<string, string | number> = {
        limit: 40,
        sort: 'deadline_soonest',
    };
    const countries = normalizeList(profile?.target_countries);
    const services = normalizeList(profile?.target_services);
    const regions = normalizeList(profile?.target_regions);
    if (countries.length > 0) params.countries = countries.join(',');
    if (services.length > 0) params.services = services.join(',');
    if (countries.length === 0 && regions.length > 0) params.region = regions[0];
    return params;
}

async function fetchLatestAnalyses(tenders: Tender[]) {
    const settled = await Promise.allSettled(
        tenders.slice(0, 12).map(async (tender) => {
            const response = await api.get<LatestAnalysis>(`/tenders/${tender.id}/latest-analysis`);
            return { tender, analysis: response.data };
        }),
    );
    return settled
        .filter((result): result is PromiseFulfilledResult<AnalysisSummary> => result.status === 'fulfilled')
        .map((result) => result.value)
        .filter((item) => Boolean(item.analysis.analysis_id))
        .sort((a, b) =>
            new Date(b.analysis.created_at ?? 0).getTime() - new Date(a.analysis.created_at ?? 0).getTime(),
        );
}

function isTestOnlyTender(tender: Tender) {
    const marker = `${tender.title} ${tender.external_id}`.toLowerCase();
    return marker.includes('[test]') || marker.includes('test-only') || marker.startsWith('test ');
}

export default function DashboardPage() {
    const serviceOptions = useServiceMeta();
    const [state, setState] = useState<LoadState>({
        profile: null,
        readiness: [],
        opportunities: [],
        analyses: [],
        failures: [],
    });
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        let mounted = true;

        const loadDashboard = async () => {
            setLoading(true);
            const failures: string[] = [];

            const profileResult = await api.get<CompanyProfile>('/users/me/company')
                .then((response) => response.data)
                .catch(() => {
                    failures.push('Company profile unavailable');
                    return null;
                });

            const [readinessResult, opportunityResult, analysisTenderResult] = await Promise.allSettled([
                api.get<ReadinessDocument[]>('/vault/readiness'),
                api.get<Tender[]>('/tenders', { params: buildTenderParams(profileResult) }),
                api.get<Tender[]>('/tenders', { params: { limit: 24, sort: 'newest' } }),
            ]);

            const readiness = readinessResult.status === 'fulfilled' ? readinessResult.value.data ?? [] : [];
            if (readinessResult.status === 'rejected') failures.push('Readiness vault unavailable');

            const opportunities = opportunityResult.status === 'fulfilled'
                ? (opportunityResult.value.data ?? []).filter((tender) => isCurrentTender(tender) && !isTestOnlyTender(tender))
                : [];
            if (opportunityResult.status === 'rejected') failures.push('Priority tenders unavailable');

            const analysisCandidates = analysisTenderResult.status === 'fulfilled'
                ? (analysisTenderResult.value.data ?? []).filter((tender) => !isTestOnlyTender(tender))
                : opportunities;
            if (analysisTenderResult.status === 'rejected') failures.push('Recent analyses unavailable');

            const analyses = await fetchLatestAnalyses(analysisCandidates).catch(() => {
                failures.push('Recent analyses unavailable');
                return [];
            });

            if (mounted) {
                setState({
                    profile: profileResult,
                    readiness,
                    opportunities,
                    analyses,
                    failures,
                });
                setLoading(false);
            }
        };

        loadDashboard();

        return () => {
            mounted = false;
        };
    }, []);

    const profileTargets = useMemo(() => ({
        countries: normalizeList(state.profile?.target_countries),
        regions: normalizeList(state.profile?.target_regions),
        services: normalizeList(state.profile?.target_services),
    }), [state.profile]);

    const priorityOpportunities = useMemo(
        () => state.opportunities
            .filter((tender) => SUPPORTED_SOURCES.includes(tender.source_system))
            .slice(0, 8),
        [state.opportunities],
    );

    const readinessStats = useMemo(() => {
        const expired = state.readiness.filter((document) =>
            document.status === 'expired' || expiryState(document.expiry_date) === 'expired',
        );
        const expiringSoon = state.readiness.filter((document) => expiryState(document.expiry_date) === 'expiring_soon');
        const missingTypes = requiredMissingTypes(state.readiness);
        const available = state.readiness.filter(isReadinessAvailable);
        const explicitlyMissing = state.readiness.filter((document) => document.status === 'missing');
        return {
            available: available.length,
            missing: missingTypes.length + explicitlyMissing.length,
            expired: expired.length,
            expiringSoon: expiringSoon.length,
            missingTypes,
        };
    }, [state.readiness]);

    const actionItems = useMemo(
        () => buildActionItems(state.analyses, state.opportunities, state.readiness),
        [state.analyses, state.opportunities, state.readiness],
    );

    const recentActivity = useMemo(() => {
        const analysisEvents = state.analyses.slice(0, 4).map(({ tender, analysis }) => ({
            key: `analysis-${analysis.analysis_id}`,
            label: cleanAnalysisStatus(analysis) === 'Completed'
                ? 'Compliance analysis completed'
                : `Compliance analysis ${cleanAnalysisStatus(analysis).toLowerCase()}`,
            subject: tender.title,
            when: analysis.created_at,
            href: `/dashboard/tenders/${tender.id}/compliance`,
        }));
        const readinessEvents = state.readiness
            .filter((document) => document.updated_at || document.created_at)
            .sort((a, b) =>
                new Date(b.updated_at ?? b.created_at ?? 0).getTime()
                - new Date(a.updated_at ?? a.created_at ?? 0).getTime(),
            )
            .slice(0, 2)
            .map((document) => ({
                key: `readiness-${document.id}`,
                label: 'Readiness record updated',
                subject: document.document_name,
                when: document.updated_at ?? document.created_at,
                href: '/dashboard/readiness-vault',
            }));
        return [...analysisEvents, ...readinessEvents]
            .sort((a, b) => new Date(b.when ?? 0).getTime() - new Date(a.when ?? 0).getTime())
            .slice(0, 6);
    }, [state.analyses, state.readiness]);

    const readinessTone = readinessStats.expired > 0
        ? 'danger'
        : readinessStats.missing > 0 || readinessStats.expiringSoon > 0
            ? 'warning'
            : 'success';

    if (loading) {
        return (
            <div className="flex h-64 items-center justify-center">
                <Loader2 className="h-7 w-7 animate-spin text-zinc-400" />
            </div>
        );
    }

    const isNewCompany = !state.profile?.company_profile_id
        || state.profile.onboarding_required
        || (
            state.readiness.length === 0
            && state.analyses.length === 0
            && priorityOpportunities.length === 0
        );

    return (
        <div className="space-y-5">
            <header className="flex flex-col gap-2 border-b border-zinc-800 pb-4 md:flex-row md:items-end md:justify-between">
                <div>
                    <p className="text-xs font-semibold uppercase tracking-[0.18em] text-zinc-500">Institutional overview</p>
                    <h1 className="mt-1 text-2xl font-semibold tracking-tight text-white">Dashboard</h1>
                    <p className="mt-1 max-w-3xl text-sm text-zinc-400">
                        Decision queue for tenders, compliance coverage, and bid readiness.
                    </p>
                </div>
                <Link
                    href="/dashboard/tenders"
                    className="inline-flex items-center gap-2 rounded-md border border-zinc-700 px-3 py-2 text-sm font-medium text-zinc-200 hover:border-zinc-500"
                >
                    Open Tender Explorer
                    <ArrowRight className="h-4 w-4" />
                </Link>
            </header>

            {state.failures.length > 0 && (
                <div className="rounded-md border border-amber-500/20 bg-amber-500/10 px-4 py-3 text-sm text-amber-100">
                    Some supporting data is unavailable. Showing the sections that loaded successfully.
                </div>
            )}

            {isNewCompany && <NewCompanySteps />}

            <section className="rounded-md border border-zinc-800 bg-zinc-950">
                <SectionHeader
                    icon={<AlertTriangle className="h-4 w-4" />}
                    title="Action Required"
                    description="Highest-priority items to clear before bidding."
                />
                {actionItems.length === 0 ? (
                    <EmptySection
                        icon={<CheckCircle2 className="h-5 w-5" />}
                        title="No urgent actions"
                        body="No failed analyses, partial document coverage, or readiness expiry issues are visible right now."
                    />
                ) : (
                    <div className="divide-y divide-zinc-900">
                        {actionItems.map((item) => (
                            <Link
                                key={item.key}
                                href={item.href}
                                className="grid gap-3 px-4 py-3 text-sm hover:bg-zinc-900/60 md:grid-cols-[1.1fr_1.4fr_180px_90px] md:items-center"
                            >
                                <div className="font-medium text-zinc-100">{item.issue}</div>
                                <div className="min-w-0 truncate text-zinc-400">{item.subject}</div>
                                <span className={`w-fit rounded border px-2 py-1 text-xs font-semibold ${statusClasses(item.tone)}`}>
                                    {item.status}
                                </span>
                                <span className="inline-flex items-center gap-1 text-xs font-semibold text-zinc-300 md:justify-end">
                                    Open <ArrowRight className="h-3.5 w-3.5" />
                                </span>
                            </Link>
                        ))}
                    </div>
                )}
            </section>

            <div className="grid gap-5 xl:grid-cols-[minmax(0,1.4fr)_minmax(360px,0.8fr)]">
                <section className="rounded-md border border-zinc-800 bg-zinc-950">
                    <SectionHeader
                        icon={<Radar className="h-4 w-4" />}
                        title="Priority Opportunities"
                        description="Current tenders aligned to the company profile and supported sources."
                    />
                    {priorityOpportunities.length === 0 ? (
                        <EmptySection
                            icon={<FileSearch className="h-5 w-5" />}
                            title={profileTargets.countries.length + profileTargets.regions.length + profileTargets.services.length === 0
                                ? 'Company targeting is not set'
                                : 'No matching tenders loaded'}
                            body={profileTargets.countries.length + profileTargets.regions.length + profileTargets.services.length === 0
                                ? 'Complete company profile targets to prioritize relevant tenders.'
                                : 'Open Tender Explorer to broaden filters or review all supported sources.'}
                            actionHref="/dashboard/settings"
                            actionLabel="Open company profile"
                        />
                    ) : (
                        <div className="divide-y divide-zinc-900">
                            {priorityOpportunities.slice(0, 8).map((tender) => (
                                <Link
                                    key={tender.id}
                                    href={`/dashboard/tenders/${tender.id}`}
                                    className="grid gap-3 px-4 py-3 hover:bg-zinc-900/60 lg:grid-cols-[92px_minmax(0,1fr)_120px_118px_150px]"
                                >
                                    <span className="text-xs font-semibold uppercase text-zinc-500">{sourceLabel(tender.source_system)}</span>
                                    <div className="min-w-0">
                                        <p className="truncate text-sm font-medium text-zinc-100">{tender.title}</p>
                                        <p className="mt-1 truncate text-xs text-zinc-500">
                                            {matchReason(tender, state.profile, serviceOptions)}
                                        </p>
                                    </div>
                                    <span className="text-sm text-zinc-300">{tender.country || 'Unknown'}</span>
                                    <span className="text-sm text-zinc-400">{deadlineState(tender.deadline)}</span>
                                    <span className={`w-fit rounded border px-2 py-1 text-xs font-semibold ${tender.compliance_analysis_available ? statusClasses('success') : statusClasses('warning')}`}>
                                        {documentAggregateLabel(tender)}
                                    </span>
                                </Link>
                            ))}
                        </div>
                    )}
                </section>

                <section className="rounded-md border border-zinc-800 bg-zinc-950">
                    <SectionHeader
                        icon={<Archive className="h-4 w-4" />}
                        title="Company Readiness"
                        description="Bid-readiness records and expiry risk."
                        actionHref="/dashboard/readiness-vault"
                        actionLabel="Readiness Vault"
                    />
                    <div className="p-4">
                        <div className={`rounded-md border px-4 py-3 ${statusClasses(readinessTone)}`}>
                            <div className="text-sm font-semibold">
                                {readinessTone === 'danger'
                                    ? 'Readiness risk requires action'
                                    : readinessTone === 'warning'
                                        ? 'Readiness has open gaps'
                                        : 'Readiness records are current'}
                            </div>
                            <p className="mt-1 text-xs opacity-80">
                                {readinessStats.expired} expired · {readinessStats.expiringSoon} expiring soon · {readinessStats.missing} missing
                            </p>
                        </div>
                        <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
                            <ReadinessMetric label="Available" value={readinessStats.available} />
                            <ReadinessMetric label="Missing" value={readinessStats.missing} urgent={readinessStats.missing > 0} />
                            <ReadinessMetric label="Expired" value={readinessStats.expired} urgent={readinessStats.expired > 0} />
                            <ReadinessMetric label="Expiring soon" value={readinessStats.expiringSoon} urgent={readinessStats.expiringSoon > 0} />
                        </div>
                        {readinessStats.missingTypes.length > 0 && (
                            <div className="mt-4 text-xs text-zinc-400">
                                Missing: {readinessStats.missingTypes.map(labelForDocumentType).join(', ')}
                            </div>
                        )}
                    </div>
                </section>
            </div>

            <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(360px,0.8fr)]">
                <section className="rounded-md border border-zinc-800 bg-zinc-950">
                    <SectionHeader
                        icon={<ShieldCheck className="h-4 w-4" />}
                        title="Recent Compliance Analyses"
                        description="Latest saved analyses for visible tenders."
                    />
                    {state.analyses.length === 0 ? (
                        <EmptySection
                            icon={<ShieldAlert className="h-5 w-5" />}
                            title="No saved analyses found"
                            body="Review a tender and run compliance analysis to populate this section."
                            actionHref="/dashboard/tenders"
                            actionLabel="Review tenders"
                        />
                    ) : (
                        <div className="divide-y divide-zinc-900">
                            {state.analyses.slice(0, 6).map(({ tender, analysis }) => {
                                const status = cleanAnalysisStatus(analysis);
                                const tone = status === 'Failed'
                                    ? 'danger'
                                    : status === 'Needs review' || status === 'Partial coverage'
                                        ? 'warning'
                                        : 'success';
                                return (
                                    <Link
                                        key={`${tender.id}-${analysis.analysis_id}`}
                                        href={`/dashboard/tenders/${tender.id}/compliance`}
                                        className="grid gap-3 px-4 py-3 text-sm hover:bg-zinc-900/60 lg:grid-cols-[minmax(0,1fr)_90px_132px_110px_124px_82px]"
                                    >
                                        <div className="min-w-0">
                                            <p className="truncate font-medium text-zinc-100">{tender.title}</p>
                                            <p className="mt-1 text-xs text-zinc-500">{sourceLabel(tender.source_system)}</p>
                                        </div>
                                        <span className={`w-fit rounded border px-2 py-1 text-xs font-semibold ${statusClasses(tone)}`}>
                                            {status}
                                        </span>
                                        <span className="text-zinc-400">{coverageStatus(analysis)}</span>
                                        <span className="text-zinc-400">{analysisRequirementCount(analysis)} requirements</span>
                                        <span className="text-zinc-500">{relativeDate(analysis.created_at)}</span>
                                        <span className="inline-flex items-center gap-1 text-xs font-semibold text-zinc-300 lg:justify-end">
                                            Open <ArrowRight className="h-3.5 w-3.5" />
                                        </span>
                                    </Link>
                                );
                            })}
                        </div>
                    )}
                </section>

                <section className="rounded-md border border-zinc-800 bg-zinc-950">
                    <SectionHeader
                        icon={<ClipboardCheck className="h-4 w-4" />}
                        title="Recent Activity"
                        description="Meaningful work only; sync and infrastructure events are excluded."
                    />
                    {recentActivity.length === 0 ? (
                        <EmptySection
                            icon={<Clock className="h-5 w-5" />}
                            title="No recent activity"
                            body="Completed compliance analyses and readiness updates will appear here."
                        />
                    ) : (
                        <div className="divide-y divide-zinc-900">
                            {recentActivity.map((event) => (
                                <Link key={event.key} href={event.href} className="block px-4 py-3 hover:bg-zinc-900/60">
                                    <p className="text-sm font-medium text-zinc-100">{event.label}</p>
                                    <p className="mt-1 truncate text-sm text-zinc-400">{event.subject}</p>
                                    <p className="mt-1 text-xs text-zinc-500">{relativeDate(event.when)}</p>
                                </Link>
                            ))}
                        </div>
                    )}
                </section>
            </div>
        </div>
    );
}

function SectionHeader({
    icon,
    title,
    description,
    actionHref,
    actionLabel,
}: {
    icon: React.ReactNode;
    title: string;
    description: string;
    actionHref?: string;
    actionLabel?: string;
}) {
    return (
        <div className="flex flex-col gap-3 border-b border-zinc-900 px-4 py-3 md:flex-row md:items-center md:justify-between">
            <div className="flex min-w-0 items-start gap-3">
                <div className="mt-0.5 text-zinc-500">{icon}</div>
                <div>
                    <h2 className="text-sm font-semibold uppercase tracking-[0.12em] text-zinc-200">{title}</h2>
                    <p className="mt-1 text-sm text-zinc-500">{description}</p>
                </div>
            </div>
            {actionHref && actionLabel && (
                <Link href={actionHref} className="text-sm font-medium text-zinc-300 hover:text-white">
                    {actionLabel}
                </Link>
            )}
        </div>
    );
}

function EmptySection({
    icon,
    title,
    body,
    actionHref,
    actionLabel,
}: {
    icon: React.ReactNode;
    title: string;
    body: string;
    actionHref?: string;
    actionLabel?: string;
}) {
    return (
        <div className="px-4 py-8 text-center">
            <div className="mx-auto flex h-10 w-10 items-center justify-center rounded-md border border-zinc-800 bg-zinc-900 text-zinc-500">
                {icon}
            </div>
            <h3 className="mt-3 text-sm font-semibold text-zinc-200">{title}</h3>
            <p className="mx-auto mt-1 max-w-md text-sm text-zinc-500">{body}</p>
            {actionHref && actionLabel && (
                <Link
                    href={actionHref}
                    className="mt-4 inline-flex items-center gap-2 rounded-md border border-zinc-700 px-3 py-2 text-sm font-medium text-zinc-200 hover:border-zinc-500"
                >
                    {actionLabel}
                    <ArrowRight className="h-4 w-4" />
                </Link>
            )}
        </div>
    );
}

function ReadinessMetric({ label, value, urgent = false }: { label: string; value: number; urgent?: boolean }) {
    return (
        <div className="rounded-md border border-zinc-800 bg-zinc-900/40 px-3 py-2">
            <div className={`text-lg font-semibold ${urgent ? 'text-amber-200' : 'text-zinc-100'}`}>{value}</div>
            <div className="text-xs text-zinc-500">{label}</div>
        </div>
    );
}

function NewCompanySteps() {
    const steps = [
        { label: 'Complete company profile', href: '/dashboard/settings' },
        { label: 'Add readiness records', href: '/dashboard/readiness-vault' },
        { label: 'Review relevant tenders', href: '/dashboard/tenders' },
        { label: 'Run first compliance analysis', href: '/dashboard/tenders' },
    ];
    return (
        <section className="rounded-md border border-zinc-800 bg-zinc-950 px-4 py-4">
            <h2 className="text-sm font-semibold uppercase tracking-[0.12em] text-zinc-200">Getting Started</h2>
            <div className="mt-3 grid gap-2 md:grid-cols-4">
                {steps.map((step) => (
                    <Link
                        key={step.label}
                        href={step.href}
                        className="rounded-md border border-zinc-800 bg-zinc-900/40 px-3 py-2 text-sm text-zinc-300 hover:border-zinc-600 hover:text-white"
                    >
                        {step.label}
                    </Link>
                ))}
            </div>
        </section>
    );
}
