"use client";

import {
  use,
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import Link from "next/link";
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
import {
  isTenderActionable,
  sourceBadgeClasses,
  tenderStatusClasses,
} from "@/types/tender";

function safeText(value: string | null | undefined, fallback: string) {
  return value?.trim() || fallback;
}

function sectionStateClasses(state: DetailsSectionState) {
  if (state === "AVAILABLE")
    return "border-emerald-500/25 bg-emerald-500/10 text-emerald-200";
  if (state === "UNAVAILABLE")
    return "border-amber-500/25 bg-amber-500/10 text-amber-200";
  return "border-zinc-700 bg-zinc-800/60 text-zinc-400";
}

function SectionStateBadge({ state }: { state: DetailsSectionState }) {
  const t = useTranslations("tenderDetails.sectionState");
  return (
    <span
      className={`inline-flex rounded-md border px-2 py-1 text-[11px] font-semibold uppercase tracking-wide ${sectionStateClasses(state)}`}
    >
      {state === "AVAILABLE"
        ? t("available")
        : state === "UNAVAILABLE"
          ? t("unavailable")
          : t("empty")}
    </span>
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
    <section
      id={id}
      aria-labelledby={`${id}-heading`}
      className="scroll-mt-28 rounded-xl border border-zinc-800 bg-zinc-950 p-4 sm:p-5"
    >
      <div className="flex flex-col gap-3 border-b border-zinc-800 pb-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex min-w-0 items-start gap-3">
          <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-zinc-700 bg-zinc-900 text-indigo-300">
            {icon}
          </div>
          <div>
            <h2
              id={`${id}-heading`}
              className="text-base font-semibold text-white sm:text-lg"
            >
              {title}
            </h2>
            <p className="mt-1 text-sm leading-5 text-zinc-500">
              {description}
            </p>
          </div>
        </div>
        {state ? <SectionStateBadge state={state} /> : null}
      </div>
      <div className="pt-4">{children}</div>
    </section>
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
  const isUnavailable = state === "UNAVAILABLE";
  return (
    <div
      role={isUnavailable ? "status" : undefined}
      className={`flex items-start gap-2 rounded-lg border px-3 py-3 text-sm ${isUnavailable ? "border-amber-500/20 bg-amber-500/5 text-amber-200" : "border-zinc-800 bg-zinc-900/50 text-zinc-400"}`}
    >
      {isUnavailable ? (
        <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
      ) : (
        <FileText
          className="mt-0.5 h-4 w-4 shrink-0 text-zinc-500"
          aria-hidden="true"
        />
      )}
      <span>{isUnavailable ? unavailable : empty}</span>
    </div>
  );
}

function DetailsLoading() {
  const t = useTranslations("tenderDetails");
  return (
    <div
      role="status"
      aria-live="polite"
      className="rounded-xl border border-zinc-800 bg-zinc-950 p-5"
    >
      <div className="flex items-center gap-3 text-sm text-zinc-300">
        <Loader2
          className="h-4 w-4 animate-spin text-indigo-300"
          aria-hidden="true"
        />
        {t("detailsLoading")}
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-3">
        {[0, 1, 2].map((item) => (
          <div
            key={item}
            className="h-20 animate-pulse rounded-lg bg-zinc-900"
          />
        ))}
      </div>
    </div>
  );
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
      classes: "border-red-500/30 bg-red-500/10 text-red-200",
      detail: copy.failedDetail,
    };
  if (partial)
    return {
      label: copy.partial,
      classes: "border-amber-500/30 bg-amber-500/10 text-amber-200",
      detail: copy.partialDetail,
    };
  if (legacy)
    return {
      label: copy.legacy,
      classes: "border-zinc-600 bg-zinc-800/70 text-zinc-200",
      detail: copy.legacyDetail,
    };
  return {
    label: compliance.decision_label || copy.available,
    classes: "border-emerald-500/30 bg-emerald-500/10 text-emerald-200",
    detail: copy.availableDetail,
  };
}

function documentAvailability(item: TenderDetailsDocumentItem) {
  if (item.availability === "AVAILABLE") return { classes: "text-emerald-300" };
  if (item.availability === "UNAVAILABLE") return { classes: "text-red-300" };
  return { classes: "text-amber-300" };
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
      console.error("Failed to load Tender:", error);
      setTenderError(t("loadFailed"));
    } finally {
      setIsLoadingTender(false);
    }
  }, [t, tenderId]);

  const loadDetails = useCallback(async () => {
    setIsLoadingDetails(true);
    setDetailsError(null);
    try {
      const response = await api.get<TenderDetailsResponse>(
        `/tenders/${tenderId}/details`,
      );
      setDetails(response.data);
    } catch (error: unknown) {
      setDetails(null);
      console.error("Failed to load additional Tender details:", error);
      setDetailsError(t("detailsFailed"));
    } finally {
      setIsLoadingDetails(false);
    }
  }, [t, tenderId]);

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
          response.headers["content-type"] ||
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
      } catch (error: unknown) {
        console.error("Failed to open Tender document:", error);
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
    value === null || value < 0 ? t("sizeMissing") : formatFileSize(value, locale);
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

  if (isLoadingTender) {
    return (
      <div role="status" aria-live="polite" className="space-y-4">
        <div className="h-5 w-32 animate-pulse rounded bg-zinc-800" />
        <div className="h-56 animate-pulse rounded-xl border border-zinc-800 bg-zinc-950" />
        <span className="sr-only">{t("loading")}</span>
      </div>
    );
  }

  if (tenderError || !tender) {
    return (
      <div className="space-y-4">
        <Link
          href={returnHref}
          className="inline-flex items-center gap-2 text-sm text-zinc-400 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400"
        >
          <ArrowLeft className="rtl-mirror h-4 w-4" aria-hidden="true" />
          {t("back")}
        </Link>
        <div
          role="alert"
          className="rounded-xl border border-red-500/25 bg-red-500/10 p-5 text-sm text-red-200"
        >
          {tenderError || t("notFound")}
        </div>
      </div>
    );
  }

  return (
    <main className="space-y-5 pb-10">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <Link
          href={returnHref}
          className="inline-flex w-fit items-center gap-2 text-sm text-zinc-400 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400"
        >
          <ArrowLeft className="rtl-mirror h-4 w-4" aria-hidden="true" />
          {t("back")}
        </Link>
        <div className="flex flex-wrap gap-2">
          {tender.source_url ? (
            <a
              href={tender.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-xs font-semibold text-zinc-200 hover:border-indigo-500 hover:text-indigo-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400"
            >
              <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
              {t("openSource")}
            </a>
          ) : null}
          <Link
            href={`/dashboard/tenders/${tender.id}/compliance`}
            className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-3 py-2 text-xs font-semibold text-white hover:bg-indigo-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400"
          >
            <ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />
            {t("openCompliance")}
          </Link>
        </div>
      </div>

      <header className="overflow-hidden rounded-xl border border-zinc-800 bg-zinc-950">
        <div className="border-b border-zinc-800 bg-gradient-to-r from-indigo-500/10 via-transparent to-sky-500/5 p-5 sm:p-6">
          <div className="flex flex-wrap items-center gap-2">
            <span dir="auto"
              className={`inline-flex rounded-md border px-2 py-1 text-xs font-semibold ${sourceBadgeClasses(tender.source_system)}`}
            >
              {t("source", {
                source: displayNameForSource(tender.source_system),
              })}
            </span>
            <span
              className={`inline-flex rounded-md border px-2 py-1 text-xs font-semibold ${tenderStatusClasses(tender.status)}`}
            >
              {t("status", { status: tenderStatus })}
            </span>
            <span dir="ltr" className="technical-ltr inline-flex rounded-md border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs font-medium text-zinc-400">
              {t("reference", { reference: tender.external_id })}
            </span>
          </div>
          <h1 dir="auto" className="bidi-auto mt-4 max-w-5xl text-2xl font-bold leading-tight text-white sm:text-3xl">
            {tender.title}
          </h1>
          <p dir="auto" className="bidi-auto mt-3 max-w-5xl text-sm leading-6 text-zinc-400">
            {tender.description || t("descriptionMissing")}
          </p>
        </div>
        <dl className="grid grid-cols-1 divide-y divide-zinc-800 sm:grid-cols-2 xl:grid-cols-4 xl:divide-x xl:divide-y-0">
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
              <dt className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
                {item.icon}
                {item.label}
              </dt>
              <dd dir="auto" className="bidi-auto mt-2 break-words text-sm font-medium text-zinc-100">
                {item.value}
              </dd>
            </div>
          ))}
        </dl>
      </header>

      <nav
        aria-label={t("sectionsLabel")}
        className="sticky top-16 z-20 -mx-1 overflow-x-auto rounded-xl border border-zinc-800 bg-zinc-950/95 px-2 py-2 shadow-xl backdrop-blur"
      >
        <div className="flex min-w-max gap-1">
          {sectionLinks.map((item) => (
            <a
              key={item.href}
              href={item.href}
              className="rounded-lg px-3 py-2 text-xs font-semibold text-zinc-400 hover:bg-zinc-900 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400"
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
          className="flex flex-col gap-3 rounded-xl border border-amber-500/25 bg-amber-500/10 p-4 text-sm text-amber-100 sm:flex-row sm:items-center sm:justify-between"
        >
          <div className="flex items-start gap-2">
            <AlertCircle
              className="mt-0.5 h-4 w-4 shrink-0"
              aria-hidden="true"
            />
            <p className="font-semibold">{detailsError}</p>
          </div>
          <button
            type="button"
            onClick={() => void loadDetails()}
            className="inline-flex w-fit items-center gap-2 rounded-lg border border-amber-400/30 px-3 py-2 text-xs font-semibold hover:bg-amber-500/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
          >
            <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
            {t("retryDetails")}
          </button>
        </div>
      ) : null}

      {details ? (
        <>
          <div id="pursuit" className="scroll-mt-28">
            <TenderEngagementPanel
              tenderId={tender.id}
              proposalContext
              engagementData={pursuit}
              proposalIdData={bidPreparation?.proposal_id ?? null}
              loadingData={false}
              canStartNew={actionable}
              onRefresh={loadDetails}
            />
            {pursuit ? (
              <p className="mt-2 px-1 text-xs text-zinc-500">
                {t("pursuitChanged", {
                  date: presentDate(pursuit.status_changed_at, true),
                })}
              </p>
            ) : null}
          </div>

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
                    className="flex items-start gap-2 rounded-lg border border-amber-500/20 bg-amber-500/5 px-3 py-2 text-sm text-amber-200"
                  >
                    <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                    {t("projectUnavailable")}
                  </div>
                ) : ["queued", "running", "never_attempted"].includes(
                    project.enrichment_state,
                  ) ? (
                  <div
                    role="status"
                    className="flex items-start gap-2 rounded-lg border border-sky-500/20 bg-sky-500/5 px-3 py-2 text-sm text-sky-200"
                  >
                    <Loader2 className="mt-0.5 h-4 w-4 shrink-0 animate-spin" />
                    {t("projectPreparing")}
                  </div>
                ) : null}
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div>
                    <h3 dir="auto" className="bidi-auto font-semibold text-zinc-100">
                      {project.name ||
                        t("projectName", {
                          source: displayNameForSource(project.source_system),
                        })}
                    </h3>
                    <p className="mt-1 text-sm text-zinc-500">
                      <span dir="auto" className="bidi-auto">{displayNameForSource(project.source_system)}</span> ·{" "}
                      <span dir="ltr" className="technical-ltr">{project.external_project_id}</span>
                    </p>
                  </div>
                  <span className="w-fit rounded-md border border-sky-500/25 bg-sky-500/10 px-2 py-1 text-xs font-semibold text-sky-200">
                    {t("projectStatus", {
                      status: safeText(
                        project.project_status,
                        t("notReported"),
                      ),
                    })}
                  </span>
                </div>
                <dl className="grid grid-cols-1 gap-4 text-sm sm:grid-cols-2 lg:grid-cols-4">
                  <div>
                    <dt className="text-xs uppercase tracking-wide text-zinc-500">
                      {t("countryRegion")}
                    </dt>
                    <dd dir="auto" className="bidi-auto mt-1 text-zinc-200">
                      {[project.country, project.region]
                        .filter(Boolean)
                        .join(" / ") || t("notReported")}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs uppercase tracking-wide text-zinc-500">
                      {t("projectApproval")}
                    </dt>
                    <dd className="mt-1 text-zinc-200">
                      {presentDate(project.approval_date)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs uppercase tracking-wide text-zinc-500">
                      {t("projectClosing")}
                    </dt>
                    <dd className="mt-1 text-zinc-200">
                      {presentDate(project.closing_date)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs uppercase tracking-wide text-zinc-500">
                      {t("projectEnrichment")}
                    </dt>
                    <dd className="mt-1 text-zinc-200">
                      {safeText(project.enrichment_state, t("notReported"))}
                    </dd>
                  </div>
                </dl>
                <div
                  aria-labelledby="project-leadership-heading"
                  className="border-t border-zinc-800 pt-5"
                >
                  <div className="flex items-center gap-2">
                    <UsersRound className="h-4 w-4 text-cyan-300" />
                    <h3
                      id="project-leadership-heading"
                      className="text-sm font-semibold uppercase tracking-wide text-zinc-200"
                    >
                      {t("leadership")}
                    </h3>
                  </div>
                  <p className="mt-2 text-xs leading-5 text-zinc-500">
                    {t("leadershipHelp")}
                  </p>
                  {currentRoles.length ? (
                    <div className="mt-3 grid gap-2 md:grid-cols-2">
                      {currentRoles.map((role) => (
                        <div
                          key={role.role_id}
                          className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-3"
                        >
                          <p dir="auto" className="bidi-auto font-medium text-zinc-100">
                            {role.display_name}
                          </p>
                          <p className="mt-1 text-xs text-zinc-400">
                            {leadershipRoleLabel(
                              role,
                              displayNameForSource(role.source_system),
                              leadershipCopy,
                            )}
                          </p>
                          <p className="mt-2 text-xs text-zinc-500">
                            {t("source", {
                              source: displayNameForSource(role.source_system),
                            })}
                          </p>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="mt-3 text-sm text-zinc-500">
                      {t("leadershipEmpty")}
                    </p>
                  )}
                  {historicalRoles.length ? (
                    <details className="mt-3">
                      <summary className="cursor-pointer text-sm font-medium text-zinc-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400">
                        {t("previousLeadership", {
                          count: historicalRoles.length,
                        })}
                      </summary>
                      <div className="mt-2 grid gap-2 md:grid-cols-2">
                        {historicalRoles.map((role) => (
                          <div
                            key={role.role_id}
                            className="rounded-lg border border-zinc-800 p-3 text-sm text-zinc-300"
                          >
                            <p dir="auto" className="bidi-auto">{role.display_name}</p>
                            <p className="mt-1 text-xs text-zinc-500">
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
            <div className="grid gap-5 xl:grid-cols-[0.9fr_1.1fr]">
              <div>
                <div className="flex items-center justify-between gap-2">
                  <h3 className="text-sm font-semibold text-zinc-100">
                    {t("importantRequirements")}
                  </h3>
                  <SectionStateBadge state={details.requirements.state} />
                </div>
                {requirements?.items.length ? (
                  <ul className="mt-3 space-y-2">
                    {requirements.items.map((item, index) => (
                      <li
                        key={`${item.label}-${index}`}
                        className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-3"
                      >
                        <div className="flex items-start gap-2">
                          <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-violet-300" />
                          <div>
                            <p dir="auto" className="bidi-auto text-sm text-zinc-100">
                              {item.label}
                            </p>
                            <p className="mt-1 text-xs font-medium text-violet-300">
                              {t("aiRequirement")}
                            </p>
                            {item.document_name || item.page || item.section ? (
                              <p dir="auto" className="bidi-auto mt-1 text-xs text-zinc-500">
                                {[item.document_name, item.section, item.page]
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
                  <p className="mt-2 text-xs text-zinc-500">
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
                  <h3 className="text-sm font-semibold text-zinc-100">
                    {t("tenderDocuments")}
                  </h3>
                  <SectionStateBadge state={details.documents.state} />
                </div>
                {documentActionError ? (
                  <p
                    role="alert"
                    className="mt-3 rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-2 text-sm text-red-200"
                  >
                    {documentActionError}
                  </p>
                ) : null}
                {documents?.items.length ? (
                  <div className="mt-3 overflow-hidden rounded-lg border border-zinc-800">
                    <div className="divide-y divide-zinc-800">
                      {documents.items.map((item) => {
                        const availability = documentAvailability(item);
                        const canOpen = item.availability === "AVAILABLE";
                        return (
                          <div
                            key={item.document_id}
                            className="grid gap-3 p-3 text-sm sm:grid-cols-[minmax(0,1fr)_130px_auto] sm:items-center"
                          >
                            <div className="min-w-0">
                              <p dir="auto" className="bidi-auto truncate font-medium text-zinc-100">
                                {item.display_name}
                              </p>
                              <p dir="auto" className="bidi-auto mt-1 text-xs text-zinc-500">
                                {item.document_type} ·{" "}
                                {displayNameForSource(item.source_system)} ·{" "}
                                {presentFileSize(item.file_size)}
                              </p>
                            </div>
                            <p
                              className={`text-xs font-semibold ${availability.classes}`}
                            >
                              {item.availability === "AVAILABLE"
                                ? t("sectionState.available")
                                : item.availability === "UNAVAILABLE"
                                  ? t("sectionState.unavailable")
                                  : t("metadataOnly")}
                            </p>
                            <button
                              type="button"
                              onClick={() => void openDocument(item)}
                              disabled={!canOpen || openingDocumentId !== null}
                              className="inline-flex w-fit items-center gap-2 rounded-lg border border-zinc-700 px-3 py-2 text-xs font-semibold text-zinc-200 hover:border-indigo-500 hover:text-indigo-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400 disabled:cursor-not-allowed disabled:opacity-50"
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
                            </button>
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
                  <p className="mt-2 text-xs text-zinc-500">
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
            <div className="grid gap-4 lg:grid-cols-2">
              <article
                className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4"
                aria-labelledby="compliance-summary-heading"
              >
                <div className="flex items-center justify-between gap-2">
                  <h3
                    id="compliance-summary-heading"
                    className="font-semibold text-zinc-100"
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
                        <span
                          className={`inline-flex rounded-md border px-2 py-1 text-xs font-semibold ${presentation.classes}`}
                        >
                          {presentation.label}
                        </span>
                        <p className="text-sm leading-5 text-zinc-400">
                          {presentation.detail}
                        </p>
                        <dl className="grid grid-cols-2 gap-3 text-sm">
                          <div>
                            <dt className="text-xs text-zinc-500">
                              {t("completeness")}
                            </dt>
                            <dd className="mt-1 text-zinc-200">
                              {compliance.compliance_completeness === "COMPLETE"
                                ? t("complete")
                                : compliance.compliance_completeness ===
                                    "PARTIAL"
                                  ? t("partial")
                                  : t("notReported")}
                            </dd>
                          </div>
                          <div>
                            <dt className="text-xs text-zinc-500">
                              {t("version")}
                            </dt>
                            <dd className="mt-1 text-zinc-200">
                              v{compliance.version_number}
                            </dd>
                          </div>
                          <div>
                            <dt className="text-xs text-zinc-500">
                              {t("keyIssues")}
                            </dt>
                            <dd className="mt-1 text-zinc-200">
                              {compliance.key_issue_count === null
                                ? t("notReported")
                                : formatNumber(
                                    compliance.key_issue_count,
                                    locale,
                                  )}
                            </dd>
                          </div>
                          <div>
                            <dt className="text-xs text-zinc-500">
                              {t("analysisCreated")}
                            </dt>
                            <dd className="mt-1 text-zinc-200">
                              {presentDate(compliance.created_at)}
                            </dd>
                          </div>
                        </dl>
                        {compliance.version_origin === "LEGACY_BACKFILL" ? (
                          <p className="text-xs font-medium text-zinc-400">
                            {t("legacyLimitations")}
                          </p>
                        ) : null}
                        {compliance.override_applied ? (
                          <p className="text-xs text-amber-300">
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
                <Link
                  href={`/dashboard/tenders/${tender.id}/compliance`}
                  className="mt-4 inline-flex items-center gap-2 text-sm font-semibold text-indigo-300 hover:text-indigo-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400"
                >
                  <ShieldCheck className="h-4 w-4" />
                  {t("openCompliance")}
                </Link>
              </article>
              <article
                className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4"
                aria-labelledby="readiness-summary-heading"
              >
                <div className="flex items-center justify-between gap-2">
                  <h3
                    id="readiness-summary-heading"
                    className="font-semibold text-zinc-100"
                  >
                    {t("readiness")}
                  </h3>
                  <SectionStateBadge state={details.company_readiness.state} />
                </div>
                {readiness ? (
                  <div className="mt-4">
                    <p className="text-sm leading-5 text-zinc-400">
                      {t("readinessHelp")}
                    </p>
                    <dl className="mt-4 grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
                      <div>
                        <dt className="text-xs text-zinc-500">
                          {t("certifications")}
                        </dt>
                        <dd className="mt-1 text-zinc-100">
                          {readiness.certifications_total}
                        </dd>
                        <p className="text-xs text-zinc-500">
                          {t("expiredCount", {
                            count: readiness.expired_certifications,
                          })}
                        </p>
                      </div>
                      <div>
                        <dt className="text-xs text-zinc-500">
                          {t("licenses")}
                        </dt>
                        <dd className="mt-1 text-zinc-100">
                          {t("activeCount", {
                            count: readiness.active_licenses,
                          })}
                        </dd>
                        <p className="text-xs text-zinc-500">
                          {t("totalCount", {
                            count: readiness.licenses_total,
                          })}
                        </p>
                      </div>
                      <div>
                        <dt className="text-xs text-zinc-500">
                          {t("credentials")}
                        </dt>
                        <dd className="mt-1 text-zinc-100">
                          {readiness.credentials_total}
                        </dd>
                        <p className="text-xs text-zinc-500">
                          {t("expiredCount", {
                            count: readiness.expired_credentials,
                          })}
                        </p>
                      </div>
                      <div>
                        <dt className="text-xs text-zinc-500">
                          {t("readinessFiles")}
                        </dt>
                        <dd className="mt-1 text-zinc-100">
                          {t("availableCount", {
                            count: readiness.readiness_documents_available,
                          })}
                        </dd>
                        <p className="text-xs text-zinc-500">
                          {t("totalCount", {
                            count: readiness.readiness_documents_total,
                          })}
                        </p>
                      </div>
                      <div>
                        <dt className="text-xs text-zinc-500">
                          {t("missingEvidence")}
                        </dt>
                        <dd className="mt-1 text-zinc-100">
                          {readiness.readiness_documents_missing}
                        </dd>
                      </div>
                      <div>
                        <dt className="text-xs text-zinc-500">
                          {t("financialYears")}
                        </dt>
                        <dd className="mt-1 text-zinc-100">
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
                <Link
                  href="/dashboard/readiness-vault"
                  className="mt-4 inline-flex items-center gap-2 text-sm font-semibold text-sky-300 hover:text-sky-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
                >
                  <FileCheck2 className="h-4 w-4" />
                  {t("openReadiness")}
                </Link>
              </article>
            </div>
          </SectionShell>

          <SectionShell
            id="contacts"
            title={t("contactsTitle")}
            description={t("contactsHelp")}
            icon={<UserRound className="h-4 w-4" />}
            state={details.procurement_contacts.state}
          >
            {contacts ? (
              <div className="grid gap-5 lg:grid-cols-2">
                <dl className="grid grid-cols-1 gap-4 text-sm sm:grid-cols-2">
                  <div>
                    <dt className="text-xs uppercase tracking-wide text-zinc-500">
                      {t("procuringEntity")}
                    </dt>
                    <dd dir="auto" className="bidi-auto mt-1 text-zinc-200">
                      {safeText(contacts.buyer_agency, t("notProvided"))}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs uppercase tracking-wide text-zinc-500">
                      {t("procurementContact")}
                    </dt>
                    <dd dir="auto" className="bidi-auto mt-1 text-zinc-200">
                      {safeText(contacts.contact_person, t("notProvided"))}
                    </dd>
                  </div>
                  <div>
                    <dt className="flex items-center gap-1 text-xs uppercase tracking-wide text-zinc-500">
                      <Mail className="h-3.5 w-3.5" />
                      {t("email")}
                    </dt>
                    <dd dir="ltr" className="technical-ltr mt-1 break-all text-zinc-200">
                      {safeText(contacts.email, t("notProvided"))}
                    </dd>
                  </div>
                  <div>
                    <dt className="flex items-center gap-1 text-xs uppercase tracking-wide text-zinc-500">
                      <Phone className="h-3.5 w-3.5" />
                      {t("phone")}
                    </dt>
                    <dd dir="ltr" className="technical-ltr mt-1 text-zinc-200">
                      {safeText(contacts.phone, t("notProvided"))}
                    </dd>
                  </div>
                </dl>
                <dl className="grid grid-cols-1 gap-4 text-sm sm:grid-cols-2">
                  <div>
                    <dt className="text-xs uppercase tracking-wide text-zinc-500">
                      {t("submissionMethod")}
                    </dt>
                    <dd dir="auto" className="bidi-auto mt-1 text-zinc-200">
                      {safeText(contacts.submission_method, t("notProvided"))}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs uppercase tracking-wide text-zinc-500">
                      {t("submissionDeadline")}
                    </dt>
                    <dd className="mt-1 text-zinc-200">
                      {presentDate(contacts.submission_deadline)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs uppercase tracking-wide text-zinc-500">
                      {t("questionDeadline")}
                    </dt>
                    <dd className="mt-1 text-zinc-200">
                      {presentDate(contacts.question_deadline)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs uppercase tracking-wide text-zinc-500">
                      {t("procedure")}
                    </dt>
                    <dd className="mt-1 text-zinc-200">
                      {safeText(contacts.procedure_type, t("notProvided"))}
                    </dd>
                  </div>
                </dl>
                {contacts.participation_instructions ||
                contacts.address ||
                contacts.document_access_notes ? (
                  <div className="lg:col-span-2 rounded-lg border border-zinc-800 bg-zinc-900/50 p-3 text-sm text-zinc-400">
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
            id="bid-preparation"
            title={t("bidTitle")}
            description={t("bidHelp")}
            icon={<Landmark className="h-4 w-4" />}
            state={details.bid_preparation.state}
          >
            {bidPreparation ? (
              <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <p className="text-sm font-semibold text-zinc-100">
                    {t("preparationStatus", {
                      status: bidPreparation.proposal_status,
                    })}
                  </p>
                  <p className="mt-1 text-sm text-zinc-500">
                    {t("bidCreated", {
                      date: presentDate(bidPreparation.created_at),
                    })}
                  </p>
                </div>
                <Link
                  href={`/dashboard/bid-preparation/${bidPreparation.detail_route_id}`}
                  className="inline-flex w-fit items-center gap-2 rounded-lg bg-indigo-600 px-3 py-2 text-xs font-semibold text-white hover:bg-indigo-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400"
                >
                  <ExternalLink className="h-3.5 w-3.5" />
                  {pursuit ? tBid("open") : tBid("continue")}
                </Link>
              </div>
            ) : (
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <p className="text-sm font-medium text-zinc-200">
                    {t("notStarted")}
                  </p>
                  <p className="mt-1 text-sm text-zinc-500">
                    {t("bidNotStartedHelp")}
                  </p>
                </div>
                <SectionStateBadge state={details.bid_preparation.state} />
              </div>
            )}
          </SectionShell>
        </>
      ) : null}

      <section
        aria-label={t("sourceClassification")}
        className="rounded-xl border border-zinc-800 bg-zinc-950 p-4"
      >
        <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
          <Globe2 className="h-4 w-4" />
          {t("sourceClassification")}
        </div>
        <div className="mt-3 grid gap-3 text-sm sm:grid-cols-3">
          <p>
            <span className="text-zinc-500">{t("category")}:</span>{" "}
            <span className="text-zinc-200">
              {safeText(
                tender.procurement_category || tender.category,
                t("notSpecified"),
              )}
            </span>
          </p>
          <p>
            <span className="text-zinc-500">{t("method")}:</span>{" "}
            <span className="text-zinc-200">
              {safeText(tender.procurement_method, t("notSpecified"))}
            </span>
          </p>
          <p>
            <span className="text-zinc-500">{t("noticeType")}:</span>{" "}
            <span className="text-zinc-200">
              {safeText(tender.notice_type, t("notSpecified"))}
            </span>
          </p>
        </div>
      </section>
    </main>
  );
}
