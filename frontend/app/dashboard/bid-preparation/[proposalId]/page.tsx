'use client';

import { use, useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { motion } from 'framer-motion';
import {
  ArrowLeft,
  Check,
  Copy,
  Download,
  FileArchive,
  FileOutput,
  FileText,
  FileType,
  Loader2,
  Save,
  Sparkles,
} from 'lucide-react';

import { api } from '@/lib/api';
import { TenderEngagementPanel } from '@/components/tenders/TenderEngagementPanel';
import {
  engagementStatusClasses,
  engagementStatusLabel,
  type EngagementStatus,
} from '@/types/engagement';
import type { TenderDocument, TenderStatus } from '@/types/tender';
import {
  isTenderActionable,
  tenderActionabilityMessage,
  tenderStatusClasses,
  tenderStatusLabel,
} from '@/types/tender';

type TenderSyncState = 'IDLE' | 'PENDING' | 'IN_PROGRESS' | 'SUCCESS' | 'FAILED';

interface TenderDocsSyncResponse {
  message: string;
  job_id: string;
  tender_id: string;
  user_id: string;
  status: TenderSyncState;
  progress: number;
  error_message: string | null;
}

interface TenderSyncStatusResponse {
  state: TenderSyncState;
  progress: number;
  docs_parsed: number;
  error: string | null;
}

interface StrategicLineItem {
  name: string;
  quantity: number;
  unit: string;
  unit_price: number;
  total: number;
}

interface Proposal {
  id: string;
  tender_id: string;
  status: string;
  structured_data: {
    strategic_summary?: string;
    ai_summary?: string;
    our_price?: number;
    delivery_days?: string | number;
    line_items?: StrategicLineItem[];
    ai_items?: StrategicLineItem[];
  } | null;
  tender_title: string;
  tender_budget: number;
  tender_currency: string;
  tender_deadline: string | null;
  tender_region: string | null;
  tender_source_system: string;
  tender_status: TenderStatus;
  engagement_status: EngagementStatus | null;
}

interface StrategicDraftResponse {
  strategic_summary: string;
  suggested_price: number;
  delivery_days: string;
  line_items: StrategicLineItem[];
}

const getDeliveryDaysInt = (value: string): number => {
  const match = value.match(/\d+/);
  if (!match) {
    return 30;
  }
  return Math.max(1, parseInt(match[0], 10));
};

const formatCurrency = (amount: number, currency: string) =>
  `${new Intl.NumberFormat('en-US').format(amount)} ${currency}`;

const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
const PREVIEW_LOADING_HTML = `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Preparing document preview</title>
    <style>
      :root { color-scheme: light; }
      body {
        margin: 0;
        min-height: 100vh;
        display: grid;
        place-items: center;
        background: #f4f7fb;
        color: #0f172a;
        font-family: Georgia, 'Times New Roman', serif;
      }
      main {
        width: min(420px, calc(100vw - 32px));
        padding: 28px 24px;
        border-radius: 18px;
        background: rgba(255, 255, 255, 0.92);
        border: 1px solid rgba(15, 23, 42, 0.08);
        box-shadow: 0 20px 50px rgba(15, 23, 42, 0.08);
      }
      h1 {
        margin: 0 0 10px;
        font-size: 20px;
      }
      p {
        margin: 0;
        font-size: 14px;
        line-height: 1.6;
        color: #475569;
      }
    </style>
  </head>
  <body>
    <main>
      <h1>Preparing PDF preview</h1>
      <p>The document is being fetched from UzEx. This tab will open the PDF automatically when it is ready.</p>
    </main>
  </body>
</html>`;
const PREVIEW_ERROR_HTML = `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Preview unavailable</title>
    <style>
      :root { color-scheme: light; }
      body {
        margin: 0;
        min-height: 100vh;
        display: grid;
        place-items: center;
        background: #fff7ed;
        color: #7c2d12;
        font-family: Georgia, 'Times New Roman', serif;
      }
      main {
        width: min(420px, calc(100vw - 32px));
        padding: 28px 24px;
        border-radius: 18px;
        background: rgba(255, 255, 255, 0.94);
        border: 1px solid rgba(194, 65, 12, 0.14);
        box-shadow: 0 20px 50px rgba(194, 65, 12, 0.08);
      }
      h1 {
        margin: 0 0 10px;
        font-size: 20px;
      }
      p {
        margin: 0;
        font-size: 14px;
        line-height: 1.6;
      }
    </style>
  </head>
  <body>
    <main>
      <h1>Preview unavailable</h1>
      <p>The PDF could not be opened right now. Close this tab and try again from the tender page.</p>
    </main>
  </body>
</html>`;

/** Strip non-digits, return raw numeric string */
const stripNonDigits = (v: string) => v.replace(/\D/g, '');

/** Format a raw numeric string with commas: "21890000000" → "21,890,000,000" */
const formatPriceDisplay = (raw: string) => {
  const digits = stripNonDigits(raw);
  if (!digits) return '';
  return Number(digits).toLocaleString('en-US');
};

/** File extension helper */
const getFileExtension = (value: string) => {
  const sanitized = value.split('?')[0].split('#')[0];
  const parts = sanitized.split('.');
  return parts.length > 1 ? parts[parts.length - 1].toLowerCase() : '';
};

const isArchiveFile = (ext: string) => ['zip', 'rar', '7z', 'tar', 'gz'].includes(ext);
const isPdfFile = (ext: string) => ext === 'pdf';

const getDocumentFilename = (doc: TenderDocument) => {
  const fallbackExtension = (doc.file_type || '').trim().toLowerCase();
  if (doc.display_name) {
    return doc.display_name;
  }

  if (doc.original_filename) {
    return doc.original_filename;
  }

  if (doc.storage_filename) {
    return doc.storage_filename;
  }

  return fallbackExtension ? `document.${fallbackExtension}` : 'document';
};

const formatDeadline = (deadline: string | null) => {
  if (!deadline) return 'No deadline';
  return new Date(deadline).toLocaleDateString('en-US', {
    month: 'long',
    day: 'numeric',
    year: 'numeric',
  });
};

export default function BidPreparationWorkspacePage({ params }: { params: Promise<{ proposalId: string }> }) {
  const resolvedParams = use(params);
  const router = useRouter();

  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [documents, setDocuments] = useState<TenderDocument[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingDocs, setIsLoadingDocs] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [generationError, setGenerationError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [isGeneratingPdf, setIsGeneratingPdf] = useState(false);
  const [isGeneratingDocx, setIsGeneratingDocx] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isCopied, setIsCopied] = useState(false);
  const [isSyncingDocs, setIsSyncingDocs] = useState(false);
  const [docsSyncError, setDocsSyncError] = useState<string | null>(null);
  const [docsSyncProgress, setDocsSyncProgress] = useState(0);
  const [downloadingDocId, setDownloadingDocId] = useState<string | null>(null);
  const [previewingDocId, setPreviewingDocId] = useState<string | null>(null);

  const [companyName, setCompanyName] = useState('');
  const [strategicSummary, setStrategicSummary] = useState('');
  const [suggestedPrice, setSuggestedPrice] = useState('');
  const [deliveryDays, setDeliveryDays] = useState('');
  const [lineItems, setLineItems] = useState<StrategicLineItem[]>([]);

  const fetchTenderDocuments = useCallback(async (tenderId: string) => {
    const response = await api.get<TenderDocument[]>(`/tenders/${tenderId}/documents`);
    setDocuments(response.data);
  }, []);

  const fetchTenderSyncStatus = useCallback(async (tenderId: string) => {
    const response = await api.get<TenderSyncStatusResponse>(`/tenders/${tenderId}/sync-status`);
    return response.data;
  }, []);

  const pollTenderDocumentSync = useCallback(async (tenderId: string) => {
    for (let attempt = 0; attempt < 60; attempt += 1) {
      const status = await fetchTenderSyncStatus(tenderId);
      setDocsSyncProgress(status.progress);

      if (status.state === 'SUCCESS') {
        return;
      }

      if (status.state === 'FAILED') {
        throw new Error(status.error || 'Document preparation failed.');
      }

      if (attempt > 0 && status.docs_parsed > 0) {
        try {
          const docsResponse = await api.get<TenderDocument[]>(`/tenders/${tenderId}/documents`);
          if (docsResponse.data.length > 0) {
            setDocuments(docsResponse.data);
          }
        } catch {
          // Ignore intermediate fetch failures while document preparation is still running.
        }
      }

      await wait(5000);
    }

    throw new Error('Document preparation is taking longer than expected. Please reload the page in a minute.');
  }, [fetchTenderSyncStatus]);

  useEffect(() => {
    const fetchProposal = async () => {
      try {
        const response = await api.get<Proposal>(`/proposals/${resolvedParams.proposalId}`);
        const data = response.data;
        setProposal(data);

        const structured = data.structured_data ?? {};
        setStrategicSummary((structured.strategic_summary || structured.ai_summary || '').trim());
        setSuggestedPrice(
          typeof structured.our_price === 'number' ? String(structured.our_price) : '',
        );
        setDeliveryDays(
          structured.delivery_days !== undefined ? String(structured.delivery_days) : '',
        );
        setLineItems((structured.line_items || structured.ai_items || []).map((item) => ({
          ...item,
          quantity: Number(item.quantity) || 1,
          unit_price: Number(item.unit_price) || 0,
          total: Number(item.total) || 0,
        })));
      } catch (requestError: unknown) {
        const detail = (requestError as { response?: { data?: { detail?: string } } }).response?.data?.detail;
        setError(detail || 'Bid Preparation not found');
      } finally {
        setIsLoading(false);
      }
    };

    fetchProposal();
  }, [resolvedParams.proposalId]);

  // Pre-fill company name from vault
  useEffect(() => {
    const fetchVault = async () => {
      try {
        const res = await api.get('/vault');
        const name = res.data?.company_name;
        if (name) setCompanyName(name);
      } catch {
        // Vault not set up yet — keep field empty
      }
    };
    fetchVault();
  }, []);

  useEffect(() => {
    if (!proposal) return;

    let isActive = true;

    const syncTenderDocuments = async () => {
      setIsLoadingDocs(true);
      setDocsSyncError(null);
      setDocsSyncProgress(0);

      try {
        const initialStatus = await fetchTenderSyncStatus(proposal.tender_id);
        if (!isActive) {
          return;
        }

        setDocsSyncProgress(initialStatus.progress);

        const isGizTender = proposal.tender_source_system === 'giz';
        const shouldStartSync =
          isTenderActionable(proposal.tender_status) &&
          !isGizTender &&
          (initialStatus.state === 'IDLE' || initialStatus.state === 'FAILED') &&
          initialStatus.docs_parsed === 0;
        const shouldPollExisting =
          initialStatus.state === 'PENDING' || initialStatus.state === 'IN_PROGRESS';

        if (initialStatus.state === 'FAILED' && !shouldStartSync) {
          setDocsSyncError(initialStatus.error || 'Document preparation failed.');
        }

        if (shouldStartSync) {
          setIsSyncingDocs(true);
          const enqueueResponse = await api.post<TenderDocsSyncResponse>(
            `/tenders/${proposal.tender_id}/sync-docs`,
          );
          if (!isActive) {
            return;
          }
          setDocsSyncProgress(enqueueResponse.data.progress);
        }

        if (shouldStartSync || shouldPollExisting) {
          setIsSyncingDocs(true);
          await pollTenderDocumentSync(proposal.tender_id);
        }

        if (!isActive) {
          return;
        }

        try {
          await fetchTenderDocuments(proposal.tender_id);
        } catch {
          setDocuments([]);
        }
      } catch (err) {
        if (!isActive) {
          return;
        }

        try {
          await fetchTenderDocuments(proposal.tender_id);
        } catch {
          setDocuments([]);
        }

        const axiosError = err as { response?: { data?: { detail?: string } } };
        const thrownError = err instanceof Error ? err.message : null;
        setDocsSyncError(
          axiosError.response?.data?.detail ||
          thrownError ||
          'Tender documents are still preparing or could not be fetched right now.',
        );
      } finally {
        if (isActive) {
          setIsLoadingDocs(false);
          setIsSyncingDocs(false);
        }
      }
    };

    syncTenderDocuments();

    return () => {
      isActive = false;
    };
  }, [fetchTenderDocuments, fetchTenderSyncStatus, pollTenderDocumentSync, proposal]);

  const handleGenerateStrategicProposal = async () => {
    if (!proposal) return;
    try {
      setIsGenerating(true);
      setGenerationError(null);
      const response = await api.post<StrategicDraftResponse>(`/proposals/${proposal.id}/ai-draft`);
      if (response.status < 200 || response.status >= 300) {
        throw new Error('Non-OK response from AI draft endpoint');
      }
      const draft = response.data;

      // Check if the AI returned an error inside the successful response
      const errorType = (draft as unknown as Record<string, unknown>).error_type as string | undefined;
      if (errorType === 'quota_exceeded') {
        setGenerationError('Monthly AI quota reached. Please try again later or contact support.');
        return;
      }
      if (errorType === 'model_overloaded') {
        setGenerationError('AI models are temporarily overloaded. Please retry in a few minutes.');
        return;
      }

      setStrategicSummary(draft.strategic_summary || '');
      setSuggestedPrice(String(draft.suggested_price ?? ''));
      setDeliveryDays(draft.delivery_days || '');
      setLineItems(
        (draft.line_items || []).map((item) => ({
          ...item,
          quantity: Number(item.quantity) || 1,
          unit_price: Number(item.unit_price) || 0,
          total: Number(item.total) || 0,
        })),
      );
    } catch (err: unknown) {
      // Parse structured error from backend if available
      const axiosErr = err as { response?: { data?: { detail?: string }; status?: number } };
      const status = axiosErr?.response?.status;
      const detail = axiosErr?.response?.data?.detail || '';

      if (status === 429 || detail.toLowerCase().includes('quota')) {
        setGenerationError('Monthly AI quota reached across all models. Please try again later or contact support.');
      } else if (status === 503 || detail.toLowerCase().includes('overload')) {
        setGenerationError('AI models are temporarily overloaded. Please retry in a few minutes.');
      } else {
        setGenerationError(
          detail || 'AI generation failed. Please check your connection and try again.',
        );
      }
    } finally {
      setIsGenerating(false);
    }
  };

  const handleDocumentDownload = useCallback(async (docId: string, filename?: string) => {
    setDownloadingDocId(docId);

    try {
      const response = await api.get(`/tenders/documents/${docId}/download`, {
        responseType: 'blob',
      });

      const contentType = response.headers['content-type'] || 'application/octet-stream';
      const blob = new Blob([response.data], { type: contentType });
      const url = URL.createObjectURL(blob);

      const link = document.createElement('a');
      link.href = url;
      link.download = filename || `document_${docId}`;
      document.body.appendChild(link);
      link.click();
      link.remove();

      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } finally {
      window.setTimeout(() => {
        setDownloadingDocId((current) => (current === docId ? null : current));
      }, 1200);
    }
  }, []);

  const handleDocumentPreview = useCallback(async (docId: string) => {
    setPreviewingDocId(docId);
    const previewTab = window.open('', '_blank');
    if (previewTab) {
      previewTab.opener = null;
      previewTab.document.write(PREVIEW_LOADING_HTML);
      previewTab.document.close();
    }

    try {
      const response = await api.get(`/tenders/documents/${docId}/download`, {
        responseType: 'blob',
      });

      const contentType = response.headers['content-type'] || 'application/octet-stream';
      const blob = new Blob([response.data], { type: contentType });
      const url = URL.createObjectURL(blob);

      if (previewTab) {
        previewTab.location.replace(url);
      } else {
        window.open(url, '_blank', 'noopener,noreferrer');
      }

      window.setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch {
      if (previewTab) {
        previewTab.document.open();
        previewTab.document.write(PREVIEW_ERROR_HTML);
        previewTab.document.close();
      }
    } finally {
      window.setTimeout(() => {
        setPreviewingDocId((current) => (current === docId ? null : current));
      }, 1200);
    }
  }, []);

  const handleCopySummary = async () => {
    if (!strategicSummary) return;
    try {
      await navigator.clipboard.writeText(strategicSummary);
      setIsCopied(true);
      setTimeout(() => setIsCopied(false), 2000);
    } catch {
      // clipboard API may fail in insecure contexts
    }
  };

  const handleSave = async () => {
    if (!proposal) return;
    setIsSaving(true);
    try {
      const rawPrice = stripNonDigits(suggestedPrice || '0');
      const priceNum = parseFloat(rawPrice || '0');
      await api.put(`/proposals/${proposal.id}`, {
        our_price: Number.isFinite(priceNum) ? priceNum : null,
        delivery_days: getDeliveryDaysInt(deliveryDays || '30'),
        structured_data: {
          ...(proposal.structured_data || {}),
          strategic_summary: strategicSummary,
          line_items: lineItems,
        },
      });
      setProposal((prev) =>
        prev
          ? {
            ...prev,
            structured_data: {
              ...(prev.structured_data || {}),
              strategic_summary: strategicSummary,
              line_items: lineItems,
            },
          }
          : prev,
      );
    } finally {
      setIsSaving(false);
    }
  };

  const handleGeneratePdf = async () => {
    if (!proposal) return;
    setIsGeneratingPdf(true);
    try {
      const rawPrice = stripNonDigits(suggestedPrice || '0');
      const response = await api.post(
        `/proposals/${proposal.id}/generate-pdf`,
        {
          price: parseFloat(rawPrice || '0'),
          delivery_days: getDeliveryDaysInt(deliveryDays || '30'),
          company_name: companyName,
        },
        { responseType: 'blob' },
      );
      const blob = new Blob([response.data], { type: 'application/pdf' });
      const url = window.URL.createObjectURL(blob);
      window.open(url, '_blank');
    } finally {
      setIsGeneratingPdf(false);
    }
  };

  const handleGenerateDocx = async () => {
    if (!proposal) return;
    setIsGeneratingDocx(true);
    try {
      const rawPrice = stripNonDigits(suggestedPrice || '0');
      const response = await api.post(
        `/proposals/${proposal.id}/export/docx`,
        {
          price: parseFloat(rawPrice || '0'),
          delivery_days: getDeliveryDaysInt(deliveryDays || '30'),
          company_name: companyName,
        },
        { responseType: 'blob' },
      );
      const blob = new Blob([response.data], {
        type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      });
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `proposal_${proposal.id.slice(0, 8)}.docx`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } finally {
      setIsGeneratingDocx(false);
    }
  };

  const computedTotal = useMemo(
    () => lineItems.reduce((acc, item) => acc + (Number(item.total) || 0), 0),
    [lineItems],
  );

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-indigo-500" />
      </div>
    );
  }

  if (error || !proposal) {
    return (
      <div className="space-y-4">
        <Link
          href="/dashboard/tenders"
          className="inline-flex items-center gap-2 text-zinc-400 transition-colors hover:text-white"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to Feed
        </Link>
        <div className="rounded-xl border border-red-500/20 bg-red-500/10 p-6 text-red-200">
          {error || 'Bid Preparation not found'}
        </div>
      </div>
    );
  }

  const actionable = isTenderActionable(proposal.tender_status);
  const actionabilityMessage = tenderActionabilityMessage(proposal.tender_status);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <Link
            href="/dashboard/tenders"
            className="mb-2 inline-flex items-center gap-2 text-zinc-400 transition-colors hover:text-white"
          >
            <ArrowLeft className="h-4 w-4" />
            Back to Feed
          </Link>
          <h1 className="text-2xl font-bold text-white">{proposal.tender_title}</h1>
          <p className="mt-1 text-sm text-zinc-400">
            Budget {formatCurrency(proposal.tender_budget, proposal.tender_currency)} | Deadline{' '}
            {formatDeadline(proposal.tender_deadline)} | {proposal.tender_region || 'No region'}
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <span className={`inline-flex rounded-md border px-2 py-1 text-xs font-semibold ${tenderStatusClasses(proposal.tender_status)}`}>
              Tender: {tenderStatusLabel(proposal.tender_status)}
            </span>
            {proposal.engagement_status ? (
              <span className={`inline-flex rounded-md border px-2 py-1 text-xs font-semibold ${engagementStatusClasses(proposal.engagement_status)}`}>
                Engagement: {engagementStatusLabel(proposal.engagement_status)}
              </span>
            ) : null}
          </div>
        </div>
        <button
          onClick={handleGenerateStrategicProposal}
          disabled={isGenerating || !actionable}
          title={!actionable ? actionabilityMessage : 'Generate strategic draft'}
          className="inline-flex items-center gap-2 bg-indigo-600 hover:bg-indigo-500 text-white font-medium px-6 py-3 rounded-lg transition-colors disabled:cursor-not-allowed disabled:opacity-60"
        >
          {isGenerating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
          Generate Strategic Draft
        </button>
      </div>

      <TenderEngagementPanel tenderId={proposal.tender_id} proposalContext />

      {isGenerating && (
        <motion.div
          initial={{ opacity: 0, y: 4 }}
          animate={{ opacity: 1, y: 0 }}
          className="rounded-xl border border-indigo-500/30 bg-indigo-500/10 p-5 text-indigo-200"
        >
          <p className="font-semibold">Analyzing Compliance Ledger... Drafting Executive Summary...</p>
        </motion.div>
      )}

      {generationError && (
        <motion.div
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, ease: 'easeOut' }}
          className="flex items-start gap-3 rounded-xl border border-amber-500/30 bg-amber-500/10 px-5 py-4 shadow-lg shadow-amber-500/5"
        >
          <div className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-amber-500/20">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="h-4 w-4 text-amber-400">
              <path fillRule="evenodd" d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.17 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 6a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 6zm0 9a1 1 0 100-2 1 1 0 000 2z" clipRule="evenodd" />
            </svg>
          </div>
          <div className="flex-1">
            <p className="text-sm font-semibold text-amber-200">{generationError}</p>
            <button
              onClick={() => setGenerationError(null)}
              className="mt-2 text-xs font-medium text-amber-400/80 underline decoration-amber-400/30 underline-offset-2 transition hover:text-amber-300 hover:decoration-amber-300/50"
            >
              Dismiss
            </button>
          </div>
        </motion.div>
      )}

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
        <div className="space-y-6 xl:col-span-2">
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
            <div className="mb-3 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <FileText className="h-5 w-5 text-sky-400" />
                <h2 className="text-lg font-semibold text-white">Strategic Executive Summary</h2>
              </div>
              <button
                onClick={handleCopySummary}
                disabled={!strategicSummary}
                className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-1.5 text-xs font-medium text-zinc-300 transition hover:border-zinc-600 hover:text-white disabled:cursor-not-allowed disabled:opacity-40"
              >
                {isCopied ? (
                  <>
                    <Check className="h-3.5 w-3.5 text-emerald-400" />
                    Copied
                  </>
                ) : (
                  <>
                    <Copy className="h-3.5 w-3.5" />
                    Copy
                  </>
                )}
              </button>
            </div>
            <textarea
              value={strategicSummary}
              onChange={(e) => setStrategicSummary(e.target.value)}
              rows={14}
              placeholder="Strategic summary will appear here after generation."
              className="w-full resize-y min-h-[200px] bg-gray-950 border border-gray-800 rounded-lg px-4 py-3 text-sm leading-6 text-gray-100 outline-none focus:ring-2 focus:ring-indigo-500/50 focus:border-indigo-500 transition-all placeholder:text-zinc-500"
            />
          </div>

          <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
            <div className="mb-4 flex items-center gap-2">
              <FileOutput className="h-5 w-5 text-emerald-400" />
              <h2 className="text-lg font-semibold text-white">Line Items</h2>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[620px] text-sm">
                <thead>
                  <tr className="border-b border-zinc-800 text-left text-zinc-400">
                    <th className="px-3 py-2">Item</th>
                    <th className="px-3 py-2 text-right">Qty</th>
                    <th className="px-3 py-2 text-right">Unit Price</th>
                    <th className="px-3 py-2 text-right">Total</th>
                  </tr>
                </thead>
                <tbody>
                  {lineItems.map((item, index) => (
                    <tr key={`${item.name}-${index}`} className="border-b border-zinc-900">
                      <td className="px-3 py-2 text-zinc-200">{item.name}</td>
                      <td className="px-3 py-2 text-right text-zinc-300">
                        {item.quantity} {item.unit}
                      </td>
                      <td className="px-3 py-2 text-right text-zinc-300">{item.unit_price.toLocaleString()}</td>
                      <td className="px-3 py-2 text-right font-medium text-emerald-300">
                        {item.total.toLocaleString()}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {lineItems.length === 0 && (
              <p className="text-sm text-zinc-500">No line items yet. Generate a strategic draft first.</p>
            )}
            {lineItems.length > 0 && (
              <p className="mt-4 text-right text-sm font-semibold text-zinc-200">
                Computed Total: {computedTotal.toLocaleString()} {proposal.tender_currency}
              </p>
            )}
          </div>
        </div>

        <div className="space-y-6">
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
            <h2 className="mb-4 text-lg font-semibold text-white">Commercial Inputs</h2>
            <div className="space-y-4">
              <div>
                <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-zinc-400">
                  Company Name
                </label>
                <input
                  type="text"
                  value={companyName}
                  onChange={(e) => setCompanyName(e.target.value)}
                  className="w-full bg-gray-950 border border-gray-800 rounded-lg px-4 py-3 text-gray-100 outline-none focus:ring-2 focus:ring-indigo-500/50 focus:border-indigo-500 transition-all"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-zinc-400">
                  Suggested Price ({proposal.tender_currency})
                </label>
                <input
                  type="text"
                  inputMode="numeric"
                  value={formatPriceDisplay(suggestedPrice)}
                  onChange={(e) => setSuggestedPrice(stripNonDigits(e.target.value))}
                  placeholder="21,890,000,000"
                  className="w-full bg-gray-950 border border-gray-800 rounded-lg px-4 py-3 text-gray-100 outline-none focus:ring-2 focus:ring-indigo-500/50 focus:border-indigo-500 transition-all"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-zinc-400">
                  Delivery Window
                </label>
                <input
                  type="text"
                  value={deliveryDays}
                  onChange={(e) => setDeliveryDays(e.target.value)}
                  placeholder="45 calendar days"
                  className="w-full bg-gray-950 border border-gray-800 rounded-lg px-4 py-3 text-gray-100 outline-none focus:ring-2 focus:ring-indigo-500/50 focus:border-indigo-500 transition-all"
                />
              </div>
            </div>
            <div className="mt-5">
              <button
                onClick={handleSave}
                disabled={isSaving}
                className="w-full inline-flex items-center justify-center gap-2 bg-indigo-600 hover:bg-indigo-500 text-white font-medium px-6 py-3 rounded-lg transition-colors disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                Save Draft
              </button>
            </div>
            <div className="mt-3 flex gap-3">
              <button
                onClick={handleGeneratePdf}
                disabled={isGeneratingPdf || !suggestedPrice}
                className="flex-1 inline-flex items-center justify-center gap-2 border border-gray-700 hover:bg-gray-800 text-gray-300 font-medium px-4 py-2.5 rounded-lg transition-colors disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isGeneratingPdf ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <FileOutput className="h-4 w-4" />
                )}
                Download PDF
              </button>
              <button
                onClick={handleGenerateDocx}
                disabled={isGeneratingDocx || !suggestedPrice}
                className="flex-1 inline-flex items-center justify-center gap-2 border border-gray-700 hover:bg-gray-800 text-gray-300 font-medium px-4 py-2.5 rounded-lg transition-colors disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isGeneratingDocx ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <FileType className="h-4 w-4" />
                )}
                Download Word
              </button>
            </div>
          </div>

          <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
            <h2 className="mb-4 text-lg font-semibold text-white">Tender Documents</h2>
            {(isLoadingDocs || isSyncingDocs) && (
              <div className="mb-4 flex items-center gap-2 rounded-lg border border-indigo-500/20 bg-indigo-500/10 px-3 py-2 text-sm text-indigo-200">
                <Loader2 className="h-4 w-4 animate-spin" />
                Preparing tender documents ({docsSyncProgress}%).
              </div>
            )}
            {docsSyncError && (
              <div className="mb-4 rounded-lg border border-amber-500/20 bg-amber-500/10 px-3 py-2 text-sm text-amber-200">
                {docsSyncError}
              </div>
            )}
            {!isLoadingDocs && !isSyncingDocs && !docsSyncError && documents.length === 0 && (
              <p className="text-sm text-zinc-500">No prepared documents found for this tender.</p>
            )}
            <div className="space-y-2">
              {documents.map((doc) => {
                const filename = getDocumentFilename(doc);
                const ext = getFileExtension(filename || doc.file_type);
                const isPdf = isPdfFile(ext) || doc.file_type?.toLowerCase() === 'pdf';
                const isArchive =
                  isArchiveFile(ext) || ['zip', 'rar', '7z', 'tar', 'gz'].includes(doc.file_type?.toLowerCase());
                const isAvailable = doc.download_status === 'available';
                const isPreviewAction = isPdf;
                const isBusy = isPreviewAction ? previewingDocId === doc.id : downloadingDocId === doc.id;
                const typeLabel = (ext || doc.file_type || 'file').toUpperCase();
                const isUnsupported = ['doc', 'xls', 'xlsx', 'rtf'].includes(ext || doc.file_type?.toLowerCase());
                const statusLabel = doc.analysis_text_available
                  ? 'Ready for analysis'
                  : doc.download_status === 'metadata_only' || doc.download_status === 'access_required'
                    ? 'Document discovered'
                    : doc.download_status === 'failed' && isUnsupported
                      ? 'Unsupported format'
                      : doc.download_status === 'failed'
                        ? 'Preparation failed'
                        : 'Document discovered';

                return (
                  <button
                    key={doc.id}
                    disabled={isBusy || !isAvailable}
                    onClick={() =>
                      isPreviewAction ? handleDocumentPreview(doc.id) : handleDocumentDownload(doc.id, filename)
                    }
                    className="flex w-full items-center justify-between gap-3 rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-2 text-left text-sm text-zinc-200 transition hover:border-zinc-700 disabled:cursor-not-allowed disabled:opacity-70"
                  >
                    <span className="flex min-w-0 items-center gap-2 truncate">
                      {isBusy ? (
                        <Loader2 className="h-4 w-4 shrink-0 animate-spin text-sky-400" />
                      ) : isArchive ? (
                        <FileArchive className="h-4 w-4 shrink-0 text-amber-400" />
                      ) : isPdf ? (
                        <FileText className="h-4 w-4 shrink-0 text-sky-400" />
                      ) : (
                        <FileType className="h-4 w-4 shrink-0 text-zinc-300" />
                      )}
                      <span className="truncate">{typeLabel} | {filename}</span>
                    </span>
                    <span className="inline-flex items-center gap-1 text-zinc-400">
                      {!isAvailable ? (
                        <span className="max-w-[180px] text-right text-xs font-medium text-amber-300">{statusLabel}</span>
                      ) : isBusy ? (
                        <span className="text-xs font-medium text-sky-300">Opening...</span>
                      ) : isPreviewAction ? (
                        <>
                          <FileText className="h-4 w-4" />
                          Preview
                        </>
                      ) : (
                        <>
                          <Download className="h-4 w-4" />
                          Download
                        </>
                      )}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      </div>

      <div className="flex justify-end">
        <button
          onClick={() => router.push('/dashboard/bid-preparation')}
          className="text-sm text-zinc-400 transition hover:text-zinc-200"
        >
          Back to Bid Preparation
        </button>
      </div>
    </div>
  );
}
