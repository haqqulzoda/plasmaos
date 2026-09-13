"use client";

import { Pagination } from "@/components/ui/Navigation";
import {
  PageHeader,
  SectionHeader,
  Surface,
  StatusBadge,
  PageSkeleton,
  EmptyState,
  Metric,
  type Tone,
} from "@/components/ui/Display";
import { Button, ButtonLink } from "@/components/ui/Button";
import { Select, Textarea } from "@/components/ui/Forms";
import { Dialog, Drawer } from "@/components/ui/Overlay";
import { Alert } from "@/components/ui/Feedback";
import { BidiText, TechnicalText } from "@/components/i18n/BidiText";
import { formatDate } from "@/i18n/formatters";
import type { CustomerSelectableLocale } from "@/i18n/locales";
import { useCollectionOffset } from "@/lib/useCollectionOffset";
import { useState, useEffect, use, useMemo, useRef } from "react";
import { useLocale, useTranslations } from "next-intl";
import DocumentViewer from "@/components/workspace/DocumentViewer";
import type {
  DynamicRequirements,
  DynamicEvaluation,
  AnalyzeTenderResponse,
  AnalysisVersionMetadata,
  ComplianceVerdictStatus,
  HybridCompliancePayload,
  RequirementMatchDetail,
  OverrideResponse,
} from "@/types/compliance";
import type { Tender, TenderDocument } from "@/types/tender";
import { isTenderActionable } from "@/types/tender";
import { extractHybridCompliance } from "@/lib/useHybridCompliance";
import { api } from "@/lib/api";
import {
  CUSTOMER_ANALYSIS_LANGUAGES,
  DEFAULT_ANALYSIS_LANGUAGE,
  analysisContentDirection,
  analysisLanguageLabel,
  normalizeCustomerAnalysisLanguage,
  type AnalysisLanguage,
  type CustomerAnalysisLanguage,
} from "@/i18n/analysisLanguages";
import { ArrowLeft, FileSearch, Download, Sparkles } from "lucide-react";

function extractContentHash(
  data: Record<string, unknown> | null | undefined,
): string | null {
  if (!data || typeof data !== "object") return null;
  const raw = (data as { content_hash?: unknown }).content_hash;
  return typeof raw === "string" && raw.trim().length > 0 ? raw : null;
}

/**
 * Deterministic hash for requirement text → synthetic node ID.
 * Used when a requirement lacks a taxonomy_node_id (token-overlap matches).
 * FNV-1a 32-bit: fast, deterministic, zero dependencies.
 */
function hashSnippet(text: string): string {
  let hash = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193);
  }
  return (hash >>> 0).toString(16).padStart(8, "0");
}

type VerdictTone = "success" | "review" | "danger" | "pending";

type UiVerdict = {
  status: ComplianceVerdictStatus | "PENDING";
  labelKey:
    | "verdict.notEligible"
    | "verdict.withReview"
    | "verdict.needsReview"
    | "verdict.compliant"
    | "verdict.pending";
  tone: VerdictTone;
};

function safeDecodeURIComponent(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

function stripStoredNamePrefix(filename: string): string {
  const [, prefix, remainder] = filename.match(/^([a-f0-9]{32})_(.+)$/i) ?? [];
  return prefix && remainder ? remainder : filename;
}

function basenameFromPathish(value: string | null | undefined): string {
  const raw = (value ?? "").trim();
  if (!raw) return "";

  try {
    const parsed = new URL(raw);
    const queryPath = parsed.searchParams.get("path");
    const candidate = safeDecodeURIComponent(queryPath || parsed.pathname);
    return stripStoredNamePrefix(
      candidate.split(/[\\/]/).filter(Boolean).pop() ?? "",
    );
  } catch {
    const candidate = safeDecodeURIComponent(raw).split("?")[0].split("#")[0];
    return stripStoredNamePrefix(
      candidate.split(/[\\/]/).filter(Boolean).pop() ?? candidate,
    );
  }
}

function normalizeFilenameValue(value: string): string {
  return value.normalize("NFKC").toLowerCase().replace(/\s+/g, " ").trim();
}

function repairUtf8Mojibake(value: string): string {
  const raw = value.trim();
  if (!raw || !/[ÃÂÐÑ]/.test(raw)) return raw;

  const chars = Array.from(raw);
  const bytes = chars.map((char) => char.charCodeAt(0));
  if (bytes.some((byte) => byte > 255)) return raw;

  try {
    return (
      new TextDecoder("utf-8", { fatal: true }).decode(new Uint8Array(bytes)) ||
      raw
    );
  } catch {
    return raw;
  }
}

function normalizedFilenameCandidates(
  value: string | null | undefined,
): string[] {
  const basename = basenameFromPathish(value);
  const repairedBasename = repairUtf8Mojibake(basename);

  return Array.from(
    new Set(
      [basename, repairedBasename].map(normalizeFilenameValue).filter(Boolean),
    ),
  );
}

function getFileExtension(value: string | null | undefined): string {
  const filename = basenameFromPathish(value);
  const parts = filename.split(".");
  return parts.length > 1 ? parts[parts.length - 1].toLowerCase() : "";
}

function filenameFromContentDisposition(value: string | null): string | null {
  if (!value) return null;

  const utf8Match = value.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match?.[1]) {
    return safeDecodeURIComponent(utf8Match[1].replace(/^"|"$/g, ""));
  }

  const asciiMatch = value.match(/filename="?([^";]+)"?/i);
  return asciiMatch?.[1] ?? null;
}

async function complianceExportErrorKey(
  error: unknown,
): Promise<"exportSignIn" | "exportUnavailable" | "exportFailed"> {
  const response = (error as { response?: { data?: unknown; status?: number } })
    ?.response;
  const status = response?.status;

  if (response?.data instanceof Blob)
    await response.data.text().catch(() => "");
  if (status === 401) return "exportSignIn";
  if (status === 403 || status === 404) return "exportUnavailable";
  return "exportFailed";
}

function documentErrorKey(
  response: Response,
):
  | "documentSignIn"
  | "documentForbidden"
  | "documentUnavailable"
  | "documentOpenFailed" {
  if (response.status === 401) return "documentSignIn";
  if (response.status === 403) return "documentForbidden";
  if (response.status === 404) return "documentUnavailable";
  return "documentOpenFailed";
}

