"use client";

import { useTranslations } from "next-intl";
import type { ServerClockReference } from "@/lib/tenderNewness";
import { shouldShowNewBadge } from "@/lib/tenderNewness";

export function NewTenderBadge({
  isNew,
  newUntil,
  clock,
  monotonicNow,
}: {
  isNew: boolean;
  newUntil: string;
  clock: ServerClockReference | null;
  monotonicNow: number;
}) {
  const t = useTranslations("explorer");
  if (!shouldShowNewBadge(isNew, newUntil, clock, monotonicNow)) return null;
  return (
    <span
      title={t("newRecent")}
      aria-label={`${t("new")}: ${t("newRecent")}`}
      className="inline-flex rounded-md border border-cyan-400/35 bg-cyan-400/10 px-2 py-1 text-[11px] font-semibold text-cyan-200"
    >
      {t("new")}
    </span>
  );
}
