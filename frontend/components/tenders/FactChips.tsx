"use client";

import { useTranslations } from "next-intl";

import { BidiText } from "@/components/i18n/BidiText";
import { translateServiceLabel } from "@/i18n/taxonomy";
import { deriveFactChips, type FactTender, type ProfileMatch } from "@/lib/factChips";

/**
 * Deterministic facts about a tender (D1-08): profile country/service match, notice
 * type and days left. Renders nothing when no fact holds.
 */
export function FactChips({
  tender,
  profileMatch,
  now,
  className,
}: {
  tender: FactTender;
  profileMatch?: ProfileMatch;
  now?: number;
  className?: string;
}) {
  const t = useTranslations("explorer.facts");
  const tCommon = useTranslations("common");
  const chips = deriveFactChips(tender, profileMatch, now);
  if (!chips.length) return null;
  return (
    <ul className={`fact-chips${className ? ` ${className}` : ""}`} aria-label={t("label")}>
      {chips.map((chip) => {
        if (chip.kind === "country")
          return (
            <li className="fact-chip fact-chip-match" data-fact="country" key={`country-${chip.country}`}>
              <BidiText>{t("countryMatch", { country: chip.country })}</BidiText>
            </li>
          );
        if (chip.kind === "service")
          return (
            <li className="fact-chip fact-chip-match" data-fact="service" key={`service-${chip.service}`}>
              <BidiText>
                {t("serviceMatch", { service: translateServiceLabel(chip.service, tCommon, chip.service) })}
              </BidiText>
            </li>
          );
        if (chip.kind === "noticeType")
          return (
            <li className="fact-chip" data-fact="notice-type" key="notice-type">
              {t(`noticeType.${chip.type}`)}
            </li>
          );
        return (
          <li className="fact-chip" data-fact="days-left" key="days-left">
            {t("daysLeft", { count: chip.days })}
          </li>
        );
      })}
    </ul>
  );
}
