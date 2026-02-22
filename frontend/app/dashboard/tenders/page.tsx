'use client';

import { useState, useEffect, useMemo } from 'react';
import { useRouter } from 'next/navigation';
import { motion } from 'framer-motion';
import { Radar, Clock, MapPin, Banknote, FileText, Loader2, AlertCircle, RefreshCw, CheckCircle, Filter, ShieldCheck, ExternalLink } from 'lucide-react';
import { api } from '@/lib/api';
import { AxiosError } from 'axios';

interface Tender {
    id: string;
    external_id: string;
    source_url: string | null;
    title: string;
    description: string | null;
    budget: number;
    currency: string;
    deadline: string | null;
    region: string | null;
    status: string;
    category: string;
    created_at: string;
}

// Category badge colors
const CATEGORY_STYLES: Record<string, { bg: string; text: string; border: string }> = {
    'Construction': { bg: 'bg-amber-500/10', text: 'text-amber-400', border: 'border-amber-500/30' },
    'IT & Tech': { bg: 'bg-cyan-500/10', text: 'text-cyan-400', border: 'border-cyan-500/30' },
    'Medical': { bg: 'bg-pink-500/10', text: 'text-pink-400', border: 'border-pink-500/30' },
    'Office': { bg: 'bg-violet-500/10', text: 'text-violet-400', border: 'border-violet-500/30' },
    'Other': { bg: 'bg-zinc-500/10', text: 'text-zinc-400', border: 'border-zinc-500/30' },
};

const CATEGORIES = ['All', 'Construction', 'IT & Tech', 'Medical', 'Office', 'Other'];

