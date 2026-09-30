"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Image from "next/image";
import { useLocale, useTranslations } from "next-intl";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Clock3,
  Database,
  FileSearch,
  FileText,
  Info,
  Landmark,
  Target,
} from "lucide-react";

import { BidiText, TechnicalText } from "@/components/i18n/BidiText";
import { DashboardBookmarkButton } from "@/components/customer/DashboardBookmarkButton";
import { SourceRefreshMenu } from "@/components/source-refresh/SourceRefreshMenu";
import { useSourceRefresh } from "@/components/source-refresh/SourceRefreshProvider";
import { Button, ButtonLink } from "@/components/ui/Button";
import {
  Badge,
  EmptyState,
  PageHeader,
  SectionHeader,
  Skeleton,
  StatusBadge,
  Surface,
} from "@/components/ui/Display";
import { Alert } from "@/components/ui/Feedback";
import {
  activeOpportunityShortlist,
  lastAuthoritativeRefresh,
  profilePromptVariant,
} from "@/lib/dashboard";
import { api } from "@/lib/api";
import { listExplorer } from "@/lib/explorer";
import {
  daysLeft,
  formatPublishedDeadline,
  isDeadlinePassed,
  isTenderOpen,
  type TenderTruth,
} from "@/lib/tenderTruth";
import { useTenderTruthLabels } from "@/lib/useTenderTruthLabels";
import { expiryState, documentTypeMessageKey } from "@/lib/readiness";
import {
  formatDate as formatLocaleDate,
  formatDateTime,
} from "@/i18n/formatters";
import type { CustomerSelectableLocale } from "@/i18n/locales";
import type { ExplorerItem, ExplorerTenderSummary } from "@/types/explorer";
import type { Tender } from "@/types/tender";

type CompanyProfile = {
  company_profile_id?: string | null;
  onboarding_required?: boolean;
  company_name?: string | null;
  director_name?: string | null;
  phone_contact?: string | null;
  inn?: string | null;
  industry?: string | null;
  target_regions?: string[] | null;
  target_countries?: string[] | null;
  target_services?: string[] | null;
};

type ReadinessDocument = {
  id: string;
  document_type: string;
  document_name: string;
  expiry_date?: string | null;
  status: string;
};

type LatestAnalysis = {
  analysis_id: string | null;
  requirement_count?: number;
  manual_review_count?: number;
  coverage_metadata?: {
    coverage_status?: unknown;
    source_document_coverage?: { coverage_status?: unknown };
  } | null;
  analysis_status: string;
  created_at?: string | null;
};

type AnalysisSummary = {
  tender: Tender;
  analysis: LatestAnalysis;
};

type SectionKey = "profile" | "readiness" | "opportunities" | "analyses";

type LoadState = {
  profile: CompanyProfile | null;
  readiness: ReadinessDocument[];
  recommendations: ExplorerItem[];
  analyses: AnalysisSummary[];
  failures: SectionKey[];
  loaded: SectionKey[];
};

type ActionItem = {
  key: string;
  issue: string;
  subject: string;
  date?: string | null;
  href: string;
  tone: "danger" | "warning";
  priority: number;
};

type DashboardTranslator = (
  key: string,
  values?: Record<string, string | number>,
) => string;

const REQUIRED_READINESS_TYPES = [
  "registration_document",
  "tax_clearance",
  "financial_statement",
  "license",
];

const SOURCE_NAMES: Record<string, string> = {
  world_bank: "World Bank",
  adb: "ADB",
  giz: "GIZ",
  ebrd: "EBRD",
  uzex: "UzEx",
};

const SOURCE_LOGOS: Record<string, string> = {
  world_bank: "/brand/sources/world-bank.svg",
  adb: "/brand/sources/adb.svg",
  giz: "/brand/sources/giz.svg",
  ebrd: "/brand/sources/ebrd.svg",
  uzex: "/brand/sources/uzex.svg",
};

