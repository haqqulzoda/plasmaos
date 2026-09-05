import type {AbstractIntlMessages} from 'next-intl';

import type {CustomerSelectableLocale} from './locales';
import type {MessageTree} from './messageValidation';
import {pseudoLocalizeMessages} from './pseudoLocale';

const localeLoaders: Record<
    CustomerSelectableLocale,
    () => Promise<{default: MessageTree}>
> = {
    en: () => import('../messages/en'),
    uz: () => import('../messages/uz'),
    ru: () => import('../messages/ru'),
    ar: () => import('../messages/ar'),
};

function mergeWithEnglishFallback(
    english: MessageTree,
    localized: MessageTree,
): MessageTree {
    const merged: Record<string, string | MessageTree> = {};
    for (const key of new Set([...Object.keys(english), ...Object.keys(localized)])) {
        const fallbackValue = english[key];
        const localizedValue = localized[key];
        if (
            fallbackValue && typeof fallbackValue === 'object'
            && localizedValue && typeof localizedValue === 'object'
        ) {
            merged[key] = mergeWithEnglishFallback(fallbackValue, localizedValue);
        } else {
            merged[key] = localizedValue ?? fallbackValue;
        }
    }
    return merged;
}

export async function loadMessages(
    locale: CustomerSelectableLocale,
): Promise<AbstractIntlMessages> {
    // Released catalogs are complete contracts. Arabic deliberately has no
    // English merge path so missing copy cannot silently ship in an RTL UI.
    if (locale === 'en' || locale === 'ar') {
        return (await localeLoaders[locale]()).default;
    }

    const [english, localized] = await Promise.all([
        localeLoaders.en(),
        localeLoaders[locale](),
    ]);
    return mergeWithEnglishFallback(english.default, localized.default);
}

export async function loadPseudoMessages(): Promise<AbstractIntlMessages> {
    return pseudoLocalizeMessages((await localeLoaders.en()).default);
}

export const ACTIVE_MESSAGE_LOADER_LOCALES = Object.freeze(
    Object.keys(localeLoaders) as CustomerSelectableLocale[],
);
