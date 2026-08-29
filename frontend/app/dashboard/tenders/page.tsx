'use client';

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { motion } from 'framer-motion';
import {
    AlertCircle,
    CheckCircle,
    Clock,
    FileText,
    Filter,
    Loader2,
    MapPin,
    Radar,
    RefreshCw,
    Search,
    ShieldCheck,
    X,
} from 'lucide-react';

import { api } from '@/lib/api';
import { PrepareBidButton } from '@/components/bid-preparation/PrepareBidButton';
import { CENTRAL_ASIA_REGION, useGeographyMeta } from '@/lib/geography';
import { labelForService, useServiceMeta } from '@/lib/services';
import type { Tender, TenderStatus } from '@/types/tender';
import {
    complianceUnavailableMessage,
    documentAggregateLabel,
    documentStatusClasses,
    isTenderActionable,
    sourceBadgeClasses,
    sourceLabel,
    tenderActionabilityMessage,
    tenderStatusClasses,
    tenderStatusLabel,
} from '@/types/tender';

const SOURCE_FILTERS = [
    { value: 'All', label: 'All' },
    { value: 'uzex', label: 'UzEx' },
    { value: 'world_bank', label: 'World Bank' },
    { value: 'adb', label: 'ADB' },
    { value: 'giz', label: 'GIZ' },
    { value: 'ebrd', label: 'EBRD' },
];

const LIFECYCLE_FILTERS: Array<{ value: TenderStatus | 'ALL'; label: string }> = [
    { value: 'OPEN', label: 'Open' },
    { value: 'UNKNOWN', label: 'Actionability unknown' },
    { value: 'CLOSED', label: 'Closed' },
    { value: 'CANCELLED', label: 'Cancelled' },
    { value: 'ALL', label: 'All statuses' },
];

const SORT_OPTIONS = [
    { value: 'newest', label: 'Newest' },
    { value: 'deadline_soonest', label: 'Deadline soonest' },
    { value: 'highest_price', label: 'Highest price' },
    { value: 'document_availability', label: 'Document availability' },
    { value: 'source', label: 'Source' },
];

const SOURCE_REFRESH_ACTIONS = [
    { value: 'uzex', label: 'UzEx', endpoint: '/tenders/sources/uzex/refresh' },
    { value: 'world_bank', label: 'World Bank', endpoint: '/tenders/sources/world_bank/refresh' },
    { value: 'adb', label: 'ADB', endpoint: '/tenders/sources/adb/refresh' },
    { value: 'giz', label: 'GIZ', endpoint: '/tenders/sources/giz/refresh' },
    { value: 'ebrd', label: 'EBRD', endpoint: '/tenders/sources/ebrd/refresh' },
] as const;

type SourceRefreshTarget = (typeof SOURCE_REFRESH_ACTIONS)[number]['value'];
type SourceRefreshState = {
    status: string;
    lastUpdated: string | null;
    message?: string;
};

type SourceRefreshStatusPayload = {
    source_system: SourceRefreshTarget;
    status: string;
    last_updated: string | null;
    message?: string;
};

const ACTIVE_REFRESH_STATUSES = new Set(['queued', 'running']);

function sourceRefreshStatusLabel(state: SourceRefreshState | undefined, updatedAt: string): string {
    if (!state) return 'Not refreshed yet';
    if (state.status === 'queued') return 'Queued';
    if (state.status === 'running') return 'Refreshing';
    if (state.status === 'source_unavailable') return `Source unavailable · ${updatedAt}`;
    if (state.status === 'partial') return `Partial · ${updatedAt}`;
    if (state.status === 'failed') return `Refresh failed · ${updatedAt}`;
    return `Last updated: ${updatedAt}`;
}

const PAGE_SIZE = 50;
const EXPLORER_RESTORE_KEY = 'plasmaos:tender-explorer:return';
const EXPLORER_PATH = '/dashboard/tenders';

interface ExplorerQueryState {
    lifecycleStatus: TenderStatus | 'ALL';
    source: string;
    region: string;
    countries: string[];
    services: string[];
    sort: string;
    priceMin: string;
    priceMax: string;
    keyword: string;
    page: number;
}

interface ExplorerRestoreState {
    explorerUrl: string;
    tenderId: string;
    scrollY: number;
    page: number;
    cursor: number;
    createdAt: number;
}

function splitList(value: string | null) {
    if (!value) return [];
    return value.split(',').map((item) => item.trim()).filter(Boolean);
}

