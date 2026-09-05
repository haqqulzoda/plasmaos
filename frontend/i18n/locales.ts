/**
 * Canonical localization contracts established by Sprint 7.1 and consumed by
 * the Sprint 7.2 runtime. Sprint 7.3 owns the visible customer UI rollout.
 * Keeping the contract here prevents onboarding, settings, and the document
 * shell from inventing separate locale lists.
 */

export const PRODUCT_LOCALE_CODES = ['en', 'uz', 'ru', 'ar'] as const;

export type ProductLocale = (typeof PRODUCT_LOCALE_CODES)[number];
export type CustomerSelectableLocale = ProductLocale;
export type LocaleDirection = 'ltr' | 'rtl';

export type LocaleDefinition = Readonly<{
    code: ProductLocale;
    displayNameNative: string;
    displayNameEnglish: string;
    enabled: boolean;
    customerSelectable: boolean;
    direction: LocaleDirection;
}>;

export const DEFAULT_PRODUCT_LOCALE: CustomerSelectableLocale = 'en';

export const LOCALE_REGISTRY = {
    en: {
        code: 'en',
        displayNameNative: 'English',
        displayNameEnglish: 'English',
        enabled: true,
        customerSelectable: true,
        direction: 'ltr',
    },
    uz: {
        code: 'uz',
        displayNameNative: 'O‘zbekcha',
        displayNameEnglish: 'Uzbek',
        enabled: true,
        customerSelectable: true,
        direction: 'ltr',
    },
    ru: {
        code: 'ru',
        displayNameNative: 'Русский',
        displayNameEnglish: 'Russian',
        enabled: true,
        customerSelectable: true,
        direction: 'ltr',
    },
    ar: {
        code: 'ar',
        displayNameNative: 'العربية',
        displayNameEnglish: 'Arabic',
        enabled: true,
        customerSelectable: true,
        direction: 'rtl',
    },
} as const satisfies Record<ProductLocale, LocaleDefinition>;

export const CUSTOMER_SELECTABLE_LOCALES = PRODUCT_LOCALE_CODES.filter(
    (code): code is CustomerSelectableLocale =>
        LOCALE_REGISTRY[code].enabled && LOCALE_REGISTRY[code].customerSelectable,
);

export const UI_LOCALE_PERSISTENCE_FIELD = 'ui_locale' as const;
export const UI_LOCALE_COOKIE_NAME = 'plasma_ui_locale' as const;

export const LOCALE_RESOLUTION_PRECEDENCE = [
    'persisted_user',
    'temporary_onboarding',
    'browser',
    'product_default',
] as const;

export type CustomerLocaleResolutionInput = Readonly<{
    persistedUserLocale?: string | null;
    temporaryOnboardingLocale?: string | null;
    browserLocales?: readonly string[] | null;
}>;

export function toProductLocale(value: string | null | undefined): ProductLocale | null {
    if (!value) return null;

    const primarySubtag = value.trim().replaceAll('_', '-').split('-', 1)[0]?.toLowerCase();
    return PRODUCT_LOCALE_CODES.find((code) => code === primarySubtag) ?? null;
}

export function toCustomerSelectableLocale(
    value: string | null | undefined,
): CustomerSelectableLocale | null {
    const locale = toProductLocale(value);
    return isCustomerSelectableLocale(locale) ? locale : null;
}

export function isCustomerSelectableLocale(
    value: unknown,
): value is CustomerSelectableLocale {
    return typeof value === 'string' && CUSTOMER_SELECTABLE_LOCALES.some(
        (locale) => locale === value,
    );
}

export function directionForLocale(value: string | null | undefined): LocaleDirection {
    return toProductLocale(value) === 'ar' ? 'rtl' : 'ltr';
}

/**
 * Pure contract helper for the future request/bootstrap resolver. It has no
 * browser, cookie, session, API, or rendering side effects.
 */
export function resolveCustomerLocale(input: CustomerLocaleResolutionInput): ProductLocale {
    const persisted = toCustomerSelectableLocale(input.persistedUserLocale);
    if (persisted) return persisted;

    const temporary = toCustomerSelectableLocale(input.temporaryOnboardingLocale);
    if (temporary) return temporary;

    for (const browserLocale of input.browserLocales ?? []) {
        const supported = toCustomerSelectableLocale(browserLocale);
        if (supported) return supported;
    }

    return DEFAULT_PRODUCT_LOCALE;
}

export const MESSAGE_NAMESPACES = [
    'common',
    'navigation',
    'auth',
    'onboarding',
    'settings',
    'explorer',
    'tenderDetails',
    'myTenders',
    'bidPreparation',
    'dashboard',
    'compliance',
    'readiness',
    'documentViewer',
    'refresh',
    'errors',
] as const;

export type MessageNamespace = (typeof MESSAGE_NAMESPACES)[number];

export const LOCALIZATION_CONTENT_POLICY = {
    product_ui: 'translate',
    source_provided: 'preserve_original',
    user_generated: 'preserve_original',
    ai_generated_analysis: 'separate_sprint_8_language_authority',
    enum_code: 'preserve_code_translate_display_label',
} as const;

export type LocalizationContentClass = keyof typeof LOCALIZATION_CONTENT_POLICY;
