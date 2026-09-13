"use client";

import {
  use,
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useLocale, useTranslations } from "next-intl";
import {
  AlertCircle,
  ArrowLeft,
  Building2,
  Calendar,
  CircleDollarSign,
  Download,
  ExternalLink,
  FileCheck2,
  FileText,
  Globe2,
  Landmark,
  Loader2,
  Mail,
  MapPin,
  Phone,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  UserRound,
  UsersRound,
} from "lucide-react";

import { TenderEngagementPanel } from "@/components/tenders/TenderEngagementPanel";
import { useSourceRefresh } from "@/components/source-refresh/SourceRefreshProvider";
import { Button, ButtonLink } from "@/components/ui/Button";
import {
  Surface,
  SectionHeader,
  StatusBadge,
  Badge,
  PageSkeleton,
  Metric,
} from "@/components/ui/Display";
import { Alert } from "@/components/ui/Feedback";
import { BidiText } from "@/components/i18n/BidiText";
import { api } from "@/lib/api";
import {
  formatCurrency,
  formatDate,
  formatDateTime,
  formatFileSize,
  formatNumber,
} from "@/i18n/formatters";
import type { CustomerSelectableLocale } from "@/i18n/locales";
import {
  EXPLORER_PATH,
  readExplorerReturnState,
} from "@/lib/explorerReturnState";
import type {
  DetailsSectionState,
  TenderDetailsCompliance,
  TenderDetailsDocumentItem,
  TenderDetailsProjectLeadershipItem,
  TenderDetailsResponse,
} from "@/types/tender-details";
import type { Tender } from "@/types/tender";
import { isTenderActionable } from "@/types/tender";

function safeText(value: string | null | undefined, fallback: string) {
  return value?.trim() || fallback;
}

function SectionStateBadge({ state }: { state: DetailsSectionState }) {
  const t = useTranslations("tenderDetails.sectionState");
  return (
    <StatusBadge
      tone={
        state === "AVAILABLE"
          ? "success"
          : state === "UNAVAILABLE"
            ? "warning"
            : "neutral"
      }
    >
      {state === "AVAILABLE"
        ? t("available")
        : state === "UNAVAILABLE"
          ? t("unavailable")
          : t("empty")}
    </StatusBadge>
  );
}
function SectionShell({
  id,
  title,
  description,
  icon,
  state,
  children,
}: {
  id: string;
  title: string;
  description: string;
  icon: ReactNode;
  state?: DetailsSectionState;
  children: ReactNode;
}) {
  return (
    <Surface
      id={id}
      role="region"
      aria-labelledby={`${id}-heading`}
      className="details-section"
    >
      <SectionHeader
        titleId={`${id}-heading`}
        title={title}
        description={description}
        icon={icon}
        action={state ? <SectionStateBadge state={state} /> : undefined}
      />
      <div className="details-section-body">{children}</div>
    </Surface>
  );
}
function CompactState({
  state,
  empty,
  unavailable,
}: {
  state: DetailsSectionState;
  empty: string;
  unavailable: string;
}) {
  return (
    <Alert
      tone={state === "UNAVAILABLE" ? "warning" : "info"}
      title={state === "UNAVAILABLE" ? unavailable : empty}
    />
  );
}
function DetailsLoading() {
  const t = useTranslations("tenderDetails");
  return <PageSkeleton label={t("detailsLoading")} />;
}

function leadershipRoleLabel(
  role: TenderDetailsProjectLeadershipItem,
  sourceDisplayName: string,
  copy: {
    sourceProjectTeam: (source: string) => string;
    taskTeamLeader: string;
    coTaskTeamLeader: string;
    projectTaskManager: string;
    projectRole: string;
  },
) {
  if (role.native_role.trim().toLowerCase() === "teamleadname")
    return copy.sourceProjectTeam(sourceDisplayName);
  if (role.canonical_role === "TASK_TEAM_LEADER") return copy.taskTeamLeader;
  if (role.canonical_role === "CO_TASK_TEAM_LEADER")
    return copy.coTaskTeamLeader;
  if (role.canonical_role === "PROJECT_TASK_MANAGER")
    return copy.projectTaskManager;
  return role.native_role || copy.projectRole;
}

function compliancePresentation(
  compliance: TenderDetailsCompliance,
  state: DetailsSectionState,
  copy: {
    failed: string;
    failedDetail: string;
    partial: string;
    partialDetail: string;
    legacy: string;
    legacyDetail: string;
    available: string;
    availableDetail: string;
  },
) {
  const failed =
    compliance.execution_state === "FAILED" || state === "UNAVAILABLE";
  const partial = compliance.compliance_completeness === "PARTIAL";
  const legacy = compliance.version_origin === "LEGACY_BACKFILL";
  if (failed)
    return {
      label: copy.failed,
      tone: "danger" as const,
      detail: copy.failedDetail,
    };
  if (partial)
    return {
      label: copy.partial,
      tone: "warning" as const,
      detail: copy.partialDetail,
    };
  if (legacy)
    return {
      label: copy.legacy,
      tone: "neutral" as const,
      detail: copy.legacyDetail,
    };
  return {
    label: compliance.decision_label || copy.available,
    tone: "success" as const,
    detail: copy.availableDetail,
  };
}

