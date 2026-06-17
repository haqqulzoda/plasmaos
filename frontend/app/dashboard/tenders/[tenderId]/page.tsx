'use client';

import { use, useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import {
    AlertCircle,
    ArrowLeft,
    Building2,
    Calendar,
    CheckCircle2,
    Download,
    ExternalLink,
    FileSearch,
    FileText,
    Globe2,
    Loader2,
    ShieldCheck,
} from 'lucide-react';

import { api } from '@/lib/api';
import type { Tender, TenderDocument } from '@/types/tender';
import {
    complianceUnavailableMessage,
    documentStatusClasses,
    documentStatusLabel,
    sourceBadgeClasses,
    sourceLabel,
} from '@/types/tender';

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

function filenameForDocument(doc: TenderDocument) {
    return doc.display_name || doc.original_filename || (doc.file_type ? `document.${doc.file_type}` : 'document');
}

function downloadStatusText(doc: TenderDocument) {
    if (doc.download_status === 'available') return 'Available in Plasma';
    if (doc.download_status === 'metadata_only') return 'PDF notice discovered — not downloaded into Plasma yet.';
    if (doc.download_status === 'failed') return 'Document processing failed.';
    return 'Document unavailable.';
}

export default function TenderDetailPage({ params }: { params: Promise<{ tenderId: string }> }) {
    const router = useRouter();
    const { tenderId } = use(params);
    const [tender, setTender] = useState<Tender | null>(null);
    const [documents, setDocuments] = useState<TenderDocument[]>([]);
    const [isLoading, setIsLoading] = useState(true);
    const [isLoadingDocuments, setIsLoadingDocuments] = useState(true);
    const [openingDocId, setOpeningDocId] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [documentError, setDocumentError] = useState<string | null>(null);

    useEffect(() => {
        let isActive = true;

        const loadTender = async () => {
            setIsLoading(true);
            setError(null);
            try {
                const { data } = await api.get<Tender>(`/tenders/${tenderId}`);
                if (isActive) setTender(data);
            } catch (err) {
                const axiosErr = err as { response?: { data?: { detail?: string } } };
                if (isActive) {
                    setError(axiosErr.response?.data?.detail || 'Tender could not be loaded.');
                }
            } finally {
                if (isActive) setIsLoading(false);
            }
        };

        loadTender();
        return () => {
            isActive = false;
        };
    }, [tenderId]);

    useEffect(() => {
        let isActive = true;

        const loadDocuments = async () => {
            setIsLoadingDocuments(true);
            setDocumentError(null);
            try {
                const { data } = await api.get<TenderDocument[]>(`/tenders/${tenderId}/documents`);
                if (isActive) setDocuments(Array.isArray(data) ? data : []);
            } catch (err) {
                const axiosErr = err as { response?: { data?: { detail?: string } } };
                if (isActive) {
                    setDocuments([]);
                    setDocumentError(axiosErr.response?.data?.detail || 'Document metadata could not be loaded.');
                }
            } finally {
                if (isActive) setIsLoadingDocuments(false);
            }
        };

        loadDocuments();
        return () => {
            isActive = false;
        };
    }, [tenderId]);

    const canAnalyze = Boolean(tender?.compliance_analysis_available);
    const unavailableMessage = useMemo(
        () => tender ? complianceUnavailableMessage(tender) : 'Document ingestion required before analysis.',
        [tender],
    );

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
                <Link href="/dashboard/tenders" className="inline-flex items-center gap-2 text-sm text-zinc-400 hover:text-zinc-200">
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
                <Link href="/dashboard/tenders" className="inline-flex items-center gap-2 text-sm text-zinc-400 hover:text-zinc-200">
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
                    <span className={`inline-flex rounded-md border px-2 py-1 text-xs font-semibold ${documentStatusClasses(tender.document_status)}`}>
                        {documentStatusLabel(tender.document_status)}
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

            <section className="rounded-lg border border-gray-800 bg-gray-950 p-5">
                <div className="mb-4 flex items-center justify-between gap-3">
                    <div>
                        <h2 className="text-lg font-semibold text-white">Documents</h2>
                        <p className="mt-1 text-sm text-zinc-500">
                            {tender.document_count} captured records, {tender.available_document_count} available in Plasma.
                        </p>
                    </div>
                    <span className={`inline-flex rounded-md border px-2 py-1 text-xs font-semibold ${documentStatusClasses(tender.document_status)}`}>
                        {documentStatusLabel(tender.document_status)}
                    </span>
                </div>

                {tender.document_status === 'processing' && (
                    <div className="mb-4 flex items-center gap-2 rounded-lg border border-indigo-500/20 bg-indigo-500/10 px-3 py-2 text-sm text-indigo-200">
                        <Loader2 className="h-4 w-4 animate-spin" />
                        Document ingestion is processing.
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
                                        <div className={isAvailable ? 'text-emerald-300' : doc.download_status === 'failed' ? 'text-red-300' : 'text-amber-300'}>
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
