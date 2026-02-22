'use client';

import { useState, useRef, useCallback } from 'react';
import DocumentViewer from '@/components/workspace/DocumentViewer';
import StrategyPanel from '@/components/workspace/StrategyPanel';
import type { GapAnalysis, AnalyzeTenderResponse } from '@/types/compliance';
import {
    Cpu,
    Clock,
    ArrowLeft,
    Upload,
    FileArchive,
    X,
    Loader2,
    AlertCircle,
    Sparkles,
} from 'lucide-react';
import Link from 'next/link';
import { clsx } from 'clsx';

// ═══════════════════════════════════════════════════════════════
// Config
// ═══════════════════════════════════════════════════════════════

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1';

const DEFAULT_COMPANY_PROFILE = {
    name: 'TechCorp',
    licenses: ['IT'],
    bank_guarantee_available: true,
};

const ACCEPTED_EXTENSIONS = ['.zip', '.rar'];

// ═══════════════════════════════════════════════════════════════
// Component
// ═══════════════════════════════════════════════════════════════

export default function TenderWorkspace() {
    // ── State ──
    const [file, setFile] = useState<File | null>(null);
    const [isLoading, setIsLoading] = useState(false);
    const [analysisData, setAnalysisData] = useState<GapAnalysis | null>(null);
    const [analysisId, setAnalysisId] = useState<string | null>(null);
    const [rawText, setRawText] = useState<string>('');
    const [error, setError] = useState<string | null>(null);
    const [elapsedTime, setElapsedTime] = useState<number | null>(null);
    const [isDragOver, setIsDragOver] = useState(false);
    const fileInputRef = useRef<HTMLInputElement>(null);

    // ── File Validation ──
    const isValidFile = (f: File): boolean => {
        const name = f.name.toLowerCase();
        return ACCEPTED_EXTENSIONS.some((ext) => name.endsWith(ext));
    };

    // ── File Selection ──
    const handleFileSelect = useCallback((selectedFile: File) => {
        if (!isValidFile(selectedFile)) {
            setError(`Invalid file type. Only ${ACCEPTED_EXTENSIONS.join(', ')} files are accepted.`);
            return;
        }
        setFile(selectedFile);
        setError(null);
        setAnalysisData(null);
        setAnalysisId(null);
        setRawText('');
        setElapsedTime(null);
    }, []);

    const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        const f = e.target.files?.[0];
        if (f) handleFileSelect(f);
    };

    // ── Drag & Drop ──
    const handleDragOver = useCallback((e: React.DragEvent) => {
        e.preventDefault();
        e.stopPropagation();
        setIsDragOver(true);
    }, []);

    const handleDragLeave = useCallback((e: React.DragEvent) => {
        e.preventDefault();
        e.stopPropagation();
        setIsDragOver(false);
    }, []);

    const handleDrop = useCallback(
        (e: React.DragEvent) => {
            e.preventDefault();
            e.stopPropagation();
            setIsDragOver(false);
            const f = e.dataTransfer.files?.[0];
            if (f) handleFileSelect(f);
        },
        [handleFileSelect]
    );

    // ── API Call ──
    const handleAnalyzeTender = async () => {
        if (!file) return;

        setIsLoading(true);
        setError(null);
        setAnalysisData(null);
        setRawText('');

        const startTime = performance.now();

        try {
            const formData = new FormData();
            formData.append('file', file);
            formData.append('company_profile', JSON.stringify(DEFAULT_COMPANY_PROFILE));

            const response = await fetch(`${API_BASE}/tenders/analyze-tender`, {
                method: 'POST',
                body: formData,
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => null);
                const detail = errorData?.detail || `Server returned ${response.status}`;
                throw new Error(detail);
            }

            const data = await response.json();
            const elapsed = ((performance.now() - startTime) / 1000).toFixed(1);

            // Handle both response formats:
            // New: { analysis_id: string, analysis: GapAnalysis }
            // Legacy: flat GapAnalysis object
            if (data.analysis_id && data.analysis) {
                setAnalysisId(data.analysis_id);
                setAnalysisData(data.analysis);
            } else {
                setAnalysisId(null);
                setAnalysisData(data as GapAnalysis);
            }
            setElapsedTime(parseFloat(elapsed));
        } catch (err: unknown) {
            const message = err instanceof Error ? err.message : 'An unexpected error occurred';
            setError(message);
        } finally {
            setIsLoading(false);
        }
    };

    // ── Clear State ──
    const handleClear = () => {
        setFile(null);
        setAnalysisData(null);
        setAnalysisId(null);
        setRawText('');
        setError(null);
        setElapsedTime(null);
        setIsLoading(false);
        if (fileInputRef.current) {
            fileInputRef.current.value = '';
        }
    };

    // ── Derive UI state ──
    const hasAnalysis = analysisData !== null;
    const complianceLabel = analysisData
        ? analysisData.is_fully_compliant
            ? 'Compliant'
            : 'Non-Compliant'
        : 'Pending';

    return (
        <div className="flex flex-col h-screen bg-black">
            {/* ── Command Bar ── */}
            <header className="flex items-center justify-between px-5 py-3 border-b border-zinc-800 bg-zinc-950/90 backdrop-blur-sm shrink-0">
                <div className="flex items-center gap-4">
                    <Link
                        href="/dashboard/tenders"
                        className="flex items-center gap-1.5 text-zinc-500 hover:text-zinc-300 transition-colors text-[13px]"
                    >
                        <ArrowLeft className="w-4 h-4" />
                        <span>Back</span>
                    </Link>
                    <div className="w-px h-5 bg-zinc-800" />
                    <div>
                        <h1 className="text-[15px] font-semibold text-zinc-100">
                            {file ? file.name : 'Sovereign Compliance Engine'}
                        </h1>
                        <p className="text-[11px] text-zinc-500 mt-0.5">
                            {file
                                ? `${(file.size / 1024 / 1024).toFixed(2)} MB · Archive Upload`
                                : 'Upload a tender archive to begin analysis'}
                        </p>
                    </div>
                </div>
                <div className="flex items-center gap-3">
                    {/* Status Badge */}
                    {hasAnalysis && (
                        <div
                            className={clsx(
                                'flex items-center gap-1.5 px-3 py-1.5 rounded-lg border',
                                analysisData.is_fully_compliant
                                    ? 'bg-emerald-500/10 border-emerald-500/20'
                                    : 'bg-red-500/10 border-red-500/20'
                            )}
                        >
                            <span
                                className={clsx(
                                    'w-1.5 h-1.5 rounded-full animate-pulse',
                                    analysisData.is_fully_compliant ? 'bg-emerald-400' : 'bg-red-400'
                                )}
                            />
                            <span
                                className={clsx(
                                    'text-[11px] font-semibold uppercase tracking-wider',
                                    analysisData.is_fully_compliant ? 'text-emerald-400' : 'text-red-400'
                                )}
                            >
                                {complianceLabel}
                            </span>
                        </div>
                    )}

                    {isLoading && (
                        <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-indigo-500/10 border border-indigo-500/20">
                            <Loader2 className="w-3.5 h-3.5 text-indigo-400 animate-spin" />
                            <span className="text-[11px] font-semibold text-indigo-400">Analyzing</span>
                        </div>
                    )}

                    <div className="flex items-center gap-1.5 text-[11px] text-zinc-500">
                        <Cpu className="w-3.5 h-3.5" />
                        <span>Gemini AI</span>
                    </div>

                    {elapsedTime !== null && (
                        <div className="flex items-center gap-1.5 text-[11px] text-zinc-500">
                            <Clock className="w-3.5 h-3.5" />
                            <span>{elapsedTime}s</span>
                        </div>
                    )}
                </div>
            </header>

            {/* ── Split Hemispheres ── */}
            <div className="flex-1 grid grid-cols-2 min-h-0">
                {/* ══ Left: Document Viewer / Upload Zone ══ */}
                <div className="border-r border-zinc-800 min-h-0">
                    {rawText ? (
                        <DocumentViewer
                            title={file?.name || 'Tender Document'}
                            content={rawText}
                        />
                    ) : (
                        /* Upload Dropzone */
                        <div className="flex flex-col h-full bg-zinc-950">
                            {/* Header */}
                            <div className="flex items-center gap-3 px-5 py-3.5 border-b border-zinc-800 bg-zinc-950/80 backdrop-blur-sm shrink-0">
                                <div className="w-8 h-8 rounded-lg bg-indigo-500/10 flex items-center justify-center">
                                    <Upload className="w-4 h-4 text-indigo-400" />
                                </div>
                                <div>
                                    <p className="text-[11px] font-medium uppercase tracking-widest text-zinc-500">
                                        Document Upload
                                    </p>
                                    <h3 className="text-sm font-semibold text-zinc-200">Tender Archive</h3>
                                </div>
                            </div>

                            {/* Dropzone Body */}
                            <div className="flex-1 flex items-center justify-center p-8">
                                <div
                                    onDragOver={handleDragOver}
                                    onDragLeave={handleDragLeave}
                                    onDrop={handleDrop}
                                    onClick={() => fileInputRef.current?.click()}
                                    className={clsx(
                                        'w-full max-w-md rounded-2xl border-2 border-dashed p-10 text-center cursor-pointer transition-all duration-200',
                                        isDragOver
                                            ? 'border-indigo-400 bg-indigo-500/5'
                                            : file
                                                ? 'border-emerald-500/30 bg-emerald-500/5'
                                                : 'border-zinc-700 bg-zinc-900/50 hover:border-zinc-500 hover:bg-zinc-900'
                                    )}
                                >
                                    <input
                                        ref={fileInputRef}
                                        type="file"
                                        accept=".zip,.rar"
                                        onChange={handleInputChange}
                                        className="hidden"
                                    />

                                    {file ? (
                                        <div className="space-y-4">
                                            <div className="w-14 h-14 mx-auto rounded-xl bg-emerald-500/10 flex items-center justify-center">
                                                <FileArchive className="w-7 h-7 text-emerald-400" />
                                            </div>
                                            <div>
                                                <p className="text-sm font-semibold text-zinc-200">{file.name}</p>
                                                <p className="text-[12px] text-zinc-500 mt-1">
                                                    {(file.size / 1024 / 1024).toFixed(2)} MB
                                                </p>
                                            </div>
                                            <div className="flex items-center justify-center gap-3 pt-2">
                                                <button
                                                    onClick={(e) => {
                                                        e.stopPropagation();
                                                        handleAnalyzeTender();
                                                    }}
                                                    disabled={isLoading}
                                                    className={clsx(
                                                        'flex items-center gap-2 px-5 py-2.5 rounded-lg text-[13px] font-semibold transition-all duration-200',
                                                        isLoading
                                                            ? 'bg-zinc-800 text-zinc-500 cursor-not-allowed'
                                                            : 'bg-indigo-600 text-white hover:bg-indigo-500'
                                                    )}
                                                >
                                                    {isLoading ? (
                                                        <>
                                                            <Loader2 className="w-4 h-4 animate-spin" />
                                                            Analyzing...
                                                        </>
                                                    ) : (
                                                        <>
                                                            <Sparkles className="w-4 h-4" />
                                                            Run Gap Analysis
                                                        </>
                                                    )}
                                                </button>
                                                <button
                                                    onClick={(e) => {
                                                        e.stopPropagation();
                                                        handleClear();
                                                    }}
                                                    className="flex items-center gap-1.5 px-3 py-2.5 rounded-lg text-[13px] text-zinc-400 hover:text-zinc-200 border border-zinc-700 hover:border-zinc-600 transition-all duration-200"
                                                >
                                                    <X className="w-3.5 h-3.5" />
                                                    Clear
                                                </button>
                                            </div>
                                        </div>
                                    ) : (
                                        <div className="space-y-4">
                                            <div className="w-14 h-14 mx-auto rounded-xl bg-zinc-800 flex items-center justify-center">
                                                <Upload className="w-7 h-7 text-zinc-500" />
                                            </div>
                                            <div>
                                                <p className="text-sm font-medium text-zinc-300">
                                                    Drop tender archive here
                                                </p>
                                                <p className="text-[12px] text-zinc-600 mt-1">
                                                    or click to browse · .zip, .rar accepted
                                                </p>
                                            </div>
                                        </div>
                                    )}
                                </div>
                            </div>

                            {/* Error Banner */}
                            {error && (
                                <div className="mx-5 mb-5 flex items-start gap-3 rounded-xl border border-red-500/20 bg-red-500/5 px-4 py-3">
                                    <AlertCircle className="w-4 h-4 text-red-400 mt-0.5 shrink-0" />
                                    <div>
                                        <p className="text-[13px] font-semibold text-red-400">Analysis Failed</p>
                                        <p className="text-[12px] text-zinc-400 mt-0.5">{error}</p>
                                    </div>
                                    <button
                                        onClick={() => setError(null)}
                                        className="ml-auto text-zinc-500 hover:text-zinc-300 transition-colors"
                                    >
                                        <X className="w-3.5 h-3.5" />
                                    </button>
                                </div>
                            )}
                        </div>
                    )}
                </div>

                {/* ══ Right: Strategy Panel ══ */}
                <div className="min-h-0">
                    {hasAnalysis ? (
                        <StrategyPanel analysis={analysisData} analysisId={analysisId || ''} />
                    ) : isLoading ? (
                        /* Loading Skeleton */
                        <div className="flex flex-col h-full bg-zinc-950">
                            <div className="px-5 py-3.5 border-b border-zinc-800 bg-zinc-950/80 shrink-0">
                                <div className="flex items-center gap-3">
                                    <div className="w-8 h-8 rounded-lg bg-indigo-500/10 flex items-center justify-center">
                                        <Loader2 className="w-4 h-4 text-indigo-400 animate-spin" />
                                    </div>
                                    <div>
                                        <p className="text-[11px] font-medium uppercase tracking-widest text-zinc-500">
                                            Processing
                                        </p>
                                        <h3 className="text-sm font-semibold text-zinc-200">Running Analysis...</h3>
                                    </div>
                                </div>
                            </div>
                            <div className="flex-1 flex items-center justify-center p-8">
                                <div className="text-center space-y-6 max-w-sm">
                                    <div className="relative w-20 h-20 mx-auto">
                                        <div className="absolute inset-0 rounded-2xl bg-indigo-500/10 animate-pulse" />
                                        <div className="absolute inset-0 flex items-center justify-center">
                                            <Cpu className="w-8 h-8 text-indigo-400" />
                                        </div>
                                    </div>
                                    <div>
                                        <p className="text-sm font-semibold text-zinc-200">
                                            Plasma AI is analyzing legal requirements...
                                        </p>
                                        <p className="text-[12px] text-zinc-500 mt-2">
                                            Extracting text from archive, identifying compliance gaps,
                                            and evaluating risk factors. This may take 15–45 seconds.
                                        </p>
                                    </div>
                                    {/* Skeleton bars */}
                                    <div className="space-y-3 pt-4">
                                        <div className="h-3 bg-zinc-800 rounded-full animate-pulse" />
                                        <div className="h-3 bg-zinc-800 rounded-full animate-pulse w-4/5" />
                                        <div className="h-3 bg-zinc-800 rounded-full animate-pulse w-3/5" />
                                        <div className="h-10 bg-zinc-800/60 rounded-xl animate-pulse mt-4" />
                                        <div className="h-10 bg-zinc-800/60 rounded-xl animate-pulse" />
                                    </div>
                                </div>
                            </div>
                        </div>
                    ) : (
                        /* Empty State */
                        <div className="flex flex-col h-full bg-zinc-950">
                            <div className="px-5 py-3.5 border-b border-zinc-800 bg-zinc-950/80 shrink-0">
                                <div className="flex items-center gap-3">
                                    <div className="w-8 h-8 rounded-lg bg-zinc-800 flex items-center justify-center">
                                        <Cpu className="w-4 h-4 text-zinc-500" />
                                    </div>
                                    <div>
                                        <p className="text-[11px] font-medium uppercase tracking-widest text-zinc-500">
                                            Compliance Analysis
                                        </p>
                                        <h3 className="text-sm font-semibold text-zinc-400">Awaiting Input</h3>
                                    </div>
                                </div>
                            </div>
                            <div className="flex-1 flex items-center justify-center p-8">
                                <div className="text-center space-y-4 max-w-xs">
                                    <div className="w-16 h-16 mx-auto rounded-2xl bg-zinc-900 flex items-center justify-center">
                                        <Sparkles className="w-7 h-7 text-zinc-600" />
                                    </div>
                                    <p className="text-sm text-zinc-500">
                                        Upload a tender archive and run the analysis to see compliance results here.
                                    </p>
                                </div>
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
