import type englishMessages from '../messages/en';
import type {CustomerSelectableLocale} from './locales';
import type {PSEUDO_LOCALE_CODE} from './pseudoLocale';

declare module 'next-intl' {
    interface AppConfig {
        Locale: CustomerSelectableLocale | typeof PSEUDO_LOCALE_CODE;
        Messages: typeof englishMessages;
    }
}
