'use client';

import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { FileText, Loader2, Clock, Banknote, MapPin, ArrowRight } from 'lucide-react';
import { api } from '@/lib/api';
import Link from 'next/link';

interface Proposal {
    id: string;
    tender_id: string;
    status: string;
    ai_confidence_score: number;
    structured_data: {
        our_price?: number;
        delivery_days?: number;
    } | null;
    tender_title: string;
    tender_budget: number;
    tender_currency: string;
    tender_deadline: string | null;
    tender_region: string | null;
    created_at: string;
}

export default function BidsPage() {
    const [proposals, setProposals] = useState<Proposal[]>([]);
    const [isLoading, setIsLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        const fetchProposals = async () => {
            try {
                const response = await api.get('/proposals');
                setProposals(response.data);
            } catch (err) {
                console.error('Failed to fetch proposals:', err);
                setError('Failed to load proposals');
            } finally {
                setIsLoading(false);
            }
        };

        fetchProposals();
    }, []);

    // Format budget
    const formatBudget = (amount: number, currency: string) => {
        if (amount >= 1_000_000_000) return `${(amount / 1_000_000_000).toFixed(1)}B ${currency}`;
        if (amount >= 1_000_000) return `${(amount / 1_000_000).toFixed(0)}M ${currency}`;
        return new Intl.NumberFormat('en-US').format(amount) + ` ${currency}`;
    };

    // Format date
    const formatDate = (dateString: string) => {
        return new Date(dateString).toLocaleDateString('en-US', {
            month: 'short',
            day: 'numeric',
            year: 'numeric',
        });
    };

    // Get status color
    const getStatusColor = (status: string) => {
        switch (status) {
            case 'DRAFT':
                return 'bg-yellow-500/10 text-yellow-400';
            case 'GENERATING':
                return 'bg-blue-500/10 text-blue-400';
            case 'COMPLETED':
                return 'bg-green-500/10 text-green-400';
            case 'SUBMITTED':
                return 'bg-purple-500/10 text-purple-400';
            default:
                return 'bg-zinc-800 text-zinc-400';
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
        <div className="space-y-6">
            {/* Header */}
            <motion.div
                initial={{ opacity: 0, y: -20 }}
                animate={{ opacity: 1, y: 0 }}
                className="flex items-center justify-between"
            >
                <div className="flex items-center gap-3">
                    <div className="w-12 h-12 rounded-xl bg-purple-500/10 flex items-center justify-center">
                        <FileText className="w-6 h-6 text-purple-500" />
                    </div>
                    <div>
                        <h1 className="text-3xl font-bold text-white">My Bids</h1>
                        <p className="text-zinc-400 mt-1">Manage your proposal drafts</p>
                    </div>
                </div>
                <div className="flex items-center gap-2 px-4 py-2 bg-purple-500/10 border border-purple-500/20 rounded-full">
                    <span className="text-purple-400 text-sm font-medium">{proposals.length} Proposals</span>
                </div>
            </motion.div>

            {/* Error Alert */}
            {error && (
                <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    className="bg-red-500/10 border border-red-500/20 rounded-xl p-4 text-red-400"
                >
                    {error}
                </motion.div>
            )}

            {/* Proposals List */}
            {proposals.length === 0 ? (
                <motion.div
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="bg-gray-900 border border-gray-800 rounded-xl p-12 text-center"
                >
                    <FileText className="w-16 h-16 text-zinc-600 mx-auto mb-4" />
                    <h3 className="text-xl font-semibold text-white mb-2">No proposals yet</h3>
                    <p className="text-zinc-400 mb-6">Draft your first proposal from the Hunter Feed.</p>
                    <Link
                        href="/dashboard/tenders"
                        className="inline-flex items-center gap-2 px-6 py-3 bg-indigo-600 hover:bg-indigo-700 text-white font-medium rounded-xl transition-colors"
                    >
                        Browse Tenders
                        <ArrowRight className="w-4 h-4" />
                    </Link>
                </motion.div>
            ) : (
                <motion.div
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="space-y-4"
                >
                    {proposals.map((proposal, index) => (
                        <motion.div
                            key={proposal.id}
                            initial={{ opacity: 0, x: -20 }}
                            animate={{ opacity: 1, x: 0 }}
                            transition={{ delay: index * 0.05 }}
                        >
                            <Link
                                href={`/dashboard/bids/${proposal.id}`}
                                className="block bg-gray-900 border border-gray-800 rounded-xl p-6 hover:border-indigo-500/50 transition-colors group"
                            >
                                <div className="flex items-start justify-between">
                                    <div className="flex-1 min-w-0">
                                        <div className="flex items-center gap-3 mb-2">
                                            <h3 className="text-lg font-semibold text-white truncate group-hover:text-indigo-400 transition-colors">
                                                {proposal.tender_title}
                                            </h3>
                                            <span className={`px-3 py-1 rounded-full text-xs font-medium ${getStatusColor(proposal.status)}`}>
                                                {proposal.status}
                                            </span>
                                        </div>

                                        <div className="flex items-center gap-6 text-sm text-zinc-400">
                                            <span className="flex items-center gap-1">
                                                <Banknote className="w-4 h-4 text-green-400" />
                                                <span className="text-green-400 font-medium">
                                                    {formatBudget(proposal.tender_budget, proposal.tender_currency)}
                                                </span>
                                            </span>

                                            {proposal.tender_region && (
                                                <span className="flex items-center gap-1">
                                                    <MapPin className="w-4 h-4" />
                                                    {proposal.tender_region}
                                                </span>
                                            )}

                                            <span className="flex items-center gap-1">
                                                <Clock className="w-4 h-4" />
                                                Created {formatDate(proposal.created_at)}
                                            </span>
                                        </div>

                                        {proposal.structured_data?.our_price && (
                                            <div className="mt-3 pt-3 border-t border-zinc-800">
                                                <span className="text-zinc-500 text-sm">
                                                    Your Price: <span className="text-white font-medium">
                                                        {formatBudget(proposal.structured_data.our_price, proposal.tender_currency)}
                                                    </span>
                                                </span>
                                            </div>
                                        )}
                                    </div>

                                    <div className="flex items-center gap-2 ml-4">
                                        <div className="text-right">
                                            <div className="text-zinc-500 text-xs mb-1">AI Confidence</div>
                                            <div className="text-white font-bold">{proposal.ai_confidence_score}%</div>
                                        </div>
                                        <ArrowRight className="w-5 h-5 text-zinc-600 group-hover:text-indigo-400 transition-colors" />
                                    </div>
                                </div>
                            </Link>
                        </motion.div>
                    ))}
                </motion.div>
            )}
        </div>
    );
}
