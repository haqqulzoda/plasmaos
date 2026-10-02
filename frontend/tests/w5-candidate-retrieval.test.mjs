import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');

test('Team retrieval starts only through an explicit reviewed-gap action', () => {
  const source = read('components/pursuits/PursuitTeam.tsx');
  assert.match(source, /effective_review_state/);
  assert.match(source, /PARTNER_FIRM/);
  assert.match(source, /EXPERT/);
  assert.match(source, /candidate-search-runs/);
  assert.match(source, /Find candidates|findCandidates/);
  assert.doesNotMatch(source, /useEffect[\s\S]{0,400}api\.post/);
});

test('candidate states remain evidence states rather than percentages', () => {
  const source = read('components/pursuits/PursuitTeam.tsx');
  const types = read('types/pursuit.ts');
  for (const state of ['SUPPORTED_BY_EVIDENCE', 'PARTIAL', 'EVIDENCE_MISSING', 'NEEDS_REVIEW', 'NOT_RELEVANT']) {
    assert.match(types, new RegExp(state));
  }
  assert.doesNotMatch(source, /match percentage|qualification probability|risk score/i);
  assert.match(source, /strongest_evidence/);
  assert.match(source, /missing_or_weak_evidence/);
});

test('candidate review is append-only through dedicated review endpoints', () => {
  const source = read('components/pursuits/PursuitTeam.tsx');
  assert.match(source, /matches\/\$\{match\.candidate_match_id\}\/reviews/);
  for (const decision of ['SHORTLISTED', 'REJECTED', 'MORE_EVIDENCE_REQUESTED', 'IRRELEVANT', 'CONTRIBUTION_CORRECTED']) {
    assert.match(source, new RegExp(decision));
  }
  assert.doesNotMatch(source, /analysis-runs\/\$\{[^}]+\}\/reviews/);
});

test('candidate retrieval does not introduce outreach authority', () => {
  const source = read('components/pursuits/PursuitTeam.tsx');
  const types = read('types/pursuit.ts');
  for (const forbidden of ['commitment_state', 'outbound_invitation', 'sendInvitation']) {
    assert.doesNotMatch(source + types, new RegExp(forbidden, 'i'));
  }
});

test('library exposes safe structured records only when records exist', () => {
  const team = read('components/pursuits/PursuitTeam.tsx');
  // D2-02: the library page composes the three tab components.
  const library = read('app/dashboard/partners-experts/page.tsx') + read('components/library/LibraryTabs.tsx')
    + read('components/library/LibraryParts.tsx');
  assert.match(team, /hasLibrary &&/);
  assert.match(library, /project_references/);
  assert.match(library, /cv_versions/);
  assert.doesNotMatch(library, /private_notes|rate|relationship_history|cv_bytes/i);
});

test('pursuit workspace includes the Partners and Experts Team section', () => {
  const page = read('app/dashboard/pursuits/[pursuitId]/page.tsx');
  assert.match(page, /PursuitTeam/);
  assert.match(page, /workspace\.team/);
});

