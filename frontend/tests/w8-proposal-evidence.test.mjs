import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');

test('Pursuit workspace exposes a real Proposal evidence section', () => {
  const page = read('app/dashboard/pursuits/[pursuitId]/page.tsx');
  assert.match(page, /PursuitProposal/);
  assert.match(page, /pursuit-proposal-title/);
  assert.doesNotMatch(page, /replace.*Bid Preparation/i);
});

test('sealing sends exact scenario revision and approval identities', () => {
  const source = read('components/pursuits/PursuitProposal.tsx');
  for (const value of ['scenario_id', 'revision_id', 'approval_decision_id', 'proposal-evidence-packs']) {
    assert.match(source, new RegExp(value));
  }
  assert.match(source, /APPROVED_FOR_PROPOSAL/);
  assert.match(source, /current_assessment_state === 'VIABLE'/);
  assert.match(source, /scenario_current/);
});

test('pack UI separates matrix roster obligations checklist and documents', () => {
  const source = read('components/pursuits/PursuitProposal.tsx');
  for (const value of ['proposal-matrix', 'teamRoster', 'LATER_STAGE_OBLIGATION', 'FORM_OR_REQUIRED_ARTIFACT', 'SOURCE_DOCUMENT', 'PRIVATE_DOCUMENT']) {
    assert.match(source, new RegExp(value));
  }
});

test('exports are price free and support PDF DOCX and JSON', () => {
  const source = read('components/pursuits/PursuitProposal.tsx');
  const locale = read('messages/en/pursuits.json');
  for (const value of ["'PDF'", "'DOCX'", "'JSON'"]) assert.match(source, new RegExp(value, 'i'));
  assert.match(locale, /commercial price/i);
  assert.doesNotMatch(source, /our_price|margin_percent|include_vat|budget-derived|AI price/i);
});

test('stale packs use explicit historical snapshot exports', () => {
  const source = read('components/pursuits/PursuitProposal.tsx');
  const locale = read('messages/en/pursuits.json');
  assert.match(source, /historical_snapshot: !pack\.pack_current/);
  assert.match(locale, /HISTORICAL SNAPSHOT/);
  assert.match(source, /stale_reasons/);
});

test('structured CV facts are disclosed without an original CV claim', () => {
  const source = read('components/pursuits/PursuitProposal.tsx');
  const locale = read('messages/en/pursuits.json');
  assert.match(source + locale, /Structured CV facts/i);
  assert.match(locale, /not an original or candidate-signed CV/i);
  assert.doesNotMatch(source, /generateOriginalCv|signedCvDownload/);
});

test('legacy Proposal compatibility is a separate link', () => {
  const source = read('components/pursuits/PursuitProposal.tsx');
  assert.match(source, /legacy_proposal_id/);
  assert.match(source, /\/dashboard\/bid-preparation\//);
  assert.doesNotMatch(source, /updateLegacyProposal|dualWrite/);
});

test('W8 locale keys remain structurally identical', () => {
  const locales = ['en', 'uz', 'ru', 'ar'].map((locale) => JSON.parse(read(`messages/${locale}/pursuits.json`)));
  const shape = (value, prefix = '') => Object.entries(value).flatMap(([key, child]) => {
    const path = prefix ? `${prefix}.${key}` : key;
    return child && typeof child === 'object' && !Array.isArray(child) ? [path, ...shape(child, path)] : [path];
  }).sort();
  const expected = shape(locales[0].proposal);
  for (const locale of locales.slice(1)) assert.deepEqual(shape(locale.proposal), expected);
});
