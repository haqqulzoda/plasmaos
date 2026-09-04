"use client";

import { AlertCircle, Loader2, RefreshCw } from "lucide-react";
import { useTranslations } from "next-intl";

import { useSourceRefresh } from "@/components/source-refresh/SourceRefreshProvider";

export function SourceRefreshMenu() {
  const t = useTranslations("refresh");
  const {
    catalog,
    catalogLoading,
    catalogError,
    pendingSources,
    requestRefresh,
    retryCatalog,
    statusItems,
  } = useSourceRefresh();

  const statusBySource = new Map(
    statusItems.map((item) => [item.source_system, item]),
  );

  return (
    <details className="relative w-fit">
      <summary className="inline-flex cursor-pointer list-none items-center gap-2 rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm font-semibold text-zinc-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400">
        <RefreshCw className="h-4 w-4" aria-hidden="true" />
        {t("sourceRefresh")}
      </summary>
      <div className="absolute right-0 z-40 mt-2 w-[min(19rem,calc(100vw-2rem))] rounded-xl border border-zinc-700 bg-zinc-950 p-2 shadow-2xl">
        {catalogLoading ? (
          <p
            role="status"
            className="flex items-center gap-2 px-3 py-3 text-xs text-zinc-400"
          >
            <Loader2
              className="h-4 w-4 motion-safe:animate-spin"
              aria-hidden="true"
            />
            {t("loadingSources")}
          </p>
        ) : null}
        {!catalogLoading && catalogError ? (
          <div
            role="alert"
            className="space-y-2 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-100"
          >
            <p className="flex gap-2">
              <AlertCircle className="h-4 w-4 shrink-0" aria-hidden="true" />
              {catalogError}
            </p>
            <button
              type="button"
              onClick={retryCatalog}
              className="rounded border border-amber-400/40 px-2 py-1 font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-300"
            >
              {t("retry")}
            </button>
          </div>
        ) : null}
        {!catalogLoading && !catalogError && catalog.length === 0 ? (
          <p role="status" className="px-3 py-3 text-xs text-zinc-400">
            {t("noneAvailable")}
          </p>
        ) : null}
        {catalog.map((source) => {
          const item = statusBySource.get(source.source_system);
          const active = item?.active_job;
          const pending = pendingSources.has(source.source_system);
          const state = !source.can_refresh
            ? t("unavailable")
            : active?.status === "queued"
              ? t("queued")
              : active?.status === "running"
                ? t("refreshing")
                : t("refresh");
          return (
            <button
              key={source.source_system}
              type="button"
              disabled={!source.can_refresh || pending}
              onClick={() => void requestRefresh(source.source_system)}
              aria-label={t("actionLabel", {
                state,
                source: source.display_name,
              })}
              className="flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2.5 text-left text-xs text-zinc-200 hover:bg-zinc-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <span className="truncate font-medium">
                {source.display_name}
              </span>
              <span className="inline-flex shrink-0 items-center gap-1 text-zinc-400">
                {pending ? (
                  <Loader2
                    className="h-3.5 w-3.5 motion-safe:animate-spin"
                    aria-hidden="true"
                  />
                ) : null}
                {pending ? t("requesting") : state}
              </span>
            </button>
          );
        })}
      </div>
    </details>
  );
}
