"use client";

import { use, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
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
} from "lucide-react";

import { api } from "@/lib/api";
import {
  formatCurrency as formatLocaleCurrency,
  formatDate as formatLocaleDate,
  formatNumber,
} from "@/i18n/formatters";
import type { CustomerSelectableLocale } from "@/i18n/locales";
import { BidiText } from "@/components/i18n/BidiText";
import { Button } from "@/components/ui/Button";
import { Alert } from "@/components/ui/Feedback";
import { TenderEngagementPanel } from "@/components/tenders/TenderEngagementPanel";
import type { EngagementStatus } from "@/types/engagement";
import type { TenderDocument, TenderStatus } from "@/types/tender";
import { isTenderActionable } from "@/types/tender";

interface StrategicLineItem {
  name: string;
  quantity: number;
  unit: string;
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
    commercial_price_origin?: string;
    price_free_draft?: {
      strategic_summary?: string;
      delivery_days?: string;
      line_items?: StrategicLineItem[];
    };
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

const escapePreviewHtml = (value: string) =>
  value.replace(
    /[&<>"']/g,
    (character) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        character
      ] ?? character,
  );

const previewLoadingHtml = (
  locale: CustomerSelectableLocale,
  title: string,
  help: string,
) => `<!doctype html>
<html lang="${locale}">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>${escapePreviewHtml(title)}</title>
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
      <h1>${escapePreviewHtml(title)}</h1>
      <p>${escapePreviewHtml(help)}</p>
    </main>
  </body>
</html>`;
const previewErrorHtml = (
  locale: CustomerSelectableLocale,
  title: string,
  help: string,
) => `<!doctype html>
<html lang="${locale}">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>${escapePreviewHtml(title)}</title>
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
      <h1>${escapePreviewHtml(title)}</h1>
      <p>${escapePreviewHtml(help)}</p>
    </main>
  </body>
</html>`;

/** Strip non-digits, return raw numeric string */
const stripNonDigits = (v: string) => v.replace(/\D/g, "");

/** Format a raw numeric string with commas: "21890000000" → "21,890,000,000" */
const formatPriceDisplay = (raw: string, locale: CustomerSelectableLocale) => {
  const digits = stripNonDigits(raw);
  if (!digits) return "";
  return formatNumber(Number(digits), locale);
};

/** File extension helper */
const getFileExtension = (value: string) => {
  const sanitized = value.split("?")[0].split("#")[0];
  const parts = sanitized.split(".");
  return parts.length > 1 ? parts[parts.length - 1].toLowerCase() : "";
};

const isArchiveFile = (ext: string) =>
  ["zip", "rar", "7z", "tar", "gz"].includes(ext);
const isPdfFile = (ext: string) => ext === "pdf";

const getDocumentFilename = (doc: TenderDocument) => {
  const fallbackExtension = (doc.file_type || "").trim().toLowerCase();
  if (doc.display_name) {
    return doc.display_name;
  }

  if (doc.original_filename) {
    return doc.original_filename;
  }

  if (doc.storage_filename) {
    return doc.storage_filename;
  }

  return fallbackExtension ? `document.${fallbackExtension}` : "document";
};

export default function BidPreparationWorkspacePage({
  params,
}: {
  params: Promise<{ proposalId: string }>;
}) {
  const resolvedParams = use(params);
  const router = useRouter();
  const t = useTranslations("bidPreparation");
  const tExplorer = useTranslations("explorer");
  const tMy = useTranslations("myTenders");
  const locale = useLocale() as CustomerSelectableLocale;
  const translateRef = useRef(t);
  translateRef.current = t;

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
  const [documentsError, setDocumentsError] = useState<string | null>(null);
  const [downloadingDocId, setDownloadingDocId] = useState<string | null>(null);
  const [previewingDocId, setPreviewingDocId] = useState<string | null>(null);

  const [companyName, setCompanyName] = useState("");
  const [strategicSummary, setStrategicSummary] = useState("");
  const [summaryEdited, setSummaryEdited] = useState(false);
  const [enteredPrice, setEnteredPrice] = useState("");
  const [deliveryDays, setDeliveryDays] = useState("");
  const [lineItems, setLineItems] = useState<StrategicLineItem[]>([]);

  const fetchTenderDocuments = useCallback(async (tenderId: string) => {
    const response = await api.get<TenderDocument[]>(
      `/tenders/${tenderId}/documents`,
    );
    setDocuments(response.data);
  }, []);

  useEffect(() => {
    const fetchProposal = async () => {
      try {
        const response = await api.get<Proposal>(
          `/proposals/${resolvedParams.proposalId}`,
        );
        const data = response.data;
        setProposal(data);

        const structured = data.structured_data ?? {};
        const priceFreeDraft = structured.price_free_draft;
        setStrategicSummary(
          (priceFreeDraft?.strategic_summary || structured.strategic_summary || structured.ai_summary || "").trim(),
        );
        setSummaryEdited(false);
        setEnteredPrice(
          structured.commercial_price_origin === "USER_ENTERED" && typeof structured.our_price === "number"
            ? String(structured.our_price)
            : "",
        );
        setDeliveryDays(
          priceFreeDraft?.delivery_days !== undefined || structured.delivery_days !== undefined
            ? String(priceFreeDraft?.delivery_days ?? structured.delivery_days)
            : "",
        );
        setLineItems(
          (priceFreeDraft?.line_items || structured.line_items || structured.ai_items || []).map((item) => ({
            name: item.name,
            quantity: Number(item.quantity) || 1,
            unit: item.unit,
          })),
        );
      } catch {
        console.error("Failed to load Bid Preparation:");
        setError(translateRef.current("notAvailable"));
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
        const res = await api.get("/vault");
        const name = res.data?.company_name;
        if (name) setCompanyName(name);
      } catch {
        // Vault not set up yet — keep field empty
      }
    };
    fetchVault();
  }, []);

  const proposalTenderId = proposal?.tender_id;

  useEffect(() => {
    if (!proposalTenderId) return;
    let isActive = true;
    setIsLoadingDocs(true);
    setDocumentsError(null);
    fetchTenderDocuments(proposalTenderId)
      .catch(() => {
        if (!isActive) return;
        setDocuments([]);
        console.error("Failed to load persisted Tender documents:");
        setDocumentsError(translateRef.current("documentsFailed"));
      })
      .finally(() => {
        if (isActive) setIsLoadingDocs(false);
      });
    return () => {
      isActive = false;
    };
  }, [fetchTenderDocuments, proposalTenderId]);

  const handleGenerateStrategicProposal = async () => {
    if (!proposal) return;
    try {
      setIsGenerating(true);
      setGenerationError(null);
      const response = await api.post<StrategicDraftResponse>(
        `/proposals/${proposal.id}/ai-draft`,
      );
      if (response.status < 200 || response.status >= 300) {
        throw new Error("Non-OK response from AI draft endpoint");
      }
      const draft = response.data;

      // Check if the AI returned an error inside the successful response
      const errorType = (draft as unknown as Record<string, unknown>)
        .error_type as string | undefined;
      if (errorType === "quota_exceeded") {
        setGenerationError(t("quotaReached"));
        return;
      }
      if (errorType === "model_overloaded") {
        setGenerationError(t("modelsBusy"));
        return;
      }

      setStrategicSummary(draft.strategic_summary || "");
      setSummaryEdited(true);
      setDeliveryDays(draft.delivery_days || "");
      setLineItems(
        (draft.line_items || []).map((item) => ({
          name: item.name,
          quantity: Number(item.quantity) || 1,
          unit: item.unit,
        })),
      );
    } catch (err: unknown) {
      // Parse structured error from backend if available
      const axiosErr = err as {
        response?: { data?: { detail?: string }; status?: number };
      };
      const status = axiosErr?.response?.status;
      const detail = axiosErr?.response?.data?.detail || "";

      if (status === 429 || detail.toLowerCase().includes("quota")) {
        setGenerationError(t("quotaReached"));
      } else if (status === 503 || detail.toLowerCase().includes("overload")) {
        setGenerationError(t("modelsBusy"));
      } else {
        setGenerationError(t("generationFailed"));
      }
    } finally {
      setIsGenerating(false);
    }
  };

  const handleDocumentDownload = useCallback(
    async (docId: string, filename?: string) => {
      setDownloadingDocId(docId);

      try {
        const response = await api.get(`/tenders/documents/${docId}/download`, {
          responseType: "blob",
        });

        const contentType =
          (typeof response.headers["content-type"] === "string" ? response.headers["content-type"] : undefined) || "application/octet-stream";
        const blob = new Blob([response.data], { type: contentType });
        const url = URL.createObjectURL(blob);

        const link = document.createElement("a");
        link.href = url;
        link.download = filename || `document_${docId}`;
        document.body.appendChild(link);
        link.click();
        link.remove();

        window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      } finally {
        window.setTimeout(() => {
          setDownloadingDocId((current) =>
            current === docId ? null : current,
          );
        }, 1200);
      }
    },
    [],
  );

  const handleDocumentPreview = useCallback(
    async (docId: string) => {
      setPreviewingDocId(docId);
      const previewTab = window.open("", "_blank");
      if (previewTab) {
        previewTab.opener = null;
        previewTab.document.write(
          previewLoadingHtml(
            locale,
            t("previewPreparingTitle"),
            t("previewPreparingHelp"),
          ),
        );
        previewTab.document.close();
      }

      try {
        const response = await api.get(`/tenders/documents/${docId}/download`, {
          responseType: "blob",
        });

        const contentType =
          (typeof response.headers["content-type"] === "string" ? response.headers["content-type"] : undefined) || "application/octet-stream";
        const blob = new Blob([response.data], { type: contentType });
        const url = URL.createObjectURL(blob);

        if (previewTab) {
          previewTab.location.replace(url);
        } else {
          window.open(url, "_blank", "noopener,noreferrer");
        }

        window.setTimeout(() => URL.revokeObjectURL(url), 60000);
      } catch {
        if (previewTab) {
          previewTab.document.open();
          previewTab.document.write(
            previewErrorHtml(
              locale,
              t("previewUnavailableTitle"),
              t("previewUnavailableHelp"),
            ),
          );
          previewTab.document.close();
        }
      } finally {
        window.setTimeout(() => {
          setPreviewingDocId((current) => (current === docId ? null : current));
        }, 1200);
      }
    },
    [locale, t],
  );

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
      const rawPrice = stripNonDigits(enteredPrice);
      const priceNum = Number(rawPrice);
      await api.put(`/proposals/${proposal.id}`, {
        ...(rawPrice && Number.isFinite(priceNum) && priceNum > 0 ? { our_price: priceNum } : {}),
        delivery_days: getDeliveryDaysInt(deliveryDays || "30"),
        structured_data: {
          ...(proposal.structured_data || {}),
          price_free_draft: {
            ...(proposal.structured_data?.price_free_draft || {}),
            ...(summaryEdited ? { strategic_summary: strategicSummary } : {}),
            delivery_days: deliveryDays,
            line_items: lineItems,
          },
        },
      });
      setProposal((prev) =>
        prev
          ? {
              ...prev,
              structured_data: {
                ...(prev.structured_data || {}),
                ...(rawPrice && priceNum > 0 ? { our_price: priceNum, commercial_price_origin: "USER_ENTERED" } : {}),
                price_free_draft: {
                  ...(prev.structured_data?.price_free_draft || {}),
                  ...(summaryEdited ? { strategic_summary: strategicSummary } : {}),
                  delivery_days: deliveryDays,
                  line_items: lineItems,
                },
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
      const rawPrice = stripNonDigits(enteredPrice);
      const response = await api.post(
        `/proposals/${proposal.id}/generate-pdf`,
        {
          price: parseFloat(rawPrice || "0"),
          delivery_days: getDeliveryDaysInt(deliveryDays || "30"),
          company_name: companyName,
        },
        { responseType: "blob" },
      );
      const blob = new Blob([response.data], { type: "application/pdf" });
      const url = window.URL.createObjectURL(blob);
      window.open(url, "_blank");
    } finally {
      setIsGeneratingPdf(false);
    }
  };

  const handleGenerateDocx = async () => {
    if (!proposal) return;
    setIsGeneratingDocx(true);
    try {
      const rawPrice = stripNonDigits(enteredPrice);
      const response = await api.post(
        `/proposals/${proposal.id}/export/docx`,
        {
          price: parseFloat(rawPrice || "0"),
          delivery_days: getDeliveryDaysInt(deliveryDays || "30"),
          company_name: companyName,
        },
        { responseType: "blob" },
      );
      const blob = new Blob([response.data], {
        type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      });
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
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

  const localizedTenderStatus = (status: TenderStatus) =>
    status === "OPEN"
      ? tExplorer("status.open")
      : status === "CLOSED"
        ? tExplorer("status.closed")
        : status === "CANCELLED"
          ? tExplorer("status.cancelled")
          : tExplorer("status.unknown");
  const localizedEngagementStatus = (status: EngagementStatus) =>
    status === "SAVED"
      ? tMy("statuses.saved")
      : status === "EVALUATING"
        ? tMy("statuses.evaluating")
        : status === "PREPARING"
          ? tMy("statuses.preparing")
          : status === "SUBMITTED"
            ? tMy("statuses.submitted")
            : status === "WON"
              ? tMy("statuses.won")
              : status === "LOST"
                ? tMy("statuses.lost")
                : tMy("statuses.dismissed");

  if (isLoading) {
    return (
      <div className="customer-page proposal-state" role="status">
        <Loader2 className="ds-spin" aria-hidden />
        {t("loadingDocuments")}
      </div>
    );
  }

  if (error || !proposal) {
    return (
      <div className="customer-page ds-container-content ds-stack">
        <Link href="/dashboard/tenders" className="ds-button ds-button-ghost proposal-back">
          <ArrowLeft className="rtl-mirror" aria-hidden />
          {t("backExplorer")}
        </Link>
        <Alert tone="danger" title={error || t("notAvailable")} />
      </div>
    );
  }

  const actionable = isTenderActionable(proposal.tender_status);

  return (
    <div className="customer-page proposal-page ds-container-data ds-stack">
      <header className="ds-page-header proposal-header">
        <div>
          <Link
            href={`/dashboard/tenders/${proposal.tender_id}`}
            className="ds-button ds-button-ghost proposal-back"
          >
            <ArrowLeft className="rtl-mirror" aria-hidden />
            {t("backDetails")}
          </Link>
          <h1>
            <BidiText>{proposal.tender_title}</BidiText>
          </h1>
          <p className="ds-muted">
            {t("summaryLine", {
              budget: formatLocaleCurrency(
                proposal.tender_budget,
                proposal.tender_currency,
                locale,
              ),
              deadline: formatLocaleDate(proposal.tender_deadline, locale),
              region: proposal.tender_region || t("noRegion"),
            })}
          </p>
          <div className="ds-row proposal-statuses">
            <span className={`ds-badge ${proposal.tender_status === "OPEN" ? "ds-tone-success" : "ds-tone-warning"}`}>
              {t("tenderStatus", {
                status: localizedTenderStatus(proposal.tender_status),
              })}
            </span>
            {proposal.engagement_status ? (
              <span className="ds-badge ds-tone-info">
                {t("engagement", {
                  status: localizedEngagementStatus(proposal.engagement_status),
                })}
              </span>
            ) : null}
          </div>
        </div>
        <Button
          onClick={handleGenerateStrategicProposal}
          disabled={isGenerating || !actionable}
          title={!actionable ? t("actionUnavailable") : t("generateStrategic")}
          loading={isGenerating}
          leadingIcon={<Sparkles aria-hidden />}
        >
          {t("generateStrategic")}
        </Button>
      </header>

      <TenderEngagementPanel tenderId={proposal.tender_id} proposalContext />

      {isGenerating && (
        <Alert tone="info" title={t("generatingStrategic")} />
      )}

      {generationError && (
        <Alert tone="warning" title={generationError} action={<Button size="sm" variant="ghost" onClick={() => setGenerationError(null)}>{t("dismiss")}</Button>} />
      )}

      <div className="proposal-layout">
        <div className="ds-stack">
          <section className="ds-surface proposal-section">
            <div className="proposal-section-heading">
              <div><FileText aria-hidden /><h2>{t("executiveSummary")}</h2></div>
              <Button
                size="sm"
                variant="secondary"
                onClick={handleCopySummary}
                disabled={!strategicSummary}
                leadingIcon={isCopied ? <Check aria-hidden /> : <Copy aria-hidden />}
              >
                {isCopied ? t("copied") : t("copy")}
              </Button>
            </div>
            {!summaryEdited && !proposal.structured_data?.price_free_draft?.strategic_summary &&
              (proposal.structured_data?.strategic_summary || proposal.structured_data?.ai_summary) && (
                <p className="ds-muted ds-text-small">{t("historicalSummaryHelp")}</p>
              )}
            <textarea
              dir="auto"
              value={strategicSummary}
              onChange={(e) => { setStrategicSummary(e.target.value); setSummaryEdited(true); }}
              rows={14}
              placeholder={t("summaryPlaceholder")}
              className="ds-control proposal-summary"
            />
          </section>

          <section className="ds-surface proposal-section">
            <div className="proposal-section-heading">
              <div><FileOutput aria-hidden /><h2>{t("lineItems")}</h2></div>
            </div>
            <div className="proposal-table-scroll">
              <table className="proposal-table">
                <thead>
                  <tr><th scope="col">{t("item")}</th><th scope="col">{t("quantity")}</th>
                  </tr>
                </thead>
                <tbody>
                  {lineItems.map((item, index) => (
                    <tr key={`${item.name}-${index}`}>
                      <td><BidiText>{item.name}</BidiText></td>
                      <td className="ds-numeric">
                        {item.quantity} {item.unit}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {lineItems.length === 0 && (
              <p className="ds-muted proposal-empty">{t("noLineItems")}</p>
            )}
          </section>
        </div>

        <aside className="ds-stack">
          <section className="ds-surface proposal-section">
            <div className="proposal-section-heading"><h2>{t("commercialInputs")}</h2></div>
            <div className="proposal-fields">
              <label className="ds-field"><span className="ds-field-label">{t("companyName")}</span>
                <input
                  dir="auto"
                  type="text"
                  value={companyName}
                  onChange={(e) => setCompanyName(e.target.value)}
                  className="ds-control"
                />
              </label>
              <label className="ds-field"><span className="ds-field-label">{t("enteredPrice", { currency: proposal.tender_currency })}</span>
                <input
                  dir="ltr"
                  type="text"
                  inputMode="numeric"
                  value={formatPriceDisplay(enteredPrice, locale)}
                  onChange={(e) =>
                    setEnteredPrice(stripNonDigits(e.target.value))
                  }
                  className="ds-control technical-ltr"
                />
              </label>
              <label className="ds-field"><span className="ds-field-label">{t("deliveryWindow")}</span>
                <input
                  dir="auto"
                  type="text"
                  value={deliveryDays}
                  onChange={(e) => setDeliveryDays(e.target.value)}
                  placeholder={t("deliveryPlaceholder")}
                  className="ds-control"
                />
              </label>
            </div>
            <div className="proposal-actions">
              <Button
                onClick={handleSave}
                loading={isSaving}
                leadingIcon={<Save aria-hidden />}
              >
                {t("saveDraft")}
              </Button>
              <Button
                variant="secondary"
                onClick={handleGeneratePdf}
                disabled={isGeneratingPdf || !enteredPrice || Number(enteredPrice) <= 0}
                loading={isGeneratingPdf}
                leadingIcon={<FileOutput aria-hidden />}
              >
                {t("downloadPdf")}
              </Button>
              <Button
                variant="secondary"
                onClick={handleGenerateDocx}
                disabled={isGeneratingDocx || !enteredPrice || Number(enteredPrice) <= 0}
                loading={isGeneratingDocx}
                leadingIcon={<FileType aria-hidden />}
              >
                {t("downloadWord")}
              </Button>
            </div>
          </section>

          <section className="ds-surface proposal-section">
            <div className="proposal-section-heading"><h2>{t("documents")}</h2></div>
            {isLoadingDocs && (
              <Alert tone="info" title={t("loadingDocuments")} />
            )}
            {documentsError && (
              <Alert tone="warning" title={documentsError} />
            )}
            {!isLoadingDocs && !documentsError && documents.length === 0 && (
              <p className="ds-muted proposal-empty">{t("noPreparedDocuments")}</p>
            )}
            <div className="proposal-documents">
              {documents.map((doc) => {
                const filename = getDocumentFilename(doc);
                const ext = getFileExtension(filename || doc.file_type);
                const isPdf =
                  isPdfFile(ext) || doc.file_type?.toLowerCase() === "pdf";
                const isArchive =
                  isArchiveFile(ext) ||
                  ["zip", "rar", "7z", "tar", "gz"].includes(
                    doc.file_type?.toLowerCase(),
                  );
                const isAvailable = doc.download_status === "available";
                const isPreviewAction = isPdf;
                const isBusy = isPreviewAction
                  ? previewingDocId === doc.id
                  : downloadingDocId === doc.id;
                const typeLabel = (
                  ext ||
                  doc.file_type ||
                  "file"
                ).toUpperCase();
                const isUnsupported = ["doc", "xls", "xlsx", "rtf"].includes(
                  ext || doc.file_type?.toLowerCase(),
                );
                const statusLabel = doc.analysis_text_available
                  ? t("documentReady")
                  : doc.download_status === "metadata_only" ||
                      doc.download_status === "access_required"
                    ? t("documentDiscovered")
                    : doc.download_status === "failed" && isUnsupported
                      ? t("unsupportedFormat")
                      : doc.download_status === "failed"
                        ? t("preparationFailed")
                        : t("documentDiscovered");

                return (
                  <button
                    key={doc.id}
                    disabled={isBusy || !isAvailable}
                    onClick={() =>
                      isPreviewAction
                        ? handleDocumentPreview(doc.id)
                        : handleDocumentDownload(doc.id, filename)
                    }
                    className="proposal-document"
                  >
                    <span className="proposal-document-name">
                      {isBusy ? (
                        <Loader2 className="ds-spin" aria-hidden />
                      ) : isArchive ? (
                        <FileArchive aria-hidden />
                      ) : isPdf ? (
                        <FileText aria-hidden />
                      ) : (
                        <FileType aria-hidden />
                      )}
                      <span>
                        {typeLabel} | {filename}
                      </span>
                    </span>
                    <span className="proposal-document-action ds-muted">
                      {!isAvailable ? (
                        <span>{statusLabel}</span>
                      ) : isBusy ? (
                        <span>{t("opening")}</span>
                      ) : isPreviewAction ? (
                        <>
                          <FileText aria-hidden />
                          {t("preview")}
                        </>
                      ) : (
                        <>
                          <Download aria-hidden />
                          {t("download")}
                        </>
                      )}
                    </span>
                  </button>
                );
              })}
            </div>
          </section>
        </aside>
      </div>

      <div className="proposal-footer">
        <Button
          variant="ghost"
          onClick={() => router.push("/dashboard/bid-preparation")}
        >
          {t("back")}
        </Button>
      </div>
    </div>
  );
}
