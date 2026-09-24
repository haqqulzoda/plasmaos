"use client";

import Link from "next/link";
import Image from "next/image";
import { useRouter, useSearchParams } from "next/navigation";
import {
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  FileText,
  MapPin,
  SlidersHorizontal,
  X,
  Globe2,
  ExternalLink,
  ArrowRight,
  Landmark,
  Eye,
} from "lucide-react";
import { Button, ButtonLink } from "@/components/ui/Button";
import {
  Surface,
  PageHeader,
  EmptyState,
  Badge,
  PageSkeleton,
} from "@/components/ui/Display";
import { Input, Select, SearchField, Checkbox } from "@/components/ui/Forms";
import { Alert } from "@/components/ui/Feedback";
import { Tabs, Pagination } from "@/components/ui/Navigation";
import { Drawer } from "@/components/ui/Overlay";
import { DashboardBookmarkButton } from "@/components/customer/DashboardBookmarkButton";
import { useLocale, useTranslations } from "next-intl";

import { BidiText, TechnicalText } from "@/components/i18n/BidiText";
import { PrepareBidButton } from "@/components/bid-preparation/PrepareBidButton";
import { SourceRefreshMenu } from "@/components/source-refresh/SourceRefreshMenu";
import { useSourceRefresh } from "@/components/source-refresh/SourceRefreshProvider";
import { NewTenderBadge } from "@/components/tenders/NewTenderBadge";
import { EngagementWorkflowActions } from "@/components/tenders/EngagementWorkflowActions";
import { RecommendationSummary } from "@/components/tenders/RecommendationSummary";
import {
  dismissRecommendation,
  listExplorer,
  restoreRecommendation,
} from "@/lib/explorer";
import {
  clearExplorerReturnState,
  readExplorerReturnState,
  writeExplorerReturnState,
} from "@/lib/explorerReturnState";
import { CENTRAL_ASIA_COUNTRIES, CENTRAL_ASIA_REGION } from "@/lib/geography";
import { DEFAULT_SERVICE_OPTIONS } from "@/lib/services";
import {
  adjustedServerNow,
  createServerClockReference,
  nextBadgeTickDelay,
  type ServerClockReference,
} from "@/lib/tenderNewness";
import {
  INVALID_FORMAT_VALUE,
  formatCurrency,
  formatDate,
  formatRelativeTime,
} from "@/i18n/formatters";
import type { CustomerSelectableLocale } from "@/i18n/locales";
import { localizeTaxonomyValue } from "@/i18n/taxonomy";
import { safeSourceUrl } from "@/lib/sourceUrl";
import type {
  ExplorerItem,
  ExplorerResponse,
  ExplorerView,
  PursuitSummary,
} from "@/types/explorer";
import type { TenderStatus } from "@/types/tender";
import { isTenderActionable } from "@/types/tender";

const PAGE_SIZE = 25;
const SOURCE_LOGOS: Record<string, string> = {
  world_bank: "/brand/sources/world-bank-supplied.png",
  adb: "/brand/sources/adb.svg",
  giz: "/brand/sources/giz.svg",
  ebrd: "/brand/sources/ebrd-supplied.png",
  uzex: "/brand/sources/uzex.svg",
};

const LIFECYCLE_STATUSES: ReadonlyArray<TenderStatus | "ALL"> = [
  "OPEN",
  "UNKNOWN",
  "CLOSED",
  "CANCELLED",
  "ALL",
];
const DOCUMENT_VALUES = [
  "",
  "documents_available",
  "files_missing",
  "metadata_only",
  "access_required",
  "no_documents_found",
  "processing",
  "failed",
] as const;
const TENDER_SORT_VALUES = [
  "newest",
  "deadline_soonest",
  "highest_price",
  "document_availability",
  "source",
] as const;
const RECOMMENDATION_SORT_VALUES = [
  "best_match",
  ...TENDER_SORT_VALUES,
] as const;

interface ExplorerQueryState {
  view: ExplorerView;
  lifecycleStatus: TenderStatus | "ALL";
  source: string;
  region: string;
  countries: string[];
  services: string[];
  deadlineStatus: string;
  documentStatus: string;
  category: string;
  sort: string;
  priceMin: string;
  priceMax: string;
  keyword: string;
  newOnly: boolean;
  page: number;
}

const splitList = (value: string | null) =>
  value
    ? value
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean)
    : [];
const positiveInteger = (value: string | null) => {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
};
const defaultSort = (view: ExplorerView) =>
  view === "all" ? "newest" : "best_match";