export default function TendersPage() {
    const router = useRouter();
    const [tenders, setTenders] = useState<Tender[]>([]);
    const [isLoading, setIsLoading] = useState(true);
    const [isRefreshing, setIsRefreshing] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [draftingId, setDraftingId] = useState<string | null>(null);
    const [showToast, setShowToast] = useState(false);
    const [toastMessage, setToastMessage] = useState('');
    const [categoryFilter, setCategoryFilter] = useState('All');

    // Show toast notification
    const showNotification = (message: string) => {
        setToastMessage(message);
        setShowToast(true);
        setTimeout(() => setShowToast(false), 4000);
    };

    // Fetch tenders
    const fetchTenders = async () => {
        try {
            const response = await api.get('/tenders');
            setTenders(response.data);
            setError(null);
        } catch (err) {
            console.error('Failed to fetch tenders:', err);
            setError('Failed to load tenders');
        } finally {
            setIsLoading(false);
        }
    };

    useEffect(() => {
        fetchTenders();
    }, []);

    // Filter tenders by category
    const filteredTenders = useMemo(() => {
        if (categoryFilter === 'All') return tenders;
        return tenders.filter(t => t.category === categoryFilter);
    }, [tenders, categoryFilter]);

    // Refresh tenders from UzEx portal
    const handleRefresh = async () => {
        setIsRefreshing(true);
        setError(null);

        try {
            const response = await api.post('/tenders/refresh');
            const { new_count, updated_count } = response.data;

            showNotification(`✅ Feed refreshed! ${new_count} new, ${updated_count} updated`);

            // Reload the tenders list
            await fetchTenders();
        } catch (err) {
            const axiosError = err as AxiosError<{ detail: string }>;
            const errorMsg = axiosError.response?.data?.detail || 'Failed to refresh feed';
            setError(errorMsg);
            showNotification(`❌ ${errorMsg}`);
        } finally {
            setIsRefreshing(false);
        }
    };

    // Format budget
    const formatBudget = (amount: number, currency: string) => {
        if (amount >= 1_000_000_000) {
            return `${(amount / 1_000_000_000).toFixed(1)}B ${currency}`;
        }
        if (amount >= 1_000_000) {
            return `${(amount / 1_000_000).toFixed(0)}M ${currency}`;
        }
        return new Intl.NumberFormat('en-US').format(amount) + ` ${currency}`;
    };

    // Check if deadline is urgent (< 3 days)
    const isUrgent = (deadline: string | null) => {
        if (!deadline) return false;
        const daysLeft = Math.ceil(
            (new Date(deadline).getTime() - Date.now()) / (1000 * 60 * 60 * 24)
        );
        return daysLeft < 3 && daysLeft >= 0;
    };

    // Check if deadline passed
    const isPassed = (deadline: string | null) => {
        if (!deadline) return false;
        return new Date(deadline).getTime() < Date.now();
    };

    // Format deadline
    const formatDeadline = (deadline: string | null) => {
        if (!deadline) return 'No deadline';
        const date = new Date(deadline);
        const daysLeft = Math.ceil((date.getTime() - Date.now()) / (1000 * 60 * 60 * 24));

        if (daysLeft < 0) return 'Expired';
        if (daysLeft === 0) return 'Today';
        if (daysLeft === 1) return 'Tomorrow';
        if (daysLeft < 7) return `${daysLeft} days left`;

        return date.toLocaleDateString('en-US', {
            month: 'short',
            day: 'numeric',
        });
    };

    // Get category style
    const getCategoryStyle = (category: string) => {
        return CATEGORY_STYLES[category] || CATEGORY_STYLES['Other'];
    };

    // Handle draft proposal
    const handleDraftProposal = async (tender: Tender) => {
        setDraftingId(tender.id);

        try {
            const response = await api.post('/proposals', { tender_id: tender.id });
            const proposalId = response.data.id;
            router.push(`/dashboard/bids/${proposalId}`);
        } catch (err) {
            const axiosError = err as AxiosError<{ detail: string }>;

            if (axiosError.response?.status === 403) {
                alert('🔒 UPGRADE REQUIRED\n\nCreating proposals is an Agent feature.\n\nUpgrade to Plasma Agent to unlock AI-powered proposal drafting.');
            } else {
                alert(`Failed to create proposal: ${axiosError.response?.data?.detail || 'Unknown error'}`);
            }
        } finally {
            setDraftingId(null);
        }
    };

    if (isLoading) {
        return (
            <div className="flex items-center justify-center h-64">
                <Loader2 className="w-8 h-8 text-indigo-500 animate-spin" />
            </div>
        );
    }

    return (
        <div className="space-y-6 relative">
            {/* Toast Notification */}
            {showToast && (
                <motion.div
                    initial={{ opacity: 0, y: -20 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -20 }}
                    className="fixed top-4 right-4 z-50 bg-zinc-800 border border-zinc-700 rounded-xl px-6 py-4 shadow-xl flex items-center gap-3"
                >
                    <CheckCircle className="w-5 h-5 text-green-400" />
                    <span className="text-white font-medium">{toastMessage}</span>
                </motion.div>
            )}

            {/* Header */}
            <motion.div
                initial={{ opacity: 0, y: -20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.5 }}
                className="flex items-center justify-between"
            >
                <div className="flex items-center gap-3">
                    <div className="w-12 h-12 rounded-xl bg-indigo-500/10 flex items-center justify-center">
                        <Radar className="w-6 h-6 text-indigo-500" />
                    </div>
                    <div>
                        <h1 className="text-3xl font-bold text-white">Hunter Feed</h1>
                        <p className="text-zinc-400 mt-1">Active tender opportunities from UzEx & Etender</p>
                    </div>
                </div>

                <div className="flex items-center gap-3">
                    {/* Refresh Button */}
                    <button
                        onClick={handleRefresh}
                        disabled={isRefreshing}
                        className="inline-flex items-center gap-2 px-4 py-2 bg-zinc-800 hover:bg-zinc-700 disabled:bg-zinc-800/50 border border-zinc-700 text-white text-sm font-medium rounded-xl transition-colors"
                    >
                        <RefreshCw className={`w-4 h-4 ${isRefreshing ? 'animate-spin' : ''}`} />
                        {isRefreshing ? 'Refreshing...' : 'Refresh Feed'}
                    </button>

                    {/* Active Count Badge */}
                    <div className="flex items-center gap-2 px-4 py-2 bg-green-500/10 border border-green-500/20 rounded-full">
                        <span className="w-2 h-2 bg-green-500 rounded-full animate-pulse" />
                        <span className="text-green-400 text-sm font-medium">{filteredTenders.length} Active</span>
                    </div>
                </div>
            </motion.div>

            {/* Category Filter */}
            <motion.div
                initial={{ opacity: 0, y: -10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3, delay: 0.1 }}
                className="flex items-center gap-3"
            >
                <Filter className="w-4 h-4 text-zinc-400" />
                <span className="text-zinc-400 text-sm">Filter:</span>
                <div className="flex gap-2 flex-wrap">
                    {CATEGORIES.map(cat => (
                        <button
                            key={cat}
                            onClick={() => setCategoryFilter(cat)}
                            className={`px-3 py-1.5 text-sm font-medium rounded-lg border transition-all ${categoryFilter === cat
                                ? 'bg-indigo-600 border-indigo-500 text-white'
                                : 'bg-zinc-800/50 border-zinc-700 text-zinc-400 hover:border-zinc-600 hover:text-zinc-300'
                                }`}
                        >
                            {cat}
                        </button>
                    ))}
                </div>
            </motion.div>

            {/* Refreshing Indicator */}
            {isRefreshing && (
                <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    className="bg-indigo-500/10 border border-indigo-500/20 rounded-xl p-4 flex items-center gap-3"
                >
                    <RefreshCw className="w-5 h-5 text-indigo-400 animate-spin" />
                    <span className="text-indigo-400">Scraping UzEx portal... This may take 10-15 seconds.</span>
                </motion.div>
            )}

            {/* Error Alert */}
            {error && (
                <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    className="bg-red-500/10 border border-red-500/20 rounded-xl p-4 flex items-center gap-3"
                >
                    <AlertCircle className="w-5 h-5 text-red-400" />
                    <span className="text-red-400">{error}</span>
                </motion.div>
            )}

            {/* Tenders Grid */}
            {filteredTenders.length === 0 ? (
                <motion.div
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="bg-zinc-900 border border-zinc-800 rounded-2xl p-12 text-center"
                >
                    <Radar className="w-16 h-16 text-zinc-600 mx-auto mb-4" />
                    <h3 className="text-xl font-semibold text-white mb-2">
                        {categoryFilter !== 'All' ? `No ${categoryFilter} tenders` : 'No tenders found'}
                    </h3>
                    <p className="text-zinc-400 mb-6">
                        {categoryFilter !== 'All'
                            ? 'Try selecting a different category or refresh to get more tenders.'
                            : 'Click "Refresh Feed" to scrape the latest tenders from UzEx.'}
                    </p>
                    <button
                        onClick={handleRefresh}
                        disabled={isRefreshing}
                        className="inline-flex items-center gap-2 px-6 py-3 bg-indigo-600 hover:bg-indigo-700 text-white font-medium rounded-xl transition-colors"
                    >
                        <RefreshCw className={`w-5 h-5 ${isRefreshing ? 'animate-spin' : ''}`} />
                        Refresh from UzEx
                    </button>
                </motion.div>
            ) : (
                <motion.div
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.5, delay: 0.1 }}
                    className="bg-zinc-900 border border-zinc-800 rounded-2xl overflow-hidden"
                >
                    <div className="w-full overflow-x-auto rounded-lg">
                        <table className="w-full text-left border-collapse table-fixed">
                            <thead className="bg-gray-900/50 border-b border-gray-800 text-gray-400 text-sm">
                                <tr>
                                    <th className="py-4 px-4 font-medium w-full text-left">Tender</th>
                                    <th className="py-4 px-4 font-medium w-[110px] text-left">Category</th>
                                    <th className="py-4 px-4 font-medium w-[140px] text-left">Budget</th>
                                    <th className="py-4 px-4 font-medium w-[120px] text-left">Region</th>
                                    <th className="py-4 px-4 font-medium w-[150px] text-left">Deadline</th>
                                    <th className="py-4 px-4 font-medium w-[90px] text-left">Source</th>
                                    <th className="py-4 px-4 font-medium w-[290px] text-right">Action</th>
                                </tr>
                            </thead>
                            <tbody>
                                {filteredTenders.map((tender, index) => {
                                    const catStyle = getCategoryStyle(tender.category);
                                    return (
                                        <motion.tr
                                            key={tender.id}
                                            initial={{ opacity: 0, x: -20 }}
                                            animate={{ opacity: 1, x: 0 }}
                                            transition={{ delay: index * 0.05 }}
                                            className="border-b border-zinc-800/50 hover:bg-zinc-800/30 transition-colors group"
                                        >
                                            {/* Title Column */}
                                            <td className="py-4 px-4 w-full max-w-0">
                                                <div className="truncate block font-medium text-gray-200">
                                                    {tender.title}
                                                </div>
                                            </td>

                                            {/* Category Column */}
                                            <td className="py-4 px-4 whitespace-nowrap w-[130px]">
                                                <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium border ${catStyle.bg} ${catStyle.text} ${catStyle.border}`}>
                                                    {tender.category}
                                                </span>
                                            </td>

                                            {/* Budget Column */}
                                            <td className="py-4 px-4 whitespace-nowrap w-[140px]">
                                                <div className="flex items-center gap-2 whitespace-nowrap">
                                                    <Banknote className="w-4 h-4 text-green-400 flex-shrink-0" />
                                                    <span className="text-green-400 font-semibold whitespace-nowrap">
                                                        {formatBudget(tender.budget, tender.currency)}
                                                    </span>
                                                </div>
                                            </td>

                                            {/* Region Column */}
                                            <td className="py-4 px-4 whitespace-nowrap w-[120px]">
                                                {tender.region ? (
                                                    <span className="inline-flex items-center gap-1 px-3 py-1 bg-zinc-800 rounded-full text-sm text-zinc-300">
                                                        <MapPin className="w-3 h-3" />
                                                        {tender.region}
                                                    </span>
                                                ) : (
                                                    <span className="text-zinc-500">—</span>
                                                )}
                                            </td>

                                            {/* Deadline Column */}
                                            <td className="py-4 px-4 whitespace-nowrap w-[150px] text-gray-300 text-sm">
                                                <div
                                                    className={`flex items-center gap-2 whitespace-nowrap ${isPassed(tender.deadline)
                                                        ? 'text-zinc-500'
                                                        : isUrgent(tender.deadline)
                                                            ? 'text-red-400'
                                                            : 'text-zinc-300'
                                                        }`}
                                                >
                                                    <Clock className="w-4 h-4" />
                                                    <span className={isUrgent(tender.deadline) ? 'font-semibold' : ''}>
                                                        {formatDeadline(tender.deadline)}
                                                    </span>
                                                </div>
                                            </td>

                                            {/* Source Column */}
                                            <td className="py-4 px-4 whitespace-nowrap w-[90px]">
                                                {tender.source_url ? (
                                                    <a
                                                        href={tender.source_url}
                                                        target="_blank"
                                                        rel="noopener noreferrer"
                                                        aria-label="Open source tender page"
                                                        className="inline-flex items-center gap-1.5 text-slate-500 hover:text-indigo-400 transition-colors"
                                                    >
                                                        <ExternalLink className="w-4 h-4 flex-shrink-0" />
                                                        <span className="hidden sm:inline text-xs font-medium">View</span>
                                                    </a>
                                                ) : (
                                                    <span className="text-zinc-600 text-sm">-</span>
                                                )}
                                            </td>

                                            {/* Action Column */}
                                            <td className="py-4 px-4 whitespace-nowrap text-right w-[290px]">
                                                <div className="flex items-center justify-end gap-3">
                                                    {/* Secondary Action: Compliance (Sovereign Shield) */}
                                                    <button
                                                        onClick={() => router.push(`/dashboard/tenders/${tender.id}/compliance`)}
                                                        className="inline-flex min-w-[148px] whitespace-nowrap flex-shrink-0 items-center justify-center gap-2 h-10 px-4 rounded-lg border border-purple-500/20 bg-purple-500/10 text-purple-300 text-sm font-medium transition-all duration-200 hover:bg-purple-500/20 hover:border-purple-500/40 hover:shadow-[0_0_15px_rgba(168,85,247,0.15)]"
                                                    >
                                                        <ShieldCheck className="w-4 h-4 flex-shrink-0" />
                                                        <span>Compliance</span>
                                                    </button>

                                                    {/* Primary Action: Draft Proposal */}
                                                    <button
                                                        onClick={() => handleDraftProposal(tender)}
                                                        disabled={isPassed(tender.deadline) || draftingId === tender.id}
                                                        className="inline-flex min-w-[148px] whitespace-nowrap flex-shrink-0 items-center justify-center gap-2 h-10 px-4 rounded-lg bg-purple-600 text-white text-sm font-medium transition-all duration-200 hover:bg-purple-500 hover:shadow-[0_0_15px_rgba(147,51,234,0.3)] focus:ring-2 focus:ring-purple-400/50 disabled:bg-zinc-700 disabled:cursor-not-allowed disabled:hover:shadow-none"
                                                    >
                                                        {draftingId === tender.id ? (
                                                            <Loader2 className="w-4 h-4 animate-spin" />
                                                        ) : (
                                                            <FileText className="w-4 h-4 flex-shrink-0" />
                                                        )}
                                                        <span>Draft Proposal</span>
                                                    </button>
                                                </div>
                                            </td>
                                        </motion.tr>
                                    );
                                })}
                            </tbody>
                        </table>
                    </div>
                </motion.div>
            )}
        </div>
    );
}
