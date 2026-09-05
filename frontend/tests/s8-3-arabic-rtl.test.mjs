import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {createTranslator} from 'next-intl';

import {
  CUSTOMER_SELECTABLE_LOCALES,
  LOCALE_REGISTRY,
  MESSAGE_NAMESPACES,
  directionForLocale,
  resolveCustomerLocale,
  toCustomerSelectableLocale,
} from '../i18n/locales.ts';
import {flattenMessageTree, validateMessageCatalogs} from '../i18n/messageValidation.ts';
import {formatCurrency, formatDate, formatFileSize, formatNumber, formatRelativeTime} from '../i18n/formatters.ts';
import {parseAcceptLanguage, resolveRequestLocale} from '../i18n/requestLocale.ts';
import {analysisContentDirection, CUSTOMER_ANALYSIS_LANGUAGES} from '../i18n/analysisLanguages.ts';
import {runRtlAudit} from '../scripts/audit-rtl.mjs';

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');
const catalog = (locale) => Object.fromEntries(MESSAGE_NAMESPACES.map((namespace) => [
  namespace,
  JSON.parse(read(`messages/${locale}/${namespace}.json`)),
]));
const catalogs = Object.fromEntries(['en', 'uz', 'ru', 'ar'].map((locale) => [locale, catalog(locale)]));

test('Arabic activation is atomic across registry, loader, root direction, and selector', () => {
  assert.deepEqual(CUSTOMER_SELECTABLE_LOCALES, ['en', 'uz', 'ru', 'ar']);
  assert.deepEqual(LOCALE_REGISTRY.ar, {
    code: 'ar', displayNameNative: 'العربية', displayNameEnglish: 'Arabic',
    enabled: true, customerSelectable: true, direction: 'rtl',
  });
  assert.match(read('i18n/messages.ts'), /ar:\s*\(\)\s*=>\s*import\('\.\.\/messages\/ar'\)/);
  assert.match(read('app/layout.tsx'), /<html lang=\{locale\} dir=\{directionForLocale\(locale\)\}>/);
  assert.match(read('components/i18n/LanguageSelector.tsx'), /CUSTOMER_SELECTABLE_LOCALES\.map/);
});

test('all 15 Arabic namespaces match the complete 866-key customer contract', () => {
  assert.equal(MESSAGE_NAMESPACES.length, 15);
  assert.equal(flattenMessageTree(catalogs.en).size, 866);
  assert.equal(flattenMessageTree(catalogs.ar).size, 866);
  assert.deepEqual(validateMessageCatalogs(catalogs.en, {ar: catalogs.ar}), []);
});

test('all four catalogs retain exact key, ICU placeholder, and rich placeholder parity', () => {
  assert.deepEqual(validateMessageCatalogs(catalogs.en, {uz: catalogs.uz, ru: catalogs.ru, ar: catalogs.ar}), []);
});

test('Arabic released copy has no exact English fallback leaf', () => {
  const english = flattenMessageTree(catalogs.en);
  const arabic = flattenMessageTree(catalogs.ar);
  const placeholderOnly = new Set(['explorer.documentCount', 'refresh.actionLabel']);
  const identical = [...english].filter(([key, value]) => arabic.get(key) === value && !placeholderOnly.has(key));
  assert.deepEqual(identical, []);
  assert.match(read('i18n/messages.ts'), /locale === 'en' \|\| locale === 'ar'/);
});

test('Arabic copy preserves approved brands and avoids inflated claims', () => {
  const values = [...flattenMessageTree(catalogs.ar).values()].join('\n');
  for (const brand of ['Google', 'Plasma AI', 'UzEx']) assert.match(values, new RegExp(brand));
  assert.doesNotMatch(values, /امتثال مضمون|أهلية مضمونة|اعتماد قانوني|فوز مضمون|مزامنة كاملة/);
});

test('Arabic variants, weighted Accept-Language, and locale precedence resolve canonically', () => {
  for (const value of ['ar', 'ar-SA', 'ar-EG', 'ar-AE', 'AR_latn_AE']) {
    assert.equal(toCustomerSelectableLocale(value), 'ar');
  }
  assert.deepEqual(parseAcceptLanguage('ru;q=0.4, ar-SA;q=0.9, en;q=0.7'), ['ar-SA', 'en', 'ru']);
  assert.equal(resolveRequestLocale({acceptLanguage: 'ru;q=0.4,ar-EG;q=0.9'}), 'ar');
  assert.equal(resolveRequestLocale({persistedUserLocale: 'ru', presentationCookie: 'ar', acceptLanguage: 'ar'}), 'ru');
  assert.equal(resolveRequestLocale({presentationCookie: 'ar', acceptLanguage: 'en'}), 'ar');
  assert.equal(resolveCustomerLocale({browserLocales: ['ar-AE']}), 'ar');
});

test('one direction function maps Arabic to RTL and every other UI locale to LTR', () => {
  assert.equal(directionForLocale('ar'), 'rtl');
  assert.equal(directionForLocale('ar-SA'), 'rtl');
  for (const locale of ['en', 'uz', 'ru', 'en-XA', null]) assert.equal(directionForLocale(locale), 'ltr');
});

