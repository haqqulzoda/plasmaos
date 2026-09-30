"use client";

import {useMemo} from "react";
import {useTranslations} from "next-intl";

import type {TenderTruthLabels} from "@/lib/tenderTruth";

/** Localized labels for lib/tenderTruth (common.tenderTruth, en/ru/uz/ar). */
export function useTenderTruthLabels(): TenderTruthLabels {
  const t = useTranslations("common.tenderTruth");
  return useMemo(
    () => ({
      notPublished: t("notPublished"),
      localTimeAsPublished: t("localTimeAsPublished"),
      zoneTimeAsPublished: (zone: string) => t("zoneTimeAsPublished", {zone}),
      dateAsPublished: t("dateAsPublished"),
      closedDeadlinePassed: t("closedDeadlinePassed"),
    }),
    [t],
  );
}
