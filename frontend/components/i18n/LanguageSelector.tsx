"use client";

import { Check, Loader2 } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Surface, SectionHeader } from "@/components/ui/Display";
import { Radio } from "@/components/ui/Forms";
import { Alert } from "@/components/ui/Feedback";

import { applyUiLocale } from "@/i18n/userLocale";
import {
  CUSTOMER_SELECTABLE_LOCALES,
  LOCALE_REGISTRY,
  type CustomerSelectableLocale,
} from "@/i18n/locales";

type LanguageSelectorProps = Readonly<{
  surface: "auth" | "onboarding" | "settings";
  foundation?: boolean;
}>;

/**
 * The only visible customer locale control. It deliberately reads the active
 * next-intl locale and delegates persistence to the Sprint 7.2 transaction.
 * A failed write therefore cannot create an optimistic language flash.
 */
export function LanguageSelector({
  surface,
  foundation = false,
}: LanguageSelectorProps) {
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
    } catch {
      console.error("Failed to persist interface language:");
      setError(true);
    } finally {
      setPendingLocale(null);
    }
  };

  if (foundation)
    return (
      <Surface className="profile-section" data-language-selector={surface}>
        <SectionHeader title={t("title")} description={t(`${surface}Help`)} />
        <div
          className="ds-row"
          role="radiogroup"
          aria-label={t("optionsLabel")}
        >
          {CUSTOMER_SELECTABLE_LOCALES.map((locale) => (
            <Radio
              key={locale}
              name="interface-language"
              label={LOCALE_REGISTRY[locale].displayNameNative}
              aria-label={t("optionLabel", {
                language: LOCALE_REGISTRY[locale].displayNameNative,
              })}
              checked={activeLocale === locale}
              disabled={pendingLocale !== null}
              onChange={() => void selectLocale(locale)}
            />
          ))}
        </div>
        <div role="status">{pendingLocale ? t("saving") : null}</div>
        {error && <Alert tone="danger" title={t("saveFailed")} />}
      </Surface>
    );

  return (
    <section
      aria-labelledby={`${surface}-interface-language-heading`}
      className={`language-selector language-selector-${surface}`}
      data-language-selector={surface}
    >
      <div>
        <h2
          id={`${surface}-interface-language-heading`}
          className="language-selector-title"
        >
          {t("title")}
        </h2>
        <p className="ds-muted language-selector-help">
          {t(`${surface}Help`)}
        </p>
      </div>
      <div
        role="radiogroup"
        aria-label={t("optionsLabel")}
        className="language-selector-options"
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
              className="language-selector-option"
            >
              <span>{LOCALE_REGISTRY[locale].displayNameNative}</span>
              {pending ? (
                <Loader2 className="ds-spin" aria-hidden="true" />
              ) : selected ? (
                <Check aria-hidden="true" />
              ) : null}
            </button>
          );
        })}
      </div>
      <div className="language-selector-status" aria-live="polite">
        {pendingLocale ? (
          <span>{t("saving")}</span>
        ) : null}
        {!pendingLocale && error ? (
          <span role="alert" className="ds-field-error">
            {t("saveFailed")}
          </span>
        ) : null}
      </div>
    </section>
  );
}
