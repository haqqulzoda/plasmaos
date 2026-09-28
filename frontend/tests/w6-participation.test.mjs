import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');

test('Team view keeps fit, availability, interest, and participation distinct', () => {
  const source = read('components/pursuits/PursuitTeam.tsx');
  for (const area of ['fitEvidence', 'availability', 'interest', 'participation']) {
    assert.match(source, new RegExp(`participation\\.${area}|t\\('${area}'\\)`));
  }
  assert.match(source, /participation-status-grid/);
  assert.doesNotMatch(source, /overallStatus|combinedParticipationState/);
});

test('participation starts explicitly from the exact latest shortlist decision', () => {
  const source = read('components/pursuits/PursuitTeam.tsx');
  assert.match(source, /candidate-matches\/\$\{match\.candidate_match_id\}\/participation-record/);
  assert.match(source, /shortlist_decision_id: match\.latest_review\.decision_id/);
  assert.match(source, /latest_review\?\.decision === 'SHORTLISTED'/);
});

test('append-only fact actions use separate W6 endpoints and correction references', () => {
  const source = read('components/pursuits/PursuitTeam.tsx');
  assert.match(source, /availability-facts/);
  assert.match(source, /interest-facts/);
  assert.match(source, /\/decisions/);
  assert.match(source, /supersedes_fact_id/);
  assert.match(source, /correctLatest/);
  assert.doesNotMatch(source, /api\.(put|patch|delete)\(/);
});

test('freshness and assignment-window disclosures are first-class projections', () => {
  const source = read('components/pursuits/PursuitTeam.tsx');
  const types = read('types/pursuit.ts');
  for (const value of ['EXPIRED', 'NEEDS_RECONFIRMATION', 'FULL_WINDOW', 'PARTIAL_WINDOW', 'NO_OVERLAP', 'UNKNOWN_DATES']) {
    assert.match(source + types, new RegExp(value));
  }
  assert.match(types, /upstream_stale/);
  assert.match(source, /upstream_stale_reason/);
});

test('confirmation provenance is factual and private notes are absent from UI projections', () => {
  const source = read('components/pursuits/PursuitTeam.tsx');
  const types = read('types/pursuit.ts');
  for (const value of ['DIRECT_EMAIL', 'CALL', 'MEETING', 'SIGNED_DOCUMENT', 'OPERATOR_RECORDED', 'CUSTOMER_RECORDED', 'OTHER']) {
    assert.match(source + types, new RegExp(value));
  }
  assert.match(source, /recordedFrom/);
  assert.doesNotMatch(types, /private_note|note:/i);
});

test('Team participation supports decline and withdrawal without outbound actions', () => {
  const source = read('components/pursuits/PursuitTeam.tsx');
  for (const value of ['UNCONFIRMED', 'TENTATIVE', 'CONFIRMED', 'DECLINED', 'WITHDRAWN']) {
    assert.match(source, new RegExp(value));
  }
  assert.doesNotMatch(source, /send invitation|send email|send sms|slack|outbound/i);
  assert.doesNotMatch(source, /proposal evidence pack|generate proposal/i);
});

test('W6 pursuit locale keys remain structurally identical', () => {
  const locales = ['en', 'uz', 'ru', 'ar'].map((locale) => JSON.parse(read(`messages/${locale}/pursuits.json`)));
  const shape = (value, prefix = '') => Object.entries(value).flatMap(([key, child]) => {
    const path = prefix ? `${prefix}.${key}` : key;
    return child && typeof child === 'object' && !Array.isArray(child) ? [path, ...shape(child, path)] : [path];
  }).sort();
  const expected = shape(locales[0].team.participation);
  for (const locale of locales.slice(1)) assert.deepEqual(shape(locale.team.participation), expected);
});
