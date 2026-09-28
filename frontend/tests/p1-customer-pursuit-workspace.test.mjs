import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');

test('P1 uses five customer-facing tabs with one mounted decision surface', () => {
  const page = read('app/dashboard/pursuits/[pursuitId]/page.tsx');
  assert.match(page, /WORKSPACE_TABS = \['overview', 'requirements', 'team', 'documents', 'proposal'\]/);
  assert.match(page, /role="tablist"/);
  assert.match(page, /role="tabpanel"/);
  assert.match(page, /activeTab === 'requirements'.*PursuitRequirements/s);
  assert.match(page, /activeTab === 'team'.*PursuitTeam/s);
  assert.match(page, /activeTab === 'proposal'.*PursuitProposal/s);
  assert.doesNotMatch(page, /['"]activity['"]/i);
});

test('P1 overview is derived from extraction and preserves source project sections', () => {
  const page = read('app/dashboard/pursuits/[pursuitId]/page.tsx');
  for (const signal of ['isSubmissionItem', 'isEvaluationItem', 'isLaterStage', 'project_context', 'project_leadership']) {
    assert.match(page, new RegExp(signal));
  }
  assert.match(page, /reviewableAnalysis\?\.requirements/);
  assert.doesNotMatch(page, /Communications Consultant|Town of University Park|UP-2012-01/);
});

test('P1 async analysis is nonblocking and retains a previous successful result', () => {
  const requirements = read('components/pursuits/PursuitRequirements.tsx');
  for (const value of ['lastReadyAnalysis', 'analysisRunning', 'analysisFailed', 'previousResultVisible', 'retryAnalysis']) {
    assert.match(requirements, new RegExp(value));
  }
  assert.doesNotMatch(requirements, /failure_reason/);
  assert.ok(requirements.indexOf('sourceEvidence') < requirements.indexOf('generatedInterpretation'));
  assert.ok(requirements.indexOf('sourceRequirement') < requirements.indexOf('plasmaAssessment'));
  assert.ok(requirements.indexOf('plasmaAssessment') < requirements.indexOf('organizationEvidence'));
});

test('P1 team and proposal progressively disclose actions in customer language', () => {
  const team = read('components/pursuits/PursuitTeam.tsx');
  const proposal = read('components/pursuits/PursuitProposal.tsx');
  const english = JSON.parse(read('messages/en/pursuits.json'));
  assert.match(team, /participation\.length > 0 \? <ScenarioWorkspace/);
  assert.match(team, /noTeamNeeds/);
  assert.doesNotMatch(team, /<BidiText>\{item\.gap_id\}<\/BidiText>/);
  assert.match(proposal, /evidenceManifest/);
  assert.match(proposal, /proposal-manifest.*technicalDetails/s);
  assert.equal(english.team.scenarios.title, 'Team options');
  assert.equal(english.requirements.packTitle, 'Choose documents to analyze');
  assert.equal(english.requirements.currentGaps, 'What needs attention');
  assert.equal(english.workspace.analysisEyebrow, 'Tender analysis');
  assert.equal(english.proposal.seal, 'Create evidence pack');
  assert.equal(english.proposal.evidenceManifest, 'Evidence manifest');
  const customerValues = JSON.stringify(english);
  for (const internalPhrase of ['Sealed analysis', 'Review analysis pack', 'Current-stage gaps', 'Candidate total:', 'Upstream W4/W5 chain']) {
    assert.doesNotMatch(customerValues, new RegExp(internalPhrase, 'i'));
  }
});

test('P1 locale catalogs have exact structural parity', () => {
  const locales = ['en', 'uz', 'ru', 'ar'].map((locale) => JSON.parse(read(`messages/${locale}/pursuits.json`)));
  const shape = (value, prefix = '') => Object.entries(value).flatMap(([key, child]) => {
    const path = prefix ? `${prefix}.${key}` : key;
    return child && typeof child === 'object' && !Array.isArray(child) ? [path, ...shape(child, path)] : [path];
  }).sort();
  const expected = shape(locales[0]);
  for (const locale of locales.slice(1)) assert.deepEqual(shape(locale), expected);
});

test('P1 responsive and keyboard contracts cover compact mobile and RTL-safe tabs', () => {
  const page = read('app/dashboard/pursuits/[pursuitId]/page.tsx');
  const css = read('components/customer/pages.css');
  const browser = read('tests/release-hardening-browser.py');
  assert.match(page, /ArrowLeft/);
  assert.match(page, /ArrowRight/);
  assert.match(page, /getComputedStyle\(event\.currentTarget\)\.direction/);
  assert.match(css, /@media \(max-width: 390px\)/);
  assert.match(css, /proposal-matrix[\s\S]+attr\(data-label\)/);
  assert.match(css, /min-block-size: 44px/);
  assert.match(browser, /window\.axe\.run\(document\)/);
  assert.match(browser, /'serious', 'critical'/);
});