function isCurrentTender(tender: ExplorerTenderSummary) {
  // Derived status plus the conservative effective deadline (D1-05b/c).
  return isTenderOpen(tender);
}

function customerDate(
  value: string | null | undefined,
  locale: CustomerSelectableLocale,
  t: DashboardTranslator,
) {
  return value ? formatLocaleDate(value, locale) : t("updatedUnavailable");
}

function deadlineState(
  truth: TenderTruth,
  now: number,
  t: DashboardTranslator,
) {
  // Days left count down to the conservative effective instant, never beyond it.
  const days = daysLeft(truth, now);
  if (days === null) return t("deadline.unknown");
  if (isDeadlinePassed(truth, now)) return t("deadline.expired");
  if (days === 0) return t("deadline.today");
  if (days === 1) return t("deadline.one");
  return t("deadline.many", { count: days });
}

function cleanAnalysisStatus(analysis: LatestAnalysis) {
  const coverage = analysis.coverage_metadata;
  const coverageStatus = String(coverage?.coverage_status ?? "");
  const sourceCoverage = String(
    coverage?.source_document_coverage?.coverage_status ?? "",
  );
  if (analysis.analysis_status === "failed" || coverageStatus === "failed") {
    return "failed" as const;
  }
  if (
    analysis.analysis_status === "needs_review" ||
    (analysis.manual_review_count ?? 0) > 0
  ) {
    return "review" as const;
  }
  if (coverageStatus === "partial" || sourceCoverage === "partial") {
    return "partial" as const;
  }
  return "complete" as const;
}

function buildActionItems(
  analyses: AnalysisSummary[],
  t: DashboardTranslator,
): ActionItem[] {
  return analyses
    .flatMap(({ tender, analysis }): ActionItem[] => {
      const status = cleanAnalysisStatus(analysis);
      if (status === "failed") {
        return [
          {
            key: `analysis-failed-${analysis.analysis_id}`,
            issue: t("issues.analysisFailed"),
            subject: tender.title,
            date: analysis.created_at,
            href: `/dashboard/tenders/${tender.id}/compliance`,
            tone: "danger",
            priority: 1,
          },
        ];
      }
      if (status === "review" || status === "partial") {
        return [
          {
            key: `analysis-review-${analysis.analysis_id}`,
            issue:
              status === "review"
                ? t("issues.manualReview")
                : t("issues.partialReview"),
            subject: tender.title,
            date: analysis.created_at,
            href: `/dashboard/tenders/${tender.id}/compliance`,
            tone: "warning",
            priority: status === "review" ? 2 : 3,
          },
        ];
      }
      return [];
    })
    .sort((a, b) => {
      if (a.priority !== b.priority) return a.priority - b.priority;
      return (
        new Date(b.date ?? 0).getTime() - new Date(a.date ?? 0).getTime()
      );
    })
    .slice(0, 3);
}

async function fetchLatestAnalyses(tenders: Tender[]) {
  const settled = await Promise.allSettled(
    tenders.slice(0, 12).map(async (tender) => {
      const response = await api.get<LatestAnalysis>(
        `/tenders/${tender.id}/latest-analysis`,
        { params: { summary_only: true } },
      );
      return { tender, analysis: response.data };
    }),
  );
  const analyses = settled
    .filter(
      (result): result is PromiseFulfilledResult<AnalysisSummary> =>
        result.status === "fulfilled",
    )
    .map((result) => result.value)
    .filter((item) => Boolean(item.analysis.analysis_id))
    .sort(
      (a, b) =>
        new Date(b.analysis.created_at ?? 0).getTime() -
        new Date(a.analysis.created_at ?? 0).getTime(),
    );
  return {
    analyses,
    successCount: settled.filter((result) => result.status === "fulfilled")
      .length,
    partial: settled.some((result) => result.status === "rejected"),
  };
}

function isTestOnlyTender(tender: Pick<Tender, "title" | "external_id">) {
  const marker = `${tender.title} ${tender.external_id}`.toLowerCase();
  return (
    marker.includes("[test]") ||
    marker.includes("test-only") ||
    marker.startsWith("test ")
  );
}

