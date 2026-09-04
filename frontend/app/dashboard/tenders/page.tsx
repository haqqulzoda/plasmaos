"use client";

import Link from "next/link";
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
  AlertCircle,
  ChevronLeft,
  ChevronRight,
  Clock,
  FileText,
  Filter,
  Loader2,
  MapPin,
  Search,
  SlidersHorizontal,
  X,
} from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { PrepareBidButton } from "@/components/bid-preparation/PrepareBidButton";
import { SourceRefreshMenu } from "@/components/source-refresh/SourceRefreshMenu";
import { useSourceRefresh } from "@/components/source-refresh/SourceRefreshProvider";
import { EngagementWorkflowActions } from "@/components/tenders/EngagementWorkflowActions";
import { NewTenderBadge } from "@/components/tenders/NewTenderBadge";
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
  formatCurrency,
  formatDate,
  formatRelativeTime,
} from "@/i18n/formatters";
import type { CustomerSelectableLocale } from "@/i18n/locales";
import { localizeTaxonomyValue } from "@/i18n/taxonomy";
import { engagementStatusClasses } from "@/types/engagement";
import type {
  ExplorerItem,
  ExplorerResponse,
  ExplorerView,
} from "@/types/explorer";
import type { TenderStatus } from "@/types/tender";
import {
  documentStatusClasses,
  isTenderActionable,
  sourceBadgeClasses,
  tenderStatusClasses,
} from "@/types/tender";