function getDocumentDisplayName(doc: TenderDocument): string {
  return (
    basenameFromPathish(doc.display_name) ||
    basenameFromPathish(doc.original_filename) ||
    basenameFromPathish(doc.storage_filename) ||
    (doc.file_type ? `document.${doc.file_type}` : "document")
  );
}

function documentCandidateNames(doc: TenderDocument): string[] {
  return [
    doc.display_name,
    doc.original_filename,
    getDocumentDisplayName(doc),
    basenameFromPathish(doc.storage_filename),
    ...(doc.parsed_source_filenames ?? []),
    ...(doc.archive_inner_filenames ?? []),
  ].filter((value): value is string => Boolean(value && value.trim()));
}

function getDocumentExtension(doc: TenderDocument | null): string {
  if (!doc) return "";
  return (
    getFileExtension(doc.display_name) ||
    getFileExtension(doc.original_filename) ||
    getFileExtension(doc.storage_filename) ||
    doc.file_type.toLowerCase()
  );
}

function isPdfDocument(doc: TenderDocument | null): boolean {
  return (
    getDocumentExtension(doc) === "pdf" ||
    doc?.file_type?.toLowerCase() === "pdf"
  );
}

function isArchiveDocument(doc: TenderDocument | null): boolean {
  return ["zip", "rar", "7z", "tar", "gz"].includes(getDocumentExtension(doc));
}

function isArchiveInnerSource(
  requirement: RequirementMatchDetail,
  doc: TenderDocument | null,
): boolean {
  if (!doc || !isArchiveDocument(doc)) return false;
  const sourceNames = new Set(
    normalizedFilenameCandidates(requirement.source_filename),
  );
  return (doc.archive_inner_filenames ?? []).some((filename) =>
    normalizedFilenameCandidates(filename).some((candidate) =>
      sourceNames.has(candidate),
    ),
  );
}

function getRequirementKey(detail: RequirementMatchDetail): string {
  return [
    detail.taxonomy_node_id ?? `synth_${hashSnippet(detail.raw_text_snippet)}`,
    detail.source_filename,
    detail.source_page,
    detail.verdict,
    detail.exact_quote || detail.raw_text_snippet,
  ].join("|");
}

function buildDocumentFilenameIndex(
  documents: TenderDocument[],
): Map<string, TenderDocument> {
  const index = new Map<string, TenderDocument>();

  for (const doc of documents) {
    for (const candidate of documentCandidateNames(doc)) {
      for (const normalized of normalizedFilenameCandidates(candidate)) {
        if (normalized && !index.has(normalized)) {
          index.set(normalized, doc);
        }
      }
    }
  }

  return index;
}

function resolveDocumentForRequirement(
  detail: RequirementMatchDetail | null,
  documentIndex: Map<string, TenderDocument>,
): TenderDocument | null {
  if (!detail) return null;
  for (const candidate of normalizedFilenameCandidates(
    detail.source_filename,
  )) {
    const doc = documentIndex.get(candidate);
    if (doc) return doc;
  }
  return null;
}

function deriveHybridVerdict(
  hybridCompliance: HybridCompliancePayload | null,
): UiVerdict | null {
  if (!hybridCompliance) return null;

  const knownStatus =
    hybridCompliance.verdict_status &&
    [
      "NOT_ELIGIBLE",
      "NEEDS_REVIEW",
      "ELIGIBLE_WITH_REVIEW",
      "COMPLIANT",
    ].includes(hybridCompliance.verdict_status)
      ? hybridCompliance.verdict_status
      : undefined;
  const status =
    knownStatus ??
    (hybridCompliance.failed_dealbreakers.length > 0 ||
    hybridCompliance.failed_count > 0
      ? "NOT_ELIGIBLE"
      : hybridCompliance.manual_reviews_required.length > 0 ||
          hybridCompliance.manual_review_count > 0
        ? hybridCompliance.satisfied_count > 0
          ? "ELIGIBLE_WITH_REVIEW"
          : "NEEDS_REVIEW"
        : hybridCompliance.satisfied_count > 0
          ? "COMPLIANT"
          : (hybridCompliance.recorded_obligations_count ?? 0) > 0
            ? "ELIGIBLE_WITH_REVIEW"
            : "NEEDS_REVIEW");

  if (status === "NOT_ELIGIBLE") {
    return { status, labelKey: "verdict.notEligible", tone: "danger" };
  }
  if (status === "ELIGIBLE_WITH_REVIEW") {
    return { status, labelKey: "verdict.withReview", tone: "review" };
  }
  if (status === "NEEDS_REVIEW") {
    return { status, labelKey: "verdict.needsReview", tone: "review" };
  }
  return { status, labelKey: "verdict.compliant", tone: "success" };
}

function deriveUiVerdict(
  hybridCompliance: HybridCompliancePayload | null,
  evaluation: DynamicEvaluation | null,
): UiVerdict {
  const hybridVerdict = deriveHybridVerdict(hybridCompliance);
  if (hybridVerdict) return hybridVerdict;

  if (!evaluation)
    return { status: "PENDING", labelKey: "verdict.pending", tone: "pending" };
  return evaluation.is_compliant
    ? { status: "COMPLIANT", labelKey: "verdict.compliant", tone: "success" }
    : {
        status: "NOT_ELIGIBLE",
        labelKey: "verdict.notEligible",
        tone: "danger",
      };
}

function deriveStatusMessage(
  hybridCompliance: HybridCompliancePayload | null,
  evaluation: DynamicEvaluation,
): string | null {
  if (hybridCompliance) {
    const manualOnly =
      hybridCompliance.failed_dealbreakers.length === 0 &&
      hybridCompliance.failed_count === 0 &&
      hybridCompliance.satisfied_count === 0 &&
      (hybridCompliance.manual_reviews_required.length > 0 ||
        hybridCompliance.manual_review_count > 0);

    if (manualOnly) {
      return null;
    }

    return hybridCompliance.status_message;
  }

  return evaluation.status_message ?? "";
}

