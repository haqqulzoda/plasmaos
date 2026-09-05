"use client";

import Link from "next/link";
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { AlertTriangle, CheckCircle2, Info, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { BidiText } from "@/components/i18n/BidiText";

import {
  ACTIVITY_DRAIN_PAGE_LIMIT,
  ACTIVE_REFRESH_POLL_MS,
  COMPLETION_GRACE_POLLS,
  INACTIVE_REFRESH_POLL_MS,
  MAX_SESSION_JOB_IDS,
  MAX_VISIBLE_NOTICES,
  NOTIFICATION_GROUP_MS,
  activityEventsWithoutDuplicates,
  isInvalidActivityCursorError,
  listSourceCatalog,
  listSourceRefreshActivity,
  listSourceRefreshStatus,
  nextPollDelay,
  notificationForEvents,
  requestSourceRefresh,
} from "@/lib/sourceRefresh";
import type {
  RefreshActivityBatch,
  RefreshNotice,
  SourceCatalogItem,
  SourceRefreshActivityEvent,
  SourceRefreshStatusItem,
} from "@/types/source-refresh";

const SESSION_KEY = "plasma-source-refresh-session-v1";

export function clearSourceRefreshSession(): void {
  if (typeof window !== "undefined") sessionStorage.removeItem(SESSION_KEY);
}

interface StoredRefreshSession {
  cursor: string;
  seen_job_ids: string[];
}

interface SourceRefreshContextValue {
  catalog: SourceCatalogItem[];
  catalogLoading: boolean;
  catalogError: string | null;
  statusItems: SourceRefreshStatusItem[];
  statusError: string | null;
  pendingSources: ReadonlySet<string>;
  activeSources: SourceRefreshStatusItem[];
  latestActivityBatch: RefreshActivityBatch | null;
  requestRefresh: (sourceSystem: string) => Promise<void>;
  retryCatalog: () => void;
  displayNameForSource: (sourceSystem: string) => string;
}

const SourceRefreshContext = createContext<SourceRefreshContextValue | null>(
  null,
);

function readStoredSession(): StoredRefreshSession | null {
  try {
    const parsed = JSON.parse(
      sessionStorage.getItem(SESSION_KEY) ?? "null",
    ) as unknown;
    if (!parsed || typeof parsed !== "object") return null;
    const candidate = parsed as Partial<StoredRefreshSession>;
    if (
      typeof candidate.cursor !== "string" ||
      !Array.isArray(candidate.seen_job_ids)
    )
      return null;
    if (!candidate.seen_job_ids.every((value) => typeof value === "string"))
      return null;
    return {
      cursor: candidate.cursor,
      seen_job_ids: candidate.seen_job_ids.slice(-MAX_SESSION_JOB_IDS),
    };
  } catch {
    return null;
  }
}

function noticeClasses(notice: RefreshNotice): string {
  if (notice.tone === "danger")
    return "border-red-500/40 bg-red-950/95 text-red-50";
  if (notice.tone === "warning")
    return "border-amber-500/40 bg-amber-950/95 text-amber-50";
  if (notice.tone === "success")
    return "border-emerald-500/40 bg-emerald-950/95 text-emerald-50";
  return "border-sky-500/40 bg-sky-950/95 text-sky-50";
}

function NoticeIcon({ notice }: { notice: RefreshNotice }) {
  if (notice.tone === "danger" || notice.tone === "warning") {
    return (
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
    );
  }
  if (notice.tone === "success") {
    return (
      <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
    );
  }
  return <Info className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />;
}

export function SourceRefreshProvider({
  enabled,
  children,
}: {
  enabled: boolean;
  children: ReactNode;
}) {
  const translateRefresh = useTranslations("refresh");
  const [catalog, setCatalog] = useState<SourceCatalogItem[]>([]);
  const [catalogLoading, setCatalogLoading] = useState(enabled);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [catalogRetry, setCatalogRetry] = useState(0);
  const [statusItems, setStatusItems] = useState<SourceRefreshStatusItem[]>([]);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [pendingSources, setPendingSources] = useState<Set<string>>(new Set());
  const [notices, setNotices] = useState<RefreshNotice[]>([]);
  const [latestActivityBatch, setLatestActivityBatch] =
    useState<RefreshActivityBatch | null>(null);

  const mountedRef = useRef(false);
  const cursorRef = useRef<string | null>(null);
  const seenJobIdsRef = useRef<Set<string>>(new Set());
  const terminalJobIdsRef = useRef<Set<string>>(new Set());
  const statusItemsRef = useRef<SourceRefreshStatusItem[]>([]);
  const pollTimerRef = useRef<number | null>(null);
  const aggregationTimerRef = useRef<number | null>(null);
  const aggregationQueueRef = useRef<SourceRefreshActivityEvent[]>([]);
  const inFlightRef = useRef(false);
  const wakePollRef = useRef<(() => void) | null>(null);
  const stateEpochRef = useRef(0);
  const batchIdRef = useRef(0);
  // Keep the active presentation locale fresh without changing the polling
  // effect identity (and therefore without resetting cursor/dedupe state).
  const translateRefreshRef = useRef(translateRefresh);
  translateRefreshRef.current = translateRefresh;

  const persistSession = useCallback(() => {
    if (!cursorRef.current) return;
    const seen = Array.from(seenJobIdsRef.current).slice(-MAX_SESSION_JOB_IDS);
    sessionStorage.setItem(
      SESSION_KEY,
      JSON.stringify({ cursor: cursorRef.current, seen_job_ids: seen }),
    );
  }, []);

  const addNotice = useCallback((notice: RefreshNotice) => {
    setNotices((current) =>
      [...current.filter((item) => item.id !== notice.id), notice].slice(
        -MAX_VISIBLE_NOTICES,
      ),
    );
  }, []);

  const dismissNotice = useCallback((id: string) => {
    setNotices((current) => current.filter((notice) => notice.id !== id));
  }, []);

  const applyStatus = useCallback((items: SourceRefreshStatusItem[]) => {
    const reconciled = items.map((item) =>
      item.active_job && terminalJobIdsRef.current.has(item.active_job.job_id)
        ? { ...item, active_job: null }
        : item,
    );
    statusItemsRef.current = reconciled;
    setStatusItems(reconciled);
    setStatusError(null);
  }, []);

  const enqueueEvents = useCallback(
    (events: SourceRefreshActivityEvent[]) => {
      if (!events.length) return;
      aggregationQueueRef.current.push(...events);
      if (aggregationTimerRef.current !== null) return;
      aggregationTimerRef.current = window.setTimeout(() => {
        aggregationTimerRef.current = null;
        const grouped = aggregationQueueRef.current.splice(0);
        if (!grouped.length || !mountedRef.current) return;
        const batchId = ++batchIdRef.current;
        const totalCreated = grouped.reduce(
          (sum, event) =>
            sum + (event.counts_authoritative ? event.created_count : 0),
          0,
        );
        setLatestActivityBatch({
          id: batchId,
          events: grouped,
          total_created: totalCreated,
        });
        addNotice(
          notificationForEvents(
            grouped,
            `activity-${batchId}-${grouped.at(-1)?.job_id ?? "terminal"}`,
            translateRefreshRef.current,
          ),
        );
      }, NOTIFICATION_GROUP_MS);
    },
    [addNotice],
  );

  const retryCatalog = useCallback(
    () => setCatalogRetry((value) => value + 1),
    [],
  );

  useEffect(() => {
    if (!enabled) {
      setCatalog([]);
      setStatusItems([]);
      statusItemsRef.current = [];
      setPendingSources(new Set());
      setNotices([]);
      setLatestActivityBatch(null);
      clearSourceRefreshSession();
      return;
    }
    const controller = new AbortController();
    setCatalogLoading(true);
    setCatalogError(null);
    void listSourceCatalog(controller.signal)
      .then(({ data }) => {
        if (!controller.signal.aborted) setCatalog(data);
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setCatalog([]);
          setCatalogError(translateRefreshRef.current("catalogUnavailable"));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setCatalogLoading(false);
      });
    return () => controller.abort();
  }, [catalogRetry, enabled]);

  useEffect(() => {
    if (!enabled) return;
    mountedRef.current = true;
    const stored = readStoredSession();
    cursorRef.current = stored?.cursor ?? null;
    seenJobIdsRef.current = new Set(stored?.seen_job_ids ?? []);
    terminalJobIdsRef.current = new Set();
    let gracePolls = 0;
    let previousActiveCount = 0;
    let failureCount = 0;
    let requestController: AbortController | null = null;

    const clearPollTimer = () => {
      if (pollTimerRef.current !== null)
        window.clearTimeout(pollTimerRef.current);
      pollTimerRef.current = null;
    };

    const saveCursor = (cursor: string) => {
      cursorRef.current = cursor;
      persistSession();
    };

    const schedule = (delay: number) => {
      clearPollTimer();
      if (!mountedRef.current || document.visibilityState === "hidden") return;
      pollTimerRef.current = window.setTimeout(() => void pollCycle(), delay);
    };

    const loadStatus = async (signal: AbortSignal): Promise<number | null> => {
      const requestEpoch = stateEpochRef.current;
      try {
        const { data } = await listSourceRefreshStatus(signal);
        if (!mountedRef.current || signal.aborted) return null;
        if (requestEpoch === stateEpochRef.current) applyStatus(data);
        const baseline = data[0]?.activity_cursor;
        if (!cursorRef.current && baseline) saveCursor(baseline);
        setStatusError(null);
        return data.filter(
          (item) =>
            item.active_job &&
            !terminalJobIdsRef.current.has(item.active_job.job_id),
        ).length;
      } catch {
        if (!signal.aborted && mountedRef.current)
          setStatusError(translateRefreshRef.current("statusUnavailable"));
        return null;
      }
    };

    const recoverCursor = async (signal: AbortSignal): Promise<void> => {
      try {
        const { data } = await listSourceRefreshStatus(signal);
        if (signal.aborted || !mountedRef.current) return;
        applyStatus(data);
        const baseline = data[0]?.activity_cursor;
        if (baseline) saveCursor(baseline);
      } catch {
        if (!signal.aborted && mountedRef.current)
          setStatusError(translateRefreshRef.current("statusUnavailable"));
      }
    };

    const drainActivity = async (
      signal: AbortSignal,
    ): Promise<{ events: SourceRefreshActivityEvent[]; more: boolean }> => {
      const accepted: SourceRefreshActivityEvent[] = [];
      let more = false;
      for (let page = 0; page < ACTIVITY_DRAIN_PAGE_LIMIT; page += 1) {
        const cursor = cursorRef.current;
        if (!cursor) break;
        try {
          const { data } = await listSourceRefreshActivity(cursor, signal);
          if (signal.aborted || !mountedRef.current) break;
          saveCursor(data.next_cursor);
          const unique = activityEventsWithoutDuplicates(
            data.events,
            seenJobIdsRef.current,
          );
          unique.forEach((event) =>
            terminalJobIdsRef.current.add(event.job_id),
          );
          accepted.push(...unique);
          more = data.has_more;
          if (!data.has_more) break;
        } catch (error: unknown) {
          if (isInvalidActivityCursorError(error)) {
            await recoverCursor(signal);
            return { events: accepted, more: false };
          }
          throw error;
        }
      }
      persistSession();
      return { events: accepted, more };
    };

    const pollCycle = async () => {
      if (
        !mountedRef.current ||
        inFlightRef.current ||
        document.visibilityState === "hidden"
      )
        return;
      inFlightRef.current = true;
      requestController = new AbortController();
      let activityFailed = false;
      try {
        const reportedActiveCount = await loadStatus(requestController.signal);
        let more = false;
        if (cursorRef.current) {
          try {
            const activity = await drainActivity(requestController.signal);
            more = activity.more;
            if (activity.events.length) {
              enqueueEvents(activity.events);
              applyStatus(statusItemsRef.current);
            }
          } catch {
            activityFailed = true;
          }
        }

        const activeCount = statusItemsRef.current.filter(
          (item) => item.active_job,
        ).length;
        if (previousActiveCount > 0 && activeCount === 0)
          gracePolls = COMPLETION_GRACE_POLLS;
        else if (activeCount > 0) gracePolls = COMPLETION_GRACE_POLLS;
        else if (gracePolls > 0) gracePolls -= 1;
        previousActiveCount = reportedActiveCount ?? activeCount;
        failureCount =
          activityFailed || reportedActiveCount === null ? failureCount + 1 : 0;
        schedule(
          more ? 0 : nextPollDelay(activeCount, gracePolls, failureCount),
        );
      } finally {
        inFlightRef.current = false;
      }
    };

    const wake = () => schedule(0);
    wakePollRef.current = wake;
    const onVisibility = () => {
      if (document.visibilityState === "visible") wake();
      else {
        clearPollTimer();
        requestController?.abort();
        inFlightRef.current = false;
      }
    };
    document.addEventListener("visibilitychange", onVisibility);

    void (async () => {
      requestController = new AbortController();
      const activeCount = await loadStatus(requestController.signal);
      previousActiveCount = activeCount ?? 0;
      if (stored?.cursor && cursorRef.current) {
        try {
          const activity = await drainActivity(requestController.signal);
          enqueueEvents(activity.events);
        } catch {
          failureCount = 1;
        }
      }
      schedule(
        nextPollDelay(
          previousActiveCount,
          previousActiveCount > 0 ? COMPLETION_GRACE_POLLS : 0,
          failureCount,
        ),
      );
    })();

    return () => {
      mountedRef.current = false;
      wakePollRef.current = null;
      document.removeEventListener("visibilitychange", onVisibility);
      clearPollTimer();
      requestController?.abort();
      inFlightRef.current = false;
      if (aggregationTimerRef.current !== null)
        window.clearTimeout(aggregationTimerRef.current);
      aggregationTimerRef.current = null;
      aggregationQueueRef.current = [];
    };
  }, [applyStatus, enabled, enqueueEvents, persistSession]);

  const requestRefresh = useCallback(
    async (sourceSystem: string) => {
      const source = catalog.find(
        (item) => item.source_system === sourceSystem,
      );
      if (!source?.can_refresh) return;
      setPendingSources((current) => new Set(current).add(sourceSystem));
      const requestEpoch = ++stateEpochRef.current;
      try {
        const { data } = await requestSourceRefresh(sourceSystem);
        const normalizedStatus = data.status.toLowerCase();
        if (
          (normalizedStatus === "queued" || normalizedStatus === "running") &&
          data.job_id
        ) {
          const active = {
            job_id: data.job_id,
            status: normalizedStatus,
            queued_at: data.created_at ?? new Date().toISOString(),
            started_at: data.started_at,
            heartbeat_at: data.heartbeat_at,
          } as const;
          const current = statusItemsRef.current;
          const existing = current.find(
            (item) => item.source_system === sourceSystem,
          );
          const next = existing
            ? current.map((item) =>
                item.source_system === sourceSystem
                  ? { ...item, active_job: active }
                  : item,
              )
            : current;
          applyStatus(next);
          addNotice({
            id: `request-${data.job_id}`,
            title: data.reused
              ? translateRefreshRef.current("alreadyStatus", {
                  source: data.display_name,
                  status:
                    normalizedStatus === "queued"
                      ? translateRefreshRef.current("queued")
                      : translateRefreshRef.current("refreshing"),
                })
              : normalizedStatus === "queued"
                ? translateRefreshRef.current("queuedNotice", {
                    source: data.display_name,
                  })
                : translateRefreshRef.current("startedNotice", {
                    source: data.display_name,
                  }),
            detail: null,
            tone: "info",
            href: null,
            action_label: null,
          });
        } else {
          addNotice({
            id: `request-${sourceSystem}-${requestEpoch}`,
            title: translateRefreshRef.current("alreadyCurrent", {
              source: data.display_name,
            }),
            detail: null,
            tone: "info",
            href: null,
            action_label: null,
          });
        }
        wakePollRef.current?.();
      } catch {
        addNotice({
          id: `request-error-${sourceSystem}-${requestEpoch}`,
          title: translateRefreshRef.current("requestFailed", {
            source: source.display_name,
          }),
          detail: translateRefreshRef.current("nothingChanged"),
          tone: "danger",
          href: null,
          action_label: null,
        });
      } finally {
        setPendingSources((current) => {
          const next = new Set(current);
          next.delete(sourceSystem);
          return next;
        });
      }
    },
    [addNotice, applyStatus, catalog],
  );

  const displayNameForSource = useCallback(
    (sourceSystem: string) =>
      catalog.find((item) => item.source_system === sourceSystem)
        ?.display_name ?? sourceSystem,
    [catalog],
  );

  const activeSources = useMemo(
    () => statusItems.filter((item) => item.active_job !== null),
    [statusItems],
  );
  const value = useMemo<SourceRefreshContextValue>(
    () => ({
      catalog,
      catalogLoading,
      catalogError,
      statusItems,
      statusError,
      pendingSources,
      activeSources,
      latestActivityBatch,
      requestRefresh,
      retryCatalog,
      displayNameForSource,
    }),
    [
      activeSources,
      catalog,
      catalogError,
      catalogLoading,
      displayNameForSource,
      latestActivityBatch,
      pendingSources,
      requestRefresh,
      retryCatalog,
      statusError,
      statusItems,
    ],
  );

  return (
    <SourceRefreshContext.Provider value={value}>
      {children}
      <section
        aria-label={translateRefresh("notifications")}
        aria-live="polite"
        aria-relevant="additions"
        className="pointer-events-none fixed inset-x-3 bottom-3 z-[100] flex flex-col items-end gap-2 sm:start-auto sm:end-5 sm:w-[25rem]"
      >
        {notices.map((notice) => (
          <article
            key={notice.id}
            role={notice.tone === "danger" ? "alert" : "status"}
            className={`pointer-events-auto w-full rounded-xl border p-4 shadow-2xl ${noticeClasses(notice)}`}
          >
            <div className="flex items-start gap-3">
              <NoticeIcon notice={notice} />
              <div className="min-w-0 flex-1">
                <BidiText className="block text-sm font-semibold">{notice.title}</BidiText>
                {notice.detail ? (
                  <BidiText className="mt-1 block text-xs opacity-80">{notice.detail}</BidiText>
                ) : null}
              </div>
              <button
                type="button"
                onClick={() => dismissNotice(notice.id)}
                aria-label={translateRefresh("dismiss")}
                className="rounded p-1 opacity-70 hover:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white"
              >
                <X className="h-4 w-4" aria-hidden="true" />
              </button>
            </div>
            {notice.href && notice.action_label ? (
              <Link
                href={notice.href}
                onClick={() => dismissNotice(notice.id)}
                className="mt-3 inline-flex rounded-lg border border-current/30 px-3 py-1.5 text-xs font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white"
              >
                {notice.action_label}
              </Link>
            ) : null}
          </article>
        ))}
      </section>
    </SourceRefreshContext.Provider>
  );
}

export function useSourceRefresh(): SourceRefreshContextValue {
  const context = useContext(SourceRefreshContext);
  if (!context)
    throw new Error(
      "useSourceRefresh must be used inside SourceRefreshProvider",
    );
  return context;
}

export function GlobalRefreshIndicator() {
  const t = useTranslations("refresh");
  const { activeSources, statusError } = useSourceRefresh();
  if (!activeSources.length && !statusError) return null;
  if (!activeSources.length)
    return (
      <span role="status" className="text-xs text-amber-300">
        {t("statusUnavailable")}
      </span>
    );
  const single = activeSources[0];
  const label =
    activeSources.length === 1
      ? single.active_job?.status === "queued"
        ? t("activeOneQueued", { source: single.display_name })
        : t("activeOneRunning", { source: single.display_name })
      : t("activeMany", { count: activeSources.length });
  return (
    <details className="relative">
      <summary
        role="status"
        aria-live="polite"
        className="flex cursor-pointer list-none items-center gap-2 rounded-lg border border-indigo-500/30 bg-indigo-500/10 px-3 py-2 text-xs font-semibold text-indigo-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400"
      >
        <span
          className="h-2 w-2 rounded-full bg-indigo-400 motion-safe:animate-pulse"
          aria-hidden="true"
        />
        {label}
      </summary>
      <div className="absolute end-0 z-40 mt-2 w-64 rounded-xl border border-zinc-700 bg-zinc-950 p-3 shadow-2xl">
        <p className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-zinc-500">
          {t("sourceRefreshes")}
        </p>
        {activeSources.map((item) => (
          <p key={item.source_system} className="py-1 text-xs text-zinc-200">
            <BidiText>{item.display_name}</BidiText> ·{" "}
            {item.active_job?.status === "queued"
              ? t("queued")
              : t("refreshing")}
          </p>
        ))}
      </div>
    </details>
  );
}

export const refreshPollingPolicy = {
  active_ms: ACTIVE_REFRESH_POLL_MS,
  inactive_ms: INACTIVE_REFRESH_POLL_MS,
  grace_polls: COMPLETION_GRACE_POLLS,
} as const;
