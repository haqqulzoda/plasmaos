import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');

test('pack review is explicit and submits exact selected identities', () => {
  const source = read('components/pursuits/PursuitRequirements.tsx');
  assert.match(source, /analysis-pack-candidate/);
  assert.match(source, /selectedSource/);
  assert.match(source, /selectedPrivate/);
  assert.match(source, /source_document_ids/);
  assert.match(source, /private_version_ids/);
  assert.match(source, /candidate_sha256/);
  assert.match(source, /Analyze selected|analyzeSelected/);
  assert.doesNotMatch(source, /useEffect[\s\S]{0,300}api\.post/);
});

test('requirements UI exposes canonical states and evidence before interpretation', () => {
  const source = read('components/pursuits/PursuitRequirements.tsx');
  const types = read('types/pursuit.ts');
  for (const state of ['SUPPORTED','PARTIAL','GAP','EVIDENCE_MISSING','NEEDS_INTERPRETATION','NOT_APPLICABLE','LATER_STAGE_OBLIGATION']) {
    assert.match(types, new RegExp(state));
  }
  const card = source.slice(source.indexOf('function RequirementCard'));
  assert.ok(card.indexOf('analysis-quote') < card.indexOf('data-generated-interpretation'));
  assert.match(source, /original_quote/);
  assert.match(source, /effective_normalized_requirement/);
  assert.match(source, /effective_title/);
  assert.match(source, /Required positions|requiredPositions/);
});

test('W4 avoids scores and future candidate actions', () => {
  const source = read('components/pursuits/PursuitRequirements.tsx');
  assert.doesNotMatch(source, /compliance percentage|readiness percentage|risk score|match score/i);
  assert.doesNotMatch(source, /Find Partner|Find Expert|TeamScenario|Availability|Commitment/);
  assert.match(source, /resolutionTypes/);
});

test('analysis locale is independent and constrained to EN UZ RU', () => {
  const source = read('components/pursuits/PursuitRequirements.tsx');
  assert.match(source, /option value="en"/);
  assert.match(source, /option value="uz"/);
  assert.match(source, /option value="ru"/);
  assert.doesNotMatch(source, /option value="ar"/);
  assert.match(source, /analysis_language: language/);
});

test('review records corrections without changing source evidence fields', () => {
  const source = read('components/pursuits/PursuitRequirements.tsx');
  assert.match(source, /analysis-runs\/\$\{runId\}\/reviews/);
  assert.match(source, /corrected_fields/);
  assert.match(source, /new_coverage_state/);
  assert.doesNotMatch(source, /corrected_fields:[\s\S]{0,100}original_quote/);
});