export default function CompliancePage({
  params,
}: {
  params: Promise<{ tenderId: string }>;
}) {
  const t = useTranslations("compliance");
  const locale = useLocale() as CustomerSelectableLocale;
  const tCommon = useTranslations("common");
  const translateRef = useRef(t);
  useEffect(() => {
    translateRef.current = t;
  }, [t]);
  const { tenderId } = use(params);

  // ── State ──
  const [isLoading, setIsLoading] = useState(false);
  const [requirements, setRequirements] = useState<DynamicRequirements | null>(
    null,
  );
  const [evaluation, setEvaluation] = useState<DynamicEvaluation | null>(null);
  const [analysisId, setAnalysisId] = useState<string | null>(null);
  const [resolvedTenderId, setResolvedTenderId] = useState<string>(tenderId);
  const [rawText, setRawText] = useState<string>("");
  const [tenderTitle, setTenderTitle] = useState<string>("");
  const [complianceGuardMessage, setComplianceGuardMessage] = useState<
    string | null
  >(null);
  const [isLoadingText, setIsLoadingText] = useState(true);
  const [textAccessReadyVersion, setTextAccessReadyVersion] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [elapsedTime, setElapsedTime] = useState<number | null>(null);
  const [acceptedNodeIds, setAcceptedNodeIds] = useState<string[]>([]);
  const [hybridCompliance, setHybridCompliance] =
    useState<HybridCompliancePayload | null>(null);
  const [contentHash, setContentHash] = useState<string | null>(null);
  const [overrideSeal, setOverrideSeal] = useState<string | null>(null);
  const [documents, setDocuments] = useState<TenderDocument[]>([]);
  const [isLoadingDocuments, setIsLoadingDocuments] = useState(false);
  const [documentFetchError, setDocumentFetchError] = useState<string | null>(
    null,
  );
  const [selectedRequirement, setSelectedRequirement] =
    useState<RequirementMatchDetail | null>(null);
  const [isDownloadingPdf, setIsDownloadingPdf] = useState(false);
  const [selectedAnalysisLanguage, setSelectedAnalysisLanguage] =
    useState<CustomerAnalysisLanguage>(DEFAULT_ANALYSIS_LANGUAGE);
  const [resultAnalysisLanguage, setResultAnalysisLanguage] =
    useState<AnalysisLanguage | null>(null);
  const [analysisVersion, setAnalysisVersion] = useState<number | null>(null);
  const [historyOffset, setHistoryOffset] = useCollectionOffset("historyPage");
  const [historyHasMore, setHistoryHasMore] = useState(false);
  const [analysisStatus, setAnalysisStatus] = useState<string | null>(null);
  const [loadingVersion, setLoadingVersion] = useState(false);
  const [loadingResult, setLoadingResult] = useState(true);
  const [historyError, setHistoryError] = useState(false);
  const [historyReload, setHistoryReload] = useState(0);
  const [latestVersion, setLatestVersion] = useState<number | null>(null);
  const [coverage, setCoverage] = useState<Record<string, unknown> | null>(
    null,
  );
  const [snapshotCompleteness, setSnapshotCompleteness] = useState<
    string | null
  >(null);
  const [contextOpen, setContextOpen] = useState(false);
  const evidenceTrigger = useRef<HTMLElement | null>(null);
  const [analysisHistory, setAnalysisHistory] = useState<
    AnalysisVersionMetadata[]
  >([]);

  useEffect(() => {
    let active = true;
    api
      .get<{ default_analysis_language?: string | null }>("/users/me")
      .then(({ data }) => {
        if (active)
          setSelectedAnalysisLanguage(
            normalizeCustomerAnalysisLanguage(data.default_analysis_language),
          );
      })
      .catch(() => {
        // English is the contractual fallback; UI locale is intentionally not consulted.
      });
    return () => {
      active = false;
    };
  }, []);

  // ── Fetch compiled source text on mount ──
  useEffect(() => {
    const fetchTenderText = async () => {
      setIsLoadingText(true);
      setComplianceGuardMessage(null);
      try {
        const resolvedId = tenderId;
        const { data: tenderData } = await api.get<Tender>(
          `/tenders/${resolvedId}`,
        );

        setResolvedTenderId(resolvedId);
        setTenderTitle(
          tenderData?.title ||
            translateRef.current("fallbackTender", {
              id: resolvedId.slice(0, 8),
            }),
        );

        if (tenderData && !isTenderActionable(tenderData)) {
          setRawText("");
          setComplianceGuardMessage(
            tenderData.status === "CLOSED"
              ? translateRef.current("guardClosed")
              : translateRef.current("guardCancelled"),
          );
          setTextAccessReadyVersion((version) => version + 1);
          return;
        }

        if (tenderData && !tenderData.compliance_analysis_available) {
          setRawText("");
          setComplianceGuardMessage(translateRef.current("guardUnavailable"));
          setTextAccessReadyVersion((version) => version + 1);
          return;
        }

        const textResponse = await api.get(
          `/tenders/${resolvedId}/compiled-text`,
        );

        setRawText(textResponse.data.compiled_master_text || "");
        setTextAccessReadyVersion((version) => version + 1);
      } catch {
        setError(translateRef.current("loadTextFailed"));
        setLoadingResult(false);
      } finally {
        setIsLoadingText(false);
      }
    };

    fetchTenderText();
  }, [tenderId]);

  // ── Load synchronized source documents for evidence preview ──
  useEffect(() => {
    if (!resolvedTenderId) return;

    const fetchTenderDocuments = async () => {
      setIsLoadingDocuments(true);
      setDocumentFetchError(null);

      try {
        const { data } = await api.get<TenderDocument[]>(
          `/tenders/${resolvedTenderId}/documents`,
        );
        setDocuments(Array.isArray(data) ? data : []);
      } catch {
        setDocuments([]);
        setDocumentFetchError(translateRef.current("loadDocumentsFailed"));
      } finally {
        setIsLoadingDocuments(false);
      }
    };

    fetchTenderDocuments();
  }, [resolvedTenderId]);

  // ── Load cached analysis on mount ──
  useEffect(() => {
    if (!resolvedTenderId || textAccessReadyVersion === 0) return;

    const fetchCachedAnalysis = async () => {
      setLoadingResult(true);
      try {
        const { data } = await api.get(
          `/tenders/${resolvedTenderId}/latest-analysis`,
        );
        if (data.analysis_id && data.requirements && data.evaluation) {
          setAnalysisId(data.analysis_id);
          setRequirements(data.requirements);
          setEvaluation(data.evaluation);
          setHybridCompliance(extractHybridCompliance(data));
          setContentHash(extractContentHash(data));
          setOverrideSeal(
            ((data as Record<string, unknown>).override_seal as
              | string
              | null) ?? null,
          );
          setResultAnalysisLanguage(
            (data.analysis_language as AnalysisLanguage | null) ?? null,
          );
          setAnalysisVersion(
            typeof data.version_number === "number"
              ? data.version_number
              : null,
          );
          setLatestVersion(
            typeof data.version_number === "number"
              ? data.version_number
              : null,
          );
          setCoverage(data.coverage_metadata ?? null);
          setAnalysisStatus(data.analysis_status ?? null);
        }
      } catch {
        setError(translateRef.current("redesign.loadResultFailed"));
      } finally {
        setLoadingResult(false);
      }
    };

    fetchCachedAnalysis();
  }, [resolvedTenderId, textAccessReadyVersion]);

  useEffect(() => {
    if (!resolvedTenderId || !analysisId) {
      setAnalysisHistory([]);
      return;
    }
    let active = true;
    setHistoryError(false);
    api
      .get<AnalysisVersionMetadata[]>(
        `/tenders/${resolvedTenderId}/analyses/${analysisId}/versions`,
        { params: { limit: 25, offset: historyOffset } },
      )
      .then(({ data, headers }) => {
        if (active) {
          setAnalysisHistory(Array.isArray(data) ? data : []);
          setHistoryHasMore(headers["x-has-more"] === "true");
        }
      })
      .catch(() => {
        if (active) setHistoryError(true);
      });
    return () => {
      active = false;
    };
  }, [resolvedTenderId, analysisId, historyOffset, historyReload]);

  // ── Load persisted risk overrides scoped to current analysis ──
  useEffect(() => {
    if (!resolvedTenderId || !analysisId) return;

    const fetchOverrides = async () => {
      try {
        const { data } = await api.get(
          `/tenders/${resolvedTenderId}/overrides?analysis_id=${analysisId}`,
        );
        const ids = Array.isArray(data.accepted_node_ids)
          ? data.accepted_node_ids
          : [];
        setAcceptedNodeIds(ids.map((id: string) => id.toLowerCase()));
      } catch {
        setAcceptedNodeIds([]);
      }
    };

    fetchOverrides();
  }, [resolvedTenderId, analysisId]);

  // ── API Call: Trigger Compliance Scan ──
  const handleAnalyzeTender = async () => {
    if (complianceGuardMessage) {
      setError(complianceGuardMessage);
      return;
    }
    setIsLoading(true);
    setError(null);
    const force = evaluation !== null;
    const startTime = performance.now();

    // Use force=true when re-scanning (cached results already shown)
    const query = new URLSearchParams({
      analysis_language: selectedAnalysisLanguage,
    });
    if (force) query.set("force", "true");

    try {
      const { data } = await api.post<AnalyzeTenderResponse>(
        `/tenders/${resolvedTenderId}/analyze?${query.toString()}`,
      );
      if (
        (data as AnalyzeTenderResponse & { analysis_status?: string })
          .analysis_status === "failed"
      ) {
        setHistoryReload((value) => value + 1);
        throw new Error("analysis execution failed");
      }
      setAnalysisStatus(
        (data as AnalyzeTenderResponse & { analysis_status?: string })
          .analysis_status ?? "completed",
      );
      const elapsed = ((performance.now() - startTime) / 1000).toFixed(1);

      setAnalysisId(data.analysis_id ?? null);
      setRequirements(data.requirements ?? null);
      setEvaluation(data.evaluation ?? null);
      setHybridCompliance(
        extractHybridCompliance(data as unknown as Record<string, unknown>),
      );
      setContentHash(data.content_hash);
      setOverrideSeal(data.override_seal ?? null);
      setResultAnalysisLanguage(data.analysis_language);
      setAnalysisVersion(data.version_number);
      setLatestVersion(data.version_number);
      setCoverage(
        (
          data as AnalyzeTenderResponse & {
            coverage_metadata?: Record<string, unknown>;
          }
        ).coverage_metadata ?? null,
      );
      setSnapshotCompleteness(null);
      setSelectedRequirement(null);
      setHistoryOffset(0);
      setHistoryReload((value) => value + 1);
      setElapsedTime(parseFloat(elapsed));
    } catch {
      setError(t("analysisFailed"));
    } finally {
      setIsLoading(false);
    }
  };

  const handleDownloadCompliancePdf = async () => {
    if (
      !resolvedTenderId ||
      isDownloadingPdf ||
      resultAnalysisLanguage === "ar"
    )
      return;

    setIsDownloadingPdf(true);
    setError(null);

    try {
      const exportQuery = new URLSearchParams();
      if (analysisId) exportQuery.set("analysis_id", analysisId);
      if (analysisVersion)
        exportQuery.set("version_number", String(analysisVersion));
      const query = exportQuery.size ? `?${exportQuery.toString()}` : "";
      const response = await api.get(
        `/tenders/${resolvedTenderId}/compliance/export/pdf${query}`,
        { responseType: "blob" },
      );
      const contentType =
        (typeof response.headers["content-type"] === "string"
          ? response.headers["content-type"]
          : undefined) || "application/pdf";
      const blob = new Blob([response.data], { type: contentType });
      const url = URL.createObjectURL(blob);
      const downloadName =
        filenameFromContentDisposition(
          (response.headers["content-disposition"] as string | undefined) ??
            null,
        ) || `compliance_report_${resolvedTenderId.slice(0, 8)}.pdf`;

      const link = document.createElement("a");
      link.href = url;
      link.download = downloadName;
      document.body.appendChild(link);
      link.click();
      link.remove();

      window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
    } catch (err: unknown) {
      setError(t(await complianceExportErrorKey(err)));
    } finally {
      setIsDownloadingPdf(false);
    }
  };

  // ── Derive UI state ──
  const hasAnalysis = requirements !== null && evaluation !== null;
  const hasText = rawText.length > 0;
  const canStartAnalysis = hasText && !complianceGuardMessage;
  const uiVerdict = deriveUiVerdict(hybridCompliance, evaluation);
  const complianceLabel = t(
    hasAnalysis ? uiVerdict.labelKey : "verdict.pending",
  );
  const documentIndex = useMemo(
    () => buildDocumentFilenameIndex(documents),
    [documents],
  );
  const selectedDocument = useMemo(
    () => resolveDocumentForRequirement(selectedRequirement, documentIndex),
    [selectedRequirement, documentIndex],
  );

  const selectVersion = async (versionNumber: number) => {
    if (
      !analysisId ||
      loadingVersion ||
      isLoading ||
      versionNumber === analysisVersion
    )
      return;
    setLoadingVersion(true);
    setError(null);
    try {
      const { data } = await api.get<{
        metadata: AnalysisVersionMetadata;
        result_snapshot: Record<string, unknown>;
        integrity: { snapshot_completeness: string };
      }>(
        `/tenders/${resolvedTenderId}/analyses/${analysisId}/versions/${versionNumber}`,
      );
      const result = data.result_snapshot;
      setRequirements((result.requirements as DynamicRequirements) ?? null);
      setEvaluation((result.evaluation as DynamicEvaluation) ?? null);
      setHybridCompliance(extractHybridCompliance(result));
      setContentHash(extractContentHash(result));
      setResultAnalysisLanguage(data.metadata.analysis_language);
      setAnalysisVersion(data.metadata.version_number);
      setAnalysisStatus(data.metadata.status.toLowerCase());
      setSnapshotCompleteness(data.integrity.snapshot_completeness);
      setCoverage(
        (result.coverage_metadata as Record<string, unknown>) ?? null,
      );
      setSelectedRequirement(null);
      setElapsedTime(null);
    } catch {
      setError(t("redesign.versionFailed"));
    } finally {
      setLoadingVersion(false);
    }
  };
  const closeContext = () => {
    setContextOpen(false);
    window.setTimeout(() => evidenceTrigger.current?.focus(), 0);
  };
  const chooseEvidence = (requirement: RequirementMatchDetail) => {
    evidenceTrigger.current = document.activeElement as HTMLElement;
    setSelectedRequirement(requirement);
    setContextOpen(true);
  };
  const partial = Boolean(
    coverage?.coverage_status && coverage.coverage_status !== "complete",
  );
  return (
    <div className="customer-page compliance-page">
      <ButtonLink href={`/dashboard/tenders/${tenderId}`} variant="ghost">
        <ArrowLeft aria-hidden className="rtl-mirror" />
        {t("back")}
      </ButtonLink>
      <PageHeader
        eyebrow={t("engineTitle")}
        title={tenderTitle || t("title")}
        description={
          isLoading
            ? t("analyzingSubtitle")
            : analysisStatus === "failed"
              ? t("analysisFailed")
              : hasAnalysis
                ? t("completeSubtitle")
                : t("readySubtitle")
        }
      />
      <Surface className="compliance-toolbar">
        <Select
          label={t("analysisLanguage")}
          value={selectedAnalysisLanguage}
          disabled={isLoading}
          onChange={(event) =>
            setSelectedAnalysisLanguage(
              event.target.value as CustomerAnalysisLanguage,
            )
          }
        >
          {CUSTOMER_ANALYSIS_LANGUAGES.map((language) => (
            <option key={language.code} value={language.code}>
              {language.nativeLabel}
            </option>
          ))}
        </Select>
        <Button
          onClick={handleAnalyzeTender}
          loading={isLoading}
          disabled={!canStartAnalysis || isLoading || loadingVersion}
        >
          <Sparkles aria-hidden />
          {hasAnalysis ? t("analyzeAgain") : t("start")}
        </Button>
        {analysisId && analysisVersion && (
          <Button
            variant="secondary"
            onClick={handleDownloadCompliancePdf}
            loading={isDownloadingPdf}
            disabled={
              isDownloadingPdf ||
              loadingVersion ||
              resultAnalysisLanguage === "ar"
            }
          >
            <Download aria-hidden />
            {t("downloadPdf")}
          </Button>
        )}
        <Button
          variant="secondary"
          onClick={() => {
            evidenceTrigger.current = document.activeElement as HTMLElement;
            setSelectedRequirement(null);
            setContextOpen(true);
          }}
        >
          <FileSearch aria-hidden />
          {t("tenderDocument")}
        </Button>
      </Surface>
      {analysisStatus === "failed" && (
        <Alert tone="danger" title={t("analysisFailed")} />
      )}
      {resultAnalysisLanguage === "ar" && (
        <Alert tone="warning" title={t("redesign.arabicPdfGate")} />
      )}
      {error && (
        <Alert
          tone="danger"
          title={error}
          onDismiss={() => setError(null)}
          dismissLabel={t("dismissError")}
        />
      )}
      {complianceGuardMessage && (
        <Alert tone="warning" title={complianceGuardMessage} />
      )}
      {isLoading && (
        <Alert title={t("running")}>{t("redesign.runningHelp")}</Alert>
      )}
      {partial && (
        <Alert tone="warning" title={t("redesign.partialCoverage")}>
          {typeof coverage?.coverage_status === "string" ? (
            <BidiText>{coverage.coverage_status}</BidiText>
          ) : null}
        </Alert>
      )}
      {snapshotCompleteness && snapshotCompleteness !== "COMPLETE" && (
        <Alert tone="warning" title={t("redesign.incompleteSnapshot")}>
          <TechnicalText>{snapshotCompleteness}</TechnicalText>
        </Alert>
      )}
      <Surface className="compliance-history">
        <Select
          label={t("versionHistory")}
          value={analysisVersion ?? ""}
          disabled={loadingVersion || isLoading || !analysisHistory.length}
          onChange={(event) => void selectVersion(Number(event.target.value))}
        >
          {!analysisHistory.some(
            (version) => version.version_number === analysisVersion,
          ) && (
            <option value={analysisVersion ?? ""}>
              {analysisVersion
                ? t("version", { version: analysisVersion })
                : t("notRecorded")}
            </option>
          )}
          {analysisHistory.map((version) => (
            <option key={version.version_number} value={version.version_number}>
              {t("version", { version: version.version_number })} ·{" "}
              {version.analysis_language
                ? analysisLanguageLabel(version.analysis_language)
                : t("notRecorded")}{" "}
              · {formatDate(version.created_at, locale)} · {version.status}
            </option>
          ))}
        </Select>
        <Pagination
          label={t("versionHistory")}
          previousLabel={tCommon("actions.previous")}
          nextLabel={tCommon("actions.next")}
          hasPrevious={historyOffset > 0}
          hasNext={historyHasMore}
          busy={loadingVersion || isLoading}
          onPrevious={() => setHistoryOffset(Math.max(0, historyOffset - 25))}
          onNext={() => setHistoryOffset(historyOffset + 25)}
        />
        {new Set(
          analysisHistory
            .map((version) => version.analysis_language)
            .filter(Boolean),
        ).size > 1 && <p className="ds-muted">{t("crossLanguageNotice")}</p>}
        {historyError && (
          <Alert
            tone="danger"
            title={t("redesign.historyFailed")}
            action={
              <Button onClick={() => setHistoryReload((value) => value + 1)}>
                {t("redesign.retry")}
              </Button>
            }
          />
        )}
      </Surface>
      {(loadingResult && isLoadingText) || loadingVersion ? (
        <PageSkeleton label={t("redesign.loadingVersion")} />
      ) : hasAnalysis ? (
        <div className="compliance-reading-layout">
          <div className="compliance-result">
            <Surface className="compliance-section">
              <SectionHeader
                title={t("redesign.assessment")}
                action={
                  <StatusBadge tone={verdictTone(uiVerdict.tone)}>
                    {complianceLabel}
                  </StatusBadge>
                }
              />
              <p
                dir={analysisContentDirection(resultAnalysisLanguage)}
                className="compliance-narrative"
              >
                {deriveStatusMessage(hybridCompliance, evaluation) ??
                  t("manualOnly")}
              </p>
              <div className="ds-row ds-muted">
                <span>
                  {t("resultLanguage")}:{" "}
                  {resultAnalysisLanguage
                    ? analysisLanguageLabel(resultAnalysisLanguage)
                    : t("notRecorded")}
                </span>
                {analysisVersion && (
                  <span>{t("version", { version: analysisVersion })}</span>
                )}
                {elapsedTime !== null && (
                  <span>{t("elapsedSeconds", { seconds: elapsedTime })}</span>
                )}
              </div>
            </Surface>
            {hybridCompliance ? (
              <>
                <Surface className="compliance-metrics">
                  {(
                    [
                      ["satisfied", hybridCompliance.satisfied_count],
                      ["failed", hybridCompliance.failed_count],
                      ["manual", hybridCompliance.manual_review_count],
                      [
                        "recorded",
                        hybridCompliance.recorded_obligations_count ??
                          hybridCompliance.skipped_optional_count,
                      ],
                    ] as const
                  ).map(([label, value]) => (
                    <Metric key={label} label={t(label)} value={value} />
                  ))}
                </Surface>
                {(
                  [
                    [
                      t("dealbreakerFailures", {
                        count: hybridCompliance.failed_dealbreakers.length,
                      }),
                      hybridCompliance.failed_dealbreakers,
                    ],
                    [
                      t("manualReviewRequired", {
                        count: hybridCompliance.manual_reviews_required.length,
                      }),
                      hybridCompliance.manual_reviews_required,
                    ],
                    [
                      t("satisfiedRequirements"),
                      hybridCompliance.satisfied_requirements,
                    ],
                    [
                      t("recordedObligations"),
                      hybridCompliance.recorded_obligations ?? [],
                    ],
                  ] as [string, RequirementMatchDetail[]][]
                )
                  .filter(([, items]) => items.length > 0)
                  .map(([label, items]) => (
                    <section className="compliance-group" key={label}>
                      <SectionHeader title={label} />
                      {items.map((detail) => (
                        <RequirementCard
                          key={getRequirementKey(detail)}
                          detail={detail}
                          analysisLanguage={resultAnalysisLanguage}
                          onEvidence={() => chooseEvidence(detail)}
                          tenderId={resolvedTenderId}
                          analysisId={analysisId}
                          canMutate={
                            analysisVersion === latestVersion && !isLoading
                          }
                          isOverridden={acceptedNodeIds.includes(
                            (
                              detail.taxonomy_node_id ??
                              `synth_${hashSnippet(detail.raw_text_snippet)}`
                            ).toLowerCase(),
                          )}
                          onOverride={(seal, nodeIds) => {
                            setOverrideSeal(seal);
                            setAcceptedNodeIds((prev) => [
                              ...new Set([
                                ...prev,
                                ...nodeIds.map((id) => id.toLowerCase()),
                              ]),
                            ]);
                          }}
                        />
                      ))}
                    </section>
                  ))}
              </>
            ) : (
              <Surface className="compliance-section">
                <EmptyState
                  title={t("auditUnavailable")}
                  description={t("auditUnavailableHelp")}
                />
              </Surface>
            )}
          </div>
          <aside
            className="compliance-context"
            aria-label={t("sourceEvidence")}
          >
            <Surface className="compliance-section">
              <SectionHeader title={t("sourceEvidence")} />
              <p className="ds-muted">{t("redesign.evidenceHelp")}</p>
              <Button
                variant="secondary"
                onClick={() => {
                  evidenceTrigger.current =
                    document.activeElement as HTMLElement;
                  setSelectedRequirement(null);
                  setContextOpen(true);
                }}
              >
                {t("tenderDocument")}
              </Button>
            </Surface>
            <Surface className="compliance-section">
              <SectionHeader title={t("versionHistory")} />
              <p>
                <TechnicalText>{analysisId}</TechnicalText>
              </p>
              {contentHash && (
                <>
                  <p className="ds-muted">{t("contentSeal")}</p>
                  <TechnicalText>{contentHash}</TechnicalText>
                </>
              )}
              {overrideSeal && (
                <>
                  <p className="ds-muted">{t("overrideSeal")}</p>
                  <TechnicalText>{overrideSeal}</TechnicalText>
                  <StatusBadge tone="warning">
                    {t("overrideCount", { count: acceptedNodeIds.length })}
                  </StatusBadge>
                </>
              )}
            </Surface>
          </aside>
        </div>
      ) : loadingResult ? (
        <PageSkeleton label={t("redesign.loadingVersion")} />
      ) : (
        <Surface>
          <EmptyState
            icon={<FileSearch aria-hidden />}
            title={t("ready")}
            description={t("introHelp")}
          />
          {!hasText && (
            <p className="compliance-section ds-muted">{t("noTextGuard")}</p>
          )}
        </Surface>
      )}
      <Drawer
        open={contextOpen}
        onClose={closeContext}
        title={selectedRequirement ? t("sourceEvidence") : t("tenderDocument")}
        closeLabel={t("backToDocument")}
      >
        {selectedRequirement ? (
          <EvidenceDocumentPane
            requirement={selectedRequirement}
            matchedDocument={selectedDocument}
            isLoadingDocuments={isLoadingDocuments}
            documentFetchError={documentFetchError}
            onClearSelection={() => setSelectedRequirement(null)}
          />
        ) : isLoadingText ? (
          <PageSkeleton label={t("loadingDocument")} />
        ) : hasText ? (
          <DocumentViewer title={tenderTitle} content={rawText} foundation />
        ) : (
          <EmptyState title={t("noTextTitle")} description={t("noTextHelp")} />
        )}
      </Drawer>
    </div>
  );
}

