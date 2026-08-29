import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const pageSource = readFileSync(
    new URL('../app/dashboard/tenders/[tenderId]/page.tsx', import.meta.url),
    'utf8',
);
const panelSource = readFileSync(
    new URL('../components/tenders/TenderEngagementPanel.tsx', import.meta.url),
    'utf8',
);
const dtoSource = readFileSync(new URL('../types/tender-details.ts', import.meta.url), 'utf8');

test('initial render has exactly the two approved passive reads', () => {
    assert.match(pageSource, /api\.get<Tender>\(`\/tenders\/\$\{tenderId\}`\)/);
    assert.match(pageSource, /api\.get<TenderDetailsResponse>\(`\/tenders\/\$\{tenderId\}\/details`\)/);
    assert.equal((pageSource.match(/api\.get</g) ?? []).length, 2);
    assert.doesNotMatch(pageSource, /decision-snapshot|\/competitors|\/engagement|`\/tenders\/\$\{tenderId\}\/project`/);
});

test('document content is fetched only from an explicit user action', () => {
    assert.match(pageSource, /onClick=\{\(\) => void openDocument\(item\)\}/);
    assert.match(pageSource, /`\/tenders\/documents\/\$\{item\.document_id\}\/download`/);
    assert.doesNotMatch(pageSource, /useEffect\([\s\S]{0,250}openDocument/);
});

test('base and consolidated detail loading are independent', () => {
    assert.match(pageSource, /const \[detailsError, setDetailsError\]/);
    assert.match(pageSource, /The source opportunity above remains available/);
    assert.match(pageSource, /Retry details/);
    assert.match(pageSource, /void loadTender\(\)/);
    assert.match(pageSource, /void loadDetails\(\)/);
});

test('sections and anchors follow the locked information hierarchy', () => {
    const anchors = ['#pursuit', '#project-context', '#requirements-documents', '#compliance-readiness', '#contacts', '#bid-preparation'];
    let cursor = -1;
    for (const anchor of anchors) {
        const next = pageSource.indexOf(`href: '${anchor}'`);
        assert.ok(next > cursor, `${anchor} must be present and ordered`);
        cursor = next;
    }
    assert.match(pageSource, /aria-label="Tender detail sections"/);
    assert.match(pageSource, /scroll-mt-28/);
});

test('Tender, Pursuit, Project Leadership, and Procurement Contacts remain distinct', () => {
    assert.match(pageSource, /Tender status/);
    assert.match(panelSource, />Pursuit<\/h2>/);
    assert.match(pageSource, /Project Leadership/);
    assert.match(pageSource, /title="Procurement Contacts"/);
    assert.match(pageSource, /not Project Leadership/);
});

test('the pursuit panel consumes consolidated state without its legacy passive GET', () => {
    assert.match(pageSource, /engagementData=\{pursuit\}/);
    assert.match(pageSource, /proposalIdData=\{bidPreparation\?\.proposal_id/);
    assert.match(panelSource, /const controlled = engagementData !== undefined/);
    assert.match(panelSource, /if \(controlled\) \{[\s\S]{0,100}return;/);
    assert.match(panelSource, /onRefresh/);
});

test('existing mutation authorities and backend-provided allowed actions are reused', () => {
    assert.match(panelSource, /EngagementWorkflowActions/);
    assert.match(dtoSource, /allowed_actions: EngagementAction\[\]/);
    assert.match(pageSource, /const actionable = isTenderActionable\(tender\)/);
    assert.match(pageSource, /canStartNew=\{actionable\}/);
    assert.doesNotMatch(pageSource, /api\.(post|put|patch|delete)/);
});

test('requirements are bounded and provenance-labelled', () => {
    assert.match(pageSource, /AI-extracted requirement/);
    assert.match(pageSource, /document_name/);
    assert.match(pageSource, /item\.section/);
    assert.match(pageSource, /page \$\{item\.page\}/);
});

test('compliance presentation distinguishes failed, partial, and legacy analysis', () => {
    assert.match(pageSource, /Analysis failed/);
    assert.match(pageSource, /Partial analysis/);
    assert.match(pageSource, /Legacy analysis/);
    assert.match(pageSource, /version_origin === 'LEGACY_BACKFILL'/);
    assert.match(pageSource, /Open Compliance/);
});

test('readiness shows factual counts and does not invent a score', () => {
    assert.match(pageSource, /No readiness percentage is calculated/);
    assert.match(pageSource, /Certifications/);
    assert.match(pageSource, /Missing evidence/);
    assert.doesNotMatch(pageSource, /readiness_score|readiness_percentage/);
});

test('bid preparation uses the proposal-backed route identifier', () => {
    assert.match(pageSource, /`\/dashboard\/bid-preparation\/\$\{bidPreparation\.detail_route_id\}`/);
    assert.doesNotMatch(pageSource, /`\/dashboard\/bid-preparation\/\$\{tender\.id\}`/);
});

test('DTOs are explicit and prohibit loose any or derived browser persistence', () => {
    assert.match(dtoSource, /export interface TenderDetailsResponse/);
    assert.match(dtoSource, /interface DetailsSection<T>/);
    assert.doesNotMatch(dtoSource, /\bany\b|localStorage|sessionStorage/);
    assert.doesNotMatch(pageSource, /localStorage\.setItem|sessionStorage\.setItem/);
});

test('responsive and keyboard-accessible controls are present', () => {
    assert.match(pageSource, /overflow-x-auto/);
    assert.match(pageSource, /focus-visible:ring-2/);
    assert.match(pageSource, /sm:grid-cols|lg:grid-cols/);
    assert.match(pageSource, /aria-live="polite"/);
    assert.match(pageSource, /role="alert"/);
});