function DashboardSkeleton({ label }: { label: string }) {
  return (
    <div
      className="customer-page dashboard-skeleton"
      role="status"
      aria-label={label}
    >
      <span className="sr-only">{label}</span>
      <div className="dashboard-skeleton-header">
        <div>
          <Skeleton />
          <Skeleton />
          <Skeleton />
        </div>
        <Skeleton />
      </div>
      <div className="dashboard-grid">
        <div className="dashboard-column dashboard-primary-column">
          <Surface className="dashboard-active dashboard-skeleton-panel">
            <Skeleton />
            <Skeleton />
            <Skeleton />
          </Surface>
          <Surface className="dashboard-attention dashboard-skeleton-panel">
            <Skeleton />
            <Skeleton />
          </Surface>
          <Surface className="dashboard-analyses dashboard-skeleton-panel">
            <Skeleton />
            <Skeleton />
          </Surface>
        </div>
        <div className="dashboard-column dashboard-support-column">
          <Surface className="dashboard-readiness dashboard-skeleton-panel">
            <Skeleton />
            <Skeleton />
            <Skeleton />
            <Skeleton />
          </Surface>
          <Surface className="dashboard-profile dashboard-skeleton-panel">
            <Skeleton />
            <Skeleton />
          </Surface>
        </div>
      </div>
    </div>
  );
}

function SourceIdentity({ source, name }: { source: string; name: string }) {
  const [logoFailed, setLogoFailed] = useState(false);
  const logo = SOURCE_LOGOS[source];

  return (
    <div className="dashboard-source">
      {logo && !logoFailed ? (
        <span className="dashboard-source-logo-frame" data-source={source}>
          <Image
            src={logo}
            alt=""
            width={36}
            height={36}
            unoptimized
            data-source-logo="official"
            onError={() => setLogoFailed(true)}
          />
        </span>
      ) : (
        <span className="dashboard-source-fallback" data-source-logo="fallback">
          <Landmark aria-hidden />
        </span>
      )}
      <BidiText className="dashboard-source-name">{name}</BidiText>
    </div>
  );
}

