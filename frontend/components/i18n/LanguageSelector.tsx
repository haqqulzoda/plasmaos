"use client";

import { Check, Loader2 } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { applyUiLocale } from "@/i18n/userLocale";
import {
  CUSTOMER_SELECTABLE_LOCALES,
  LOCALE_REGISTRY,
  type CustomerSelectableLocale,
} from "@/i18n/locales";

type LanguageSelectorProps = Readonly<{
  surface: "onboarding" | "settings";
}>;

/**
 * The only visible customer locale control. It deliberately reads the active
 * next-intl locale and delegates persistence to the Sprint 7.2 transaction.
 * A failed write therefore cannot create an optimistic language flash.
 */
export function LanguageSelector({ surface }: LanguageSelectorProps) {
  const router = useRouter();
  const activeLocale = useLocale() as CustomerSelectableLocale;
  const t = useTranslations("settings.language");
  const [pendingLocale, setPendingLocale] =
    useState<CustomerSelectableLocale | null>(null);
  const [error, setError] = useState(false);

  const selectLocale = async (locale: CustomerSelectableLocale) => {
    if (locale === activeLocale || pendingLocale) return;
    setError(false);
    setPendingLocale(locale);
    try {
      await applyUiLocale(locale, router);
    } catch (requestError) {
      console.error("Failed to persist interface language:", requestError);
      setError(true);
    } finally {
      setPendingLocale(null);
    }
  };

  return (
    <section
      aria-labelledby={`${surface}-interface-language-heading`}
      className="space-y-4 rounded-xl border border-cyan-500/20 bg-cyan-500/[0.06] p-4 sm:p-5"
      data-language-selector={surface}
    >
      <div>
        <h2
          id={`${surface}-interface-language-heading`}
          className="text-base font-semibold text-white"
        >
          {t("title")}
        </h2>
        <p className="mt-1 text-sm leading-5 text-zinc-400">
          {t(`${surface}Help`)}
        </p>
      </div>
      <div
        role="radiogroup"
        aria-label={t("optionsLabel")}
        className="grid grid-cols-1 gap-2 sm:grid-cols-3"
      >
        {CUSTOMER_SELECTABLE_LOCALES.map((locale) => {
          const selected = activeLocale === locale;
          const pending = pendingLocale === locale;
          return (
            <button
              key={locale}
              type="button"
              role="radio"
              aria-checked={selected}
              aria-label={t("optionLabel", {
                language: LOCALE_REGISTRY[locale].displayNameNative,
              })}
              disabled={pendingLocale !== null}
              onClick={() => void selectLocale(locale)}
              className={`flex min-h-12 items-center justify-between gap-3 rounded-lg border px-4 py-3 text-left text-sm font-semibold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300 disabled:cursor-wait disabled:opacity-70 ${
                selected
                  ? "border-cyan-400 bg-cyan-500/15 text-cyan-100"
                  : "border-zinc-700 bg-zinc-950 text-zinc-200 hover:border-zinc-500"
              }`}
            >
              <span>{LOCALE_REGISTRY[locale].displayNameNative}</span>
              {pending ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : selected ? (
                <Check className="h-4 w-4" aria-hidden="true" />
              ) : null}
            </button>
          );
        })}
      </div>
      <div className="min-h-5 text-xs" aria-live="polite">
        {pendingLocale ? (
          <span className="text-cyan-200">{t("saving")}</span>
        ) : null}
        {!pendingLocale && error ? (
          <span role="alert" className="text-red-300">
            {t("saveFailed")}
          </span>
        ) : null}
      </div>
    </section>
  );
}