function verdictTone(tone: VerdictTone): Tone {
  return tone === "review" ? "warning" : tone === "pending" ? "neutral" : tone;
}

function RequirementCard({
  detail,
  analysisLanguage,
  onEvidence,
  tenderId,
  analysisId,
  canMutate,
  isOverridden,
  onOverride,
}: {
  detail: RequirementMatchDetail;
  analysisLanguage: AnalysisLanguage | null;
  onEvidence: () => void;
  tenderId: string;
  analysisId: string | null;
  canMutate: boolean;
  isOverridden: boolean;
  onOverride: (seal: string | null, ids: string[]) => void;
}) {
  const t = useTranslations("compliance");
  const [open, setOpen] = useState(false);
  const fatal = detail.verdict === "FAILED" && detail.is_dealbreaker;
  const quote = detail.exact_quote || detail.raw_text_snippet;
  return (
    <Surface className="compliance-requirement">
      <div className="ds-row">
        <StatusBadge
          tone={
            detail.verdict === "SATISFIED"
              ? "success"
              : detail.verdict === "FAILED"
                ? "danger"
                : "warning"
          }
        >
          {t(
            detail.verdict === "SATISFIED"
              ? "verdictLabels.satisfied"
              : detail.verdict === "FAILED"
                ? "verdictLabels.failed"
                : "verdictLabels.manualReview",
          )}
        </StatusBadge>
        {fatal && <StatusBadge tone="danger">{t("fatal")}</StatusBadge>}
        {isOverridden && (
          <StatusBadge tone="warning">{t("overridden")}</StatusBadge>
        )}
      </div>
      {detail.parent_section_header && (
        <p className="ds-muted">
          <BidiText>{detail.parent_section_header}</BidiText>
        </p>
      )}
      <div className="ds-row ds-muted">
        <BidiText>{detail.source_filename || t("sourceDocument")}</BidiText>
        <span>
          {detail.source_page
            ? t("page", { page: detail.source_page })
            : t("documentLevel")}
        </span>
        <TechnicalText>
          {detail.category || detail.requirement_type}
        </TechnicalText>
      </div>
      <h3
        dir={
          detail.headline ? analysisContentDirection(analysisLanguage) : "auto"
        }
      >
        {detail.headline || detail.raw_text_snippet}
      </h3>
      {detail.reason && (
        <>
          <p className="ds-muted">{t("redesign.rationale")}</p>
          <p dir={analysisContentDirection(analysisLanguage)}>
            {detail.reason}
          </p>
        </>
      )}
      <blockquote className="compliance-quote">
        <p className="ds-muted">{t("evidenceQuote")}</p>
        <p dir="auto">{quote}</p>
      </blockquote>
      {detail.matched_credential && (
        <p>
          <span className="ds-muted">{t("redesign.recordedCredential")}: </span>
          <BidiText>{detail.matched_credential}</BidiText>
        </p>
      )}
      <div className="ds-row">
        <Button variant="secondary" onClick={onEvidence}>
          {t("sourceEvidence")}
        </Button>
        {fatal && canMutate && analysisId && !isOverridden && (
          <Button variant="ghost" onClick={() => setOpen(true)}>
            {t("overrideFlag")}
          </Button>
        )}
      </div>
      {open && analysisId && (
        <OverrideChallengeModal
          tenderId={tenderId}
          analysisId={analysisId}
          nodeId={
            detail.taxonomy_node_id ??
            `synth_${hashSnippet(detail.raw_text_snippet)}`
          }
          requirementSnippet={detail.raw_text_snippet}
          onClose={() => setOpen(false)}
          onOverrideComplete={(seal, ids) => {
            onOverride(seal, ids);
            setOpen(false);
          }}
        />
      )}
    </Surface>
  );
}