export default function DashboardPage() {
  const locale = useLocale() as CustomerSelectableLocale;
  const truthLabels = useTenderTruthLabels();
  const translate = useTranslations("dashboard");
  const translateReadiness = useTranslations("readiness");
  const t = translate as DashboardTranslator;
  const tReadiness = translateReadiness as DashboardTranslator;
  const {
    displayNameForSource,
    statusItems,
    statusError,
    latestActivityBatch,
  } = useSourceRefresh();
  const [state, setState] = useState<LoadState>({
    profile: null,
    readiness: [],
    recommendations: [],
    analyses: [],
    failures: [],
    loaded: [],
  });
  const [initialLoading, setInitialLoading] = useState(true);
  const [retryVersion, setRetryVersion] = useState(0);
  const [now, setNow] = useState(() => Date.now());
  const hasLoadedRef = useRef(false);
  const refreshBatchId = latestActivityBatch?.id ?? 0;

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 60_000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    let mounted = true;

    const loadDashboard = async () => {
      if (!hasLoadedRef.current) setInitialLoading(true);
      const failures = new Set<SectionKey>();
      const loaded = new Set<SectionKey>();
      const [profileResult, readinessResult, opportunityResult, tendersResult] =
        await Promise.allSettled([
          api.get<CompanyProfile>("/users/me/company"),
          api.get<ReadinessDocument[]>("/vault/readiness"),
          listExplorer({
            view: "recommended",
            limit: 100,
            offset: 0,
            status: "OPEN",
            sort: "best_match",
          }),
          api.get<Tender[]>("/tenders", {
            params: { limit: 24, sort: "newest" },
          }),
        ]);

      if (profileResult.status === "fulfilled") loaded.add("profile");
      else failures.add("profile");
      if (readinessResult.status === "fulfilled") loaded.add("readiness");
      else failures.add("readiness");
      if (opportunityResult.status === "fulfilled")
        loaded.add("opportunities");
      else failures.add("opportunities");

      let analyses: AnalysisSummary[] | null = null;
      if (tendersResult.status === "fulfilled") {
        const candidates = (tendersResult.value.data ?? []).filter(
          (tender) => !isTestOnlyTender(tender),
        );
        const result = await fetchLatestAnalyses(candidates);
        if (result.successCount > 0 || candidates.length === 0) {
          analyses = result.analyses;
          loaded.add("analyses");
        }
        if (result.partial) failures.add("analyses");
      } else {
        failures.add("analyses");
      }

      if (!mounted) return;
      setState((current) => {
        const nextLoaded = new Set([...current.loaded, ...loaded]);
        return {
          profile:
            profileResult.status === "fulfilled"
              ? profileResult.value.data
              : current.profile,
          readiness:
            readinessResult.status === "fulfilled"
              ? readinessResult.value.data ?? []
              : current.readiness,
          recommendations:
            opportunityResult.status === "fulfilled"
              ? opportunityResult.value.data.items.filter((item) =>
                  isCurrentTender(item.tender),
                )
              : current.recommendations,
          analyses: analyses ?? current.analyses,
          failures: [...failures],
          loaded: [...nextLoaded],
        };
      });
      hasLoadedRef.current = true;
      setInitialLoading(false);
    };

    void loadDashboard();
    return () => {
      mounted = false;
    };
  }, [refreshBatchId, retryVersion]);

  const readinessStats = useMemo(() => {
    const expired = state.readiness.filter(
      (document) =>
        document.status === "expired" ||
        expiryState(document.expiry_date) === "expired",
    );
    const expiringSoon = state.readiness.filter(
      (document) =>
        document.status === "available" &&
        expiryState(document.expiry_date) === "expiring_soon",
    );
    const available = state.readiness.filter((document) => {
      const expiry = expiryState(document.expiry_date);
      return (
        document.status === "available" &&
        expiry !== "expired" &&
        expiry !== "expiring_soon"
      );
    });
    const representedTypes = new Set(
      state.readiness
        .filter((document) => document.status !== "missing")
        .map((document) => document.document_type),
    );
    const missingTypes = new Set(
      state.readiness
        .filter((document) => document.status === "missing")
        .map((document) => document.document_type),
    );
    REQUIRED_READINESS_TYPES.forEach((type) => {
      if (!representedTypes.has(type)) missingTypes.add(type);
    });
    return {
      available: available.length,
      missing: missingTypes.size,
      expired: expired.length,
      expiringSoon: expiringSoon.length,
      missingTypes: [...missingTypes],
    };
  }, [state.readiness]);

  const opportunities = useMemo(
    () => activeOpportunityShortlist(state.recommendations, now),
    [now, state.recommendations],
  );
  const actionItems = useMemo(
    () => buildActionItems(state.analyses, t),
    [state.analyses, t],
  );
  const profilePrompt = profilePromptVariant(state.profile);
  const lastUpdated = useMemo(
    () => lastAuthoritativeRefresh(statusItems),
    [statusItems],
  );
  const unavailable = (key: SectionKey) => state.failures.includes(key);
  const hasLoaded = (key: SectionKey) => state.loaded.includes(key);
  const failedAll = (
    ["profile", "readiness", "opportunities", "analyses"] as SectionKey[]
  ).every(unavailable);
  const retry = (
    <Button variant="secondary" onClick={() => setRetryVersion((v) => v + 1)}>
      {t("redesign.retry")}
    </Button>
  );
  const missing = (
    <EmptyState
      title={t("redesign.unavailable")}
      description={t("redesign.unavailableHelp")}
      action={retry}
    />
  );
  const staleNotice = (key: SectionKey) =>
    unavailable(key) && hasLoaded(key) ? (
      <p className="dashboard-stale" role="status">
        {t("sectionStale")}
      </p>
    ) : null;

  if (initialLoading) return <DashboardSkeleton label={t("loading")} />;

  return (
    <div className="customer-page ds-stack" data-page="dashboard">
      <PageHeader
        eyebrow={t("eyebrow")}
        title={t("title")}
        description={t("subtitle")}
        primaryAction={
          <ButtonLink href="/dashboard/tenders" size="lg">
            {t("openExplorer")}
            <ArrowRight className="rtl-mirror" aria-hidden />
          </ButtonLink>
        }
        secondaryAction={
          <div className="dashboard-header-tools">
            <div className="dashboard-updated" role="status">
              <span>{t("lastUpdated")}</span>
              {lastUpdated ? (
                <time dateTime={lastUpdated}>
                  {formatDateTime(lastUpdated, locale)}
                </time>
              ) : (
                <span>{t("updatedUnavailable")}</span>
              )}
              {statusError && <span>{t("refreshStatusUnavailable")}</span>}
            </div>
            <SourceRefreshMenu foundation triggerLabel={t("refresh")} />
          </div>
        }
      />

      {state.failures.length > 0 && (
        <Alert
          tone={failedAll && state.loaded.length === 0 ? "danger" : "warning"}
          title={
            failedAll && state.loaded.length === 0
              ? t("redesign.failed")
              : t("partialData")
          }
          action={retry}
        >
          {t("redesign.unavailableHelp")}
        </Alert>
      )}

      {failedAll && state.loaded.length === 0 ? (
        missing
      ) : (
        <div className="dashboard-grid">
          <div className="dashboard-column dashboard-primary-column">
            <Surface className="dashboard-panel dashboard-active">
            <SectionHeader
              icon={<Target aria-hidden />}
              title={t("opportunitiesTitle")}
              description={t("opportunitiesHelp")}
              action={
                <ButtonLink
                  variant="ghost"
                  size="sm"
                  href="/dashboard/tenders?view=recommended"
                >
                  {t("viewAllActive")}
                  <ArrowRight className="rtl-mirror" aria-hidden />
                </ButtonLink>
              }
            />
            {staleNotice("opportunities")}
            {unavailable("opportunities") && !hasLoaded("opportunities") ? (
              missing
            ) : opportunities.length ? (
              <div
                className="dashboard-opportunities"
                data-opportunity-count={opportunities.length}
              >
                {opportunities.map(({ tender, recommendation, pursuit }) => (
                  <article
                    className="dashboard-opportunity"
                    key={tender.id}
                    data-tender-id={tender.id}
                  >
                    <SourceIdentity
                      source={tender.source_system}
                      name={
                        displayNameForSource(tender.source_system) ===
                        tender.source_system
                          ? (SOURCE_NAMES[tender.source_system] ??
                            tender.source_system)
                          : displayNameForSource(tender.source_system)
                      }
                    />
                    <div className="dashboard-opportunity-main">
                      <h3>
                        <BidiText>{tender.title}</BidiText>
                      </h3>
                      <p className="dashboard-opportunity-meta ds-muted">
                        <BidiText>
                          {tender.country || tender.region || t("unknown")}
                        </BidiText>
                        <span aria-hidden>·</span>
                        <TechnicalText>{tender.external_id}</TechnicalText>
                      </p>
                      {recommendation?.rationale_summary && (
                        <BidiText className="dashboard-opportunity-context ds-muted">
                          {recommendation.rationale_summary}
                        </BidiText>
                      )}
                      <div className="dashboard-opportunity-tags ds-muted">
                        {tender.category && (
                          <BidiText>{tender.category}</BidiText>
                        )}
                        {tender.sector && tender.sector !== tender.category && (
                          <BidiText>{tender.sector}</BidiText>
                        )}
                      </div>
                    </div>
                    <div className="dashboard-opportunity-side">
                      <div className="dashboard-opportunity-state">
                        <StatusBadge tone="success">
                          {t("openStatus")}
                        </StatusBadge>
                        <DashboardBookmarkButton
                          tenderId={tender.id}
                          pursuit={pursuit}
                          onChanged={(nextPursuit) =>
                            setState((current) => ({
                              ...current,
                              recommendations: current.recommendations.map(
                                (item) =>
                                  item.tender.id === tender.id
                                    ? { ...item, pursuit: nextPursuit }
                                    : item,
                              ),
                            }))
                          }
                        />
                      </div>
                      <div className="dashboard-deadline">
                        <span>{t("deadlineLabel")}</span>
                        {tender.deadline ? (
                          <>
                            <strong>
                              {formatPublishedDeadline(tender, locale, truthLabels)}
                            </strong>
                            <span>
                              {deadlineState(tender, now, t)}
                            </span>
                          </>
                        ) : (
                          <strong className="dashboard-deadline-unavailable">
                            {t("deadline.unavailable")}
                          </strong>
                        )}
                      </div>
                      <ButtonLink
                        variant="secondary"
                        size="sm"
                        href={`/dashboard/tenders/${tender.id}`}
                      >
                        {t("viewTender")}
                        <ArrowRight className="rtl-mirror" aria-hidden />
                      </ButtonLink>
                    </div>
                  </article>
                ))}
              </div>
            ) : (
              <EmptyState
                icon={<FileSearch aria-hidden />}
                title={t("noMatches")}
                description={t("broadenHelp")}
                action={
                  <ButtonLink variant="secondary" href="/dashboard/tenders">
                    {t("openExplorer")}
                  </ButtonLink>
                }
              />
            )}
            </Surface>

            <Surface className="dashboard-panel dashboard-attention">
              <SectionHeader
                icon={<AlertTriangle aria-hidden />}
                title={t("actionTitle")}
                description={t("actionHelp")}
              />
              {staleNotice("analyses")}
              {unavailable("analyses") && !hasLoaded("analyses") ? (
                missing
              ) : actionItems.length ? (
                <ul className="dashboard-action-list">
                  {actionItems.map((item) => (
                    <li className="dashboard-action" key={item.key}>
                      <span
                        className={`dashboard-action-icon dashboard-action-${item.tone}`}
                      >
                        <FileText aria-hidden />
                      </span>
                      <div>
                        <strong>{item.issue}</strong>
                        <BidiText className="ds-muted">{item.subject}</BidiText>
                      </div>
                      <time dateTime={item.date ?? undefined}>
                        {customerDate(item.date, locale, t)}
                      </time>
                      <ButtonLink variant="secondary" size="sm" href={item.href}>
                        {t("review")}
                        <ArrowRight className="rtl-mirror" aria-hidden />
                      </ButtonLink>
                    </li>
                  ))}
                </ul>
              ) : (
                <EmptyState
                  icon={<CheckCircle2 aria-hidden />}
                  title={t("noUrgent")}
                  description={t("noUrgentHelp")}
                />
              )}
            </Surface>

            <Surface className="dashboard-panel dashboard-analyses">
              <SectionHeader
                icon={<Clock3 aria-hidden />}
                title={t("analysesTitle")}
                description={t("analysesHelp")}
                action={
                  <ButtonLink
                    variant="ghost"
                    size="sm"
                    href="/dashboard/my-tenders"
                  >
                    {t("viewAllAnalyses")}
                    <ArrowRight className="rtl-mirror" aria-hidden />
                  </ButtonLink>
                }
              />
              {staleNotice("analyses")}
              {unavailable("analyses") && !hasLoaded("analyses") ? (
                missing
              ) : state.analyses.length ? (
                <ul className="dashboard-analysis-list">
                  {state.analyses.slice(0, 2).map(({ tender, analysis }) => (
                    <li key={analysis.analysis_id}>
                      <span className="dashboard-document-icon">
                        <FileText aria-hidden />
                      </span>
                      <BidiText>{tender.title}</BidiText>
                      <time dateTime={analysis.created_at ?? undefined}>
                        {customerDate(analysis.created_at, locale, t)}
                      </time>
                      <ButtonLink
                        variant="secondary"
                        size="sm"
                        href={`/dashboard/tenders/${tender.id}/compliance`}
                      >
                        {t("open")}
                        <ArrowRight className="rtl-mirror" aria-hidden />
                      </ButtonLink>
                    </li>
                  ))}
                </ul>
              ) : (
                <EmptyState
                  icon={<FileText aria-hidden />}
                  title={t("noAnalyses")}
                  description={t("noAnalysesHelp")}
                  action={
                    <ButtonLink variant="secondary" href="/dashboard/tenders">
                      {t("reviewTenders")}
                    </ButtonLink>
                  }
                />
              )}
            </Surface>
          </div>

          <div className="dashboard-column dashboard-support-column">
            <Surface className="dashboard-panel dashboard-readiness">
            <SectionHeader
              icon={<Database aria-hidden />}
              title={t("readinessTitle")}
              description={t("readinessHelp")}
            />
            {staleNotice("readiness")}
            {unavailable("readiness") && !hasLoaded("readiness") ? (
              missing
            ) : (
              <div className="dashboard-readiness-body">
                <Alert
                  tone={
                    readinessStats.missing ||
                    readinessStats.expired ||
                    readinessStats.expiringSoon
                      ? "warning"
                      : "success"
                  }
                  title={
                    readinessStats.missing
                      ? t("recordsMissing", {
                          count: readinessStats.missing,
                        })
                      : readinessStats.expired
                        ? t("recordsExpired", {
                            count: readinessStats.expired,
                          })
                        : readinessStats.expiringSoon
                          ? t("recordsExpiring", {
                              count: readinessStats.expiringSoon,
                            })
                          : t("readinessCurrent")
                  }
                >
                  {readinessStats.missing
                    ? t("addMissingRecords")
                    : t("readinessSummary", {
                        expired: readinessStats.expired,
                        expiring: readinessStats.expiringSoon,
                        missing: readinessStats.missing,
                      })}
                </Alert>
                <dl className="dashboard-readiness-metrics">
                  {[
                    [t("available"), readinessStats.available],
                    [t("missing"), readinessStats.missing],
                    [t("expired"), readinessStats.expired],
                    [t("expiringSoon"), readinessStats.expiringSoon],
                  ].map(([label, value]) => (
                    <div key={String(label)}>
                      <dt>{label}</dt>
                      <dd>{value}</dd>
                    </div>
                  ))}
                </dl>
                {readinessStats.missingTypes.length > 0 && (
                  <ul className="dashboard-missing-records">
                    {readinessStats.missingTypes.slice(0, 6).map((type) => (
                      <li key={type}>
                        <span className="dashboard-document-icon">
                          <FileText aria-hidden />
                        </span>
                        <BidiText>
                          {tReadiness(documentTypeMessageKey(type))}
                        </BidiText>
                        <Badge>{t("missing")}</Badge>
                      </li>
                    ))}
                  </ul>
                )}
                <ButtonLink
                  variant="secondary"
                  href="/dashboard/readiness-vault"
                >
                  {t("readinessVault")}
                  <ArrowRight className="rtl-mirror" aria-hidden />
                </ButtonLink>
              </div>
            )}
            </Surface>

            {unavailable("profile") && !hasLoaded("profile") ? (
              <Surface className="dashboard-panel dashboard-profile">
                {missing}
              </Surface>
            ) : profilePrompt ? (
              <Surface className="dashboard-profile" variant="subtle">
                {staleNotice("profile")}
                <Info aria-hidden />
                <div>
                  <h2>{t("profilePromptTitle")}</h2>
                  <p className="ds-muted">{t("profilePrompt.all")}</p>
                  <ButtonLink variant="ghost" href="/dashboard/settings">
                    {t("goToProfile")}
                    <ArrowRight className="rtl-mirror" aria-hidden />
                  </ButtonLink>
                </div>
              </Surface>
            ) : null}
          </div>
        </div>
      )}
    </div>
  );
}