export function parseExplorerQuery(
  params: URLSearchParams,
): ExplorerQueryState {
  const rawView = params.get("view");
  const view: ExplorerView =
    rawView === "recommended" || rawView === "dismissed" ? rawView : "all";
  const rawStatus = (params.get("status") || "OPEN").toUpperCase();
  const lifecycleStatus = LIFECYCLE_STATUSES.some(
    (value) => value === rawStatus,
  )
    ? (rawStatus as TenderStatus | "ALL")
    : "OPEN";
  const requestedSort = params.get("sort") || defaultSort(view);
  const availableSorts =
    view === "all" ? TENDER_SORT_VALUES : RECOMMENDATION_SORT_VALUES;
  const sort = availableSorts.some((value) => value === requestedSort)
    ? requestedSort
    : defaultSort(view);
  const cursorPage =
    Math.floor((positiveInteger(params.get("cursor")) ?? 0) / PAGE_SIZE) + 1;
  return {
    view,
    lifecycleStatus,
    source: params.get("source") || params.get("source_system") || "",
    region: params.get("region") || "",
    countries: splitList(params.get("countries") || params.get("country")),
    services: splitList(params.get("services") || params.get("service")),
    deadlineStatus: params.get("deadline_status") || "",
    documentStatus: params.get("document_status") || "",
    category: params.get("category") || "",
    sort,
    priceMin: params.get("price_min") || params.get("min_price") || "",
    priceMax: params.get("price_max") || params.get("max_price") || "",
    keyword: params.get("q") || params.get("search") || "",
    newOnly: params.get("new_only") === "true",
    page: positiveInteger(params.get("page")) ?? cursorPage,
  };
}

export function buildExplorerSearch(query: ExplorerQueryState): string {
  const params = new URLSearchParams({ view: query.view });
  if (query.lifecycleStatus !== "OPEN")
    params.set("status", query.lifecycleStatus.toLowerCase());
  if (query.source) params.set("source", query.source);
  if (query.region) params.set("region", query.region);
  if (query.countries.length)
    params.set("countries", query.countries.join(","));
  if (query.services.length) params.set("services", query.services.join(","));
  if (query.deadlineStatus) params.set("deadline_status", query.deadlineStatus);
  if (query.documentStatus) params.set("document_status", query.documentStatus);
  if (query.category.trim()) params.set("category", query.category.trim());
  if (query.priceMin.trim()) params.set("price_min", query.priceMin.trim());
  if (query.priceMax.trim()) params.set("price_max", query.priceMax.trim());
  if (query.keyword.trim()) params.set("q", query.keyword.trim());
  if (query.newOnly) params.set("new_only", "true");
  if (query.sort !== defaultSort(query.view)) params.set("sort", query.sort);
  if (query.page > 1) params.set("page", String(query.page));
  return params.toString();
}

const isExpiredDeadline = (value: string | null) =>
  Boolean(value && new Date(value).getTime() < Date.now());

