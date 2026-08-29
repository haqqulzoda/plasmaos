import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
    engagementStatusClasses,
    engagementStatusLabel,
} from '../types/engagement.ts';

const page = readFileSync(
    new URL('../app/dashboard/my-tenders/page.tsx', import.meta.url),
    'utf8',
);
const pursuitPanel = readFileSync(
    new URL('../components/tenders/TenderEngagementPanel.tsx', import.meta.url),
    'utf8',
);
const layout = readFileSync(
    new URL('../app/dashboard/layout.tsx', import.meta.url),
    'utf8',
);

test('all canonical statuses use customer language and visible text', () => {
    const expected = {
        SAVED: 'Saved',
        EVALUATING: 'Evaluating',
        PREPARING: 'Preparing',
        SUBMITTED: 'Submitted',
        WON: 'Won',
        LOST: 'Lost',
        DISMISSED: 'Dismissed',
    };
    for (const [status, label] of Object.entries(expected)) {
        assert.equal(engagementStatusLabel(status), label);
        assert.ok(engagementStatusClasses(status).includes('text-'));
    }
    assert.notEqual(engagementStatusLabel('PREPARING'), 'Draft');
});

test('My Tenders is engagement-only, bounded, and URL-driven', () => {
    assert.match(page, /api\.get<MyTendersListResponse>\('\/my-tenders'/);
    assert.match(page, /PAGE_SIZE = 25/);
    assert.match(page, /useSearchParams/);
    assert.match(page, /status/);
    assert.match(page, /search/);
    assert.match(page, /sort/);
    assert.match(page, /page/);
    assert.doesNotMatch(page, /\/proposals|Proposal|compliance|Hunter|Recommendation/);
});

test('engagement and source status are separately labeled and accessible', () => {
    assert.match(page, /Engagement: \{engagementStatusLabel/);
    assert.match(page, /Tender: \{tenderStatusLabel/);
    assert.match(page, /aria-label="Engagement and tender statuses"/);
    assert.match(page, /focus-visible:ring/);
    assert.match(page, /role="status"/);
    assert.match(page, /role="alert"/);
});

test('empty state is truthful and never imports legacy bids', () => {
    assert.match(page, /No tenders saved yet/);
    assert.match(page, /Explore Tenders/);
    assert.doesNotMatch(page, /no bids|legacy proposals/i);
});

test('save happens only in explicit click handler and represents re-engagement', () => {
    const effect = pursuitPanel.split('useEffect(() =>', 2)[1].split('const save =', 1)[0];
    assert.doesNotMatch(effect, /api\.post/);
    assert.match(pursuitPanel, /const save = async/);
    assert.match(pursuitPanel, /api\.post<SaveToMyTendersResponse>/);
    assert.match(pursuitPanel, /onClick=\{save\}/);
    assert.match(pursuitPanel, /Save to My Tenders/);
});

test('navigation exposes My Tenders and Bid Preparation separately', () => {
    assert.match(layout, /name: 'My Tenders'/);
    assert.match(layout, /name: 'Bid Preparation'/);
    assert.doesNotMatch(layout, /name: 'My Bids'/);
});
