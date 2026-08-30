import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { test } from 'node:test';

const root = new URL('../', import.meta.url);
const read = (path) => readFileSync(new URL(path, root), 'utf8');
const redirectPage = read('app/dashboard/hunter/page.tsx');
const explorerPage = read('app/dashboard/tenders/page.tsx');
const explorerClient = read('lib/explorer.ts');
const layout = read('app/dashboard/layout.tsx');
const backendHunter = read('../backend/app/api/endpoints/hunter.py');
const worker = read('../backend/app/workers/hunter_tasks.py');
const celery = read('../backend/app/core/celery_app.py');

test('legacy customer route is a passive compatibility redirect', () => {
    assert.match(redirectPage, /import \{ redirect \} from 'next\/navigation'/);
    assert.match(redirectPage, /redirect\('\/dashboard\/tenders\?view=recommended'\)/);
    for (const forbidden of ['use client', 'api.', 'fetch(', 'useEffect', 'useState', 'Recommendation', 'TenderEngagement', 'Proposal', 'Compliance']) {
        assert.doesNotMatch(redirectPage, new RegExp(forbidden.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
    }
});

test('dead Hunter frontend implementation and types are removed', () => {
    assert.equal(existsSync(new URL('types/hunter.ts', root)), false);
    assert.doesNotMatch(redirectPage, /Hunter Feed|AI-curated|No Recommendations Yet|scanning the market/);
    assert.doesNotMatch(explorerPage, /\/hunter\/|HunterRecommendation|Hunter Feed/);
});

test('unified Explorer remains canonical frontend authority', () => {
    assert.match(explorerClient, /api\.get<ExplorerResponse>\('\/explorer\/tenders'/);
    assert.match(explorerClient, /recommendations\/\$\{recommendationId\}\/dismiss/);
    assert.match(explorerClient, /recommendations\/\$\{recommendationId\}\/restore/);
    assert.doesNotMatch(explorerPage, /api\.get<Tender\[]>\('\/tenders'|\/hunter/);
});

test('primary navigation has no duplicate discovery product', () => {
    assert.match(layout, /name: 'Tenders'/);
    assert.match(layout, /name: 'My Tenders'/);
    assert.match(layout, /name: 'Bid Preparation'/);
    assert.doesNotMatch(layout, /Hunter|AI Hunter|Recommendations.*href/);
});

test('legacy backend APIs remain compatibility-only and share mutation authority', () => {
    assert.match(backendHunter, /@router\.get\(""/);
    assert.match(backendHunter, /@router\.post\([\s\S]*recommendation_id[\s\S]*dismiss/);
    assert.match(backendHunter, /dismiss_owned_recommendation\(/);
    assert.match(backendHunter, /Recommendation not found or access denied/);
    assert.doesNotMatch(backendHunter, /restore/);
});

test('generation owner and document dispatch stay internal and unchanged', () => {
    assert.match(worker, /def run_hunter_sweep/);
    assert.match(worker, /evaluate_tenders_batch/);
    assert.match(worker, /TenderRecommendation\(/);
    assert.match(worker, /process_tender_docs\.delay/);
    assert.match(celery, /run-hunter-sweep-every-30-minutes/);
    assert.match(celery, /app\.workers\.hunter_tasks\.run_hunter_sweep/);
});
