import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
    engagementStatusDescription,
    engagementStatusLabel,
} from '../types/engagement.ts';

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');
const actions = read('components/tenders/EngagementWorkflowActions.tsx');
const panel = read('components/tenders/TenderEngagementPanel.tsx');
const myTenders = read('app/dashboard/my-tenders/page.tsx');
const tenderDetail = read('app/dashboard/tenders/[tenderId]/page.tsx');
const preparation = read('app/dashboard/bid-preparation/[proposalId]/page.tsx');

test('every canonical status has concise non-color meaning', () => {
    for (const status of ['SAVED', 'EVALUATING', 'PREPARING', 'SUBMITTED', 'WON', 'LOST', 'DISMISSED']) {
        assert.ok(engagementStatusLabel(status));
        assert.match(engagementStatusDescription(status), /\.$/);
    }
});

test('high-significance actions use confirmation and exact semantics', () => {
    assert.match(actions, /role="dialog"/);
    assert.match(actions, /aria-modal="true"/);
    assert.match(actions, /Mark as Submitted/);
    assert.match(actions, /You are recording that this bid was submitted/);
    assert.match(actions, /Record as Won/);
    assert.match(actions, /Record as Lost/);
    assert.match(actions, /Correct status to Preparing/);
    assert.doesNotMatch(actions, /Submit Bid|Submit Tender/);
});

test('commands send expected state and refresh authoritative backend truth', () => {
    assert.match(actions, /expected_status: engagement\.engagement_status/);
    assert.match(actions, /Status changed\. We refreshed the latest state\./);
    assert.match(actions, /await onRefresh\?\.\(\)/);
    assert.match(myTenders, /setRefreshVersion/);
});

test('Tender Details and Bid Preparation share the compact pursuit panel', () => {
    assert.match(tenderDetail, /<TenderEngagementPanel tenderId=\{tender\.id\}/);
    assert.match(preparation, /<TenderEngagementPanel tenderId=\{proposal\.tender_id\} proposalContext/);
    assert.match(panel, /Open My Tenders/);
    assert.match(panel, /Open Bid Preparation/);
});

test('legacy proposal is continued only by explicit click', () => {
    const effect = panel.split('useEffect', 2)[1].split('const save', 1)[0];
    assert.doesNotMatch(effect, /api\.post/);
    assert.match(panel, /proposalId=\{proposalId\} label="Continue Bid Preparation"/);
});

test('source and engagement semantics remain independent', () => {
    assert.match(myTenders, /Engagement: \{engagementStatusLabel/);
    assert.match(myTenders, /Tender: \{tenderStatusLabel/);
    assert.doesNotMatch(actions, /tender_status|deadline|ProposalArtifactStatus|compliance/i);
});
