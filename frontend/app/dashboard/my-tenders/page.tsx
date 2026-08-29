'use client';

import { FormEvent, Suspense, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import {
    AlertCircle,
    ArrowRight,
    Bookmark,
    Building2,
    CalendarDays,
    FolderKanban,
    Loader2,
    MapPin,
    Search,
} from 'lucide-react';

import { api } from '@/lib/api';
import { EngagementWorkflowActions } from '@/components/tenders/EngagementWorkflowActions';
import {
    engagementStatusClasses,
    engagementStatusLabel,
    type MyTenderListItem,
    type MyTendersListResponse,
} from '@/types/engagement';
import {
    sourceBadgeClasses,
    sourceLabel,
    tenderStatusClasses,
    tenderStatusLabel,
} from '@/types/tender';

const PAGE_SIZE = 25;
const STATUS_FILTERS = [
    ['ACTIVE', 'Active'],
    ['ALL', 'All'],
    ['SAVED', 'Saved'],
    ['EVALUATING', 'Evaluating'],
    ['PREPARING', 'Preparing'],
    ['SUBMITTED', 'Submitted'],
    ['WON', 'Won'],
    ['LOST', 'Lost'],
    ['DISMISSED', 'Dismissed'],
] as const;

const SOURCES = [
    ['', 'All sources'],
    ['uzex', 'UzEx'],
    ['world_bank', 'World Bank'],
    ['adb', 'ADB'],
    ['giz', 'GIZ'],
    ['ebrd', 'EBRD'],
] as const;

const SOURCE_STATUSES = [
    ['', 'All tender statuses'],
    ['OPEN', 'Open'],
    ['CLOSED', 'Closed'],
    ['CANCELLED', 'Cancelled'],
    ['UNKNOWN', 'Actionability unknown'],
] as const;

function formattedDate(value: string | null) {
    if (!value) return 'Deadline unavailable';
    return new Intl.DateTimeFormat('en', {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        timeZone: 'UTC',
    }).format(new Date(value));
}

function formattedValue(item: MyTenderListItem) {
    if (item.estimated_value === null) return 'Value unavailable';
    return `${new Intl.NumberFormat('en', { maximumFractionDigits: 2 }).format(item.estimated_value)} ${item.currency ?? ''}`.trim();
}

function MyTenderCard({ item, onRefresh }: { item: MyTenderListItem; onRefresh: () => void }) {
    return (
        <article className="rounded-xl border border-zinc-800 bg-zinc-950 p-5 shadow-sm">
            <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-start">
                <div className="min-w-0 space-y-3">
                    <div className="flex flex-wrap gap-2" aria-label="Engagement and tender statuses">
                        <span className={`rounded-md border px-2 py-1 text-xs font-semibold ${engagementStatusClasses(item.engagement_status)}`}>
                            Engagement: {engagementStatusLabel(item.engagement_status)}
                        </span>
                        <span className={`rounded-md border px-2 py-1 text-xs font-semibold ${tenderStatusClasses(item.tender_status)}`}>
                            Tender: {tenderStatusLabel(item.tender_status)}
                        </span>
                        <span className={`rounded-md border px-2 py-1 text-xs font-semibold ${sourceBadgeClasses(item.source_system)}`}>
                            {sourceLabel(item.source_system)}
                        </span>
                    </div>
                    <div>
                        <h2 className="text-lg font-semibold text-white">{item.tender_title}</h2>
                        <p className="mt-1 flex items-center gap-2 text-sm text-zinc-400">
                            <Building2 className="h-4 w-4 shrink-0" aria-hidden="true" />
                            {item.buyer || 'Procuring entity unavailable'}
                        </p>
                    </div>
                    <div className="flex flex-wrap gap-x-5 gap-y-2 text-sm text-zinc-400">
                        <span className="inline-flex items-center gap-2">
                            <CalendarDays className="h-4 w-4" aria-hidden="true" />
                            Deadline: {formattedDate(item.deadline)}
                        </span>
                        <span>{formattedValue(item)}</span>
                        {(item.country || item.region) && (
                            <span className="inline-flex items-center gap-2">
                                <MapPin className="h-4 w-4" aria-hidden="true" />
                                {[item.country, item.region].filter(Boolean).join(' · ')}
                            </span>
                        )}
                    </div>
                    {item.project_external_id && (
                        <div className="inline-flex items-center gap-2 text-sm text-sky-200">
                            <FolderKanban className="h-4 w-4" aria-hidden="true" />
                            Project: {item.project_name || item.project_external_id}
                        </div>
                    )}
                </div>
                <div className="flex shrink-0 flex-wrap items-start gap-2">
                    <EngagementWorkflowActions
                        engagement={item}
                        tenderId={item.tender_id}
                        onRefresh={onRefresh}
                    />
                    <Link
                        href={`/dashboard/tenders/${item.tender_id}`}
                        className="inline-flex items-center justify-center gap-2 rounded-lg border border-zinc-700 px-3 py-2 text-sm font-semibold text-zinc-200 transition hover:border-indigo-500 hover:text-indigo-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400"
                    >
                        Open Tender
                        <ArrowRight className="h-4 w-4" aria-hidden="true" />
                    </Link>
                </div>
            </div>
        </article>
    );
}

function MyTendersContent() {
    const router = useRouter();
    const searchParams = useSearchParams();
    const searchString = searchParams.toString();
    const status = searchParams.get('status') || 'ACTIVE';
    const source = searchParams.get('source') || '';
    const tenderStatus = searchParams.get('tender_status') || '';
    const sort = searchParams.get('sort') || 'recently_updated';
    const page = Math.max(1, Number(searchParams.get('page') || '1') || 1);
    const search = searchParams.get('search') || '';
    const [searchDraft, setSearchDraft] = useState(search);
    const [data, setData] = useState<MyTendersListResponse | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [refreshVersion, setRefreshVersion] = useState(0);
    const hasLoadedRef = useRef(false);

    const updateQuery = (updates: Record<string, string>) => {
        const next = new URLSearchParams(searchString);
        Object.entries(updates).forEach(([key, value]) => {
            if (value && !(key === 'status' && value === 'ACTIVE') && !(key === 'page' && value === '1')) {
                next.set(key, value);
            } else {
                next.delete(key);
            }
        });
        router.push(`/dashboard/my-tenders${next.size ? `?${next}` : ''}`);
    };

    useEffect(() => {
        setSearchDraft(search);
    }, [search]);

    useEffect(() => {
        let cancelled = false;
        if (!hasLoadedRef.current) setLoading(true);
        setError(null);
        api.get<MyTendersListResponse>('/my-tenders', {
            params: {
                status,
                source: source || undefined,
                tender_status: tenderStatus || undefined,
                search: search || undefined,
                sort,
                offset: (page - 1) * PAGE_SIZE,
                limit: PAGE_SIZE,
            },
        }).then((response) => {
            if (!cancelled) {
                setData(response.data);
                hasLoadedRef.current = true;
            }
        }).catch((requestError: { response?: { status?: number } }) => {
            if (cancelled) return;
            const code = requestError.response?.status;
            setError(code === 401 || code === 403
                ? 'Your session no longer has access to My Tenders. Please sign in again.'
                : 'My Tenders could not be loaded. Please try again.');
        }).finally(() => {
            if (!cancelled) setLoading(false);
        });
        return () => {
            cancelled = true;
        };
    }, [page, refreshVersion, search, sort, source, status, tenderStatus]);

    const totalPages = Math.max(1, Math.ceil((data?.total ?? 0) / PAGE_SIZE));
    const countFor = useMemo(() => ({
        ACTIVE: data?.counts.active ?? 0,
        ALL: data?.counts.all ?? 0,
        SAVED: data?.counts.saved ?? 0,
        EVALUATING: data?.counts.evaluating ?? 0,
        PREPARING: data?.counts.preparing ?? 0,
        SUBMITTED: data?.counts.submitted ?? 0,
        WON: data?.counts.won ?? 0,
        LOST: data?.counts.lost ?? 0,
        DISMISSED: data?.counts.dismissed ?? 0,
    }), [data]);

    const submitSearch = (event: FormEvent) => {
        event.preventDefault();
        updateQuery({ search: searchDraft.trim(), page: '1' });
    };

    return (
        <main className="mx-auto w-full max-w-7xl space-y-6 p-4 sm:p-6 lg:p-8">
            <header>
                <div className="flex items-center gap-3">
                    <Bookmark className="h-7 w-7 text-sky-300" aria-hidden="true" />
                    <h1 className="text-3xl font-bold text-white">My Tenders</h1>
                </div>
                <p className="mt-2 text-zinc-400">Opportunities your company has explicitly saved or is pursuing.</p>
            </header>

            <section aria-label="Engagement status filters" className="flex flex-wrap gap-2">
                {STATUS_FILTERS.map(([value, label]) => (
                    <button
                        key={value}
                        type="button"
                        onClick={() => updateQuery({ status: value, page: '1' })}
                        aria-pressed={status === value}
                        className={`rounded-lg border px-3 py-2 text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400 ${
                            status === value
                                ? 'border-sky-400 bg-sky-500/20 text-sky-100'
                                : 'border-zinc-700 text-zinc-300 hover:border-zinc-500'
                        }`}
                    >
                        {label} <span className="text-xs text-zinc-400">{countFor[value]}</span>
                    </button>
                ))}
            </section>

            <section className="grid gap-3 rounded-xl border border-zinc-800 bg-zinc-950 p-4 md:grid-cols-[minmax(240px,1fr)_180px_190px_180px]">
                <form onSubmit={submitSearch} className="flex gap-2">
                    <label className="sr-only" htmlFor="my-tenders-search">Search title or buyer</label>
                    <div className="relative min-w-0 flex-1">
                        <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-zinc-500" aria-hidden="true" />
                        <input
                            id="my-tenders-search"
                            value={searchDraft}
                            onChange={(event) => setSearchDraft(event.target.value)}
                            placeholder="Search title or buyer"
                            className="w-full rounded-lg border border-zinc-700 bg-zinc-900 py-2 pl-9 pr-3 text-sm text-white outline-none focus:border-sky-400 focus:ring-1 focus:ring-sky-400"
                        />
                    </div>
                    <button type="submit" className="rounded-lg bg-sky-600 px-3 py-2 text-sm font-semibold text-white hover:bg-sky-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-300">Search</button>
                </form>
                <label className="sr-only" htmlFor="my-tenders-source">Tender source</label>
                <select id="my-tenders-source" value={source} onChange={(event) => updateQuery({ source: event.target.value, page: '1' })} className="rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-white focus:border-sky-400">
                    {SOURCES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </select>
                <label className="sr-only" htmlFor="my-tenders-source-status">Tender source status</label>
                <select id="my-tenders-source-status" value={tenderStatus} onChange={(event) => updateQuery({ tender_status: event.target.value, page: '1' })} className="rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-white focus:border-sky-400">
                    {SOURCE_STATUSES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </select>
                <label className="sr-only" htmlFor="my-tenders-sort">Sort My Tenders</label>
                <select id="my-tenders-sort" value={sort} onChange={(event) => updateQuery({ sort: event.target.value, page: '1' })} className="rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-white focus:border-sky-400">
                    <option value="recently_updated">Recently updated</option>
                    <option value="recently_added">Recently added</option>
                    <option value="deadline_soonest">Deadline soonest</option>
                </select>
            </section>

            {loading ? (
                <div role="status" aria-live="polite" className="flex min-h-56 items-center justify-center gap-3 text-zinc-300">
                    <Loader2 className="h-6 w-6 animate-spin text-sky-300" aria-hidden="true" />
                    Loading My Tenders…
                </div>
            ) : error ? (
                <div role="alert" className="flex items-center gap-3 rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-red-200">
                    <AlertCircle className="h-5 w-5" aria-hidden="true" />
                    {error}
                </div>
            ) : !data?.items.length ? (
                <div className="rounded-xl border border-dashed border-zinc-700 bg-zinc-950 px-6 py-16 text-center">
                    <Bookmark className="mx-auto h-10 w-10 text-zinc-500" aria-hidden="true" />
                    <h2 className="mt-4 text-xl font-semibold text-white">No tenders saved yet</h2>
                    <p className="mt-2 text-zinc-400">Save an opportunity from Tender Explorer to add it here.</p>
                    <Link href="/dashboard/tenders" className="mt-5 inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-300">
                        Explore Tenders <ArrowRight className="h-4 w-4" aria-hidden="true" />
                    </Link>
                </div>
            ) : (
                <div className="space-y-3">
                    {data.items.map((item) => <MyTenderCard key={item.engagement_id} item={item} onRefresh={() => setRefreshVersion((value) => value + 1)} />)}
                </div>
            )}

            {!loading && !error && data && data.total > 0 && (
                <nav aria-label="My Tenders pagination" className="flex items-center justify-between gap-4 border-t border-zinc-800 pt-4">
                    <p className="text-sm text-zinc-400">Page {page} of {totalPages} · {data.total} results</p>
                    <div className="flex gap-2">
                        <button type="button" disabled={page <= 1} onClick={() => updateQuery({ page: String(page - 1) })} className="rounded-lg border border-zinc-700 px-3 py-2 text-sm text-zinc-200 disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400">Previous</button>
                        <button type="button" disabled={page >= totalPages} onClick={() => updateQuery({ page: String(page + 1) })} className="rounded-lg border border-zinc-700 px-3 py-2 text-sm text-zinc-200 disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400">Next</button>
                    </div>
                </nav>
            )}
        </main>
    );
}

export default function MyTendersPage() {
    return (
        <Suspense fallback={<div role="status" className="p-8 text-zinc-300">Loading My Tenders…</div>}>
            <MyTendersContent />
        </Suspense>
    );
}
