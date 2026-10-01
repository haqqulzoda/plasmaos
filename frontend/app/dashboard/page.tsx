"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Image from "next/image";
import { useLocale, useTranslations } from "next-intl";
import {
  ArrowRight,
  Briefcase,
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
import { OpenWorkspaceButton } from "@/components/pursuits/OpenWorkspaceButton";
import { FactChips } from "@/components/tenders/FactChips";
import { expiryState, documentTypeMessageKey } from "@/lib/readiness";
import { activeOrganizations, pursuitWorkspaceHref } from "@/lib/openWorkspace";
import { pursuitDisplayTitle } from "@/lib/requirementsReview";
import {
  formatDate as formatLocaleDate,
  formatDateTime,
} from "@/i18n/formatters";
import type { CustomerSelectableLocale } from "@/i18n/locales";
import type { ExplorerItem, ExplorerTenderSummary } from "@/types/explorer";
import type { OrganizationSummary, Pursuit, PursuitListResponse } from "@/types/pursuit";
import { isTenderActionable } from "@/types/tender";

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

type SectionKey = "profile" | "readiness" | "opportunities" | "pursuits";

/** "Your pursuits" needs one organization; several must be chosen on the Pursuits page. */
type PursuitsState =
  | { kind: "list"; organizationId: string; items: Pursuit[]; total: number }
  | { kind: "choose" }
  | { kind: "none" };

type LoadState = {
  profile: CompanyProfile | null;
  readiness: ReadinessDocument[];
  recommendations: ExplorerItem[];
  pursuits: PursuitsState;
  failures: SectionKey[];
  loaded: SectionKey[];
};

const DASHBOARD_PURSUIT_LIMIT = 5;

async function fetchPursuits(): Promise<PursuitsState> {
  const organizations = activeOrganizations(
    (await api.get<OrganizationSummary[]>("/organizations")).data ?? [],
  );
  if (!organizations.length) return { kind: "none" };
  if (organizations.length > 1) return { kind: "choose" };
  const organizationId = organizations[0].organization_id;
  const response = await api.get<PursuitListResponse>("/pursuits", {
    params: { limit: DASHBOARD_PURSUIT_LIMIT, offset: 0 },
    headers: { "X-Organization-ID": organizationId },
  });
  return {
    kind: "list",
    organizationId,
    items: response.data.items ?? [],
    total: response.data.total ?? 0,
  };
}

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
  return (
    isTenderActionable(tender.status) &&
    (!tender.deadline || new Date(tender.deadline).getTime() >= Date.now())
  );
}

