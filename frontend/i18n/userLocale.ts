"use client";

import { api } from "@/lib/api";
import type { CustomerSelectableLocale } from "./locales";
import { commitUiLocaleChange, type LocalePreference } from "./localeAction";

export type UserLocalePreference = LocalePreference;

export async function updateOwnUiLocale(
  uiLocale: CustomerSelectableLocale,
): Promise<UserLocalePreference> {
  const response = await api.patch<UserLocalePreference>(
    "/users/me/preferences",
    {
      ui_locale: uiLocale,
    },
  );
  return response.data;
}

async function updatePresentationCookie(
  uiLocale: CustomerSelectableLocale,
): Promise<void> {
  const response = await fetch("/api/ui-locale", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ui_locale: uiLocale }),
  });
  if (!response.ok) throw new Error("presentation_cookie_update_failed");
}

/**
 * Shared Sprint 7.2 transaction used by the visible Sprint 7.3 selectors. Persistence succeeds
 * before presentation changes, so a failed preference save retains the
 * current UI. `router.refresh()` preserves mounted client/provider state.
 */
export async function applyUiLocale(
  uiLocale: CustomerSelectableLocale,
  router: Readonly<{ refresh(): void }>,
): Promise<UserLocalePreference> {
  return commitUiLocaleChange(
    uiLocale,
    router,
    updateOwnUiLocale,
    updatePresentationCookie,
  );
}