function positiveInteger(value: string | null) {
    if (!value) return null;
    const parsed = Number.parseInt(value, 10);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

function parseExplorerQuery(searchParams: URLSearchParams): ExplorerQueryState {
    const cursorPage = Math.floor((positiveInteger(searchParams.get('cursor')) ?? 0) / PAGE_SIZE) + 1;
    const page = positiveInteger(searchParams.get('page')) ?? cursorPage;

    const requestedStatus = (searchParams.get('status') || 'OPEN').toUpperCase();
    const lifecycleStatus = LIFECYCLE_FILTERS.some((item) => item.value === requestedStatus)
        ? requestedStatus as TenderStatus | 'ALL'
        : 'OPEN';

    return {
        lifecycleStatus,
        source: searchParams.get('source') || searchParams.get('source_system') || 'All',
        region: searchParams.get('region') || '',
        countries: splitList(searchParams.get('countries')),
        services: splitList(searchParams.get('services')),
        sort: searchParams.get('sort') || 'newest',
        priceMin: searchParams.get('min_price') || searchParams.get('price_min') || '',
        priceMax: searchParams.get('max_price') || searchParams.get('price_max') || '',
        keyword: searchParams.get('search') || searchParams.get('q') || '',
        page: Math.max(1, page),
    };
}

function buildExplorerSearch(query: ExplorerQueryState) {
    const params = new URLSearchParams();
    if (query.lifecycleStatus !== 'OPEN') params.set('status', query.lifecycleStatus.toLowerCase());
    if (query.source !== 'All') params.set('source', query.source);
    if (query.region) params.set('region', query.region);
    if (query.countries.length > 0) params.set('countries', query.countries.join(','));
    if (query.services.length > 0) params.set('services', query.services.join(','));
    if (query.keyword.trim()) params.set('search', query.keyword.trim());
    if (query.priceMin.trim()) params.set('min_price', query.priceMin.trim());
    if (query.priceMax.trim()) params.set('max_price', query.priceMax.trim());
    if (query.sort !== 'newest') params.set('sort', query.sort);
    if (query.page > 1) params.set('page', String(query.page));
    return params.toString();
}

function explorerHref(query: ExplorerQueryState) {
    const search = buildExplorerSearch(query);
    return search ? `${EXPLORER_PATH}?${search}` : EXPLORER_PATH;
}

function formatDate(value: string | null) {
    if (!value) return 'Unknown';
    return new Date(value).toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
    });
}

function publishedDateLabel(tender: Tender) {
    return tender.publication_date ? formatDate(tender.publication_date) : 'Unknown';
}

function timeRemaining(deadline: string | null) {
    if (!deadline) return 'Unknown deadline';
    const date = new Date(deadline);
    const daysLeft = Math.ceil((date.getTime() - Date.now()) / (1000 * 60 * 60 * 24));
    if (daysLeft < 0) return 'Expired';
    if (daysLeft === 0) return 'Due today';
    if (daysLeft === 1) return '1 day remaining';
    return `${daysLeft} days remaining`;
}

function isExpired(deadline: string | null) {
    return Boolean(deadline && new Date(deadline).getTime() < Date.now());
}

function tenderCategory(tender: Tender) {
    return tender.sector || tender.procurement_category || tender.category || 'Uncategorized';
}

