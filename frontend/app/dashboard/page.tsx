"use client";

import { useEffect, useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import Link from "next/link";
import {
  AlertTriangle,
  Archive,
  ArrowRight,
  CheckCircle2,
  ClipboardCheck,
  Clock,
  FileSearch,
  Radar,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";

import { Alert } from "@/components/ui/Feedback";
import { Button, ButtonLink } from "@/components/ui/Button";
import {
  Surface,
  SectionHeader,
  PageHeader,
  EmptyState,
  Metric,
  StatusBadge,
  PageSkeleton,
} from "@/components/ui/Display";
import { SourceRefreshMenu } from "@/components/source-refresh/SourceRefreshMenu";
import { listExplorer } from "@/lib/explorer";
import type { ExplorerItem, ExplorerTenderSummary } from "@/types/explorer";
import { api } from "@/lib/api";
import { useSourceRefresh } from "@/components/source-refresh/SourceRefreshProvider";
import { expiryState, documentTypeMessageKey } from "@/lib/readiness";
import { formatDate as formatLocaleDate } from "@/i18n/formatters";
import type { CustomerSelectableLocale } from "@/i18n/locales";
import { BidiText } from "@/components/i18n/BidiText";
import type { Tender } from "@/types/tender";
import { documentAggregateLabel, isTenderActionable } from "@/types/tender";
import type {
  DynamicEvaluation,
  DynamicRequirements,
  HybridCompliancePayload,
} from "@/types/compliance";

type CompanyProfile = {
  company_profile_id?: string | null;
  onboarding_required?: boolean;
  company_name?: string | null;
  target_regions?: string[] | null;
  target_countries?: string[] | null;
  target_services?: string[] | null;
  approval_status?: string | null;
  pilot_status?: string | null;
};

type ReadinessDocument = {
  id: string;
  document_type: string;
  document_name: string;
  expiry_date?: string | null;
  status: string;
  related_service?: string | null;
  updated_at?: string | null;
  created_at?: string | null;
};

type LatestAnalysis = {
  analysis_id: string | null;
  requirement_count?: number;
  manual_review_count?: number;
  requirements: DynamicRequirements | null;
  evaluation: DynamicEvaluation | null;
  hybrid_compliance?: HybridCompliancePayload | null;
  coverage_metadata?: Record<string, unknown> | null;
  analysis_status: string;
  extraction_error?: string | null;
  created_at?: string | null;
};

type AnalysisSummary = {
  tender: Tender;
  analysis: LatestAnalysis;
};

type LoadState = {
  profile: CompanyProfile | null;
  readiness: ReadinessDocument[];
  opportunities: ExplorerTenderSummary[];
  analyses: AnalysisSummary[];
  failures: string[];
  recommendations: ExplorerItem[];
};

type ActionItem = {
  key: string;
  issue: string;
  subject: string;
  status: string;
  href: string;
  tone: "danger" | "warning" | "review";
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

function customerDate(
  value: string | null | undefined,
  locale: CustomerSelectableLocale,
  t: DashboardTranslator,
) {
  return value ? formatLocaleDate(value, locale) : t("updatedUnavailable");
}

function deadlineState(deadline: string | null, t: DashboardTranslator) {
  if (!deadline) return t("deadline.unknown");
  const days = Math.ceil(
    (new Date(deadline).getTime() - Date.now()) / (1000 * 60 * 60 * 24),
  );
  if (days < 0) return t("deadline.expired");
  if (days === 0) return t("deadline.today");
  if (days === 1) return t("deadline.one");
  return t("deadline.many", { count: days });
}

function isCurrentTender(tender: ExplorerTenderSummary) {
  return (
    isTenderActionable(tender.status) &&
    (!tender.deadline || new Date(tender.deadline).getTime() >= Date.now())
  );
}

function analysisRequirementCount(analysis: LatestAnalysis) {
  if (typeof analysis.hybrid_compliance?.total_requirements === "number") {
    return analysis.hybrid_compliance.total_requirements;
  }
  if (typeof analysis.requirement_count === "number")
    return analysis.requirement_count;
  const mapped = analysis.requirements?.mapped_requirement_uuids?.length ?? 0;
  const unmapped =
    analysis.requirements?.unmapped_custom_requirements?.length ?? 0;
  return mapped + unmapped;
}

function coverageStatus(analysis: LatestAnalysis) {
  const coverage = analysis.coverage_metadata ?? {};
  const status = String(coverage.coverage_status ?? "");
  const sourceCoverage = coverage.source_document_coverage as
    | { coverage_status?: unknown }
    | undefined;
  if (status === "failed") return "Failed";
  if (status === "partial" || sourceCoverage?.coverage_status === "partial")
    return "Partial coverage";
  if (status === "complete") return "Complete coverage";
  return "Coverage recorded";
}

function cleanAnalysisStatus(analysis: LatestAnalysis) {
  if (analysis.analysis_status === "failed") return "Failed";
  if (coverageStatus(analysis) === "Partial coverage")
    return "Partial coverage";
  if (
    analysis.analysis_status === "needs_review" ||
    (analysis.manual_review_count ??
      analysis.hybrid_compliance?.manual_review_count ??
      0) > 0 ||
    (analysis.evaluation?.unmapped_requirements?.length ?? 0) > 0
  ) {
    return "Needs review";
  }
  return "Completed";
}

function analysisStatusMessageKey(status: string) {
  if (status === "Failed") return "status.failed";
  if (status === "Needs review") return "status.needsReview";
  if (status === "Partial coverage") return "status.partial";
  return "status.complete";
}

function documentAggregateMessageKey(label: string) {
  if (label === "Partial coverage") return "status.partial";
  if (label === "Ready for analysis") return "status.readyAnalysis";
  if (label === "Document discovered") return "status.documentDiscovered";
  if (label === "Preparation failed") return "status.preparationFailed";
  return "status.documentsUnavailable";
}

function isReadinessAvailable(document: ReadinessDocument) {
  return (
    document.status === "available" &&
    expiryState(document.expiry_date) !== "expired"
  );
}

function requiredMissingTypes(documents: ReadinessDocument[]) {
  return REQUIRED_READINESS_TYPES.filter(
    (type) =>
      !documents.some(
        (document) =>
          document.document_type === type && isReadinessAvailable(document),
      ),
  );
}

function buildActionItems(
  analyses: AnalysisSummary[],
  opportunities: ExplorerTenderSummary[],
  readiness: ReadinessDocument[],
  locale: CustomerSelectableLocale,
  t: DashboardTranslator,
  tReadiness: DashboardTranslator,
) {
  const items: ActionItem[] = [];

  analyses.forEach(({ tender, analysis }) => {
    const status = cleanAnalysisStatus(analysis);
    if (status === "Failed") {
      items.push({
        key: `analysis-failed-${analysis.analysis_id}`,
        issue: t("issues.analysisFailed"),
        subject: tender.title,
        status: t("status.failed"),
        href: `/dashboard/tenders/${tender.id}/compliance`,
        tone: "danger",
        priority: 1,
      });
    } else if (status === "Needs review") {
      items.push({
        key: `analysis-review-${analysis.analysis_id}`,
        issue: t("issues.manualReview"),
        subject: tender.title,
        status: t("status.reviewCount", {
          count: analysis.hybrid_compliance?.manual_review_count ?? 1,
        }),
        href: `/dashboard/tenders/${tender.id}/compliance`,
        tone: "review",
        priority: 2,
      });
    }
  });

  opportunities
    .filter((tender) =>
      ["partial", "files_missing", "metadata_only", "access_required"].includes(
        tender.document_status,
      ),
    )
    .slice(0, 3)
    .forEach((tender) => {
      items.push({
        key: `coverage-${tender.id}`,
        issue: t("issues.coverage"),
        subject: tender.title,
        status: t(documentAggregateMessageKey(documentAggregateLabel(tender))),
        href: `/dashboard/tenders/${tender.id}`,
        tone: "warning",
        priority: 3,
      });
    });

  readiness.forEach((document) => {
    const expiry = expiryState(document.expiry_date);
    if (document.status === "expired" || expiry === "expired") {
      items.push({
        key: `readiness-expired-${document.id}`,
        issue: t("issues.expired"),
        subject: document.document_name,
        status: customerDate(document.expiry_date, locale, t),
        href: "/dashboard/readiness-vault",
        tone: "danger",
        priority: 1,
      });
    } else if (expiry === "expiring_soon") {
      items.push({
        key: `readiness-soon-${document.id}`,
        issue: t("issues.expiring"),
        subject: document.document_name,
        status: customerDate(document.expiry_date, locale, t),
        href: "/dashboard/readiness-vault",
        tone: "warning",
        priority: 4,
      });
    }
  });

  requiredMissingTypes(readiness).forEach((type) => {
    items.push({
      key: `readiness-missing-${type}`,
      issue: t("issues.missing"),
      subject: tReadiness(documentTypeMessageKey(type)),
      status: t("status.requiredBid"),
      href: "/dashboard/readiness-vault",
      tone: "warning",
      priority: 5,
    });
  });

  return items.sort((a, b) => a.priority - b.priority).slice(0, 5);
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
  if (settled.some((result) => result.status === "rejected"))
    throw new Error("Analysis summaries unavailable");
  return settled
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
}

function isTestOnlyTender(tender: Pick<Tender, "title" | "external_id">) {
  const marker = `${tender.title} ${tender.external_id}`.toLowerCase();
  return (
    marker.includes("[test]") ||
    marker.includes("test-only") ||
    marker.startsWith("test ")
  );
}

export default function DashboardPage() {
  const locale = useLocale() as CustomerSelectableLocale;
  const translate = useTranslations("dashboard");
  const translateReadiness = useTranslations("readiness");
  const t = translate as DashboardTranslator;
  const tReadiness = translateReadiness as DashboardTranslator;
  const { displayNameForSource } = useSourceRefresh();
  const [state, setState] = useState<LoadState>({
    profile: null,
    readiness: [],
    opportunities: [],
    analyses: [],
    failures: [],
    recommendations: [],
  });
  const [loading, setLoading] = useState(true);
  const [retryVersion, setRetryVersion] = useState(0);
  const copy = useTranslations("dashboard.redesign");

  useEffect(() => {
    let mounted = true;

    const loadDashboard = async () => {
      setLoading(true);
      const failures: string[] = [];

      const profileResult = await api
        .get<CompanyProfile>("/users/me/company")
        .then((response) => response.data)
        .catch(() => {
          failures.push("profile");
          return null;
        });

      const [readinessResult, opportunityResult, analysisTenderResult] =
        await Promise.allSettled([
          api.get<ReadinessDocument[]>("/vault/readiness"),
          listExplorer({
            view: "recommended",
            limit: 8,
            offset: 0,
            status: "OPEN",
            sort: "best_match",
          }),
          api.get<Tender[]>("/tenders", {
            params: { limit: 24, sort: "newest" },
          }),
        ]);

      const readiness =
        readinessResult.status === "fulfilled"
          ? (readinessResult.value.data ?? [])
          : [];
      if (readinessResult.status === "rejected") failures.push("readiness");

      const opportunities =
        opportunityResult.status === "fulfilled"
          ? opportunityResult.value.data.items
              .map((item) => item.tender)
              .filter(
                (tender) =>
                  isCurrentTender(tender) && !isTestOnlyTender(tender),
              )
          : [];
      if (opportunityResult.status === "rejected")
        failures.push("opportunities");

      const analysisCandidates =
        analysisTenderResult.status === "fulfilled"
          ? (analysisTenderResult.value.data ?? []).filter(
              (tender) => !isTestOnlyTender(tender),
            )
          : [];
      if (analysisTenderResult.status === "rejected") failures.push("analyses");

      const analyses = await fetchLatestAnalyses(analysisCandidates).catch(
        () => {
          failures.push("analyses");
          return [];
        },
      );

      if (mounted) {
        setState({
          profile: profileResult,
          readiness,
          opportunities,
          analyses,
          failures,
          recommendations:
            opportunityResult.status === "fulfilled"
              ? opportunityResult.value.data.items
              : [],
        });
        setLoading(false);
      }
    };

    loadDashboard();

    return () => {
      mounted = false;
    };
  }, [retryVersion]);

  const readinessStats = useMemo(() => {
    const expired = state.readiness.filter(
      (document) =>
        document.status === "expired" ||
        expiryState(document.expiry_date) === "expired",
    );
    const expiringSoon = state.readiness.filter(
      (document) => expiryState(document.expiry_date) === "expiring_soon",
    );
    const missingTypes = requiredMissingTypes(state.readiness);
    const available = state.readiness.filter(isReadinessAvailable);
    const explicitlyMissing = state.readiness.filter(
      (document) => document.status === "missing",
    );
    return {
      available: available.length,
      missing: missingTypes.length + explicitlyMissing.length,
      expired: expired.length,
      expiringSoon: expiringSoon.length,
      missingTypes,
    };
  }, [state.readiness]);

  const actionItems = useMemo(
    () =>
      buildActionItems(
        state.analyses,
        state.opportunities,
        state.readiness,
        locale,
        t,
        tReadiness,
      ),
    [
      locale,
      state.analyses,
      state.opportunities,
      state.readiness,
      t,
      tReadiness,
    ],
  );

  const recentActivity = useMemo(() => {
    const analysisEvents = state.analyses
      .slice(0, 4)
      .map(({ tender, analysis }) => ({
        key: `analysis-${analysis.analysis_id}`,
        label:
          cleanAnalysisStatus(analysis) === "Completed"
            ? t("analysisCompleted")
            : t("analysisState", {
                status: t(
                  analysisStatusMessageKey(cleanAnalysisStatus(analysis)),
                ),
              }),
        subject: tender.title,
        when: analysis.created_at,
        href: `/dashboard/tenders/${tender.id}/compliance`,
      }));
    const readinessEvents = state.readiness
      .filter((document) => document.updated_at || document.created_at)
      .sort(
        (a, b) =>
          new Date(b.updated_at ?? b.created_at ?? 0).getTime() -
          new Date(a.updated_at ?? a.created_at ?? 0).getTime(),
      )
      .slice(0, 2)
      .map((document) => ({
        key: `readiness-${document.id}`,
        label: t("readinessUpdated"),
        subject: document.document_name,
        when: document.updated_at ?? document.created_at,
        href: "/dashboard/readiness-vault",
      }));
    return [...analysisEvents, ...readinessEvents]
      .sort(
        (a, b) =>
          new Date(b.when ?? 0).getTime() - new Date(a.when ?? 0).getTime(),
      )
      .slice(0, 6);
  }, [state.analyses, state.readiness, t]);

  const readinessTone =
    readinessStats.expired > 0
      ? "danger"
      : readinessStats.missing > 0 || readinessStats.expiringSoon > 0
        ? "warning"
        : "success";

  if (loading)
    return (
      <div className="customer-page">
        <PageSkeleton label={t("loading")} />
      </div>
    );
  const unavailable = (key: string) => state.failures.includes(key);
  const failedAll = ["profile", "readiness", "opportunities", "analyses"].every(
    unavailable,
  );
  const retry = (
    <Button variant="secondary" onClick={() => setRetryVersion((v) => v + 1)}>
      {copy("retry")}
    </Button>
  );
  const missing = (
    <EmptyState
      title={copy("unavailable")}
      description={copy("unavailableHelp")}
      action={retry}
    />
  );
  const setup =
    !unavailable("profile") &&
    (!state.profile?.company_profile_id ||
      state.profile.onboarding_required ||
      (!state.readiness.length && !state.analyses.length));
  return (
    <div className="customer-page ds-stack" data-page="dashboard">
      <PageHeader
        eyebrow={t("eyebrow")}
        title={t("title")}
        description={t("subtitle")}
        primaryAction={
          <ButtonLink href="/dashboard/tenders">
            {t("openExplorer")}
            <ArrowRight className="rtl-mirror" aria-hidden />
          </ButtonLink>
        }
        secondaryAction={<SourceRefreshMenu foundation />}
      />
      {state.failures.length > 0 && (
        <Alert
          tone={failedAll ? "danger" : "warning"}
          title={failedAll ? copy("failed") : t("partialData")}
          action={retry}
        >
          {copy("unavailableHelp")}
        </Alert>
      )}
      {failedAll ? (
        missing
      ) : (
        <>
          {setup && (
            <Surface className="dashboard-setup">
              <div className="ds-stack">
                <h2>{t("gettingStarted")}</h2>
                <p className="ds-muted">{copy("setupHelp")}</p>
                <ButtonLink href="/dashboard/settings">
                  {t("openProfile")}
                </ButtonLink>
              </div>
              <div className="dashboard-steps">
                {[
                  {
                    label: t("steps.profile"),
                    href: "/dashboard/settings",
                    done: Boolean(
                      state.profile?.company_profile_id &&
                        !state.profile.onboarding_required,
                    ),
                    Icon: ClipboardCheck,
                  },
                  {
                    label: t("steps.readiness"),
                    href: "/dashboard/readiness-vault",
                    done:
                      !unavailable("readiness") &&
                      readinessStats.available > 0 &&
                      readinessStats.missing === 0,
                    Icon: Archive,
                  },
                  {
                    label: t("steps.tenders"),
                    href: "/dashboard/tenders",
                    done: false,
                    Icon: Radar,
                  },
                  {
                    label: t("steps.analysis"),
                    href: "/dashboard/tenders",
                    done: !unavailable("analyses") && state.analyses.length > 0,
                    Icon: ShieldCheck,
                  },
                ].map(({ label, href, done, Icon }) => (
                  <Surface
                    variant="subtle"
                    className="dashboard-step"
                    key={href + label}
                  >
                    <Icon aria-hidden />
                    <strong>{label}</strong>
                    {done ? (
                      <StatusBadge tone="success">
                        {copy("complete")}
                      </StatusBadge>
                    ) : (
                      <ButtonLink variant="secondary" size="sm" href={href}>
                        {t("open")}
                      </ButtonLink>
                    )}
                  </Surface>
                ))}
              </div>
            </Surface>
          )}
          <div className="dashboard-primary">
            <Surface>
              <SectionHeader
                icon={<AlertTriangle aria-hidden />}
                title={t("actionTitle")}
                description={t("actionHelp")}
              />
              {unavailable("readiness") || unavailable("analyses") ? (
                missing
              ) : actionItems.length ? (
                actionItems.map((item) => (
                  <Link
                    prefetch={false}
                    className="dashboard-action"
                    key={item.key}
                    href={item.href}
                  >
                    <strong>{item.issue}</strong>
                    <BidiText className="ds-muted">{item.subject}</BidiText>
                    <div className="ds-row">
                      <StatusBadge
                        tone={item.tone === "review" ? "info" : item.tone}
                      >
                        {item.status}
                      </StatusBadge>
                      <span className="ds-link">{t("open")}</span>
                    </div>
                  </Link>
                ))
              ) : (
                <EmptyState
                  icon={<CheckCircle2 aria-hidden />}
                  title={t("noUrgent")}
                  description={t("noUrgentHelp")}
                />
              )}
            </Surface>
            <Surface>
              <SectionHeader
                icon={<Radar aria-hidden />}
                title={t("opportunitiesTitle")}
                description={copy("opportunitiesHelp")}
                action={
                  <ButtonLink
                    variant="ghost"
                    size="sm"
                    href="/dashboard/tenders?view=recommended"
                  >
                    {t("open")}
                  </ButtonLink>
                }
              />
              {unavailable("opportunities") ? (
                missing
              ) : state.recommendations.length ? (
                state.recommendations
                  .slice(0, 8)
                  .map(({ tender, recommendation }) => (
                    <Link
                      prefetch={false}
                      className="dashboard-opportunity"
                      key={tender.id}
                      href={`/dashboard/tenders/${tender.id}`}
                    >
                      <div className="ds-row ds-text-small ds-muted">
                        <BidiText>
                          {displayNameForSource(tender.source_system)}
                        </BidiText>
                        <BidiText>{tender.country || t("unknown")}</BidiText>
                      </div>
                      <h3>
                        <BidiText>{tender.title}</BidiText>
                      </h3>
                      {recommendation && (
                        <>
                          <p className="ds-text-small ds-muted">
                            <BidiText>
                              {recommendation.rationale_summary}
                            </BidiText>
                          </p>
                          <StatusBadge tone="accent">
                            {copy("match", {
                              score: recommendation.match_score,
                            })}
                          </StatusBadge>
                        </>
                      )}
                      <span className="ds-text-small ds-muted">
                        {deadlineState(tender.deadline, t)}
                      </span>
                    </Link>
                  ))
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
            <Surface>
              <SectionHeader
                icon={<Archive aria-hidden />}
                title={t("readinessTitle")}
                description={t("readinessHelp")}
              />
              {unavailable("readiness") ? (
                missing
              ) : (
                <div className="ds-pad ds-stack">
                  <Alert
                    tone={readinessTone}
                    title={
                      readinessTone === "danger"
                        ? t("readinessRisk")
                        : readinessTone === "warning"
                          ? t("readinessGaps")
                          : t("readinessCurrent")
                    }
                  >
                    {t("readinessSummary", {
                      expired: readinessStats.expired,
                      expiring: readinessStats.expiringSoon,
                      missing: readinessStats.missing,
                    })}
                  </Alert>
                  <div className="ds-grid-two">
                    {[
                      [t("available"), readinessStats.available],
                      [t("missing"), readinessStats.missing],
                      [t("expired"), readinessStats.expired],
                      [t("expiringSoon"), readinessStats.expiringSoon],
                    ].map(([label, value]) => (
                      <Metric key={String(label)} label={label} value={value} />
                    ))}
                  </div>
                  {readinessStats.missingTypes.length > 0 && (
                    <p className="ds-muted ds-text-small">
                      {t("missingList", {
                        items: readinessStats.missingTypes
                          .map((type) =>
                            tReadiness(documentTypeMessageKey(type)),
                          )
                          .join(", "),
                      })}
                    </p>
                  )}
                  <ButtonLink href="/dashboard/readiness-vault">
                    {t("readinessVault")}
                    <ArrowRight className="rtl-mirror" aria-hidden />
                  </ButtonLink>
                </div>
              )}
            </Surface>
          </div>
          <div className="dashboard-secondary">
            <Surface>
              <SectionHeader
                icon={<ShieldCheck aria-hidden />}
                title={t("analysesTitle")}
                description={t("analysesHelp")}
              />
              {unavailable("analyses") ? (
                missing
              ) : state.analyses.length ? (
                state.analyses.slice(0, 6).map(({ tender, analysis }) => {
                  const status = cleanAnalysisStatus(analysis);
                  return (
                    <Link
                      prefetch={false}
                      key={analysis.analysis_id}
                      href={`/dashboard/tenders/${tender.id}/compliance`}
                      className="dashboard-action"
                    >
                      <strong>
                        <BidiText>{tender.title}</BidiText>
                      </strong>
                      <div className="ds-row">
                        <StatusBadge
                          tone={
                            status === "Failed"
                              ? "danger"
                              : status === "Needs review" ||
                                  status === "Partial coverage"
                                ? "warning"
                                : "success"
                          }
                        >
                          {t(analysisStatusMessageKey(status))}
                        </StatusBadge>
                        <span className="ds-muted ds-text-small">
                          {t("requirementCount", {
                            count: analysisRequirementCount(analysis),
                          })}
                        </span>
                        <span className="ds-muted ds-text-small">
                          {customerDate(analysis.created_at, locale, t)}
                        </span>
                      </div>
                    </Link>
                  );
                })
              ) : (
                <EmptyState
                  icon={<ShieldAlert aria-hidden />}
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
            <Surface>
              <SectionHeader
                icon={<Clock aria-hidden />}
                title={t("activityTitle")}
                description={t("activityHelp")}
              />
              {unavailable("analyses") || unavailable("readiness") ? (
                missing
              ) : recentActivity.length ? (
                recentActivity.map((event) => (
                  <Link
                    prefetch={false}
                    key={event.key}
                    href={event.href}
                    className="dashboard-action"
                  >
                    <strong>{event.label}</strong>
                    <BidiText className="ds-muted">{event.subject}</BidiText>
                    <span className="ds-muted ds-text-small">
                      {customerDate(event.when, locale, t)}
                    </span>
                  </Link>
                ))
              ) : (
                <EmptyState
                  icon={<ClipboardCheck aria-hidden />}
                  title={t("noActivity")}
                  description={t("noActivityHelp")}
                />
              )}
            </Surface>
          </div>
        </>
      )}
    </div>
  );
}