const PAGE_SIZE = 25;
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
  const searchParams = useSearchParams();
  const searchString = searchParams.toString();
  const query = useMemo(
    () => parseExplorerQuery(new URLSearchParams(searchString)),
    [searchString],
  );
  const { catalog, catalogError, displayNameForSource, latestActivityBatch } =
    useSourceRefresh();
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

  return (
    <main className="mx-auto w-full max-w-[1600px] space-y-5 p-4 sm:p-6">
      <header className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">{t("title")}</h1>
          <p className="mt-1 text-sm text-zinc-400">{t("subtitle")}</p>
        </div>
        <SourceRefreshMenu />
      </header>
      {newArrival ? (
        <section
          role="status"
          aria-live="polite"
          className="flex flex-col gap-3 rounded-xl border border-cyan-500/30 bg-cyan-500/10 p-3 text-sm text-cyan-50 sm:flex-row sm:items-center sm:justify-between"
        >
          <p>
            <span className="font-semibold">
              {t("newArrivals", { count: newArrival.total_created })}
            </span>
            <span className="ml-2 text-cyan-100/70">{t("resultsStable")}</span>
          </p>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={showNewArrivals}
              className="rounded-lg bg-cyan-500 px-3 py-1.5 text-xs font-semibold text-cyan-950 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-200"
            >
              {t("show")}
            </button>
            <button
              type="button"
              onClick={() => setDismissedBatchId(newArrival.id)}
              aria-label={t("dismissNew")}
              className="rounded p-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-200"
            >
              <X className="h-4 w-4" aria-hidden="true" />
            </button>
          </div>
        </section>
      ) : null}

      <div
        role="tablist"
        aria-label={t("viewsLabel")}
        className="flex max-w-full overflow-x-auto rounded-xl border border-zinc-800 bg-zinc-950 p-1"
      >
        {modes.map(([value, label, count]) => (
          <button
            key={value}
            role="tab"
            type="button"
            aria-selected={query.view === value}
            onClick={() => navigate({ view: value, sort: defaultSort(value) })}
            className={`min-w-fit flex-1 rounded-lg px-4 py-2.5 text-sm font-semibold focus-visible:ring-2 focus-visible:ring-indigo-400 ${query.view === value ? "bg-indigo-600 text-white" : "text-zinc-400 hover:bg-zinc-900"}`}
          >
            {label}{" "}
            <span
              className="ml-1 tabular-nums"
              aria-label={t("itemCount", { count })}
            >
              {count}
            </span>
          </button>
        ))}
      </div>

      <section
        aria-label={t("filtersLabel")}
        className="space-y-3 rounded-xl border border-zinc-800 bg-zinc-950/70 p-4"
      >
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
          <label className="relative xl:col-span-2">
            <span className="sr-only">{t("search")}</span>
            <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-zinc-500" />
            <input
              value={searchDraft}
              onChange={(event) => setSearchDraft(event.target.value)}
              placeholder={t("search")}
              className="w-full rounded-lg border border-zinc-700 bg-zinc-900 py-2 pl-9 pr-3 text-sm text-white focus:border-indigo-400"
            />
          </label>
          <select
            aria-label={t("source")}
            value={query.source}
            disabled={Boolean(catalogError)}
            onChange={(event) => navigate({ source: event.target.value })}
            className="rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-white disabled:opacity-60"
          >
            <option value="">{t("allSources")}</option>
            {query.source &&
            !catalog.some((source) => source.source_system === query.source) ? (
              <option value={query.source}>{query.source}</option>
            ) : null}
            {catalog.map((source) => (
              <option key={source.source_system} value={source.source_system}>
                {source.display_name}
              </option>
            ))}
          </select>
          <select
            aria-label={t("lifecycle")}
            value={query.lifecycleStatus}
            onChange={(event) =>
              navigate({
                lifecycleStatus: event.target.value as TenderStatus | "ALL",
              })
            }
            className="rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-white"
          >
            {statuses.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
          <select
            aria-label={t("sort")}
            value={query.sort}
            onChange={(event) => navigate({ sort: event.target.value })}
            className="rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-white"
          >
            {(query.view === "all" ? tenderSorts : recommendationSorts).map(
              ([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ),
            )}
          </select>
        </div>
        <button
          type="button"
          aria-pressed={query.newOnly}
          onClick={() => navigate({ newOnly: !query.newOnly })}
          title={t("newRecent")}
          className={`inline-flex rounded-full border px-3 py-1.5 text-xs font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300 ${query.newOnly ? "border-cyan-400 bg-cyan-400/10 text-cyan-200" : "border-zinc-700 text-zinc-300"}`}
        >
          {t("newLast24")}
        </button>
        <details>
          <summary className="flex w-fit cursor-pointer list-none items-center gap-2 rounded px-2 py-1 text-sm font-semibold text-zinc-300 focus-visible:ring-2 focus-visible:ring-indigo-400">
            <SlidersHorizontal className="h-4 w-4" />
            {t("moreFilters")}
          </summary>
          <div className="mt-3 space-y-4 border-t border-zinc-800 pt-4">
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <select
                aria-label={t("deadlineFilter")}
                value={query.deadlineStatus}
                onChange={(event) =>
                  navigate({ deadlineStatus: event.target.value })
                }
                className="rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-white"
              >
                <option value="">{t("deadlineAny")}</option>
                <option value="active">{t("deadlineActive")}</option>
                <option value="expired">{t("deadlineExpired")}</option>
                <option value="unknown">{t("deadlineUnknown")}</option>
              </select>
              <select
                aria-label={t("documentStatus")}
                value={query.documentStatus}
                onChange={(event) =>
                  navigate({ documentStatus: event.target.value })
                }
                className="rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-white"
              >
                {documents.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
              <input
                aria-label={t("category")}
                value={categoryDraft}
                onChange={(event) => setCategoryDraft(event.target.value)}
                onBlur={commitDrafts}
                onKeyDown={(event) => {
                  if (event.key === "Enter") commitDrafts();
                }}
                placeholder={t("category")}
                className="rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-white"
              />
              <button
                type="button"
                aria-pressed={query.region === CENTRAL_ASIA_REGION}
                onClick={() =>
                  navigate({
                    region:
                      query.region === CENTRAL_ASIA_REGION
                        ? ""
                        : CENTRAL_ASIA_REGION,
                  })
                }
                className={`rounded-lg border px-3 py-2 text-sm ${query.region === CENTRAL_ASIA_REGION ? "border-indigo-400 text-indigo-200" : "border-zinc-700 text-zinc-300"}`}
              >
                {t("centralAsia")}
              </button>
              <input
                type="number"
                min="0"
                aria-label={t("minimumValue")}
                value={minimumDraft}
                onChange={(event) => setMinimumDraft(event.target.value)}
                onBlur={commitDrafts}
                onKeyDown={(event) => {
                  if (event.key === "Enter") commitDrafts();
                }}
                placeholder={t("minimumValue")}
                className="rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-white"
              />
              <input
                type="number"
                min="0"
                aria-label={t("maximumValue")}
                value={maximumDraft}
                onChange={(event) => setMaximumDraft(event.target.value)}
                onBlur={commitDrafts}
                onKeyDown={(event) => {
                  if (event.key === "Enter") commitDrafts();
                }}
                placeholder={t("maximumValue")}
                className="rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-white"
              />
            </div>
            <fieldset>
              <legend className="mb-2 text-xs font-semibold uppercase text-zinc-500">
                {t("countries")}
              </legend>
              <div className="flex flex-wrap gap-2">
                {CENTRAL_ASIA_COUNTRIES.map((country) => (
                  <button
                    key={country}
                    type="button"
                    aria-pressed={query.countries.includes(country)}
                    onClick={() => toggleList("countries", country)}
                    className={`rounded-full border px-3 py-1 text-xs ${query.countries.includes(country) ? "border-indigo-400 text-indigo-200" : "border-zinc-700 text-zinc-400"}`}
                  >
                    {localizeTaxonomyValue("country", country, tCommon)}
                  </button>
                ))}
              </div>
            </fieldset>
            <fieldset>
              <legend className="mb-2 text-xs font-semibold uppercase text-zinc-500">
                {t("services")}
              </legend>
              <div className="flex flex-wrap gap-2">
                {DEFAULT_SERVICE_OPTIONS.map((service) => (
                  <button
                    key={service.value}
                    type="button"
                    aria-pressed={query.services.includes(service.value)}
                    onClick={() => toggleList("services", service.value)}
                    className={`rounded-full border px-3 py-1 text-xs ${query.services.includes(service.value) ? "border-indigo-400 text-indigo-200" : "border-zinc-700 text-zinc-400"}`}
                  >
                    {localizeTaxonomyValue("service", service.value, tCommon)}
                  </button>
                ))}
              </div>
            </fieldset>
          </div>
        </details>
      </section>

      {mutationError ? (
        <div
          role="alert"
          className="flex items-center gap-2 rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-200"
        >
          <AlertCircle className="h-4 w-4" />
          {mutationError}
        </div>
      ) : null}
      {profileRequired && query.view !== "all" && !loading ? (
        <section className="rounded-xl border border-indigo-500/30 bg-indigo-500/10 p-8 text-center">
          <h2 className="text-lg font-semibold text-white">
            {t("profileTitle")}
          </h2>
          <p className="mt-2 text-sm text-zinc-300">{t("profileHelp")}</p>
          <Link
            href="/dashboard/settings"
            className="mt-4 inline-flex rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white"
          >
            {t("openProfile")}
          </Link>
        </section>
      ) : loading ? (
        <div
          role="status"
          aria-live="polite"
          className="flex min-h-52 items-center justify-center gap-3 rounded-xl border border-zinc-800 text-sm text-zinc-300"
        >
          <Loader2 className="h-5 w-5 animate-spin" />
          {t("loading")}
        </div>
      ) : error ? (
        <div
          role="alert"
          className="rounded-xl border border-red-500/30 bg-red-500/10 p-8 text-center"
        >
          <p className="text-sm text-red-200">{error}</p>
          <button
            type="button"
            onClick={() => setRefreshVersion((value) => value + 1)}
            className="mt-4 rounded-lg border border-red-400/40 px-4 py-2 text-sm text-red-100"
          >
            {t("retry")}
          </button>
        </div>
      ) : response && !response.items.length ? (
        <section className="rounded-xl border border-zinc-800 p-10 text-center">
          <Filter className="mx-auto h-7 w-7 text-zinc-500" />
          <h2 className="mt-3 text-base font-semibold text-white">
            {query.view === "all"
              ? t("empty.all")
              : query.view === "dismissed"
                ? t("empty.dismissed")
                : allDismissed
                  ? t("empty.active")
                  : t("empty.recommended")}
          </h2>
        </section>
      ) : response ? (
        <section aria-label={t("resultsLabel")} className="space-y-3">
          <p className="text-xs text-zinc-500">
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
              key={item.tender.id}
              item={item}
              sourceDisplayName={displayNameForSource(
                item.tender.source_system,
              )}
              clock={serverClock}
              monotonicNow={monotonicNow}
              pendingRecommendation={pendingRecommendation}
              onDismiss={(id) => void mutateRecommendation(id, false)}
              onRestore={(id) => void mutateRecommendation(id, true)}
              onRefresh={() => setRefreshVersion((value) => value + 1)}
              onOpen={(tenderId) =>
                writeExplorerReturnState({
                  explorerUrl: explorerHref,
                  tenderId,
                  scrollY: window.scrollY,
                  page: query.page,
                  createdAt: Date.now(),
                })
              }
            />
          ))}
          <nav
            aria-label={t("pagesLabel")}
            className="flex items-center justify-between rounded-xl border border-zinc-800 p-3"
          >
            <button
              type="button"
              disabled={query.page <= 1}
              onClick={() => navigate({ page: query.page - 1 }, false)}
              className="inline-flex items-center gap-1 rounded-lg border border-zinc-700 px-3 py-2 text-sm disabled:opacity-40"
            >
              <ChevronLeft className="h-4 w-4" />
              {t("previous")}
            </button>
            <span className="text-sm text-zinc-400">
              {t("page", { page: query.page, totalPages: lastPage })}
            </span>
            <button
              type="button"
              disabled={query.page >= lastPage}
              onClick={() => navigate({ page: query.page + 1 }, false)}
              className="inline-flex items-center gap-1 rounded-lg border border-zinc-700 px-3 py-2 text-sm disabled:opacity-40"
            >
              {t("next")}
              <ChevronRight className="h-4 w-4" />
            </button>
          </nav>
        </section>
      ) : null}
    </main>
  );
}

