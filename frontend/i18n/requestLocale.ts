import {
    DEFAULT_PRODUCT_LOCALE,
    UI_LOCALE_COOKIE_NAME,
    type CustomerSelectableLocale,
    toCustomerSelectableLocale,
} from './locales.ts';

export const PERSISTED_UI_LOCALE_HEADER = 'x-plasma-persisted-ui-locale';
export {UI_LOCALE_COOKIE_NAME};

export type RequestLocaleInput = Readonly<{
    persistedUserLocale?: string | null;
    presentationCookie?: string | null;
    acceptLanguage?: string | null;
}>;

type WeightedLanguage = Readonly<{
    tag: string;
    quality: number;
    position: number;
}>;

export function parseAcceptLanguage(value: string | null | undefined): readonly string[] {
    if (!value) return [];

    const weighted: WeightedLanguage[] = [];
    for (const [position, rawEntry] of value.split(',').entries()) {
        const [rawTag, ...parameters] = rawEntry.trim().split(';');
        const tag = rawTag?.trim();
        if (!tag || tag === '*' || !/^[A-Za-z]{2,8}(?:[-_][A-Za-z0-9]{1,8})*$/.test(tag)) {
            continue;
        }

        let quality = 1;
        let malformed = false;
        for (const parameter of parameters) {
            const match = parameter.trim().match(/^q\s*=\s*(0(?:\.\d{0,3})?|1(?:\.0{0,3})?)$/i);
            if (!match) {
                malformed = true;
                break;
            }
            quality = Number(match[1]);
        }
        if (!malformed && quality > 0) weighted.push({tag, quality, position});
    }

    return weighted
        .sort((left, right) => right.quality - left.quality || left.position - right.position)
        .map(({tag}) => tag);
}

export function resolveRequestLocale(input: RequestLocaleInput): CustomerSelectableLocale {
    const persisted = toCustomerSelectableLocale(input.persistedUserLocale);
    if (persisted) return persisted;

    const cookie = toCustomerSelectableLocale(input.presentationCookie);
    if (cookie) return cookie;

    for (const requested of parseAcceptLanguage(input.acceptLanguage)) {
        const locale = toCustomerSelectableLocale(requested);
        if (locale) return locale;
    }

    return DEFAULT_PRODUCT_LOCALE;
}
