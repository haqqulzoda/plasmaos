'use client';

import { useState, useEffect, use, useCallback, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { motion } from 'framer-motion';
import { FileText, Banknote, Clock, MapPin, Save, FileOutput, Loader2, ArrowLeft, Calculator, Sparkles, CheckCircle, Download, ExternalLink, AlertTriangle, FileWarning, Upload } from 'lucide-react';
import { api } from '@/lib/api';
import Link from 'next/link';

interface TenderDocument {
    id: string;
    file_url: string;
    file_type: string;
    created_at: string;
}

interface Proposal {
    id: string;
    tender_id: string;
    status: string;
    ai_confidence_score: number;
    structured_data: {
        our_price?: number;
        delivery_days?: number;
        ai_items?: EditableItem[];
        subtotal?: number;
        vat_amount?: number;
        grand_total?: number;
    } | null;
    margin_percent: number;
    include_vat: boolean;
    currency: string;
    tender_title: string;
    tender_budget: number;
    tender_currency: string;
    tender_deadline: string | null;
    tender_region: string | null;
}

interface AIItem {
    name: string;
    quantity: number;
    unit: string;
}

interface EditableItem {
    name: string;
    quantity: number;
    unit: string;
    base_cost: number;
    unit_price?: number;
    total?: number;
}

interface AIAnalysis {
    estimated_cost: number;
    suggested_margin: number;
    delivery_days: number;
    technical_summary: string;
    confidence_score: number;
    items: AIItem[];
    required_licenses: string[];
    key_requirements: string[];
    risks: string[];
}

export default function BidWorkspacePage({ params }: { params: Promise<{ id: string }> }) {
    const resolvedParams = use(params);
    const router = useRouter();
    const [proposal, setProposal] = useState<Proposal | null>(null);
    const [isLoading, setIsLoading] = useState(true);
    const [isSaving, setIsSaving] = useState(false);
    const [isAnalyzing, setIsAnalyzing] = useState(false);
    const [isGeneratingPDF, setIsGeneratingPDF] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [aiAnalysis, setAiAnalysis] = useState<AIAnalysis | null>(null);
    const [showToast, setShowToast] = useState(false);
    const [toastMessage, setToastMessage] = useState('');

    // Document state
    const [documents, setDocuments] = useState<TenderDocument[]>([]);
    const [isLoadingDocs, setIsLoadingDocs] = useState(false);
    const [docError, setDocError] = useState<string | null>(null);
    const [selectedPdf, setSelectedPdf] = useState<string | null>(null);

    // Archive upload state
    const [isUploading, setIsUploading] = useState(false);
    const [uploadedPdfUrl, setUploadedPdfUrl] = useState<string | null>(null);
    const [isDragging, setIsDragging] = useState(false);

    // Form state
    const [ourPrice, setOurPrice] = useState<string>('');
    const [deliveryDays, setDeliveryDays] = useState<string>('');
    const [companyName, setCompanyName] = useState<string>('Your Company LLC');

    // Financial state
    const [marginPercent, setMarginPercent] = useState<number>(20);
    const [includeVat, setIncludeVat] = useState<boolean>(true);
    const [editableItems, setEditableItems] = useState<EditableItem[]>([]);

    // Debounce timer for auto-save
    const saveTimerRef = useRef<NodeJS.Timeout | null>(null);
    const [pendingSave, setPendingSave] = useState(false);

    // Update item base cost with local calculation and debounced save
    const updateItemCost = useCallback((index: number, baseCost: number) => {
        setEditableItems(prev => {
            const updated = [...prev];
            updated[index] = {
                ...updated[index],
                base_cost: baseCost,
                // Calculate locally for instant feedback
                unit_price: Math.round(baseCost * (1 + marginPercent / 100)),
                total: Math.round(baseCost * (1 + marginPercent / 100) * updated[index].quantity),
            };
            return updated;
        });

        // Clear existing timer
        if (saveTimerRef.current) {
            clearTimeout(saveTimerRef.current);
        }

        // Set new debounced save (500ms) - just set flag, useEffect handles actual save
        saveTimerRef.current = setTimeout(() => {
            setPendingSave(true);
        }, 500);
    }, [marginPercent]);

    // Calculate totals locally for instant UI feedback
    const calculatedSubtotal = editableItems.reduce((sum, item) => {
        const sellPrice = (item.base_cost || 0) * (1 + marginPercent / 100);
        return sum + (sellPrice * (item.quantity || 0));
    }, 0);
    const calculatedVat = includeVat ? calculatedSubtotal * 0.12 : 0;
    const calculatedTotal = calculatedSubtotal + calculatedVat;
    const calculatedProfit = calculatedSubtotal - editableItems.reduce((sum, item) => sum + ((item.base_cost || 0) * (item.quantity || 0)), 0);

    useEffect(() => {
        const fetchProposal = async () => {
            try {
                const response = await api.get(`/proposals/${resolvedParams.id}`);
                setProposal(response.data);

                // Initialize form with existing data
                if (response.data.structured_data) {
                    setOurPrice(response.data.structured_data.our_price?.toString() || '');
                    setDeliveryDays(response.data.structured_data.delivery_days?.toString() || '');

                    // Initialize editable items if present - ensure base_cost defaults to 0
                    if (response.data.structured_data.ai_items) {
                        setEditableItems(response.data.structured_data.ai_items.map((item: EditableItem) => ({
                            ...item,
                            base_cost: item.base_cost || 0,
                            unit_price: item.unit_price || 0,
                            total: item.total || 0,
                        })));
                    }
                }

                // Initialize financial settings from proposal
                setMarginPercent(response.data.margin_percent || 20);
                setIncludeVat(response.data.include_vat ?? true);
            } catch (err) {
                console.error('Failed to fetch proposal:', err);
                setError('Proposal not found');
            } finally {
                setIsLoading(false);
            }
        };

        fetchProposal();
    }, [resolvedParams.id]);

    // Fetch tender documents on mount
    useEffect(() => {
        if (!proposal) return;

        const syncDocs = async () => {
            setIsLoadingDocs(true);
            setDocError(null);
            try {
                const response = await api.post(`/tenders/${proposal.tender_id}/sync-docs`);
                setDocuments(response.data.documents);

                // Auto-select first PDF for preview
                const firstPdf = response.data.documents.find((d: TenderDocument) => d.file_type === 'pdf');
                if (firstPdf) {
                    // Use proxy endpoint for PDF preview (NEXT_PUBLIC_API_URL already includes /api/v1)
                    setSelectedPdf(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1'}/tenders/documents/${firstPdf.id}/download`);
                }
            } catch (err) {
                console.error('Failed to sync documents:', err);
                setDocError('Failed to fetch documents from portal');
            } finally {
                setIsLoadingDocs(false);
            }
        };

        syncDocs();
    }, [proposal?.tender_id]);

    // Show toast notification
    const showNotification = (message: string) => {
        setToastMessage(message);
        setShowToast(true);
        setTimeout(() => setShowToast(false), 4000);
    };

    // Format budget
    const formatBudget = (amount: number, currency: string) => {
        return new Intl.NumberFormat('en-US').format(amount) + ` ${currency}`;
    };

    // Format deadline
    const formatDeadline = (deadline: string | null) => {
        if (!deadline) return 'No deadline';
        return new Date(deadline).toLocaleDateString('en-US', {
            month: 'long',
            day: 'numeric',
            year: 'numeric',
        });
    };

    // Calculate margin
    const calculateMargin = () => {
        if (!proposal || !ourPrice) return null;
        const price = parseFloat(ourPrice);
        if (isNaN(price) || price === 0) return null;

        const margin = ((proposal.tender_budget - price) / proposal.tender_budget) * 100;
        return margin.toFixed(1);
    };

    // Handle AI Analysis
    const handleAIAnalyze = async () => {
        if (!proposal) return;

        setIsAnalyzing(true);
        try {
            const response = await api.post(`/proposals/${proposal.id}/ai-draft`);
            const analysis: AIAnalysis = response.data;
            setAiAnalysis(analysis);

            // Auto-fill form with AI suggestions
            const suggestedPrice = proposal.tender_budget * 0.80;
            setOurPrice(suggestedPrice.toString());
            setDeliveryDays(analysis.delivery_days.toString());

            // Update proposal state with new confidence
            setProposal(prev => prev ? { ...prev, ai_confidence_score: analysis.confidence_score } : null);

            showNotification(`✨ Analysis Complete! Estimated Margin: ${analysis.suggested_margin}%`);
        } catch (err) {
            console.error('AI analysis failed:', err);
            showNotification('❌ AI analysis failed. Please try again.');
        } finally {
            setIsAnalyzing(false);
        }
    };

    // Check if any document is non-PDF (requires manual upload)
    const hasNonPdfDocument = documents.some(
        (doc) => doc.file_type !== 'pdf'
    );
    const hasPdfDocument = documents.some(d => d.file_type === 'pdf');

    // Handle TZ PDF upload for archive tenders
    const handleTZUpload = async (file: File) => {
        if (!proposal) return;

        setIsUploading(true);
        try {
            const formData = new FormData();
            formData.append('file', file);

            const response = await api.post(
                `/proposals/${proposal.id}/upload-tz`,
                formData,
                { headers: { 'Content-Type': 'multipart/form-data' } }
            );

            const analysis: AIAnalysis = response.data;
            setAiAnalysis(analysis);

            // Set uploaded PDF URL for preview
            const newPdfUrl = `${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1'}/proposals/${proposal.id}/uploaded-tz`;
            setUploadedPdfUrl(newPdfUrl);
            setSelectedPdf(newPdfUrl);

            // Auto-fill form with AI suggestions
            const suggestedPrice = proposal.tender_budget * 0.80;
            setOurPrice(suggestedPrice.toString());
            setDeliveryDays(analysis.delivery_days.toString());

            // Update proposal state with new confidence
            setProposal(prev => prev ? { ...prev, ai_confidence_score: analysis.confidence_score } : null);

            showNotification(`✨ Analysis Complete! Confidence: ${analysis.confidence_score}%`);
        } catch (err) {
            console.error('Upload failed:', err);
            showNotification('❌ Upload failed. Please try again.');
        } finally {
            setIsUploading(false);
        }
    };

    // Drag and drop handlers
    const handleDragOver = (e: React.DragEvent) => {
        e.preventDefault();
        setIsDragging(true);
    };

    const handleDragLeave = (e: React.DragEvent) => {
        e.preventDefault();
        setIsDragging(false);
    };

    const handleDrop = (e: React.DragEvent) => {
        e.preventDefault();
        setIsDragging(false);
        const file = e.dataTransfer.files[0];
        if (file && file.type === 'application/pdf') {
            handleTZUpload(file);
        } else {
            showNotification('❌ Please drop a PDF file');
        }
    };

    const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (file) {
            handleTZUpload(file);
        }
    };

    // Handle save
    const handleSave = async () => {
        if (!proposal) return;

        setIsSaving(true);
        try {
            // Build items array for financial calculation
            const itemsToSend = editableItems.length > 0 ? editableItems.map(item => ({
                name: item.name,
                unit: item.unit,
                quantity: item.quantity,
                base_cost: item.base_cost,
            })) : null;

            await api.put(`/proposals/${proposal.id}`, {
                our_price: ourPrice ? parseFloat(ourPrice) : null,
                delivery_days: deliveryDays ? parseInt(deliveryDays) : null,
                margin_percent: marginPercent,
                include_vat: includeVat,
                items: itemsToSend,
            });
            showNotification('✅ Draft saved successfully!');
        } catch (err) {
            console.error('Failed to save:', err);
            showNotification('❌ Failed to save draft');
        } finally {
            setIsSaving(false);
        }
    };

    // Auto-save effect for debounced updates
    useEffect(() => {
        if (pendingSave && proposal) {
            handleSave();
            setPendingSave(false);
        }
    }, [pendingSave, proposal]);

    // Handle PDF Generation
    const handleGeneratePDF = async () => {
        if (!proposal || !ourPrice || !deliveryDays) return;

        setIsGeneratingPDF(true);
        try {
            const response = await api.post(
                `/proposals/${proposal.id}/generate-pdf`,
                {
                    price: parseFloat(ourPrice),
                    delivery_days: parseInt(deliveryDays),
                    company_name: companyName,
                },
                { responseType: 'blob' }
            );

            // Create blob URL and open in new tab
            const blob = new Blob([response.data], { type: 'application/pdf' });
            const url = window.URL.createObjectURL(blob);
            window.open(url, '_blank');

            // Update proposal status
            setProposal(prev => prev ? { ...prev, status: 'COMPLETED' } : null);
            showNotification('📄 PDF generated! Opening in new tab...');
        } catch (err) {
            console.error('PDF generation failed:', err);
            showNotification('❌ Failed to generate PDF');
        } finally {
            setIsGeneratingPDF(false);
        }
    };

    // Check if form is filled
    const isFormFilled = ourPrice && deliveryDays;

    if (isLoading) {
        return (
            <div className="flex items-center justify-center h-64">
                <Loader2 className="w-8 h-8 text-indigo-500 animate-spin" />
            </div>
        );
    }

    if (error || !proposal) {
        return (
            <div className="space-y-4">
                <Link
                    href="/dashboard/tenders"
                    className="inline-flex items-center gap-2 text-zinc-400 hover:text-white transition-colors"
                >
                    <ArrowLeft className="w-4 h-4" />
                    Back to Feed
                </Link>
                <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-6 text-red-400">
                    {error || 'Proposal not found'}
                </div>
            </div>
        );
    }

    const margin = calculateMargin();

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
                className="flex items-center justify-between"
            >
                <div className="flex items-center gap-4">
                    <Link
                        href="/dashboard/tenders"
                        className="p-2 rounded-lg bg-zinc-800 hover:bg-zinc-700 transition-colors"
                    >
                        <ArrowLeft className="w-5 h-5 text-zinc-400" />
                    </Link>
                    <div>
                        <h1 className="text-2xl font-bold text-white">Proposal Workspace</h1>
                        <p className="text-zinc-400 mt-1">Draft your commercial proposal</p>
                    </div>
                </div>
                <div className="flex items-center gap-3">
                    <span className={`px-3 py-1 rounded-full text-sm font-medium ${proposal.status === 'DRAFT'
                        ? 'bg-yellow-500/10 text-yellow-400'
                        : proposal.status === 'COMPLETED'
                            ? 'bg-green-500/10 text-green-400'
                            : 'bg-zinc-800 text-zinc-400'
                        }`}>
                        {proposal.status}
                    </span>
                </div>
            </motion.div>

            {/* Split Screen Layout */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {/* Left Column - Source Material */}
                <motion.div
                    initial={{ opacity: 0, x: -20 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: 0.1 }}
                    className="space-y-4"
                >
                    <h2 className="text-lg font-semibold text-white flex items-center gap-2">
                        <FileText className="w-5 h-5 text-zinc-400" />
                        Technical Task (Source)
                    </h2>

                    {/* Tender Info Card */}
                    <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-6 space-y-4">
                        <h3 className="text-xl font-bold text-white">{proposal.tender_title}</h3>

                        <div className="grid grid-cols-2 gap-4">
                            <div className="bg-zinc-800/50 rounded-xl p-4">
                                <div className="flex items-center gap-2 text-zinc-400 mb-2">
                                    <Banknote className="w-4 h-4" />
                                    <span className="text-sm">Budget</span>
                                </div>
                                <p className="text-green-400 font-bold text-lg">
                                    {formatBudget(proposal.tender_budget, proposal.tender_currency)}
                                </p>
                            </div>

                            <div className="bg-zinc-800/50 rounded-xl p-4">
                                <div className="flex items-center gap-2 text-zinc-400 mb-2">
                                    <Clock className="w-4 h-4" />
                                    <span className="text-sm">Deadline</span>
                                </div>
                                <p className="text-white font-medium">
                                    {formatDeadline(proposal.tender_deadline)}
                                </p>
                            </div>
                        </div>

                        {proposal.tender_region && (
                            <div className="flex items-center gap-2 text-zinc-400">
                                <MapPin className="w-4 h-4" />
                                <span>{proposal.tender_region}</span>
                            </div>
                        )}
                    </div>

                    {/* Document Section */}
                    <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-6 space-y-4">
                        <h3 className="text-white font-semibold flex items-center gap-2">
                            <FileText className="w-5 h-5 text-zinc-400" />
                            Attached Documents
                        </h3>

                        {isLoadingDocs && (
                            <div className="flex items-center justify-center gap-3 py-8">
                                <Loader2 className="w-6 h-6 text-indigo-400 animate-spin" />
                                <span className="text-zinc-400">Fetching Technical Task from UzEx...</span>
                            </div>
                        )}

                        {docError && (
                            <div className="bg-amber-500/10 border border-amber-500/20 rounded-xl p-4 flex items-start gap-3">
                                <AlertTriangle className="w-5 h-5 text-amber-400 flex-shrink-0 mt-0.5" />
                                <div>
                                    <p className="text-amber-400 font-medium">Document Fetch Failed</p>
                                    <p className="text-zinc-400 text-sm mt-1">{docError}</p>
                                    <a
                                        href={proposal?.tender_title ? `https://etender.uzex.uz` : '#'}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        className="text-indigo-400 hover:text-indigo-300 text-sm inline-flex items-center gap-1 mt-2"
                                    >
                                        Check source manually <ExternalLink className="w-3 h-3" />
                                    </a>
                                </div>
                            </div>
                        )}

                        {!isLoadingDocs && !docError && documents.length === 0 && (
                            <div className="bg-zinc-800/50 border border-zinc-700 rounded-xl p-6 text-center">
                                <FileWarning className="w-10 h-10 text-zinc-600 mx-auto mb-3" />
                                <p className="text-zinc-400 font-medium">No digital documents found</p>
                                <p className="text-zinc-500 text-sm mt-1">Check the source link manually for attachments</p>
                            </div>
                        )}

                        {documents.length > 0 && (
                            <div className="space-y-2">
                                {documents.map((doc) => (
                                    <div
                                        key={doc.id}
                                        className={`flex items-center justify-between p-3 rounded-xl border transition-all cursor-pointer ${selectedPdf?.includes(doc.id)
                                            ? 'bg-indigo-500/10 border-indigo-500/30'
                                            : 'bg-zinc-800/50 border-zinc-700 hover:border-zinc-600'
                                            }`}
                                        onClick={() => doc.file_type === 'pdf' && setSelectedPdf(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1'}/tenders/documents/${doc.id}/download`)}
                                    >
                                        <div className="flex items-center gap-3">
                                            <div className={`p-2 rounded-lg ${doc.file_type === 'pdf' ? 'bg-red-500/10 text-red-400' :
                                                doc.file_type === 'doc' || doc.file_type === 'docx' ? 'bg-blue-500/10 text-blue-400' :
                                                    'bg-green-500/10 text-green-400'
                                                }`}>
                                                <FileText className="w-4 h-4" />
                                            </div>
                                            <div>
                                                <p className="text-white text-sm font-medium truncate max-w-[200px]">
                                                    {doc.file_url.split('/').pop() || `Document.${doc.file_type}`}
                                                </p>
                                                <p className="text-zinc-500 text-xs uppercase">{doc.file_type}</p>
                                            </div>
                                        </div>
                                        <a
                                            href={`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1'}/tenders/documents/${doc.id}/download`}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                            onClick={(e) => e.stopPropagation()}
                                            className="p-2 rounded-lg bg-zinc-700 hover:bg-zinc-600 text-zinc-300 transition-colors"
                                        >
                                            <Download className="w-4 h-4" />
                                        </a>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>

                    {/* Upload Dropzone - Show when no viewable PDF (archive, word, unknown, or empty) */}
                    {(documents.length === 0 || (hasNonPdfDocument && !hasPdfDocument)) && !uploadedPdfUrl && (
                        <motion.div
                            initial={{ opacity: 0, scale: 0.95 }}
                            animate={{ opacity: 1, scale: 1 }}
                            className={`bg-gradient-to-br from-amber-500/10 to-orange-500/10 border-2 border-dashed rounded-2xl p-8 text-center transition-all ${isDragging
                                ? 'border-amber-400 bg-amber-500/20'
                                : 'border-amber-500/30 hover:border-amber-500/50'
                                }`}
                            onDragOver={handleDragOver}
                            onDragLeave={handleDragLeave}
                            onDrop={handleDrop}
                        >
                            {isUploading ? (
                                <>
                                    <Loader2 className="w-12 h-12 text-amber-400 mx-auto mb-4 animate-spin" />
                                    <p className="text-amber-400 font-semibold text-lg">Uploading & Analyzing...</p>
                                    <p className="text-zinc-400 text-sm mt-2">Eagle AI is reading your Technical Task</p>
                                </>
                            ) : (
                                <>
                                    <div className="w-16 h-16 bg-amber-500/20 rounded-2xl flex items-center justify-center mx-auto mb-4">
                                        <Upload className="w-8 h-8 text-amber-400" />
                                    </div>
                                    <p className="text-amber-400 font-semibold text-lg mb-2">
                                        {documents.length === 0 ? '📄 No Documents Found' : `⚠️ ${documents[0]?.file_type?.toUpperCase() || 'Non-PDF'} File Detected`}
                                    </p>
                                    <p className="text-zinc-400 text-sm mb-4">
                                        {documents.length === 0
                                            ? 'Upload the Technical Task (TZ) PDF to start AI analysis'
                                            : 'System detected a non-PDF file. Please upload the PDF version to enable AI.'}
                                    </p>
                                    <label className="inline-flex items-center gap-2 px-6 py-3 bg-amber-600 hover:bg-amber-700 text-white font-medium rounded-xl cursor-pointer transition-colors">
                                        <Upload className="w-5 h-5" />
                                        Select PDF
                                        <input
                                            type="file"
                                            accept=".pdf,application/pdf"
                                            onChange={handleFileSelect}
                                            className="hidden"
                                        />
                                    </label>
                                    <p className="text-zinc-500 text-xs mt-3">
                                        or drag and drop a PDF file here
                                    </p>
                                </>
                            )}
                        </motion.div>
                    )}

                    {/* PDF Viewer - Show when PDF available (either from original docs or uploaded) */}
                    {(selectedPdf || uploadedPdfUrl) && (hasPdfDocument || uploadedPdfUrl) && (
                        <div className="bg-zinc-900 border border-zinc-800 rounded-2xl overflow-hidden">
                            <div className="p-3 border-b border-zinc-800 flex items-center justify-between">
                                <span className="text-zinc-400 text-sm">
                                    {uploadedPdfUrl ? '✅ Uploaded TZ Preview' : 'PDF Preview'}
                                </span>
                                <a
                                    href={uploadedPdfUrl || selectedPdf || '#'}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="text-indigo-400 hover:text-indigo-300 text-sm flex items-center gap-1"
                                >
                                    Open in new tab <ExternalLink className="w-3 h-3" />
                                </a>
                            </div>
                            <iframe
                                src={uploadedPdfUrl || selectedPdf || ''}
                                className="w-full h-[400px] bg-zinc-800"
                                title="Technical Task PDF"
                            />
                        </div>
                    )}

                    {/* AI Analysis Summary */}
                    {aiAnalysis && (
                        <motion.div
                            initial={{ opacity: 0, y: 10 }}
                            animate={{ opacity: 1, y: 0 }}
                            className="bg-gradient-to-br from-indigo-500/10 to-purple-500/10 border border-indigo-500/20 rounded-2xl p-6 space-y-5"
                        >
                            <h3 className="text-indigo-400 font-semibold flex items-center gap-2 text-lg">
                                <Sparkles className="w-5 h-5" />
                                AI Analysis Results
                                <span className="ml-auto text-sm font-normal text-zinc-400">
                                    Confidence: {aiAnalysis.confidence_score}%
                                </span>
                            </h3>

                            {/* Technical Summary */}
                            <div className="bg-zinc-900/50 rounded-xl p-4">
                                <p className="text-zinc-300 text-sm leading-relaxed">
                                    {aiAnalysis.technical_summary}
                                </p>
                            </div>

                            {/* Extracted Items */}
                            {aiAnalysis.items && aiAnalysis.items.length > 0 && (
                                <div>
                                    <h4 className="text-white font-medium mb-2 flex items-center gap-2">
                                        <FileText className="w-4 h-4 text-indigo-400" />
                                        Identified Items ({aiAnalysis.items.length})
                                    </h4>
                                    <div className="bg-zinc-900/50 rounded-xl overflow-hidden">
                                        <table className="w-full text-sm">
                                            <thead className="bg-zinc-800/50">
                                                <tr>
                                                    <th className="text-left text-zinc-400 px-4 py-2 font-medium">Item</th>
                                                    <th className="text-right text-zinc-400 px-4 py-2 font-medium">Qty</th>
                                                    <th className="text-right text-zinc-400 px-4 py-2 font-medium">Unit</th>
                                                </tr>
                                            </thead>
                                            <tbody>
                                                {aiAnalysis.items.slice(0, 10).map((item, idx) => (
                                                    <tr key={idx} className="border-t border-zinc-800">
                                                        <td className="text-zinc-300 px-4 py-2">{item.name}</td>
                                                        <td className="text-zinc-300 px-4 py-2 text-right">{item.quantity}</td>
                                                        <td className="text-zinc-400 px-4 py-2 text-right">{item.unit}</td>
                                                    </tr>
                                                ))}
                                            </tbody>
                                        </table>
                                        {aiAnalysis.items.length > 10 && (
                                            <p className="text-zinc-500 text-xs px-4 py-2 text-center">
                                                +{aiAnalysis.items.length - 10} more items
                                            </p>
                                        )}
                                    </div>
                                </div>
                            )}

                            {/* Requirements & Risks Grid */}
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                {/* Required Licenses */}
                                {aiAnalysis.required_licenses && aiAnalysis.required_licenses.length > 0 && (
                                    <div className="bg-zinc-900/50 rounded-xl p-4">
                                        <h4 className="text-amber-400 font-medium mb-2 text-sm">📜 Required Licenses</h4>
                                        <ul className="space-y-1">
                                            {aiAnalysis.required_licenses.map((license, idx) => (
                                                <li key={idx} className="text-zinc-300 text-sm flex items-start gap-2">
                                                    <span className="text-amber-500 mt-1">•</span>
                                                    {license}
                                                </li>
                                            ))}
                                        </ul>
                                    </div>
                                )}

                                {/* Risks */}
                                {aiAnalysis.risks && aiAnalysis.risks.length > 0 && (
                                    <div className="bg-zinc-900/50 rounded-xl p-4">
                                        <h4 className="text-red-400 font-medium mb-2 text-sm">⚠️ Potential Risks</h4>
                                        <ul className="space-y-1">
                                            {aiAnalysis.risks.slice(0, 5).map((risk, idx) => (
                                                <li key={idx} className="text-zinc-300 text-sm flex items-start gap-2">
                                                    <span className="text-red-500 mt-1">•</span>
                                                    {risk}
                                                </li>
                                            ))}
                                        </ul>
                                    </div>
                                )}
                            </div>

                            {/* Key Requirements */}
                            {aiAnalysis.key_requirements && aiAnalysis.key_requirements.length > 0 && (
                                <div className="bg-zinc-900/50 rounded-xl p-4">
                                    <h4 className="text-green-400 font-medium mb-2 text-sm">✅ Key Requirements</h4>
                                    <ul className="space-y-1">
                                        {aiAnalysis.key_requirements.slice(0, 5).map((req, idx) => (
                                            <li key={idx} className="text-zinc-300 text-sm flex items-start gap-2">
                                                <span className="text-green-500 mt-1">•</span>
                                                {req}
                                            </li>
                                        ))}
                                    </ul>
                                </div>
                            )}
                        </motion.div>
                    )}
                </motion.div>

                {/* Right Column - Proposal Form */}
                <motion.div
                    initial={{ opacity: 0, x: 20 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: 0.2 }}
                    className="space-y-4"
                >
                    <div className="flex items-center justify-between">
                        <h2 className="text-lg font-semibold text-white flex items-center gap-2">
                            <FileOutput className="w-5 h-5 text-indigo-400" />
                            Commercial Proposal
                        </h2>

                        {/* AI Auto-Analyze Button */}
                        <button
                            onClick={handleAIAnalyze}
                            disabled={isAnalyzing}
                            className="inline-flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-indigo-600 to-purple-600 hover:from-indigo-700 hover:to-purple-700 disabled:from-indigo-600/50 disabled:to-purple-600/50 text-white text-sm font-medium rounded-xl transition-all"
                        >
                            {isAnalyzing ? (
                                <>
                                    <Loader2 className="w-4 h-4 animate-spin" />
                                    Analyzing...
                                </>
                            ) : (
                                <>
                                    <Sparkles className="w-4 h-4" />
                                    AI Auto-Analyze
                                </>
                            )}
                        </button>
                    </div>

                    {/* AI Loading State */}
                    {isAnalyzing && (
                        <motion.div
                            initial={{ opacity: 0 }}
                            animate={{ opacity: 1 }}
                            className="bg-indigo-500/10 border border-indigo-500/20 rounded-xl p-6 text-center"
                        >
                            <Sparkles className="w-8 h-8 text-indigo-400 mx-auto mb-3 animate-pulse" />
                            <p className="text-indigo-400 font-medium">Eagle AI is reading the Technical Task...</p>
                            <p className="text-zinc-500 text-sm mt-2">Analyzing requirements and calculating optimal pricing</p>
                        </motion.div>
                    )}

                    {/* Form */}
                    <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-6 space-y-6">
                        {/* Company Name */}
                        <div>
                            <label className="block text-zinc-400 text-sm font-medium mb-2">
                                Company Name
                            </label>
                            <input
                                type="text"
                                value={companyName}
                                onChange={(e) => setCompanyName(e.target.value)}
                                placeholder="Your company name"
                                className="w-full px-4 py-3 bg-zinc-800 border border-zinc-700 rounded-xl text-white placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                            />
                        </div>

                        {/* Our Price */}
                        <div>
                            <label className="block text-zinc-400 text-sm font-medium mb-2">
                                Our Proposed Price ({proposal.tender_currency})
                            </label>
                            <input
                                type="number"
                                value={ourPrice}
                                onChange={(e) => setOurPrice(e.target.value)}
                                placeholder="Enter your price"
                                className="w-full px-4 py-3 bg-zinc-800 border border-zinc-700 rounded-xl text-white placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                            />
                        </div>

                        {/* Delivery Days */}
                        <div>
                            <label className="block text-zinc-400 text-sm font-medium mb-2">
                                Delivery Time (Days)
                            </label>
                            <input
                                type="number"
                                value={deliveryDays}
                                onChange={(e) => setDeliveryDays(e.target.value)}
                                placeholder="Enter delivery days"
                                className="w-full px-4 py-3 bg-zinc-800 border border-zinc-700 rounded-xl text-white placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                            />
                        </div>

                        {/* Editable Items Table */}
                        {editableItems.length > 0 && (
                            <div className="bg-zinc-800/50 border border-zinc-700 rounded-xl overflow-hidden">
                                <div className="p-3 border-b border-zinc-700 flex items-center justify-between">
                                    <span className="text-white font-medium text-sm">
                                        📦 Cost Calculator ({editableItems.length} items)
                                    </span>
                                    <span className="text-zinc-500 text-xs">
                                        Edit base cost → sell price updates
                                    </span>
                                </div>
                                <table className="w-full text-sm">
                                    <thead className="bg-zinc-900/50">
                                        <tr>
                                            <th className="text-left text-zinc-400 px-3 py-2 font-medium">Item</th>
                                            <th className="text-center text-zinc-400 px-2 py-2 font-medium w-16">Qty</th>
                                            <th className="text-right text-zinc-400 px-2 py-2 font-medium w-28">Base Cost</th>
                                            <th className="text-right text-zinc-400 px-2 py-2 font-medium w-28">Sell Price</th>
                                            <th className="text-right text-zinc-400 px-3 py-2 font-medium w-28">Total</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {editableItems.map((item, idx) => (
                                            <tr key={idx} className="border-t border-zinc-800 hover:bg-zinc-800/30">
                                                <td className="text-zinc-300 px-3 py-2 truncate max-w-[150px]" title={item.name}>
                                                    {item.name}
                                                </td>
                                                <td className="text-zinc-400 px-2 py-2 text-center">
                                                    {item.quantity}
                                                </td>
                                                <td className="px-2 py-1">
                                                    <input
                                                        type="number"
                                                        value={item.base_cost || ''}
                                                        onChange={(e) => updateItemCost(idx, Number(e.target.value))}
                                                        placeholder="0"
                                                        className="w-full px-2 py-1 bg-zinc-700 border border-zinc-600 rounded text-white text-right text-sm focus:outline-none focus:ring-1 focus:ring-emerald-500"
                                                    />
                                                </td>
                                                <td className="text-amber-400 px-2 py-2 text-right font-medium">
                                                    {Math.round((item.base_cost || 0) * (1 + marginPercent / 100)).toLocaleString()}
                                                </td>
                                                <td className="text-emerald-400 px-3 py-2 text-right font-bold">
                                                    {Math.round((item.base_cost || 0) * (1 + marginPercent / 100) * (item.quantity || 0)).toLocaleString()}
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                    <tfoot className="bg-zinc-900/80">
                                        <tr className="border-t border-zinc-600">
                                            <td colSpan={4} className="text-right text-zinc-400 px-3 py-2 font-medium">
                                                Subtotal:
                                            </td>
                                            <td className="text-white px-3 py-2 text-right font-bold">
                                                {Math.round(calculatedSubtotal).toLocaleString()}
                                            </td>
                                        </tr>
                                        {includeVat && (
                                            <tr>
                                                <td colSpan={4} className="text-right text-amber-400 px-3 py-1 text-sm">
                                                    + VAT (12%):
                                                </td>
                                                <td className="text-amber-400 px-3 py-1 text-right text-sm">
                                                    {Math.round(calculatedVat).toLocaleString()}
                                                </td>
                                            </tr>
                                        )}
                                        <tr className="border-t border-emerald-500/30">
                                            <td colSpan={4} className="text-right text-emerald-400 px-3 py-2 font-bold">
                                                Grand Total:
                                            </td>
                                            <td className="text-emerald-400 px-3 py-2 text-right font-bold text-lg">
                                                {Math.round(calculatedTotal).toLocaleString()}
                                            </td>
                                        </tr>
                                    </tfoot>
                                </table>
                            </div>
                        )}

                        {/* Financial Controls */}
                        <div className="bg-gradient-to-br from-emerald-500/10 to-teal-500/10 border border-emerald-500/20 rounded-xl p-4 space-y-4">
                            <div className="flex items-center justify-between">
                                <div className="flex items-center gap-2">
                                    <Calculator className="w-5 h-5 text-emerald-400" />
                                    <span className="text-emerald-400 font-medium">Financial Controls</span>
                                </div>
                                {proposal.structured_data?.grand_total && (
                                    <span className="bg-emerald-500/20 text-emerald-400 text-sm font-bold px-3 py-1 rounded-lg">
                                        Total: {proposal.structured_data.grand_total.toLocaleString()} {proposal.tender_currency}
                                    </span>
                                )}
                            </div>

                            {/* Margin Slider */}
                            <div>
                                <div className="flex items-center justify-between mb-2">
                                    <label className="text-zinc-400 text-sm">Margin %</label>
                                    <span className="text-white font-bold">{marginPercent}%</span>
                                </div>
                                <input
                                    type="range"
                                    min="0"
                                    max="100"
                                    value={marginPercent}
                                    onChange={(e) => setMarginPercent(Number(e.target.value))}
                                    className="w-full h-2 bg-zinc-700 rounded-lg appearance-none cursor-pointer accent-emerald-500"
                                />
                                <div className="flex justify-between text-xs text-zinc-500 mt-1">
                                    <span>0%</span>
                                    <span>50%</span>
                                    <span>100%</span>
                                </div>
                            </div>

                            {/* VAT Toggle */}
                            <div className="flex items-center justify-between pt-2 border-t border-emerald-500/20">
                                <div>
                                    <span className="text-zinc-300 text-sm">Include VAT (12%)</span>
                                    <p className="text-zinc-500 text-xs">Added to subtotal</p>
                                </div>
                                <button
                                    onClick={() => setIncludeVat(!includeVat)}
                                    className={`relative w-14 h-7 rounded-full transition-colors ${includeVat ? 'bg-emerald-500' : 'bg-zinc-600'
                                        }`}
                                >
                                    <div className={`absolute top-1 w-5 h-5 bg-white rounded-full transition-transform ${includeVat ? 'translate-x-8' : 'translate-x-1'
                                        }`} />
                                </button>
                            </div>

                            {/* Calculated Totals */}
                            {proposal.structured_data?.subtotal && (
                                <div className="pt-2 border-t border-emerald-500/20 space-y-1 text-sm">
                                    <div className="flex justify-between">
                                        <span className="text-zinc-400">Subtotal:</span>
                                        <span className="text-white">{proposal.structured_data.subtotal.toLocaleString()} {proposal.tender_currency}</span>
                                    </div>
                                    {includeVat && proposal.structured_data.vat_amount && (
                                        <div className="flex justify-between">
                                            <span className="text-zinc-400">VAT (12%):</span>
                                            <span className="text-amber-400">+{proposal.structured_data.vat_amount.toLocaleString()} {proposal.tender_currency}</span>
                                        </div>
                                    )}
                                    <div className="flex justify-between font-bold text-lg pt-1">
                                        <span className="text-zinc-300">Grand Total:</span>
                                        <span className="text-emerald-400">{proposal.structured_data.grand_total?.toLocaleString()} {proposal.tender_currency}</span>
                                    </div>
                                </div>
                            )}

                            {/* Estimated Profit Badge */}
                            {proposal.structured_data?.subtotal && (
                                <div className="bg-zinc-900/50 rounded-lg p-3 flex items-center justify-between">
                                    <span className="text-zinc-400 text-sm">Est. Profit (at {marginPercent}% margin):</span>
                                    <span className="text-emerald-400 font-bold">
                                        {Math.round(proposal.structured_data.subtotal * (marginPercent / (100 + marginPercent))).toLocaleString()} {proposal.tender_currency}
                                    </span>
                                </div>
                            )}
                        </div>

                        {/* Action Buttons */}
                        <div className="flex gap-3 pt-4">
                            <button
                                onClick={handleSave}
                                disabled={isSaving}
                                className="flex-1 inline-flex items-center justify-center gap-2 px-4 py-3 bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-600/50 text-white font-medium rounded-xl transition-colors"
                            >
                                {isSaving ? (
                                    <Loader2 className="w-5 h-5 animate-spin" />
                                ) : (
                                    <Save className="w-5 h-5" />
                                )}
                                Save Draft
                            </button>
                            <button
                                onClick={handleGeneratePDF}
                                disabled={!isFormFilled || isGeneratingPDF}
                                className={`flex-1 inline-flex items-center justify-center gap-2 px-4 py-3 font-medium rounded-xl transition-colors ${isFormFilled
                                    ? 'bg-green-600 hover:bg-green-700 text-white'
                                    : 'bg-zinc-700 text-zinc-400 cursor-not-allowed'
                                    }`}
                            >
                                {isGeneratingPDF ? (
                                    <Loader2 className="w-5 h-5 animate-spin" />
                                ) : (
                                    <FileOutput className="w-5 h-5" />
                                )}
                                Generate PDF
                            </button>
                        </div>
                    </div>

                    {/* AI Confidence */}
                    <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-6">
                        <div className="flex items-center justify-between mb-4">
                            <span className="text-zinc-400 font-medium">AI Confidence Score</span>
                            <span className="text-white font-bold">{proposal.ai_confidence_score}%</span>
                        </div>
                        <div className="w-full bg-zinc-800 rounded-full h-2">
                            <motion.div
                                className="bg-indigo-500 h-2 rounded-full"
                                initial={{ width: 0 }}
                                animate={{ width: `${proposal.ai_confidence_score}%` }}
                                transition={{ duration: 0.5 }}
                            />
                        </div>
                        <p className="text-zinc-500 text-sm mt-3">
                            {proposal.ai_confidence_score === 0
                                ? 'Click "AI Auto-Analyze" to get AI-powered suggestions.'
                                : 'AI analysis complete. Review and adjust values as needed.'}
                        </p>
                    </div>
                </motion.div>
            </div>
        </div>
    );
}
