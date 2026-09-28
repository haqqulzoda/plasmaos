import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');

test('analysis summary separates processing from extraction quality', () => {
  const source = read('components/pursuits/PursuitRequirements.tsx');
  const types = read('types/pursuit.ts');
  for (const state of ['READY_FOR_REVIEW', 'NEEDS_ATTENTION', 'FAILED']) {
    assert.match(types, new RegExp(state));
  }
  assert.match(source, /analysis\.quality_state/);
  assert.match(source, /processingStatus/);
  assert.match(source, /qualityStatus/);
  assert.match(source, /analysis\.quality_summary/);
  assert.match(source, /technicalDetails/);
});

test('empty or anomalous extraction cannot claim there are no gaps', () => {
  const source = read('components/pursuits/PursuitRequirements.tsx');
  assert.match(source, /qualityReady && <section[^>]+analysis-current-gaps/);
  assert.match(source, /needsAttentionHelp/);
  assert.match(source, /reviewAnalysis/);
  assert.match(source, /rerunAnalysis/);
  assert.ok(source.indexOf('qualityReady && <section') < source.indexOf("t('noCurrentGaps')"));
});

test('next action derives from the authoritative workflow projections', () => {
  const source = read('app/dashboard/pursuits/[pursuitId]/page.tsx');
  for (const state of [
    'chooseDocuments', 'analysisInProgress', 'analysisNeedsAttention',
    'reviewRequirementsGaps', 'reviewPartnerExpertOptions', 'prepareEvidencePack',
  ]) assert.match(source, new RegExp(state));
  assert.match(source, /analysis\.quality_state/);
  assert.match(source, /APPROVED_FOR_PROPOSAL/);
  assert.match(source, /current_assessment_state === 'VIABLE'/);
});

test('source conflicts and historical deadlines remain visible without overwrite', () => {
  const source = read('app/dashboard/pursuits/[pursuitId]/page.tsx');
  const types = read('types/pursuit.ts');
  assert.match(types, /USER_OVERRIDE_CONFLICTS_WITH_SOURCE/);
  assert.match(source, /contextConflicts/);
  assert.match(source, /userConfirmed/);
  assert.match(source, /sourceIndicates/);
  assert.match(source, /historicalDeadline/);
  assert.doesNotMatch(source, /reviewConflict[^\n]+setContextValues/);
});

test('position criteria preserve mandatory preferred and desired distinctions', () => {
  const source = read('components/pursuits/PursuitRequirements.tsx');
  const types = read('types/pursuit.ts');
  assert.match(source, /qualification_criteria/);
  assert.match(source, /qualificationDistinctions/);
  assert.match(types, /'MANDATORY' \| 'PREFERRED' \| 'DESIRED'/);
});
