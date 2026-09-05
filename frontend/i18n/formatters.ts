import type {CustomerSelectableLocale} from './locales.ts';

export const INVALID_FORMAT_VALUE = '—';

const INTL_LOCALES: Record<CustomerSelectableLocale, string> = {
    en: 'en-US',
    uz: 'uz-Latn-UZ',
    ru: 'ru-RU',
    ar: 'ar',
};

type DateInput = Date | string | number | null | undefined;

function validDate(value: DateInput): Date | null {
    if (value === null || value === undefined || value === '') return null;
    const date = value instanceof Date ? value : new Date(value);
    return Number.isNaN(date.getTime()) ? null : date;
}

export function formatDate(
    value: DateInput,
    locale: CustomerSelectableLocale,
    options: Intl.DateTimeFormatOptions = {},
): string {
    const date = validDate(value);
    if (!date) return INVALID_FORMAT_VALUE;
    return new Intl.DateTimeFormat(INTL_LOCALES[locale], {
        timeZone: 'UTC',
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        ...options,
    }).format(date);
}

export function formatDateTime(
    value: DateInput,
    locale: CustomerSelectableLocale,
    options: Intl.DateTimeFormatOptions = {},
): string {
    return formatDate(value, locale, {
        hour: '2-digit',
        minute: '2-digit',
        ...options,
    });
}

export function formatNumber(
    value: number | null | undefined,
    locale: CustomerSelectableLocale,
    options: Intl.NumberFormatOptions = {},
): string {
    if (value === null || value === undefined || !Number.isFinite(value)) {
        return INVALID_FORMAT_VALUE;
    }
    return new Intl.NumberFormat(INTL_LOCALES[locale], options).format(value);
}

export function formatCurrency(
    amount: number | null | undefined,
    currencyCode: string | null | undefined,
    locale: CustomerSelectableLocale,
    options: Omit<Intl.NumberFormatOptions, 'style' | 'currency'> = {},
): string {
    const currency = currencyCode?.trim().toUpperCase();
    if (
        amount === null || amount === undefined || !Number.isFinite(amount)
        || !currency || !/^[A-Z]{3}$/.test(currency)
    ) {
        return INVALID_FORMAT_VALUE;
    }
    try {
        return new Intl.NumberFormat(INTL_LOCALES[locale], {
            style: 'currency',
            currency,
            ...options,
        }).format(amount);
    } catch {
        return INVALID_FORMAT_VALUE;
    }
}

export function formatFileSize(
    bytes: number | null | undefined,
    locale: CustomerSelectableLocale,
): string {
    if (bytes === null || bytes === undefined || !Number.isFinite(bytes) || bytes < 0) {
        return INVALID_FORMAT_VALUE;
    }
    const units = ['B', 'KB', 'MB', 'GB'] as const;
    let value = bytes;
    let unitIndex = 0;
    while (value >= 1024 && unitIndex < units.length - 1) {
        value /= 1024;
        unitIndex += 1;
    }
    return `${formatNumber(value, locale, {maximumFractionDigits: unitIndex === 0 ? 0 : 1})} ${units[unitIndex]}`;
}

export function formatRelativeTime(
    value: DateInput,
    now: DateInput,
    locale: CustomerSelectableLocale,
): string {
    const date = validDate(value);
    const reference = validDate(now);
    if (!date || !reference) return INVALID_FORMAT_VALUE;

    const seconds = (date.getTime() - reference.getTime()) / 1000;
    const units: ReadonlyArray<readonly [Intl.RelativeTimeFormatUnit, number]> = [
        ['year', 60 * 60 * 24 * 365],
        ['month', 60 * 60 * 24 * 30],
        ['day', 60 * 60 * 24],
        ['hour', 60 * 60],
        ['minute', 60],
        ['second', 1],
    ];
    const [, divisor] = units.find(([, size]) => Math.abs(seconds) >= size) ?? units.at(-1)!;
    const unit = units.find(([, size]) => size === divisor)![0];
    return new Intl.RelativeTimeFormat(INTL_LOCALES[locale], {numeric: 'auto'}).format(
        Math.round(seconds / divisor),
        unit,
    );
}
