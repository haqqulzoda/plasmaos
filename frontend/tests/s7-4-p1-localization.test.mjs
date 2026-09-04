import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';

import {auditCustomerLiterals} from '../scripts/audit-customer-literals.mjs';
import {MESSAGE_NAMESPACES, CUSTOMER_SELECTABLE_LOCALES, LOCALE_REGISTRY} from '../i18n/locales.ts';
import {flattenMessageTree, validateMessageCatalogs} from '../i18n/messageValidation.ts';

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');
const catalog = (locale) => Object.fromEntries(MESSAGE_NAMESPACES.map((namespace) => [
  namespace,
  JSON.parse(read(`messages/${locale}/${namespace}.json`)),
]));
const catalogs = Object.fromEntries(CUSTOMER_SELECTABLE_LOCALES.map((locale) => [locale, catalog(locale)]));

test('final Sprint 7 catalogs have exact EN/UZ/RU key, ICU, and rich-message parity', () => {
  assert.deepEqual(validateMessageCatalogs(catalogs.en, {uz: catalogs.uz, ru: catalogs.ru}), []);
  const expected = flattenMessageTree(catalogs.en).size;
  assert.ok(expected >= 780, expected);
  for (const locale of CUSTOMER_SELECTABLE_LOCALES) assert.equal(flattenMessageTree(catalogs[locale]).size, expected);
});

test('P1 customer surfaces contain no unexplained literal JSX or accessibility copy', () => {
  assert.deepEqual(auditCustomerLiterals(), []);
});

test('Compliance localizes chrome while preserving analysis, evidence, and requirement content', () => {
  const source = read('app/dashboard/tenders/[tenderId]/compliance/page.tsx');
  assert.match(source, /useTranslations\('compliance'\)/);
  for (const expression of ['hybridCompliance.status_message', 'requirementSnippet', 'detail.raw_text_snippet', 'detail.exact_quote', 'd.matched_credential']) {
    assert.match(source, new RegExp(expression.replaceAll('.', '\\.')));
  }
  assert.doesNotMatch(source, /(?:^|[^A-Za-z])t\((?:hybridCompliance\.status_message|requirementSnippet|detail\.(?:raw_text_snippet|exact_quote)|d\.matched_credential)/m);
  assert.doesNotMatch(source, /api\.post[^\n]*(?:locale|language)|analysis_language|report_language/);
});

test('Readiness enum mappings are exhaustive and canonical values are unchanged', async () => {
  const readiness = await import('../lib/readiness.ts');
  assert.deepEqual(readiness.DOCUMENT_STATUS_OPTIONS.map((item) => item.value), ['available', 'missing', 'expired', 'unknown']);
  assert.ok(readiness.DOCUMENT_TYPE_OPTIONS.every((item) => item.messageKey.startsWith('types.')));
  assert.equal(readiness.documentStatusMessageKey('future_status'), 'statuses.unknown');
  assert.equal(readiness.documentTypeMessageKey('future_type'), 'types.unknown');
});

test('customer formatting is centralized and invalid values are safe', async () => {
  const formatting = await import('../i18n/formatters.ts');
  assert.equal(formatting.formatDate('not-a-date', 'en'), '—');
  assert.equal(formatting.formatNumber(Number.NaN, 'uz'), '—');
  assert.equal(formatting.formatCurrency(10, 'invalid', 'ru'), '—');
  assert.equal(formatting.formatFileSize(-1, 'en'), '—');
  assert.match(formatting.formatFileSize(1536, 'ru'), /KB$/);
  const customer = [
    read('app/dashboard/page.tsx'), read('app/dashboard/readiness-vault/page.tsx'),
    read('app/dashboard/tenders/[tenderId]/page.tsx'), read('app/dashboard/bid-preparation/[proposalId]/page.tsx'),
  ].join('\n');
  assert.doesNotMatch(customer, /\.toLocale(?:String|DateString|TimeString)\(|new Intl\.(?:DateTimeFormat|NumberFormat|RelativeTimeFormat)/);
});

test('Arabic, RTL, localStorage, and analysis/report language remain outside Sprint 7', () => {
  assert.deepEqual(CUSTOMER_SELECTABLE_LOCALES, ['en', 'uz', 'ru']);
  assert.equal(LOCALE_REGISTRY.ar.customerSelectable, false);
  const selector = read('components/i18n/LanguageSelector.tsx');
  const customer = CUSTOMER_SELECTABLE_LOCALES.map((locale) => JSON.stringify(catalogs[locale])).join('\n');
  assert.doesNotMatch(selector, /العربية|dir=|localStorage/);
  assert.doesNotMatch(customer, /analysis_language|report_language/);
});

test('claim-sensitive translations avoid certification and guarantee inflation', () => {
  for (const locale of CUSTOMER_SELECTABLE_LOCALES) {
    const messages = [catalogs[locale].compliance, catalogs[locale].readiness, catalogs[locale].refresh]
      .map((value) => JSON.stringify(value)).join(' ');
    assert.doesNotMatch(messages, /guaranteed compliance|guaranteed eligibility|government approved|fully synchronized/i, locale);
  }
});
