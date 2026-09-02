import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
    classifyProjectContextFailure,
    projectFreshnessMessage,
    projectMetadataRows,
    projectRoleLabel,
} from '../types/project.ts';


const pageSource = readFileSync(
    new URL('../app/dashboard/tenders/[tenderId]/page.tsx', import.meta.url),
    'utf8',
);

const project = (overrides = {}) => ({
    id: 'internal-project-uuid',
    source_system: 'world_bank',
    external_project_id: 'P179267',
    name: 'Regional Solar Project',
    country: 'Liberia',
    region: 'Western and Central Africa',
    status: 'Active',
    approval_date: '2022-12-20',
    closing_date: '2027-06-30',
    borrower: 'Republic of Liberia',
    implementing_agencies: ['Liberia Electricity Corporation'],
    source_url: 'https://projects.worldbank.org/project/P179267',
    enrichment_status: 'successful',
    last_successful_enrichment_at: '2026-08-26T12:00:00Z',
    source_freshness: 'fresh',
    ...overrides,
});

const role = (canonicalRole, nativeRole = canonicalRole) => ({
    canonical_role: canonicalRole,
    native_role: nativeRole,
    source_system: 'world_bank',
});

const projectSectionSource = pageSource
    .split('<SectionShell id="project-context"', 2)[1]
    .split('<SectionShell id="requirements-documents"', 1)[0];

test('no Project has an explicit consolidated empty state', () => {
    assert.match(projectSectionSource, /No canonical Project is linked to this Tender/);
});

test('linked not-enriched identity remains visible while details prepare', () => {
    assert.equal(projectFreshnessMessage('pending'), 'Project details are being prepared.');
    assert.match(projectSectionSource, /project\.external_project_id/);
    assert.match(projectSectionSource, /Project details are being prepared/);
});

test('enriched metadata renders only meaningful rows', () => {
    const rows = projectMetadataRows(project());
    assert.deepEqual(rows.map((row) => row.label), [
        'Country / Region',
        'Project Status',
        'Project Approval',
        'Project Closing',
        'Borrower',
        'Implementing Agency',
    ]);
});

test('missing metadata is omitted instead of rendered as placeholders', () => {
    assert.deepEqual(projectMetadataRows(project({
        country: null,
        region: null,
        status: null,
        approval_date: null,
        closing_date: null,
        borrower: null,
        implementing_agencies: null,
    })), []);
    assert.doesNotMatch(projectSectionSource, /['"]N\/A['"]|['"]undefined['"]|['"]null['"]/);
});

test('current leadership is visible under the locked section label', () => {
    assert.match(projectSectionSource, />Project Leadership</);
    assert.match(projectSectionSource, /currentRoles\.map/);
});

test('historical leadership is separate and keyboard-accessible', () => {
    assert.match(projectSectionSource, /<details/);
    assert.match(projectSectionSource, /<summary/);
    assert.match(projectSectionSource, /Previous project leadership/);
    assert.match(projectSectionSource, /historicalRoles\.map/);
});

test('Task Team Leader canonical label is exact', () => {
    assert.equal(projectRoleLabel(role('TASK_TEAM_LEADER', 'Task Team Leader')), 'Task Team Leader');
});

test('Co-Task Team Leader canonical label is exact', () => {
    assert.equal(projectRoleLabel(role('CO_TASK_TEAM_LEADER', 'Co-Task Team Leader')), 'Co-Task Team Leader');
});

test('Task Manager canonical label is exact and not TTL', () => {
    assert.equal(projectRoleLabel(role('PROJECT_TASK_MANAGER', 'Task Manager')), 'Task Manager');
});

test('teamleadname never renders as TTL', () => {
    const label = projectRoleLabel(role('OTHER_PROJECT_ROLE', 'teamleadname'), 'World Bank');
    assert.equal(label, 'World Bank project team');
    assert.doesNotMatch(label, /Task Team Leader|\bTTL\b|Co-TTL/i);
});

test('no leadership email is inferred or replaced with a placeholder', () => {
    assert.doesNotMatch(projectSectionSource, /role\.email|mailto:|email format/);
});

test('procurement contact remains an explicitly separate Tender section', () => {
    assert.match(pageSource, /title="Procurement Contacts"/);
    assert.match(pageSource, /not Project Leadership/);
    assert.match(projectSectionSource, /not the Tender&apos;s procurement contact/);
});

test('Project dates have explicit non-deadline labels', () => {
    const labels = projectMetadataRows(project()).map((row) => row.label);
    assert.ok(labels.includes('Project Approval'));
    assert.ok(labels.includes('Project Closing'));
    assert.ok(!labels.includes('Tender Deadline'));
});

test('Project status presentation does not use Tender actionability helpers', () => {
    assert.doesNotMatch(projectSectionSource, /isTenderActionable|tenderStatusLabel|TenderStatus/);
});

test('stale and partial states use restrained truthful messages', () => {
    assert.equal(projectFreshnessMessage('stale'), 'Project information may be outdated.');
    assert.equal(projectFreshnessMessage('incomplete'), 'Some project information is unavailable.');
    assert.equal(projectFreshnessMessage('unavailable'), 'Official project data is currently unavailable.');
    assert.notEqual(
        projectFreshnessMessage('unavailable'),
        'Project details are temporarily unavailable.',
    );
    assert.equal(projectFreshnessMessage('fresh'), null);
});

test('Project API failure is isolated from the Tender load', () => {
    assert.match(pageSource, /const loadTender = useCallback/);
    assert.match(pageSource, /const loadDetails = useCallback/);
    assert.match(pageSource, /useEffect\(\(\) => \{ void loadTender\(\); \}, \[loadTender\]\)/);
    assert.match(pageSource, /useEffect\(\(\) => \{ void loadDetails\(\); \}, \[loadDetails\]\)/);
    assert.match(pageSource, /detailsError \?/);
    assert.match(pageSource, /The source opportunity above remains available/);
});

test('Project HTTP outcomes remain semantically distinct', () => {
    assert.equal(classifyProjectContextFailure(404), 'no_project');
    assert.equal(classifyProjectContextFailure(401), 'authorization');
    assert.equal(classifyProjectContextFailure(403), 'authorization');
    assert.equal(classifyProjectContextFailure(500), 'endpoint_failure');
    assert.equal(classifyProjectContextFailure(undefined), 'endpoint_failure');
});

test('source and status semantics are accessible and responsive', () => {
    assert.match(pageSource, /<SectionShell id="project-context"/);
    assert.match(pageSource, /aria-labelledby=\{`\$\{id\}-heading`\}/);
    assert.match(projectSectionSource, /role="status"/);
    assert.match(projectSectionSource, /sm:grid-cols-2/);
    assert.match(projectSectionSource, /lg:grid-cols-4/);
});
