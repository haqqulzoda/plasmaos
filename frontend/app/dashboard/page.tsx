'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { motion } from 'framer-motion';
import { Radar, Clock, TrendingUp, FileText, Loader2, MapPin, Banknote, ShieldCheck } from 'lucide-react';
import { api } from '@/lib/api';
import Link from 'next/link';

interface Tender {
    id: string;
    external_id: string;
    title: string;
    budget: number;
    currency: string;
    deadline: string | null;
    region: string | null;
    status: string;
    created_at: string;
}

export default function DashboardPage() {
    const router = useRouter();
    const [tenders, setTenders] = useState<Tender[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        const fetchData = async () => {
            try {
                const response = await api.get('/tenders');
                setTenders(response.data);
            } catch (err) {
                console.error('Failed to fetch data:', err);
                setError('Failed to load dashboard data');
            } finally {
                setLoading(false);
            }
        };

        fetchData();
    }, []);

    // Calculate metrics
    const totalBudget = tenders.reduce((sum, t) => sum + t.budget, 0);
    const openTenders = tenders.filter((t) => t.status === 'OPEN').length;
    const urgentTenders = tenders.filter((t) => {
        if (!t.deadline) return false;
        const daysLeft = Math.ceil(
            (new Date(t.deadline).getTime() - Date.now()) / (1000 * 60 * 60 * 24)
        );
        return daysLeft < 3 && daysLeft >= 0;
    }).length;

    // Format budget
    const formatBudget = (amount: number) => {
        if (amount >= 1_000_000_000) return `${(amount / 1_000_000_000).toFixed(1)}B`;
        if (amount >= 1_000_000) return `${(amount / 1_000_000).toFixed(0)}M`;
        return new Intl.NumberFormat('en-US').format(amount);
    };

    // Format date
    const formatDate = (dateString: string) => {
        return new Date(dateString).toLocaleDateString('en-US', {
            month: 'short',
            day: 'numeric',
        });
    };

    if (loading) {
        return (
            <div className="flex items-center justify-center h-64">
                <Loader2 className="w-8 h-8 text-indigo-500 animate-spin" />
            </div>
        );
    }

    if (error) {
        return (
            <div className="text-red-400 bg-red-500/10 border border-red-500/20 rounded-xl p-6">
                {error}
            </div>
        );
    }

    return (
        <div className="space-y-8">
            {/* Header */}
            <motion.div
                initial={{ opacity: 0, y: -20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.5 }}
            >
                <h1 className="text-3xl font-bold text-white tracking-tight">Dashboard</h1>
                <p className="text-gray-400 mt-1">Autonomous Tender Officer at a glance</p>
            </motion.div>

            {/* Stats Grid */}
            <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.5, delay: 0.1 }}
                className="grid grid-cols-1 md:grid-cols-3 gap-6"
            >
                {/* Total Budget Card */}
                <div className="bg-gray-950 border border-gray-800 rounded-xl p-6 hover:border-gray-700 transition-colors shadow-lg shadow-black/20">
                    <div className="flex items-center justify-between mb-4">
                        <div className="w-12 h-12 rounded-xl bg-emerald-500/10 flex items-center justify-center">
                            <Banknote className="w-6 h-6 text-emerald-500" />
                        </div>
                        <div className="flex items-center gap-1 text-emerald-400 text-sm">
                            <TrendingUp className="w-4 h-4" />
                            <span>Opportunities</span>
                        </div>
                    </div>
                    <h3 className="text-gray-400 text-sm mb-1">Total Available Budget</h3>
                    <p className="text-emerald-400 font-semibold text-3xl">{formatBudget(totalBudget)} UZS</p>
                    <p className="text-gray-500 text-sm mt-2">{tenders.length} active tenders</p>
                </div>

                {/* Open Tenders Card */}
                <div className="bg-gray-950 border border-gray-800 rounded-xl p-6 hover:border-gray-700 transition-colors shadow-lg shadow-black/20">
                    <div className="flex items-center justify-between mb-4">
                        <div className="w-12 h-12 rounded-xl bg-indigo-500/10 flex items-center justify-center">
                            <Radar className="w-6 h-6 text-indigo-500" />
                        </div>
                    </div>
                    <h3 className="text-gray-400 text-sm mb-1">Open Tenders</h3>
                    <p className="text-3xl font-bold text-white">{openTenders}</p>
                    <p className="text-gray-500 text-sm mt-2">Ready for proposals</p>
                </div>

                {/* Urgent Card */}
                <div className="bg-gray-950 border border-gray-800 rounded-xl p-6 hover:border-gray-700 transition-colors shadow-lg shadow-black/20">
                    <div className="flex items-center justify-between mb-4">
                        <div className="w-12 h-12 rounded-xl bg-red-500/10 flex items-center justify-center">
                            <Clock className="w-6 h-6 text-red-500" />
                        </div>
                    </div>
                    <h3 className="text-gray-400 text-sm mb-1">Urgent Deadlines</h3>
                    <p className="text-3xl font-bold text-red-400">{urgentTenders}</p>
                    <p className="text-gray-500 text-sm mt-2">Due in &lt; 3 days</p>
                </div>
            </motion.div>

            {/* Recent Tenders */}
            <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.5, delay: 0.2 }}
                className="bg-gray-950 border border-gray-800 rounded-xl overflow-hidden shadow-lg shadow-black/20"
            >
                <div className="px-6 py-4 border-b border-gray-800 flex items-center justify-between">
                    <div className="flex items-center gap-3">
                        <Radar className="w-5 h-5 text-gray-400" />
                        <h2 className="text-lg font-semibold text-white">Recent Opportunities</h2>
                    </div>
                    <Link
                        href="/dashboard/tenders"
                        className="text-indigo-400 hover:text-indigo-300 text-sm font-medium transition-colors"
                    >
                        View All →
                    </Link>
                </div>

                {tenders.length === 0 ? (
                    <div className="p-12 text-center">
                        <Radar className="w-12 h-12 text-gray-600 mx-auto mb-4" />
                        <p className="text-gray-400">No tenders yet. Seed demo data to get started.</p>
                    </div>
                ) : (
                    <div className="flex flex-col gap-4 p-4">
                        {tenders.slice(0, 5).map((tender, index) => (
                            <motion.div
                                key={tender.id}
                                initial={{ opacity: 0, x: -20 }}
                                animate={{ opacity: 1, x: 0 }}
                                transition={{ delay: index * 0.1 }}
                                className="flex flex-col lg:flex-row justify-between items-start lg:items-center bg-gray-900 border border-gray-800 rounded-xl p-5 hover:border-gray-700 hover:bg-gray-800/50 transition-all shadow-md"
                            >
                                {/* Left Panel — Context */}
                                <div className="flex-1 min-w-0">
                                    <p className="text-lg font-medium text-white line-clamp-2 mb-2">{tender.title}</p>
                                    <div className="text-sm text-gray-400 flex items-center gap-3">
                                        <a
                                            href={`https://etender.uzex.uz/lot/${tender.external_id}`}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                            className="font-mono hover:text-indigo-400 transition-colors"
                                            onClick={(e) => e.stopPropagation()}
                                        >
                                            {tender.external_id}
                                        </a>
                                        <a
                                            href={`https://etender.uzex.uz/lot/${tender.external_id}`}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                            className="px-2 py-0.5 rounded-full bg-indigo-500/10 text-indigo-400 text-xs font-medium hover:bg-indigo-500/20 transition-colors cursor-pointer"
                                            onClick={(e) => e.stopPropagation()}
                                        >
                                            {tender.status} ↗
                                        </a>
                                    </div>
                                </div>

                                {/* Middle Panel — Meta */}
                                <div className="flex items-center gap-6 mt-4 lg:mt-0 lg:mx-8 shrink-0">
                                    <p className="text-xl font-bold text-emerald-400">{formatBudget(tender.budget)} UZS</p>
                                    {tender.region && (
                                        <span className="text-gray-400 text-sm flex items-center gap-1">
                                            <MapPin className="w-3.5 h-3.5" />
                                            {tender.region}
                                        </span>
                                    )}
                                    {tender.deadline && (
                                        <span className="text-gray-400 text-sm flex items-center gap-1">
                                            <Clock className="w-3.5 h-3.5" />
                                            {formatDate(tender.deadline)}
                                        </span>
                                    )}
                                </div>

                                {/* Right Panel — Actions */}
                                <div className="flex gap-3 mt-4 lg:mt-0 shrink-0">
                                    <Link
                                        href={`/dashboard/bids/${tender.id}`}
                                        className="px-4 py-2 rounded-lg border border-gray-700 text-gray-300 hover:bg-gray-800 transition-colors text-sm flex items-center gap-2"
                                    >
                                        <ShieldCheck className="w-4 h-4" />
                                        Compliance
                                    </Link>
                                    <Link
                                        href={`/dashboard/bids/${tender.id}`}
                                        className="px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-medium transition-colors text-sm"
                                    >
                                        Draft Proposal
                                    </Link>
                                </div>
                            </motion.div>
                        ))}
                    </div>
                )}
            </motion.div>
        </div>
    );
}
