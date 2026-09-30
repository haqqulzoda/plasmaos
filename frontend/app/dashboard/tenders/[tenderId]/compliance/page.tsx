"use client";

import { Pagination } from "@/components/ui/Navigation";
import {
  Badge,
  PageHeader,
  SectionHeader,
  Surface,
  StatusBadge,
  PageSkeleton,
  EmptyState,
  Skeleton,
  type Tone,
} from "@/components/ui/Display";
import { Button, ButtonLink } from "@/components/ui/Button";
import { SearchField, Select, Textarea } from "@/components/ui/Forms";
import { Dialog, Drawer } from "@/components/ui/Overlay";
import { Alert } from "@/components/ui/Feedback";
import { BidiText, TechnicalText } from "@/components/i18n/BidiText";
import { formatDate } from "@/i18n/formatters";
import { formatPublishedDeadline } from "@/lib/tenderTruth";
import { useTenderTruthLabels } from "@/lib/useTenderTruthLabels";
import type { CustomerSelectableLocale } from "@/i18n/locales";
import { useCollectionOffset } from "@/lib/useCollectionOffset";
import { useState, useEffect, use, useId, useMemo, useRef } from "react";
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
import {
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  Download,
  ExternalLink,
  FileSearch,
  FileText,
  Sparkles,
} from "lucide-react";

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

type RequirementStatusFilter = "ALL" | RequirementMatchDetail["verdict"];

