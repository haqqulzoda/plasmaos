'use client';

import { useTranslations } from 'next-intl';

export type LibraryTranslator = (key: string, values?: Record<string, string | number>) => string;

/**
 * pursuits.library messages with keys built from record values (roles, states,
 * error codes). Every such key exists in all four catalogs; the library tests
 * check the catalogs against the enums.
 */
export function useLibraryT(): LibraryTranslator {
    return useTranslations('pursuits.library') as unknown as LibraryTranslator;
}
