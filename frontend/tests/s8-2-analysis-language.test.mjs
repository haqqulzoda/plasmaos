import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');
const registry = read('i18n/analysisLanguages.ts');
const settings = read('app/dashboard/settings/page.tsx');
const compliance = read('app/dashboard/tenders/[tenderId]/compliance/page.tsx');
const types = read('types/compliance.ts');
const catalogs = ['en', 'uz', 'ru'].map((locale) => JSON.parse(read(`messages/${locale}/settings.json`)));
const complianceCatalogs = ['en', 'uz', 'ru'].map((locale) => JSON.parse(read(`messages/${locale}/compliance.json`)));

test('analysis registry is independent, canonical, native-labelled, and truthfully gates Arabic', () => {
  for (const code of ['en', 'uz', 'ru', 'ar']) assert.match(registry, new RegExp(`code: '${code}'`));
  for (const label of ['English', 'O‘zbekcha', 'Русский', 'العربية']) assert.ok(registry.includes(label));
  assert.match(registry, /code: 'ar'.*customerSelectable: false/);
  assert.match(registry, /code: 'ar'.*direction: 'rtl'/);
  assert.doesNotMatch(registry.toLowerCase(), /flag/);
});

test('Settings separates interface and default analysis preferences', () => {
  assert.ok(settings.includes('<LanguageSelector surface="settings" />'));
  assert.ok(settings.includes('analysisLanguage.title'));
  assert.ok(settings.includes('/users/me/preferences'));
  assert.ok(settings.includes('{ default_analysis_language: analysisLanguage }'));
  assert.ok(!settings.includes('{ ui_locale: analysisLanguage }'));
});

test('Compliance captures one explicit per-run language and preserves default', () => {
  assert.ok(compliance.includes("new URLSearchParams({ analysis_language: selectedAnalysisLanguage })"));
  assert.ok(compliance.includes("query.set('force', 'true')"));
  assert.ok(!compliance.includes('default_analysis_language: selectedAnalysisLanguage'));
  assert.ok(compliance.includes('setResultAnalysisLanguage(data.analysis_language)'));
});

test('version metadata, history, legacy NULL, and exact export version are represented', () => {
  assert.ok(types.includes("analysis_language: 'en' | 'uz' | 'ru' | 'ar' | null"));
  assert.ok(compliance.includes('/versions`'));
  assert.ok(compliance.includes("exportQuery.set('version_number'"));
  assert.ok(compliance.includes("t('notRecorded')"));
  assert.ok(compliance.includes("t('crossLanguageNotice')"));
});

test('content direction is scoped and evidence remains auto', () => {
  assert.ok(compliance.includes('dir={analysisContentDirection(analysisLanguage)}'));
  assert.ok(compliance.includes('dir="auto"'));
  assert.ok(!compliance.includes('document.documentElement.dir'));
  assert.ok(!settings.includes('document.documentElement.dir'));
});

test('all active UI catalogs contain independent analysis-language copy', () => {
  for (const catalog of catalogs) {
    assert.ok(catalog.language.title);
    assert.ok(catalog.analysisLanguage.title);
    assert.ok(catalog.analysisLanguage.label);
    assert.ok(catalog.analysisLanguage.saveFailed);
  }
  for (const catalog of complianceCatalogs) {
    for (const key of ['analysisLanguage', 'analyzeAgain', 'resultLanguage', 'versionHistory', 'notRecorded', 'crossLanguageNotice']) {
      assert.ok(catalog[key], key);
    }
  }
});

test('UI locale is not execution-language authority', () => {
  const executionBlock = compliance.slice(compliance.indexOf('const handleAnalyzeTender'), compliance.indexOf('const handleDownloadCompliancePdf'));
  assert.ok(!executionBlock.includes('ui_locale'));
  assert.ok(!executionBlock.includes('useLocale'));
  assert.ok(!executionBlock.includes('document.documentElement.lang'));
});