function TendersPageContent() {
  const router = useRouter();
  const t = useTranslations("explorer");
  const tCommon = useTranslations("common");
  const tRefresh = useTranslations("refresh");
  const searchParams = useSearchParams();
  const searchString = searchParams.toString();
  const query = useMemo(
    () => parseExplorerQuery(new URLSearchParams(searchString)),
    [searchString],
  );
  const { catalog, catalogError, displayNameForSource, latestActivityBatch, statusItems } =
    useSourceRefresh();
  const copy = useTranslations("explorer.redesign");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [response, setResponse] = useState<ExplorerResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [mutationError, setMutationError] = useState<string | null>(null);
  const [pendingRecommendation, setPendingRecommendation] = useState<
    string | null
  >(null);
  const [refreshVersion, setRefreshVersion] = useState(0);
  const [searchDraft, setSearchDraft] = useState(query.keyword);
  const [categoryDraft, setCategoryDraft] = useState(query.category);
  const [minimumDraft, setMinimumDraft] = useState(query.priceMin);
  const [maximumDraft, setMaximumDraft] = useState(query.priceMax);
  const [serverClock, setServerClock] = useState<ServerClockReference | null>(
    null,
  );
  const [monotonicNow, setMonotonicNow] = useState(0);
  const [dismissedBatchId, setDismissedBatchId] = useState(0);
  const requestSequence = useRef(0);
  const explorerHref = useMemo(
    () => `/dashboard/tenders?${buildExplorerSearch(query)}`,
    [query],
  );

  const navigate = useCallback(
    (patch: Partial<ExplorerQueryState>, resetPage = true) => {
      const next = {
        ...query,
        ...patch,
        page: resetPage ? 1 : (patch.page ?? query.page),
      };
      clearExplorerReturnState();
      router.push(`/dashboard/tenders?${buildExplorerSearch(next)}`);
    },
    [query, router],
  );

  useEffect(() => {
    const canonical = buildExplorerSearch(query);
    if (canonical !== searchString)
      router.replace(`/dashboard/tenders?${canonical}`);
  }, [query, router, searchString]);
  useEffect(() => setSearchDraft(query.keyword), [query.keyword]);
  useEffect(() => setCategoryDraft(query.category), [query.category]);
  useEffect(() => setMinimumDraft(query.priceMin), [query.priceMin]);
  useEffect(() => setMaximumDraft(query.priceMax), [query.priceMax]);
  useEffect(() => {
    if (searchDraft === query.keyword) return;
    const timer = window.setTimeout(
      () => navigate({ keyword: searchDraft }),
      350,
    );
    return () => window.clearTimeout(timer);
  }, [navigate, query.keyword, searchDraft]);

  useEffect(() => {
    const controller = new AbortController();
    const sequence = ++requestSequence.current;
    setLoading(true);
    setError(null);
    void listExplorer(
      {
        view: query.view,
        limit: PAGE_SIZE,
        offset: (query.page - 1) * PAGE_SIZE,
        status: query.lifecycleStatus.toLowerCase(),
        source: query.source || undefined,
        q: query.keyword || undefined,
        region: query.region || undefined,
        countries: query.countries.length
          ? query.countries.join(",")
          : undefined,
        services: query.services.length ? query.services.join(",") : undefined,
        deadline_status: query.deadlineStatus || undefined,
        document_status: query.documentStatus || undefined,
        category: query.category || undefined,
        price_min: query.priceMin || undefined,
        price_max: query.priceMax || undefined,
        sort: query.sort,
        new_only: query.newOnly || undefined,
      },
      controller.signal,
    )
      .then(({ data }) => {
        if (sequence !== requestSequence.current) return;
        const finalPage = Math.max(1, Math.ceil(data.total / data.limit));
        if (query.page > finalPage) navigate({ page: finalPage }, false);
        else {
          const browserMonotonicMs = performance.now();
          setServerClock(
            createServerClockReference(data.server_time, browserMonotonicMs),
          );
          setMonotonicNow(browserMonotonicMs);
          setResponse(data);
        }
      })
      .catch((requestError: unknown) => {
        if (controller.signal.aborted || sequence !== requestSequence.current)
          return;
        const status = (requestError as { response?: { status?: number } })
          .response?.status;
        setError(
          status === 401 || status === 403
            ? t("accessDenied")
            : t("loadFailed"),
        );
      })
      .finally(() => {
        if (sequence === requestSequence.current && !controller.signal.aborted)
          setLoading(false);
      });
    return () => controller.abort();
  }, [navigate, query, refreshVersion, t]);

  useEffect(() => {
    if (!response || !serverClock) return;
    const newUntilValues = response.items
      .filter((item) => item.tender.is_new)
      .map((item) => item.tender.new_until);
    const timer = window.setTimeout(
      () => setMonotonicNow(performance.now()),
      nextBadgeTickDelay(newUntilValues, serverClock, monotonicNow),
    );
    return () => window.clearTimeout(timer);
  }, [monotonicNow, response, serverClock]);

  useEffect(() => {
    if (loading || !response) return;
    const restoreState = readExplorerReturnState();
    if (!restoreState || restoreState.explorerUrl !== explorerHref) return;
    const row = window.document.querySelector<HTMLElement>(
      `[data-tender-id="${CSS.escape(restoreState.tenderId)}"]`,
    );
    const frame = window.requestAnimationFrame(() => {
      if (row) row.scrollIntoView({ block: "center" });
      else window.scrollTo({ top: restoreState.scrollY, behavior: "auto" });
      clearExplorerReturnState();
    });
    return () => window.cancelAnimationFrame(frame);
  }, [explorerHref, loading, response]);

  const toggleList = (field: "countries" | "services", value: string) => {
    const current = query[field];
    navigate({
      [field]: current.includes(value)
        ? current.filter((item) => item !== value)
        : [...current, value],
    });
  };
  const commitDrafts = () =>
    navigate({
      category: categoryDraft,
      priceMin: minimumDraft,
      priceMax: maximumDraft,
    });
  const mutateRecommendation = async (id: string, restore: boolean) => {
    setPendingRecommendation(id);
    setMutationError(null);
    try {
      if (restore) await restoreRecommendation(id);
      else await dismissRecommendation(id);
      setRefreshVersion((value) => value + 1);
    } catch (requestError: unknown) {
      const status = (requestError as { response?: { status?: number } })
        .response?.status;
      setMutationError(
        status === 401 || status === 403
          ? t("recommendationDenied")
          : status === 404
            ? t("recommendationMissing")
            : t("recommendationFailed"),
      );
    } finally {
      setPendingRecommendation(null);
    }
  };
  const counts = response?.counts ?? {
    all_tenders: 0,
    active_recommendations: 0,
    dismissed_recommendations: 0,
  };
  const modes: Array<[ExplorerView, string, number]> = [
    ["all", t("views.all"), counts.all_tenders],
    ["recommended", t("views.recommended"), counts.active_recommendations],
    ["dismissed", t("views.dismissed"), counts.dismissed_recommendations],
  ];
  const statuses: ReadonlyArray<readonly [TenderStatus | "ALL", string]> = [
    ["OPEN", t("status.open")],
    ["UNKNOWN", t("status.unknown")],
    ["CLOSED", t("status.closed")],
    ["CANCELLED", t("status.cancelled")],
    ["ALL", t("status.all")],
  ];
  const documents = DOCUMENT_VALUES.map(
    (value) =>
      [
        value,
        value === ""
          ? t("documents.all")
          : value === "documents_available"
            ? t("documents.ready")
            : value === "files_missing"
              ? t("documents.preparationFailed")
              : value === "metadata_only"
                ? t("documents.discovered")
                : value === "access_required"
                  ? t("documents.accessRequired")
                  : value === "no_documents_found"
                    ? t("documents.unavailable")
                    : value === "processing"
                      ? t("documents.processing")
                      : t("documents.failed"),
      ] as const,
  );
  const tenderSorts = TENDER_SORT_VALUES.map(
    (value) =>
      [
        value,
        value === "newest"
          ? t("sorts.newest")
          : value === "deadline_soonest"
            ? t("sorts.deadline")
            : value === "highest_price"
              ? t("sorts.price")
              : value === "document_availability"
                ? t("sorts.documents")
                : t("sorts.source"),
      ] as const,
  );
  const recommendationSorts = [
    ["best_match", t("sorts.match")] as const,
    ...tenderSorts,
  ];
  const lastPage = response
    ? Math.max(1, Math.ceil(response.total / response.limit))
    : 1;
  const profileRequired =
    response?.recommendation_availability === "PROFILE_REQUIRED";
  const allDismissed =
    query.view === "recommended" &&
    counts.active_recommendations === 0 &&
    counts.dismissed_recommendations > 0;
  const newArrival =
    latestActivityBatch &&
    latestActivityBatch.id > dismissedBatchId &&
    latestActivityBatch.total_created > 0
      ? latestActivityBatch
      : null;
  const showNewArrivals = () => {
    if (!newArrival) return;
    const source =
      newArrival.events.length === 1 ? newArrival.events[0].source_system : "";
    setDismissedBatchId(newArrival.id);
    navigate({ newOnly: true, source });
  };

  const selected =
    response?.items.find((item) => item.tender.id === selectedId) ?? null;
  const remember = (tenderId: string) =>
    writeExplorerReturnState({
      explorerUrl: explorerHref,
      tenderId,
      scrollY: window.scrollY,
      page: query.page,
      createdAt: Date.now(),
    });
  const choose = (item: ExplorerItem) => {
    setSelectedId(item.tender.id);
    setPreviewOpen(true);
  };
  const degradedSources = statusItems.filter((item) =>
    ["partial", "failed", "source_unavailable"].includes(
      item.latest_terminal?.status ?? "",
    ) && (!query.source || item.source_system === query.source),
  );
  const chips: { key: string; label: string; clear: () => void }[] = [
    ...query.countries.map((v) => ({
      key: `country-${v}`,
      label: localizeTaxonomyValue("country", v, tCommon),
      clear: () => toggleList("countries", v),
    })),
    ...query.services.map((v) => ({
      key: `service-${v}`,
      label: localizeTaxonomyValue("service", v, tCommon),
      clear: () => toggleList("services", v),
    })),
    ...(
      [
        "source",
        "region",
        "deadlineStatus",
        "documentStatus",
        "category",
        "priceMin",
        "priceMax",
        "keyword",
      ] as const
    )
      .filter((key) => query[key])
      .map((key) => ({
        key,
        label: `${key === "region" ? copy("regionCountry") : t(({ source: "source", region: "centralAsia", deadlineStatus: "deadlineFilter", documentStatus: "documentStatus", category: "category", priceMin: "minimumValue", priceMax: "maximumValue", keyword: "search" } as const)[key])}: ${key === "source" ? displayNameForSource(query[key]) : key === "region" && query[key] === CENTRAL_ASIA_REGION ? t("centralAsia") : key === "deadlineStatus" ? t(query[key] === "active" ? "deadlineActive" : query[key] === "expired" ? "deadlineExpired" : "deadlineUnknown") : key === "documentStatus" ? documents.find(([value]) => value === query[key])?.[1] ?? query[key] : query[key]}`,
        clear: () => {
          if (key === "keyword") setSearchDraft("");
          if (key === "category") setCategoryDraft("");
          if (key === "priceMin") setMinimumDraft("");
          if (key === "priceMax") setMaximumDraft("");
          navigate({ [key]: "" });
        },
      })),
    ...(query.newOnly
      ? [
          {
            key: "new",
            label: t("newLast24"),
            clear: () => navigate({ newOnly: false }),
          },
        ]
      : []),
    {
      key: "status",
      label: `${copy("statusLabel")}: ${statuses.find(([v]) => v === query.lifecycleStatus)?.[1] ?? ""}`,
      clear: () => navigate({ lifecycleStatus: "ALL" }),
    },
  ];
  const preview = selected ? (
    <ExplorerPreview
      item={selected}
      source={displayNameForSource(selected.tender.source_system)}
      remember={remember}
      pending={pendingRecommendation}
      onDismiss={(id) => void mutateRecommendation(id, false)}
      onRestore={(id) => void mutateRecommendation(id, true)}
      onRefresh={() => setRefreshVersion((value) => value + 1)}
    />
  ) : (
    <EmptyState
      icon={<FileText aria-hidden />}
      title={copy("selectTitle")}
      description={copy("selectHelp")}
    />
  );
  return (
    <div className="customer-page ds-stack" data-page="explorer">
      <PageHeader
        eyebrow={copy("eyebrow")}
        title={t("title")}
        description={t("subtitle")}
        secondaryAction={<SourceRefreshMenu foundation triggerLabel={tRefresh("refresh")} />}
      />
      <div className="explorer-workspace">
        <div className="ds-stack">
          {newArrival && (
            <Alert
              tone="success"
              title={t("newArrivals", { count: newArrival.total_created })}
              onDismiss={() => setDismissedBatchId(newArrival.id)}
              dismissLabel={t("dismissNew")}
              action={
                <Button size="sm" onClick={showNewArrivals}>
                  {t("show")}
                </Button>
              }
            >
              {t("resultsStable")}
            </Alert>
          )}
          {profileRequired && !loading && (
            <Alert
              tone="warning"
              title={t("profileTitle")}
              action={
                <ButtonLink
                  variant="secondary"
                  size="sm"
                  href="/dashboard/settings"
                >
                  {t("openProfile")}
                </ButtonLink>
              }
            >
              {t("profileHelp")}
            </Alert>
          )}
          <Surface
            className="explorer-filters ds-stack"
            role="region"
            aria-label={t("filtersLabel")}
          >
            <SearchField
              label={t("search")}
              clearLabel={copy("clearSearch")}
              dir="auto"
              value={searchDraft}
              onValueChange={setSearchDraft}
              placeholder={copy("searchPlaceholder")}
            />
            <div className="explorer-filter-grid">
              <Select
                label={copy("sourceLabel")}
                value={query.source}
                disabled={Boolean(catalogError)}
                onChange={(e) => navigate({ source: e.target.value })}
              >
                <option value="">{t("allSources")}</option>
                {query.source &&
                  !catalog.some((s) => s.source_system === query.source) && (
                    <option dir="auto" value={query.source}>
                      {query.source}
                    </option>
                  )}
                {catalog.map((source) => (
                  <option
                    dir="auto"
                    key={source.source_system}
                    value={source.source_system}
                  >
                    {source.display_name}
                  </option>
                ))}
              </Select>
              <Select
                label={copy("regionCountry")}
                value={query.region}
                onChange={(e) => navigate({ region: e.target.value })}
              >
                <option value="">{copy("allRegions")}</option>
                <option value={CENTRAL_ASIA_REGION}>{t("centralAsia")}</option>
                {query.region && query.region !== CENTRAL_ASIA_REGION && <option dir="auto" value={query.region}>{query.region}</option>}
              </Select>
              <Select
                label={copy("statusLabel")}
                value={query.lifecycleStatus}
                onChange={(e) =>
                  navigate({
                    lifecycleStatus: e.target.value as TenderStatus | "ALL",
                  })
                }
              >
                {statuses.map(([v, l]) => (
                  <option key={v} value={v}>
                    {l}
                  </option>
                ))}
              </Select>
              <Input
                label={copy("categorySector")}
                dir="auto"
                value={categoryDraft}
                onChange={(e) => setCategoryDraft(e.target.value)}
                onBlur={commitDrafts}
                onKeyDown={(e) => {
                  if (e.key === "Enter") commitDrafts();
                }}
                placeholder={copy("allCategories")}
              />
              <Select
                label={t("deadlineFilter")}
                value={query.deadlineStatus}
                onChange={(e) => navigate({ deadlineStatus: e.target.value })}
              >
                <option value="">{t("deadlineAny")}</option>
                <option value="active">{t("deadlineActive")}</option>
                <option value="expired">{t("deadlineExpired")}</option>
                <option value="unknown">{t("deadlineUnknown")}</option>
              </Select>
            </div>
            <details className="explorer-more-filters">
              <summary className="ds-button ds-button-ghost ds-button-sm">
                <SlidersHorizontal aria-hidden />
                {t("moreFilters")}
              </summary>
              <div className="ds-stack ds-divider">
                <div className="explorer-filter-grid">
                  <Select
                    label={t("documentStatus")}
                    value={query.documentStatus}
                    onChange={(e) =>
                      navigate({ documentStatus: e.target.value })
                    }
                  >
                    {documents.map(([v, l]) => (
                      <option key={v} value={v}>
                        {l}
                      </option>
                    ))}
                  </Select>
                  <Input
                    label={t("minimumValue")}
                    type="number"
                    min="0"
                    value={minimumDraft}
                    onChange={(e) => setMinimumDraft(e.target.value)}
                    onBlur={commitDrafts}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") commitDrafts();
                    }}
                  />
                  <Input
                    label={t("maximumValue")}
                    type="number"
                    min="0"
                    value={maximumDraft}
                    onChange={(e) => setMaximumDraft(e.target.value)}
                    onBlur={commitDrafts}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") commitDrafts();
                    }}
                  />
                </div>
                <fieldset className="ds-stack">
                  <legend>{t("countries")}</legend>
                  <div className="ds-row">
                    {CENTRAL_ASIA_COUNTRIES.map((country) => (
                      <Checkbox
                        key={country}
                        label={localizeTaxonomyValue(
                          "country",
                          country,
                          tCommon,
                        )}
                        checked={query.countries.includes(country)}
                        onChange={() => toggleList("countries", country)}
                      />
                    ))}
                  </div>
                </fieldset>
                <fieldset className="ds-stack">
                  <legend>{t("services")}</legend>
                  <div className="ds-row">
                    {DEFAULT_SERVICE_OPTIONS.map((service) => (
                      <Checkbox
                        key={service.value}
                        label={localizeTaxonomyValue(
                          "service",
                          service.value,
                          tCommon,
                        )}
                        checked={query.services.includes(service.value)}
                        onChange={() => toggleList("services", service.value)}
                      />
                    ))}
                  </div>
                </fieldset>
              </div>
            </details>
          </Surface>
          <div className="explorer-view-row">
            <Tabs
              label={t("viewsLabel")}
              value={query.view}
              onChange={(value) =>
                navigate({
                  view: value as ExplorerView,
                  sort: defaultSort(value as ExplorerView),
                })
              }
              items={modes.map(([value, label, count]) => ({
                value,
                label: <>{label} <span className="ds-numeric">{response ? count : "—"}</span></>,
                content: null,
              }))}
            />
            <Checkbox
              label={t("newLast24")}
              checked={query.newOnly}
              onChange={() => navigate({ newOnly: !query.newOnly })}
            />
          </div>
          {chips.length > 0 && (
            <div className="explorer-active-filters" aria-label={copy("activeFilters")}>
              <span className="explorer-active-label">{copy("activeFilters")}:</span>
              {chips.map((chip) => (
                <Button
                  key={chip.key}
                  size="sm"
                  variant="secondary"
                  onClick={chip.clear}
                  aria-label={copy("removeFilter", { filter: chip.label })}
                >
                  <BidiText>{chip.label}</BidiText>
                  <X aria-hidden />
                </Button>
              ))}
              <Button
                variant="ghost"
                size="sm"
                onClick={() =>
                  {
                    setSearchDraft("");
                    setCategoryDraft("");
                    setMinimumDraft("");
                    setMaximumDraft("");
                    navigate({
                      ...parseExplorerQuery(new URLSearchParams()),
                      view: query.view,
                      sort: defaultSort(query.view),
                    });
                  }
                }
              >
                {copy("clearAll")}
              </Button>
            </div>
          )}
          {mutationError && <Alert tone="danger" title={mutationError} />}
          {degradedSources.length > 0 && (
            <Alert tone="warning" title={copy("partialTitle")}>
              {copy("partialHelp", { sources: degradedSources.map((source) => source.display_name).join(", ") })}
            </Alert>
          )}
          <Surface className="explorer-results-toolbar" role="group" aria-label={copy("resultsToolbar")}>
            <strong className="ds-numeric">
              {response ? copy("resultCount", { count: response.total }) : t("loading")}
            </strong>
            <div className="explorer-results-sort">
              <Select
                label={copy("sortBy")}
                value={query.sort}
                onChange={(e) => navigate({ sort: e.target.value })}
              >
                {(query.view === "all" ? tenderSorts : recommendationSorts).map(([v, l]) => (
                  <option key={v} value={v}>{l}</option>
                ))}
              </Select>
              {response && <span className="ds-muted ds-text-small">{t("page", { page: query.page, totalPages: lastPage })}</span>}
            </div>
          </Surface>
          {loading && !response ? (
            <ExplorerResultSkeleton label={t("loading")} />
          ) : error && !response ? (
            <Alert
              tone="danger"
              title={error}
              action={
                <Button
                  variant="secondary"
                  onClick={() => setRefreshVersion((v) => v + 1)}
                >
                  {t("retry")}
                </Button>
              }
            />
          ) : response && !response.items.length ? (
            <Surface>
              <EmptyState
                title={
                  query.view === "all"
                    ? t("empty.all")
                    : query.view === "dismissed"
                      ? t("empty.dismissed")
                      : allDismissed
                        ? t("empty.active")
                        : t("empty.recommended")
                }
                action={<Button variant="secondary" onClick={() => {
                  setSearchDraft("");
                  navigate({ ...parseExplorerQuery(new URLSearchParams()), view: query.view, sort: defaultSort(query.view) });
                }}>{copy("clearAll")}</Button>}
              />
            </Surface>
          ) : response ? (
            <section aria-label={t("resultsLabel")} className="explorer-results" aria-busy={loading}>
              {error && <Alert tone="danger" title={error} action={<Button variant="secondary" onClick={() => setRefreshVersion((v) => v + 1)}>{t("retry")}</Button>} />}
              <p className="ds-muted ds-text-small explorer-range">
                {t("showing", {
                  start: response.offset + 1,
                  end: Math.min(
                    response.offset + response.items.length,
                    response.total,
                  ),
                  total: response.total,
                })}
              </p>
              {response.items.map((item) => (
                <ExplorerCard
                  key={`${item.tender.id}:${item.pursuit?.status ?? "none"}`}
                  item={item}
                  selected={selectedId === item.tender.id}
                  sourceDisplayName={displayNameForSource(
                    item.tender.source_system,
                  )}
                  clock={serverClock}
                  monotonicNow={monotonicNow}
                  onRefresh={() => setRefreshVersion((v) => v + 1)}
                  onOpen={remember}
                  onPreview={() => choose(item)}
                />
              ))}
              <Pagination
                label={t("pagesLabel")}
                previousLabel={t("previous")}
                nextLabel={t("next")}
                hasPrevious={query.page > 1}
                hasNext={query.page < lastPage}
                onPrevious={() => navigate({ page: query.page - 1 }, false)}
                onNext={() => navigate({ page: query.page + 1 }, false)}
              >
                {t("page", { page: query.page, totalPages: lastPage })}
              </Pagination>
            </section>
          ) : null}
        </div>
      </div>
      <Drawer
        open={previewOpen && Boolean(selected)}
        onClose={() => setPreviewOpen(false)}
        title={copy("preview")}
        closeLabel={copy("closePreview")}
      >
        <div className="customer-page">{preview}</div>
      </Drawer>
    </div>
  );
}

