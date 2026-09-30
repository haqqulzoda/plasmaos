"use client";

import {
  FormEvent,
  Suspense,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import {
  ArrowRight,
  Bookmark,
  Building2,
  CalendarDays,
  FolderKanban,
  MapPin,
  Globe2,
} from "lucide-react";
import { api } from "@/lib/api";
import { BidiText } from "@/components/i18n/BidiText";
import { formatBudget, formatPublishedDeadline, isClosedByDeadline } from "@/lib/tenderTruth";
import { useTenderTruthLabels } from "@/lib/useTenderTruthLabels";
import type { CustomerSelectableLocale } from "@/i18n/locales";
import { useSourceRefresh } from "@/components/source-refresh/SourceRefreshProvider";
import { EngagementWorkflowActions } from "@/components/tenders/EngagementWorkflowActions";
import type {
  MyTenderListItem,
  MyTendersListResponse,
} from "@/types/engagement";
import {
  EmptyState,
  PageHeader,
  PageSkeleton,
  Surface,
  StatusBadge,
} from "@/components/ui/Display";
import { Button, ButtonLink } from "@/components/ui/Button";
import { SearchField, Select } from "@/components/ui/Forms";
import { Tabs, Pagination } from "@/components/ui/Navigation";
import { Alert } from "@/components/ui/Feedback";

const PAGE_SIZE = 25;
const STATUS_FILTERS = [
  "ACTIVE",
  "ALL",
  "SAVED",
  "EVALUATING",
  "PREPARING",
  "SUBMITTED",
  "WON",
  "LOST",
  "DISMISSED",
] as const;

const SOURCE_STATUSES = ["", "OPEN", "CLOSED", "CANCELLED", "UNKNOWN"] as const;

function MyTenderCard({
  item,
  sourceDisplayName,
  onRefresh,
}: {
  item: MyTenderListItem;
  sourceDisplayName: string;
  onRefresh: () => void;
}) {
  const t = useTranslations("myTenders");
  const locale = useLocale() as CustomerSelectableLocale;
  const truthLabels = useTenderTruthLabels();
  const engagementLabel =
    item.engagement_status === "SAVED"
      ? t("statuses.saved")
      : item.engagement_status === "EVALUATING"
        ? t("statuses.evaluating")
        : item.engagement_status === "PREPARING"
          ? t("statuses.preparing")
          : item.engagement_status === "SUBMITTED"
            ? t("statuses.submitted")
            : item.engagement_status === "WON"
              ? t("statuses.won")
              : item.engagement_status === "LOST"
                ? t("statuses.lost")
                : t("statuses.dismissed");
  const truth = { ...item, status: item.tender_status };
  const tenderLabel = isClosedByDeadline(truth)
    ? truthLabels.closedDeadlinePassed
    : item.tender_status === "OPEN"
      ? t("tenderStatuses.open")
      : item.tender_status === "CLOSED"
        ? t("tenderStatuses.closed")
        : item.tender_status === "CANCELLED"
          ? t("tenderStatuses.cancelled")
          : t("tenderStatuses.unknown");
  const deadline = item.deadline
    ? formatPublishedDeadline(truth, locale, truthLabels)
    : t("deadlineMissing");
  const value = formatBudget(item.estimated_value, item.currency, locale, truthLabels.notPublished, {
    maximumFractionDigits: 2,
  });
  const copy = useTranslations("myTenders.redesign");
  return (
    <Surface
      className="pipeline-row"
      role="article"
      aria-label={item.tender_title}
      data-engagement-id={item.engagement_id}
    >
      <div className="pipeline-source" aria-hidden>
        <Globe2 />
      </div>
      <div className="pipeline-summary ds-stack">
        <div className="ds-row" aria-label={t("statusesLabel")}>
          <StatusBadge
            tone={
              item.engagement_status === "WON"
                ? "success"
                : item.engagement_status === "LOST"
                  ? "danger"
                  : item.engagement_status === "EVALUATING"
                    ? "warning"
                    : item.engagement_status === "DISMISSED"
                      ? "neutral"
                      : "info"
            }
          >
            {t("engagement", { status: engagementLabel })}
          </StatusBadge>
          <StatusBadge
            tone={item.tender_status === "OPEN" ? "success" : "neutral"}
          >
            {t("tender", { status: tenderLabel })}
          </StatusBadge>
          <span className="ds-muted ds-text-small">
            <BidiText>{sourceDisplayName}</BidiText>
          </span>
        </div>
        <h2>
          <BidiText>{item.tender_title}</BidiText>
        </h2>
        <div className="ds-row ds-muted ds-text-small">
          <Building2 aria-hidden />
          <BidiText>{item.buyer || t("buyerMissing")}</BidiText>
          {(item.country || item.region) && (
            <>
              <MapPin aria-hidden />
              <BidiText>
                {[item.country, item.region].filter(Boolean).join(" · ")}
              </BidiText>
            </>
          )}
        </div>
        {item.project_external_id && (
          <div className="ds-row ds-muted ds-text-small">
            <FolderKanban aria-hidden />
            <BidiText>
              {t("project", {
                project: item.project_name || item.project_external_id,
              })}
            </BidiText>
          </div>
        )}
      </div>
      <dl className="pipeline-facts">
        <div>
          <dt>
            <CalendarDays aria-hidden />
            {copy("deadline")}
          </dt>
          <dd>{deadline}</dd>
        </div>
        <div>
          <dt>{copy("estimatedValue")}</dt>
          <dd className="ds-numeric">{value}</dd>
        </div>
        <div>
          <dt>{copy("matchScore")}</dt>
          <dd className="ds-muted">{copy("unavailable")}</dd>
        </div>
      </dl>
      <div className="pipeline-actions">
        <ButtonLink
          variant="secondary"
          size="sm"
          href={`/dashboard/tenders/${item.tender_id}`}
        >
          {t("openTender")}
          <ArrowRight className="rtl-mirror" aria-hidden />
        </ButtonLink>
        <EngagementWorkflowActions
          foundation
          menuActions
          engagement={item}
          tenderId={item.tender_id}
          onRefresh={onRefresh}
        />
      </div>
    </Surface>
  );
}

function MyTendersContent() {
  const t = useTranslations("myTenders");
  const copy = useTranslations("myTenders.redesign");
  const { catalog, catalogError, displayNameForSource } = useSourceRefresh();
  const router = useRouter();
  const searchParams = useSearchParams();
  const searchString = searchParams.toString();
  const status = searchParams.get("status") || "ACTIVE";
  const source = searchParams.get("source") || "";
  const tenderStatus = searchParams.get("tender_status") || "";
  const sort = searchParams.get("sort") || "recently_updated";
  const page = Math.max(1, Number(searchParams.get("page") || "1") || 1);
  const search = searchParams.get("search") || "";
  const [searchDraft, setSearchDraft] = useState(search);
  const [data, setData] = useState<MyTendersListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshVersion, setRefreshVersion] = useState(0);
  const hasLoadedRef = useRef(false);

  const updateQuery = (updates: Record<string, string>) => {
    const next = new URLSearchParams(searchString);
    Object.entries(updates).forEach(([key, value]) => {
      if (
        value &&
        !(key === "status" && value === "ACTIVE") &&
        !(key === "page" && value === "1")
      ) {
        next.set(key, value);
      } else {
        next.delete(key);
      }
    });
    router.push(`/dashboard/my-tenders${next.size ? `?${next}` : ""}`);
  };

  useEffect(() => {
    setSearchDraft(search);
  }, [search]);

  useEffect(() => {
    let cancelled = false;
    if (!hasLoadedRef.current) setLoading(true);
    setError(null);
    api
      .get<MyTendersListResponse>("/my-tenders", {
        params: {
          status,
          source: source || undefined,
          tender_status: tenderStatus || undefined,
          search: search || undefined,
          sort,
          offset: (page - 1) * PAGE_SIZE,
          limit: PAGE_SIZE,
        },
      })
      .then((response) => {
        if (!cancelled) {
          setData(response.data);
          hasLoadedRef.current = true;
        }
      })
      .catch((requestError: { response?: { status?: number } }) => {
        if (cancelled) return;
        const code = requestError.response?.status;
        setError(code === 401 || code === 403 ? "accessDenied" : "loadFailed");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [page, refreshVersion, search, sort, source, status, tenderStatus]);

  const totalPages = Math.max(1, Math.ceil((data?.total ?? 0) / PAGE_SIZE));
  const countFor = useMemo(
    () => ({
      ACTIVE: data?.counts.active ?? 0,
      ALL: data?.counts.all ?? 0,
      SAVED: data?.counts.saved ?? 0,
      EVALUATING: data?.counts.evaluating ?? 0,
      PREPARING: data?.counts.preparing ?? 0,
      SUBMITTED: data?.counts.submitted ?? 0,
      WON: data?.counts.won ?? 0,
      LOST: data?.counts.lost ?? 0,
      DISMISSED: data?.counts.dismissed ?? 0,
    }),
    [data],
  );

  const submitSearch = (event: FormEvent) => {
    event.preventDefault();
    updateQuery({ search: searchDraft.trim(), page: "1" });
  };
  const engagementFilterLabel = (value: (typeof STATUS_FILTERS)[number]) =>
    value === "ACTIVE"
      ? t("statuses.active")
      : value === "ALL"
        ? t("statuses.all")
        : value === "SAVED"
          ? t("statuses.saved")
          : value === "EVALUATING"
            ? t("statuses.evaluating")
            : value === "PREPARING"
              ? t("statuses.preparing")
              : value === "SUBMITTED"
                ? t("statuses.submitted")
                : value === "WON"
                  ? t("statuses.won")
                  : value === "LOST"
                    ? t("statuses.lost")
                    : t("statuses.dismissed");
  const tenderFilterLabel = (value: (typeof SOURCE_STATUSES)[number]) =>
    value === ""
      ? t("tenderStatuses.all")
      : value === "OPEN"
        ? t("tenderStatuses.open")
        : value === "CLOSED"
          ? t("tenderStatuses.closed")
          : value === "CANCELLED"
            ? t("tenderStatuses.cancelled")
            : t("tenderStatuses.unknown");

  const filtered = Boolean(search || source || tenderStatus);
  const content = (
    <div className="ds-stack">
      <Surface className="pipeline-filters">
        <form onSubmit={submitSearch} className="pipeline-search">
          <SearchField
            id="my-tenders-search"
            label={t("searchLabel")}
            placeholder={t("searchLabel")}
            clearLabel={copy("clearSearch")}
            dir="auto"
            value={searchDraft}
            onValueChange={(value) => {
              setSearchDraft(value);
              if (!value) updateQuery({ search: "", page: "1" });
            }}
          />
          <Button type="submit" variant="secondary">
            {t("search")}
          </Button>
        </form>
        <Select
          id="my-tenders-source"
          label={t("source")}
          value={source}
          disabled={Boolean(catalogError)}
          onChange={(event) =>
            updateQuery({ source: event.target.value, page: "1" })
          }
        >
          <option value="">{t("allSources")}</option>
          {source && !catalog.some((item) => item.source_system === source) && (
            <option dir="auto" value={source}>
              {source}
            </option>
          )}
          {catalog.map((item) => (
            <option
              dir="auto"
              key={item.source_system}
              value={item.source_system}
            >
              {item.display_name}
            </option>
          ))}
        </Select>
        <Select
          id="my-tenders-source-status"
          label={t("sourceStatus")}
          value={tenderStatus}
          onChange={(event) =>
            updateQuery({ tender_status: event.target.value, page: "1" })
          }
        >
          {SOURCE_STATUSES.map((value) => (
            <option key={value} value={value}>
              {tenderFilterLabel(value)}
            </option>
          ))}
        </Select>
        <Select
          id="my-tenders-sort"
          label={t("sort")}
          value={sort}
          onChange={(event) =>
            updateQuery({ sort: event.target.value, page: "1" })
          }
        >
          <option value="recently_updated">{t("sortRecentUpdated")}</option>
          <option value="recently_added">{t("sortRecentAdded")}</option>
          <option value="deadline_soonest">{t("sortDeadline")}</option>
        </Select>
      </Surface>
      {loading ? (
        <PageSkeleton label={t("loading")} />
      ) : error ? (
        <Alert
          tone="danger"
          title={t(error === "accessDenied" ? "accessDenied" : "loadFailed")}
          action={
            <Button
              variant="secondary"
              onClick={() => setRefreshVersion((v) => v + 1)}
            >
              {copy("retry")}
            </Button>
          }
        />
      ) : !data?.items.length ? (
        <EmptyState
          icon={<Bookmark aria-hidden />}
          title={
            filtered
              ? copy("filteredEmpty")
              : data && data.counts.all > 0
                ? copy("statusEmpty")
                : t("emptyTitle")
          }
          description={filtered ? copy("filteredHelp") : t("emptyHelp")}
          action={
            <ButtonLink href="/dashboard/tenders">
              {t("explore")}
              <ArrowRight className="rtl-mirror" aria-hidden />
            </ButtonLink>
          }
        />
      ) : (
        <div className="ds-stack" aria-label={t("title")}>
          {data.items.map((item) => (
            <MyTenderCard
              key={item.engagement_id}
              item={item}
              sourceDisplayName={displayNameForSource(item.source_system)}
              onRefresh={() => setRefreshVersion((v) => v + 1)}
            />
          ))}
        </div>
      )}
      {!loading && !error && data && data.total > 0 && (
        <Pagination
          label={t("paginationLabel")}
          previousLabel={t("previous")}
          nextLabel={t("next")}
          hasPrevious={page > 1}
          hasNext={page < totalPages}
          onPrevious={() => updateQuery({ page: String(page - 1) })}
          onNext={() => updateQuery({ page: String(page + 1) })}
        >
          <span role="status">
            {t("page", { page, totalPages, count: data.total })}
          </span>
        </Pagination>
      )}
    </div>
  );
  return (
    <div className="customer-page ds-stack">
      <PageHeader
        eyebrow={copy("eyebrow")}
        title={t("title")}
        description={t("subtitle")}
        primaryAction={
          <ButtonLink href="/dashboard/tenders">
            {t("explore")}
            <ArrowRight className="rtl-mirror" aria-hidden />
          </ButtonLink>
        }
      />
      <Tabs
        label={t("filtersLabel")}
        value={status}
        onChange={(value) => updateQuery({ status: value, page: "1" })}
        items={STATUS_FILTERS.map((value) => ({
          value,
          label: (
            <>
              {engagementFilterLabel(value)}
              {data && !error && (
                <span className="ds-muted ds-text-small">
                  {countFor[value]}
                </span>
              )}
            </>
          ),
          content: value === status ? content : null,
        }))}
      />
      {!STATUS_FILTERS.some(value => value === status) && content}
    </div>
  );
}
export default function MyTendersPage() {
  return (
    <Suspense fallback={<PageSkeleton label="" />}>
      <MyTendersContent />
    </Suspense>
  );
}