function documentAvailability(item: TenderDetailsDocumentItem) {
  return {
    tone:
      item.availability === "AVAILABLE"
        ? ("success" as const)
        : item.availability === "UNAVAILABLE"
          ? ("danger" as const)
          : ("warning" as const),
  };
}

export default function TenderDetailPage({
  params,
}: {
  params: Promise<{ tenderId: string }>;
}) {
  const t = useTranslations("tenderDetails");
  const tExplorer = useTranslations("explorer");
  const tBid = useTranslations("bidPreparation");
  const locale = useLocale() as CustomerSelectableLocale;
  const { displayNameForSource } = useSourceRefresh();
  const { tenderId } = use(params);
  const [returnHref, setReturnHref] = useState(EXPLORER_PATH);
  const [tender, setTender] = useState<Tender | null>(null);
  const [details, setDetails] = useState<TenderDetailsResponse | null>(null);
  const [isLoadingTender, setIsLoadingTender] = useState(true);
  const [isLoadingDetails, setIsLoadingDetails] = useState(true);
  const [tenderError, setTenderError] = useState<string | null>(null);
  const [detailsError, setDetailsError] = useState<string | null>(null);
  const copy = useTranslations("tenderDetails.redesign");
  const [openingDocumentId, setOpeningDocumentId] = useState<string | null>(
    null,
  );
  const [documentActionError, setDocumentActionError] = useState<string | null>(
    null,
  );

  useEffect(() => {
    const restoreState = readExplorerReturnState();
    if (restoreState) setReturnHref(restoreState.explorerUrl);
  }, []);

  const loadTender = useCallback(async () => {
    setIsLoadingTender(true);
    setTenderError(null);
    try {
      const response = await api.get<Tender>(`/tenders/${tenderId}`);
      setTender(response.data);
    } catch (error: unknown) {
      setTender(null);
      console.error("Failed to load Tender:");
      const status = (error as { response?: { status?: number } }).response
        ?.status;
      setTenderError(
        status === 404
          ? "notFound"
          : status === 401 || status === 403
            ? "denied"
            : "loadFailed",
      );
    } finally {
      setIsLoadingTender(false);
    }
  }, [tenderId]);

  const loadDetails = useCallback(async () => {
    setIsLoadingDetails(true);
    setDetailsError(null);
    try {
      const response = await api.get<TenderDetailsResponse>(
        `/tenders/${tenderId}/details`,
      );
      setDetails(response.data);
    } catch {
      setDetails(null);
      console.error("Failed to load additional Tender details:");
      setDetailsError("detailsFailed");
    } finally {
      setIsLoadingDetails(false);
    }
  }, [tenderId]);

  useEffect(() => {
    void loadTender();
  }, [loadTender]);
  useEffect(() => {
    void loadDetails();
  }, [loadDetails]);

  useEffect(() => {
    if (isLoadingDetails || !window.location.hash) return;
    const target = document.querySelector(window.location.hash);
    if (!target) return;
    window.requestAnimationFrame(() =>
      target.scrollIntoView({ block: "start" }),
    );
  }, [isLoadingDetails]);

  const openDocument = useCallback(
    async (item: TenderDetailsDocumentItem) => {
      if (item.availability !== "AVAILABLE" || openingDocumentId) return;
      setOpeningDocumentId(item.document_id);
      setDocumentActionError(null);
      try {
        const response = await api.get(
          `/tenders/documents/${item.document_id}/download`,
          { responseType: "blob" },
        );
        const contentType =
          (typeof response.headers["content-type"] === "string"
            ? response.headers["content-type"]
            : undefined) ||
          item.content_type ||
          "application/octet-stream";
        const url = URL.createObjectURL(
          new Blob([response.data], { type: contentType }),
        );
        const link = document.createElement("a");
        link.href = url;
        if (contentType.includes("pdf")) {
          link.target = "_blank";
          link.rel = "noreferrer";
        } else {
          link.download = item.display_name;
        }
        document.body.appendChild(link);
        link.click();
        link.remove();
        window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
      } catch {
        console.error("Failed to open Tender document:");
        setDocumentActionError(t("documentOpenFailed"));
      } finally {
        setOpeningDocumentId(null);
      }
    },
    [openingDocumentId, t],
  );

  const actionable = isTenderActionable(tender);
  const project = details?.project_context.data ?? null;
  const leadership = details?.project_leadership.data ?? null;
  const contacts = details?.procurement_contacts.data ?? null;
  const requirements = details?.requirements.data ?? null;
  const documents = details?.documents.data ?? null;
  const compliance = details?.compliance.data ?? null;
  const readiness = details?.company_readiness.data ?? null;
  const pursuit = details?.pursuit.data ?? null;
  const bidPreparation = details?.bid_preparation.data ?? null;
  const currentRoles = useMemo(
    () => leadership?.items.filter((role) => role.is_current) ?? [],
    [leadership],
  );
  const historicalRoles = useMemo(
    () => leadership?.items.filter((role) => !role.is_current) ?? [],
    [leadership],
  );
  const presentDate = (
    value: string | null | undefined,
    includeTime = false,
  ) =>
    includeTime ? formatDateTime(value, locale) : formatDate(value, locale);
  const presentFileSize = (value: number | null) =>
    value === null || value < 0
      ? t("sizeMissing")
      : formatFileSize(value, locale);
  const presentMoney =
    tender?.price_display ||
    (tender && tender.budget > 0
      ? formatCurrency(tender.budget, tender.currency, locale, {
          maximumFractionDigits: 2,
        })
      : t("notSpecified"));
  const tenderStatus =
    tender?.status === "OPEN"
      ? tExplorer("status.open")
      : tender?.status === "CLOSED"
        ? tExplorer("status.closed")
        : tender?.status === "CANCELLED"
          ? tExplorer("status.cancelled")
          : tExplorer("status.unknown");
  const sectionLinks = [
    { href: "#pursuit", label: t("sections.pursuit") },
    { href: "#project-context", label: t("sections.project") },
    { href: "#requirements-documents", label: t("sections.requirements") },
    { href: "#compliance-readiness", label: t("sections.compliance") },
    { href: "#contacts", label: t("sections.contacts") },
    { href: "#bid-preparation", label: t("sections.bid") },
  ];
  const leadershipCopy = {
    sourceProjectTeam: (source: string) => t("sourceProjectTeam", { source }),
    taskTeamLeader: t("taskTeamLeader"),
    coTaskTeamLeader: t("coTaskTeamLeader"),
    projectTaskManager: t("projectTaskManager"),
    projectRole: t("projectRole"),
  };

  if (isLoadingTender)
    return (
      <div className="customer-page">
        <PageSkeleton label={t("loading")} />
      </div>
    );

  if (tenderError || !tender) {
    return (
      <div className="customer-page ds-stack">
        <ButtonLink prefetch={false} href={returnHref}>
          <ArrowLeft className="rtl-mirror" aria-hidden="true" />
          {t("back")}
        </ButtonLink>
        <div
          role="alert"
          className="ds-rounded border ds-border ds-bg-subtle p-5 ds-body-text ds-text-danger"
        >
          {tenderError === "notFound"
            ? copy("notFound")
            : tenderError === "denied"
              ? copy("denied")
              : t("loadFailed")}
        </div>
      </div>
    );
  }

  return (
    <div className="customer-page ds-stack" data-page="tender-details">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <ButtonLink prefetch={false} href={returnHref}>
          <ArrowLeft className="rtl-mirror" aria-hidden="true" />
          {t("back")}
        </ButtonLink>
        <div className="flex flex-wrap gap-2">
          {tender.source_url ? (
            <a
              href={tender.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="ds-button ds-button-secondary ds-button-sm"
            >
              <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
              {t("openSource")}
            </a>
          ) : null}
          <ButtonLink
            prefetch={false}
            href={`/dashboard/tenders/${tender.id}/compliance`}
          >
            <ShieldCheck aria-hidden="true" />
            {t("openCompliance")}
          </ButtonLink>
        </div>
      </div>

      <header className="details-hero">
        <div className="ds-stack">
          <div className="flex flex-wrap items-center gap-2">
            <Badge>
              {t("source", {
                source: displayNameForSource(tender.source_system),
              })}
            </Badge>
            <StatusBadge
              tone={tender.status === "OPEN" ? "success" : "neutral"}
            >
              {t("status", { status: tenderStatus })}
            </StatusBadge>
            <span
              dir="ltr"
              className="technical-ltr inline-flex ds-rounded border ds-border ds-bg-subtle px-2 py-1 ds-text-small font-medium ds-muted"
            >
              {t("reference", { reference: tender.external_id })}
            </span>
          </div>
          <h1 dir="auto" className="bidi-auto">
            {tender.title}
          </h1>
          <p
            dir="auto"
            className="bidi-auto mt-3 max-w-5xl ds-body-text leading-6 ds-muted"
          >
            {tender.description || t("descriptionMissing")}
          </p>
        </div>
        <dl className="details-facts">
          {[
            {
              label: t("procuringEntity"),
              value: safeText(tender.buyer, t("notSpecified")),
              icon: <Building2 className="h-4 w-4" />,
            },
            {
              label: t("deadline"),
              value: presentDate(tender.deadline),
              icon: <Calendar className="h-4 w-4" />,
            },
            {
              label: t("estimatedValue"),
              value: presentMoney,
              icon: <CircleDollarSign className="h-4 w-4" />,
            },
            {
              label: t("location"),
              value:
                [tender.country, tender.region].filter(Boolean).join(" / ") ||
                t("notSpecified"),
              icon: <MapPin className="h-4 w-4" />,
            },
          ].map((item) => (
            <div key={item.label} className="min-w-0 p-4">
              <dt className="flex items-center gap-2 ds-text-small font-semibold uppercase tracking-wide ds-muted">
                {item.icon}
                {item.label}
              </dt>
              <dd
                dir="auto"
                className="bidi-auto mt-2 break-words ds-body-text font-medium ds-text"
              >
                {item.value}
              </dd>
            </div>
          ))}
        </dl>
      </header>

      <nav aria-label={t("sectionsLabel")} className="details-anchors">
        <div className="flex min-w-max gap-1">
          {sectionLinks.map((item) => (
            <a
              key={item.href}
              href={item.href}
              className="ds-button ds-button-secondary ds-button-sm"
            >
              {item.label}
            </a>
          ))}
        </div>
      </nav>

      {isLoadingDetails ? <DetailsLoading /> : null}
      {detailsError ? (
        <div
          role="alert"
          className="flex flex-col gap-3 ds-rounded border ds-border ds-bg-subtle p-4 ds-body-text ds-text sm:flex-row sm:items-center sm:justify-between"
        >
          <div className="flex items-start gap-2">
            <AlertCircle
              className="mt-0.5 h-4 w-4 shrink-0"
              aria-hidden="true"
            />
            <p className="font-semibold">{t("detailsFailed")}</p>
          </div>
          <Button
            variant="secondary"
            size="sm"
            type="button"
            onClick={() => void loadDetails()}
          >
            <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
            {t("retryDetails")}
          </Button>
        </div>
      ) : null}

      <div className="details-layout">
        <div>
          {details ? (
            <div className="details-grid">
              <div id="pursuit" className="scroll-mt-28">
                <TenderEngagementPanel
                  foundation
                  tenderId={tender.id}
                  proposalContext
                  engagementData={pursuit}
                  proposalIdData={bidPreparation?.proposal_id ?? null}
                  loadingData={false}
                  canStartNew={actionable}
                  onRefresh={loadDetails}
                />
                {pursuit ? (
                  <p className="mt-2 px-1 ds-text-small ds-muted">
                    {t("pursuitChanged", {
                      date: presentDate(pursuit.status_changed_at, true),
                    })}
                  </p>
                ) : null}
              </div>
              <SectionShell
                id="compliance-readiness"
                title={t("complianceTitle")}
                description={t("complianceHelp")}
                icon={<ShieldCheck className="h-4 w-4" />}
                state={
                  details.compliance.state === "UNAVAILABLE"
                    ? "UNAVAILABLE"
                    : compliance || readiness
                      ? "AVAILABLE"
                      : "EMPTY"
                }
              >
                <div className="grid gap-4 details-fields">
                  <article
                    className="ds-rounded border ds-border ds-bg-subtle p-4"
                    aria-labelledby="compliance-summary-heading"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <h3
                        id="compliance-summary-heading"
                        className="font-semibold ds-text"
                      >
                        {t("compliance")}
                      </h3>
                      <SectionStateBadge state={details.compliance.state} />
                    </div>
                    {compliance ? (
                      (() => {
                        const presentation = compliancePresentation(
                          compliance,
                          details.compliance.state,
                          {
                            failed: t("complianceFailed"),
                            failedDetail: t("complianceFailedDetail"),
                            partial: t("compliancePartial"),
                            partialDetail: t("compliancePartialDetail"),
                            legacy: t("complianceLegacy"),
                            legacyDetail: t("complianceLegacyDetail"),
                            available: t("complianceAvailable"),
                            availableDetail: t("complianceAvailableDetail"),
                          },
                        );
                        return (
                          <div className="mt-4 space-y-3">
                            <StatusBadge tone={presentation.tone}>
                              {presentation.label}
                            </StatusBadge>
                            <p className="ds-body-text leading-5 ds-muted">
                              {presentation.detail}
                            </p>
                            <dl className="grid grid-cols-2 gap-3 ds-body-text">
                              <div>
                                <dt className="ds-text-small ds-muted">
                                  {t("completeness")}
                                </dt>
                                <dd className="mt-1 ds-text">
                                  {compliance.compliance_completeness ===
                                  "COMPLETE"
                                    ? t("complete")
                                    : compliance.compliance_completeness ===
                                        "PARTIAL"
                                      ? t("partial")
                                      : t("notReported")}
                                </dd>
                              </div>
                              <div>
                                <dt className="ds-text-small ds-muted">
                                  {t("version")}
                                </dt>
                                <dd className="mt-1 ds-text">
                                  v{compliance.version_number}
                                </dd>
                              </div>
                              <div>
                                <dt className="ds-text-small ds-muted">
                                  {t("keyIssues")}
                                </dt>
                                <dd className="mt-1 ds-text">
                                  {compliance.key_issue_count === null
                                    ? t("notReported")
                                    : formatNumber(
                                        compliance.key_issue_count,
                                        locale,
                                      )}
                                </dd>
                              </div>
                              <div>
                                <dt className="ds-text-small ds-muted">
                                  {t("analysisCreated")}
                                </dt>
                                <dd className="mt-1 ds-text">
                                  {presentDate(compliance.created_at)}
                                </dd>
                              </div>
                            </dl>
                            {compliance.version_origin === "LEGACY_BACKFILL" ? (
                              <p className="ds-text-small font-medium ds-muted">
                                {t("legacyLimitations")}
                              </p>
                            ) : null}
                            {compliance.override_applied ? (
                              <p className="ds-text-small ds-text">
                                {t("overrideRecorded")}
                              </p>
                            ) : null}
                          </div>
                        );
                      })()
                    ) : (
                      <div className="mt-4">
                        <CompactState
                          state={details.compliance.state}
                          empty={t("complianceEmpty")}
                          unavailable={t("complianceUnavailable")}
                        />
                      </div>
                    )}
                    <ButtonLink
                      prefetch={false}
                      href={`/dashboard/tenders/${tender.id}/compliance`}
                    >
                      <ShieldCheck />
                      {t("openCompliance")}
                    </ButtonLink>
                  </article>
                  <article
                    className="ds-rounded border ds-border ds-bg-subtle p-4"
                    aria-labelledby="readiness-summary-heading"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <h3
                        id="readiness-summary-heading"
                        className="font-semibold ds-text"
                      >
                        {t("readiness")}
                      </h3>
                      <SectionStateBadge
                        state={details.company_readiness.state}
                      />
                    </div>
                    {readiness ? (
                      <div className="mt-4">
                        <p className="ds-body-text leading-5 ds-muted">
                          {t("readinessHelp")}
                        </p>
                        <dl className="mt-4 grid grid-cols-2 gap-3 ds-body-text sm:grid-cols-3">
                          <div>
                            <dt className="ds-text-small ds-muted">
                              {t("certifications")}
                            </dt>
                            <dd className="mt-1 ds-text">
                              {readiness.certifications_total}
                            </dd>
                            <dd className="ds-text-small ds-muted">
                              {t("expiredCount", {
                                count: readiness.expired_certifications,
                              })}
                            </dd>
                          </div>
                          <div>
                            <dt className="ds-text-small ds-muted">
                              {t("licenses")}
                            </dt>
                            <dd className="mt-1 ds-text">
                              {t("activeCount", {
                                count: readiness.active_licenses,
                              })}
                            </dd>
                            <dd className="ds-text-small ds-muted">
                              {t("totalCount", {
                                count: readiness.licenses_total,
                              })}
                            </dd>
                          </div>
                          <div>
                            <dt className="ds-text-small ds-muted">
                              {t("credentials")}
                            </dt>
                            <dd className="mt-1 ds-text">
                              {readiness.credentials_total}
                            </dd>
                            <dd className="ds-text-small ds-muted">
                              {t("expiredCount", {
                                count: readiness.expired_credentials,
                              })}
                            </dd>
                          </div>
                          <div>
                            <dt className="ds-text-small ds-muted">
                              {t("readinessFiles")}
                            </dt>
                            <dd className="mt-1 ds-text">
                              {t("availableCount", {
                                count: readiness.readiness_documents_available,
                              })}
                            </dd>
                            <dd className="ds-text-small ds-muted">
                              {t("totalCount", {
                                count: readiness.readiness_documents_total,
                              })}
                            </dd>
                          </div>
                          <div>
                            <dt className="ds-text-small ds-muted">
                              {t("missingEvidence")}
                            </dt>
                            <dd className="mt-1 ds-text">
                              {readiness.readiness_documents_missing}
                            </dd>
                          </div>
                          <div>
                            <dt className="ds-text-small ds-muted">
                              {t("financialYears")}
                            </dt>
                            <dd className="mt-1 ds-text">
                              {readiness.financial_history_years}
                            </dd>
                          </div>
                        </dl>
                      </div>
                    ) : (
                      <div className="mt-4">
                        <CompactState
                          state={details.company_readiness.state}
                          empty={t("readinessEmpty")}
                          unavailable={t("readinessUnavailable")}
                        />
                      </div>
                    )}
                    <ButtonLink
                      prefetch={false}
                      href="/dashboard/readiness-vault"
                    >
                      <FileCheck2 />
                      {t("openReadiness")}
                    </ButtonLink>
                  </article>
                </div>
              </SectionShell>
              <SectionShell
                id="project-context"
                title={t("projectTitle")}
                description={t("projectHelp")}
                icon={<Globe2 className="h-4 w-4" />}
                state={details.project_context.state}
              >
                {project ? (
                  <div className="space-y-5">
                    {details.project_context.state === "UNAVAILABLE" ? (
                      <div
                        role="status"
                        className="flex items-start gap-2 ds-rounded border ds-border ds-bg-subtle px-3 py-2 ds-body-text ds-text"
                      >
                        <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                        {t("projectUnavailable")}
                      </div>
                    ) : ["queued", "running", "never_attempted"].includes(
                        project.enrichment_state,
                      ) ? (
                      <div
                        role="status"
                        className="flex items-start gap-2 ds-rounded border ds-border ds-bg-subtle px-3 py-2 ds-body-text ds-text"
                      >
                        <Loader2 className="mt-0.5 h-4 w-4 shrink-0 animate-spin" />
                        {t("projectPreparing")}
                      </div>
                    ) : null}
                    <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                      <div>
                        <h3
                          dir="auto"
                          className="bidi-auto font-semibold ds-text"
                        >
                          {project.name ||
                            t("projectName", {
                              source: displayNameForSource(
                                project.source_system,
                              ),
                            })}
                        </h3>
                        <p className="mt-1 ds-body-text ds-muted">
                          <span dir="auto" className="bidi-auto">
                            {displayNameForSource(project.source_system)}
                          </span>{" "}
                          ·{" "}
                          <span dir="ltr" className="technical-ltr">
                            {project.external_project_id}
                          </span>
                        </p>
                      </div>
                      <span className="w-fit ds-rounded border ds-border ds-bg-subtle px-2 py-1 ds-text-small font-semibold ds-text">
                        {t("projectStatus", {
                          status: safeText(
                            project.project_status,
                            t("notReported"),
                          ),
                        })}
                      </span>
                    </div>
                    <dl className="grid grid-cols-1 gap-4 ds-body-text details-fields details-fields">
                      <div>
                        <dt className="ds-text-small uppercase tracking-wide ds-muted">
                          {t("countryRegion")}
                        </dt>
                        <dd dir="auto" className="bidi-auto mt-1 ds-text">
                          {[project.country, project.region]
                            .filter(Boolean)
                            .join(" / ") || t("notReported")}
                        </dd>
                      </div>
                      <div>
                        <dt className="ds-text-small uppercase tracking-wide ds-muted">
                          {t("projectApproval")}
                        </dt>
                        <dd className="mt-1 ds-text">
                          {presentDate(project.approval_date)}
                        </dd>
                      </div>
                      <div>
                        <dt className="ds-text-small uppercase tracking-wide ds-muted">
                          {t("projectClosing")}
                        </dt>
                        <dd className="mt-1 ds-text">
                          {presentDate(project.closing_date)}
                        </dd>
                      </div>
                      <div>
                        <dt className="ds-text-small uppercase tracking-wide ds-muted">
                          {t("projectEnrichment")}
                        </dt>
                        <dd className="mt-1 ds-text">
                          {safeText(project.enrichment_state, t("notReported"))}
                        </dd>
                      </div>
                    </dl>
                    <div
                      aria-labelledby="project-leadership-heading"
                      className="border-t ds-border pt-5"
                    >
                      <div className="flex items-center gap-2">
                        <UsersRound className="h-4 w-4 text-cyan-300" />
                        <h3
                          id="project-leadership-heading"
                          className="ds-body-text font-semibold uppercase tracking-wide ds-text"
                        >
                          {t("leadership")}
                        </h3>
                      </div>
                      <p className="mt-2 ds-text-small leading-5 ds-muted">
                        {t("leadershipHelp")}
                      </p>
                      {currentRoles.length ? (
                        <div className="mt-3 grid gap-2 md:grid-cols-2">
                          {currentRoles.map((role) => (
                            <div
                              key={role.role_id}
                              className="ds-rounded border ds-border ds-bg-subtle p-3"
                            >
                              <p
                                dir="auto"
                                className="bidi-auto font-medium ds-text"
                              >
                                {role.display_name}
                              </p>
                              <p className="mt-1 ds-text-small ds-muted">
                                {leadershipRoleLabel(
                                  role,
                                  displayNameForSource(role.source_system),
                                  leadershipCopy,
                                )}
                              </p>
                              <p className="mt-2 ds-text-small ds-muted">
                                {t("source", {
                                  source: displayNameForSource(
                                    role.source_system,
                                  ),
                                })}
                              </p>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <p className="mt-3 ds-body-text ds-muted">
                          {t("leadershipEmpty")}
                        </p>
                      )}
                      {historicalRoles.length ? (
                        <details className="mt-3">
                          <summary className="cursor-pointer ds-body-text font-medium ds-muted focus-visible:outline-none focus-visible:ring-2">
                            {t("previousLeadership", {
                              count: historicalRoles.length,
                            })}
                          </summary>
                          <div className="mt-2 grid gap-2 md:grid-cols-2">
                            {historicalRoles.map((role) => (
                              <div
                                key={role.role_id}
                                className="ds-rounded border ds-border p-3 ds-body-text ds-muted"
                              >
                                <p dir="auto" className="bidi-auto">
                                  {role.display_name}
                                </p>
                                <p className="mt-1 ds-text-small ds-muted">
                                  {leadershipRoleLabel(
                                    role,
                                    displayNameForSource(role.source_system),
                                    leadershipCopy,
                                  )}{" "}
                                  ·{" "}
                                  {t("observedUntil", {
                                    date: presentDate(role.ended_at),
                                  })}
                                </p>
                              </div>
                            ))}
                          </div>
                        </details>
                      ) : null}
                    </div>
                  </div>
                ) : (
                  <CompactState
                    state={details.project_context.state}
                    empty={t("projectLinkedEmpty")}
                    unavailable={t("projectUnavailable")}
                  />
                )}
              </SectionShell>
              <SectionShell
                id="contacts"
                title={t("contactsTitle")}
                description={t("contactsHelp")}
                icon={<UserRound className="h-4 w-4" />}
                state={details.procurement_contacts.state}
              >
                {contacts ? (
                  <div className="grid gap-5 details-fields">
                    <dl className="grid grid-cols-1 gap-4 ds-body-text details-fields">
                      <div>
                        <dt className="ds-text-small uppercase tracking-wide ds-muted">
                          {t("procuringEntity")}
                        </dt>
                        <dd dir="auto" className="bidi-auto mt-1 ds-text">
                          {safeText(contacts.buyer_agency, t("notProvided"))}
                        </dd>
                      </div>
                      <div>
                        <dt className="ds-text-small uppercase tracking-wide ds-muted">
                          {t("procurementContact")}
                        </dt>
                        <dd dir="auto" className="bidi-auto mt-1 ds-text">
                          {safeText(contacts.contact_person, t("notProvided"))}
                        </dd>
                      </div>
                      <div>
                        <dt className="flex items-center gap-1 ds-text-small uppercase tracking-wide ds-muted">
                          <Mail className="h-3.5 w-3.5" />
                          {t("email")}
                        </dt>
                        <dd
                          dir="ltr"
                          className="technical-ltr mt-1 break-all ds-text"
                        >
                          {safeText(contacts.email, t("notProvided"))}
                        </dd>
                      </div>
                      <div>
                        <dt className="flex items-center gap-1 ds-text-small uppercase tracking-wide ds-muted">
                          <Phone className="h-3.5 w-3.5" />
                          {t("phone")}
                        </dt>
                        <dd dir="ltr" className="technical-ltr mt-1 ds-text">
                          {safeText(contacts.phone, t("notProvided"))}
                        </dd>
                      </div>
                    </dl>
                    <dl className="grid grid-cols-1 gap-4 ds-body-text details-fields">
                      <div>
                        <dt className="ds-text-small uppercase tracking-wide ds-muted">
                          {t("submissionMethod")}
                        </dt>
                        <dd dir="auto" className="bidi-auto mt-1 ds-text">
                          {safeText(
                            contacts.submission_method,
                            t("notProvided"),
                          )}
                        </dd>
                      </div>
                      <div>
                        <dt className="ds-text-small uppercase tracking-wide ds-muted">
                          {t("submissionDeadline")}
                        </dt>
                        <dd className="mt-1 ds-text">
                          {presentDate(contacts.submission_deadline)}
                        </dd>
                      </div>
                      <div>
                        <dt className="ds-text-small uppercase tracking-wide ds-muted">
                          {t("questionDeadline")}
                        </dt>
                        <dd className="mt-1 ds-text">
                          {presentDate(contacts.question_deadline)}
                        </dd>
                      </div>
                      <div>
                        <dt className="ds-text-small uppercase tracking-wide ds-muted">
                          {t("procedure")}
                        </dt>
                        <dd className="mt-1 ds-text">
                          {safeText(contacts.procedure_type, t("notProvided"))}
                        </dd>
                      </div>
                    </dl>
                    {contacts.participation_instructions ||
                    contacts.address ||
                    contacts.document_access_notes ? (
                      <div className="lg:col-span-2 ds-rounded border ds-border ds-bg-subtle p-3 ds-body-text ds-muted">
                        <p>
                          {safeText(
                            contacts.participation_instructions ||
                              contacts.document_access_notes ||
                              contacts.address,
                            t("notProvided"),
                          )}
                        </p>
                      </div>
                    ) : null}
                  </div>
                ) : (
                  <CompactState
                    state={details.procurement_contacts.state}
                    empty={t("contactsEmpty")}
                    unavailable={t("contactsUnavailable")}
                  />
                )}
              </SectionShell>
              <SectionShell
                id="requirements-documents"
                title={t("requirementsTitle")}
                description={t("requirementsHelp")}
                icon={<FileCheck2 className="h-4 w-4" />}
                state={
                  details.documents.state === "UNAVAILABLE" ||
                  details.requirements.state === "UNAVAILABLE"
                    ? "UNAVAILABLE"
                    : documents || requirements
                      ? "AVAILABLE"
                      : "EMPTY"
                }
              >
                <div className="grid gap-5 details-column-grid">
                  <div>
                    <div className="flex items-center justify-between gap-2">
                      <h3 className="ds-body-text font-semibold ds-text">
                        {t("importantRequirements")}
                      </h3>
                      <SectionStateBadge state={details.requirements.state} />
                    </div>
                    {requirements?.items.length ? (
                      <ul className="mt-3 space-y-2">
                        {requirements.items.map((item, index) => (
                          <li
                            key={`${item.label}-${index}`}
                            className="ds-rounded border ds-border ds-bg-subtle p-3"
                          >
                            <div className="flex items-start gap-2">
                              <Sparkles className="mt-0.5 h-4 w-4 shrink-0 ds-link" />
                              <div>
                                <p
                                  dir="auto"
                                  className="bidi-auto ds-body-text ds-text"
                                >
                                  {item.label}
                                </p>
                                <p className="mt-1 ds-text-small font-medium ds-link">
                                  {t("aiRequirement")}
                                </p>
                                {item.document_name ||
                                item.page ||
                                item.section ? (
                                  <p
                                    dir="auto"
                                    className="bidi-auto mt-1 ds-text-small ds-muted"
                                  >
                                    {[
                                      item.document_name,
                                      item.section,
                                      item.page,
                                    ]
                                      .filter(Boolean)
                                      .join(" · ")}
                                  </p>
                                ) : null}
                              </div>
                            </div>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <div className="mt-3">
                        <CompactState
                          state={details.requirements.state}
                          empty={t("requirementsEmpty")}
                          unavailable={t("requirementsUnavailable")}
                        />
                      </div>
                    )}
                    {requirements?.truncated ? (
                      <p className="mt-2 ds-text-small ds-muted">
                        {t("requirementsTruncated", {
                          returned: formatNumber(
                            requirements.returned_count,
                            locale,
                          ),
                          total: formatNumber(requirements.total_count, locale),
                        })}
                      </p>
                    ) : null}
                  </div>
                  <div>
                    <div className="flex items-center justify-between gap-2">
                      <h3 className="ds-body-text font-semibold ds-text">
                        {t("tenderDocuments")}
                      </h3>
                      <SectionStateBadge state={details.documents.state} />
                    </div>
                    {documentActionError ? (
                      <p
                        role="alert"
                        className="mt-3 ds-rounded border ds-border ds-bg-subtle px-3 py-2 ds-body-text ds-text-danger"
                      >
                        {documentActionError}
                      </p>
                    ) : null}
                    {documents?.items.length ? (
                      <div className="mt-3 overflow-hidden ds-rounded border ds-border">
                        <div className="divide-y ds-divide">
                          {documents.items.map((item) => {
                            const availability = documentAvailability(item);
                            const canOpen = item.availability === "AVAILABLE";
                            return (
                              <div
                                key={item.document_id}
                                className="grid gap-3 p-3 ds-body-text details-column-grid sm:items-center"
                              >
                                <div className="min-w-0">
                                  <p
                                    dir="auto"
                                    className="bidi-auto truncate font-medium ds-text"
                                  >
                                    {item.display_name}
                                  </p>
                                  <p
                                    dir="auto"
                                    className="bidi-auto mt-1 ds-text-small ds-muted"
                                  >
                                    {item.document_type} ·{" "}
                                    {displayNameForSource(item.source_system)} ·{" "}
                                    {presentFileSize(item.file_size)}
                                  </p>
                                </div>
                                <StatusBadge tone={availability.tone}>
                                  {item.availability === "AVAILABLE"
                                    ? t("sectionState.available")
                                    : item.availability === "UNAVAILABLE"
                                      ? t("sectionState.unavailable")
                                      : t("metadataOnly")}
                                </StatusBadge>
                                <Button
                                  variant="secondary"
                                  size="sm"
                                  type="button"
                                  onClick={() => void openDocument(item)}
                                  disabled={
                                    !canOpen || openingDocumentId !== null
                                  }
                                >
                                  {openingDocumentId === item.document_id ? (
                                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                  ) : canOpen ? (
                                    <Download className="h-3.5 w-3.5" />
                                  ) : (
                                    <FileText className="h-3.5 w-3.5" />
                                  )}
                                  {openingDocumentId === item.document_id
                                    ? t("opening")
                                    : canOpen
                                      ? t("openDocument")
                                      : t("metadataOnly")}
                                </Button>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    ) : (
                      <div className="mt-3">
                        <CompactState
                          state={details.documents.state}
                          empty={t("documentsEmpty")}
                          unavailable={t("documentsUnavailable")}
                        />
                      </div>
                    )}
                    {documents?.truncated ? (
                      <p className="mt-2 ds-text-small ds-muted">
                        {t("documentsTruncated", {
                          count:
                            documents.visible_total_count -
                            documents.returned_count,
                        })}
                      </p>
                    ) : null}
                  </div>
                </div>
              </SectionShell>
              <SectionShell
                id="bid-preparation"
                title={t("bidTitle")}
                description={t("bidHelp")}
                icon={<Landmark className="h-4 w-4" />}
                state={details.bid_preparation.state}
              >
                {bidPreparation ? (
                  <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                    <div>
                      <p className="ds-body-text font-semibold ds-text">
                        {t("preparationStatus", {
                          status: bidPreparation.proposal_status,
                        })}
                      </p>
                      <p className="mt-1 ds-body-text ds-muted">
                        {t("bidCreated", {
                          date: presentDate(bidPreparation.created_at),
                        })}
                      </p>
                    </div>
                    <ButtonLink
                      prefetch={false}
                      href={`/dashboard/bid-preparation/${bidPreparation.detail_route_id}`}
                    >
                      <ExternalLink />
                      {pursuit ? tBid("open") : tBid("continue")}
                    </ButtonLink>
                  </div>
                ) : (
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                    <div>
                      <p className="ds-body-text font-medium ds-text">
                        {t("notStarted")}
                      </p>
                      <p className="mt-1 ds-body-text ds-muted">
                        {t("bidNotStartedHelp")}
                      </p>
                    </div>
                    <SectionStateBadge state={details.bid_preparation.state} />
                  </div>
                )}
              </SectionShell>
            </div>
          ) : null}
        </div>
        <aside className="details-rail" aria-label={copy("glance")}>
          <Surface className="ds-pad ds-stack">
            <h2>{copy("recommendation")}</h2>
            {details?.recommendation ? (
              <>
                <Metric
                  label={copy("match")}
                  value={`${details.recommendation.match_score}/100`}
                />
                <p className="ds-muted">
                  <BidiText>
                    {details.recommendation.rationale_summary}
                  </BidiText>
                </p>
                {details.recommendation.is_dismissed && (
                  <StatusBadge>{copy("dismissed")}</StatusBadge>
                )}
              </>
            ) : (
              <p className="ds-muted">{copy("noRecommendation")}</p>
            )}
          </Surface>

          <section
            aria-label={t("sourceClassification")}
            className="ds-rounded border ds-border ds-bg-subtle p-4"
          >
            <div className="flex items-center gap-2 ds-text-small font-semibold uppercase tracking-wide ds-muted">
              <Globe2 className="h-4 w-4" />
              {t("sourceClassification")}
            </div>
            <div className="mt-3 grid gap-3 ds-body-text sm:grid-cols-3">
              <p>
                <span className="ds-muted">{t("category")}:</span>{" "}
                <span className="ds-text">
                  {safeText(
                    tender.procurement_category || tender.category,
                    t("notSpecified"),
                  )}
                </span>
              </p>
              <p>
                <span className="ds-muted">{t("method")}:</span>{" "}
                <span className="ds-text">
                  {safeText(tender.procurement_method, t("notSpecified"))}
                </span>
              </p>
              <p>
                <span className="ds-muted">{t("noticeType")}:</span>{" "}
                <span className="ds-text">
                  {safeText(tender.notice_type, t("notSpecified"))}
                </span>
              </p>
            </div>
          </section>
        </aside>
      </div>
    </div>
  );
}