function ExplorerCard({
  item,
  sourceDisplayName,
  clock,
  monotonicNow,
  onRefresh,
  onOpen,
  onPreview,
  selected,
}: {
  item: ExplorerItem;
  sourceDisplayName: string;
  clock: ServerClockReference | null;
  monotonicNow: number;
  onRefresh: () => void;
  onOpen: (id: string) => void;
  onPreview: () => void;
  selected: boolean;
}) {
  const t = useTranslations("explorer");
  const copy = useTranslations("explorer.redesign");
  const locale = useLocale() as CustomerSelectableLocale;
  const [initialNow] = useState(() => Date.now());
  const [pursuitState, setPursuitState] = useState<PursuitSummary | null>(item.pursuit);
  const { tender, recommendation } = item;
  const actionable = isTenderActionable(tender.status);
  const expired = isExpiredDeadline(tender.deadline);
  const status = t(
    `status.${tender.status === "OPEN" ? "open" : tender.status === "CLOSED" ? "closed" : tender.status === "CANCELLED" ? "cancelled" : "unknown"}`,
  );
  const sourceUrl = safeSourceUrl(tender.source_url);
  const tags = [...new Set([tender.sector, tender.category, tender.country, tender.region].filter((value): value is string => Boolean(value && value.trim())))].slice(0, 4);
  const formattedBudget = tender.budget > 0 && Number.isFinite(tender.budget)
    ? formatCurrency(
        tender.budget,
        tender.currency,
        locale,
        Number.isInteger(tender.budget) ? { maximumFractionDigits: 0 } : {},
      )
    : INVALID_FORMAT_VALUE;
  const budget = formattedBudget === INVALID_FORMAT_VALUE
    ? t("valueMissing")
    : formattedBudget;
  return (
    <Surface
      className="explorer-card"
      data-tender-id={tender.id}
      data-selected={selected}
    >
      <div className="explorer-card-source">
        <ExplorerSourceIdentity source={tender.source_system} name={sourceDisplayName} />
      </div>
      <div className="explorer-card-main">
        <div className="explorer-card-title-row"><h2><Link prefetch={false} onClick={() => onOpen(tender.id)} href={`/dashboard/tenders/${tender.id}`}><BidiText>{tender.title}</BidiText></Link></h2><NewTenderBadge foundation isNew={tender.is_new} newUntil={tender.new_until} clock={clock} monotonicNow={monotonicNow} /><Button variant="icon" size="sm" className="explorer-preview-control" aria-label={copy("preview")} aria-pressed={selected} onClick={onPreview}><Eye aria-hidden /></Button></div>
        <p className="explorer-card-reference"><MapPin aria-hidden /><BidiText>{tender.country || tender.region || t("locationMissing")}</BidiText><span aria-hidden>·</span><TechnicalText>{tender.external_id}</TechnicalText></p>
        {tags.length > 0 && <div className="explorer-card-tags">{tags.map((tag) => <span key={tag} className="explorer-card-tag"><BidiText>{tag}</BidiText></span>)}</div>}
      </div>
      <div className="explorer-card-facts">
        <span className="explorer-status" data-status={tender.status}>{status}</span>
        <div className="explorer-card-date">
          <span className="explorer-card-deadline-label">{t("deadlineFilter")}</span>
          <strong>{tender.deadline ? formatDate(tender.deadline, locale) : copy("deadlineUnavailable")}</strong>
          {tender.deadline && tender.status === "OPEN" && <span className="ds-muted ds-text-small">{formatRelativeTime(tender.deadline, clock ? adjustedServerNow(clock, monotonicNow) : initialNow, locale)}</span>}
        </div>
        <div className="explorer-card-budget">
          <span>{copy("budget")}</span>
          <strong><bdi>{budget}</bdi></strong>
        </div>
      </div>
      <div className="explorer-card-actions">
        <div className="explorer-card-action-top">
          {recommendation && <span className="explorer-match">{copy("match", { score: recommendation.match_score })}</span>}
          <span className="explorer-card-action-icons">
            <DashboardBookmarkButton tenderId={tender.id} pursuit={pursuitState} disabled={!actionable || expired} onChanged={(value) => { setPursuitState(value); onRefresh(); }} />
          </span>
        </div>
        <ButtonLink href={`/dashboard/tenders/${tender.id}`} onClick={() => onOpen(tender.id)} size="sm" className="explorer-view-tender">{t("viewTender")}<ArrowRight className="rtl-mirror" aria-hidden /></ButtonLink>
        {sourceUrl && <a className="ds-button ds-button-secondary ds-button-sm explorer-open-source" href={sourceUrl} target="_blank" rel="noopener noreferrer external" aria-label={copy("openSourceFor", { title: tender.title })}><ExternalLink aria-hidden />{copy("openSource")}</a>}
      </div>
    </Surface>
  );
}

