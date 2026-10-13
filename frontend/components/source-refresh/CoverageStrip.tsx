"use client";

import { useLocale, useTranslations } from "next-intl";

import { BidiText } from "@/components/i18n/BidiText";
import { useSourceRefresh } from "@/components/source-refresh/SourceRefreshProvider";

const DESCRIBED_SOURCES = ["world_bank", "ebrd", "giz", "uzex"] as const;
type DescribedSource = (typeof DESCRIBED_SOURCES)[number];
const isDescribed = (value: string): value is DescribedSource => (DESCRIBED_SOURCES as readonly string[]).includes(value);

/**
 * S1 coverage strip on Opportunities: which sources Plasma reads, the notice types it
 * lists from each, when each last refreshed successfully, and what is coming next.
 * Sources and refresh times come from the source registry (catalog + refresh status);
 * notice types are a fixed, translated description per source.
 */
export function CoverageStrip() {
  const t = useTranslations("explorer.coverage");
  const tTruth = useTranslations("common.tenderTruth");
  const locale = useLocale();
  const { catalog, catalogLoading, catalogError, statusItems } = useSourceRefresh();

  if (catalogLoading || catalogError || catalog.length === 0) return null;

  const statusBySource = new Map(statusItems.map((item) => [item.source_system, item]));
  const formatter = new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" });
  const formatTime = (value: string) => {
    const parsed = new Date(value);
    return Number.isNaN(parsed.valueOf()) ? null : formatter.format(parsed);
  };

  return (
    <section className="coverage-strip" aria-labelledby="coverage-strip-title" data-coverage-strip>
      <h2 id="coverage-strip-title" className="coverage-strip-title">{t("title")}</h2>
      <ul className="coverage-strip-list">
        {catalog.map((source) => {
          const status = statusBySource.get(source.source_system);
          const key = source.source_system;
          const lastSuccess = status?.last_success_at ? formatTime(status.last_success_at) : null;
          return (
            <li key={source.source_system} className="coverage-strip-item" data-coverage-source={source.source_system}>
              <strong><BidiText>{source.display_name}</BidiText></strong>
              {isDescribed(key) && <span className="coverage-strip-types">{t(`types.${key}`)}</span>}
              <span className="coverage-strip-refresh" data-coverage-refreshed={lastSuccess ? "true" : "false"}>
                {lastSuccess ? t("lastRefresh", { time: lastSuccess }) : t("noRefreshYet")}
                {status?.last_success_partial && <> · {tTruth("sourcePartial")}</>}
                {status?.stale && <> · {tTruth("sourceStale")}</>}
              </span>
            </li>
          );
        })}
        <li className="coverage-strip-item coverage-strip-coming" data-coverage-source="adb-consulting">
          <strong>{t("adbConsulting")}</strong>
          <span className="coverage-strip-refresh">{t("coming")}</span>
        </li>
      </ul>
    </section>
  );
}