test('Arabic number, currency, date, relative time, and file-size formatting is centralized', () => {
  assert.notEqual(formatNumber(12345.6, 'ar'), '—');
  assert.notEqual(formatCurrency(1234.5, 'USD', 'ar'), '—');
  assert.match(formatDate('2026-09-04T00:00:00Z', 'ar'), /سبتمبر|سبت|٢٠٢٦|2026/);
  assert.match(formatRelativeTime('2026-09-03T00:00:00Z', '2026-09-04T00:00:00Z', 'ar'), /أمس|يوم/);
  assert.match(formatFileSize(1536, 'ar'), /KB$/);
});

test('Arabic ICU messages execute with Arabic plural rules and source interpolation', () => {
  const t = createTranslator({locale: 'ar', messages: catalogs.ar});
  assert.match(t('common.tenderCount', {count: 1}), /مناقصة/);
  assert.match(t('refresh.completeFromSource', {count: 2, source: 'World Bank'}), /World Bank/);
});

test('Arabic UI remains independent from the gated analysis-language registry', () => {
  assert.deepEqual(CUSTOMER_ANALYSIS_LANGUAGES.map(({code}) => code), ['en', 'uz', 'ru']);
  assert.equal(analysisContentDirection('en'), 'ltr');
  assert.equal(analysisContentDirection('uz'), 'ltr');
  assert.equal(analysisContentDirection('ru'), 'ltr');
  assert.equal(analysisContentDirection('ar'), 'rtl');
  assert.equal(analysisContentDirection(null), 'auto');
});

test('source, user, technical, and analysis content have reusable bidi boundaries', () => {
  const bidi = read('components/i18n/BidiText.tsx');
  const css = read('app/globals.css');
  assert.match(bidi, /<bdi/);
  assert.match(bidi, /direction="ltr"/);
  assert.match(css, /unicode-bidi:\s*plaintext/);
  assert.match(css, /unicode-bidi:\s*isolate/);
  for (const file of [
    'app/dashboard/tenders/page.tsx', 'app/dashboard/my-tenders/page.tsx',
    'app/dashboard/tenders/[tenderId]/page.tsx', 'app/dashboard/readiness-vault/page.tsx',
  ]) assert.match(read(file), /BidiText|dir="auto"/);
});

test('analysis, evidence, identifier, and filename islands are explicit in Compliance', () => {
  const source = read('app/dashboard/tenders/[tenderId]/compliance/page.tsx');
  assert.match(source, /dir=\{analysisContentDirection\(analysisLanguage\)\}/);
  assert.match(source, /<span dir="auto">&quot;\{quote\}/);
  assert.match(source, /dir="ltr" className="technical-ltr[^>]*font-mono/);
  assert.match(source, /dir="auto" className="bidi-auto[^>]*truncate">\{d\.source_filename/);
});

test('profile, onboarding, search, proposal, and readiness inputs declare content direction', () => {
  const natural = [
    'app/dashboard/onboarding/page.tsx', 'app/dashboard/settings/page.tsx',
    'app/dashboard/tenders/page.tsx', 'app/dashboard/my-tenders/page.tsx',
    'app/dashboard/bid-preparation/[proposalId]/page.tsx', 'app/dashboard/readiness-vault/page.tsx',
  ].map(read).join('\n');
  assert.match(natural, /dir="auto"/);
  assert.match(natural, /dir="ltr"/);
  assert.doesNotMatch(natural, /\\u202[ABCDEF]|\\u206[6-9]/i);
});

test('customer CSS and semantic direction icons pass the zero-exception RTL guard', () => {
  assert.deepEqual(runRtlAudit(), {physical: [], icons: [], authority: []});
});

test('dedicated Admin content is an explicit English LTR island', () => {
  const admin = read('app/admin/layout.tsx');
  assert.match(admin, /lang="en" dir="ltr" data-admin-ltr-island/);
});

test('document source geometry stays LTR while source lines use auto direction', () => {
  const viewer = read('components/workspace/DocumentViewer.tsx');
  assert.match(viewer, /<div dir="ltr" className="flex font-mono/);
  assert.match(viewer, /dir="auto"/);
  assert.match(viewer, /border-e/);
});

test('locale switching persists only ui_locale then refreshes without route replacement', () => {
  const action = read('i18n/localeAction.ts');
  const client = read('i18n/userLocale.ts');
  assert.match(client, /\{\s*ui_locale: uiLocale/);
  assert.match(action, /await persist\(locale\)[\s\S]*router\.refresh\(\)/);
  assert.doesNotMatch(action, /router\.(?:push|replace)/);
});

test('canonical query and payload values remain locale-neutral', () => {
  const explorer = read('app/dashboard/tenders/page.tsx');
  const compliance = read('app/dashboard/tenders/[tenderId]/compliance/page.tsx');
  assert.match(explorer, /new URLSearchParams\(\{ view: query\.view \}\)/);
  assert.match(compliance, /new URLSearchParams\(\{ analysis_language: selectedAnalysisLanguage \}\)/);
  assert.doesNotMatch(compliance, /analysis_language:\s*(?:locale|uiLocale)/);
});