type RequirementGroup = {
  key: "critical" | "review" | "matched" | "recorded";
  items: RequirementMatchDetail[];
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
  const truthLabels = useTenderTruthLabels();
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
  const [tender, setTender] = useState<Tender | null>(null);
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
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] =
    useState<RequirementStatusFilter>("ALL");
  const [categoryFilter, setCategoryFilter] = useState("ALL");
  const [documentFilter, setDocumentFilter] = useState("ALL");
  const [matchedExpanded, setMatchedExpanded] = useState(false);
  const [overrideRequirement, setOverrideRequirement] =
    useState<RequirementMatchDetail | null>(null);
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
        setTender(tenderData);
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
  const requirementGroups = useMemo<RequirementGroup[]>(
    () =>
      hybridCompliance
        ? [
            { key: "critical", items: hybridCompliance.failed_dealbreakers },
            { key: "review", items: hybridCompliance.manual_reviews_required },
            { key: "matched", items: hybridCompliance.satisfied_requirements },
            {
              key: "recorded",
              items: hybridCompliance.recorded_obligations ?? [],
            },
          ]
        : [],
    [hybridCompliance],
  );
  const allRequirements = useMemo(
    () => requirementGroups.flatMap((group) => group.items),
    [requirementGroups],
  );
  const requirementIndex = useMemo(
    () =>
      new Map(
        allRequirements.map((detail, index) => [
          getRequirementKey(detail),
          index + 1,
        ]),
      ),
    [allRequirements],
  );
  const categoryOptions = useMemo(
    () =>
      Array.from(
        new Set(allRequirements.map((item) => item.category).filter(Boolean)),
      ).sort((a, b) => a.localeCompare(b)),
    [allRequirements],
  );
  const documentOptions = useMemo(
    () =>
      Array.from(
        new Set(
          allRequirements.map((item) => item.source_filename).filter(Boolean),
        ),
      ).sort((a, b) => a.localeCompare(b)),
    [allRequirements],
  );
  const normalizedQuery = searchQuery.trim().toLocaleLowerCase();
  const filteredGroups = useMemo(
    () =>
      requirementGroups.map((group) => ({
        ...group,
        items: group.items.filter((detail) => {
          const matchesSearch =
            !normalizedQuery ||
            [
              detail.headline,
              detail.raw_text_snippet,
              detail.parent_section_header,
              detail.source_filename,
            ].some((value) =>
              (value ?? "").toLocaleLowerCase().includes(normalizedQuery),
            );
          return (
            matchesSearch &&
            (statusFilter === "ALL" || detail.verdict === statusFilter) &&
            (categoryFilter === "ALL" || detail.category === categoryFilter) &&
            (documentFilter === "ALL" ||
              detail.source_filename === documentFilter)
          );
        }),
      })),
    [
      categoryFilter,
      documentFilter,
      normalizedQuery,
      requirementGroups,
      statusFilter,
    ],
  );
  const filtersActive = Boolean(
    normalizedQuery ||
      statusFilter !== "ALL" ||
      categoryFilter !== "ALL" ||
      documentFilter !== "ALL",
  );
  const visibleRequirementCount = filteredGroups.reduce(
    (total, group) => total + group.items.length,
    0,
  );
  const defaultRequirement =
    filteredGroups.find((group) => group.items.length > 0)?.items[0] ??
    allRequirements[0] ??
    null;
  const activeRequirement = selectedRequirement ?? defaultRequirement;
  const selectedDocument = useMemo(
    () => resolveDocumentForRequirement(activeRequirement, documentIndex),
    [activeRequirement, documentIndex],
  );
  const readinessSupportedCount = useMemo(
    () =>
      (hybridCompliance?.satisfied_requirements ?? []).filter(
        (detail) =>
          detail.match_method === "VAULT_DETERMINISTIC" ||
          Boolean(
            detail.vault_evidence_id ||
              detail.vault_match_source ||
              detail.matched_credential,
          ),
      ).length,
    [hybridCompliance],
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
  const chooseRequirement = (requirement: RequirementMatchDetail) => {
    evidenceTrigger.current = document.activeElement as HTMLElement;
    setSelectedRequirement(requirement);
    if (window.matchMedia("(max-width: 1199px)").matches) {
      setContextOpen(true);
    }
  };
  const openEvidence = (requirement: RequirementMatchDetail) => {
    evidenceTrigger.current = document.activeElement as HTMLElement;
    setSelectedRequirement(requirement);
    setContextOpen(true);
  };
  const partial = Boolean(
    coverage?.coverage_status && coverage.coverage_status !== "complete",
  );
  const sourceSystemLabel = tender
    ? tender.source_system === "world_bank"
      ? t("workspace.sourceSystems.worldBank")
      : tender.source_system === "adb"
        ? t("workspace.sourceSystems.adb")
        : tender.source_system === "giz"
          ? t("workspace.sourceSystems.giz")
          : tender.source_system === "ebrd"
            ? t("workspace.sourceSystems.ebrd")
            : t("workspace.sourceSystems.uzex")
    : null;
  const currentCanMutate =
    analysisVersion === latestVersion && !isLoading && Boolean(analysisId);
  const activeKey = activeRequirement
    ? getRequirementKey(activeRequirement)
    : null;
  const activeIsOverridden = activeRequirement
    ? acceptedNodeIds.includes(
        (
          activeRequirement.taxonomy_node_id ??
          `synth_${hashSnippet(activeRequirement.raw_text_snippet)}`
        ).toLowerCase(),
      )
    : false;
  const resetFilters = () => {
    setSearchQuery("");
    setStatusFilter("ALL");
    setCategoryFilter("ALL");
    setDocumentFilter("ALL");
  };
  return (
    <div className="customer-page compliance-page">
      <ButtonLink
        href={`/dashboard/tenders/${tenderId}`}
        variant="ghost"
        className="compliance-back-link"
      >
        <ArrowLeft aria-hidden className="rtl-mirror" />
        {t("back")}
      </ButtonLink>
      <PageHeader
        eyebrow={t("engineTitle")}
        title={tenderTitle || t("title")}
        status={
          <Badge tone="accent">
            <span title={t("workspace.betaHelp")}>{t("workspace.beta")}</span>
          </Badge>
        }
        description={t("workspace.betaHelp")}
        metadata={
          tender ? (
            <>
              <TechnicalText>{tender.external_id}</TechnicalText>
              {sourceSystemLabel && <span>{sourceSystemLabel}</span>}
              {tender.deadline && (
                <span>
                  {t("workspace.closes", {
                    date: formatPublishedDeadline(tender, locale, truthLabels),
                  })}
                </span>
              )}
            </>
          ) : undefined
        }
        secondaryAction={
          tender?.source_url ? (
            <ButtonLink
              href={tender.source_url}
              target="_blank"
              rel="noreferrer"
              variant="secondary"
            >
              {t("workspace.openOriginalSource")}
              <ExternalLink aria-hidden />
            </ButtonLink>
          ) : undefined
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
        <ComplianceWorkspaceSkeleton label={t("redesign.loadingVersion")} />
      ) : hasAnalysis ? (
        <>
          <Surface className="compliance-summary compliance-section">
            <div className="compliance-summary-state">
              <SectionHeader
                title={complianceLabel}
                action={
                  <StatusBadge tone={verdictTone(uiVerdict.tone)}>
                    {complianceLabel}
                  </StatusBadge>
                }
              />
              <p
                dir={analysisContentDirection(resultAnalysisLanguage)}
                className="compliance-narrative ds-muted"
              >
                {deriveStatusMessage(hybridCompliance, evaluation) ??
                  t("manualOnly")}
              </p>
              <div className="compliance-summary-meta ds-muted">
                <span>
                  {t("resultLanguage")}: {" "}
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
            </div>
            <SummaryMetric
              value={hybridCompliance?.total_requirements ?? 0}
              label={t("workspace.requirementsReviewed")}
            />
            <SummaryMetric
              value={hybridCompliance?.failed_dealbreakers.length ?? 0}
              label={t("workspace.criticalGaps")}
              tone="danger"
            />
            <SummaryMetric
              value={readinessSupportedCount}
              label={t("workspace.readinessSupported")}
              tone="success"
            />
            <SummaryMetric
              value={documentOptions.length}
              label={t("workspace.referencedDocuments")}
            />
          </Surface>
          <Surface className="compliance-review-controls">
            <div className="compliance-filters">
              <SearchField
                label={t("workspace.searchLabel")}
                clearLabel={t("workspace.clearSearch")}
                placeholder={t("workspace.searchPlaceholder")}
                value={searchQuery}
                onValueChange={setSearchQuery}
              />
              <Select
                label={t("workspace.statusFilter")}
                value={statusFilter}
                onChange={(event) =>
                  setStatusFilter(
                    event.target.value as RequirementStatusFilter,
                  )
                }
              >
                <option value="ALL">{t("workspace.allStatuses")}</option>
                <option value="FAILED">{t("verdictLabels.failed")}</option>
                <option value="NEEDS_MANUAL_REVIEW">
                  {t("verdictLabels.manualReview")}
                </option>
                <option value="SATISFIED">
                  {t("verdictLabels.satisfied")}
                </option>
              </Select>
              <Select
                label={t("workspace.categoryFilter")}
                value={categoryFilter}
                onChange={(event) => setCategoryFilter(event.target.value)}
              >
                <option value="ALL">{t("workspace.allCategories")}</option>
                {categoryOptions.map((category) => (
                  <option key={category} value={category}>
                    {category}
                  </option>
                ))}
              </Select>
              <Select
                label={t("workspace.documentFilter")}
                value={documentFilter}
                onChange={(event) => setDocumentFilter(event.target.value)}
              >
                <option value="ALL">{t("workspace.allDocuments")}</option>
                {documentOptions.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </Select>
              <Button
                variant="ghost"
                onClick={resetFilters}
                disabled={!filtersActive}
              >
                {t("workspace.reset")}
              </Button>
            </div>
          </Surface>
          <div className="compliance-reading-layout">
          <div className="compliance-result">
            {hybridCompliance ? (
              <>
                <div className="compliance-result-heading">
                  <div>
                    <span className="ds-eyebrow">
                      {t("workspace.reviewWorkspace")}
                    </span>
                    <h2>{t("workspace.requirements")}</h2>
                  </div>
                  <span className="ds-muted">
                    {t("workspace.showingCount", {
                      visible: visibleRequirementCount,
                      total: allRequirements.length,
                    })}
                  </span>
                </div>
                {visibleRequirementCount > 0 ? (
                  filteredGroups
                    .filter((group) => group.items.length > 0)
                    .map((group) => (
                      <RequirementGroupSection
                        key={group.key}
                        group={group}
                        totalCount={
                          requirementGroups.find(
                            (candidate) => candidate.key === group.key,
                          )?.items.length ?? 0
                        }
                        indexByKey={requirementIndex}
                        activeKey={activeKey}
                        overriddenNodeIds={acceptedNodeIds}
                        analysisLanguage={resultAnalysisLanguage}
                        collapsed={
                          group.key === "matched" &&
                          !matchedExpanded &&
                          !filtersActive
                        }
                        onToggle={() =>
                          setMatchedExpanded((expanded) => !expanded)
                        }
                        onSelect={chooseRequirement}
                        onOpen={openEvidence}
                      />
                    ))
                ) : (
                  <Surface className="compliance-section">
                    <EmptyState
                      title={t("workspace.noResults")}
                      description={t("workspace.noResultsHelp")}
                      action={
                        <Button variant="secondary" onClick={resetFilters}>
                          {t("workspace.reset")}
                        </Button>
                      }
                    />
                  </Surface>
                )}
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
            aria-label={t("workspace.requirementDetails")}
          >
            {activeRequirement ? (
              <EvidenceInspector
                requirement={activeRequirement}
                requirementNumber={
                  requirementIndex.get(getRequirementKey(activeRequirement)) ?? 1
                }
                analysisLanguage={resultAnalysisLanguage}
                matchedDocument={selectedDocument}
                isLoadingDocuments={isLoadingDocuments}
                documentFetchError={documentFetchError}
                canMutate={currentCanMutate}
                isOverridden={activeIsOverridden}
                onOverride={() => setOverrideRequirement(activeRequirement)}
              />
            ) : (
              <Surface className="compliance-section">
                <EmptyState
                  title={t("workspace.selectRequirement")}
                  description={t("workspace.selectRequirementHelp")}
                />
              </Surface>
            )}
          </aside>
          </div>
          {(contentHash || overrideSeal) && (
            <details className="compliance-audit-details">
              <summary>{t("workspace.auditDetails")}</summary>
              <div className="compliance-audit-grid">
                {analysisId && (
                  <div>
                    <span className="ds-muted">{t("workspace.analysisId")}</span>
                    <TechnicalText>{analysisId}</TechnicalText>
                  </div>
                )}
                {contentHash && (
                  <div>
                    <span className="ds-muted">{t("contentSeal")}</span>
                    <TechnicalText>{contentHash}</TechnicalText>
                  </div>
                )}
                {overrideSeal && (
                  <div>
                    <span className="ds-muted">{t("overrideSeal")}</span>
                    <TechnicalText>{overrideSeal}</TechnicalText>
                    <StatusBadge tone="warning">
                      {t("overrideCount", { count: acceptedNodeIds.length })}
                    </StatusBadge>
                  </div>
                )}
              </div>
            </details>
          )}
        </>
      ) : loadingResult ? (
        <ComplianceWorkspaceSkeleton label={t("redesign.loadingVersion")} />
      ) : (
        <Surface>
          <EmptyState
            icon={<FileSearch aria-hidden />}
            title={t("ready")}
            description={t("introHelp")}
            action={
              <Button
                onClick={handleAnalyzeTender}
                loading={isLoading}
                disabled={!canStartAnalysis || isLoading}
              >
                <Sparkles aria-hidden />
                {t("start")}
              </Button>
            }
          />
          {!hasText && (
            <p className="compliance-section ds-muted">{t("noTextGuard")}</p>
          )}
        </Surface>
      )}
      <Drawer
        open={contextOpen}
        onClose={closeContext}
        title={
          selectedRequirement
            ? t("workspace.requirementDetails")
            : t("tenderDocument")
        }
        closeLabel={t("workspace.closeInspector")}
      >
        {selectedRequirement ? (
          <EvidenceInspector
            requirement={selectedRequirement}
            requirementNumber={
              requirementIndex.get(getRequirementKey(selectedRequirement)) ?? 1
            }
            analysisLanguage={resultAnalysisLanguage}
            matchedDocument={resolveDocumentForRequirement(
              selectedRequirement,
              documentIndex,
            )}
            isLoadingDocuments={isLoadingDocuments}
            documentFetchError={documentFetchError}
            canMutate={currentCanMutate}
            isOverridden={acceptedNodeIds.includes(
              (
                selectedRequirement.taxonomy_node_id ??
                `synth_${hashSnippet(selectedRequirement.raw_text_snippet)}`
              ).toLowerCase(),
            )}
            onOverride={() => setOverrideRequirement(selectedRequirement)}
          />
        ) : isLoadingText ? (
          <PageSkeleton label={t("loadingDocument")} />
        ) : hasText ? (
          <DocumentViewer title={tenderTitle} content={rawText} foundation />
        ) : (
          <EmptyState title={t("noTextTitle")} description={t("noTextHelp")} />
        )}
      </Drawer>
      {overrideRequirement && analysisId && (
        <OverrideChallengeModal
          tenderId={resolvedTenderId}
          analysisId={analysisId}
          nodeId={
            overrideRequirement.taxonomy_node_id ??
            `synth_${hashSnippet(overrideRequirement.raw_text_snippet)}`
          }
          requirementSnippet={overrideRequirement.raw_text_snippet}
          onClose={() => setOverrideRequirement(null)}
          onOverrideComplete={(seal, nodeIds) => {
            setOverrideSeal(seal);
            setAcceptedNodeIds((previous) => [
              ...new Set([
                ...previous,
                ...nodeIds.map((id) => id.toLowerCase()),
              ]),
            ]);
            setOverrideRequirement(null);
          }}
        />
      )}
    </div>
  );
}

function SummaryMetric({
  value,
  label,
  tone = "neutral",
}: {
  value: number;
  label: string;
  tone?: "neutral" | "danger" | "success";
}) {
  return (
    <dl className={`compliance-summary-metric is-${tone}`}>
      <dt>{label}</dt>
      <dd className="ds-numeric">{value}</dd>
    </dl>
  );
}

function ComplianceWorkspaceSkeleton({ label }: { label: string }) {
  return (
    <div className="compliance-workspace-skeleton" role="status" aria-label={label}>
      <span className="sr-only">{label}</span>
      <Surface className="compliance-summary">
        {[0, 1, 2, 3, 4].map((item) => (
          <div className="ds-stack" key={item}>
            <Skeleton />
            <Skeleton />
          </div>
        ))}
      </Surface>
      <div className="compliance-reading-layout">
        <Surface className="compliance-section">
          {[0, 1, 2, 3].map((item) => (
            <Skeleton key={item} />
          ))}
        </Surface>
        <Surface className="compliance-section">
          {[0, 1, 2].map((item) => (
            <Skeleton key={item} />
          ))}
        </Surface>
      </div>
    </div>
  );
}

function RequirementGroupSection({
  group,
  totalCount,
  indexByKey,
  activeKey,
  overriddenNodeIds,
  analysisLanguage,
  collapsed,
  onToggle,
  onSelect,
  onOpen,
}: {
  group: RequirementGroup;
  totalCount: number;
  indexByKey: Map<string, number>;
  activeKey: string | null;
  overriddenNodeIds: string[];
  analysisLanguage: AnalysisLanguage | null;
  collapsed: boolean;
  onToggle: () => void;
  onSelect: (requirement: RequirementMatchDetail) => void;
  onOpen: (requirement: RequirementMatchDetail) => void;
}) {
  const t = useTranslations("compliance");
  const title = t(`workspace.groups.${group.key}.title`);
  const description = t(`workspace.groups.${group.key}.description`);
  const GroupIcon =
    group.key === "critical"
      ? AlertCircle
      : group.key === "matched"
        ? CheckCircle2
        : CircleHelp;
  return (
    <section
      className={`compliance-group compliance-section is-${group.key}`}
      aria-labelledby={`compliance-group-${group.key}`}
    >
      <SectionHeader
        title={title}
        titleId={`compliance-group-${group.key}`}
        description={description}
        icon={<GroupIcon aria-hidden />}
        action={<Badge>{group.items.length}</Badge>}
      />
      {!collapsed && (
        <div className="compliance-requirement-list">
          {group.items.map((detail) => {
            const key = getRequirementKey(detail);
            const nodeId = (
              detail.taxonomy_node_id ??
              `synth_${hashSnippet(detail.raw_text_snippet)}`
            ).toLowerCase();
            return (
              <RequirementRow
                key={key}
                detail={detail}
                number={indexByKey.get(key) ?? 1}
                analysisLanguage={analysisLanguage}
                selected={key === activeKey}
                isOverridden={overriddenNodeIds.includes(nodeId)}
                onSelect={() => onSelect(detail)}
                onOpen={() => onOpen(detail)}
              />
            );
          })}
        </div>
      )}
      {group.key === "matched" && (
        <Button variant="ghost" size="sm" onClick={onToggle}>
          {collapsed ? <ChevronDown aria-hidden /> : <ChevronRight aria-hidden className="rtl-mirror" />}
          {collapsed
            ? t("workspace.showMatched", { count: totalCount })
            : t("workspace.hideMatched")}
        </Button>
      )}
    </section>
  );
}

function RequirementRow({
  detail,
  number,
  analysisLanguage,
  selected,
  isOverridden,
  onSelect,
  onOpen,
}: {
  detail: RequirementMatchDetail;
  number: number;
  analysisLanguage: AnalysisLanguage | null;
  selected: boolean;
  isOverridden: boolean;
  onSelect: () => void;
  onOpen: () => void;
}) {
  const t = useTranslations("compliance");
  const title = detail.headline || detail.raw_text_snippet;
  const description =
    detail.raw_text_snippet !== title ? detail.raw_text_snippet : null;
  return (
    <div
      className={`compliance-requirement${selected ? " is-selected" : ""}`}
    >
      <button
        type="button"
        className="compliance-row-select"
        aria-pressed={selected}
        onClick={onSelect}
      >
        <span className="compliance-row-number ds-numeric">{number}</span>
        <span className="compliance-row-copy">
          <h3 dir={analysisContentDirection(analysisLanguage)}>{title}</h3>
          {description && <span dir="auto">{description}</span>}
          <span className="compliance-row-source ds-muted">
            {detail.parent_section_header && (
              <BidiText>{detail.parent_section_header}</BidiText>
            )}
            {detail.source_filename && (
              <BidiText>{detail.source_filename}</BidiText>
            )}
            {detail.source_page > 0 && (
              <span>{t("page", { page: detail.source_page })}</span>
            )}
          </span>
        </span>
        <RequirementStatus detail={detail} isOverridden={isOverridden} />
      </button>
      <Button
        variant="icon"
        className="compliance-row-open"
        aria-label={t("sourceEvidence")}
        onClick={onOpen}
      >
        <ChevronRight aria-hidden className="rtl-mirror" />
      </Button>
    </div>
  );
}

function RequirementStatus({
  detail,
  isOverridden = false,
}: {
  detail: RequirementMatchDetail;
  isOverridden?: boolean;
}) {
  const t = useTranslations("compliance");
  const tone =
    detail.verdict === "SATISFIED"
      ? "success"
      : detail.verdict === "FAILED"
        ? "danger"
        : "warning";
  const Icon =
    detail.verdict === "SATISFIED"
      ? CheckCircle2
      : detail.verdict === "FAILED"
        ? AlertCircle
        : CircleHelp;
  const label = t(
    detail.verdict === "SATISFIED"
      ? "verdictLabels.satisfied"
      : detail.verdict === "FAILED"
        ? "verdictLabels.failed"
        : "verdictLabels.manualReview",
  );
  return (
    <span className={`compliance-row-status is-${tone}`}>
      <Icon aria-hidden />
      <span>{label}</span>
      {isOverridden && <Badge tone="warning">{t("overridden")}</Badge>}
    </span>
  );
}

function EvidenceInspector({
  requirement,
  requirementNumber,
  analysisLanguage,
  matchedDocument,
  isLoadingDocuments,
  documentFetchError,
  canMutate,
  isOverridden,
  onOverride,
}: {
  requirement: RequirementMatchDetail;
  requirementNumber: number;
  analysisLanguage: AnalysisLanguage | null;
  matchedDocument: TenderDocument | null;
  isLoadingDocuments: boolean;
  documentFetchError: string | null;
  canMutate: boolean;
  isOverridden: boolean;
  onOverride: () => void;
}) {
  const t = useTranslations("compliance");
  const sourceTitleId = useId();
  const analysisTitleId = useId();
  const sourcePage = requirement.source_page;
  const quote = requirement.exact_quote || requirement.raw_text_snippet;
  const sourceFilename = requirement.source_filename || t("sourceDocument");
  const matchedName = matchedDocument
    ? getDocumentDisplayName(matchedDocument)
    : sourceFilename;
  const documentUrl = matchedDocument
    ? `/document-preview/${matchedDocument.id}${
        isPdfDocument(matchedDocument) && sourcePage > 0
          ? `#page=${sourcePage}`
          : ""
      }`
    : null;
  const readinessContext =
    requirement.matched_credential ||
    requirement.vault_missing_reason ||
    requirement.vault_match_source;
  return (
    <Surface className="compliance-inspector compliance-section">
      <header className="compliance-inspector-header">
        <div>
          <span className="ds-eyebrow">
            {t("workspace.requirementNumber", { number: requirementNumber })}
          </span>
          <h2 dir={analysisContentDirection(analysisLanguage)}>
            {requirement.headline || requirement.raw_text_snippet}
          </h2>
        </div>
        <RequirementStatus
          detail={requirement}
          isOverridden={isOverridden}
        />
      </header>

      <div className="compliance-inspector-meta">
        {requirement.category && (
          <div>
            <span className="ds-muted">{t("workspace.category")}</span>
            <TechnicalText>{requirement.category}</TechnicalText>
          </div>
        )}
        {requirement.taxonomy_node_id && (
          <div>
            <span className="ds-muted">{t("workspace.requirementId")}</span>
            <TechnicalText>{requirement.taxonomy_node_id}</TechnicalText>
          </div>
        )}
      </div>

      <section className="compliance-evidence-block" aria-labelledby={sourceTitleId}>
        <span className="ds-eyebrow" id={sourceTitleId}>
          {t("workspace.sourceEvidenceLabel")}
        </span>
        <div className="compliance-source-document">
          <FileText aria-hidden />
          <div>
            <strong><BidiText>{matchedName}</BidiText></strong>
            <span className="ds-muted">
              {requirement.parent_section_header && (
                <BidiText>{requirement.parent_section_header}</BidiText>
              )}
              {sourcePage > 0 && <span>{t("page", { page: sourcePage })}</span>}
            </span>
          </div>
        </div>
        {documentFetchError && (
          <Alert tone="danger" title={documentFetchError} />
        )}
        {isLoadingDocuments && (
          <p className="ds-muted">{t("workspace.resolvingDocument")}</p>
        )}
        {!isLoadingDocuments && !documentFetchError && !matchedDocument && (
          <p className="ds-muted">{t("fallbackUnmatched")}</p>
        )}
        {documentUrl && (
          <ButtonLink
            href={documentUrl}
            target="_blank"
            rel="noreferrer"
            variant="secondary"
            size="sm"
          >
            {t("workspace.openDocument")}
            <ExternalLink aria-hidden />
          </ButtonLink>
        )}
        <blockquote className="compliance-quote">
          <p dir="auto">{quote || t("workspace.evidenceUnavailable")}</p>
        </blockquote>
      </section>

      <section className="compliance-analysis-block" aria-labelledby={analysisTitleId}>
        <span className="ds-eyebrow" id={analysisTitleId}>
          {t("workspace.plasmaAnalysisLabel")}
        </span>
        <p dir={analysisContentDirection(analysisLanguage)}>
          {requirement.reason || t("workspace.analysisUnavailable")}
        </p>
      </section>

      {readinessContext && (
        <section className="compliance-readiness-support">
          <span className="ds-eyebrow">{t("workspace.readinessEvidence")}</span>
          {requirement.matched_credential && (
            <p><BidiText>{requirement.matched_credential}</BidiText></p>
          )}
          {!requirement.matched_credential && requirement.vault_missing_reason && (
            <p dir={analysisContentDirection(analysisLanguage)}>
              {requirement.vault_missing_reason}
            </p>
          )}
          <p className="ds-muted">{t("workspace.readinessEvidenceHelp")}</p>
          <ButtonLink href="/dashboard/readiness-vault" variant="secondary" size="sm">
            {t("workspace.openReadinessVault")}
          </ButtonLink>
        </section>
      )}

      {requirement.verdict === "FAILED" &&
        requirement.is_dealbreaker &&
        canMutate &&
        !isOverridden && (
          <Button variant="ghost" onClick={onOverride}>
            {t("overrideFlag")}
          </Button>
        )}
    </Surface>
  );
}

function verdictTone(tone: VerdictTone): Tone {
  return tone === "review" ? "warning" : tone === "pending" ? "neutral" : tone;
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