function EvidenceDocumentPane({
  requirement,
  matchedDocument,
  isLoadingDocuments,
  documentFetchError,
  onClearSelection,
}: {
  requirement: RequirementMatchDetail;
  matchedDocument: TenderDocument | null;
  isLoadingDocuments: boolean;
  documentFetchError: string | null;
  onClearSelection: () => void;
}) {
  const t = useTranslations("compliance");
  const sourcePage = requirement.source_page;
  const quote = requirement.exact_quote || requirement.raw_text_snippet;
  const sourceFilename = requirement.source_filename || t("sourceDocument");
  const matchedName = matchedDocument
    ? getDocumentDisplayName(matchedDocument)
    : sourceFilename;
  const documentUrl = matchedDocument
    ? `/document-preview/${matchedDocument.id}`
    : null;
  const iframeSrc = documentUrl
    ? `${documentUrl}${sourcePage ? `#page=${sourcePage}` : ""}`
    : null;
  const extension = getDocumentExtension(matchedDocument);
  const isPdf = isPdfDocument(matchedDocument);
  const isDocx = extension === "docx" || extension === "doc";
  const isArchive = isArchiveDocument(matchedDocument);
  const isArchiveInner = isArchiveInnerSource(requirement, matchedDocument);
  const pageLabel =
    isDocx || !sourcePage
      ? t("documentLevel")
      : t("page", { page: sourcePage });

  return (
    <div className="compliance-section">
      <SectionHeader
        title={<BidiText>{matchedName}</BidiText>}
        action={
          <Button variant="ghost" onClick={onClearSelection}>
            {t("backToDocument")}
          </Button>
        }
      />
      <div className="ds-row ds-muted">
        <BidiText>{sourceFilename}</BidiText>
        <span>{pageLabel}</span>
      </div>
      <blockquote className="compliance-quote">
        <p className="ds-muted">{t("evidenceQuote")}</p>
        <p dir="auto">{quote}</p>
      </blockquote>
      {isPdf && iframeSrc ? (
        <>
          <p className="ds-muted">{t("pdfBestEffort")}</p>
          <iframe
            key={iframeSrc}
            title={t("evidenceFrame", { name: matchedName })}
            src={iframeSrc}
            className="compliance-document-frame"
          />
        </>
      ) : (
        <EvidenceFallbackPanel
          matchedDocument={matchedDocument}
          documentUrl={documentUrl}
          sourceFilename={sourceFilename}
          pageLabel={pageLabel}
          isLoadingDocuments={isLoadingDocuments}
          documentFetchError={documentFetchError}
          isDocx={isDocx}
          isArchive={isArchive}
          isArchiveInner={isArchiveInner}
        />
      )}
    </div>
  );
}