function ExplorerCard({
  item,
  sourceDisplayName,
  clock,
  monotonicNow,
  pendingRecommendation,
  onDismiss,
  onRestore,
  onRefresh,
  onOpen,
}: {
  item: ExplorerItem;
  sourceDisplayName: string;
  clock: ServerClockReference | null;
  monotonicNow: number;
  pendingRecommendation: string | null;
  onDismiss: (id: string) => void;
  onRestore: (id: string) => void;
  onRefresh: () => void;
  onOpen: (tenderId: string) => void;
}) {
  const t = useTranslations("explorer");
  const tMy = useTranslations("myTenders");
  const locale = useLocale() as CustomerSelectableLocale;
  const [initialNow] = useState(() => Date.now());
  const { tender, recommendation, pursuit } = item;
  const actionable = isTenderActionable(tender.status);
  const expired = isExpiredDeadline(tender.deadline);
  const remember = () => onOpen(tender.id);
  const tenderStatus =
    tender.status === "OPEN"
      ? t("status.open")
      : tender.status === "CLOSED"
        ? t("status.closed")
        : tender.status === "CANCELLED"
          ? t("status.cancelled")
          : t("status.unknown");
  const documentStatus =
    tender.document_status === "documents_available"
      ? t("documents.ready")
      : tender.document_status === "files_missing"
        ? t("documents.preparationFailed")
        : tender.document_status === "metadata_only"
          ? t("documents.discovered")
          : tender.document_status === "access_required"
            ? t("documents.accessRequired")
            : tender.document_status === "processing"
              ? t("documents.processing")
              : tender.document_status === "failed"
                ? t("documents.failed")
                : t("documents.unavailable");
  const pursuitStatus = pursuit
    ? pursuit.status === "SAVED"
      ? tMy("statuses.saved")
      : pursuit.status === "EVALUATING"
        ? tMy("statuses.evaluating")
        : pursuit.status === "PREPARING"
          ? tMy("statuses.preparing")
          : pursuit.status === "SUBMITTED"
            ? tMy("statuses.submitted")
            : pursuit.status === "WON"
              ? tMy("statuses.won")
              : pursuit.status === "LOST"
                ? tMy("statuses.lost")
                : tMy("statuses.dismissed")
    : "";
  const deadline = tender.deadline
    ? formatRelativeTime(
        tender.deadline,
        clock ? adjustedServerNow(clock, monotonicNow) : initialNow,
        locale,
      )
    : t("deadlineMissing");
  const value =
    tender.budget > 0
      ? formatCurrency(tender.budget, tender.currency || "USD", locale, {
          maximumFractionDigits: 0,
        })
      : t("valueMissing");
  return (
    <article
      data-tender-id={tender.id}
      className="space-y-3 rounded-xl border border-zinc-800 bg-zinc-950/70 p-4"
    >
      <div className="grid gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(12rem,0.7fr)_minmax(13rem,auto)]">
        <div className="min-w-0">
          <div className="flex flex-wrap gap-2">
            <NewTenderBadge
              isNew={tender.is_new}
              newUntil={tender.new_until}
              clock={clock}
              monotonicNow={monotonicNow}
            />
            <span
              className={`rounded-md border px-2 py-1 text-[11px] font-semibold ${sourceBadgeClasses(tender.source_system)}`}
            >
              {sourceDisplayName}
            </span>
            <span
              className={`rounded-md border px-2 py-1 text-[11px] font-semibold ${tenderStatusClasses(tender.status)}`}
            >
              {t("sourceStatus", { status: tenderStatus })}
            </span>
            <span
              className={`rounded-md border px-2 py-1 text-[11px] font-semibold ${documentStatusClasses(tender.document_status)}`}
            >
              {t("documentCount", {
                status: documentStatus,
                count: tender.document_count,
              })}
            </span>
          </div>
          <Link
            onClick={remember}
            href={`/dashboard/tenders/${tender.id}`}
            className="mt-3 block text-base font-semibold text-white hover:text-indigo-300"
          >
            {tender.title}
          </Link>
          <p className="mt-1 text-xs text-zinc-500">
            {tender.buyer || t("buyerMissing")} · {tender.external_id}
          </p>
          <div className="mt-3 flex flex-wrap gap-4 text-xs text-zinc-400">
            <span className="inline-flex gap-1">
              <MapPin className="h-3.5 w-3.5" />
              {tender.country || tender.region || t("locationMissing")}
            </span>
            <span>
              {tender.sector || tender.category || t("uncategorized")}
            </span>
          </div>
        </div>
        <div className="space-y-2 text-sm">
          <p
            className={
              tender.budget > 0
                ? "font-semibold text-emerald-300"
                : "text-zinc-500"
            }
          >
            {value}
          </p>
          <p
            className={`inline-flex gap-1.5 ${expired ? "text-zinc-500" : "text-zinc-300"}`}
          >
            <Clock className="h-3.5 w-3.5" />
            {deadline}
          </p>
          <p className="text-xs text-zinc-500">
            {formatDate(tender.deadline, locale)}
          </p>
          {pursuit ? (
            <span
              className={`inline-flex rounded-md border px-2 py-1 text-[11px] font-semibold ${engagementStatusClasses(pursuit.status)}`}
            >
              {t("pursuit", { status: pursuitStatus })}
            </span>
          ) : null}
        </div>
        <div className="flex flex-wrap gap-2 xl:justify-end">
          <Link
            onClick={remember}
            href={`/dashboard/tenders/${tender.id}`}
            className="inline-flex items-center gap-1 rounded-lg border border-zinc-700 px-3 py-2 text-xs font-semibold text-zinc-200"
          >
            <FileText className="h-3.5 w-3.5" />
            {t("viewTender")}
          </Link>
          {pursuit ? (
            <EngagementWorkflowActions
              engagement={{
                engagement_id: pursuit.engagement_id,
                engagement_status: pursuit.status,
                allowed_actions: pursuit.allowed_actions,
              }}
              tenderId={tender.id}
              onRefresh={onRefresh}
            />
          ) : (
            <PrepareBidButton
              tenderId={tender.id}
              disabled={!actionable || expired}
              title={
                !actionable
                  ? t("status.unknown")
                  : expired
                    ? t("deadlinePassed")
                    : t("startBid")
              }
            />
          )}
        </div>
      </div>
      {recommendation ? (
        <RecommendationSummary
          recommendation={recommendation}
          pending={pendingRecommendation === recommendation.recommendation_id}
          onDismiss={onDismiss}
          onRestore={onRestore}
        />
      ) : null}
    </article>
  );
}

export default function TendersPage() {
  return (
    <Suspense
      fallback={
        <div role="status" className="flex h-64 items-center justify-center">
          <Loader2 className="h-7 w-7 animate-spin text-indigo-500" />
        </div>
      }
    >
      <TendersPageContent />
    </Suspense>
  );
}
