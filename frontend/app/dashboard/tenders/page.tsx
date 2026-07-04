'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { motion } from 'framer-motion';
import {
    AlertCircle,
    ArrowRight,
    CalendarClock,
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
import { CENTRAL_ASIA_REGION, useGeographyMeta } from '@/lib/geography';
import { labelForService, useServiceMeta } from '@/lib/services';
import type { Tender } from '@/types/tender';
import {
    complianceUnavailableMessage,
    documentAggregateLabel,
    documentStatusClasses,
    sourceBadgeClasses,
    sourceLabel,
} from '@/types/tender';

const SOURCE_FILTERS = [
    { value: 'All', label: 'All' },
    { value: 'uzex', label: 'UzEx' },
    { value: 'world_bank', label: 'World Bank' },
    { value: 'adb', label: 'ADB' },
    { value: 'giz', label: 'GIZ' },
    { value: 'ebrd', label: 'EBRD' },
];

const DEADLINE_FILTERS = [
    { value: 'All', label: 'Any deadline' },
    { value: 'active', label: 'Active' },
    { value: 'expired', label: 'Expired' },
    { value: 'unknown', label: 'Unknown' },
];

const DOCUMENT_STATUS_FILTERS = [
    { value: 'All', label: 'Any docs' },
    { value: 'documents_available', label: 'Available' },
    { value: 'files_missing', label: 'Missing files' },
    { value: 'metadata_only', label: 'Metadata' },
    { value: 'access_required', label: 'Access required' },
    { value: 'processing', label: 'Processing' },
    { value: 'failed', label: 'Failed' },
    { value: 'no_documents_found', label: 'No docs' },
];

const SORT_OPTIONS = [
    { value: 'newest', label: 'Newest' },
    { value: 'deadline_soonest', label: 'Deadline soonest' },
    { value: 'highest_price', label: 'Highest price' },
    { value: 'document_availability', label: 'Document availability' },
    { value: 'source', label: 'Source' },
];

const SOURCE_REFRESH_ACTIONS = [
    { value: 'uzex', label: 'UzEx', endpoint: '/tenders/refresh' },
    { value: 'world_bank', label: 'World Bank', endpoint: '/tenders/sources/world-bank/sync' },
    { value: 'adb', label: 'ADB', endpoint: '/tenders/sources/adb/sync' },
    { value: 'giz', label: 'GIZ', endpoint: '/tenders/sources/giz/sync' },
    { value: 'ebrd', label: 'EBRD', endpoint: '/tenders/sources/ebrd/sync' },
] as const;

type SourceRefreshTarget = (typeof SOURCE_REFRESH_ACTIONS)[number]['value'];

const PAGE_SIZE = 50;

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

export default function TendersPage() {
    const router = useRouter();
    const fetchRequestId = useRef(0);
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

    const [sourceFilter, setSourceFilter] = useState('All');
    const [regionFilter, setRegionFilter] = useState('');
    const [countryFilters, setCountryFilters] = useState<string[]>([]);
    const [serviceFilters, setServiceFilters] = useState<string[]>([]);
    const [deadlineFilter, setDeadlineFilter] = useState('All');
    const [documentStatusFilter, setDocumentStatusFilter] = useState('All');
    const [sortFilter, setSortFilter] = useState('newest');
    const [priceMin, setPriceMin] = useState('');
    const [priceMax, setPriceMax] = useState('');
    const [keyword, setKeyword] = useState('');
    const isRefreshing = refreshingSource !== null;
    const refreshingLabel = SOURCE_REFRESH_ACTIONS.find((item) => item.value === refreshingSource)?.label;
    const centralAsiaCountries = geography.central_asia_countries;

    const showNotification = (message: string) => {
        setToastMessage(message);
        setShowToast(true);
        setTimeout(() => setShowToast(false), 4000);
    };

    const fetchTenders = useCallback(async (offset = 0, append = false) => {
        const requestId = fetchRequestId.current + 1;
        fetchRequestId.current = requestId;
        if (append) {
            setIsLoadingMore(true);
        }

        try {
            const params: Record<string, string | number> = {
                limit: PAGE_SIZE,
                offset,
            };
            if (sourceFilter !== 'All') params.source_system = sourceFilter;
            if (regionFilter) params.region = regionFilter;
            if (countryFilters.length > 0) params.countries = countryFilters.join(',');
            if (serviceFilters.length > 0) params.services = serviceFilters.join(',');
            if (deadlineFilter !== 'All') params.deadline_status = deadlineFilter;
            if (documentStatusFilter !== 'All') params.document_status = documentStatusFilter;
            if (sortFilter) params.sort = sortFilter;
            if (priceMin.trim()) params.price_min = priceMin.trim();
            if (priceMax.trim()) params.price_max = priceMax.trim();
            if (keyword.trim()) params.q = keyword.trim();

            const response = await api.get<Tender[]>('/tenders', { params });
            if (requestId !== fetchRequestId.current) return;

            setTenders((prev) => append ? [...prev, ...response.data] : response.data);
            setHasMore(response.data.length === PAGE_SIZE);
            setError(null);
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
    }, [
        countryFilters,
        deadlineFilter,
        documentStatusFilter,
        keyword,
        priceMax,
        priceMin,
        regionFilter,
        serviceFilters,
        sortFilter,
        sourceFilter,
    ]);

    useEffect(() => {
        setIsLoading(true);
        setTenders([]);
        setHasMore(false);
        fetchTenders();
    }, [fetchTenders]);

    const toggleCountry = (countryName: string) => {
        setCountryFilters((current) => current.includes(countryName)
            ? current.filter((item) => item !== countryName)
            : [...current, countryName]);
    };

    const toggleService = (serviceName: string) => {
        setServiceFilters((current) => current.includes(serviceName)
            ? current.filter((item) => item !== serviceName)
            : [...current, serviceName]);
    };

    const toggleCentralAsia = () => {
        setRegionFilter((current) => current === CENTRAL_ASIA_REGION ? '' : CENTRAL_ASIA_REGION);
    };

    const resetFilters = () => {
        setSourceFilter('All');
        setRegionFilter('');
        setCountryFilters([]);
        setServiceFilters([]);
        setDeadlineFilter('All');
        setDocumentStatusFilter('All');
        setSortFilter('newest');
        setPriceMin('');
        setPriceMax('');
        setKeyword('');
    };

    const activeFilterBadges = [
        ...(sourceFilter !== 'All'
            ? [{
                key: 'source',
                label: `Source: ${SOURCE_FILTERS.find((item) => item.value === sourceFilter)?.label ?? sourceFilter}`,
                onRemove: () => setSourceFilter('All'),
            }]
            : []),
        ...(regionFilter
            ? [{
                key: 'region',
                label: `Region: ${regionFilter}`,
                onRemove: () => setRegionFilter(''),
            }]
            : []),
        ...countryFilters.map((countryName) => ({
            key: `country-${countryName}`,
            label: countryName,
            onRemove: () => setCountryFilters((current) => current.filter((item) => item !== countryName)),
        })),
        ...serviceFilters.map((serviceName) => ({
            key: `service-${serviceName}`,
            label: labelForService(serviceName, serviceOptions),
            onRemove: () => setServiceFilters((current) => current.filter((item) => item !== serviceName)),
        })),
        ...(deadlineFilter !== 'All'
            ? [{
                key: 'deadline',
                label: `Deadline: ${DEADLINE_FILTERS.find((item) => item.value === deadlineFilter)?.label ?? deadlineFilter}`,
                onRemove: () => setDeadlineFilter('All'),
            }]
            : []),
        ...(documentStatusFilter !== 'All'
            ? [{
                key: 'documents',
                label: `Docs: ${DOCUMENT_STATUS_FILTERS.find((item) => item.value === documentStatusFilter)?.label ?? documentStatusFilter}`,
                onRemove: () => setDocumentStatusFilter('All'),
            }]
            : []),
        ...(priceMin.trim()
            ? [{
                key: 'price-min',
                label: `Min: ${priceMin}`,
                onRemove: () => setPriceMin(''),
            }]
            : []),
        ...(priceMax.trim()
            ? [{
                key: 'price-max',
                label: `Max: ${priceMax}`,
                onRemove: () => setPriceMax(''),
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
            const status = payload.status ?? 'success';
            const created = payload.new_count ?? payload.created_count ?? payload.created ?? 0;
            const updated = payload.updated_count ?? payload.updated ?? 0;
            const failed = payload.failed_count ?? payload.failed ?? 0;
            const skipped = payload.skipped_count ?? payload.skipped ?? 0;
            const message = payload.message;

            if (status === 'failed' || (target === 'uzex' && status !== 'success')) {
                const errorMsg = message || 'Failed to refresh feed';
                setError(errorMsg);
                showNotification(errorMsg);
                return;
            }

            const resultSummary = `${refreshAction.label} refreshed: ${created} new, ${updated} updated`;
            const extraSummary = failed > 0
                ? `, ${failed} failed`
                : skipped > 0
                    ? `, ${skipped} skipped`
                    : '';
            showNotification(`${resultSummary}${extraSummary}`);
            await fetchTenders();
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
                    {SOURCE_REFRESH_ACTIONS.map((action) => (
                        <button
                            key={action.value}
                            onClick={() => handleRefresh(action.value)}
                            disabled={isRefreshing}
                            title={`Refresh ${action.label}`}
                            className="inline-flex items-center gap-2 px-3 py-2 bg-zinc-900 hover:bg-zinc-800 disabled:bg-zinc-900/50 border border-zinc-700 text-white text-sm font-medium rounded-lg transition-colors"
                        >
                            <RefreshCw className={`w-4 h-4 ${refreshingSource === action.value ? 'animate-spin' : ''}`} />
                            {refreshingSource === action.value ? 'Refreshing...' : action.label}
                        </button>
                    ))}
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
                            value={keyword}
                            onChange={(event) => setKeyword(event.target.value)}
                            placeholder="Search title, buyer, project, sector, method..."
                            className="w-full rounded-lg border border-zinc-800 bg-gray-950 py-2.5 pl-9 pr-3 text-sm text-zinc-100 outline-none transition focus:border-indigo-500"
                        />
                    </label>
                    <input
                        value={priceMin}
                        onChange={(event) => setPriceMin(event.target.value)}
                        inputMode="decimal"
                        placeholder="Min price"
                        className="w-full rounded-lg border border-zinc-800 bg-gray-950 px-3 py-2.5 text-sm text-zinc-100 outline-none transition focus:border-indigo-500"
                    />
                    <input
                        value={priceMax}
                        onChange={(event) => setPriceMax(event.target.value)}
                        inputMode="decimal"
                        placeholder="Max price"
                        className="w-full rounded-lg border border-zinc-800 bg-gray-950 px-3 py-2.5 text-sm text-zinc-100 outline-none transition focus:border-indigo-500"
                    />
                    <select
                        value={sortFilter}
                        onChange={(event) => setSortFilter(event.target.value)}
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
                    <div className="flex flex-wrap items-center gap-2">
                        {SOURCE_FILTERS.map((source) => (
                            <button
                                key={source.value}
                                onClick={() => setSourceFilter(source.value)}
                                className={`rounded-lg border px-3 py-1.5 text-sm font-medium transition ${sourceFilter === source.value
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
                        className={`rounded-lg border px-3 py-1.5 text-sm font-medium transition ${regionFilter === CENTRAL_ASIA_REGION
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
                            className={`rounded-lg border px-3 py-1.5 text-sm font-medium transition ${countryFilters.includes(countryName)
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
                            className={`rounded-lg border px-3 py-1.5 text-sm font-medium transition ${serviceFilters.includes(option.value)
                                ? 'border-sky-500 bg-sky-600 text-white'
                                : 'border-zinc-800 bg-gray-950 text-zinc-400 hover:border-zinc-600 hover:text-zinc-200'
                                }`}
                        >
                            {option.label}
                        </button>
                    ))}
                </div>

                <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="flex flex-wrap items-center gap-2">
                        <CalendarClock className="h-4 w-4 text-zinc-500" />
                        {DEADLINE_FILTERS.map((filter) => (
                            <button
                                key={filter.value}
                                onClick={() => setDeadlineFilter(filter.value)}
                                className={`rounded-lg border px-3 py-1.5 text-sm font-medium transition ${deadlineFilter === filter.value
                                    ? 'border-indigo-500 bg-indigo-600 text-white'
                                    : 'border-zinc-800 bg-gray-950 text-zinc-400 hover:border-zinc-600 hover:text-zinc-200'
                                    }`}
                            >
                                {filter.label}
                            </button>
                        ))}
                    </div>

                    <div className="flex flex-wrap items-center gap-2">
                        {DOCUMENT_STATUS_FILTERS.map((filter) => (
                            <button
                                key={filter.value}
                                onClick={() => setDocumentStatusFilter(filter.value)}
                                className={`rounded-lg border px-3 py-1.5 text-sm font-medium transition ${documentStatusFilter === filter.value
                                    ? 'border-amber-500 bg-amber-600 text-white'
                                    : 'border-zinc-800 bg-gray-950 text-zinc-400 hover:border-zinc-600 hover:text-zinc-200'
                                    }`}
                            >
                                {filter.label}
                            </button>
                        ))}
                        <button
                            onClick={resetFilters}
                            className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-sm font-medium text-zinc-200 transition hover:border-zinc-500"
                        >
                            <X className="h-3.5 w-3.5" />
                            Reset
                        </button>
                    </div>
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
                            const disabledCompliance = !tender.compliance_analysis_available;
                            return (
                                <motion.div
                                    key={tender.id}
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
                                            onClick={() => router.push(`/dashboard/tenders/${tender.id}`)}
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
                                            onClick={() => router.push(`/dashboard/tenders/${tender.id}`)}
                                            className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-xs font-semibold text-zinc-200 transition hover:border-indigo-500 hover:text-indigo-200"
                                        >
                                            <FileText className="h-3.5 w-3.5" />
                                            Details
                                        </button>
                                        <button
                                            onClick={() => router.push(`/dashboard/tenders/${tender.id}/compliance`)}
                                            disabled={disabledCompliance}
                                            title={disabledCompliance ? complianceUnavailableMessage(tender) : 'Open compliance analysis'}
                                            className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-xs font-semibold text-zinc-200 transition hover:border-emerald-500 hover:text-emerald-200 disabled:cursor-not-allowed disabled:border-zinc-800 disabled:text-zinc-600"
                                        >
                                            <ShieldCheck className="h-3.5 w-3.5" />
                                            Compliance
                                        </button>
                                        <button
                                            onClick={() => router.push(`/dashboard/bids/${tender.id}`)}
                                            disabled={isExpired(tender.deadline)}
                                            className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-2 text-xs font-semibold text-white transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:bg-zinc-800 disabled:text-zinc-500"
                                        >
                                            Draft
                                            <ArrowRight className="h-3.5 w-3.5" />
                                        </button>
                                    </div>
                                </motion.div>
                            );
                        })}
                    </div>
                    {hasMore && (
                        <div className="border-t border-gray-800 p-4 text-center">
                            <button
                                onClick={() => fetchTenders(tenders.length, true)}
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