function EvidenceFallbackPanel({
  matchedDocument,
  documentUrl,
  sourceFilename,
  pageLabel,
  isLoadingDocuments,
  documentFetchError,
  isDocx,
  isArchive,
  isArchiveInner,
}: {
  matchedDocument: TenderDocument | null;
  documentUrl: string | null;
  sourceFilename: string;
  pageLabel: string;
  isLoadingDocuments: boolean;
  documentFetchError: string | null;
  isDocx: boolean;
  isArchive: boolean;
  isArchiveInner: boolean;
}) {
  const t = useTranslations("compliance");
  const [openError, setOpenError] = useState<string | null>(null);
  const [isOpening, setIsOpening] = useState(false);
  let message = t("fallbackDefault");

  if (isLoadingDocuments) {
    message = t("fallbackResolving");
  } else if (documentFetchError) {
    message = documentFetchError;
  } else if (isArchiveInner) {
    message = t("fallbackArchiveInner");
  } else if (!matchedDocument) {
    message = t("fallbackUnmatched");
  } else if (isDocx) {
    message = t("fallbackDocx");
  } else if (isArchive) {
    message = t("fallbackArchive");
  }

  const handleOpenDocument = async () => {
    if (!documentUrl || isOpening) return;

    setIsOpening(true);
    setOpenError(null);

    try {
      const response = await fetch(documentUrl, { cache: "no-store" });
      if (!response.ok) {
        setOpenError(t(documentErrorKey(response)));
        return;
      }

      const blob = await response.blob();
      const blobUrl = URL.createObjectURL(blob);
      const contentType = response.headers.get("Content-Type") ?? "";
      const downloadName =
        filenameFromContentDisposition(
          response.headers.get("Content-Disposition"),
        ) ||
        (matchedDocument
          ? getDocumentDisplayName(matchedDocument)
          : sourceFilename);

      const link = document.createElement("a");
      link.href = blobUrl;

      if (contentType.includes("pdf")) {
        link.target = "_blank";
        link.rel = "noreferrer";
      } else {
        link.download = downloadName;
      }

      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(blobUrl), 30_000);
    } catch {
      setOpenError(t("documentOpenFailed"));
    } finally {
      setIsOpening(false);
    }
  };

  return (
    <div className="compliance-section">
      <Alert tone="warning" title={t("fallbackTitle")}>
        {message}
      </Alert>
      <dl className="readiness-facts">
        <div>
          <dt>{t("sourceFilename")}</dt>
          <dd>
            <BidiText>{sourceFilename}</BidiText>
          </dd>
        </div>
        <div>
          <dt>{t("sourcePosition")}</dt>
          <dd>{pageLabel}</dd>
        </div>
      </dl>
      {openError && <Alert tone="danger" title={openError} />}
      {documentUrl && (
        <Button
          variant="secondary"
          onClick={handleOpenDocument}
          loading={isOpening}
          disabled={isOpening}
        >
          {isOpening ? t("openingSource") : t("openSource")}
        </Button>
      )}
    </div>
  );
}

