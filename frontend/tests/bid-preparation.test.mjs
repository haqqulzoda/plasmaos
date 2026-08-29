import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');
const layout = read('app/dashboard/layout.tsx');
const list = read('app/dashboard/bid-preparation/page.tsx');
const detail = read('app/dashboard/bid-preparation/[proposalId]/page.tsx');
const legacyList = read('app/dashboard/bids/page.tsx');
const legacyDetail = read('app/dashboard/bids/[id]/page.tsx');
const legacyProposals = read('app/dashboard/proposals/page.tsx');
const legacyWorkspace = read('app/dashboard/workspace/page.tsx');
const prepareButton = read('components/bid-preparation/PrepareBidButton.tsx');
const compliance = read('app/dashboard/tenders/[tenderId]/compliance/page.tsx');

test('canonical customer navigation is Bid Preparation', () => {
    assert.match(layout, /name: 'Bid Preparation'/);
    assert.match(layout, /href: '\/dashboard\/bid-preparation'/);
    assert.doesNotMatch(layout, /name: 'My Bids'/);
});

test('legacy list is a single read-only redirect', () => {
    assert.match(legacyList, /permanentRedirect\('\/dashboard\/bid-preparation'\)/);
    assert.doesNotMatch(legacyList, /api\.|\/proposals|post\(/);
});

test('legacy proposal list and workspace are permanent non-mutating redirects', () => {
    assert.match(legacyProposals, /permanentRedirect\('\/dashboard\/bid-preparation'\)/);
    assert.match(legacyWorkspace, /permanentRedirect\('\/dashboard\/tenders'\)/);
    assert.doesNotMatch(`${legacyProposals}\n${legacyWorkspace}`, /api\.|post\(|put\(|patch\(|delete\(/);
});

test('canonical dynamic route is Proposal-ID-only and passive', () => {
    assert.match(detail, /Promise<\{ proposalId: string \}>/);
    assert.match(detail, /`\/proposals\/\$\{resolvedParams\.proposalId\}`/);
    assert.doesNotMatch(detail, /resolvedParams\.id|tender ID|tender_id: resolvedParams|api\.post<\{ id: string \}>\('\/proposals'/);
    assert.doesNotMatch(detail, /sync-docs|sync-status|pollTenderDocumentSync|TenderSyncJob/);
    assert.match(detail, /api\.get<TenderDocument\[\]>\(`\/tenders\/\$\{tenderId\}\/documents`\)/);
});

test('legacy detail validates the owned Proposal then redirects without fallback', () => {
    assert.match(legacyDetail, /api\.get\(`\/proposals\/\$\{id\}`\)/);
    assert.match(legacyDetail, /router\.replace\(`\/dashboard\/bid-preparation\/\$\{id\}`\)/);
    assert.doesNotMatch(legacyDetail, /api\.post|tender_id|\/tenders\//);
});

test('Prepare Bid is an explicit POST with separate Tender and Proposal identifiers', () => {
    assert.match(prepareButton, /onClick=\{prepare\}/);
    assert.match(prepareButton, /\/proposals\/prepare/);
    assert.match(prepareButton, /\/proposals\/\$\{proposalId\}\/continue/);
    assert.doesNotMatch(prepareButton, /useEffect/);
});

test('Bid Preparation list remains Proposal-backed with optional engagement context', () => {
    assert.match(list, /api\.get\('\/proposals'\)/);
    assert.match(list, /proposal\.engagement_status/);
    assert.match(list, /Continue Bid Preparation/);
    assert.doesNotMatch(list, /\/my-tenders/);
});

test('Compliance page no longer creates or resolves Proposal artifacts passively', () => {
    assert.doesNotMatch(compliance, /api\.post\('\/proposals'|\/proposals\/\$\{tenderId\}|proposal ID from/);
});

test('canonical detail return links use their domain identifiers', () => {
    assert.match(detail, /href=\{`\/dashboard\/tenders\/\$\{proposal\.tender_id\}`\}/);
    assert.match(compliance, /href=\{`\/dashboard\/tenders\/\$\{tenderId\}`\}/);
});