function deadlineState(
  deadline: string | null,
  now: number,
  t: DashboardTranslator,
) {
  if (!deadline) return t("deadline.unknown");
  const deadlineTime = new Date(deadline).getTime();
  if (!Number.isFinite(deadlineTime)) return t("deadline.unknown");
  const days = Math.ceil((deadlineTime - now) / (1000 * 60 * 60 * 24));
  if (days < 0) return t("deadline.expired");
  if (days === 0) return t("deadline.today");
  if (days === 1) return t("deadline.one");
  return t("deadline.many", { count: days });
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
          <Surface className="dashboard-pursuits dashboard-skeleton-panel">
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
  const translate = useTranslations("dashboard");
  const translateReadiness = useTranslations("readiness");
  const translatePursuits = useTranslations("pursuits");
  const t = translate as DashboardTranslator;
  const tReadiness = translateReadiness as DashboardTranslator;
  const tPursuits = translatePursuits as DashboardTranslator;
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
    pursuits: { kind: "none" },
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
      const [profileResult, readinessResult, opportunityResult, pursuitsResult] =
        await Promise.allSettled([
          api.get<CompanyProfile>("/users/me/company"),
          api.get<ReadinessDocument[]>("/vault/readiness"),
          listExplorer({
            view: "recommended",
            limit: 100,
            offset: 0,
            status: "OPEN",
            sort: "deadline_soonest",
          }),
          fetchPursuits(),
        ]);

      if (profileResult.status === "fulfilled") loaded.add("profile");
      else failures.add("profile");
      if (readinessResult.status === "fulfilled") loaded.add("readiness");
      else failures.add("readiness");
      if (opportunityResult.status === "fulfilled")
        loaded.add("opportunities");
      else failures.add("opportunities");

      if (pursuitsResult.status === "fulfilled") loaded.add("pursuits");
      else failures.add("pursuits");

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
          pursuits:
            pursuitsResult.status === "fulfilled"
              ? pursuitsResult.value
              : current.pursuits,
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
  const profilePrompt = profilePromptVariant(state.profile);
  const lastUpdated = useMemo(
    () => lastAuthoritativeRefresh(statusItems),
    [statusItems],
  );
  const unavailable = (key: SectionKey) => state.failures.includes(key);
  const hasLoaded = (key: SectionKey) => state.loaded.includes(key);
  const failedAll = (
    ["profile", "readiness", "opportunities", "pursuits"] as SectionKey[]
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
              description={t("matchesHelp")}
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
                {opportunities.map(({ tender, profile_match: profileMatch, pursuit }) => (
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
                      <FactChips tender={tender} profileMatch={profileMatch} now={now} />
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
                              {formatLocaleDate(tender.deadline, locale)}
                            </strong>
                            <span>
                              {deadlineState(tender.deadline, now, t)}
                            </span>
                          </>
                        ) : (
                          <strong className="dashboard-deadline-unavailable">
                            {t("deadline.unavailable")}
                          </strong>
                        )}
                      </div>
                      <OpenWorkspaceButton tenderId={tender.id} />
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

            <Surface className="dashboard-panel dashboard-pursuits" data-dashboard-pursuits>
              <SectionHeader
                icon={<Briefcase aria-hidden />}
                title={t("pursuitsTitle")}
                description={t("pursuitsHelp")}
                action={
                  <ButtonLink variant="ghost" size="sm" href="/dashboard/my-tenders">
                    {t("viewAllPursuits")}
                    <ArrowRight className="rtl-mirror" aria-hidden />
                  </ButtonLink>
                }
              />
              {staleNotice("pursuits")}
              {unavailable("pursuits") && !hasLoaded("pursuits") ? (
                missing
              ) : state.pursuits.kind === "choose" ? (
                <EmptyState
                  icon={<Briefcase aria-hidden />}
                  title={t("pursuitsChoose")}
                  description={t("pursuitsChooseHelp")}
                  action={
                    <ButtonLink variant="secondary" href="/dashboard/my-tenders">
                      {t("viewAllPursuits")}
                    </ButtonLink>
                  }
                />
              ) : state.pursuits.kind === "list" && state.pursuits.items.length ? (
                <ul className="dashboard-pursuit-list">
                  {state.pursuits.items.map((pursuit) => {
                    const deadline = pursuit.external_deadline ?? pursuit.source_deadline;
                    const organizationId = (state.pursuits as { organizationId: string }).organizationId;
                    return (
                      <li key={pursuit.pursuit_id} data-pursuit-id={pursuit.pursuit_id}>
                        <span className="dashboard-document-icon">
                          <FileText aria-hidden />
                        </span>
                        <div className="dashboard-pursuit-main">
                          <BidiText>
                            {pursuitDisplayTitle(pursuit, (date) => tPursuits("values.uploadedOn", { date: formatLocaleDate(date, locale) }))}
                          </BidiText>
                          <span className="ds-muted">
                            {tPursuits(`stages.${pursuit.stage}`)}
                            <span aria-hidden> · </span>
                            {deadline ? (
                              <time dateTime={deadline}>{formatLocaleDate(deadline, locale)}</time>
                            ) : (
                              t("pursuitNoDeadline")
                            )}
                          </span>
                        </div>
                        <ButtonLink
                          variant="secondary"
                          size="sm"
                          href={pursuitWorkspaceHref(pursuit.pursuit_id, organizationId)}
                        >
                          {t("openWorkspace")}
                          <ArrowRight className="rtl-mirror" aria-hidden />
                        </ButtonLink>
                      </li>
                    );
                  })}
                </ul>
              ) : (
                <EmptyState
                  icon={<Briefcase aria-hidden />}
                  title={t("pursuitsEmpty")}
                  description={t("pursuitsEmptyHelp")}
                  action={
                    <ButtonLink variant="secondary" href="/dashboard/tenders">
                      {t("openExplorer")}
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
                  href="/dashboard/settings"
                  data-company-link
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