function OverrideChallengeModal({
  tenderId,
  analysisId,
  nodeId,
  requirementSnippet,
  onClose,
  onOverrideComplete,
}: {
  tenderId: string;
  analysisId: string;
  nodeId: string;
  requirementSnippet: string;
  onClose: () => void;
  onOverrideComplete: (seal: string | null, nodeIds: string[]) => void;
}) {
  const t = useTranslations("compliance");
  const [justification, setJustification] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isValid = justification.trim().length >= 10;

  const handleSubmit = async () => {
    if (!isValid || isSubmitting) return;

    setIsSubmitting(true);
    setError(null);

    try {
      const { data } = await api.post<OverrideResponse>(
        `/tenders/${tenderId}/override`,
        {
          node_id: nodeId,
          analysis_id: analysisId,
          justification: justification.trim(),
        },
      );
      onOverrideComplete(data.override_seal, data.overridden_node_ids);
    } catch {
      setError(t("overrideFailed"));
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Dialog
      open
      onClose={() => {
        if (!isSubmitting) onClose();
      }}
      title={t("overrideTitle")}
      description={t("overrideExplanation")}
      closeLabel={t("cancel")}
    >
      <form
        className="compliance-section"
        onSubmit={(event) => {
          event.preventDefault();
          void handleSubmit();
        }}
      >
        <p className="ds-muted">{t("requirementOverridden")}</p>
        <blockquote dir="auto" className="compliance-quote">
          {requirementSnippet}
        </blockquote>
        <Alert tone="warning" title={t("responsibilityTitle")}>
          {t("responsibilityHelp")}
        </Alert>
        <Textarea
          label={t("justification")}
          placeholder={t("justificationPlaceholder")}
          value={justification}
          onChange={(event) => setJustification(event.target.value)}
          disabled={isSubmitting}
          dir="auto"
          required
          minLength={10}
          count={t("minimumCharacters", { count: justification.trim().length })}
        />
        {error && <Alert tone="danger" title={error} />}
        <div className="ds-row">
          <Button variant="secondary" onClick={onClose} disabled={isSubmitting}>
            {t("cancel")}
          </Button>
          <Button
            type="submit"
            disabled={!isValid || isSubmitting}
            loading={isSubmitting}
          >
            {isSubmitting ? t("sealing") : t("seal")}
          </Button>
        </div>
        <p className="ds-muted">{t("sealNotice")}</p>
      </form>
    </Dialog>
  );
}
