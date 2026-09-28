import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');

test('Team workspace supports named alternatives and immutable revisions', () => {
  const source = read('components/pursuits/PursuitTeam.tsx');
  assert.match(source, /team-scenarios/);
  assert.match(source, /participation_record_ids/);
  assert.match(source, /\/revisions/);
  assert.match(source, /sealRevision/);
  assert.doesNotMatch(source, /api\.(put|patch|delete)\(/);
});

test('scenario summaries disclose operational counts without percentages or ranking', () => {
  const source = read('components/pursuits/PursuitTeam.tsx');
  for (const value of ['covered_gap_count', 'unresolved_gap_count', 'participant_count', 'confirmed_participant_count', 'issue_count']) {
    assert.match(source, new RegExp(value));
  }
  assert.doesNotMatch(source, /match percentage|readiness percentage|best team|win probability/i);
});

test('lead organization, partner firms, experts, contributions and gaps stay distinct', () => {
  const source = read('components/pursuits/PursuitTeam.tsx');
  const types = read('types/pursuit.ts');
  for (const value of ['leadOrganization', 'PARTNER_FIRM', 'EXPERT', 'gap_assessments', 'contributions']) {
    assert.match(source + types, new RegExp(value));
  }
});

test('scenario assessment states never use procurement or prediction claims', () => {
  const source = read('components/pursuits/PursuitTeam.tsx');
  const types = read('types/pursuit.ts');
  for (const value of ['DRAFT', 'NEEDS_REVIEW', 'BLOCKED', 'VIABLE']) assert.match(source + types, new RegExp(value));
  assert.doesNotMatch(source + types, /GUARANTEED|WINNABLE|ELIGIBLE|COMPLIANT/);
});

test('structured issues include scheduling, evidence, staleness and conflicting facts', () => {
  const types = read('types/pursuit.ts');
  for (const value of ['EXPERT_DOUBLE_COUNT', 'CONCURRENT_FULL_TIME_CONFLICT', 'UNKNOWN_EFFORT', 'PARTIAL_CANDIDATE_EVIDENCE', 'UPSTREAM_STALE', 'CONFLICTING_PARTICIPATION_FACTS']) {
    assert.match(types, new RegExp(value));
  }
});

test('proposal approval is explicitly confirmed and gated by current viability', () => {
  const source = read('components/pursuits/PursuitTeam.tsx');
  assert.match(source, /APPROVED_FOR_PROPOSAL/);
  assert.match(source, /explicit_confirmation/);
  assert.match(source, /revision\.scenario_current/);
  assert.match(source, /revision\.current_assessment_state !== 'VIABLE'/);
});

test('scenario comparison is restrained and does not choose a winner', () => {
  const source = read('components/pursuits/PursuitTeam.tsx');
  for (const value of ['scenario-comparison', 'blocking_issue_count', 'unresolved_gap_count']) assert.match(source, new RegExp(value));
  assert.doesNotMatch(source, /recommendScenario|rankScenario|automaticWinner/);
});

test('W7 locale keys remain structurally identical', () => {
  const locales = ['en', 'uz', 'ru', 'ar'].map((locale) => JSON.parse(read(`messages/${locale}/pursuits.json`)));
  const shape = (value, prefix = '') => Object.entries(value).flatMap(([key, child]) => {
    const path = prefix ? `${prefix}.${key}` : key;
    return child && typeof child === 'object' && !Array.isArray(child) ? [path, ...shape(child, path)] : [path];
  }).sort();
  const expected = shape(locales[0].team.scenarios);
  for (const locale of locales.slice(1)) assert.deepEqual(shape(locale.team.scenarios), expected);
});
