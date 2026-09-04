export const LOCALIZABLE_ERROR_CODES = [
    'unsupported_ui_locale',
    'locale_save_failed',
] as const;

export type LocalizableErrorCode = (typeof LOCALIZABLE_ERROR_CODES)[number];

const ERROR_MESSAGE_KEYS: Record<LocalizableErrorCode, string> = {
    unsupported_ui_locale: 'unsupportedUiLocale',
    locale_save_failed: 'localeSaveFailed',
};

export function localizableErrorCode(value: unknown): LocalizableErrorCode | null {
    return typeof value === 'string'
        ? LOCALIZABLE_ERROR_CODES.find((code) => code === value) ?? null
        : null;
}

export function errorMessageKey(value: unknown): string {
    const code = localizableErrorCode(value);
    return code ? ERROR_MESSAGE_KEYS[code] : 'generic';
}