function ExplorerSourceIdentity({ source, name }: { source: string; name: string }) {
  const [logoFailed, setLogoFailed] = useState(false);
  const logo = SOURCE_LOGOS[source];
  return <div className="explorer-source-identity">
    {logo && !logoFailed ? <span className="explorer-source-logo" data-source={source}><Image src={logo} alt={name} width={source === "world_bank" ? 3000 : source === "ebrd" ? 1140 : 68} height={source === "world_bank" ? 2000 : source === "ebrd" ? 1141 : 60} unoptimized onError={() => setLogoFailed(true)} data-source-logo="official" /></span> : <><span className="explorer-source-fallback" data-source-logo="fallback"><Landmark aria-hidden /></span><BidiText className="explorer-source-name">{name}</BidiText></>}
  </div>;
}

function ExplorerResultSkeleton({ label }: { label: string }) {
  return <div className="explorer-results-skeleton" role="status" aria-label={label}>{[0, 1, 2].map((index) => <Surface key={index} className="explorer-card explorer-card-skeleton"><span className="ds-skeleton" /><span className="ds-skeleton" /><span className="ds-skeleton" /><span className="ds-skeleton" /></Surface>)}</div>;
}

function ExplorerPreview({
  item,
  source,
  remember,
  pending,
  onDismiss,
  onRestore,
  onRefresh,
}: {
  item: ExplorerItem;
  source: string;
  remember: (id: string) => void;
  pending: string | null;
  onDismiss: (id: string) => void;
  onRestore: (id: string) => void;
  onRefresh: () => void;
}) {
  const t = useTranslations("explorer");
  const tMy = useTranslations("myTenders");
  const locale = useLocale() as CustomerSelectableLocale;
  const { tender, recommendation, pursuit } = item;
  return (
    <div className="explorer-preview">
      <Badge icon={<Globe2 aria-hidden />}>
        <BidiText>{source}</BidiText>
      </Badge>
      <h2>
        <BidiText>{tender.title}</BidiText>
      </h2>
      <TechnicalText>{tender.external_id}</TechnicalText>
      <dl>
        {[
          [t("source"), source],
          [
            t("countries"),
            tender.country || tender.region || t("locationMissing"),
          ],
          [
            t("category"),
            tender.sector || tender.category || t("uncategorized"),
          ],
          [t("deadlineFilter"), formatDate(tender.deadline, locale)],
          [
            t("redesign.value"),
            tender.budget > 0
              ? formatCurrency(tender.budget, tender.currency || "USD", locale)
              : t("valueMissing"),
          ],
        ].map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>
              <BidiText>{value}</BidiText>
            </dd>
          </div>
        ))}
      </dl>
      <ButtonLink
        href={`/dashboard/tenders/${tender.id}`}
        onClick={() => remember(tender.id)}
      >
        {t("viewTender")}
      </ButtonLink>
      {pursuit ? (
        <div className="ds-stack">
          <span className="ds-muted ds-text-small">{t("pursuit", { status: tMy(`statuses.${pursuit.status.toLowerCase() as "saved" | "evaluating" | "preparing" | "submitted" | "won" | "lost" | "dismissed"}`) })}</span>
          <EngagementWorkflowActions
            foundation
            engagement={{ engagement_id: pursuit.engagement_id, engagement_status: pursuit.status, allowed_actions: pursuit.allowed_actions }}
            tenderId={tender.id}
            onRefresh={onRefresh}
          />
        </div>
      ) : (
        <PrepareBidButton foundation tenderId={tender.id} disabled={!isTenderActionable(tender.status) || isExpiredDeadline(tender.deadline)} title={t("startBid")} />
      )}
      {recommendation && (
        <RecommendationSummary
          foundation
          recommendation={recommendation}
          pending={pending === recommendation.recommendation_id}
          onDismiss={onDismiss}
          onRestore={onRestore}
        />
      )}
    </div>
  );
}
export default function TendersPage() {
  const t = useTranslations("explorer");
  return (
    <Suspense fallback={<PageSkeleton label={t("loading")} />}>
      <TendersPageContent />
    </Suspense>
  );
}
