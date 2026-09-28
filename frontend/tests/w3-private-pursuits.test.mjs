import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');
const json = (locale, name) => JSON.parse(read(`messages/${locale}/${name}.json`));

function keys(value, prefix = '') {
  return Object.entries(value).flatMap(([key, item]) => {
    const path = prefix ? `${prefix}.${key}` : key;
    return item && typeof item === 'object' ? keys(item, path) : [path];
  }).sort();
}

test('Upload Tender is a persistent customer-shell action and route', () => {
  const shell = read('components/shell/CustomerShell.tsx');
  assert.match(shell, /uploadedTenders/);
  assert.match(shell, /\/dashboard\/uploaded-tenders\/upload/);
  assert.match(shell, /shell-upload-action/);
});

test('uploaded tenders uses only factual W3 pursuit data', () => {
  const page = read('app/dashboard/uploaded-tenders/page.tsx');
  assert.match(page, /origin: 'UPLOAD'/);
  assert.match(page, /processed_count/);
  assert.match(page, /owner_name/);
  assert.doesNotMatch(page, /compliance score|gap count|team readiness|proposal progress/i);
});

test('upload intake sends a private multi-file pack and explicit organization', () => {
  const page = read('app/dashboard/uploaded-tenders/upload/page.tsx');
  assert.match(page, /multiple/);
  assert.match(page, /25 \* 1024 \* 1024/);
  assert.match(page, /150 \* 1024 \* 1024/);
  assert.match(page, /X-Organization-ID/);
  assert.match(page, /context_json/);
  assert.match(page, /confirmed_fields/);
  assert.doesNotMatch(page, /budget/);
});

test('W3 Overview and Documents remain intact after the W4 Requirements extension', () => {
  const page = read('app/dashboard/pursuits/[pursuitId]/page.tsx');
  assert.match(page, /workspace\.overview/);
  assert.match(page, /workspace\.documents/);
  assert.match(page, /retry/);
  assert.match(page, /versions/);
  assert.match(page, /PursuitRequirements/);
  assert.doesNotMatch(page, />Team</);
  assert.doesNotMatch(page, />Proposal</);
  assert.doesNotMatch(page, />Activity</);
});

test('Tender Details separates official source documents from lazy private upload', () => {
  const detail = read('app/dashboard/tenders/[tenderId]/page.tsx');
  const upload = read('components/pursuits/SourcePrivateUpload.tsx');
  assert.match(detail, /officialSourceDocuments/);
  assert.match(detail, /SourcePrivateUpload/);
  assert.match(upload, /pursuits\/source\/\$\{encodeURIComponent\(tenderId\)\}\/documents/);
  assert.doesNotMatch(detail, /\/pursuits\/.*\/documents.*api\.get/);
});

test('private processing notifications navigate by IDs to the pursuit workspace', () => {
  const communications = read('lib/communications.ts');
  assert.match(communications, /PRIVATE_DOCUMENTS_READY/);
  assert.match(communications, /payload\.pursuit_id/);
  assert.match(communications, /payload\.organization_id/);
  assert.doesNotMatch(communications, /payload\.storage_key|payload\.filename|payload\.extracted_text/);
});

test('W3 locale catalog is complete for EN UZ RU and AR', () => {
  const englishKeys = keys(json('en', 'pursuits'));
  for (const locale of ['uz', 'ru', 'ar']) {
    assert.deepEqual(keys(json(locale, 'pursuits')), englishKeys, `${locale} pursuit keys`);
  }
});

test('private pursuit layouts use logical responsive CSS', () => {
  const css = read('components/customer/pages.css');
  assert.match(css, /pursuit-workspace/);
  assert.match(css, /private-document-row/);
  assert.match(css, /@media \(max-width: 640px\)/);
  assert.match(css, /inline-size/);
  assert.doesNotMatch(css.match(/\/\* W3 private pursuit[\s\S]*$/)?.[0] || '', /margin-left|padding-right|left:/);
});
