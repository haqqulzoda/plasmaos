'use client';

import { useState, useEffect, useMemo } from 'react';
import { useRouter } from 'next/navigation';
import { motion } from 'framer-motion';
import { Radar, Clock, MapPin, Banknote, FileText, Loader2, AlertCircle, RefreshCw, CheckCircle, Filter, ShieldCheck } from 'lucide-react';
import { api } from '@/lib/api';


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
            const axiosError = err as { response?: { data?: { detail?: string } } };
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
    const handleDraftProposal = (tender: Tender) => {
        router.push(`/dashboard/bids/${tender.id}`);
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

            {/* Tenders — Enterprise Action Cards */}
            {filteredTenders.length === 0 ? (
                <motion.div
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="bg-gray-900 border border-gray-800 rounded-xl p-12 text-center"
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
                <div className="flex flex-col gap-4">
                    {filteredTenders.map((tender, index) => {
                        const catStyle = getCategoryStyle(tender.category);
                        return (
                            <motion.div
                                key={tender.id}
                                initial={{ opacity: 0, x: -20 }}
                                animate={{ opacity: 1, x: 0 }}
                                transition={{ delay: index * 0.05 }}
                                className="bg-gray-900 border border-gray-800 rounded-xl p-6 hover:bg-gray-800/60 hover:border-gray-600 transition-all flex flex-col xl:flex-row justify-between items-start xl:items-center gap-6"
                            >
                                {/* Left Content — Title & ID */}
                                <div className="flex-1 max-w-3xl">
                                    <h3 className="text-lg font-semibold text-gray-100 mb-2 leading-snug">{tender.title}</h3>
                                    <div className="flex items-center gap-3">
                                        <a
                                            href={`https://etender.uzex.uz/lot/${tender.external_id}`}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                            className="text-xs text-slate-500 hover:text-indigo-400 underline-offset-2 hover:underline"
                                        >
                                            ID: {tender.external_id}
                                        </a>
                                        <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium border ${catStyle.bg} ${catStyle.text} ${catStyle.border}`}>
                                            {tender.category}
                                        </span>
                                    </div>
                                </div>

                                {/* Middle Content — Key Metrics */}
                                <div className="flex flex-wrap items-center gap-x-6 gap-y-2 shrink-0">
                                    <div>
                                        <span className="text-2xl font-bold text-emerald-400 block mb-1">
                                            {formatBudget(tender.budget, tender.currency)}
                                        </span>
                                    </div>
                                    {tender.region ? (
                                        <span className="text-sm text-gray-400 inline-flex items-center gap-1">
                                            <MapPin className="w-3.5 h-3.5" />
                                            {tender.region}
                                        </span>
                                    ) : (
                                        <span className="text-sm text-zinc-600">No region</span>
                                    )}
                                    <span
                                        className={`text-sm inline-flex items-center gap-1 ${isPassed(tender.deadline)
                                            ? 'text-zinc-500'
                                            : isUrgent(tender.deadline)
                                                ? 'text-red-400 font-semibold'
                                                : 'text-gray-400'
                                            }`}
                                    >
                                        <Clock className="w-3.5 h-3.5" />
                                        {formatDeadline(tender.deadline)}
                                    </span>
                                </div>

                                {/* Right Content — Actions */}
                                <div className="flex flex-row xl:flex-col gap-3 shrink-0">
                                    <button
                                        onClick={() => handleDraftProposal(tender)}
                                        disabled={isPassed(tender.deadline)}
                                        className="bg-indigo-600 hover:bg-indigo-500 text-white w-full px-5 py-2.5 rounded-lg font-medium transition-all text-sm inline-flex items-center justify-center gap-2 disabled:bg-zinc-700 disabled:cursor-not-allowed"
                                    >
                                        <FileText className="w-4 h-4" />
                                        Draft Proposal
                                    </button>
                                    <button
                                        onClick={() => router.push(`/dashboard/tenders/${tender.id}/compliance`)}
                                        className="border border-gray-700 hover:bg-gray-700 text-gray-300 w-full px-5 py-2.5 rounded-lg transition-colors text-sm inline-flex items-center justify-center gap-2"
                                    >
                                        <ShieldCheck className="w-4 h-4" />
                                        Compliance
                                    </button>
                                </div>
                            </motion.div>
                        );
                    })}
                </div>
            )}
        </div>
    );
}