function buyerOrProject(tender: Tender) {
    return tender.buyer || tender.project_id || 'Not specified';
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

function TendersPageContent() {
    const router = useRouter();
    const searchParams = useSearchParams();
    const fetchRequestId = useRef(0);
    const skipNextUrlFetchRef = useRef(false);
    const geography = useGeographyMeta();
    const serviceOptions = useServiceMeta();
    const [tenders, setTenders] = useState<Tender[]>([]);
    const [isLoading, setIsLoading] = useState(true);
    const [refreshingSource, setRefreshingSource] = useState<SourceRefreshTarget | null>(null);
    const [isLoadingMore, setIsLoadingMore] = useState(false);
    const [hasMore, setHasMore] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [showToast, setShowToast] = useState(false);
    const [toastMessage, setToastMessage] = useState('');
    const [draftKeyword, setDraftKeyword] = useState('');
    const [sourceRefreshState, setSourceRefreshState] = useState<
        Partial<Record<SourceRefreshTarget, SourceRefreshState>>
    >({});

    const searchString = searchParams.toString();
    const queryState = useMemo(
        () => parseExplorerQuery(new URLSearchParams(searchString)),
        [searchString],
    );
    const isRefreshing = refreshingSource !== null;
    const refreshingLabel = SOURCE_REFRESH_ACTIONS.find((item) => item.value === refreshingSource)?.label;
    const centralAsiaCountries = geography.central_asia_countries;
    const normalizedHref = useMemo(() => explorerHref(queryState), [queryState]);

    const showNotification = (message: string) => {
        setToastMessage(message);
        setShowToast(true);
        setTimeout(() => setShowToast(false), 4000);
    };

    const clearStoredRestoreState = useCallback(() => {
        if (typeof window !== 'undefined') {
            window.sessionStorage.removeItem(EXPLORER_RESTORE_KEY);
        }
    }, []);

    const replaceQuery = useCallback((patch: Partial<ExplorerQueryState>, resetPage = true) => {
        const nextQuery = {
            ...queryState,
            ...patch,
            page: resetPage ? 1 : (patch.page ?? queryState.page),
        };
        clearStoredRestoreState();
        router.replace(explorerHref(nextQuery), { scroll: false });
    }, [clearStoredRestoreState, queryState, router]);

    const fetchTenders = useCallback(async ({
        offset = 0,
        append = false,
        limit = PAGE_SIZE,
    }: {
        offset?: number;
        append?: boolean;
        limit?: number;
    } = {}) => {
        const requestId = fetchRequestId.current + 1;
        fetchRequestId.current = requestId;
        if (append) {
            setIsLoadingMore(true);
        }

        try {
            const params: Record<string, string | number> = {
                limit,
                offset,
                status: queryState.lifecycleStatus.toLowerCase(),
            };
            if (queryState.source !== 'All') params.source_system = queryState.source;
            if (queryState.region) params.region = queryState.region;
            if (queryState.countries.length > 0) params.countries = queryState.countries.join(',');
            if (queryState.services.length > 0) params.services = queryState.services.join(',');
            if (queryState.sort) params.sort = queryState.sort;
            if (queryState.priceMin.trim()) params.price_min = queryState.priceMin.trim();
            if (queryState.priceMax.trim()) params.price_max = queryState.priceMax.trim();
            if (queryState.keyword.trim()) params.q = queryState.keyword.trim();

            const response = await api.get<Tender[]>('/tenders', { params });
            if (requestId !== fetchRequestId.current) return;

            setTenders((prev) => append ? [...prev, ...response.data] : response.data);
            setHasMore(response.data.length === limit);
            setError(null);
            return response.data;
        } catch (err) {
            if (requestId !== fetchRequestId.current) return;
            console.error('Failed to fetch tenders:', err);
            setError('Failed to load tenders');
        } finally {
            if (requestId === fetchRequestId.current) {
                setIsLoading(false);
                setIsLoadingMore(false);
            }
        }
    }, [queryState]);

    useEffect(() => {
        if (normalizedHref !== `${EXPLORER_PATH}${searchString ? `?${searchString}` : ''}`) {
            router.replace(normalizedHref, { scroll: false });
        }
    }, [normalizedHref, router, searchString]);

    useEffect(() => {
        setDraftKeyword(queryState.keyword);
    }, [queryState.keyword]);

    useEffect(() => {
        let active = true;
        api.get<SourceRefreshStatusPayload[]>('/tenders/sources/refresh-status')
            .then(({ data }) => {
                if (!active) return;
                setSourceRefreshState(Object.fromEntries(
                    data.map((item) => [
                        item.source_system,
                        {
                            status: item.status,
                            lastUpdated: item.last_updated,
                            message: item.message,
                        },
                    ]),
                ));
            })
            .catch(() => {
                // Refresh metadata is supplementary; tender loading remains independent.
            });
        return () => {
            active = false;
        };
    }, []);

    const activeRefreshSources = useMemo(
        () => Object.entries(sourceRefreshState)
            .filter(([, state]) => state && ACTIVE_REFRESH_STATUSES.has(state.status))
            .map(([source]) => source as SourceRefreshTarget)
            .sort()
            .join(','),
        [sourceRefreshState],
    );

    useEffect(() => {
        if (!activeRefreshSources) return;
        let active = true;
        let requestInFlight = false;
        const pendingSources = new Set(activeRefreshSources.split(','));

        const pollRefreshStatus = async () => {
            if (requestInFlight) return;
            requestInFlight = true;
            try {
                const { data } = await api.get<SourceRefreshStatusPayload[]>(
                    '/tenders/sources/refresh-status',
                );
                if (!active) return;
                const completedPendingSource = data.some(
                    (item) => pendingSources.has(item.source_system)
                        && !ACTIVE_REFRESH_STATUSES.has(item.status),
                );
                setSourceRefreshState(Object.fromEntries(
                    data.map((item) => [
                        item.source_system,
                        {
                            status: item.status,
                            lastUpdated: item.last_updated,
                            message: item.message,
                        },
                    ]),
                ));
                if (completedPendingSource) {
                    await fetchTenders({ limit: PAGE_SIZE * queryState.page });
                }
            } catch {
                // Keep the last durable status; polling will retry on the next interval.
            } finally {
                requestInFlight = false;
            }
        };

        const interval = window.setInterval(pollRefreshStatus, 3000);
        void pollRefreshStatus();
        return () => {
            active = false;
            window.clearInterval(interval);
        };
    }, [activeRefreshSources, fetchTenders, queryState.page]);

    useEffect(() => {
        if (draftKeyword === queryState.keyword) return;

        const timeout = window.setTimeout(() => {
            replaceQuery({ keyword: draftKeyword });
        }, 350);

        return () => window.clearTimeout(timeout);
    }, [draftKeyword, queryState.keyword, replaceQuery]);

    useEffect(() => {
        if (skipNextUrlFetchRef.current) {
            skipNextUrlFetchRef.current = false;
            return;
        }

        setIsLoading(true);
        setTenders([]);
        setHasMore(false);
        fetchTenders({ limit: PAGE_SIZE * queryState.page });
    }, [fetchTenders, queryState.page]);

    useEffect(() => {
        if (isLoading || isLoadingMore || typeof window === 'undefined') return;

        const rawState = window.sessionStorage.getItem(EXPLORER_RESTORE_KEY);
        if (!rawState) return;

        let restoreState: ExplorerRestoreState | null = null;
        try {
            restoreState = JSON.parse(rawState) as ExplorerRestoreState;
        } catch {
            window.sessionStorage.removeItem(EXPLORER_RESTORE_KEY);
            return;
        }

        if (!restoreState || restoreState.explorerUrl !== normalizedHref) return;

        const row = window.document.querySelector<HTMLElement>(`[data-tender-id="${CSS.escape(restoreState.tenderId)}"]`);
        window.requestAnimationFrame(() => {
            if (row) {
                row.scrollIntoView({ block: 'center' });
            } else {
                window.scrollTo({ top: restoreState.scrollY, behavior: 'auto' });
            }
            window.sessionStorage.removeItem(EXPLORER_RESTORE_KEY);
        });
    }, [isLoading, isLoadingMore, normalizedHref, tenders]);

    const toggleCountry = (countryName: string) => {
        replaceQuery({
            countries: queryState.countries.includes(countryName)
                ? queryState.countries.filter((item) => item !== countryName)
                : [...queryState.countries, countryName],
        });
    };

    const toggleService = (serviceName: string) => {
        replaceQuery({
            services: queryState.services.includes(serviceName)
                ? queryState.services.filter((item) => item !== serviceName)
                : [...queryState.services, serviceName],
        });
    };

    const toggleCentralAsia = () => {
        replaceQuery({ region: queryState.region === CENTRAL_ASIA_REGION ? '' : CENTRAL_ASIA_REGION });
    };

    const resetFilters = () => {
        clearStoredRestoreState();
        router.replace(EXPLORER_PATH, { scroll: false });
    };

    const openTenderRoute = (tenderId: string, href: string) => {
        if (typeof window !== 'undefined') {
            const restoreState: ExplorerRestoreState = {
                explorerUrl: normalizedHref,
                tenderId,
                scrollY: window.scrollY,
                page: queryState.page,
                cursor: (queryState.page - 1) * PAGE_SIZE,
                createdAt: Date.now(),
            };
            window.sessionStorage.setItem(EXPLORER_RESTORE_KEY, JSON.stringify(restoreState));
        }
        router.push(href);
    };

    const loadMore = async () => {
        const response = await fetchTenders({ offset: tenders.length, append: true });
        if (response && response.length > 0) {
            skipNextUrlFetchRef.current = true;
            replaceQuery({ page: queryState.page + 1 }, false);
        }
    };

    const activeFilterBadges = [
        ...(queryState.lifecycleStatus !== 'OPEN'
            ? [{
                key: 'status',
                label: `Status: ${LIFECYCLE_FILTERS.find((item) => item.value === queryState.lifecycleStatus)?.label}`,
                onRemove: () => replaceQuery({ lifecycleStatus: 'OPEN' }),
            }]
            : []),
        ...(queryState.source !== 'All'
            ? [{
                key: 'source',
                label: `Source: ${SOURCE_FILTERS.find((item) => item.value === queryState.source)?.label ?? queryState.source}`,
                onRemove: () => replaceQuery({ source: 'All' }),
            }]
            : []),
        ...(queryState.region
            ? [{
                key: 'region',
                label: `Region: ${queryState.region}`,
                onRemove: () => replaceQuery({ region: '' }),
            }]
            : []),
        ...queryState.countries.map((countryName) => ({
            key: `country-${countryName}`,
            label: countryName,
            onRemove: () => replaceQuery({ countries: queryState.countries.filter((item) => item !== countryName) }),
        })),
        ...queryState.services.map((serviceName) => ({
            key: `service-${serviceName}`,
            label: labelForService(serviceName, serviceOptions),
            onRemove: () => replaceQuery({ services: queryState.services.filter((item) => item !== serviceName) }),
        })),
        ...(queryState.priceMin.trim()
            ? [{
                key: 'price-min',
                label: `Min: ${queryState.priceMin}`,
                onRemove: () => replaceQuery({ priceMin: '' }),
            }]
            : []),
        ...(queryState.priceMax.trim()
            ? [{
                key: 'price-max',
                label: `Max: ${queryState.priceMax}`,
                onRemove: () => replaceQuery({ priceMax: '' }),
            }]
            : []),
    ];

    const handleRefresh = async (target: SourceRefreshTarget) => {
        const refreshAction = SOURCE_REFRESH_ACTIONS.find((item) => item.value === target);
        if (!refreshAction) return;

        setRefreshingSource(target);
        setError(null);

        try {
            const response = await api.post(refreshAction.endpoint);
            const payload = response.data;
            const status = payload.status ?? 'failed';
            const lastUpdated = payload.last_updated ?? null;
            setSourceRefreshState((previous) => ({
                ...previous,
                [target]: { status, lastUpdated, message: payload.message },
            }));

            if (status === 'source_unavailable') {
                const errorMsg = 'Source unavailable. Existing tenders are still shown.';
                setError(errorMsg);
                showNotification(errorMsg);
                return;
            }
            if (status === 'failed') {
                const errorMsg = payload.message || 'Refresh failed. Existing tenders are still shown.';
                setError(errorMsg);
                showNotification(errorMsg);
                return;
            }
            if (status === 'queued' || status === 'running') {
                showNotification(payload.reused ? 'Already refreshing' : 'Refreshing');
                return;
            }
            if (status === 'fresh') {
                showNotification('Updated successfully');
                return;
            }

            showNotification('Updated successfully');
            await fetchTenders({ limit: PAGE_SIZE * queryState.page });
        } catch (err) {
            const axiosError = err as { response?: { data?: { detail?: string } } };
            const errorMsg = axiosError.response?.data?.detail || 'Failed to refresh feed';
            setError(errorMsg);
            showNotification(errorMsg);
        } finally {
            setRefreshingSource(null);
        }
    };

    return (
        <div className="space-y-5 relative">
            {showToast && (
                <motion.div
                    initial={{ opacity: 0, y: -20 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="fixed top-4 right-4 z-50 bg-zinc-900 border border-zinc-700 rounded-lg px-5 py-3 shadow-xl flex items-center gap-3"
                >
                    <CheckCircle className="w-4 h-4 text-emerald-400" />
                    <span className="text-white text-sm font-medium">{toastMessage}</span>
                </motion.div>
            )}

            <motion.div
                initial={{ opacity: 0, y: -14 }}
                animate={{ opacity: 1, y: 0 }}
                className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between"
            >
                <div className="flex items-center gap-3">
                    <div className="w-11 h-11 rounded-lg bg-indigo-500/10 flex items-center justify-center">
                        <Radar className="w-5 h-5 text-indigo-400" />
                    </div>
                    <div>
                        <h1 className="text-2xl font-bold text-white">Tender Explorer</h1>
                        <p className="text-zinc-400 text-sm mt-1">UzEx enterprise, World Bank, ADB, GIZ, and EBRD opportunities in one worklist</p>
                    </div>
                </div>

                <div className="flex flex-wrap items-center gap-2">
                    {SOURCE_REFRESH_ACTIONS.map((action) => {
                        const refreshState = sourceRefreshState[action.value];
                        const updatedAt = refreshState?.lastUpdated
                            ? new Date(refreshState.lastUpdated).toLocaleString()
                            : 'Not refreshed yet';
                        const statusLabel = sourceRefreshStatusLabel(refreshState, updatedAt);
                        return (
                            <div key={action.value} className="flex flex-col gap-1">
                                <button
                                    onClick={() => handleRefresh(action.value)}
                                    disabled={isRefreshing}
                                    title={`Refresh ${action.label}`}
                                    className="inline-flex items-center justify-center gap-2 px-3 py-2 bg-zinc-900 hover:bg-zinc-800 disabled:bg-zinc-900/50 border border-zinc-700 text-white text-sm font-medium rounded-lg transition-colors"
                                >
                                    <RefreshCw className={`w-4 h-4 ${refreshingSource === action.value ? 'animate-spin' : ''}`} />
                                    {refreshingSource === action.value ? 'Refreshing...' : action.label}
                                </button>
                                <span
                                    className="text-[10px] text-zinc-500"
                                    title={refreshState?.message || updatedAt}
                                >
                                    {statusLabel}
                                </span>
                            </div>
                        );
                    })}
                    <div className="px-3 py-2 rounded-lg border border-zinc-700 bg-zinc-900 text-sm text-zinc-300">
                        {tenders.length} shown
                    </div>
                </div>
            </motion.div>

            <motion.div
                initial={{ opacity: 0, y: -8 }}
                animate={{ opacity: 1, y: 0 }}
                className="rounded-lg border border-zinc-800 bg-zinc-950 p-4 space-y-4"
            >
                <div className="grid grid-cols-1 gap-3 xl:grid-cols-[1.4fr_0.7fr_0.7fr_0.7fr]">
                    <label className="relative">
                        <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-500" />
                        <input
                            value={draftKeyword}
                            onChange={(event) => setDraftKeyword(event.target.value)}
                            placeholder="Search title, buyer, project, sector, method..."
                            className="w-full rounded-lg border border-zinc-800 bg-gray-950 py-2.5 pl-9 pr-3 text-sm text-zinc-100 outline-none transition focus:border-indigo-500"
                        />
                    </label>
                    <input
                        value={queryState.priceMin}
                        onChange={(event) => replaceQuery({ priceMin: event.target.value })}
                        inputMode="decimal"
                        placeholder="Min price"
                        className="w-full rounded-lg border border-zinc-800 bg-gray-950 px-3 py-2.5 text-sm text-zinc-100 outline-none transition focus:border-indigo-500"
                    />
                    <input
                        value={queryState.priceMax}
                        onChange={(event) => replaceQuery({ priceMax: event.target.value })}
                        inputMode="decimal"
                        placeholder="Max price"
                        className="w-full rounded-lg border border-zinc-800 bg-gray-950 px-3 py-2.5 text-sm text-zinc-100 outline-none transition focus:border-indigo-500"
                    />
                    <select
                        value={queryState.sort}
                        onChange={(event) => replaceQuery({ sort: event.target.value })}
                        className="w-full rounded-lg border border-zinc-800 bg-gray-950 px-3 py-2.5 text-sm text-zinc-100 outline-none transition focus:border-indigo-500"
                    >
                        {SORT_OPTIONS.map((option) => (
                            <option key={option.value} value={option.value}>
                                {option.label}
                            </option>
                        ))}
                    </select>
                </div>

                <div className="flex flex-wrap items-center gap-2">
                    <Filter className="h-4 w-4 text-zinc-500" />
                    <select
                        value={queryState.lifecycleStatus}
                        onChange={(event) => replaceQuery({ lifecycleStatus: event.target.value as TenderStatus | 'ALL' })}
                        aria-label="Tender lifecycle status"
                        className="rounded-lg border border-zinc-800 bg-gray-950 px-3 py-1.5 text-sm font-medium text-zinc-300 outline-none transition focus:border-indigo-500"
                    >
                        {LIFECYCLE_FILTERS.map((option) => (
                            <option key={option.value} value={option.value}>{option.label}</option>
                        ))}
                    </select>
                    <div className="flex flex-wrap items-center gap-2">
                        {SOURCE_FILTERS.map((source) => (
                            <button
                                key={source.value}
                                onClick={() => replaceQuery({ source: source.value })}
                                className={`rounded-lg border px-3 py-1.5 text-sm font-medium transition ${queryState.source === source.value
                                    ? 'border-indigo-500 bg-indigo-600 text-white'
                                    : 'border-zinc-800 bg-gray-950 text-zinc-400 hover:border-zinc-600 hover:text-zinc-200'
                                    }`}
                            >
                                {source.label}
                            </button>
                        ))}
                    </div>

                    <button
                        onClick={toggleCentralAsia}
                        className={`rounded-lg border px-3 py-1.5 text-sm font-medium transition ${queryState.region === CENTRAL_ASIA_REGION
                            ? 'border-emerald-500 bg-emerald-600 text-white'
                            : 'border-zinc-800 bg-gray-950 text-zinc-400 hover:border-zinc-600 hover:text-zinc-200'
                            }`}
                    >
                        Central Asia
                    </button>
                </div>

                <div className="flex flex-wrap items-center gap-2">
                    <MapPin className="h-4 w-4 text-zinc-500" />
                    {centralAsiaCountries.map((countryName) => (
                        <button
                            key={countryName}
                            onClick={() => toggleCountry(countryName)}
                            className={`rounded-lg border px-3 py-1.5 text-sm font-medium transition ${queryState.countries.includes(countryName)
                                ? 'border-emerald-500 bg-emerald-600 text-white'
                                : 'border-zinc-800 bg-gray-950 text-zinc-400 hover:border-zinc-600 hover:text-zinc-200'
                                }`}
                        >
                            {countryName}
                        </button>
                    ))}
                </div>

                <div className="flex flex-wrap items-center gap-2">
                    {serviceOptions.map((option) => (
                        <button
                            key={option.value}
                            onClick={() => toggleService(option.value)}
                            className={`rounded-lg border px-3 py-1.5 text-sm font-medium transition ${queryState.services.includes(option.value)
                                ? 'border-sky-500 bg-sky-600 text-white'
                                : 'border-zinc-800 bg-gray-950 text-zinc-400 hover:border-zinc-600 hover:text-zinc-200'
                                }`}
                        >
                            {option.label}
                        </button>
                    ))}
                </div>

                <div className="flex flex-wrap items-center justify-end gap-2">
                    <button
                        onClick={resetFilters}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-sm font-medium text-zinc-200 transition hover:border-zinc-500"
                    >
                        <X className="h-3.5 w-3.5" />
                        Reset
                    </button>
                </div>

                {activeFilterBadges.length > 0 && (
                    <div className="flex flex-wrap items-center gap-2 border-t border-zinc-900 pt-3">
                        {activeFilterBadges.map((badge) => (
                            <button
                                key={badge.key}
                                onClick={badge.onRemove}
                                className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-700 bg-zinc-900 px-2.5 py-1 text-xs font-medium text-zinc-300 transition hover:border-zinc-500 hover:text-white"
                            >
                                {badge.label}
                                <X className="h-3 w-3" />
                            </button>
                        ))}
                    </div>
                )}
            </motion.div>

            {isRefreshing && (
                <div className="bg-indigo-500/10 border border-indigo-500/20 rounded-lg p-3 flex items-center gap-3">
                    <RefreshCw className="w-4 h-4 text-indigo-400 animate-spin" />
                    <span className="text-indigo-300 text-sm">Refreshing {refreshingLabel} source feed.</span>
                </div>
            )}

            {error && (
                <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-3 flex items-center gap-3">
                    <AlertCircle className="w-4 h-4 text-red-400" />
                    <span className="text-red-300 text-sm">{error}</span>
                </div>
            )}

            {isLoading ? (
                <div className="flex items-center justify-center h-64">
                    <Loader2 className="w-7 h-7 text-indigo-500 animate-spin" />
                </div>
            ) : tenders.length === 0 ? (
                <div className="bg-gray-900 border border-gray-800 rounded-lg p-10 text-center">
                    <Radar className="w-12 h-12 text-zinc-600 mx-auto mb-4" />
                    <h3 className="text-lg font-semibold text-white mb-2">No tenders found</h3>
                    <p className="text-zinc-400 text-sm">Adjust filters or refresh the relevant source sync.</p>
                </div>
            ) : (
                <div className="overflow-hidden rounded-lg border border-gray-800 bg-gray-950">
                    <div className="hidden xl:grid grid-cols-[minmax(0,2fr)_1fr_1fr_1fr_1fr_1fr_220px] gap-4 border-b border-gray-800 bg-gray-900/70 px-4 py-3 text-[11px] font-semibold uppercase tracking-wide text-zinc-500">
                        <span>Tender</span>
                        <span>Location</span>
                        <span>Buyer / Project</span>
                        <span>Price</span>
                        <span>Deadline</span>
                        <span>Category / Method</span>
                        <span>Actions</span>
                    </div>
                    <div className="divide-y divide-gray-900">
                        {tenders.map((tender, index) => {
                            const actionable = isTenderActionable(tender);
                            const disabledCompliance = !actionable || !tender.compliance_analysis_available;
                            const actionabilityMessage = tenderActionabilityMessage(tender.status);
                            return (
                                <motion.div
                                    key={tender.id}
                                    data-tender-id={tender.id}
                                    initial={{ opacity: 0, y: 8 }}
                                    animate={{ opacity: 1, y: 0 }}
                                    transition={{ delay: Math.min(index * 0.02, 0.2) }}
                                    className="grid grid-cols-1 gap-4 px-4 py-4 transition hover:bg-gray-900/70 xl:grid-cols-[minmax(0,2fr)_1fr_1fr_1fr_1fr_1fr_220px]"
                                >
                                    <div className="min-w-0 space-y-2">
                                        <div className="flex flex-wrap items-center gap-2">
                                            <span className={`inline-flex rounded-md border px-2 py-1 text-[11px] font-semibold ${sourceBadgeClasses(tender.source_system)}`}>
                                                {sourceLabel(tender.source_system)}
                                            </span>
                                            <span className={`inline-flex rounded-md border px-2 py-1 text-[11px] font-semibold ${tenderStatusClasses(tender.status)}`}>
                                                {tenderStatusLabel(tender.status)}
                                            </span>
                                            {tender.source_url ? (
                                                <a
                                                    href={tender.source_url}
                                                    target="_blank"
                                                    rel="noopener noreferrer"
                                                    title="Open source notice"
                                                    className="text-[11px] text-zinc-500 underline-offset-2 transition hover:text-indigo-300 hover:underline"
                                                >
                                                    ID {tender.external_id}
                                                </a>
                                            ) : (
                                                <span className="text-[11px] text-zinc-500">ID {tender.external_id}</span>
                                            )}
                                            <span className={`inline-flex rounded-md border px-2 py-1 text-[11px] font-semibold ${documentStatusClasses(tender.document_status)}`}>
                                                {documentAggregateLabel(tender)}
                                            </span>
                                        </div>
                                        <button
                                            onClick={() => openTenderRoute(tender.id, `/dashboard/tenders/${tender.id}`)}
                                            className="block text-left text-[15px] font-semibold leading-snug text-gray-100 hover:text-indigo-300"
                                        >
                                            {tender.title}
                                        </button>
                                        <div className="text-[12px] text-zinc-500">
                                            Published {publishedDateLabel(tender)}
                                        </div>
                                    </div>

                                    <div className="text-sm text-zinc-300">
                                        <div className="flex items-center gap-1.5">
                                            <MapPin className="h-3.5 w-3.5 text-zinc-500" />
                                            <span>{tender.country || 'Unknown Region'}</span>
                                        </div>
                                        <p className="mt-1 text-xs text-zinc-500">{tender.region || 'No region'}</p>
                                    </div>

                                    <div className="min-w-0 text-sm text-zinc-300">
                                        <p className="truncate">{buyerOrProject(tender)}</p>
                                        {tender.project_id && tender.buyer && (
                                            <p className="mt-1 text-xs text-zinc-500 truncate">{tender.project_id}</p>
                                        )}
                                    </div>

                                    <div className="text-sm text-zinc-300">
                                        <p className={(tender.price_display || tender.budget > 0) ? 'font-semibold text-emerald-300' : 'text-zinc-500'}>
                                            {priceDisplay(tender)}
                                        </p>
                                    </div>

                                    <div className="text-sm">
                                        <div className={`flex items-center gap-1.5 ${isExpired(tender.deadline) ? 'text-zinc-500' : 'text-zinc-300'}`}>
                                            <Clock className="h-3.5 w-3.5" />
                                            <span>{timeRemaining(tender.deadline)}</span>
                                        </div>
                                        <p className="mt-1 text-xs text-zinc-500">{formatDate(tender.deadline)}</p>
                                    </div>

                                    <div className="min-w-0 text-sm text-zinc-300">
                                        <p className="truncate">{tenderCategory(tender)}</p>
                                        <p className="mt-1 text-xs text-zinc-500 truncate">{tender.procurement_method || tender.notice_type || 'Method not specified'}</p>
                                    </div>

                                    <div className="flex flex-wrap items-center gap-2 xl:justify-end">
                                        <button
                                            onClick={() => openTenderRoute(tender.id, `/dashboard/tenders/${tender.id}`)}
                                            className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-xs font-semibold text-zinc-200 transition hover:border-indigo-500 hover:text-indigo-200"
                                        >
                                            <FileText className="h-3.5 w-3.5" />
                                            Details
                                        </button>
                                        <button
                                            onClick={() => openTenderRoute(tender.id, `/dashboard/tenders/${tender.id}/compliance`)}
                                            disabled={disabledCompliance}
                                            title={!actionable ? actionabilityMessage : disabledCompliance ? complianceUnavailableMessage(tender) : 'Open compliance analysis'}
                                            className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-xs font-semibold text-zinc-200 transition hover:border-emerald-500 hover:text-emerald-200 disabled:cursor-not-allowed disabled:border-zinc-800 disabled:text-zinc-600"
                                        >
                                            <ShieldCheck className="h-3.5 w-3.5" />
                                            Compliance
                                        </button>
                                        <PrepareBidButton
                                            tenderId={tender.id}
                                            disabled={!actionable || isExpired(tender.deadline)}
                                            title={!actionable ? actionabilityMessage : isExpired(tender.deadline) ? 'Tender deadline has passed' : 'Start bid preparation'}
                                        />
                                    </div>
                                </motion.div>
                            );
                        })}
                    </div>
                    {hasMore && (
                        <div className="border-t border-gray-800 p-4 text-center">
                            <button
                                onClick={loadMore}
                                disabled={isLoadingMore}
                                className="inline-flex items-center gap-2 rounded-lg border border-zinc-700 bg-zinc-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-zinc-800 disabled:opacity-60"
                            >
                                <Loader2 className={`w-4 h-4 ${isLoadingMore ? 'animate-spin' : 'hidden'}`} />
                                {isLoadingMore ? 'Loading...' : 'Load more'}
                            </button>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}

export default function TendersPage() {
    return (
        <Suspense fallback={(
            <div className="flex h-64 items-center justify-center">
                <Loader2 className="h-7 w-7 animate-spin text-indigo-500" />
            </div>
        )}
        >
            <TendersPageContent />
        </Suspense>
    );
}
