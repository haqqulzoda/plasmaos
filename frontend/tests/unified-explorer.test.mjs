import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import {
    EXPLORER_RETURN_STATE_KEY,
    clearExplorerReturnState,
    readExplorerReturnState,
    writeExplorerReturnState,
} from '../lib/explorerReturnState.ts';

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');
const page = read('app/dashboard/tenders/page.tsx');
const client = read('lib/explorer.ts');
const types = read('types/explorer.ts');
const recommendation = read('components/tenders/RecommendationSummary.tsx');
const layout = read('app/dashboard/layout.tsx');
const hunter = read('app/dashboard/hunter/page.tsx');
const detail = read('app/dashboard/tenders/[tenderId]/page.tsx');
const returnState = read('lib/explorerReturnState.ts');

test('canonical unified request graph', () => {
    assert.match(client, /api\.get<ExplorerResponse>\('\/explorer\/tenders'/);
    assert.match(page, /listExplorer\(\{/);
    assert.doesNotMatch(page, /api\.get<Tender\[]>\('\/tenders'/);
    assert.doesNotMatch(page, /\/hunter\//);
    assert.doesNotMatch(page, /useGeographyMeta|useServiceMeta|refresh-status/);
});

test('explicit types and canonical recommendation commands', () => {
    for (const name of ['ExplorerResponse', 'ExplorerItem', 'ExplorerCounts', 'RecommendationSummary', 'RecommendationAvailability', 'PursuitSummary']) {
        assert.match(types, new RegExp(`(?:interface|type) ${name}`));
    }
    assert.doesNotMatch(types, /\bany\b/);
    assert.match(client, /recommendations\/\$\{recommendationId\}\/dismiss/);
    assert.match(client, /recommendations\/\$\{recommendationId\}\/restore/);
});

test('URL-backed modes, filters, reset, and pagination', () => {
    for (const value of ['all', 'recommended', 'dismissed']) assert.match(page, new RegExp(`'${value}'`));
    for (const name of ['view', 'source', 'countries', 'services', 'deadline_status', 'document_status', 'category', 'price_min', 'price_max', 'q', 'sort', 'page']) assert.match(page, new RegExp(`['\"]${name}['\"]`));
    assert.match(page, /page: resetPage \? 1/);
    assert.match(page, /total \/ response\.limit/);
    assert.match(page, /Page \{query\.page\} of \{lastPage\}/);
    assert.match(page, /defaultSort\(view\)/);
});

test('filtered Explorer return state is shared with Tender Details', () => {
    assert.match(page, /writeExplorerReturnState\(\{ explorerUrl: explorerHref/);
    assert.match(page, /readExplorerReturnState\(\)/);
    assert.match(detail, /readExplorerReturnState\(\)/);
    assert.match(returnState, /plasmaos:tender-explorer:return/);
    assert.doesNotMatch(page, /tender-explorer-restore|JSON\.stringify\(\{ tenderId: tender\.id, href/);
});

test('filtered Explorer return state round-trips and rejects unsafe paths', () => {
    const values = new Map();
    const previousWindow = globalThis.window;
    globalThis.window = {
        sessionStorage: {
            getItem: (key) => values.get(key) ?? null,
            setItem: (key, value) => values.set(key, value),
            removeItem: (key) => values.delete(key),
        },
    };
    try {
        const state = {
            explorerUrl: '/dashboard/tenders?view=recommended&source=world_bank&q=water&page=2',
            tenderId: 'tender-42',
            scrollY: 640,
            page: 2,
            createdAt: 1_000,
        };
        writeExplorerReturnState(state);
        assert.deepEqual(readExplorerReturnState(), state);
        clearExplorerReturnState();
        assert.equal(readExplorerReturnState(), null);

        values.set(EXPLORER_RETURN_STATE_KEY, JSON.stringify({ ...state, explorerUrl: 'https://example.invalid/dashboard/tenders' }));
        assert.equal(readExplorerReturnState(), null);
        assert.equal(values.has(EXPLORER_RETURN_STATE_KEY), false);
    } finally {
        if (previousWindow === undefined) delete globalThis.window;
        else globalThis.window = previousWindow;
    }
});

test('authoritative refresh and stale-response protection', () => {
    assert.match(page, /AbortController/);
    assert.match(page, /requestSequence/);
    assert.match(page, /setRefreshVersion/);
    assert.doesNotMatch(page, /setResponse\([^\n]*(filter|map)/);
    assert.match(page, /query\.page > finalPage/);
});

test('truthful recommendation presentation', () => {
    assert.match(recommendation, /Match score/);
    assert.match(recommendation, /Why this may match/);
    assert.match(recommendation, /Recommended on/);
    assert.match(recommendation, /Dismiss recommendation/);
    assert.match(recommendation, /Restore recommendation/);
    for (const forbidden of ['Win probability', 'Chance to win', 'Guaranteed', 'Last refreshed', 'Updated recommendation', 'Dismiss Tender']) assert.doesNotMatch(recommendation, new RegExp(forbidden, 'i'));
});

test('empty and profile-required states are truthful', () => {
    for (const copy of ['No tenders match these filters.', 'No recommendations match your current filters.', 'No active recommendations.', 'No dismissed recommendations.', 'Complete your company profile']) assert.match(page, new RegExp(copy.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
    assert.doesNotMatch(page, /AI is analyzing your profile|Recommendations are generating|Check back soon/);
});

test('pursuit is independent and uses shared workflow actions', () => {
    assert.match(page, /Pursuit: \{engagementStatusLabel/);
    assert.match(page, /EngagementWorkflowActions/);
    assert.match(page, /allowed_actions: pursuit\.allowed_actions/);
    assert.match(page, /PrepareBidButton/);
    assert.doesNotMatch(page, /recommendation[^\n]*(engagement|proposal|compliance)/i);
});

test('canonical navigation converges while Hunter compatibility remains', () => {
    assert.match(layout, /href: '\/dashboard\/tenders'/);
    assert.match(layout, /href: '\/dashboard\/my-tenders'/);
    assert.doesNotMatch(layout, /href: '\/dashboard\/hunter'/);
    assert.match(hunter, /redirect\('\/dashboard\/tenders\?view=recommended'\)/);
    assert.doesNotMatch(hunter, /api\.|useEffect|useState|HunterRecommendation/);
});

test('accessibility and responsive contracts are present', () => {
    for (const token of ['role="tablist"', 'role="tab"', 'aria-selected', 'aria-live="polite"', 'role="alert"', 'aria-label="Tender result pages"', 'focus-visible', 'overflow-x-auto', 'sm:', 'xl:']) assert.match(page, new RegExp(token.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
    assert.match(recommendation, /type="button"/);
    assert.match(recommendation, /aria-label=/);
});
