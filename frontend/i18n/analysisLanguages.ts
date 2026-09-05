export type AnalysisLanguage = 'en' | 'uz' | 'ru' | 'ar';
export type CustomerAnalysisLanguage = Exclude<AnalysisLanguage, 'ar'>;
export type ContentDirection = 'ltr' | 'rtl' | 'auto';

export type AnalysisLanguageDefinition = {
  code: AnalysisLanguage;
  nativeLabel: string;
  generationSupported: boolean;
  customerSelectable: boolean;
  direction: Exclude<ContentDirection, 'auto'>;
};

export const ANALYSIS_LANGUAGES: readonly AnalysisLanguageDefinition[] = [
  { code: 'en', nativeLabel: 'English', generationSupported: true, customerSelectable: true, direction: 'ltr' },
  { code: 'uz', nativeLabel: 'O‘zbekcha', generationSupported: true, customerSelectable: true, direction: 'ltr' },
  { code: 'ru', nativeLabel: 'Русский', generationSupported: true, customerSelectable: true, direction: 'ltr' },
  { code: 'ar', nativeLabel: 'العربية', generationSupported: true, customerSelectable: false, direction: 'rtl' },
] as const;

export const CUSTOMER_ANALYSIS_LANGUAGES = ANALYSIS_LANGUAGES.filter(
  (language): language is AnalysisLanguageDefinition & { code: CustomerAnalysisLanguage } =>
    language.customerSelectable,
);

export const DEFAULT_ANALYSIS_LANGUAGE: CustomerAnalysisLanguage = 'en';

export function normalizeCustomerAnalysisLanguage(value: unknown): CustomerAnalysisLanguage {
  return CUSTOMER_ANALYSIS_LANGUAGES.some((language) => language.code === value)
    ? value as CustomerAnalysisLanguage
    : DEFAULT_ANALYSIS_LANGUAGE;
}

export function analysisLanguageLabel(value: AnalysisLanguage | null | undefined): string {
  if (!value) return 'Not recorded';
  return ANALYSIS_LANGUAGES.find((language) => language.code === value)?.nativeLabel ?? 'Not recorded';
}

export function analysisContentDirection(value: AnalysisLanguage | null | undefined): ContentDirection {
  if (!value) return 'auto';
  return ANALYSIS_LANGUAGES.find((language) => language.code === value)?.direction ?? 'auto';
}
