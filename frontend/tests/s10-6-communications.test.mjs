import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { notificationDestination, notificationQuery, SYSTEM_TEMPLATE_KEYS } from '../lib/communications.ts';

const root = resolve(import.meta.dirname, '..');
const source = (path) => readFileSync(resolve(root, path), 'utf8');
const base = { id: '00000000-0000-4000-8000-000000000010', event_id: '00000000-0000-4000-8000-000000000011', category: 'SYSTEM', template_key: null, payload: {}, subject: null, body: null, message_type: null, content_format: 'plain_text', is_test: false, created_at: '2026-09-13T10:00:00Z', read_at: null, is_read: false };

test('known notification routes are internal and allowlisted', () => {
  const tender = notificationDestination({ ...base, event_type: 'RECOMMENDATION_CREATED', payload: { tender_id: '00000000-0000-4000-8000-000000000012', url: 'https://evil.invalid' } });
  assert.equal(tender.href, '/dashboard/tenders/00000000-0000-4000-8000-000000000012');
  assert.equal(notificationDestination({ ...base, event_type: 'ACCOUNT_APPROVED', payload: { url: '//evil.invalid' } }).href, '/dashboard');
  assert.equal(notificationDestination({ ...base, event_type: 'ANALYSIS_COMPLETED', payload: { analysis_id: '00000000-0000-4000-8000-000000000013' } }).href, '/dashboard/my-tenders');
  assert.equal(notificationDestination({ ...base, event_type: 'DOCUMENTS_READY', payload: { tender_id: '00000000-0000-4000-8000-000000000014' } }).href, '/dashboard/tenders/00000000-0000-4000-8000-000000000014#requirements-documents');
  assert.equal(notificationDestination({ ...base, event_type: 'PRIVATE_DOCUMENTS_READY', payload: { pursuit_id: '00000000-0000-4000-8000-000000000015', organization_id: '00000000-0000-4000-8000-000000000016' } }).href, '/dashboard/pursuits/00000000-0000-4000-8000-000000000015?organization_id=00000000-0000-4000-8000-000000000016');
});

for (const [name, item] of [
  ['unknown event', { ...base, event_type: 'OBSOLETE', payload: { url: 'https://evil.invalid' } }],
  ['invalid tender id', { ...base, event_type: 'RECOMMENDATION_CREATED', payload: { tender_id: '../admin' } }],
  ['missing analysis id', { ...base, event_type: 'ANALYSIS_COMPLETED', payload: {} }],
]) test(`unsafe navigation fallback: ${name}`, () => assert.equal(notificationDestination(item), null));

for (const [filter, expected] of [
  ['ALL', { unread: undefined, category: undefined }],
  ['UNREAD', { unread: true, category: undefined }],
  ['SYSTEM', { unread: undefined, category: 'SYSTEM' }],
  ['TENDER_ALERT', { unread: undefined, category: 'TENDER_ALERT' }],
  ['ADMIN', { unread: undefined, category: 'ADMIN' }],
]) test(`cursor query remains bounded for ${filter}`, () => {
  const query = notificationQuery(filter, 'opaque');
  assert.equal(query.limit, 25); assert.equal(query.cursor, 'opaque');
  assert.equal(query.unread, expected.unread); assert.equal(query.category, expected.category);
});

for (const locale of ['en', 'uz', 'ru', 'ar']) test(`${locale} has complete notification contract`, () => {
  const messages = JSON.parse(source(`messages/${locale}/notifications.json`));
  assert.deepEqual(Object.keys(messages.templates).sort(), ['accountApproved', 'analysisCompleted', 'documentsFailed', 'documentsPartial', 'documentsReady', 'eoiDraftReady', 'privateDocumentsFailed', 'privateDocumentsPartial', 'privateDocumentsReady', 'pursuitAnalysisCompleted', 'pursuitAnalysisFailed', 'recommendationCreated']);
  assert.deepEqual(Object.keys(messages.filters).sort(), ['ADMIN', 'ALL', 'SYSTEM', 'TENDER_ALERT', 'UNREAD']);
  assert.ok(messages.fallback.title && messages.fallback.body && messages.states.mutationFailure);
});

for (const [key, local] of Object.entries(SYSTEM_TEMPLATE_KEYS)) test(`template ${key} maps to released localized key`, () => {
  assert.match(key, /^notifications\./); assert.ok(local);
  for (const locale of ['en', 'uz', 'ru', 'ar']) assert.ok(JSON.parse(source(`messages/${locale}/notifications.json`)).templates[local]);
});

const inbox = source('app/dashboard/notifications/page.tsx');
const provider = source('components/notifications/NotificationProvider.tsx');
const broadcasts = source('app/admin/broadcasts/page.tsx');
const accounts = source('app/admin/approvals/page.tsx');
const shell = source('components/shell/CustomerShell.tsx') + source('lib/customerNavigation.ts');

for (const [name, pattern, text] of [
  ['cursor inbox', /next_cursor/, inbox], ['delivery id patch', /notifications\/\$\{encodeURIComponent\(item\.id\)\}/, inbox],
  ['mark all', /notifications\/mark-all-read/, inbox], ['authoritative count', /notifications\/unread-count/, provider],
  ['bounded interval', /60_000/, provider], ['focus refresh', /addEventListener\('focus'/, provider],
  ['navigation entry', /dashboard\/notifications/, shell], ['bounded bell', /99\+/, provider],
  ['plain-text renderer', /notification-body/, inbox], ['no raw html inbox', /BidiText/, inbox],
  ['history pagination', /next_cursor/, broadcasts], ['draft create', /post<BroadcastDetail>\('\/admin\/broadcasts'/, broadcasts],
  ['draft update', /api\.patch<BroadcastDetail>/, broadcasts], ['audience preview', /audience-preview/, broadcasts],
  ['stable test id', /testRequestIds/, broadcasts], ['final confirmation', /Confirm final broadcast/, broadcasts],
  ['final send', /\/send`/, broadcasts], ['selected search limit', /limit: 20/, broadcasts],
  ['approved selected search', /approval_status: 'approved'/, broadcasts], ['no recipient mass read', /full user corpus is never loaded/, broadcasts],
  ['immutable draft gate', /mutableBroadcast/, broadcasts], ['terminal counts', /delivered_count/, broadcasts],
  ['safe errors', /communicationsError/, broadcasts], ['account drawer', /<Drawer/, accounts],
  ['account dialog', /<Dialog/, accounts], ['auth invalidation warning', /sessions and credentials stop working immediately/, accounts],
  ['read-only admin mode', /Read-only administrator view/, accounts], ['audit link', /immutable audit history/, accounts],
  ['account pagination', /PAGE_SIZE = 25/, accounts], ['account search', /query: searchQuery/, accounts],
]) test(`contract source: ${name}`, () => assert.match(text, pattern));

test('authored content never uses executable HTML rendering', () => {
  for (const text of [inbox, broadcasts]) assert.doesNotMatch(text, /dangerouslySetInnerHTML|innerHTML\s*=/);
});

test('notification provider owns exactly one interval', () => {
  assert.equal((provider.match(/setInterval/g) || []).length, 1);
  assert.equal((provider.match(/clearInterval/g) || []).length, 1);
});
