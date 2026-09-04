import type {CustomerSelectableLocale} from './locales.ts';

export type LocalePreference = Readonly<{ui_locale: CustomerSelectableLocale}>;
export type LocalePersister = (locale: CustomerSelectableLocale) => Promise<LocalePreference>;
export type PresentationCookieWriter = (locale: CustomerSelectableLocale) => Promise<void>;

/**
 * Transaction ordering for locale changes. The persisted user authority is
 * written first; only a successful save may reconcile presentation state.
 */
export async function commitUiLocaleChange(
    locale: CustomerSelectableLocale,
    router: Readonly<{refresh(): void}>,
    persist: LocalePersister,
    writePresentationCookie: PresentationCookieWriter,
): Promise<LocalePreference> {
    const preference = await persist(locale);
    await writePresentationCookie(preference.ui_locale).catch(() => undefined);
    router.refresh();
    return preference;
}
